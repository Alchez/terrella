import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import {
  DEFAULT_TERRAIN_RAMP_FLOOR,
  MAX_TERRAIN_EXAGGERATION,
  TERRAIN_CONTENT_TYPE,
  TERRAIN_MAX_ZOOM,
  TERRAIN_PATH_TEMPLATE,
  TERRAIN_QUANTISATION_M,
  TERRAIN_RAMP_END_ZOOM,
  TERRAIN_RAMP_START_ZOOM,
  TERRAIN_TILE_EXTENSION,
  TERRAIN_TILE_SIZE,
  defaultTerrainRamp,
  describeTerrainState,
  parseTerrainExaggeration,
  parseTerrainRamp,
  parseTerrainVariant,
  rampedExaggeration,
  terrainEncoding,
} from "./terrainSource";

const flags = (search: string) => new URLSearchParams(search);

describe("the encoding matches what the pipeline writes", () => {
  it("names standard terrarium at one metre per level, with no custom factors", () => {
    // At step 1 the pipeline emits R*256 + G - 32768, which IS terrarium with blue zeroed.
    // Naming the standard encoding keeps the style free of four numbers that could drift.
    expect(terrainEncoding(1)).toEqual({ encoding: "terrarium" });
    expect(TERRAIN_QUANTISATION_M).toBe(1);
  });

  it("expresses a coarser quantisation as custom factors that decode to the same metres", () => {
    const encoding = terrainEncoding(4);
    expect(encoding.encoding).toBe("custom");
    if (encoding.encoding !== "custom") throw new Error("unreachable");
    // MapLibre computes R*red + G*green + B*blue - baseShift (dem_data.ts unpack()).
    const decode = (r: number, g: number, b: number) =>
      r * encoding.redFactor + g * encoding.greenFactor + b * encoding.blueFactor -
      encoding.baseShift;
    // 2000 m at step 4 packs as (2000 + 32768)/4 = 8692 -> R=33, G=244.
    expect(decode(33, 244, 0)).toBe(2000);
    // Blue must not contribute: the pipeline writes it as a constant, and any weight on it
    // would turn that constant into a systematic elevation offset.
    expect(decode(33, 244, 255)).toBe(2000);
  });

  it("keeps blue inert at every quantisation", () => {
    for (const step of [2, 4, 8, 16]) {
      const encoding = terrainEncoding(step);
      if (encoding.encoding !== "custom") throw new Error("unreachable");
      expect(encoding.blueFactor).toBe(0);
    }
  });
});

describe("?terrain=N", () => {
  it("reads a positive exaggeration, integer or not", () => {
    expect(parseTerrainExaggeration(flags("?terrain=15"))).toBe(15);
    expect(parseTerrainExaggeration(flags("?terrain=2.5"))).toBe(2.5);
  });

  it("is absent by default, so terrain never turns itself on", () => {
    expect(parseTerrainExaggeration(flags(""))).toBeNull();
    expect(parseTerrainExaggeration(flags("?bare"))).toBeNull();
  });

  it("refuses zero, negatives, junk and anything past the ceiling", () => {
    // Zero is refused because it is indistinguishable from off, and a run that thinks it
    // measured "terrain at 0" measured the flat globe under a different name.
    for (const raw of ["0", "-5", "", "  ", "15x", "NaN", "Infinity",
                       String(MAX_TERRAIN_EXAGGERATION + 1)]) {
      expect(parseTerrainExaggeration(flags(`?terrain=${raw}`))).toBeNull();
    }
  });

  it("accepts the ceiling itself", () => {
    expect(parseTerrainExaggeration(flags(`?terrain=${MAX_TERRAIN_EXAGGERATION}`)))
      .toBe(MAX_TERRAIN_EXAGGERATION);
  });
});

describe("?dem=clamp|bathy", () => {
  it("defaults to the clamped sea", () => {
    expect(parseTerrainVariant(flags(""))).toBe("clamp");
    expect(parseTerrainVariant(flags("?terrain=15"))).toBe("clamp");
  });

  it("selects the bathymetry build when asked", () => {
    expect(parseTerrainVariant(flags("?dem=bathy"))).toBe("bathy");
  });

  it("falls back to the default on an unrecognised value", () => {
    expect(parseTerrainVariant(flags("?dem=deep"))).toBe("clamp");
  });
});

describe("the contract", () => {
  it("is lossless, because a lossy tile decodes to wrong metres rather than to a blur", () => {
    expect(TERRAIN_TILE_EXTENSION).toBe("png");
    expect(TERRAIN_CONTENT_TYPE).toBe("image/png");
    expect(TERRAIN_PATH_TEMPLATE).toBe("{z}/{x}/{y}.png");
  });

  it("declares its true 512 px tile size, unlike the relief source's deliberate 256", () => {
    // The relief source declares 512 px assets as tileSize 256 to centre on DPR 2. Terrain wants
    // the opposite — an honest 512 fetches at the map zoom, and MapLibre's own deltaZoom = 1 for
    // terrain takes it one lower again, so at map z7 it is terrain z6 against colour z8.
    expect(TERRAIN_TILE_SIZE).toBe(512);
    const relief = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");
    expect(relief).toContain("tileSize: 256");
  });

  it("stops shallower than the colour pyramid, which is a size lever and not a defect", () => {
    expect(TERRAIN_MAX_ZOOM).toBeLessThan(8);
  });
});

describe("the zoom ramp", () => {
  it("holds the base over the whole overview, where displacement is near-invisible anyway", () => {
    expect(rampedExaggeration(15, 0, 4)).toBe(15);
    expect(rampedExaggeration(15, TERRAIN_RAMP_START_ZOOM, 4)).toBe(15);
    expect(rampedExaggeration(15, TERRAIN_RAMP_START_ZOOM - 0.5, 4)).toBe(15);
  });

  it("holds the floor at and past the camera's own ceiling", () => {
    expect(rampedExaggeration(15, TERRAIN_RAMP_END_ZOOM, 4)).toBe(4);
    expect(rampedExaggeration(15, TERRAIN_RAMP_END_ZOOM + 3, 4)).toBe(4);
  });

  it("decays monotonically in between, with no step at either join", () => {
    const at = (zoom: number) => rampedExaggeration(15, zoom, 4);
    const samples = [3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5, 8].map(at);
    for (let index = 1; index < samples.length; index += 1) {
      expect(samples[index]).toBeLessThan(samples[index - 1]);
    }
    // Continuity at the joins is what stops a visible pop as the camera crosses them.
    expect(at(TERRAIN_RAMP_START_ZOOM + 1e-9)).toBeCloseTo(15, 6);
    expect(at(TERRAIN_RAMP_END_ZOOM - 1e-9)).toBeCloseTo(4, 6);
  });

  it("is geometric, not linear — the midpoint is the geometric mean", () => {
    // Facet slope scales with exaggeration, so the perceived step between zooms is a ratio.
    // A linear ramp would give (15+4)/2 = 9.5 here; the geometric one gives sqrt(60) = 7.75.
    const middle = (TERRAIN_RAMP_START_ZOOM + TERRAIN_RAMP_END_ZOOM) / 2;
    expect(rampedExaggeration(15, middle, 4)).toBeCloseTo(Math.sqrt(15 * 4), 10);
  });

  it("keeps a constant per-level factor, which is the property that makes it scale-free", () => {
    const at = (zoom: number) => rampedExaggeration(15, zoom, 4);
    const first = at(5) / at(4);
    for (const zoom of [5, 6, 7]) {
      expect(at(zoom + 1) / at(zoom)).toBeCloseTo(first, 10);
    }
  });

  it("decays at the rate that holds apparent slope constant, not merely at a plausible one", () => {
    // The load-bearing number. Elevation change across a mesh facet goes as ~width^0.5 and the
    // facet halves per zoom level, so slope stays put only if exaggeration falls by 2^-0.5 per
    // level. This is what makes the DEFAULT floor a derived value rather than a preference: the
    // earlier 0.768 looked fine for a level or two and had drifted the 99th-percentile facet
    // from ~45deg to ~58deg by z8. A change to the floor or the zoom span must keep this true.
    const perLevel =
      rampedExaggeration(15, 6, DEFAULT_TERRAIN_RAMP_FLOOR) /
      rampedExaggeration(15, 5, DEFAULT_TERRAIN_RAMP_FLOOR);
    // Within 2%: the exactly scale-invariant floor from 15x over five levels is 15*2^-2.5 =
    // 2.652, and 2.5 is that rounded to a number a person can type into ?ramp. The 1.1% the
    // rounding costs is far inside what an eye resolves; a floor that missed by 10% would not be.
    expect(Math.abs(perLevel / Math.SQRT1_2 - 1)).toBeLessThan(0.02);
  });

  it("degenerates cleanly when floor equals base, so ?ramp=15 is a valid control", () => {
    for (const zoom of [0, 3, 5.5, 8, 12]) {
      expect(rampedExaggeration(15, zoom, 15)).toBeCloseTo(15, 10);
    }
  });

  it("defaults its floor to the shared constant rather than to a literal", () => {
    expect(rampedExaggeration(15, 8)).toBe(DEFAULT_TERRAIN_RAMP_FLOOR);
  });
});

describe("?ramp=off|<floor>", () => {
  it("ramps by default, so the flag is opt-out rather than opt-in", () => {
    expect(parseTerrainRamp(flags(""))).toEqual({ kind: "ramp", floor: DEFAULT_TERRAIN_RAMP_FLOOR });
    expect(parseTerrainRamp(flags("?terrain=15"))).toEqual({
      kind: "ramp",
      floor: DEFAULT_TERRAIN_RAMP_FLOOR,
    });
  });

  it("reads off as the constant-exaggeration control arm, case-insensitively", () => {
    expect(parseTerrainRamp(flags("?ramp=off"))).toEqual({ kind: "off" });
    expect(parseTerrainRamp(flags("?ramp=OFF"))).toEqual({ kind: "off" });
  });

  it("reads a floor to sweep", () => {
    expect(parseTerrainRamp(flags("?ramp=2"))).toEqual({ kind: "ramp", floor: 2 });
    expect(parseTerrainRamp(flags("?ramp=6.5"))).toEqual({ kind: "ramp", floor: 6.5 });
  });

  it("refuses a malformed value loudly rather than silently sweeping the default", () => {
    for (const search of ["?ramp=0", "?ramp=-3", "?ramp=abc", `?ramp=${MAX_TERRAIN_EXAGGERATION + 1}`]) {
      expect(parseTerrainRamp(flags(search))).toBeNull();
    }
  });

  it("treats a bare ?ramp as absent, not as malformed", () => {
    // `?ramp` with no value is a plausible typo for the default, and defaulting is what it means.
    expect(parseTerrainRamp(flags("?ramp"))).toEqual({
      kind: "ramp",
      floor: DEFAULT_TERRAIN_RAMP_FLOOR,
    });
  });

  it("hands back a fresh default each time, so one caller cannot mutate another's", () => {
    const first = defaultTerrainRamp();
    if (first.kind !== "ramp") throw new Error("unreachable");
    first.floor = 99;
    expect(defaultTerrainRamp()).toEqual({ kind: "ramp", floor: DEFAULT_TERRAIN_RAMP_FLOOR });
  });
});

describe("the ?perf terrain line", () => {
  it("names the live exaggeration and the arm, so a screenshot describes itself", () => {
    expect(describeTerrainState(5.9466, 15, { kind: "ramp", floor: 4 })).toBe(
      "terrain 5.9x · ramp 15→4",
    );
  });

  it("distinguishes the control arm from a ramp that happens to be at its base", () => {
    // Both read 15x at z3. Without the arm, two different runs produce identical screenshots.
    expect(describeTerrainState(15, 15, { kind: "off" })).toBe("terrain 15.0x · ramp off");
    expect(describeTerrainState(15, 15, { kind: "ramp", floor: 4 })).toBe(
      "terrain 15.0x · ramp 15→4",
    );
  });

  it("says pending, not off, before the style has attached terrain", () => {
    // The line only exists when terrain was requested, so "off" would be a lie during the gap
    // between page script and style.load.
    expect(describeTerrainState(null, 15, { kind: "ramp", floor: 4 })).toBe(
      "terrain pending · ramp 15→4",
    );
  });
});

describe("source guard — the pipeline is the source of truth for the numbers", () => {
  it("applies the ramp by uniform, never by re-calling setTerrain", () => {
    // ui/map.ts builds a fresh Terrain and RenderToTexture on every setTerrain call and only
    // reaches Terrain.destroy() on the removal path. Calling it from a zoom handler would leak a
    // framebuffer pair per zoom step and discard the mesh cache; exaggeration is a per-frame
    // uniform, so the assignment below is the whole mechanism. Exactly one call must exist.
    const globe = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");
    expect(globe.match(/map\.setTerrain\(/g)).toHaveLength(1);
    expect(globe).toContain("map.terrain.exaggeration = next");
  });

  it("keeps the pipeline's quantisation default and this module's in step", () => {
    // Two files, one fact. The pipeline writes the bytes; this module tells MapLibre how to read
    // them, and a mismatch is silent: every tile decodes, to the wrong altitude.
    const pipeline = readFileSync(
      new URL("../../../pipeline/tile/terrain_rgb.py", import.meta.url), "utf8");
    expect(pipeline).toContain('ap.add_argument("--step", type=float, default=1.0');
    expect(pipeline).toContain("BASE_SHIFT = 32768.0");
  });
});
