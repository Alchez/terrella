import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import * as maplibregl from "maplibre-gl";
import {
  GL_LOSS_AMNESTY_MS,
  GL_RECOVERY_ATTEMPT_LIMIT,
  GL_RECOVERY_CEILING_MS,
  GL_RECOVERY_POLL_MS,
  GL_RECOVERY_VERIFY_MS,
  GL_RESTORE_GRACE_MS,
  type MapLike,
  capLayerStates,
  capTextureBytes,
  chargeLoss,
  describeGiveUp,
  describeLoss,
  recoveryVerdict,
  formatGlLoss,
  formatGpuInitFailure,
  restoreFault,
  snapshotGlLoss,
  snapshotHasContent,
  tileCountsBySource,
  totalCapTextureBytes,
} from "./glDiagnostics";
import { CAP_POLES, capLayerId } from "./polarCaps";
import { type TileManagerLike } from "./tileCacheBudget";

/** A tile holding a DEM buffer, shaped like MapLibre's — the only shape summariseDemCache weighs. */
function demTile(assetPixels: number) {
  const stride = assetPixels + 2;
  return { dem: { data: { byteLength: stride * stride * 4 } } };
}

/** A tile manager shaped like the real one: an out-of-view cache keyed by tile id, plus in-view
 *  tiles behind a getAllTiles() method. */
function fakeTileManager(cachedTiles: number, inViewTiles: number, max: number): TileManagerLike {
  const data: Record<string, Array<{ value?: { dem?: { data?: { byteLength?: unknown } } } }>> = {};
  for (let index = 0; index < cachedTiles; index += 1) {
    data[`tile-${index}`] = [{ value: demTile(512) }];
  }
  const inView = Array.from({ length: inViewTiles }, () => demTile(512));
  return {
    _maxTileCacheSize: max,
    _outOfViewCache: { max, data },
    _inViewTiles: { getAllTiles: () => inView },
  };
}

/** A map that is fully healthy — every field restoreFault requires is present. */
function healthyMap(overrides: Partial<MapLike> = {}): MapLike {
  const canvas = { clientWidth: 2560, clientHeight: 1321, width: 5120, height: 2642 };
  return {
    getCanvas: () => canvas as unknown as HTMLCanvasElement,
    getLayer: (layerId: string) =>
      layerId === capLayerId("north")
        ? { implementation: { loadedRungPx: 8192 } }
        : layerId === capLayerId("south")
          ? { implementation: { loadedRungPx: 8192 } }
          : undefined,
    getTerrain: () => ({ source: "terrain-dem", exaggeration: 15 }),
    painter: { context: {} },
    style: {
      _layers: { relief: {}, borders: {} },
      _order: ["relief", "borders"],
      tileManagers: { "terrain-dem": fakeTileManager(605, 77, 605) },
      projection: { name: "globe" },
    },
    ...overrides,
  };
}

describe("capTextureBytes — the one VRAM term we allocate ourselves", () => {
  it("prices an 8192 cap at 341.3 MiB — RGBA WITH the mip chain the upload allocates", () => {
    // The number this replaces was 256 MiB, and the old test asserted "no mipmaps" in its own name.
    // The upload calls generateMipmap and filters LINEAR_MIPMAP_LINEAR, so the chain was always
    // resident; the guard pinned the undercount rather than catching it. A test can only protect
    // the model it encodes.
    expect(capTextureBytes(8192)).toBe(357_913_940);
    expect(capTextureBytes(8192) / (1024 * 1024)).toBeCloseTo(341.33, 2);
  });

  it("is the base level plus the whole chain below it, at every rung", () => {
    // The exact recursive identity, which the old "quarters exactly" claim never was — a finite
    // chain does not quarter cleanly, and asserting that it does is how the tail got dropped.
    for (const rung of [8192, 4096, 2048, 1024]) {
      expect(capTextureBytes(rung)).toBe(rung * rung * 4 + capTextureBytes(rung / 2));
    }
    // Still ~4x between rungs, so "the mobile rung is a quarter" survives as an approximation.
    expect(capTextureBytes(4096) / capTextureBytes(8192)).toBeCloseTo(0.25, 4);
  });

  it("puts ~683 MiB on a desktop before MapLibre allocates anything", () => {
    // Desktop budget is Infinity, so BOTH poles reach the top rung. This is the number that has to
    // appear in any VRAM attribution before an unexplained remainder can be claimed — and it is
    // 683, not the 512 quoted while the mip chain was missing from the price.
    const bytes = totalCapTextureBytes(capLayerStates(healthyMap()));
    expect(bytes / (1024 * 1024)).toBeCloseTo(682.67, 2);
  });

  it("counts an unloaded cap as zero rather than guessing a rung", () => {
    expect(
      totalCapTextureBytes([
        { layerId: "polar-cap-north", loadedRungPx: null, rungLoading: null, elevLoaded: null },
        { layerId: "polar-cap-south", loadedRungPx: 0, rungLoading: null, elevLoaded: true },
      ]),
    ).toBe(0);
  });

  it("bills nothing for a cap whose FIRST fetch is still in flight", () => {
    // The state on every cold load: no texture on the GPU, 5 MB on the wire. A `loadedRungPx ??
    // rungLoading` fallback reads naturally and is wrong — it would bill 268 MB of VRAM for bytes
    // that have not been uploaded, at exactly the moment someone is trying to attribute a stall.
    // The two poles cover both spellings of "nothing loaded", because they are not the same value.
    expect(
      totalCapTextureBytes([
        { layerId: "polar-cap-north", loadedRungPx: null, rungLoading: 8192, elevLoaded: false },
        { layerId: "polar-cap-south", loadedRungPx: 0, rungLoading: 4096, elevLoaded: false },
      ]),
    ).toBe(0);
  });
});

describe("capLayerStates", () => {
  it("reads the rung off the custom layer's implementation, for both poles", () => {
    expect(capLayerStates(healthyMap())).toEqual([
      { layerId: "polar-cap-north", loadedRungPx: 8192, rungLoading: null, elevLoaded: null },
      { layerId: "polar-cap-south", loadedRungPx: 8192, rungLoading: null, elevLoaded: null },
    ]);
  });

  it("takes its layer ids from polarCaps, so one rename moves both", () => {
    expect(capLayerStates(healthyMap()).map((cap) => cap.layerId)).toEqual(
      CAP_POLES.map(capLayerId),
    );
  });

  it("reads the in-flight rung and the elevation flag, not just what is already on the GPU", () => {
    // The distinction the panel exists for: a cap SETTLED at 4096 and a cap CLIMBING to 8192 look
    // identical on screen, and only the second is still spending main thread.
    const getLayer = () => ({
      implementation: { loadedRungPx: 4096, rungLoading: 8192, elevLoaded: false },
    });
    expect(capLayerStates(healthyMap({ getLayer }))[0]).toEqual({
      layerId: "polar-cap-north",
      loadedRungPx: 4096,
      rungLoading: 8192,
      elevLoaded: false,
    });
  });

  it.each([
    ["the layer is absent (?nocaps, or before style.load)", () => undefined],
    ["MapLibre stopped exposing implementation", () => ({ id: "polar-cap-north" })],
    ["the cap has not loaded a rung yet", () => ({ implementation: {} })],
    [
      "the fields are no longer the types we read",
      () => ({ implementation: { loadedRungPx: "8192", rungLoading: "8192", elevLoaded: 1 } }),
    ],
  ])("reports null, not a fabricated reading, when %s", (_case, getLayer) => {
    const states = capLayerStates(healthyMap({ getLayer }));
    for (const state of states) {
      expect(state.loadedRungPx).toBeNull();
      expect(state.rungLoading).toBeNull();
      // `1` is truthy — a Boolean() coercion here would report a wrong-typed field as loaded.
      expect(state.elevLoaded).toBeNull();
    }
    expect(totalCapTextureBytes(states)).toBe(0);
  });

  it("survives a map with no getLayer at all", () => {
    expect(capLayerStates({})).toHaveLength(2);
    expect(capLayerStates(undefined)[0].loadedRungPx).toBeNull();
  });
});

describe("tileCountsBySource — every source, not just the one we suspected", () => {
  it("reports each source's occupancy, sorted so two snapshots can be diffed", () => {
    const counts = tileCountsBySource({
      relief: fakeTileManager(121, 40, 385),
      "terrain-dem": fakeTileManager(605, 77, 605),
    });
    expect(counts.map((entry) => entry.source)).toEqual(["relief", "terrain-dem"]);
    expect(counts[1].counts).toMatchObject({ cachedTiles: 605, inViewTiles: 77, maxSlots: 605 });
  });

  it("does not stop at the terrain source — the relief cache holds megabyte tiles too", () => {
    // The whole point: a snapshot that reported only the source the hypothesis named would
    // confirm that hypothesis and be blind to everything else.
    const counts = tileCountsBySource({ relief: fakeTileManager(121, 40, 385) });
    expect(counts[0].counts?.cachedTiles).toBe(121);
  });

  it.each([
    ["_outOfViewCache is gone", { _inViewTiles: { getAllTiles: () => [] } }],
    ["max is no longer a number", { _outOfViewCache: { max: "605", data: {} } }],
    ["_inViewTiles lost getAllTiles", { _outOfViewCache: { max: 605, data: {} } }],
  ])("reports null — never zero — when %s", (_case, broken) => {
    // Zero tiles and an unreadable cache are different facts, and only the second means the
    // instrument is broken. Collapsing them is how a dead probe reads as a healthy cache.
    const counts = tileCountsBySource({ "terrain-dem": broken as TileManagerLike });
    expect(counts[0].counts).toBeNull();
  });

  it("returns nothing rather than throwing when the style has no sources yet", () => {
    expect(tileCountsBySource(undefined)).toEqual([]);
    expect(tileCountsBySource({})).toEqual([]);
  });
});

describe("snapshotGlLoss — the state that is unreadable a moment later", () => {
  const snapshot = snapshotGlLoss(healthyMap(), {
    phase: "lost",
    msSinceLoad: 187_400,
    devicePixelRatio: 2,
    statusMessage: "GPU process exited",
  });

  it("records both canvas sizes, because the buffer is what costs memory", () => {
    expect(snapshot).toMatchObject({
      cssWidth: 2560,
      cssHeight: 1321,
      bufferWidth: 5120,
      bufferHeight: 2642,
      devicePixelRatio: 2,
    });
  });

  it("records the browser's own reason when it gives one", () => {
    expect(snapshot.statusMessage).toBe("GPU process exited");
    expect(snapshotGlLoss(healthyMap(), {
      phase: "lost",
      msSinceLoad: 0,
      devicePixelRatio: 1,
    }).statusMessage).toBeNull();
  });

  it("records terrain, every source, and the cap bytes together", () => {
    expect(snapshot.terrainOn).toBe(true);
    expect(snapshot.sources.map((entry) => entry.source)).toEqual(["terrain-dem"]);
    expect(snapshot.capTextureBytes / (1024 * 1024)).toBeCloseTo(682.67, 2);
  });

  it("does not throw on a map that is already in pieces", () => {
    // This runs on the crash path. A snapshot that throws costs us the one reading that mattered.
    expect(() => snapshotGlLoss({}, { phase: "lost", msSinceLoad: 0, devicePixelRatio: 1 }))
      .not.toThrow();
    expect(() => snapshotGlLoss(undefined, { phase: "lost", msSinceLoad: 0, devicePixelRatio: 1 }))
      .not.toThrow();
  });
});

describe("formatGlLoss", () => {
  const line = formatGlLoss(
    snapshotGlLoss(healthyMap(), {
      phase: "lost",
      msSinceLoad: 187_400,
      devicePixelRatio: 2,
      statusMessage: "GPU process exited",
    }),
  );

  it("carries the facts a scrollback reader needs, in one greppable line", () => {
    expect(line).toContain("[gl] context lost at 187.4s");
    expect(line).toContain("2560x1321 css / 5120x2642 buffer @ DPR 2");
    expect(line).toContain("terrain on");
    expect(line).toContain("caps north 8192/south 8192 = 683 MB");
    expect(line).toContain("terrain-dem 605/605 slots");
    expect(line).toContain("browser said: GPU process exited");
  });

  it("says a source is unreadable instead of printing a confident zero", () => {
    const broken = snapshotGlLoss(
      healthyMap({ style: { tileManagers: { "terrain-dem": {} }, projection: {} } }),
      { phase: "lost", msSinceLoad: 0, devicePixelRatio: 1 },
    );
    expect(formatGlLoss(broken)).toContain("terrain-dem unreadable");
  });

  it("omits the browser reason when there is none, rather than printing an empty one", () => {
    const quiet = formatGlLoss(
      snapshotGlLoss(healthyMap(), { phase: "lost", msSinceLoad: 0, devicePixelRatio: 1 }),
    );
    expect(quiet).not.toContain("browser said");
  });

  it("shows a cap mid-climb as BOTH rungs, and a flat cap as flat", () => {
    // A settled 4096 and a 4096 climbing to 8192 are the same picture on screen; only the second
    // is still spending main thread, so only the second explains a stall in the same screenshot.
    const climbing = formatGlLoss(
      snapshotGlLoss(
        healthyMap({
          getLayer: () => ({
            implementation: { loadedRungPx: 4096, rungLoading: 8192, elevLoaded: false },
          }),
        }),
        { phase: "sampled", msSinceLoad: 0, devicePixelRatio: 1 },
      ),
    );
    expect(climbing).toContain("north 4096→8192 loading (flat)");
    // The bytes stay billed to what is actually uploaded — 2 x 4096² x 4 = 128 MiB, not 8192's.
    expect(climbing).toContain("= 171 MB");
  });

  it("stays silent about a settled cap, so the climb annotation means something", () => {
    // If every reading carried an arrow the arrow would be noise. `caps north 8192/south 8192` is
    // the quiet state and must render exactly as it did before this field existed.
    expect(line).toContain("caps north 8192/south 8192 = 683 MB");
    expect(line).not.toContain("loading");
    expect(line).not.toContain("(flat)");
  });
});

describe("describeLoss — the loss handler cannot read the style, and must not pretend it can", () => {
  // Measured live: MapLibre registers its own canvas listener in the Map constructor, so by the
  // time our webglcontextlost handler runs the style is gone. The first build logged
  // "no sources · caps none" on a map that had five sources and both caps resident 100 ms earlier.
  const healthy = snapshotGlLoss(healthyMap(), {
    phase: "sampled",
    msSinceLoad: 91_200,
    devicePixelRatio: 2,
  });
  const tornDown = snapshotGlLoss(healthyMap({ style: { projection: {} }, getLayer: () => undefined }), {
    phase: "lost",
    msSinceLoad: 91_800,
    devicePixelRatio: 2,
  });

  it("knows an empty read from a real one", () => {
    expect(snapshotHasContent(healthy)).toBe(true);
    expect(snapshotHasContent(tornDown)).toBe(false);
  });

  it("falls back to the healthy sample and says how old it is", () => {
    const line = describeLoss(tornDown, healthy);
    expect(line).toContain("terrain-dem 605/605 slots");
    expect(line).toContain("caps north 8192/south 8192 = 683 MB");
    expect(line).toContain("READ 0.6s EARLIER");
    // The LOSS's clock and phase, not the sample's — a loss report labelled "context sampled"
    // reads as a different event entirely, and someone would reason from it later.
    expect(line).toContain("[gl] context lost at 91.8s");
    expect(line).not.toContain("context sampled");
  });

  it("never presents a stale reading as a live one", () => {
    // The failure this module exists to make impossible: numbers that look live and are not.
    expect(describeLoss(tornDown, healthy)).toContain("already torn the style down");
    expect(describeLoss(healthy, null)).not.toContain("EARLIER");
  });

  it("uses the loss-time read when it actually has content", () => {
    const line = describeLoss(healthy, null);
    expect(line).toBe(formatGlLoss(healthy));
  });

  it("says there is nothing rather than printing a confident empty snapshot", () => {
    expect(describeLoss(tornDown, null)).toContain("no earlier sample");
  });
});

describe("restoreFault — 'restored' is not 'recovered'", () => {
  it("passes a map that actually came back", () => {
    expect(restoreFault(healthyMap())).toBeNull();
  });

  it("catches the zombie the 2K freeze produced: context back, style in pieces", () => {
    // The exact state measured after the GPU process crash-looped — isContextLost() read FALSE,
    // which is why every check we had passed while the map was dead.
    const zombie = healthyMap({
      style: { _layers: {}, _order: [], tileManagers: {}, projection: undefined },
    });
    expect(restoreFault(zombie)).toContain("no projection");
  });

  it.each([
    ["the style was never rebuilt", { style: undefined }, "never rebuilt the style"],
    [
      "the projection is gone",
      { style: { ...healthyMap().style, projection: undefined } },
      "no projection",
    ],
    ["the painter is gone", { painter: undefined }, "painter was never rebuilt"],
    [
      "the style came back with no layers",
      { style: { ...healthyMap().style, _layers: {}, _order: [] } },
      "came back empty",
    ],
    [
      "the style came back with no sources",
      { style: { ...healthyMap().style, tileManagers: {} } },
      "came back empty",
    ],
  ])("faults when %s", (_case, overrides, expected) => {
    const fault = restoreFault(healthyMap(overrides as Partial<MapLike>));
    expect(fault).not.toBeNull();
    expect(fault).toContain(expected);
  });

  it("names the counts, so the log says how empty rather than just 'empty'", () => {
    const fault = restoreFault(
      healthyMap({ style: { ...healthyMap().style, _layers: {}, _order: [] } }),
    );
    expect(fault).toContain("1 sources, 0 layers, 0 in draw order");
  });

  it("reports the most fundamental failure first", () => {
    // A map missing everything must not report the layer count — that would send a reader chasing
    // an empty style when the style object itself never came back.
    expect(restoreFault({})).toContain("never rebuilt the style");
    expect(restoreFault(undefined)).toBe("no map");
    // Reports the OBSERVATION, never a cause it did not check. Only the recovery poll knows a
    // restore fired, and it says so in its own log line; the perf report calls this on every
    // export, where "the context came back" would be an unfounded claim about a healthy-looking
    // phone. Caught by exporting from a phone whose style had gone for reasons never established.
    for (const fault of [restoreFault({}), restoreFault(undefined)]) {
      expect(fault).not.toContain("context came back");
    }
  });
});

describe("formatGpuInitFailure — MapLibre names what we used to infer from a timeout", () => {
  it("quotes the browser's reason when there is one", () => {
    expect(formatGpuInitFailure({ statusMessage: "GPU process isn't usable" })).toContain(
      ": GPU process isn't usable",
    );
  });

  it("says so plainly when the browser gives no reason", () => {
    expect(formatGpuInitFailure({})).toContain("browser gave no reason");
    expect(formatGpuInitFailure({ statusMessage: null })).toContain("browser gave no reason");
  });

  it("distinguishes itself from a recoverable loss in the message", () => {
    expect(formatGpuInitFailure({})).toContain("not a recoverable loss");
  });
});

describe("canary — the MapLibre surface this module depends on", () => {
  it("GPUInitializationError is still a constructable VALUE, not just a type", () => {
    // The instanceof branch in globe.astro fails SILENTLY if this becomes type-only or is renamed:
    // the check simply never matches, and the GPU-dead case goes back to being inferred from a
    // four-second timeout with no error in the console.
    expect(typeof maplibregl.GPUInitializationError).toBe("function");
    expect(maplibregl.GPUInitializationError.prototype).toBeInstanceOf(Error);
  });

  it("carries the fields the message is built from", () => {
    const error = new maplibregl.GPUInitializationError({ antialias: true }, null);
    expect(error).toBeInstanceOf(Error);
    expect(error.statusMessage).toBeNull();
    expect(error.requestedAttributes).toEqual({ antialias: true });
    expect(formatGpuInitFailure(error)).toContain("browser gave no reason");
  });

  it("still fires webglcontextlost with the original WebGLContextEvent", () => {
    // statusMessage is read off event.originalEvent; if MapLibre stops forwarding it the snapshot
    // silently loses the browser's own explanation.
    const declarations = readFileSync(
      new URL("../../node_modules/maplibre-gl/dist/maplibre-gl.d.ts", import.meta.url),
      "utf8",
    );
    expect(declarations).toMatch(/webglcontextlost: MapContextEvent;/);
    expect(declarations).toMatch(/class MapContextEvent extends MapLibreEvent<WebGLContextEvent>/);
    expect(declarations).toMatch(/originalEvent: WebGLContextEvent;/);
  });

  it("still exposes the style fields the recovery check reads", () => {
    const declarations = readFileSync(
      new URL("../../node_modules/maplibre-gl/dist/maplibre-gl.d.ts", import.meta.url),
      "utf8",
    );
    // If any of these move, restoreFault would report a fault on a HEALTHY map — a false alarm
    // that puts a "could not recover" notice over a working globe.
    expect(declarations).toMatch(/projection: Projection \| undefined;/);
    expect(declarations).toMatch(/_order: string\[\];/);
    expect(declarations).toMatch(/implementation: CustomLayerInterface;/);
    expect(declarations).toMatch(/getPixelRatio\(\): number;/);
  });

  // Three comments in globe.astro cite LINE NUMBERS in the shipped bundle, and they are load-
  // bearing: the whole reason the DEM bound, the polar caps and the recovery watch are driven
  // from a healthy `idle` rather than from `webglcontextrestored` is the ORDER of these five
  // statements. A version bump moves every one of them, and a citation that has silently drifted
  // is worse than none — it reads as evidence. This pins the order, and prints the real numbers
  // when it breaks so the comments can be corrected rather than deleted.
  it("still restores the context in the order those comments describe", () => {
    const bundle = readFileSync(
      new URL("../../node_modules/maplibre-gl/dist/maplibre-gl-dev.mjs", import.meta.url),
      "utf8",
    ).split("\n");
    const lineOf = (needle: string) => {
      const index = bundle.findIndex((line) => line.includes(needle));
      expect(index, `MapLibre no longer contains ${needle}`).toBeGreaterThan(-1);
      return index + 1; // findIndex is 0-based; comments cite 1-based editor lines
    };
    const contextRestored = lineOf("this._contextRestored = (event) => {");
    const setStyle = lineOf("if (this._lostContextStyle.style) this.setStyle(");
    const setupPainter = bundle.findIndex(
      (line, index) => index > contextRestored && line.includes("this._setupPainter();"),
    ) + 1;
    const resize = bundle.findIndex(
      (line, index) => index > setupPainter && line.trim() === "this.resize();",
    ) + 1;
    const fireRestored = lineOf('this.fire(new MapContextEvent("webglcontextrestored"');

    const cited = { setStyle: 22594, setupPainter: 22600, resize: 22602, fireRestored: 22605 };
    const actual = { setStyle, setupPainter, resize, fireRestored };
    expect(
      actual,
      `globe.astro cites these bundle lines; MapLibre moved them. Update the comments beside ` +
        `reassertTerrainBound, reassertPolarCaps and startRecoveryWatch to ` +
        `${JSON.stringify(actual)}.`,
    ).toEqual(cited);

    // The ORDER is the claim those comments actually rest on, and it must hold even once the
    // numbers move: setStyle (which fires `style.load`) runs BEFORE _setupPainter, so a cap or a
    // custom layer added from `style.load` binds to the pre-restore context; and resize() — which
    // is what throws on our hash-driven unproject — runs BEFORE the restored event is fired, which
    // is why that event may never arrive.
    expect(setStyle).toBeLessThan(setupPainter);
    expect(setupPainter).toBeLessThan(resize);
    expect(resize).toBeLessThan(fireRestored);
  });
});

describe("globe.astro wires the diagnostics rather than re-stating them", () => {
  const globe = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");

  const restoredHandler = globe
    .match(/map\.on\("webglcontextrestored"[\s\S]*?\n  \}\);/)?.[0];
  const lostHandler = globe.match(/map\.on\("webglcontextlost"[\s\S]*?\n  \}\);/)?.[0];

  const idleSampler = globe.match(/map\.on\("idle", \(\) => \{[\s\S]*?\n  \}\);/g)
    ?.find((block) => block.includes("lastHealthyGlState"));

  const sampledGlState = globe.match(/const sampledGlState = [\s\S]*?\n  \};/)?.[0];

  // The verdict logic lives here now rather than in the restore handler, because the restore event
  // is not guaranteed to fire (see the comment on the loss handler). Both entry points share it.
  const recoveryWatch = globe.match(/const startRecoveryWatch = [\s\S]*?\n  \};/)?.[0];

  // Measured: MapLibre's _contextRestored calls this.resize() BEFORE it fires
  // "webglcontextrestored", and with hash:"map" + terrain that resize reaches its own Hash plugin
  // -> unproject -> the terrain depth pass and THROWS, so the event never arrives. Recovery keyed
  // to that event is therefore a coin toss, and these guards pin the state-driven wiring that
  // replaced it. All three defects it caused (uncapped DEM cache, black polar disc, a stuck
  // "could not recover" notice) reproduce from one WEBGL_lose_context cycle if this regresses.
  it("starts the recovery watch from the LOSS, because the restore event may never fire", () => {
    expect(lostHandler, "loss handler must start the watch itself").toContain(
      "startRecoveryWatch(",
    );
  });

  it("puts back what a restore silently drops, once the map reads healthy", () => {
    const watch = globe.match(/const startRecoveryWatch = [\s\S]*?\n  \};/)?.[0];
    expect(watch, "startRecoveryWatch must exist").toBeTruthy();
    expect(watch).toContain("reassertTerrainBound()");
    expect(watch).toContain("reassertPolarCaps()");
  });

  it("bounds recovery by recurrence rather than trying to read a cause that does not exist", () => {
    expect(lostHandler).toContain("chargeLoss(");
    expect(lostHandler).toContain("recoveryVerdict(");
    expect(lostHandler).toContain("describeGiveUp(");
  });

  it("caps the DEM cache AFTER setTerrain, which is what builds the manager it lands on", () => {
    const styleLoad = globe.match(/map\.on\("style\.load", \(\) => \{[\s\S]*?\n    \}\);/g)?.find(
      (block) => block.includes("applyCacheCap()"),
    );
    expect(styleLoad, "the terrain style.load handler must exist").toBeTruthy();
    const terrainAt = styleLoad!.indexOf("map.setTerrain(");
    const capAt = styleLoad!.indexOf("applyCacheCap()");
    expect(terrainAt).toBeGreaterThan(-1);
    expect(capAt).toBeGreaterThan(terrainAt);
  });

  it("keeps the timing policy in the module, not as literals in the page", () => {
    for (const name of [
      "GL_RESTORE_GRACE_MS",
      "GL_RECOVERY_VERIFY_MS",
      "GL_RECOVERY_POLL_MS",
      "GL_RECOVERY_CEILING_MS",
    ]) {
      expect(globe, `${name} must be imported, not redeclared`).not.toMatch(
        new RegExp(`const ${name}\\s*=`),
      );
      expect(globe).toContain(name);
    }
  });

  it("NEVER hides the notice on the restore event alone — this is the whole bug", () => {
    // The regression that made a dead globe display as a working one. If a future edit puts an
    // unconditional setAttribute("hidden") back in this handler, it must fail here.
    expect(recoveryWatch, "the recovery watch must exist").toBeTruthy();
    expect(recoveryWatch).toContain("restoreFault");
    const hides = recoveryWatch!.match(/setAttribute\("hidden"/g) ?? [];
    expect(hides, "exactly one hide, and it must be behind the fault check").toHaveLength(1);
    const beforeHide = recoveryWatch!.slice(0, recoveryWatch!.indexOf('setAttribute("hidden"'));
    expect(beforeHide).toContain("fault === null");
    // Stronger than before: the restore handler may not touch the notice AT ALL. It fires on an
    // event that says the browser returned a context, which is not evidence the map came back —
    // and on a measured build it does not fire at all.
    expect(restoredHandler, "the restore handler must exist").toBeTruthy();
    expect(restoredHandler).not.toContain('setAttribute("hidden"');
  });

  it("shows the notice when the deadline passes with the map still broken", () => {
    expect(recoveryWatch).toContain("removeAttribute(\"hidden\")");
    expect(recoveryWatch).toMatch(/console\.error/);
  });

  it("keeps watching past its own verdict, so a late recovery retracts the notice", () => {
    // A measured loss recovered at ~6s, past the deadline. The first build gave up at the deadline
    // and left "could not recover" over a working globe.
    expect(recoveryWatch).toContain("GL_RECOVERY_CEILING_MS");
    // The fault path must NOT stop the poll — only recovery or the ceiling may.
    const faultBranch = recoveryWatch!.slice(recoveryWatch!.indexOf("faultReported = true"));
    const untilCeiling = faultBranch.slice(0, faultBranch.indexOf("GL_RECOVERY_CEILING_MS"));
    expect(untilCeiling, "reporting the fault must not end the watch").not.toContain(
      "clearInterval",
    );
  });

  it("samples the state on idle, because the loss handler reads an already-torn-down style", () => {
    // The defect this replaced: MapLibre tears the style down before our listener runs, so the
    // loss-time read is always empty. Sampling on idle is the only place the numbers exist.
    expect(idleSampler, "an idle handler must maintain lastHealthyGlState").toBeTruthy();
    expect(idleSampler).toContain("sampledGlState(");
  });

  it("rejects an empty read at the single place a routine sample is taken", () => {
    // These two assertions used to match `if (snapshotHasContent(snapshot)) lastHealthyGlState =`
    // inline in the idle handler. The rejection moved into one shared helper when export gained a
    // second caller, so the guard follows the invariant rather than the old shape of the code.
    expect(sampledGlState, "sampledGlState must exist").toBeTruthy();
    expect(sampledGlState).toContain("snapshotHasContent");
    expect(sampledGlState).toMatch(/\?\s*snapshot\s*:\s*null/);
  });

  it("never overwrites the healthy sample with an empty read", () => {
    // Without the fallback, one idle tick during a teardown erases the only reading we had.
    expect(idleSampler).toMatch(/lastHealthyGlState = sampledGlState\(\) \?\? lastHealthyGlState/);
  });

  it("takes a FRESH sample on export and the stale one on the panel tick", () => {
    // The asymmetry is the fix and the constraint at once. Export is one user-initiated moment, so
    // it can afford a current reading — the first production phone capture carried a 25.7 s stale
    // GL block describing the calm before the panning rather than the panning. The 300 ms panel
    // tick cannot: a fresh read walks the covering set and every tile manager, and doing per-tick
    // probe work is precisely how this instrument previously killed the map it was measuring.
    expect(globe).toMatch(/gl: \(sampleGlNow \? sampledGlState\(\) : null\) \?\? lastHealthyGlState/);
    // Both call sites asserted literally rather than by matching a span. A span match here has to
    // reach past a comment block to its terminator, so it needs a bound, and a bound that is wrong
    // fails as "not findable" — which reads as a missing feature rather than a bad matcher. These
    // two strings ARE the asymmetry, so pin them and nothing else.
    expect(globe).toMatch(
      /buildReport: \(timing, panel\) => composeReport\(timing, panel, \{ sampleGlNow: true \}\)/,
    );
    expect(globe).toContain("perfReportLines(composeReport(timing, { expanded: true }))");
    // Exactly one opt-in, and the line above proved it is the export's. A second would ship
    // per-tick sampling while both assertions above kept passing.
    expect(globe.match(/sampleGlNow: true/g)).toHaveLength(1);
  });

  it("reports the loss through describeLoss, so a stale reading is always labelled", () => {
    expect(lostHandler, "the loss handler must exist").toBeTruthy();
    expect(lostHandler).toContain("describeLoss");
    expect(lostHandler).toContain("lastHealthyGlState");
    // The browser's own reason must reach the snapshot; dropping it loses the only external
    // evidence of WHY, and nothing else in the log would show it had gone missing.
    expect(lostHandler).toContain("originalEvent");
  });

  it("reads the map's pixel ratio, not the display's", () => {
    // The degradation ladder lowers the map's ratio; window.devicePixelRatio would keep reporting
    // a number we stopped rendering at, in exactly the low-memory situation this runs in.
    // Matched on the ASSIGNMENT, not the word: the comment beside it names window.devicePixelRatio
    // to explain why it is wrong, and a substring guard would fail on its own documentation.
    const reader = globe.match(/const readGlState = [\s\S]*?\n    \}\);/)?.[0];
    expect(reader, "readGlState must exist").toBeTruthy();
    expect(reader).toContain("devicePixelRatio: map.getPixelRatio()");
    expect(reader).not.toMatch(/devicePixelRatio:\s*window\.devicePixelRatio/);
  });

  it("branches on GPUInitializationError and shows the notice without waiting", () => {
    const errorHandler = globe.match(/map\.on\("error"[\s\S]*?\n  \}\);/)?.[0];
    expect(errorHandler).toContain("maplibregl.GPUInitializationError");
    expect(errorHandler).toContain("formatGpuInitFailure");
    expect(errorHandler).toContain("removeAttribute(\"hidden\")");
  });

  it("cancels a pending recovery poll on every path that supersedes it", () => {
    // Two timers race: the grace watchdog and the recovery poll. A path that leaves one running
    // can flip the notice back after another path has settled it.
    expect(lostHandler).toContain("clearInterval(recoveryPoll)");
    // The watch supersedes any earlier one, so it clears before arming; the restore handler no
    // longer polls itself, it just cancels the grace watchdog and re-enters the watch.
    expect(recoveryWatch).toContain("clearInterval(recoveryPoll)");
    expect(restoredHandler).toContain("clearTimeout(restoreWatchdog)");
    expect(restoredHandler).toContain("startRecoveryWatch(");
  });

  it("declares the notice before any handler that touches it", () => {
    expect(globe.indexOf("const glLostNotice")).toBeLessThan(globe.indexOf('map.on("error"'));
  });
});

describe("the timing policy", () => {
  it("gives a recoverable loss time to heal before crying wolf", () => {
    expect(GL_RESTORE_GRACE_MS).toBeGreaterThanOrEqual(2000);
  });

  it("polls often enough to retract a wrongly-shown notice quickly", () => {
    expect(GL_RECOVERY_POLL_MS).toBeLessThan(GL_RECOVERY_VERIFY_MS);
    expect(GL_RECOVERY_VERIFY_MS / GL_RECOVERY_POLL_MS).toBeGreaterThanOrEqual(4);
  });

  it("watches well past the ~6s recovery that was actually measured", () => {
    expect(GL_RECOVERY_CEILING_MS).toBeGreaterThan(GL_RECOVERY_VERIFY_MS);
    expect(GL_RECOVERY_CEILING_MS).toBeGreaterThanOrEqual(10_000);
  });
});

describe("the recovery budget — conditioned on recurrence, because no cause is available", () => {
  it("recovers from a first loss, which is the ordinary transient one", () => {
    expect(recoveryVerdict(chargeLoss([], 1000))).toBe("recover");
  });

  it("still gives a second loss the benefit of the doubt", () => {
    const charged = chargeLoss(chargeLoss([], 1000), 20_000);
    expect(charged).toHaveLength(2);
    expect(recoveryVerdict(charged)).toBe("recover");
  });

  it("stops at the third loss in the window — the incident logged four", () => {
    let charged = chargeLoss([], 1000);
    charged = chargeLoss(charged, 20_000);
    charged = chargeLoss(charged, 40_000);
    expect(recoveryVerdict(charged)).toBe("give-up");
  });

  it("forgives losses older than the amnesty, so a long-lived tab is not sentenced by its morning", () => {
    const morning = chargeLoss(chargeLoss([], 1000), 20_000);
    const afternoon = chargeLoss(morning, 20_000 + GL_LOSS_AMNESTY_MS + 1);
    expect(afternoon).toHaveLength(1);
    expect(recoveryVerdict(afternoon)).toBe("recover");
  });

  it("keeps a loss that lands exactly on the amnesty boundary", () => {
    const charged = chargeLoss(chargeLoss([], 1000), 1000 + GL_LOSS_AMNESTY_MS);
    expect(charged).toHaveLength(2);
  });

  it("does not mutate the array it is handed", () => {
    const previous = Object.freeze([1000]) as readonly number[];
    expect(() => chargeLoss(previous, 2000)).not.toThrow();
    expect(previous).toHaveLength(1);
  });

  it("names the count and the window, so the log reads as a policy and not a crash", () => {
    const sentence = describeGiveUp([1, 2, 3]);
    expect(sentence).toContain("3 context losses");
    expect(sentence).toContain(`${GL_LOSS_AMNESTY_MS / 60_000} min`);
    expect(sentence).toMatch(/reload/i);
  });

  it("the limit is a budget, not a switch that disables recovery", () => {
    expect(GL_RECOVERY_ATTEMPT_LIMIT).toBeGreaterThanOrEqual(1);
  });
});

describe("the snapshot names its library and what the camera needed", () => {
  const snapshot = snapshotGlLoss(healthyMap(), {
    phase: "lost",
    msSinceLoad: 18_400,
    devicePixelRatio: 1,
    libraryVersion: "6.0.0",
    coveringTiles: 52,
  });

  it("records the MapLibre version, because every canary here is version-sensitive", () => {
    expect(snapshot.libraryVersion).toBe("6.0.0");
    expect(formatGlLoss(snapshot)).toContain("maplibre 6.0.0");
  });

  it("records the covering count beside the realized in-view count", () => {
    // The gap between them IS terrain's _addTerrainIdealTiles addition, which coveringTiles
    // cannot include — reporting both is what keeps that a visible fact rather than a silent one.
    expect(snapshot.coveringTiles).toBe(52);
    const line = formatGlLoss(snapshot);
    expect(line).toContain("camera needs 52 tiles");
    expect(line).toContain("+77 view");
  });

  it("omits both cleanly when they were not supplied", () => {
    const bare = snapshotGlLoss(healthyMap(), {
      phase: "lost",
      msSinceLoad: 0,
      devicePixelRatio: 1,
    });
    expect(bare.libraryVersion).toBeNull();
    expect(bare.coveringTiles).toBeNull();
    expect(formatGlLoss(bare)).not.toContain("maplibre");
    expect(formatGlLoss(bare)).not.toContain("camera needs");
  });

  it("prints 'needs 0' rather than dropping the field when a camera covers nothing", () => {
    const empty = snapshotGlLoss(healthyMap(), {
      phase: "lost",
      msSinceLoad: 0,
      devicePixelRatio: 1,
      coveringTiles: 0,
    });
    expect(formatGlLoss(empty)).toContain("camera needs 0 tiles");
  });
});

describe("globe.astro feeds the snapshot the version and the covering count", () => {
  const globe = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");
  const reader = globe.match(/const readGlState = [\s\S]*?\n    \}\);/)?.[0];

  it("passes MapLibre's own getVersion, not a hard-coded string", () => {
    expect(reader).toContain("libraryVersion: maplibregl.getVersion()");
  });

  it("passes the covering count through the hoisted closure", () => {
    // Hoisted because `?terrain=off` never enters the terrain block, and null is the honest
    // answer there — a default of 0 would read as "this camera needs nothing".
    expect(reader).toContain("coveringTiles: coveringTileCount()");
    expect(globe).toMatch(/let coveringTileCount: \(\) => number \| null = \(\) => null;/);
  });

  it("computes it from the DECLARED tile size, so ?terrain=Npx is honoured", () => {
    expect(globe).toMatch(
      /coveringTileCount = \(\) =>\s*terrainCoveringTileCount\(map, declaredTileSize,/,
    );
  });
});
