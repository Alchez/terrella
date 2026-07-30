// The caps.json contract mapping and the pure mesh math — the values the pipeline authors
// (edge_lat, feather ceiling, URLs) must flow through capOptionsFrom untouched, because the
// literals they replaced drifted silently by construction (the hero/tile constants lesson).

import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Map as MaplibreMap } from "maplibre-gl";
import {
  MAPLIBRE_GLOBE_RADIUS_M,
  MOBILE_CAP_BUDGET_PX,
  RINGS,
  SECTORS,
  addPolarCap,
  buildMesh,
  canvasBackingRatio,
  capDisplacementScale,
  capOptionsFrom,
  capProjectedExtentPx,
  capTextureBudget,
  clampedTextureSize,
  classifyDevice,
  compositedAlpha,
  decodeCapElevation,
  deviceClass,
  isMobileClassDevice,
  loadCapElevation,
  pickRung,
  rungForDemand,
  syncCapRung,
  vertexSrc,
  zeroElevationTexel,
  type CapLayer,
  type CapOptions,
  type CapsManifest,
} from "./polarCaps";
import { TERRAIN_QUANTISATION_M, terrainEncoding } from "./terrainSource";

// The shipped ladder (cap_render.CAP_RUNGS), so the fixture cannot drift from production.
const RUNGS = (pole: string) => [
  { px: 1024, url: `/caps/cap_${pole}_1024.webp` },
  { px: 2048, url: `/caps/cap_${pole}_2048.webp` },
  { px: 4096, url: `/caps/cap_${pole}_4096.webp` },
  { px: 8192, url: `/caps/cap_${pole}_8192.webp` },
];

const MANIFEST: CapsManifest = {
  north: {
    rungs: RUNGS("north"), edge_lat: 78, feather_hi: 84,
    elev_url: "/caps/cap_north_elev.webp", elev_step: TERRAIN_QUANTISATION_M,
  },
  south: {
    rungs: RUNGS("south"), edge_lat: -78, feather_hi: -84,
    elev_url: "/caps/cap_south_elev.webp", elev_step: TERRAIN_QUANTISATION_M,
  },
};

describe("pickRung", () => {
  it("takes the largest rung the budget affords", () => {
    expect(pickRung(RUNGS("north"), Infinity).px).toBe(8192);
    expect(pickRung(RUNGS("north"), MOBILE_CAP_BUDGET_PX).px).toBe(4096);
  });

  it("rounds DOWN to a shipped rung rather than overshooting the budget", () => {
    // A 6000 budget must not fetch 8192 — overshooting is what the rung exists to prevent.
    expect(pickRung(RUNGS("north"), 6000).px).toBe(4096);
  });

  it("falls back to the smallest rung when nothing fits", () => {
    // A GPU below every shipped rung still gets a texture (the upload clamp handles the rest);
    // returning undefined here would render the pole black.
    expect(pickRung(RUNGS("north"), 512).px).toBe(1024);
  });

  it("does not depend on the manifest's rung order", () => {
    const shuffled = [...RUNGS("north")].reverse();
    expect(pickRung(shuffled, MOBILE_CAP_BUDGET_PX).px).toBe(4096);
    expect(pickRung(shuffled, Infinity).px).toBe(8192);
  });
});

describe("capOptionsFrom", () => {
  it("maps the pipeline contract onto both caps without re-encoding it", () => {
    const [north, south] = capOptionsFrom(MANIFEST);
    expect(north.layerId).toBe("polar-cap-north");
    // The whole ladder rides through, unresolved: which rung this cap needs depends on the camera,
    // which does not exist yet when the options are built.
    expect(north.rungs).toEqual(RUNGS("north"));
    expect(north.poleLat).toBe(90);
    expect(north.texEdgeLat).toBe(78);
    expect(south.poleLat).toBe(-90);
    expect(south.texEdgeLat).toBe(-78);
    expect(south.latBottom).toBeLessThan(0);
  });

  it("feathers on |lat| even though the south ships a signed ceiling", () => {
    const [north, south] = capOptionsFrom(MANIFEST);
    expect(north.featherHi).toBe(84);
    expect(south.featherHi).toBe(84); // Math.abs(−84): the shader compares against |lat|
  });

  it("keeps the feather ordered: fade starts below the ceiling", () => {
    for (const options of capOptionsFrom(MANIFEST)) {
      expect(options.featherLo).toBeLessThan(options.featherHi);
    }
  });

  it("carries the device budget through to both caps", () => {
    const [north, south] = capOptionsFrom(MANIFEST, capTextureBudget(true));
    expect(north.budgetPx).toBe(MOBILE_CAP_BUDGET_PX);
    expect(south.budgetPx).toBe(MOBILE_CAP_BUDGET_PX);
    expect(capOptionsFrom(MANIFEST, capTextureBudget(false))[0].budgetPx).toBe(Infinity);
  });
});

describe("classifyDevice", () => {
  it("prefers UA-Client-Hints, and says so — Chromium phones answer here, Firefox never does", () => {
    expect(classifyDevice(true, false)).toEqual({ mobileClass: true, via: "ua-client-hints" });
    // The hint WINS over a disagreeing pointer heuristic rather than being OR-ed with it: a
    // Chromium desktop with a touchscreen reports coarse pointers and is not a phone.
    expect(classifyDevice(false, true)).toEqual({ mobileClass: false, via: "ua-client-hints" });
  });

  it("falls through to the pointer heuristic when the hint is absent", () => {
    expect(classifyDevice(undefined, true)).toEqual({ mobileClass: true, via: "pointer-coarse" });
    expect(classifyDevice(undefined, false)).toEqual({
      mobileClass: false,
      via: "pointer-coarse",
    });
  });

  it("reports NO SIGNAL as its own state, instead of a desktop verdict from no evidence", () => {
    // This is the whole reason `via` exists. Both arms absent used to return a bare `false`, which
    // reads downstream as "desktop" and buys Infinity texture budget — 512 MB of caps decided by
    // the absence of a measurement. The verdict is still false (it has to be something), but it
    // now arrives labelled, so a snapshot cannot present it as a reading.
    expect(classifyDevice(undefined, undefined)).toEqual({ mobileClass: false, via: "no-signal" });
  });

  it("keeps the boolean helper agreeing with the structured verdict", () => {
    // Two entry points, one rule. If these ever disagree, the cap budget and the panel disagree.
    expect(isMobileClassDevice()).toBe(deviceClass().mobileClass);
  });
});

describe("rungForDemand", () => {
  it("caps a phone at the mobile rung however close the camera gets, for BOTH poles", () => {
    // The payload cut the mobile rung exists for: a phone must never download either 8192 texture,
    // even zoomed onto a pole where the demand genuinely exceeds 4096.
    const budget = capTextureBudget(true);
    expect(rungForDemand(RUNGS("north"), 99999, budget).url).toBe("/caps/cap_north_4096.webp");
    expect(rungForDemand(RUNGS("south"), 99999, budget).url).toBe("/caps/cap_south_4096.webp");
  });

  it("lets desktop reach the top rung when the camera actually demands it", () => {
    expect(rungForDemand(RUNGS("north"), 99999, capTextureBudget(false)).px).toBe(8192);
  });
});

describe("buildMesh", () => {
  it("builds the full grid with in-range AEQD UVs", () => {
    const [north] = capOptionsFrom(MANIFEST);
    const { vertices, indices } = buildMesh(north);
    expect(vertices.length).toBe((RINGS + 1) * (SECTORS + 1) * 6);
    expect(indices.length).toBe(RINGS * SECTORS * 6);
    for (let vertex = 0; vertex < vertices.length; vertex += 6) {
      expect(vertices[vertex + 3]).toBeGreaterThanOrEqual(0); // u
      expect(vertices[vertex + 3]).toBeLessThanOrEqual(1);
      expect(vertices[vertex + 4]).toBeGreaterThanOrEqual(0); // v
      expect(vertices[vertex + 4]).toBeLessThanOrEqual(1);
    }
  });

  it("pins the pole ring to the texture centre (AEQD radius 0 at the pole)", () => {
    const [north] = capOptionsFrom(MANIFEST);
    const { vertices } = buildMesh(north);
    const poleRingStart = RINGS * (SECTORS + 1) * 6; // last ring = the pole
    for (let sector = 0; sector <= SECTORS; sector++) {
      const base = poleRingStart + sector * 6;
      expect(vertices[base + 3]).toBeCloseTo(0.5, 6); // u
      expect(vertices[base + 4]).toBeCloseTo(0.5, 6); // v
      expect(vertices[base + 5]).toBeCloseTo(90, 6); // lat
    }
  });
});

describe("clampedTextureSize", () => {
  it("passes a fitting texture through and clamps an oversized one", () => {
    expect(clampedTextureSize(4096, 16384)).toBe(4096);
    expect(clampedTextureSize(8192, 4096)).toBe(4096); // the weak-GPU case
  });

  it("applies the device budget even when the GPU could take the full texture", () => {
    // The OnePlus 11R case: Adreno 730 reports MAX_TEXTURE_SIZE 16384, so the GPU
    // clamp never fires — the budget is what spares the phone the 268 MB upload.
    expect(clampedTextureSize(8192, 16384, 4096)).toBe(4096);
  });

  it("leaves desktops at full size when the budget is Infinity", () => {
    expect(clampedTextureSize(8192, 16384, Infinity)).toBe(8192);
  });

  it("never upscales past the image itself", () => {
    expect(clampedTextureSize(4096, 16384, 8192)).toBe(4096);
  });
});

describe("capTextureBudget", () => {
  it("gives mobile-class devices the 4096 rung and desktops no budget", () => {
    expect(capTextureBudget(true)).toBe(MOBILE_CAP_BUDGET_PX);
    expect(capTextureBudget(false)).toBe(Infinity);
  });
});

// ---------------------------------------------------------------------------------------------
// Rung selection from the camera. The numbers below are not invented: they are what the live globe
// measured at DPR 1 (untouched default camera 110 px, north pole dragged into view at
// default zoom 1173 px, centred on the pole at z4 5822 px), so a change in the selection rule shows
// up here as a disagreement with reality rather than with a guess.
// ---------------------------------------------------------------------------------------------

/** A projector that puts the edge parallel on a circle of radius `radiusPx` and the pole at its
 *  centre, so the measured extent is exactly `2 * radiusPx`. */
function circleProjector(radiusPx: number, edgeLat: number) {
  return ([lng, lat]: [number, number]) => {
    if (lat === edgeLat) {
      const theta = (lng * Math.PI) / 180;
      return { x: 500 + radiusPx * Math.cos(theta), y: 500 + radiusPx * Math.sin(theta) };
    }
    return { x: 500, y: 500 }; // the pole
  };
}

describe("capProjectedExtentPx", () => {
  it("measures the cap's on-screen box when the camera is over the pole", () => {
    const extent = capProjectedExtentPx(circleProjector(55, 78), [0, 90], 78, 90);
    expect(Math.round(extent)).toBe(110); // the measured default-camera figure
  });

  it("returns 0 for a cap that is entirely behind the globe", () => {
    // The guard that stops a DPR-3 phone pulling a megabyte of NORTH cap while it looks at
    // Antarctica: MapLibre projects back-facing points anyway, and their box SATURATES near 970 px
    // rather than shrinking, so without the front-facing filter this reads as real demand.
    const extent = capProjectedExtentPx(circleProjector(2000, 78), [0, -89.9], 78, 90);
    expect(extent).toBe(0);
  });

  it("keeps a cap that is merely oblique, not hidden", () => {
    // Centre at 25 N is the real default camera: every point of the 78 N parallel is still
    // front-facing (the far meridian sits at 77 degrees away), so nothing may be dropped.
    expect(capProjectedExtentPx(circleProjector(55, 78), [20, 25], 78, 90)).toBeGreaterThan(0);
  });
});

describe("canvasBackingRatio", () => {
  it("reads the backing store, so a degraded canvas asks for less texture", () => {
    expect(canvasBackingRatio({ width: 2560, clientWidth: 2560 })).toBe(1);
    expect(canvasBackingRatio({ width: 5120, clientWidth: 2560 })).toBe(2);
    // What the FPS watchdog's setPixelRatio(1) produces on a DPR-2 device: demand must fall to 1x,
    // which window.devicePixelRatio would still report as 2.
    expect(canvasBackingRatio({ width: 2560, clientWidth: 2560 })).toBe(1);
  });

  it("does not divide by zero on a canvas that has not been laid out", () => {
    expect(canvasBackingRatio({ width: 0, clientWidth: 0 })).toBe(1);
  });
});

describe("rungForDemand — the measured camera table", () => {
  const north = RUNGS("north");
  it("serves the untouched default camera from the floor at every DPR", () => {
    for (const dpr of [1, 2, 3]) {
      expect(rungForDemand(north, 110 * dpr, Infinity).px).toBe(1024);
    }
  });

  it("steps to 2048 when the pole is dragged into view at default zoom (DPR 1)", () => {
    expect(rungForDemand(north, 1173, Infinity).px).toBe(2048);
  });

  it("needs 4096 for that same view on a DPR-2 screen", () => {
    expect(rungForDemand(north, 1173 * 2, Infinity).px).toBe(4096);
  });

  it("reaches the top rung only when the camera is actually at the pole", () => {
    expect(rungForDemand(north, 5822, Infinity).px).toBe(8192);
  });

  it("never overshoots: a demand between rungs takes the one ABOVE it", () => {
    // Undershooting is the failure that shows, since an upscaled texture reads as blur.
    expect(rungForDemand(north, 1025, Infinity).px).toBe(2048);
    expect(rungForDemand(north, 4097, Infinity).px).toBe(8192);
  });
});

// ---------------------------------------------------------------------------------------------
// The upload oracle. The bug was not a wrong picture — it was the RIGHT picture uploaded
// up to five times, which nothing observed. Counting texImage2D is the only assertion that would
// have caught it, so the upgrade path is tested by upload count, not by appearance.
// ---------------------------------------------------------------------------------------------

interface FakeGl {
  uploads: number[];
  fetched: string[];
  /** Every `texParameteri(target, pname, value)` as a [pname, value] pair. The elevation texture's
   *  filter is a correctness setting, not a preference, so it has to be observable. */
  params: Array<[number, number]>;
  mipmaps: number;
}

function fakeGl(): FakeGl & Record<string, unknown> {
  const uploads: number[] = [];
  const params: Array<[number, number]> = [];
  const self: FakeGl & Record<string, unknown> = {
    uploads,
    params,
    mipmaps: 0,
    fetched: [],
    TEXTURE_2D: 1, RGBA: 2, UNSIGNED_BYTE: 3, MAX_TEXTURE_SIZE: 4,
    TEXTURE_MIN_FILTER: 5, TEXTURE_MAG_FILTER: 6, TEXTURE_WRAP_S: 7, TEXTURE_WRAP_T: 8,
    LINEAR_MIPMAP_LINEAR: 9, LINEAR: 10, CLAMP_TO_EDGE: 11, NEAREST: 12,
    getParameter: () => 16384, // a GPU that can take any rung, so the clamp never confuses the count
    bindTexture: () => undefined,
    generateMipmap: () => { self.mipmaps = (self.mipmaps as number) + 1; },
    texParameteri: (_target: number, pname: number, value: number) => {
      params.push([pname, value]);
    },
    texImage2D: (...args: unknown[]) => {
      const image = args[args.length - 1] as { width?: number };
      if (image && typeof image.width === "number") uploads.push(image.width);
    },
  };
  return self;
}

function fakeMap(extentPx: number, backingRatio = 1) {
  return {
    getCenter: () => ({ lng: 0, lat: 90 }),
    project: circleProjector(extentPx / 2, 78),
    getCanvas: () => ({ width: 1000 * backingRatio, clientWidth: 1000 }),
    triggerRepaint: () => undefined,
  } as unknown as MaplibreMap;
}

const OPTS: CapOptions = {
  layerId: "polar-cap-north",
  rungs: RUNGS("north"),
  budgetPx: Infinity,
  poleLat: 90,
  latBottom: 80,
  texEdgeLat: 78,
  featherLo: 81,
  featherHi: 84,
  elevUrl: "/caps/cap_north_elev.webp",
  elevStep: TERRAIN_QUANTISATION_M,
};

/** Stub the two browser APIs loadCapImage needs; record every URL it asks for. */
function stubImageLoading(gl: FakeGl, hold?: Promise<void>) {
  vi.stubGlobal("fetch", async (url: string) => {
    gl.fetched.push(url);
    if (hold) await hold;
    return { ok: true, blob: async () => ({ size: 1 }) };
  });
  vi.stubGlobal("createImageBitmap", async (_blob: unknown) => {
    const px = Number(/_(\d+)\.webp$/.exec(gl.fetched[gl.fetched.length - 1] ?? "")?.[1] ?? 0);
    return { width: px, height: px, close: () => undefined };
  });
}

function makeLayer(gl: unknown): CapLayer {
  return {
    id: "polar-cap-north",
    type: "custom",
    render: () => undefined,
    gl: gl as WebGL2RenderingContext,
    texture: {} as WebGLTexture,
    loadedRungPx: 0,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("syncCapRung", () => {
  it("uploads exactly once per rung change, and nothing when the camera needs nothing new", async () => {
    const gl = fakeGl();
    stubImageLoading(gl);
    const layer = makeLayer(gl);

    await syncCapRung(layer, OPTS, fakeMap(110)); // first load
    expect(gl.uploads).toEqual([1024]);

    await syncCapRung(layer, OPTS, fakeMap(110)); // same camera — must be a no-op
    expect(gl.uploads).toEqual([1024]);

    await syncCapRung(layer, OPTS, fakeMap(5822)); // zoomed to the pole
    expect(gl.uploads).toEqual([1024, 8192]);
  });

  it("jumps straight to the needed rung instead of walking the ladder", async () => {
    // Walking 1024 -> 2048 -> 4096 -> 8192 would be three extra decodes and uploads on the main
    // thread, which is the cost this design exists to avoid.
    const gl = fakeGl();
    stubImageLoading(gl);
    await syncCapRung(makeLayer(gl), OPTS, fakeMap(5822));
    expect(gl.fetched).toEqual(["/caps/cap_north_8192.webp"]);
  });

  it("never downgrades when the camera pulls back out", async () => {
    const gl = fakeGl();
    stubImageLoading(gl);
    const layer = makeLayer(gl);

    await syncCapRung(layer, OPTS, fakeMap(5822));
    expect(layer.loadedRungPx).toBe(8192);

    await syncCapRung(layer, OPTS, fakeMap(110)); // back to the overview
    expect(gl.uploads).toEqual([8192]); // no second upload, no softening
    expect(layer.loadedRungPx).toBe(8192);
  });

  it("honours the mobile budget however close the camera gets", async () => {
    const gl = fakeGl();
    stubImageLoading(gl);
    await syncCapRung(makeLayer(gl), { ...OPTS, budgetPx: MOBILE_CAP_BUDGET_PX }, fakeMap(5822));
    expect(gl.fetched).toEqual(["/caps/cap_north_4096.webp"]);
  });

  it("scales demand by the canvas backing ratio, not by the viewport", async () => {
    const gl = fakeGl();
    stubImageLoading(gl);
    // The same 1173 px cap on a DPR-2 canvas needs 4096, not the 2048 that DPR 1 takes.
    await syncCapRung(makeLayer(gl), OPTS, fakeMap(1173, 2));
    expect(gl.fetched).toEqual(["/caps/cap_north_4096.webp"]);
  });

  it("starts only one fetch while a rung is in flight", async () => {
    // A fast zoom fires many moveends; without the guard each would start its own 5 MB download.
    const gl = fakeGl();
    let release = () => undefined as void;
    const hold = new Promise<void>((resolve) => { release = () => resolve(); });
    stubImageLoading(gl, hold);
    const layer = makeLayer(gl);

    const first = syncCapRung(layer, OPTS, fakeMap(5822));
    const second = syncCapRung(layer, OPTS, fakeMap(5822));
    const third = syncCapRung(layer, OPTS, fakeMap(5822));
    release();
    await Promise.all([first, second, third]);

    expect(gl.fetched).toEqual(["/caps/cap_north_8192.webp"]);
    expect(gl.uploads).toEqual([8192]);
  });

  it("leaves the rung unchanged when the fetch fails, so a later move can retry", async () => {
    const gl = fakeGl();
    vi.stubGlobal("fetch", async () => ({ ok: false, status: 404 }));
    const layer = makeLayer(gl);
    await syncCapRung(layer, OPTS, fakeMap(5822));
    expect(gl.uploads).toEqual([]);
    expect(layer.loadedRungPx).toBe(0);
    expect(layer.rungLoading).toBeUndefined(); // the in-flight slot must not stay wedged
  });
});

/** A map that can gain and lose layers, and whose listeners outlive its style — which is the whole
 *  asymmetry a WebGL context loss exposes. `addLayer` attaches the gl/texture that the real `onAdd`
 *  would, so `syncCapRung` runs its true path instead of bailing on a missing context. */
function fakeMapWithStyle(extentPx: number, gl: unknown) {
  const listeners = new Map<string, Array<() => void>>();
  const layers = new Map<string, CapLayer>();
  const map = {
    getCenter: () => ({ lng: 0, lat: 90 }),
    project: circleProjector(extentPx / 2, 78),
    getCanvas: () => ({ width: 1000, clientWidth: 1000 }),
    triggerRepaint: () => undefined,
    getLayer: (id: string) => layers.get(id),
    addLayer: (layer: CapLayer) => {
      layer.gl = gl as WebGL2RenderingContext;
      layer.texture = {} as WebGLTexture;
      layer.loadedRungPx = 0;
      layers.set(layer.id, layer);
    },
    on: (event: string, handler: () => void) => {
      listeners.set(event, [...(listeners.get(event) ?? []), handler]);
    },
    off: (event: string, handler: () => void) => {
      listeners.set(event, (listeners.get(event) ?? []).filter((h) => h !== handler));
    },
  };
  return {
    map: map as unknown as MaplibreMap,
    moveEndCount: () => (listeners.get("moveend") ?? []).length,
    /** What a context loss does: MapLibre destroys the STYLE and rebuilds it from a snapshot that
     *  cannot carry a custom layer. Map-level listeners are untouched. */
    loseContext: () => layers.clear(),
    fireMoveEnd: async () => {
      for (const handler of [...(listeners.get("moveend") ?? [])]) handler();
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    },
    removeLayer: (id: string) => {
      const layer = layers.get(id);
      layers.delete(id);
      (layer as unknown as { onRemove?: (m: MaplibreMap) => void }).onRemove?.(
        map as unknown as MaplibreMap,
      );
    },
  };
}

describe("cap listener lifecycle across a WebGL context loss", () => {
  it("re-adding after a context loss leaves ONE moveend listener, not one per loss", () => {
    const harness = fakeMapWithStyle(110, fakeGl());
    addPolarCap(harness.map, OPTS);
    expect(harness.moveEndCount()).toBe(1);

    // Three losses. Before the registry each of these stranded a listener holding a dead layer.
    for (let loss = 0; loss < 3; loss++) {
      harness.loseContext();
      addPolarCap(harness.map, OPTS);
    }
    expect(harness.moveEndCount()).toBe(1);
  });

  it("fetches an upgraded rung ONCE after a loss — the doubled request measured live", async () => {
    const gl = fakeGl();
    stubImageLoading(gl);
    // Small cap: the first load takes 1024 and leaves room to upgrade.
    const harness = fakeMapWithStyle(110, gl);
    addPolarCap(harness.map, OPTS);
    harness.loseContext();
    addPolarCap(harness.map, OPTS);

    // A camera move that genuinely demands a bigger rung.
    const zoomed = fakeMapWithStyle(1600, gl);
    (harness.map as unknown as { project: unknown }).project = (
      zoomed.map as unknown as { project: unknown }
    ).project;
    await harness.fireMoveEnd();

    const requested = gl.fetched.filter((url) => url.includes("cap_north"));
    expect(requested.length).toBe(1);
    expect(new Set(requested).size).toBe(requested.length); // no URL fetched twice
  });

  it("onRemove detaches the listener, so an explicit removeLayer leaves nothing behind", () => {
    const harness = fakeMapWithStyle(110, fakeGl());
    addPolarCap(harness.map, OPTS);
    expect(harness.moveEndCount()).toBe(1);
    harness.removeLayer(OPTS.layerId);
    expect(harness.moveEndCount()).toBe(0);
  });
});

// ---------------------------------------------------------------------------------------------
// Displacement. The cap is a `custom` layer, which MapLibre never drapes onto the terrain mesh, so
// while the tiles rose the cap stayed at sea level — the flat bright disc at both poles. These
// pin the arithmetic that lifts it, and the two ways that arithmetic can be silently wrong: bytes
// decoded differently from the tiles' own DEM, and a mesh that displaces when it should be flat.
// ---------------------------------------------------------------------------------------------

describe("decodeCapElevation", () => {
  it("decodes exactly as MapLibre decodes the TILE dem, at the same step", () => {
    // The failure this prevents has no error and no obvious tell: cap and tiles are both drawn
    // across the alpha crossfade, so a decode that differs by one factor lifts two surfaces to
    // different heights in the same band and they ghost through each other. terrainEncoding() is
    // the spec handed to MapLibre for the pyramid; this is the cap doing it by hand. They must be
    // one statement, so the test compares them rather than restating the numbers a third time.
    const spec = terrainEncoding(TERRAIN_QUANTISATION_M);
    expect(spec.encoding).toBe("custom");
    if (spec.encoding !== "custom") return;
    for (const [red, green] of [[0, 0], [16, 0], [255, 255], [12, 200], [17, 0]]) {
      expect(decodeCapElevation(red, green, TERRAIN_QUANTISATION_M)).toBe(
        red * spec.redFactor + green * spec.greenFactor - spec.baseShift,
      );
    }
  });

  it("puts sea level and the encoding's extremes where terrarium says they are", () => {
    // Independent of the comparison above: an absolute anchor, so both sides moving together
    // cannot pass. Packed 4096 at 8 m/level is (4096*8) - 32768 = 0 m.
    expect(decodeCapElevation(16, 0, 8)).toBe(0);
    expect(decodeCapElevation(0, 0, 8)).toBe(-32768); // the encoding's floor
    expect(decodeCapElevation(0, 0, 1)).toBe(-32768); // ...which is the base shift, at any step
  });
});

describe("capDisplacementScale", () => {
  it("is EXACTLY 1 with terrain off, so the flat cap is bit-identical to the pre-displacement one", () => {
    // Object.is, not toBeCloseTo: `?terrain=off`, the Globe tier and the watchdog's disable-terrain
    // rung are all controls, and a control that renders 'almost' the same is not a control. IEEE754
    // multiplication by exactly 1.0 is exact, which is why the formula is written to collapse to it.
    for (const metres of [0, -5000, 8848.86, 32767]) {
      expect(Object.is(capDisplacementScale(metres, 0), 1)).toBe(true);
    }
  });

  it("lifts a vertex by elevation/radius, exaggerated — MapLibre's own globe formula", () => {
    // Everest at 1x is its height as a fraction of the globe radius, and nothing else.
    expect(capDisplacementScale(8848.86, 1)).toBeCloseTo(1 + 8848.86 / MAPLIBRE_GLOBE_RADIUS_M, 12);
    // Linear in exaggeration, so the ramp's live value needs no second curve here.
    expect(capDisplacementScale(1000, 15) - 1).toBeCloseTo(15 * (capDisplacementScale(1000, 1) - 1), 12);
    // Bathymetry displaces DOWNWARD — the pyramid ships `--sea bathy`, so the cap must too, or
    // the Arctic ocean would sit above the sea it feathers into.
    expect(capDisplacementScale(-4000, 15)).toBeLessThan(1);
  });

  it("uses MapLibre's globe radius, not the pipeline's AEQD projection radius", () => {
    // 6371008.8 vs cap_render's 6371000.0. Eight metres apart, and both are 'the earth radius' to
    // anyone reading quickly — which is exactly why one of them being wrong here would survive.
    expect(MAPLIBRE_GLOBE_RADIUS_M).toBe(6371008.8);
    expect(capDisplacementScale(MAPLIBRE_GLOBE_RADIUS_M, 1)).toBe(2);
  });
});

describe("zeroElevationTexel", () => {
  it("decodes to exactly sea level, at any step", () => {
    // The placeholder is GEOMETRY, unlike the colour texture's transparent black. Getting it wrong
    // is not a blank frame: RGBA(0,0,0,0) decodes to -32768 m, which at 15x pulls the cap to 92%
    // of the globe radius and hides it inside the planet until the fetch lands.
    for (const step of [1, 8, 16]) {
      const [red, green, blue, alpha] = zeroElevationTexel(step);
      expect(decodeCapElevation(red, green, step)).toBe(0);
      expect(blue).toBe(0); // the pipeline zeroes blue; the decode ignores it either way
      expect(alpha).toBe(255);
    }
  });

  it("is the shipped step's texel, spelled out once as a known answer", () => {
    expect(Array.from(zeroElevationTexel(8))).toEqual([16, 0, 0, 255]);
  });
});

describe("the displaced mesh", () => {
  it("indexes 32-bit, because the tessellation displacement needs overflows 16", () => {
    // Not a style choice. A Uint16Array does not throw on overflow, it WRAPS — vertex 65,536
    // becomes vertex 0, and the mesh folds through the pole while still drawing happily. This
    // asserts both halves: the buffer is wide enough, and the mesh really is big enough to need it.
    const [north] = capOptionsFrom(MANIFEST);
    const { vertices, indices } = buildMesh(north);
    expect(indices).toBeInstanceOf(Uint32Array);
    const vertexCount = vertices.length / 6;
    expect(vertexCount).toBeGreaterThan(65535);
    // reduce, not Math.max(...indices): 614,400 arguments overflows the call stack, and the
    // failure reads as a broken test rather than as a mesh too big for the old index width.
    const highest = indices.reduce((seen, index) => (index > seen ? index : seen), 0);
    expect(highest).toBe(vertexCount - 1); // every vertex reachable, and none wrapped to 0
  });

  it("keeps facets finer than the elevation texture it samples", () => {
    // The mesh is the resolution limit by design (cap_render CAP_ELEV_PX says so from its side).
    // At the mesh's equatorward edge — where sectors are widest — a sector must stay under the
    // texture's ~5.2 km/px times a small factor, or the cap would be visibly coarser than the
    // tiles it crossfades into however exactly the two agree in metres.
    const earthCircumferenceKm = 2 * Math.PI * 6371;
    const sectorKmAtMeshEdge = (earthCircumferenceKm * Math.cos((80 * Math.PI) / 180)) / SECTORS;
    const ringKm = (earthCircumferenceKm / 360) * (10 / RINGS);
    expect(sectorKmAtMeshEdge).toBeLessThan(15);
    expect(ringKm).toBeLessThan(15);
  });
});

describe("vertexSrc", () => {
  // What a node test can reach is the GENERATED SOURCE, not the compiled shader — there is no GL
  // context here. So these pin the thing that can drift silently: the constants the shader is
  // built from. The arithmetic itself is verified through decodeCapElevation / capDisplacementScale
  // above, which the GLSL is written to mirror line for line, and finally by looking at the globe.
  it("carries the manifest's step and MapLibre's radius rather than GLSL literals", () => {
    const source = vertexSrc({ ...OPTS, elevStep: 4 });
    expect(source).toContain("4.000000"); // the step came from the options, not from a literal 8
    expect(source).toContain(String(MAPLIBRE_GLOBE_RADIUS_M));
    expect(vertexSrc(OPTS)).toContain(TERRAIN_QUANTISATION_M.toFixed(6));
  });

  it("states its mip level, because a vertex shader has no implicit derivatives", () => {
    expect(vertexSrc(OPTS)).toMatch(/textureLod\(\s*u_elev,\s*a_uv,\s*0\.0\s*\)/);
  });

  it("clips on the displaced position, so a peak near the limb is not culled behind the horizon", () => {
    const source = vertexSrc(OPTS);
    expect(source).toMatch(/v_clip\s*=\s*dot\(u_clip\.xyz,\s*pos\)/);
    expect(source).toMatch(/gl_Position\s*=\s*u_matrix\s*\*\s*vec4\(pos,\s*1\.0\)/);
  });
});

describe("loadCapElevation", () => {
  function elevLayer(gl: unknown): CapLayer {
    return {
      id: "polar-cap-north", type: "custom", render: () => undefined,
      gl: gl as WebGL2RenderingContext,
      elevTexture: {} as WebGLTexture,
      elevLoaded: false,
    };
  }

  it("fetches the manifest's texture and samples it NEAREST, never filtered or mipmapped", async () => {
    // THE LOAD-BEARING ASSERTION IN THIS FILE. These texels are not colour: elevation is
    // (R*256 + G)*step, so green wraps every 2,048 m at our step. LINEAR filtering across a wrap
    // mixes R=16,G=255 with R=17,G=0 and decodes ~1 km from either neighbour — a phantom cliff in
    // a smooth slope, with nothing on screen to explain it. A mip chain averages the same bytes.
    // The pipeline refuses this operation on its side; this is the same rule reaching the GPU.
    const gl = fakeGl();
    stubImageLoading(gl);
    const layer = elevLayer(gl);
    await loadCapElevation(layer, OPTS, fakeMap(110));

    expect(gl.fetched).toEqual(["/caps/cap_north_elev.webp"]);
    const filters = gl.params.filter(([pname]) =>
      pname === gl.TEXTURE_MIN_FILTER || pname === gl.TEXTURE_MAG_FILTER);
    expect(filters.length).toBe(2);
    for (const [, value] of filters) expect(value).toBe(gl.NEAREST);
    expect(gl.mipmaps).toBe(0);
    expect(layer.elevLoaded).toBe(true);
  });

  it("loads once — it is one size, so there is no camera that could want another", async () => {
    const gl = fakeGl();
    stubImageLoading(gl);
    const layer = elevLayer(gl);
    const map = fakeMap(110);
    await loadCapElevation(layer, OPTS, map);
    await loadCapElevation(layer, OPTS, map);
    expect(gl.fetched.length).toBe(1);
  });

  it("degrades to a FLAT cap when the fetch fails, not to a collapsed one", async () => {
    // The placeholder decodes to 0 m, so a 404 leaves exactly the pre-displacement rendering. That
    // is the whole reason the placeholder is computed rather than written as transparent black.
    const gl = fakeGl();
    vi.stubGlobal("fetch", async () => ({ ok: false, status: 404 }));
    vi.stubGlobal("console", { ...console, error: () => undefined });
    const layer = elevLayer(gl);
    await loadCapElevation(layer, OPTS, fakeMap(110));
    expect(layer.elevLoaded).toBe(false);
    expect(gl.uploads).toEqual([]); // the placeholder was never overwritten
  });
});

// ---------------------------------------------------------------------------------------------
// Compositing. Both of this layer's visual bugs were ALPHA bugs in opposite directions — the polar
// ring (canvas made translucent where it should be opaque) and the bright polar disc (canvas left
// transparent where the cap had painted, so the browser ADDED the cap's colour to the page). Each
// fix looked safe until the other regime showed up, so the rule is pinned in both regimes.
// ---------------------------------------------------------------------------------------------

describe("compositedAlpha", () => {
  it("cannot make an already-opaque canvas translucent — the polar ring, made impossible", () => {
    // dst = 1 is the flat globe, where the background layer has filled the frame before the cap
    // draws. Exactly 1 for every source alpha, including the feather band's fractional ones, which
    // is where the ring lived.
    for (const src of [0, 0.13, 0.5, 0.87, 1]) expect(compositedAlpha(src, 1)).toBe(1);
  });

  it("makes the canvas opaque where the cap is opaque over nothing — the bright disc", () => {
    // dst = 0 is what terrain leaves poleward of the Mercator limit: `background` is one of
    // MapLibre's LAYERS_TO_TEXTURES, so with terrain on it is drawn into render tiles, and render
    // tiles stop at ±85.0511°. Leaving alpha at 0 there is what made the page show through
    // additively.
    expect(compositedAlpha(1, 0)).toBe(1);
    expect(compositedAlpha(0, 0)).toBe(0); // outside the cap, still nothing drawn — unchanged
    expect(compositedAlpha(0.25, 0)).toBe(0.25);
  });
});

describe("the cap's draw call", () => {
  /** Enough GL to run the real `render`, recording the decisions worth asserting. */
  function recordingGl() {
    const calls = { blend: null as null | number[], draw: null as null | number[], uniforms: {} as Record<string, number> };
    const constants = { TEXTURE_2D: 1, ARRAY_BUFFER: 2, ELEMENT_ARRAY_BUFFER: 3, FLOAT: 4, BLEND: 5,
      ONE: 6, ONE_MINUS_SRC_ALPHA: 7, ZERO: 8, TRIANGLES: 9, UNSIGNED_INT: 10, UNSIGNED_SHORT: 11,
      TEXTURE0: 12, TEXTURE1: 13 };
    return {
      calls, ...constants,
      useProgram: () => undefined, uniformMatrix4fv: () => undefined, uniform4f: () => undefined,
      activeTexture: () => undefined, bindTexture: () => undefined, bindBuffer: () => undefined,
      enableVertexAttribArray: () => undefined, vertexAttribPointer: () => undefined,
      disableVertexAttribArray: () => undefined, isEnabled: () => true, enable: () => undefined,
      disable: () => undefined, uniform1i: () => undefined,
      uniform1f: (location: unknown, value: number) => { calls.uniforms[String(location)] = value; },
      blendFunc: (src: number, dst: number) => { calls.blend = [src, dst, src, dst]; },
      blendFuncSeparate: (sc: number, dc: number, sa: number, da: number) => { calls.blend = [sc, dc, sa, da]; },
      drawElements: (mode: number, count: number, type: number) => { calls.draw = [mode, count, type]; },
    };
  }

  const args = { defaultProjectionData: { projectionTransition: 1, mainMatrix: new Float32Array(16),
    clippingPlane: [0, 0, 1, 0] } };

  function renderOnce(terrain?: { exaggeration: number }) {
    const gl = recordingGl();
    const harness = fakeMapWithStyle(110, fakeGl());
    (harness.map as unknown as { terrain?: unknown }).terrain = terrain;
    addPolarCap(harness.map, OPTS);
    const layer = harness.map.getLayer(OPTS.layerId) as unknown as CapLayer;
    layer.uExaggeration = "u_exaggeration" as unknown as WebGLUniformLocation;
    layer.render!(gl as unknown as WebGL2RenderingContext, args as never);
    return gl.calls;
  }

  it("blends alpha with the SAME factors as colour, so the cap writes canvas opacity", () => {
    // Asserted as a property rather than as an API spelling: blendFunc and a blendFuncSeparate
    // whose alpha factors match are both correct, and a future edit may legitimately use either.
    // What must never come back is alpha pinned to the destination (ZERO, ONE) — the cap then
    // paints colour into a fully transparent canvas, and a premultipliedAlpha canvas composites
    // that ADDITIVELY over the page. That is the bright polar disc.
    const gl = recordingGl();
    const [srcColor, dstColor, srcAlpha, dstAlpha] = renderOnce()!.blend!;
    expect([srcColor, dstColor]).toEqual([gl.ONE, gl.ONE_MINUS_SRC_ALPHA]);
    expect([srcAlpha, dstAlpha]).toEqual([srcColor, dstColor]);
  });

  it("draws with 32-bit indices, matching the buffer buildMesh emits", () => {
    const gl = recordingGl();
    expect(renderOnce()!.draw![2]).toBe(gl.UNSIGNED_INT);
  });

  it("takes exaggeration from map.terrain, and 0 when there is no terrain", () => {
    // map.terrain is the object globe.astro MUTATES on zoom — it never re-calls setTerrain, because
    // that rebuilds Terrain and RenderToTexture and leaks framebuffers. So map.getTerrain() reports
    // the spec handed in once and goes stale after the first ramp step; reading it here would
    // silently freeze the cap at the base exaggeration while the tiles ramped away from it.
    expect(renderOnce({ exaggeration: 6.25 })!.uniforms["u_exaggeration"]).toBe(6.25);
    expect(renderOnce(undefined)!.uniforms["u_exaggeration"]).toBe(0);
  });
});

describe("the context-loss recovery contract", () => {
  const globe = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");

  it("globe.astro installs the caps from style.load, not from a one-shot load", () => {
    const boundToStyleLoad = /map\.on\(\s*["']style\.load["']\s*,\s*addCaps\s*\)/.test(globe);
    expect(
      boundToStyleLoad,
      "globe.astro must install the caps from a `style.load` handler. MapLibre re-applies a " +
        "serialized style on restore and that style cannot carry a `custom` layer, so a one-shot " +
        "`load` binding leaves every rebuilt globe capless: no error, just holes at the poles.",
    ).toBe(true);
  });

  // CORRECTS THE CLAIM THIS BLOCK USED TO MAKE. It asserted the caps "survive ONLY because the
  // restore re-fires style.load". They do not survive: measured, a restore re-fires style.load and
  // the caps come back as a BLACK DISC over the pole. _contextRestored calls setStyle() at line
  // 22594 and _setupPainter() only at 22600, so a cap added from style.load binds its buffers to
  // the outgoing GL context. Present, wrong, and silent — worse than the hole it was guarding
  // against, because a hole is visible as a hole.
  it("re-adds the caps on recovery, from OUTSIDE style.load, because that ordering is too early", () => {
    expect(globe, "a recovery re-add must exist").toMatch(/reassertPolarCaps\s*=\s*\(\)\s*=>/);
    const reassert = globe.match(/reassertPolarCaps = \(\) => \{[\s\S]*?\n    \};/)?.[0];
    expect(reassert).toBeTruthy();
    // Must clear the dead layers first: addLayer throws on a duplicate id, and the layer sitting
    // there is the black-disc one.
    expect(reassert).toContain("removeLayer");
    expect(reassert).toContain("addCaps()");
  });
});
