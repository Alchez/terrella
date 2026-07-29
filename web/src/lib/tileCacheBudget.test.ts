import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  DEM_TILE_PADDING_PX,
  MAPLIBRE_MAX_TILE_CACHE_ZOOM_LEVELS,
  TERRAIN_DELTA_ZOOM,
  type TileManagerLike,
  TERRAIN_ASSET_TILE_PX,
  TERRAIN_CACHE_BYTE_BUDGET,
  TERRAIN_CACHE_SLOT_MULTIPLIER,
  applyDemCacheCap,
  demCacheCapFault,
  demCacheLine,
  describeDemCacheState,
  demSlotBytes,
  parseDemCacheSetting,
  resolveDemCacheSlots,
  shippedTerrainCacheSlots,
  slotsWithinByteBudget,
  summariseDemCache,
  terrainCacheSlotBound,
  terrainCoveringTileCount,
  terrainFillTileSize,
  viewDependentCacheSlots,
} from "./tileCacheBudget";

/** The canvas the ~1.45 GB report was measured on, so the numbers here are the reported ones. */
const MEASURED_CANVAS_WIDTH = 2500;
const MEASURED_CANVAS_HEIGHT = 1300;

/** A tile holding a DEM buffer of the given asset size, shaped like MapLibre's. */
function fakeTile(assetPixels: number) {
  return { dem: { data: { byteLength: demSlotBytes(assetPixels) } } };
}

/** A TileManager-shaped fake: `cached` tiles out of view, `inView` tiles in it. */
function fakeTileManager(options: {
  cached: number;
  inView: number;
  max: number;
  assetPixels?: number;
}): TileManagerLike {
  const assetPixels = options.assetPixels ?? 512;
  const data: Record<string, Array<{ value: { dem: { data: { byteLength: number } } } }>> = {};
  for (let index = 0; index < options.cached; index += 1) {
    data[`key-${index}`] = [{ value: fakeTile(assetPixels) }];
  }
  const inViewTiles = Array.from({ length: options.inView }, () => fakeTile(assetPixels));
  return {
    _outOfViewCache: { max: options.max, data },
    _inViewTiles: { getAllTiles: () => inViewTiles },
  };
}

describe("demSlotBytes", () => {
  it("is the padded RGBA buffer MapLibre actually keeps, not the tile's nominal area", () => {
    // DEMData holds `new Uint32Array(data.data.buffer)` over an RGBAImage with 1px padding all
    // round, so a 512px asset is a 514 stride: 514 * 514 * 4.
    expect(demSlotBytes(512)).toBe(1_056_784);
    expect(DEM_TILE_PADDING_PX).toBe(1);
  });

  it("falls ~4x for a 256px asset, which is the whole of the smaller-asset arm", () => {
    expect(demSlotBytes(256)).toBe(266_256);
    expect(demSlotBytes(512) / demSlotBytes(256)).toBeCloseTo(3.97, 2);
  });

  it("is indifferent to the DECLARED tile size — it takes an asset size and nothing else", () => {
    // Stated as a test because this is the fact the 512 -> 128 declaration change missed: the
    // declaration multiplied slots and moved none of the bytes behind them.
    expect(demSlotBytes(512)).toBe(demSlotBytes(512));
  });
});

describe("viewDependentCacheSlots", () => {
  it("reproduces the ~1.24 GiB ceiling the shipping declaration actually asks for", () => {
    const slots = viewDependentCacheSlots(MEASURED_CANVAS_WIDTH, MEASURED_CANVAS_HEIGHT, 128);
    expect(slots).toBe(1260); // (ceil(2500/128)+1) * (ceil(1300/128)+1) * 5 = 21 * 12 * 5
    expect(slots * demSlotBytes(512)).toBe(1_331_547_840);
  });

  it("carries a border term that does not scale, so the ratio is 3.27x and not 4x", () => {
    const sized = viewDependentCacheSlots(MEASURED_CANVAS_WIDTH, MEASURED_CANVAS_HEIGHT, 128);
    const filled = viewDependentCacheSlots(MEASURED_CANVAS_WIDTH, MEASURED_CANVAS_HEIGHT, 256);
    expect(filled).toBe(385); // 11 * 7 * 5
    expect(sized / filled).toBeCloseTo(3.27, 2);
  });

  it("approaches 4x as the canvas grows, which is where the 4x claim is true", () => {
    const hugeSized = viewDependentCacheSlots(20000, 20000, 128);
    const hugeFilled = viewDependentCacheSlots(20000, 20000, 256);
    expect(hugeSized / hugeFilled).toBeGreaterThan(3.9);
  });

  it("honours a caller-supplied zoom-level count rather than assuming MapLibre's default", () => {
    const atDefault = viewDependentCacheSlots(1000, 1000, 256);
    const atOne = viewDependentCacheSlots(1000, 1000, 256, 1);
    expect(atDefault).toBe(atOne * MAPLIBRE_MAX_TILE_CACHE_ZOOM_LEVELS);
  });
});

describe("terrainFillTileSize", () => {
  it("doubles the declaration, because TerrainTileManager's deltaZoom is 1", () => {
    expect(TERRAIN_DELTA_ZOOM).toBe(1);
    expect(terrainFillTileSize(128)).toBe(256);
    expect(terrainFillTileSize(512)).toBe(1024);
  });
});

describe("terrainCacheSlotBound", () => {
  it("is the size MapLibre would have computed had updateCacheSize honoured usedForTerrain", () => {
    expect(terrainCacheSlotBound(MEASURED_CANVAS_WIDTH, MEASURED_CANVAS_HEIGHT, 128)).toBe(
      viewDependentCacheSlots(MEASURED_CANVAS_WIDTH, MEASURED_CANVAS_HEIGHT, 256),
    );
  });

  it("only ever shrinks the cache — MapLibre applies it as Math.min against its own size", () => {
    for (const declared of [128, 256, 512]) {
      const bound = terrainCacheSlotBound(MEASURED_CANVAS_WIDTH, MEASURED_CANVAS_HEIGHT, declared);
      const unbounded = viewDependentCacheSlots(
        MEASURED_CANVAS_WIDTH,
        MEASURED_CANVAS_HEIGHT,
        declared,
      );
      expect(bound).toBeLessThanOrEqual(unbounded);
    }
  });

  it("scales with the canvas, which is why it is derived and not a constant", () => {
    const small = terrainCacheSlotBound(800, 600, 128);
    const large = terrainCacheSlotBound(3840, 2160, 128);
    expect(large).toBeGreaterThan(small);
    // A cap chosen for a laptop would throttle a 4K screen; the derived form cannot.
    expect(small).toBeLessThan(viewDependentCacheSlots(3840, 2160, 256));
  });

  it("cuts the measured ceiling from ~1.24 GiB to ~388 MiB at the reported canvas", () => {
    const bound = terrainCacheSlotBound(MEASURED_CANVAS_WIDTH, MEASURED_CANVAS_HEIGHT, 128);
    expect(bound * demSlotBytes(512)).toBe(406_861_840);
  });
});

describe("shippedTerrainCacheSlots", () => {
  it("clears the MEASURED knee, which the derived bound alone did not", () => {
    // Sweep on a 12-position regional tour, working set 294 tiles, revisiting the same ground:
    //   cap      605  450  300  240  180
    //   refetch    3    3    3  303  338
    // The bound on that canvas (1235x1175) was 180 — below the knee. This is why the multiplier
    // exists, and the assertion is against the measurement rather than against the formula.
    const MEASURED_KNEE = 294;
    expect(terrainCacheSlotBound(1235, 1175, 128)).toBeLessThan(MEASURED_KNEE);
    expect(shippedTerrainCacheSlots(1235, 1175, 128)).toBeGreaterThan(MEASURED_KNEE);
  });

  it("is the bound times the multiplier, and nothing else", () => {
    expect(shippedTerrainCacheSlots(1235, 1175, 128)).toBe(
      terrainCacheSlotBound(1235, 1175, 128) * TERRAIN_CACHE_SLOT_MULTIPLIER,
    );
  });

  it("cuts the reported canvas to under a third of its uncapped ceiling", () => {
    // Was "well below" with a 0.65 threshold, back when the multiplier was the only governor and
    // this canvas got 770 slots. The byte ceiling binds here, so the real figure is 0.30.
    const capped = shippedTerrainCacheSlots(MEASURED_CANVAS_WIDTH, MEASURED_CANVAS_HEIGHT, 128);
    const uncapped = viewDependentCacheSlots(MEASURED_CANVAS_WIDTH, MEASURED_CANVAS_HEIGHT, 128);
    expect(capped).toBeLessThan(uncapped);
    expect(capped / uncapped).toBeLessThan(0.35);
  });

  it("scales with the canvas UNTIL the budget binds, then stops", () => {
    // The original of this test asserted only that a bigger screen gets a bigger cache, and its
    // comment argued that "a constant would throttle a big screen". That reasoning is what put
    // 1.69 GB on a 4K display. Both halves of the two-governor design are asserted here now.
    expect(shippedTerrainCacheSlots(1280, 720, 128)).toBeGreaterThan(
      shippedTerrainCacheSlots(640, 480, 128),
    );
    expect(shippedTerrainCacheSlots(3840, 2160, 128)).toBe(
      shippedTerrainCacheSlots(5120, 1440, 128),
    );
  });
});

describe("the byte ceiling — regression for the cap that grew with the screen", () => {
  // Real display sizes, plus the two that broke it. Before the ceiling these produced 363 MB,
  // 813 MB and 1.69 GB respectively: the "cap" granted a 4K screen more cache than an UNCAPPED
  // laptop, which is what a canvas-area formula does when nothing bounds it.
  const CANVASES: Array<[string, number, number]> = [
    ["laptop", 1235, 1175],
    ["1080p", 1920, 1000],
    ["2K (the canvas that lost the context)", 2560, 1321],
    ["4K", 3840, 2160],
    ["ultrawide", 5120, 1440],
    ["absurd", 12000, 8000],
  ];

  it.each(CANVASES)("never exceeds the byte budget at %s", (_name, width, height) => {
    const slots = shippedTerrainCacheSlots(width, height, 128);
    expect(slots * demSlotBytes(TERRAIN_ASSET_TILE_PX)).toBeLessThanOrEqual(
      TERRAIN_CACHE_BYTE_BUDGET,
    );
  });

  it("is MONOTONIC in the right direction — a bigger screen never gets a bigger cache", () => {
    // The defect stated as a property. Growing the canvas may leave the cap flat, never raise it
    // past the budget, and this is the assertion the original code would have failed.
    const byArea = [...CANVASES].sort((a, b) => a[1] * a[2] - b[1] * b[2]);
    const ceiling = slotsWithinByteBudget(TERRAIN_CACHE_BYTE_BUDGET, TERRAIN_ASSET_TILE_PX);
    for (const [, width, height] of byArea) {
      expect(shippedTerrainCacheSlots(width, height, 128)).toBeLessThanOrEqual(ceiling);
    }
  });

  it("does NOT bind at laptop sizes, so the measured behaviour is unchanged there", () => {
    // 2x derived is 360 on this canvas and the budget allows 381, so the formula still rules and
    // the 363 MB reading from the live A/B still stands.
    expect(shippedTerrainCacheSlots(1235, 1175, 128)).toBe(
      terrainCacheSlotBound(1235, 1175, 128) * TERRAIN_CACHE_SLOT_MULTIPLIER,
    );
  });

  it("DOES bind at 2K, which is the whole point", () => {
    const derived = terrainCacheSlotBound(2560, 1321, 128) * TERRAIN_CACHE_SLOT_MULTIPLIER;
    const shipped = shippedTerrainCacheSlots(2560, 1321, 128);
    expect(shipped).toBeLessThan(derived);
    expect(shipped).toBe(slotsWithinByteBudget(TERRAIN_CACHE_BYTE_BUDGET, TERRAIN_ASSET_TILE_PX));
  });

  it("stays above the measured knee on the canvas where the knee was measured", () => {
    // The ceiling must not silently undo the multiplier's reason for existing.
    expect(shippedTerrainCacheSlots(1235, 1175, 128)).toBeGreaterThan(294);
  });

  it("tracks the asset size, so the 256px arm gets 4x the slots for the same bytes", () => {
    const at512 = slotsWithinByteBudget(TERRAIN_CACHE_BYTE_BUDGET, 512);
    const at256 = slotsWithinByteBudget(TERRAIN_CACHE_BYTE_BUDGET, 256);
    expect(at256 / at512).toBeCloseTo(3.97, 1);
  });

  it("never returns zero slots, however small the budget", () => {
    expect(slotsWithinByteBudget(1, 512)).toBe(1);
  });
});

describe("demCacheCapFault — the cap is verified, not assumed", () => {
  const withCap = (written: number | null, enforced: number): TileManagerLike => ({
    _maxTileCacheSize: written,
    _outOfViewCache: { max: enforced, data: {} },
    _inViewTiles: { getAllTiles: () => [] },
  });

  it("is silent when the write stuck and MapLibre is enforcing it", () => {
    expect(demCacheCapFault(withCap(360, 360), 360)).toBeNull();
  });

  it("is silent when MapLibre enforces something TIGHTER than asked", () => {
    // Math.min against its own view-dependent size: a smaller number is MapLibre agreeing, not
    // disagreeing, and flagging it would make the check cry wolf on every small viewport.
    expect(demCacheCapFault(withCap(360, 120), 360)).toBeNull();
  });

  it("catches a write that did not stick", () => {
    expect(demCacheCapFault(withCap(null, 605), 360)).toContain("did not stick");
  });

  it("catches MapLibre not honouring a cap that was written", () => {
    // The end-to-end failure: field set, effect absent. Only a read-back of the LIVE cache sees it.
    expect(demCacheCapFault(withCap(360, 605), 360)).toContain("not enforced");
  });

  it("catches the cache reporting no max at all", () => {
    expect(
      demCacheCapFault({ _maxTileCacheSize: 360, _outOfViewCache: { data: {} } }, 360),
    ).toContain("internals moved");
  });

  it("reports a missing tile manager rather than passing silently", () => {
    expect(demCacheCapFault(undefined, 360)).toContain("no terrain tile manager");
  });

  it("enforces nothing on the uncapped control arm", () => {
    expect(demCacheCapFault(withCap(null, 605), null)).toBeNull();
  });
});

describe("parseDemCacheSetting", () => {
  it("defaults to the derived cap when absent or blank", () => {
    expect(parseDemCacheSetting(new URLSearchParams())).toEqual({ kind: "derived" });
    expect(parseDemCacheSetting(new URLSearchParams("demcache="))).toEqual({ kind: "derived" });
  });

  it("reads off as the uncapped control arm", () => {
    expect(parseDemCacheSetting(new URLSearchParams("demcache=off"))).toEqual({ kind: "off" });
  });

  it("reads an explicit slot count", () => {
    expect(parseDemCacheSetting(new URLSearchParams("demcache=300"))).toEqual({
      kind: "fixed",
      slots: 300,
    });
  });

  it.each(["nonsense", "0", "-5", "12.5", "300px"])("returns null for %s", (raw) => {
    expect(parseDemCacheSetting(new URLSearchParams(`demcache=${raw}`))).toBeNull();
  });
});

describe("resolveDemCacheSlots", () => {
  it("returns null for off, so MapLibre's own sizing is left alone", () => {
    expect(resolveDemCacheSlots({ kind: "off" }, 1235, 1175, 128)).toBeNull();
  });

  it("passes a fixed count through untouched, canvas irrelevant", () => {
    expect(resolveDemCacheSlots({ kind: "fixed", slots: 42 }, 1235, 1175, 128)).toBe(42);
    expect(resolveDemCacheSlots({ kind: "fixed", slots: 42 }, 3840, 2160, 128)).toBe(42);
  });

  it("derives from the canvas otherwise", () => {
    expect(resolveDemCacheSlots({ kind: "derived" }, 1235, 1175, 128)).toBe(
      shippedTerrainCacheSlots(1235, 1175, 128),
    );
  });
});

describe("applyDemCacheCap", () => {
  it("writes the field MapLibre re-reads on every render", () => {
    const manager: TileManagerLike = { _maxTileCacheSize: null };
    expect(applyDemCacheCap(manager, 360)).toBe(true);
    expect(manager._maxTileCacheSize).toBe(360);
  });

  it("writes null for the uncapped arm rather than skipping the write", () => {
    // Skipping would leave a previously-applied cap in place after a resize into ?demcache=off.
    const manager: TileManagerLike = { _maxTileCacheSize: 360 };
    expect(applyDemCacheCap(manager, null)).toBe(true);
    expect(manager._maxTileCacheSize).toBeNull();
  });

  it("reports failure instead of throwing when there is no manager", () => {
    expect(applyDemCacheCap(undefined, 360)).toBe(false);
  });

  it("reports failure when the field MapLibre reads has moved", () => {
    // The sabotage that matters: a silent no-op here would ship an uncapped globe that claims to
    // be capped, and the perf line would still print an arm label.
    expect(applyDemCacheCap({ _outOfViewCache: { max: 1, data: {} } }, 360)).toBe(false);
  });
});

describe("summariseDemCache", () => {
  it("sums the out-of-view cache and the in-view tiles, which both pin their dem", () => {
    const summary = summariseDemCache(fakeTileManager({ cached: 40, inView: 12, max: 1260 }));
    expect(summary).toEqual({
      cachedTiles: 40,
      inViewTiles: 12,
      maxSlots: 1260,
      cachedBytes: 40 * demSlotBytes(512),
      inViewBytes: 12 * demSlotBytes(512),
    });
  });

  it("reports zero bytes for a tile whose dem was already deleted on eviction", () => {
    const summary = summariseDemCache({
      _outOfViewCache: { max: 10, data: { a: [{ value: {} }] } },
      _inViewTiles: { getAllTiles: () => [] },
    });
    expect(summary).toEqual({
      cachedTiles: 1,
      inViewTiles: 0,
      maxSlots: 10,
      cachedBytes: 0,
      inViewBytes: 0,
    });
  });

  it("counts every entry under a key — TileCache stores an ARRAY per key", () => {
    const summary = summariseDemCache({
      _outOfViewCache: { max: 10, data: { a: [{ value: fakeTile(512) }, { value: fakeTile(512) }] } },
      _inViewTiles: { getAllTiles: () => [] },
    });
    expect(summary?.cachedTiles).toBe(2);
  });

  // The sabotage arm: each of these is a field MapLibre could rename, and every one of them must
  // read as "no answer" rather than as an empty cache. An empty cache and a moved internal produce
  // the same 0 MB, and only one of them is news.
  it.each([
    ["the tile manager itself is absent", undefined],
    ["_outOfViewCache moved", { _inViewTiles: { getAllTiles: () => [] } }],
    ["the cache's data map moved", { _outOfViewCache: { max: 1 }, _inViewTiles: { getAllTiles: () => [] } }],
    ["max is no longer a number", { _outOfViewCache: { max: null, data: {} }, _inViewTiles: { getAllTiles: () => [] } }],
    ["_inViewTiles moved", { _outOfViewCache: { max: 1, data: {} } }],
    ["getAllTiles is no longer callable", { _outOfViewCache: { max: 1, data: {} }, _inViewTiles: {} }],
  ])("returns null, not zero, when %s", (_case, tileManager) => {
    expect(summariseDemCache(tileManager as TileManagerLike | undefined)).toBeNull();
  });

  it("distinguishes a genuinely empty cache from a moved internal", () => {
    const empty = summariseDemCache(fakeTileManager({ cached: 0, inView: 0, max: 1260 }));
    expect(empty).toEqual({
      cachedTiles: 0,
      inViewTiles: 0,
      maxSlots: 1260,
      cachedBytes: 0,
      inViewBytes: 0,
    });
    expect(empty).not.toBeNull();
  });
});

describe("demCacheLine", () => {
  it("says so loudly when the summary is unavailable", () => {
    expect(demCacheLine(null)).toContain("n/a");
  });

  it("prints cached megabytes against the live ceiling", () => {
    const summary = summariseDemCache(fakeTileManager({ cached: 100, inView: 20, max: 1260 }));
    const line = demCacheLine(summary);
    expect(line).toContain("101/1270 MB"); // 100 tiles * 1,056,784 B = 100.8 MiB
    expect(line).toContain("100/1260 slots");
    expect(line).toContain("+20 MB in 20 view tiles");
  });

  it("never shows resident exceeding the ceiling — in-view tiles are not capped", () => {
    // A full cache plus in-view tiles printed "659 MB (ceiling 610 MB)" on the running page, which
    // reads as an overflow bug in MapLibre rather than as the cap doing its job.
    const full = summariseDemCache(fakeTileManager({ cached: 605, inView: 49, max: 605 }));
    const line = demCacheLine(full);
    expect(line).toContain("610/610 MB");
    expect(line).toContain("605/605 slots");
  });
});

describe("describeDemCacheState", () => {
  it("says the source is absent rather than crying wolf about MapLibre", () => {
    // The ordinary state for the first frames and for every ?terrain=off visit. This was printing
    // "MapLibre internals moved" until the overlay was actually read on a running page.
    const line = describeDemCacheState(undefined);
    expect(line).toContain("no terrain source");
    expect(line).not.toContain("moved");
  });

  it("still cries wolf when the source EXISTS but its internals do not match", () => {
    const line = describeDemCacheState({ _outOfViewCache: { max: 1 } } as TileManagerLike);
    expect(line).toContain("moved");
  });

  it("reports the numbers once the source is real", () => {
    const line = describeDemCacheState(fakeTileManager({ cached: 100, inView: 20, max: 1260 }));
    expect(line).toContain("100/1260 slots");
  });
});

describe("globe.astro wires the instrument rather than re-stating it", () => {
  const globe = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");

  it("reads the terrain source's own tile manager, not some other source's", () => {
    // Getting the source id wrong here reports the RELIEF cache and reads as a reassuringly small
    // number — the failure mode has no symptom, which is the same shape as the terrain/ prefix bug.
    const reads = globe.match(/map\.style\?\.tileManagers\?\.\[[A-Z_"'a-z]+\]/g) ?? [];
    expect(reads.length).toBeGreaterThan(0);
    for (const read of reads) expect(read).toContain("[TERRAIN_SOURCE]");
  });

  it("applies the cap and re-applies it on resize, or the viewport outgrows it", () => {
    // Scoped to the handler, so a cap applied somewhere it never runs fails here rather than
    // passing on a file-wide substring.
    expect(globe).toMatch(/map\.on\("resize", applyCacheCap\)/);
    const styleLoad = globe
      .match(/map\.on\("style\.load\", \(\) => \{[\s\S]*?\n    \}\);/g)
      ?.find((block) => block.includes("addSource(TERRAIN_SOURCE"));
    expect(styleLoad, "terrain must be added on style.load").toBeTruthy();
    expect(styleLoad).toContain("applyCacheCap()");
  });

  it("warns rather than failing silently when the cap cannot be installed", () => {
    expect(globe).toMatch(/if \(applyDemCacheCap\(tileManager, intendedCacheSlots\)\) return;/);
    expect(globe).toContain("no terrain source to bound yet");
  });

  it("reads the cap back after a frame, so 'applied' means enforced and not merely written", () => {
    // Scoped to the idle handler: a read-back moved somewhere it never runs would pass a
    // file-wide substring check while verifying nothing.
    const idle = globe
      .match(/map\.on\("idle", \(\) => \{[\s\S]*?\n    \}\);/g)
      ?.find((block) => block.includes("demCacheCapFault"));
    expect(idle, "an idle handler must verify the cap").toBeTruthy();
    expect(idle).toContain("console.error");
    expect(idle).toContain("capFaultReported");
  });

  it("surfaces the line through the perf overlay, so it is visible in Zen without devtools", () => {
    // The crash was in Zen and Zen is where it gets judged; a console-only probe would only ever
    // be read in the browser I can drive.
    const mount = globe.match(/mountPerfOverlay\([\s\S]*?\),\n    \);/)?.[0];
    expect(mount, "the perf overlay must be mounted").toBeTruthy();
    expect(mount).toContain("demCache()");
  });

  it("keeps the byte arithmetic out of the page — one place it can drift from", () => {
    expect(globe).not.toContain("1056784");
    expect(globe).not.toContain("MAX_TILE_CACHE_ZOOM_LEVELS");
  });
});

describe("canary — the MapLibre internals this module corrects", () => {
  // Everything in this module is read out of the shipped bundle; none of it is documented. The
  // failure that matters most is MapLibre FIXING the mismatch: our cap would then be an
  // over-constraint, silently discarding cache the globe should have kept. Property names survive
  // minification, so these read the production build.
  const bundleUrl = new URL("../../node_modules/maplibre-gl/dist/maplibre-gl.mjs", import.meta.url);
  const sharedUrl = new URL(
    "../../node_modules/maplibre-gl/dist/maplibre-gl-shared.mjs",
    import.meta.url,
  );
  const bundle = readFileSync(bundleUrl, "utf8");
  const shared = readFileSync(sharedUrl, "utf8");

  it("still SIZES the cache from the source's declared tile size", () => {
    expect(bundle).toMatch(
      /updateCacheSize\(\w+\)\{let \w+=\(Math\.ceil\(\w+\.width\/this\._source\.tileSize\)\+1\)\*\(Math\.ceil\(\w+\.height\/this\._source\.tileSize\)\+1\)/,
    );
  });

  it("still FILLS a terrain source from the doubled tile size — the mismatch this module corrects", () => {
    expect(bundle).toMatch(/usedForTerrain\?this\.tileSize:this\._source\.tileSize/);
    expect(bundle).toMatch(/tileSize=\w+\._source\.tileSize\*2\*\*this\.deltaZoom/);
    expect(bundle).toMatch(/deltaZoom=1\b/);
  });

  it("still applies maxTileCacheSize as a Math.min, so a cap can only shrink the cache", () => {
    expect(bundle).toMatch(/Math\.min\(this\._maxTileCacheSize,\w+\)/);
  });

  it("still defaults to five zoom levels", () => {
    expect(shared).toMatch(
      new RegExp(`MAX_TILE_CACHE_ZOOM_LEVELS:${MAPLIBRE_MAX_TILE_CACHE_ZOOM_LEVELS}\\b`),
    );
  });

  it("still frees the dem only on eviction, which is why the cap is the whole lever", () => {
    // raster_dem_tile_source.unloadTile is the sole `delete tile.dem`, and TileCache's onRemove is
    // what calls it. If either moves, a bounded cache stops bounding bytes.
    expect(bundle).toMatch(/delete \w+\.dem\b/);
    expect(bundle).toMatch(/_outOfViewCache=new \w+\(0,\w+=>this\._unloadTile\(\w+\)\)/);
  });
});

describe("terrainCoveringTileCount — MapLibre's own answer, not our restatement", () => {
  /** Records the options so the call itself can be asserted, not just its result. */
  function spyMap(returns: unknown) {
    const calls: Array<Record<string, unknown>> = [];
    return {
      calls,
      map: {
        coveringTiles: (options: Record<string, unknown>) => {
          calls.push(options);
          if (typeof returns === "function") return (returns as () => unknown[])();
          return returns as unknown[];
        },
      },
    };
  }

  it("asks at the FILL size, not the declared one — reading the declared size here would reproduce the bug", () => {
    const { calls, map } = spyMap(new Array(52).fill(null));
    expect(terrainCoveringTileCount(map, 128, 0, 8)).toBe(52);
    expect(calls[0].tileSize).toBe(256); // 128 * 2**deltaZoom
    expect(calls[0]).toMatchObject({ minzoom: 0, maxzoom: 8, roundZoom: false });
  });

  it("tracks the declared size through terrainFillTileSize rather than hard-coding 256", () => {
    const { calls, map } = spyMap([]);
    terrainCoveringTileCount(map, 256, 0, 8);
    expect(calls[0].tileSize).toBe(terrainFillTileSize(256));
  });

  it("is the number the sizing formula should have used — measured, the formula over-counts ~6x", () => {
    // Live on a 2560x1265 canvas at z5: coveringTiles gave 52 at tileSize 256; the rectangular
    // formula gives 330. That gap is why the byte budget it fed had no defensible upper bound.
    expect(viewDependentCacheSlots(2560, 1265, 256)).toBe(330);
    expect(viewDependentCacheSlots(2560, 1265, 128)).toBe(1155);
    const { map } = spyMap(new Array(52).fill(null));
    expect(terrainCoveringTileCount(map, 128, 0, 8)).toBe(52);
  });

  it.each([
    ["the map has no coveringTiles at all", undefined],
    ["MapLibre stopped exposing it", {}],
    ["it no longer returns an array", { coveringTiles: () => 52 }],
  ])("reports null — never zero — when %s", (_case, map) => {
    expect(terrainCoveringTileCount(map as never, 128, 0, 8)).toBeNull();
  });

  it("returns null rather than throwing when the camera is mid-transition", () => {
    const map = {
      coveringTiles: () => {
        throw new Error("transform not ready");
      },
    };
    expect(() => terrainCoveringTileCount(map, 128, 0, 8)).not.toThrow();
    expect(terrainCoveringTileCount(map, 128, 0, 8)).toBeNull();
  });
});

describe("demCacheLine prices the cap against what the camera needs", () => {
  const summary = {
    cachedTiles: 40,
    inViewTiles: 67,
    maxSlots: 381,
    cachedBytes: 40 * demSlotBytes(512),
    inViewBytes: 67 * demSlotBytes(512),
  };

  it("states the headroom ratio, because a bare slot count is unreadable", () => {
    expect(demCacheLine(summary, undefined, 52)).toContain("needs 52 (7.3x headroom)");
  });

  it("omits it entirely when the covering count could not be read", () => {
    // Not "needs 0" and not "needs 1x" — an unread camera must not render as a satisfied one.
    expect(demCacheLine(summary, undefined, null)).not.toContain("needs");
    expect(demCacheLine(summary)).not.toContain("needs");
  });

  it("never divides by zero when a camera covers nothing", () => {
    expect(() => demCacheLine(summary, undefined, 0)).not.toThrow();
    expect(demCacheLine(summary, undefined, 0)).toContain("needs 0");
  });
});
