// The caps.json contract mapping and the pure mesh math — the values the pipeline authors
// (edge_lat, feather ceiling, URLs) must flow through capOptionsFrom untouched, because the
// literals they replaced drifted silently by construction (the hero/tile constants lesson).

import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Map as MaplibreMap } from "maplibre-gl";
import {
  MOBILE_CAP_BUDGET_PX,
  RINGS,
  SECTORS,
  addPolarCap,
  buildMesh,
  canvasBackingRatio,
  capOptionsFrom,
  capProjectedExtentPx,
  capTextureBudget,
  clampedTextureSize,
  pickRung,
  rungForDemand,
  syncCapRung,
  type CapLayer,
  type CapOptions,
  type CapsManifest,
} from "./polarCaps";

// The shipped ladder (cap_render.CAP_RUNGS), so the fixture cannot drift from production.
const RUNGS = (pole: string) => [
  { px: 1024, url: `/caps/cap_${pole}_1024.webp` },
  { px: 2048, url: `/caps/cap_${pole}_2048.webp` },
  { px: 4096, url: `/caps/cap_${pole}_4096.webp` },
  { px: 8192, url: `/caps/cap_${pole}_8192.webp` },
];

const MANIFEST: CapsManifest = {
  north: { rungs: RUNGS("north"), edge_lat: 78, feather_hi: 84 },
  south: { rungs: RUNGS("south"), edge_lat: -78, feather_hi: -84 },
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
// measured on 2026-07-25 at DPR 1 (untouched default camera 110 px, north pole dragged into view at
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
// The upload oracle. The 2026-07-23 bug was not a wrong picture — it was the RIGHT picture uploaded
// up to five times, which nothing observed. Counting texImage2D is the only assertion that would
// have caught it, so the upgrade path is tested by upload count, not by appearance.
// ---------------------------------------------------------------------------------------------

interface FakeGl {
  uploads: number[];
  fetched: string[];
}

function fakeGl(): FakeGl & Record<string, unknown> {
  const uploads: number[] = [];
  return {
    uploads,
    fetched: [],
    TEXTURE_2D: 1, RGBA: 2, UNSIGNED_BYTE: 3, MAX_TEXTURE_SIZE: 4,
    TEXTURE_MIN_FILTER: 5, TEXTURE_MAG_FILTER: 6, TEXTURE_WRAP_S: 7, TEXTURE_WRAP_T: 8,
    LINEAR_MIPMAP_LINEAR: 9, LINEAR: 10, CLAMP_TO_EDGE: 11,
    getParameter: () => 16384, // a GPU that can take any rung, so the clamp never confuses the count
    bindTexture: () => undefined,
    generateMipmap: () => undefined,
    texParameteri: () => undefined,
    texImage2D: (...args: unknown[]) => {
      const image = args[args.length - 1] as { width?: number };
      if (image && typeof image.width === "number") uploads.push(image.width);
    },
  };
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

describe("the context-loss recovery contract", () => {
  it("globe.astro installs the caps from style.load — the binding recovery depends on", () => {
    const source = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");
    const boundToStyleLoad = /map\.on\(\s*["']style\.load["'][\s\S]{0,400}?addPolarCaps/.test(source);
    expect(
      boundToStyleLoad,
      "globe.astro must call addPolarCaps from a `style.load` handler. MapLibre restores a lost " +
        "WebGL context by re-applying a serialized style, which cannot carry a `custom` layer — " +
        "the caps survive ONLY because that restore re-fires `style.load`. Bound to a one-shot " +
        "`load` instead, every recovered globe is silently capless: no error, just holes at the poles.",
    ).toBe(true);
  });
});
