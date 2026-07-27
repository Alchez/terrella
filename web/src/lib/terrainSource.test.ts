import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import {
  DEFAULT_TERRAIN_RAMP_FLOOR,
  MAX_TERRAIN_EXAGGERATION,
  TERRAIN_CONTENT_TYPE,
  TERRAIN_MAX_ZOOM,
  TERRAIN_PATH_TEMPLATE,
  TERRAIN_QUANTISATION_M,
  TERRAIN_QUANTISATION_STEPS,
  TERRAIN_RAMP_END_ZOOM,
  TERRAIN_RAMP_START_ZOOM,
  TERRAIN_TILE_EXTENSION,
  TERRAIN_TILE_FORMATS,
  TERRAIN_TILE_SIZE,
  defaultTerrainRamp,
  parseTerrainTileSize,
  terrainZoomsFor,
  describeTerrainState,
  parseTerrainExaggeration,
  parseTerrainFormat,
  parseTerrainQuantisation,
  parseTerrainRamp,
  parseTerrainVariant,
  rampedExaggeration,
  terrainBuildDirectory,
  terrainEncoding,
  terrainPathTemplate,
} from "./terrainSource";

const flags = (search: string) => new URLSearchParams(search);

describe("the encoding matches what the pipeline writes", () => {
  it("names standard terrarium at one metre per level, with no custom factors", () => {
    // At step 1 the pipeline emits R*256 + G - 32768, which IS terrarium with blue zeroed.
    // Naming the standard encoding keeps the style free of four numbers that could drift.
    // Kept although we no longer ship step 1, because `?quant=1` still selects that build.
    expect(terrainEncoding(1)).toEqual({ encoding: "terrarium" });
  });

  it("ships 8 m, which is the knee of the size curve and not a round number someone liked", () => {
    // 0.49x the archive. Nearly free because quantisation error is largest where displacement is
    // smallest: five cameras under the shipping ramp read 0.011-0.145 mean DN against a ~1 DN
    // floor, LOWEST on the plain. Only affordable because our shading is baked into the colour
    // tiles rather than computed from this DEM. 16 m buys another 0.74x and is past the knee.
    expect(TERRAIN_QUANTISATION_M).toBe(8);
    const shipped = terrainEncoding();
    expect(shipped.encoding).toBe("custom");
    if (shipped.encoding !== "custom") throw new Error("unreachable");
    expect(shipped.redFactor).toBe(256 * 8);
    expect(shipped.greenFactor).toBe(8);
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
  it("defaults to the sea treatment Step 0 actually ratified", () => {
    // Was "clamp" while both were candidates. Leaving it there after bathymetry won would make
    // every unflagged capture measure the rejected arm — a default that silently contradicts a
    // decision is worse than no default.
    expect(parseTerrainVariant(flags(""))).toBe("bathy");
    expect(parseTerrainVariant(flags("?terrain=15"))).toBe("bathy");
  });

  it("selects the clamped build when asked", () => {
    expect(parseTerrainVariant(flags("?dem=clamp"))).toBe("clamp");
  });

  it("falls back to the default on an unrecognised value", () => {
    expect(parseTerrainVariant(flags("?dem=deep"))).toBe("bathy");
  });
});

describe("?quant=1|2|4|8", () => {
  it("defaults to whatever the pipeline currently writes", () => {
    expect(parseTerrainQuantisation(flags(""))).toBe(TERRAIN_QUANTISATION_M);
    expect(parseTerrainQuantisation(flags("?terrain=15"))).toBe(TERRAIN_QUANTISATION_M);
  });

  it("reads every step that was built", () => {
    for (const step of TERRAIN_QUANTISATION_STEPS) {
      expect(parseTerrainQuantisation(flags(`?quant=${step}`))).toBe(step);
    }
  });

  it("refuses a step that was never built, rather than decoding at the wrong scale", () => {
    // The whole reason this returns null instead of falling back: a build fetched at one step and
    // decoded at another still 200s on every tile and still renders. There is no symptom except a
    // planet wrong by that ratio, so the flag has to complain rather than guess.
    expect(parseTerrainQuantisation(flags("?quant=3"))).toBeNull();
    expect(parseTerrainQuantisation(flags("?quant=16"))).toBeNull();
    expect(parseTerrainQuantisation(flags("?quant=eight"))).toBeNull();
    expect(parseTerrainQuantisation(flags("?quant=0"))).toBeNull();
  });

  it("treats a bare ?quant as absent, not as malformed", () => {
    expect(parseTerrainQuantisation(flags("?quant="))).toBe(TERRAIN_QUANTISATION_M);
  });
});

describe("?demfmt=png|webp", () => {
  it("defaults to the shipping extension", () => {
    expect(parseTerrainFormat(flags(""))).toBe(TERRAIN_TILE_EXTENSION);
  });

  it("reads both lossless codecs", () => {
    for (const format of TERRAIN_TILE_FORMATS) {
      expect(parseTerrainFormat(flags(`?demfmt=${format}`))).toBe(format);
    }
  });

  it("refuses anything else, loudly", () => {
    expect(parseTerrainFormat(flags("?demfmt=jpeg"))).toBeNull();
    expect(parseTerrainFormat(flags("?demfmt=webp2"))).toBeNull();
  });
});

describe("the build directory", () => {
  it("names the default build with no suffixes at all", () => {
    expect(terrainBuildDirectory("bathy", 1, "png")).toBe("bathy");
    expect(terrainBuildDirectory("clamp", 1, "png")).toBe("clamp");
  });

  it("suffixes the quantisation and the codec, matching terrain_rgb.py --out on disk", () => {
    expect(terrainBuildDirectory("bathy", 8, "png")).toBe("bathy_s8");
    expect(terrainBuildDirectory("bathy", 8, "webp")).toBe("bathy_s8_webp");
    expect(terrainBuildDirectory("bathy", 2, "webp")).toBe("bathy_s2_webp");
  });

  it("stays inside the dev route's own character class, so a build cannot 404 on its name", () => {
    const route = readFileSync(new URL("../../astro.config.ts", import.meta.url), "utf8");
    const characterClass = /\[a-z0-9_\]\{1,(\d+)\}/.exec(route);
    expect(characterClass).not.toBeNull();
    const longest = terrainBuildDirectory("bathy", 8, "webp");
    expect(longest).toMatch(/^[a-z0-9_]+$/);
    expect(longest.length).toBeLessThanOrEqual(Number(characterClass?.[1]));
  });

  it("templates the path on the codec, agreeing with the constant at the default", () => {
    expect(terrainPathTemplate("png")).toBe("{z}/{x}/{y}.png");
    expect(terrainPathTemplate("webp")).toBe("{z}/{x}/{y}.webp");
    expect(terrainPathTemplate(TERRAIN_TILE_EXTENSION)).toBe(TERRAIN_PATH_TEMPLATE);
  });
});

describe("the contract", () => {
  it("is lossless, because a lossy tile decodes to wrong metres rather than to a blur", () => {
    // The requirement is losslessness, NOT png. Lossless WebP meets it at 0.67x the bytes,
    // measured whole-pyramid and proven byte-identical through GDAL, the browser's own decode
    // and the rendered frame. If this ever reads a lossy codec, elevation is silently wrong.
    expect(TERRAIN_TILE_FORMATS).toContain(TERRAIN_TILE_EXTENSION);
    expect(TERRAIN_TILE_EXTENSION).toBe("webp");
    expect(TERRAIN_CONTENT_TYPE).toBe("image/webp");
    expect(TERRAIN_PATH_TEMPLATE).toBe("{z}/{x}/{y}.webp");
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

describe("?demsize=256|512 and the zoom arithmetic behind it", () => {
  it("defaults to the shipped declaration and refuses anything unbuilt", () => {
    expect(parseTerrainTileSize(flags(""))).toBe(TERRAIN_TILE_SIZE);
    expect(parseTerrainTileSize(flags("?demsize=256"))).toBe(256);
    expect(parseTerrainTileSize(flags("?demsize=512"))).toBe(512);
    expect(parseTerrainTileSize(flags("?demsize=1024"))).toBeNull();
    expect(parseTerrainTileSize(flags("?demsize=big"))).toBeNull();
  });

  it("reproduces what a live map actually did at camera z6 with 512 declared", () => {
    // Measured 2026-07-27 against a running globe: four render tiles at z5, all resolving through
    // getSourceTile to ONE DEM tile at z4 (dim 512, stride 514). If this ever disagrees with the
    // map again, the internals moved — see the canary below.
    expect(terrainZoomsFor(6, 512)).toEqual({ renderZoom: 5, demZoom: 4 });
  });

  it("returns the NOMINAL zoom — the globe's covering set is mixed, and this does not model that", () => {
    // Same camera, declared 256: measured 9 render tiles at the nominal z6 plus 3 at z5 (globe
    // projection allows variable zoom toward the limb), consuming DEM z5 and z4. The nominal pair
    // is what this function returns; anyone sizing a request budget off it must treat the square
    // as an upper bound — observed was 12 render tiles vs 4, i.e. 3x rather than 4x.
    expect(terrainZoomsFor(6, 256)).toEqual({ renderZoom: 6, demZoom: 5 });
  });

  it("shifts both zooms up exactly one when 256 is declared, which is the whole of axis B", () => {
    for (const cameraZoom of [4, 5, 6, 7]) {
      const honest = terrainZoomsFor(cameraZoom, 512, 8);
      const misdeclared = terrainZoomsFor(cameraZoom, 256, 8);
      expect(misdeclared.renderZoom).toBe(honest.renderZoom + 1);
      expect(misdeclared.demZoom).toBe(honest.demZoom + 1);
    }
  });

  it("clamps the DEM at the pyramid ceiling, which is what caps the 256 lever", () => {
    // At the camera's own maxZoom of 8, declaring 256 wants DEM z7 — which does not exist while
    // TERRAIN_MAX_ZOOM is 6. The lever is partly spent at the deepest camera until the pyramid
    // grows, and growing it means re-deriving 65536^2 from the master, not another re-cut.
    expect(terrainZoomsFor(8, 256).demZoom).toBe(TERRAIN_MAX_ZOOM);
    expect(terrainZoomsFor(8, 512).demZoom).toBe(TERRAIN_MAX_ZOOM);
    expect(terrainZoomsFor(8, 256, 7).demZoom).toBe(7);
  });

  it("never returns a negative zoom at the overview", () => {
    expect(terrainZoomsFor(0, 512).renderZoom).toBe(0);
    expect(terrainZoomsFor(0, 512).demZoom).toBe(0);
  });
});

describe("canary — MapLibre internals we depend on that the docs do not cover", () => {
  // The style spec documents exactly `source` and `exaggeration` for terrain, and describes
  // `tileSize` only as "the minimum visual size to display tiles" with no mention of zoom
  // selection. Everything terrainZoomsFor() encodes is read out of the bundle. A minor MapLibre
  // release could change any of it with no error and no visible break — geometry resolution would
  // simply halve or double. These read the SHIPPED bundle (property names survive minification),
  // so an upgrade that moves them fails here rather than in a look test months later.
  const bundle = readFileSync(
    new URL("../../node_modules/maplibre-gl/dist/maplibre-gl.mjs", import.meta.url), "utf8");

  it("still doubles the declared tile size for the terrain tile manager", () => {
    expect(bundle).toMatch(/tileSize\s*=\s*\w+\._source\.tileSize\s*\*\s*2\s*\*\*\s*this\.deltaZoom/);
    expect(bundle).toMatch(/deltaZoom\s*=\s*1\b/);
  });

  it("still meshes at 128, which 16-bit indices make a hard ceiling", () => {
    // 129^2 = 16,641 vertices fits a uint16 index buffer; meshSize 256 would need 257^2 = 66,049
    // and overflow it. So this is not a tunable — it is the largest power of two that fits.
    expect(bundle).toMatch(/meshSize\s*=\s*128\b/);
  });

  it("still oversamples render-to-texture by 2, which is why rttSize is 2048 and not 1024", () => {
    // MapLibre's own class doc says 1024; the code multiplies the ALREADY-doubled manager size.
    // Trust the arithmetic, not the comment.
    expect(bundle).toMatch(/qualityFactor\s*=\s*2\b/);
    expect(bundle).toMatch(/rttSize\s*=\s*\w+\.tileManager\.tileSize\s*\*\s*\w+\.qualityFactor/);
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

  it("threads ONE quantisation and ONE codec into the path and the decode together", () => {
    // The failure this exists for is silent and total: fetch a build cut at 8 m, decode it with
    // 1 m factors, and every tile still 200s, still decodes, still renders — a planet eight times
    // too flat with nothing in the console. So the directory, the extension and the unpack factors
    // must all be derived from the same two parsed values, and `terrainEncoding()` must never be
    // called bare (its default is the shipping step, which silently ignores ?quant).
    const globe = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");
    expect(globe).toContain("terrainBuildDirectory(variant, quantisation, format)");
    expect(globe).toContain("terrainEncoding(quantisation)");
    expect(globe).toContain("terrainPathTemplate(format)");
    expect(globe).toContain("/terrain/${build}/");
    expect(globe).not.toMatch(/terrainEncoding\(\s*\)/);
  });

  it("keeps both delivery codecs lossless in the pipeline", () => {
    // Elevation is not an image: a lossy re-encode produces plausible bytes and therefore wrong
    // metres, with no blur to notice and no error to catch. WebP is here for entropy coding only.
    const pipeline = readFileSync(
      new URL("../../../pipeline/tile/terrain_rgb.py", import.meta.url), "utf8");
    expect(pipeline).toContain('"webp": ("WEBP", ["LOSSLESS=YES"])');
    expect(pipeline).not.toMatch(/QUALITY=/);
  });

  it("keeps the pipeline's quantisation default and this module's in step", () => {
    // Two files, one fact. The pipeline writes the bytes; this module tells MapLibre how to read
    // them, and a mismatch is silent: every tile decodes, to the wrong altitude.
    const pipeline = readFileSync(
      new URL("../../../pipeline/tile/terrain_rgb.py", import.meta.url), "utf8");
    expect(pipeline).toContain('ap.add_argument("--step", type=float, default=8.0');
    expect(pipeline).toContain('default="webp"');
    expect(pipeline).toContain("BASE_SHIFT = 32768.0");
  });
});
