import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { PUBLISHED } from "./tileAddress";
import {
  DEFAULT_TERRAIN_EXAGGERATION,
  DEFAULT_TERRAIN_RAMP_FLOOR,
  defaultTerrainRamp,
  describeTerrainState,
  describeTerrainTileTypeMismatch,
  MAX_TERRAIN_EXAGGERATION,
  parseTerrainExaggeration,
  parseTerrainRamp,
  parseTerrainSkirt,
  parseTerrainTilePath,
  parseTerrainTileSize,
  rampedExaggeration,
  resolveTerrainExaggeration,
  TERRAIN_CONTENT_TYPE,
  TERRAIN_MAX_ZOOM,
  TERRAIN_OFF,
  TERRAIN_PATH_PREFIX,
  TERRAIN_QUANTISATION_M,
  TERRAIN_RAMP_END_ZOOM,
  TERRAIN_RAMP_START_ZOOM,
  TERRAIN_SKIRT_DEFAULT,
  TERRAIN_SKIRT_MODES,
  TERRAIN_TILE_EXTENSION,
  TERRAIN_TILE_SIZE,
  terrainEncoding,
  terrainZoomsFor,
} from "./terrainSource";
import { parseTilePath } from "./reliefTiles";

/** The shipping ramp sampled at one zoom: base 15x, full-strength through z4.
 *
 *  Module-level because two tests below sample the SAME curve — one for monotonicity, one for the
 *  constant per-level factor — and a second copy of these arguments could drift into describing a
 *  different curve while both tests still passed. */
const at = (zoom: number) => rampedExaggeration(15, zoom, 4);

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

describe("the archive replaced four flags, and the answers outlive them", () => {
  // ?dem, ?quant, ?demfmt and ?demdepth each named a BUILD DIRECTORY under planet_terrain, and
  // one PMTiles archive has no directories to choose between. These tests replace theirs: what
  // the flags settled is now a constant, and a constant is what the pipeline has to agree with.
  //
  // Rewritten rather than deleted, per the repo's rule about tests that carry a rationale — the
  // reasoning below is the whole reason the retired defaults were the values they were.

  it("ships the sea treatment, quantisation, codec and depth the A/Bs actually chose", () => {
    // bathymetry (Step 0, judged by eye), 8 m (the knee of the size curve), lossless WebP
    // (0.67x PNG, byte-exact) and z0-8 (what made the 128 declaration spendable). Each of these
    // was a default someone could have got wrong silently, which is why they were flags first.
    expect(TERRAIN_QUANTISATION_M).toBe(8);
    expect(TERRAIN_TILE_EXTENSION).toBe("webp");
    expect(TERRAIN_MAX_ZOOM).toBe(8);
    expect(TERRAIN_CONTENT_TYPE).toBe(`image/${TERRAIN_TILE_EXTENSION}`);
  });

  it("leaves no way to ask the globe for a build directory", () => {
    // The retired flags are gone from BOTH sides or from neither: a parser with no caller is dead
    // code, and a caller with no parser is a crash. The globe is where it would show.
    //
    // Keyed on CODE, never on the flag spelling — the first draft searched for the literal
    // "?quant" and went red against a comment in earth.astro explaining what had been retired. A
    // guard that cannot tell an identifier from prose punishes documenting the decision.
    const globe = readFileSync(new URL("../pages/earth.astro", import.meta.url), "utf8");
    const retiredCalls = [
      "parseTerrainVariant",
      "parseTerrainQuantisation",
      "parseTerrainFormat",
      "parseTerrainPyramidDepth",
      "terrainBuildDirectory",
      "terrainPathTemplate",
    ];
    for (const call of retiredCalls) {
      expect(globe, `${call} resolves a build directory that no longer exists`).not.toContain(
        `${call}(`,
      );
    }
    for (const flag of ["dem", "quant", "demfmt", "demdepth"]) {
      expect(globe, `?${flag} is read but can no longer select anything`).not.toContain(
        `urlFlags.get("${flag}")`,
      );
    }
  });

  it("addresses ONE archive, not a directory under a spike route", () => {
    // The spike served /terrain/<build>/{z}/{x}/{y} off loose tiles from location.origin. Both
    // halves of that are retired: the build segment, and the same-origin assumption that would
    // send production's DEM requests at the site Worker instead of the tile Worker.
    const globe = readFileSync(new URL("../pages/earth.astro", import.meta.url), "utf8");
    expect(globe).toContain('tileUrlTemplate(body.slug, "terrain")');
    expect(globe, "the DEM base must follow the tile hostname").not.toContain(
      "location.origin}/terrain",
    );
  });
});

describe("the path contract — the layer segment is the only discriminator left", () => {
  it("keeps the prefix its own parser reads, which is the legacy grammar's discriminator", () => {
    // Nothing the browser asks for carries this prefix any more: tileAddress.ts builds those as
    // `{body}/terrain/{token}/…`, where `terrain` is the LAYER segment and does the same job with
    // a body and a cut beside it. The prefix survives because `parseTerrainTilePath` is still what
    // accepts the shape a page built before the switch is asking for, and it goes when that does.
    expect(TERRAIN_PATH_PREFIX).toBe("terrain");
    expect(parseTerrainTilePath(`${TERRAIN_PATH_PREFIX}/8/189/107.${TERRAIN_TILE_EXTENSION}`)).toEqual(
      { z: 8, x: 189, y: 107 },
    );
  });

  it("parses a terrain address, with or without a leading slash", () => {
    expect(parseTerrainTilePath("/terrain/8/189/107.webp")).toEqual({ z: 8, x: 189, y: 107 });
    expect(parseTerrainTilePath("terrain/0/0/0.webp")).toEqual({ z: 0, x: 0, y: 0 });
  });

  it("REFUSES a bare relief address, which is the failure with no symptom", () => {
    // This is the test the whole prefix exists for. Both archives are lossless WebP over z0-8 on
    // one tiling scheme, so /8/189/107.webp is a valid address in both — and serving colour where
    // elevation was asked for does not 404 or throw: MapLibre decodes relief bytes as terrarium
    // metres and displaces the globe by whatever they happen to mean.
    expect(parseTerrainTilePath("/8/189/107.webp")).toBeNull();
    expect(parseTilePath("/terrain/8/189/107.webp")).toBeNull();
  });

  it("cannot both-match any path, in either direction", () => {
    for (const path of [
      "/0/0/0.webp",
      "/terrain/0/0/0.webp",
      "/8/189/107.webp",
      "/terrain/8/189/107.webp",
    ]) {
      const matches = [parseTilePath(path), parseTerrainTilePath(path)].filter(Boolean);
      expect(matches, `${path} must resolve to exactly one archive`).toHaveLength(1);
    }
  });

  it("rejects a tile outside the 2^z grid rather than range-reading 2.6 GB for a typo", () => {
    expect(parseTerrainTilePath("/terrain/0/1/0.webp")).toBeNull();
    expect(parseTerrainTilePath("/terrain/8/256/0.webp")).toBeNull();
    expect(parseTerrainTilePath(`/terrain/${TERRAIN_MAX_ZOOM + 1}/0/0.webp`)).toBeNull();
  });

  it("rejects the extension it does not serve, and directory traversal", () => {
    expect(parseTerrainTilePath("/terrain/8/189/107.png")).toBeNull();
    expect(parseTerrainTilePath("/terrain/../8/189/107.webp")).toBeNull();
    expect(parseTerrainTilePath("/terrain/bathy_s8_webp/8/189/107.webp")).toBeNull();
  });

  it("names the encoding check after its own constant, so a drift message is actionable", () => {
    expect(describeTerrainTileTypeMismatch(`.${TERRAIN_TILE_EXTENSION}`)).toBeNull();
    expect(describeTerrainTileTypeMismatch(".png")).toMatch(/LOSSLESS/);
  });
});

describe("the contract", () => {
  it("is lossless, because a lossy tile decodes to wrong metres rather than to a blur", () => {
    // The requirement is losslessness, NOT png. Lossless WebP meets it at 0.67x the bytes,
    // measured whole-pyramid and proven byte-identical through GDAL, the browser's own decode
    // and the rendered frame. If this ever reads a lossy codec, elevation is silently wrong.
    expect(TERRAIN_TILE_EXTENSION).toBe("webp");
    expect(TERRAIN_CONTENT_TYPE).toBe("image/webp");
  });

  it("declares a QUARTER of its true 512 px size, which is the whole of the axis-B decision", () => {
    // Both sources misdeclare, for different reasons. Relief declares 512 px assets as 256 to
    // centre on DPR 2 — a sharpness trick. Terrain declares 128 so a render tile covers a quarter
    // of the ground, which is the only way to shrink a facet: meshSize is hardcoded at 128 quads
    // per tile, so covering less ground per tile is the sole lever.
    //
    // Was 512 ("declared honestly"). Ratified by eye at z8 pitch 60,
    // affordable because GPU frame cost is FLAT across declarations (3.87 / 4.54 / 4.31 ms at
    // 512 / 256 / 128, Chrome, DPR control passed) — rttSize halves as tile count doubles.
    expect(TERRAIN_TILE_SIZE).toBe(128);
    expect(TERRAIN_TILE_SIZE).toBeLessThan(512); // the asset is 512; this is a misdeclaration
    const relief = readFileSync(new URL("../pages/earth.astro", import.meta.url), "utf8");
    expect(relief).toContain("tileSize: 256");
  });

  it("now matches the colour pyramid's depth, because the declaration made depth spendable", () => {
    // Was deliberately shallower while tileSize was 512: the DEM sits at camera-2, so against a
    // maxZoom-8 camera nothing past z6 could ever load and z7/z8 would have been dead bytes.
    // At 128 the DEM sits at camera, so the full depth is reachable — and z8 is the master's own
    // grid, so this is the ceiling rather than a step on the way to more.
    expect(TERRAIN_MAX_ZOOM).toBe(8);
    const pipeline = readFileSync(
      new URL("../../../pipeline/tile/terrain_rgb.py", import.meta.url), "utf8");
    expect(pipeline).toContain("MASTER_ZOOM = 8");
    expect(pipeline).toContain('"--max-zoom", type=int, default=8');
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

describe("?skirt=auto|none — which seam artifact you get", () => {
  it("defaults to the ratified \"none\", NOT to MapLibre's default", () => {
    // Ratified by eye, in motion: "none" removes essentially all the pan-time
    // tearing, trading it for tiny black specks that appear ONLY on drastic elevation changes and
    // never on flatland. That distribution is the LOD crack showing itself — it is widest exactly
    // where elevation changes fastest between two DEM levels.
    expect(TERRAIN_SKIRT_DEFAULT).toBe("none");
    expect(parseTerrainSkirt(flags(""))).toBe("none");
    expect(parseTerrainSkirt(flags("?skirt=none"))).toBe("none");
    expect(parseTerrainSkirt(flags("?skirt=auto"))).toBe("auto"); // the escape back to skirts
    // There is no length control — MapLibre's option is a two-value enum, so a number is not
    // "a shorter skirt", it is a typo that would otherwise silently render the default.
    expect(parseTerrainSkirt(flags("?skirt=0"))).toBeNull();
    expect(parseTerrainSkirt(flags("?skirt=short"))).toBeNull();
    expect([...TERRAIN_SKIRT_MODES]).toEqual(["auto", "none"]);
  });

  it("reaches the Map CONSTRUCTOR, because a skirt is baked into the cached mesh", () => {
    // Not settable on a live map: getTerrainMesh caches per tile and _buildSkirts runs at build
    // time, so anything that toggles this after construction is reaching into _meshCache. If this
    // ever moves to a post-construction call it will look like it works and change nothing.
    const globe = readFileSync(new URL("../pages/earth.astro", import.meta.url), "utf8");
    expect(globe).toContain("terrainSkirtLength: terrainSkirtMode");
    const constructorAt = globe.indexOf("new maplibregl.Map({");
    expect(constructorAt).toBeGreaterThan(-1);
    expect(globe.indexOf("const terrainSkirtMode =")).toBeLessThan(constructorAt);
  });
});

describe("the pyramid depth the source is allowed to reach", () => {
  it("declares its maxzoom from the archive's own depth, with nothing left to disagree", () => {
    // `?demdepth` used to pick a build directory AND the source's maxzoom, and its whole risk was
    // that the two could disagree: a deep directory declared 6 silently never requests the levels
    // it paid to build, and a shallow one declared 8 404s every tile past z6. With one archive
    // there is one number, which is the structural version of that guarantee.
    const globe = readFileSync(new URL("../pages/earth.astro", import.meta.url), "utf8");
    const source = globe.slice(globe.indexOf("type: \"raster-dem\""));
    expect(source.slice(0, 400)).toContain("maxzoom: TERRAIN_MAX_ZOOM");
    expect(TERRAIN_MAX_ZOOM).toBe(8);
  });

  it("is what makes 256 and 128 mean anything at the deepest camera", () => {
    // The whole reason the deep build was cut. Against the z0-6 pyramid every arm bottoms out on
    // z6 at camera z8, so the declaration buys mesh density and nothing else. Against z0-8 the
    // three arms finally separate — one DEM level each.
    expect(terrainZoomsFor(8, 512, 6).demZoom).toBe(6);
    expect(terrainZoomsFor(8, 256, 6).demZoom).toBe(6); // clamped: asked z7, pyramid stopped at 6
    expect(terrainZoomsFor(8, 128, 6).demZoom).toBe(6); // clamped harder: asked z8

    expect(terrainZoomsFor(8, 512, 8).demZoom).toBe(6); // 512 can NEVER reach past z6 at maxZoom 8
    expect(terrainZoomsFor(8, 256, 8).demZoom).toBe(7);
    expect(terrainZoomsFor(8, 128, 8).demZoom).toBe(8);
    // ...but this is the NOMINAL zoom, and the globe does not always grant it. Measured on a live
    // map at camera z8 against the deep pyramid: 512 -> z6 and 256 -> z7 at every pitch, while
    // 128 gets its z8 only at pitch 0 and 30 and drops to z7 at pitch 60. See the pitch test below.
  });

  it("does not model the globe's pitch penalty, which costs 128 a whole DEM level", () => {
    // MEASURED 2026-07-28, camera z8, deep pyramid, deepest DEM actually consumed:
    //          pitch 0   pitch 30   pitch 60
    //   512       z6        z6         z6
    //   256       z7        z7         z7
    //   128       z8        z8         z7   <- the nominal says z8 at all three
    //
    // Cause is MapLibre's globe LOD heuristic, not our arithmetic: coveringTiles takes a per-tile
    // desired zoom from defaultCalculateTileZoom(9.314, 3), which subtracts a pitch term and a
    // tile-count penalty. So the PITCHED view — the one terrain exists to make worth looking at —
    // systematically gets less elevation detail than the flat-on view.
    const globe = readFileSync(new URL("../pages/earth.astro", import.meta.url), "utf8");
    expect(globe).toContain("maxZoom: 8");
    // 128's nominal exceeds what the camera cap alone would allow, which is why it is the arm
    // whose delivered depth depends on the heuristic rather than on the declaration.
    expect(terrainZoomsFor(8, 128, 8).renderZoom).toBeGreaterThan(8);
    expect(terrainZoomsFor(8, 256, 8).renderZoom).toBe(8);
  });

  it("shows why a deeper pyramid cannot rescue 512", () => {
    // 512's DEM sits at camera-2, so z7 would need camera z9 — and earth.astro caps at maxZoom 8.
    // Building deeper is only spendable if the declaration moves with it.
    for (const depth of [6, 8]) {
      expect(terrainZoomsFor(8, 512, depth).demZoom).toBe(6);
    }
    const globe = readFileSync(new URL("../pages/earth.astro", import.meta.url), "utf8");
    expect(globe).toContain("maxZoom: 8");
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

  it("reaches the pyramid ceiling at the deepest camera, which is what 128 was for", () => {
    // The shipping pair: tileSize 128 puts the DEM at the camera zoom, so camera z8 asks for z8
    // and the z0-8 build answers. Nothing is clamped and nothing is left unused — the two
    // constants are matched by construction, which is why they moved together.
    expect(terrainZoomsFor(8, TERRAIN_TILE_SIZE).demZoom).toBe(TERRAIN_MAX_ZOOM);
    // The arms that lost, at the same camera and pyramid: each declaration costs a level.
    expect(terrainZoomsFor(8, 256).demZoom).toBe(7);
    expect(terrainZoomsFor(8, 512).demZoom).toBe(6);
    // And 512 could never have spent the deep build at all — its DEM is camera-2 against a
    // maxZoom-8 camera, so z7 would need camera z9. That is why depth followed the declaration.
    expect(terrainZoomsFor(8, 512, 8).demZoom).toBe(6);
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

  it("still oversamples render-to-texture by 2, which is why rttSize is 512 and not 256", () => {
    // MapLibre's own class doc understates this; the code multiplies the ALREADY-doubled manager
    // size. Trust the arithmetic, not the comment.
    //
    // The chain, measured live 2026-07-30: the source declares 128, TerrainTileManager doubles it
    // to 256, and qualityFactor 2 gives rttSize 512 — so each render-to-texture target is
    // 512x512x4 = exactly 1 MiB, which is why `rttPoolTrim`'s pool length reads directly as MiB.
    // (This comment previously said 2048/1024, from the era when the source declared 512.)
    expect(bundle).toMatch(/qualityFactor\s*=\s*2\b/);
    expect(bundle).toMatch(/rttSize\s*=\s*\w+\.tileManager\.tileSize\s*\*\s*\w+\.qualityFactor/);
  });
});

describe("source guard — the pipeline is the source of truth for the numbers", () => {
  it("applies the ramp by uniform, never by re-calling setTerrain", () => {
    // ui/map.ts builds a fresh Terrain and RenderToTexture on every setTerrain call and only
    // reaches Terrain.destroy() on the REMOVAL path. Calling it from a zoom handler would leak a
    // framebuffer pair per zoom step and discard the mesh cache; exaggeration is a per-frame
    // uniform, so the assignment below is the whole mechanism.
    //
    // The leak is not theoretical — a measurement rig that toggled terrain four times in one page
    // watched frame time climb monotonically 0.48 -> 1.92 ms across otherwise identical arms.
    //
    // So the rule is about the ESTABLISHING call, and it is split from the removal call rather
    // than counted together: exactly one `setTerrain({...})` may exist, while `setTerrain(null)`
    // is the one form that cleans up after itself and is what the degradation ladder's
    // `disable-terrain` rung pulls.
    const globe = readFileSync(new URL("../pages/earth.astro", import.meta.url), "utf8");
    const establishing = globe.match(/map\.setTerrain\(\s*\{/g) ?? [];
    const removing = globe.match(/map\.setTerrain\(\s*null\s*\)/g) ?? [];
    expect(establishing, "exactly one setTerrain({...}) — every extra call leaks").toHaveLength(1);
    expect(removing.length, "setTerrain(null) is the only other permitted form").toBeLessThanOrEqual(1);
    // Nothing may reach setTerrain by a third spelling that neither pattern above would catch.
    expect(globe.match(/map\.setTerrain\(/g) ?? []).toHaveLength(
      establishing.length + removing.length,
    );
    expect(globe).toContain("map.terrain.exaggeration = next");
  });

  it("releases the DEM source on the degradation rung, not just the terrain", () => {
    // Dropping the terrain stops the geometry and returns none of the memory — the raster-dem
    // tile cache stays fully resident. That cache is bounded at
    // (ceil(W/D) + 1) * (ceil(H/D) + 1) * MAX_TILE_CACHE_ZOOM_LEVELS slots for declared size D,
    // each holding ~1 MiB of Uint32Array fixed by the 512 px asset, which at the shipping
    // declaration of 128 lands near a gigabyte on a desktop canvas (fpsDegradation.ts header).
    // Only removing the SOURCE reaches TileManager.onRemove -> clearTiles ->
    // _outOfViewCache.reset(), whose eviction callback deletes tile.dem and destroys tile.fbo.
    //
    // Asserted against the rung's OWN BRANCH rather than the whole file, so a release that gets
    // moved somewhere it never executes fails here instead of passing on a substring.
    const globe = readFileSync(new URL("../pages/earth.astro", import.meta.url), "utf8");
    const rung = globe.match(/action === "disable-terrain"[\s\S]*?\n\s*\} else \{/)?.[0];
    expect(rung, "the disable-terrain branch must exist").toBeTruthy();
    expect(rung, "the rung must drop the terrain").toMatch(/setTerrain\(\s*null\s*\)/);
    expect(
      rung,
      "and release the source — dropping terrain alone frees no memory",
    ).toMatch(/removeSource\(\s*TERRAIN_SOURCE\s*\)/);
    // Exactly one release. A second would throw on an already-removed source, and a throw here
    // escapes the rAF loop, silently retiring the whole watchdog rather than failing loudly.
    expect(globe.match(/map\.removeSource\(/g) ?? []).toHaveLength(1);
  });

  it("cannot fetch one encoding and decode with another, because there is one of each", () => {
    // The failure this guarded was silent and total: fetch a build cut at 8 m, decode it with 1 m
    // factors, and every tile still 200s, still decodes, still renders — a planet eight times too
    // flat with nothing in the console. While four flags each picked a build, the only defence
    // was threading one parsed value through the directory, the extension and the unpack factors
    // together, and a test that they were the SAME value.
    //
    // The archive replaces that with structure: one path, one maxzoom, one set of factors, none
    // of them selectable. `terrainEncoding()` is now correct to call bare — its default IS the
    // shipping step — which is the exact opposite of what this test asserted before, and the
    // reason it is rewritten rather than retargeted.
    const globe = readFileSync(new URL("../pages/earth.astro", import.meta.url), "utf8");
    const source = globe.slice(globe.indexOf('type: "raster-dem"'), globe.indexOf('type: "raster-dem"') + 400);
    expect(source).toContain("tiles: [terrainTileUrlTemplate]");
    expect(source).toContain("maxzoom: TERRAIN_MAX_ZOOM");
    expect(source).toContain("...terrainEncoding()");
    // The one value still parsed per-request is the declared tile size, which cannot corrupt a
    // decode — it changes which zoom loads, not what the bytes mean.
    expect(source).toContain("tileSize: declaredTileSize");
  });

  it("keeps both delivery codecs lossless in the pipeline", () => {
    // Elevation is not an image: a lossy re-encode produces plausible bytes and therefore wrong
    // metres, with no blur to notice and no error to catch. WebP is here for entropy coding only.
    const pipeline = readFileSync(
      new URL("../../../pipeline/tile/terrain_rgb.py", import.meta.url), "utf8");
    expect(pipeline).toContain('"webp": ("WEBP", ["LOSSLESS=YES"])');
    expect(pipeline).not.toMatch(/QUALITY=/);
  });

  it("keeps the pipeline's quantisation and this module's in step", () => {
    // Two files, one fact. The pipeline writes the bytes; this module tells MapLibre how to read
    // them, and a mismatch is silent: every tile decodes, to the wrong altitude.
    //
    // Pinned to the MODULE CONSTANT rather than the argparse default this used to grep for. The
    // number gained a third reader when the polar caps started encoding their own displacement
    // texture: cap and tiles are both drawn across the cap's alpha crossfade, so a mismatch puts
    // two surfaces at different heights and they ghost. A bare argparse literal is not something
    // another module can import, which is exactly why it had to stop being one.
    const pipeline = readFileSync(
      new URL("../../../pipeline/tile/terrain_rgb.py", import.meta.url), "utf8");
    // A real cross-language tie: the pipeline's constant is compared against THIS module's value,
    // not against a second hand-written literal that could drift with it.
    expect(pipeline).toContain(`QUANTISATION_M = ${TERRAIN_QUANTISATION_M}.0`);
    // ...and the CLI must READ that constant. Restating the number in argparse is the drift.
    expect(pipeline).toMatch(/default=QUANTISATION_M/);
    expect(pipeline).toContain('default="webp"');
    expect(pipeline).toContain("BASE_SHIFT = 32768.0");

    // The caps import the encoding rather than copying it — asserted on the qualified reference,
    // so a local re-spelling of the number cannot satisfy this.
    const caps = readFileSync(
      new URL("../../../pipeline/tile/cap_render.py", import.meta.url), "utf8");
    expect(caps).toMatch(/terrain_rgb\.QUANTISATION_M/);
    expect(caps).toMatch(/terrain_rgb\.SHIPPED_SEA_CLAMP/);
  });
});

describe("resolveTerrainExaggeration — what the `full` tier actually turns on", () => {
  it("gives the full tier the ratified exaggeration with no flag at all", () => {
    // The whole point of Tier 3 step 4: a visitor types nothing and gets terrain because the
    // probe promoted them. Before this, 15 existed only inside `?terrain=15`.
    expect(resolveTerrainExaggeration(flags(""), true)).toBe(DEFAULT_TERRAIN_EXAGGERATION);
  });

  it("leaves every other tier flat", () => {
    expect(resolveTerrainExaggeration(flags(""), false)).toBeNull();
  });

  it("lets ?terrain=N force terrain on at ANY tier, so the A/B flags stay usable", () => {
    // Every look question from here on needs to set exaggeration explicitly without first
    // talking the capability probe into promoting the machine it runs on.
    expect(resolveTerrainExaggeration(flags("terrain=40"), false)).toBe(40);
    expect(resolveTerrainExaggeration(flags("terrain=2.5"), false)).toBe(2.5);
  });

  it("lets ?terrain=off remove ONLY the geometry, without demoting the tier", () => {
    // The control arm. Picking "Globe" in the view bar also disables terrain, but it changes the
    // tier too — so it cannot answer "same tier, same everything, no mesh".
    expect(resolveTerrainExaggeration(flags(`terrain=${TERRAIN_OFF}`), true)).toBeNull();
    expect(resolveTerrainExaggeration(flags(`terrain=${TERRAIN_OFF}`), false)).toBeNull();
    // And the caller must be able to tell "off" from a typo, or it will warn about a deliberate
    // choice: parse returns null for both, so the literal is what distinguishes them.
    expect(TERRAIN_OFF).toBe("off");
  });

  it("does NOT quietly upgrade a malformed value to the tier default", () => {
    // "I asked for 3x and silently got 15x" is exactly the failure the loud-refusal convention
    // exists to prevent, and it would only appear on the tier that already wanted terrain.
    for (const bad of ["terrain=abc", "terrain=0", "terrain=-5", "terrain=99999"]) {
      expect(resolveTerrainExaggeration(flags(bad), true), bad).toBeNull();
      expect(resolveTerrainExaggeration(flags(bad), false), bad).toBeNull();
    }
  });

  it("treats an empty ?terrain= as absent, deferring to the tier", () => {
    expect(resolveTerrainExaggeration(flags("terrain="), true)).toBe(DEFAULT_TERRAIN_EXAGGERATION);
    expect(resolveTerrainExaggeration(flags("terrain="), false)).toBeNull();
  });

  it("starts from a value the ramp actually decays — endpoints are not independent", () => {
    // The ramp holds this to z3 and lands on the floor by z8. If the base ever drifts below the
    // floor the ramp inverts and every deep camera gets MORE exaggeration, not less.
    expect(DEFAULT_TERRAIN_EXAGGERATION).toBeGreaterThan(DEFAULT_TERRAIN_RAMP_FLOOR);
    expect(rampedExaggeration(DEFAULT_TERRAIN_EXAGGERATION, TERRAIN_RAMP_START_ZOOM, DEFAULT_TERRAIN_RAMP_FLOOR))
      .toBeCloseTo(DEFAULT_TERRAIN_EXAGGERATION, 6);
    expect(rampedExaggeration(DEFAULT_TERRAIN_EXAGGERATION, TERRAIN_RAMP_END_ZOOM, DEFAULT_TERRAIN_RAMP_FLOOR))
      .toBeCloseTo(DEFAULT_TERRAIN_RAMP_FLOOR, 6);
  });
});

describe("the deploy preflight must refuse a globe production cannot serve", () => {
  it("checks BOTH halves — that the route exists and that the bytes do", () => {
    // The failure it prevents is silent and total: a promoted visitor's every DEM tile 404s while
    // the globe still renders, just flat. The object check cannot see it, because neither archive
    // is in the manifest at all.
    //
    // Before step 3 this could only assert the first half, and said so: "an archive nothing routes
    // at is worth nothing". The converse is now equally reachable and just as silent — a Worker
    // that routes /terrain/ perfectly at an object nobody uploaded — so the guard has to know
    // about the bucket too. That is the assertion that replaces the old source-only one.
    const script = readFileSync(new URL("../../scripts/check_deploy_sync.ts", import.meta.url), "utf8");
    // DEFINED **AND CALLED**. Asserting the name alone was vacuous and mutation-testing proved it:
    // deleting the call from main() left the function sitting there unreferenced, the grep passed,
    // and the deploy would have stopped checking archives entirely. Two occurrences each — the
    // declaration and the one call — so neither deleting a call nor smuggling in a second one goes
    // unnoticed.
    const occurrences = (name: string) => script.split(name).length - 1;
    expect(occurrences("checkTerrainIsRoutable"), "declared and called exactly once").toBe(2);
    expect(occurrences("checkEveryPublishedArchiveIsUploaded"), "declared and called once").toBe(2);
    expect(script, "and main() is what calls them").toMatch(
      /checkTerrainIsRoutable\(\);\s*\n\s*checkEveryPublishedArchiveIsUploaded\(endpoint\);/,
    );
    // The route half is two greps, because routing lives in the registry: the Worker has to
    // dispatch through the shared resolver, AND the registry has to publish a terrain archive for
    // it to find. Either alone is satisfiable while every DEM tile 404s.
    expect(script, "the route half — the worker dispatches").toMatch(
      /worker\.includes\("resolveTileRequest"\)/,
    );
    expect(script, "the route half — the registry publishes").toMatch(/registry\)/);
    // The bytes half is no longer terrain-specific and no longer named key by key. It enumerates
    // every archive the registry publishes — which is what closed the hole this test could not see:
    // the check named two variables, so the COUNTRY archive was never verified at all, and a
    // deploy missing it reported clean.
    expect(script, "the bytes half").toContain("checkEveryPublishedArchiveIsUploaded");
    expect(script, "and it enumerates rather than naming").toContain("publishedArchiveKeys");
    expect(script, "against the archive bucket").toContain("ARCHIVE_BUCKET");
    // Vacuity: a parse that matched nothing would report a perfect deploy for every archive at
    // once, so the script must refuse to run on an empty enumeration.
    expect(script, "and it must refuse a vacuous enumeration").toMatch(/keys\.length === 0/);
  });

  it("is satisfied by what step 3 actually landed, in every place it looks", () => {
    // The state assertion this replaces was armed on purpose while nothing served terrain, and
    // was written to flip here. It flips by becoming its own inverse: the same three files, now
    // asserted to agree rather than to disagree.
    const globe = readFileSync(new URL("../pages/earth.astro", import.meta.url), "utf8");
    const worker = readFileSync(new URL("../../worker/index.ts", import.meta.url), "utf8");

    // Matched on the FACT, not on one spelling of it. This regex used to require the literal
    // `currentTier()`, and went red the day that call was hoisted to a `bootTier` const to save a
    // second WebGL probe — a refactor that changed nothing about whether terrain rides the tier.
    // So: capture whatever is compared to "full", then require that identifier to actually BE a
    // tier, which is what stops `anythingAtAll === "full"` from satisfying it.
    // The twin of this check lives in capability.test.ts (it decides whether the Full tooltip must
    // say "terrain"); both read the same call site, so both go red together rather than drifting.
    const gate = globe.match(
      /resolveTerrainExaggeration\(\s*urlFlags\s*,\s*([\w$]+(?:\(\))?)\s*===\s*"full"\s*\)/,
    );
    const tierExpression = gate?.[1] ?? "";
    // `decide(Globe)?Tier`: the globe page uses the `decideGlobeTier` wrapper, which clamps a soft
    // `gallery` verdict on a page already showing the globe. Both spellings are the tier decision;
    // its twin in capability.test.ts carries the longer note.
    const ridesOnTier =
      tierExpression === "currentTier()" ||
      tierExpression === "currentGlobeTier()" ||
      (tierExpression !== "" &&
        new RegExp(`const\\s+${tierExpression}\\s*=\\s*decide(?:Globe)?Tier\\(`).test(globe));
    expect(ridesOnTier, `terrain rides the full tier (gate read: ${tierExpression || "none"})`).toBe(
      true,
    );
    expect(worker, "the worker dispatches through the shared resolver").toContain(
      "resolveTileRequest",
    );
    expect(PUBLISHED.earth.terrain, "and the registry publishes a terrain cut").not.toBeNull();
    // The object it reads is named HERE, in the registry, and nowhere else. It used to also be a
    // `TERRAIN_ARCHIVE_KEY` var in wrangler.jsonc, pinned against this entry — two copies of one
    // fact, kept in step by a test. The var is gone: an env-only swap could not work anyway, since
    // a tile URL carries the archive's token and that token is compiled into the site bundle.
    expect(PUBLISHED.earth.terrain?.objectKey).toMatch(/\.pmtiles$/);
  });
});
