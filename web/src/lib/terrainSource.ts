/** The terrain-RGB contract — a `raster-dem` source over an elevation pyramid, for Tier 3.
 *
 *  Sibling of reliefTiles.ts rather than a generalisation of it. The two pyramids share a tiling
 *  scheme and nothing else: one is colour, one is elevation; one is WebP, one is PNG; and they are
 *  independent MapLibre sources with their own `maxzoom`, so terrain need not track the colour
 *  pyramid's depth. Folding them into one parameterised module would put a "which archive am I"
 *  branch in the single file whose job is to have no branches.
 *
 *  Like reliefTiles.ts this is dependency-free and free of `import.meta.env`, because it is
 *  imported from the browser, the Astro dev server (plain Node, before Vite env exists) and
 *  eventually the tile Worker.
 *
 *  ENCODING. The pipeline writes Mapzen terrarium with the blue channel zeroed, so elevation is
 *  `R*256 + G - 32768` metres — see pipeline/tile/terrain_rgb.py, which is the source of truth
 *  for the numbers below and carries the reasoning for zeroing blue.
 */

/** MapLibre source id, owned here for the same reason COUNTRIES_SOURCE is owned by
 *  countryHighlight.ts — the module that defines a source names it. */
export const TERRAIN_SOURCE = "terrain-dem";

/** Elevation tiles must be byte-exact, so the encoding is lossless. A lossy WebP tile would
 *  decode to plausible-looking bytes and therefore to wrong metres, silently. */
export const TERRAIN_TILE_EXTENSION = "png";
export const TERRAIN_CONTENT_TYPE = "image/png";

/** Path portion of a terrain tile URL, with MapLibre's placeholders. */
export const TERRAIN_PATH_TEMPLATE = `{z}/{x}/{y}.${TERRAIN_TILE_EXTENSION}`;

export const TERRAIN_MIN_ZOOM = 0;

/** Depth of the elevation pyramid. Deliberately shallower than the colour pyramid's z8: MapLibre
 *  builds a fixed 128x128 mesh PER TILE regardless of the DEM's resolution, so an overzoomed
 *  terrain tile keeps full mesh density and loses only elevation detail. Raising this costs
 *  bytes and buys detail, not geometry — a size lever, decided on a look that already works.
 *
 *  The sharper form of that, because it bounds what any depth can buy: one mesh quad spans
 *  512/128 = 4 DEM samples of whichever zoom loaded, and a loaded tile always covers 1024 CSS px
 *  (see TERRAIN_TILE_SIZE), so a facet is ~8 CSS px wide AT EVERY ZOOM. A deeper pyramid places
 *  those vertices more accurately; it does not give you more of them. */
export const TERRAIN_MAX_ZOOM = 6;

/** The tile's true pixel size, declared honestly — unlike the relief source, which declares 512 px
 *  assets as `tileSize: 256` to land them in a 256 slot at DPR 2.
 *
 *  MapLibre turns tileSize into a zoom offset: `floor(mapZoom + log2(512 / tileSize))`
 *  (covering_tiles.ts, coveringZoomLevel), so relief fetches mapZoom + 1 and an honest 512 fetches
 *  mapZoom. Terrain then takes a second discount MapLibre applies on its own: TerrainTileManager
 *  sets `deltaZoom = 1` and overrides the cache's tileSize to 1024, which tile_manager.ts honours
 *  whenever `usedForTerrain` — so DEM tiles actually load at mapZoom - 1. At map z7 that is colour
 *  z8 against terrain z6: two levels apart, ~1/16 the tiles per view, not the quarter that the
 *  declared size alone would suggest. */
export const TERRAIN_TILE_SIZE = 512;

/** Metres per encoded level, matching the pipeline's `--step`. */
export const TERRAIN_QUANTISATION_M = 1;

/** Terrarium's zero point (dem_data.ts hard-codes 32768 for the named encoding). */
const TERRAIN_BASE_SHIFT = 32768;

/** The style-spec fields a `raster-dem` source needs to decode our tiles.
 *
 *  MapLibre decodes as `R*red + G*green + B*blue - baseShift`. At one metre per level that is
 *  bit-for-bit standard `terrarium`, so we name the standard encoding and carry no custom
 *  factors — a coarser step is expressible, but only as `custom`.
 */
export function terrainEncoding(quantisationMetres: number = TERRAIN_QUANTISATION_M) {
  if (quantisationMetres === 1) return { encoding: "terrarium" as const };
  return {
    encoding: "custom" as const,
    redFactor: 256 * quantisationMetres,
    greenFactor: quantisationMetres,
    blueFactor: 0,
    baseShift: TERRAIN_BASE_SHIFT,
  };
}

/** Ceiling for `?terrain=N`. Not a MapLibre limit — displacement is `elevation * N / 6371008.8` of
 *  the globe radius, so N=200 already lifts Everest to ~28% of the radius, well past anything a
 *  look test would defend. A guard against a typo'd URL turning the planet inside out. */
export const MAX_TERRAIN_EXAGGERATION = 200;

/**
 * Read `?terrain=N` — the exaggeration, and the switch that enables terrain at all.
 *
 * Returns `null` for absent, malformed, or out of range, exactly as parseMaxParallelImageRequests
 * does and for the same reason: a run that believes it measured 15x while running at MapLibre's
 * default 1x is worse than no run. Callers check `params.has("terrain")` to complain about a typo.
 *
 * Non-integers are accepted here (unlike `?maxreq`) because exaggeration is a continuous look
 * knob and 2.5 is a legitimate rung; zero is not, because it is indistinguishable from off.
 */
export function parseTerrainExaggeration(params: URLSearchParams): number | null {
  const raw = params.get("terrain");
  if (raw === null || raw.trim() === "") return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  if (value <= 0 || value > MAX_TERRAIN_EXAGGERATION) return null;
  return value;
}

/** Zoom at or below which the ramp holds the base exaggeration. Below here the whole globe is on
 *  screen and displacement is near-invisible — Everest at 15x is ~5 px against a ~249 px globe
 *  radius — so there is nothing to give back. */
export const TERRAIN_RAMP_START_ZOOM = 3;

/** Zoom at or above which the ramp holds its floor. Matches the globe's own maxZoom, so the ramp
 *  spends its whole range inside the reachable camera. */
export const TERRAIN_RAMP_END_ZOOM = 8;

/** Exaggeration held at TERRAIN_RAMP_END_ZOOM.
 *
 *  Chosen so the ramp is SCALE-INVARIANT, then confirmed by eye. Measured on the shipped tiles,
 *  elevation change across a mesh facet scales as roughly `width^0.5`, and the facet halves each
 *  zoom level — so apparent slope holds constant only if exaggeration falls by ~0.707 per level.
 *  From 15x over five levels that is exactly 15*2^-2.5 = 2.652; 2.5 is that rounded to a number
 *  a person can type into `?ramp`, costing 1.1% of the ideal decay. The earlier 4 gave 0.768,
 *  which looks right for a level or two and compounds: by z8 it had drifted the 99th-percentile
 *  facet from ~45deg to ~58deg, which is the zoom where the needles came back.
 *
 *  Consequence worth knowing before changing it: the endpoints are not independent. Holding 15x
 *  at TERRAIN_RAMP_START_ZOOM and 2.5x at the end IS the scale-invariant pair; moving either one
 *  trades constant apparent slope for more relief at one end. → HISTORY § the terrain
 *  exaggeration ramp. */
export const DEFAULT_TERRAIN_RAMP_FLOOR = 2.5;

/**
 * Exaggeration for a map zoom, decaying geometrically from `base` to `floor`.
 *
 * One constant cannot serve both ends of the range. Displacement is `elevation * N / 6371008.8`
 * of the globe radius, so Everest at 15x is ~5 px against the overview globe and ~125 px at z7 —
 * a ~25x swing, and the eye reads the two ends as different decisions. Measured off the shipped
 * z6 tiles at MapLibre's real mesh stride, 15x turns the Karakoram's median facet (284 m over
 * 4.0 km, a true 4.0 deg) into 46.5 deg and its 99th percentile into 80 deg. Those are the
 * needles; they are an amplitude problem, not a resolution one.
 *
 * Geometric rather than linear because the perceived quantity is a ratio — facet slope scales
 * with exaggeration — so a fixed per-level factor keeps the decay scale-free. See
 * DEFAULT_TERRAIN_RAMP_FLOOR for why that factor has to be ~0.707 rather than any value that
 * merely looks reasonable at one zoom.
 */
export function rampedExaggeration(
  baseExaggeration: number,
  zoom: number,
  floorExaggeration: number = DEFAULT_TERRAIN_RAMP_FLOOR,
): number {
  if (zoom <= TERRAIN_RAMP_START_ZOOM) return baseExaggeration;
  if (zoom >= TERRAIN_RAMP_END_ZOOM) return floorExaggeration;
  const span =
    (zoom - TERRAIN_RAMP_START_ZOOM) / (TERRAIN_RAMP_END_ZOOM - TERRAIN_RAMP_START_ZOOM);
  return baseExaggeration * (floorExaggeration / baseExaggeration) ** span;
}

/** `?ramp=off` — the control arm of the A/B, holding `?terrain=N` constant at every zoom. */
export const TERRAIN_RAMP_OFF = "off";

export type TerrainRamp = { kind: "off" } | { kind: "ramp"; floor: number };

/** Built fresh per call rather than exported as a shared literal, so no caller can mutate the
 *  default out from under the next one. */
export function defaultTerrainRamp(): TerrainRamp {
  return { kind: "ramp", floor: DEFAULT_TERRAIN_RAMP_FLOOR };
}

/**
 * Read `?ramp=off|<floor>` — absent is the default ramp, `off` holds the base constant, and a
 * number is the exaggeration to hold at TERRAIN_RAMP_END_ZOOM.
 *
 * Returns null for malformed ONLY. Absent and malformed both end up on the default ramp, but the
 * caller has to be able to tell them apart to warn about a typo — a run that believes it swept
 * floor 2 while running floor 4 is worse than no run.
 */
export function parseTerrainRamp(params: URLSearchParams): TerrainRamp | null {
  const raw = params.get("ramp");
  if (raw === null || raw.trim() === "") return defaultTerrainRamp();
  if (raw.trim().toLowerCase() === TERRAIN_RAMP_OFF) return { kind: "off" };
  const floor = Number(raw);
  if (!Number.isFinite(floor) || floor <= 0 || floor > MAX_TERRAIN_EXAGGERATION) return null;
  return { kind: "ramp", floor };
}

/**
 * One line describing the live terrain state, for the `?perf` overlay.
 *
 * The ramp makes exaggeration a function of zoom, so a screenshot of the globe no longer says
 * what produced it. Putting the arm and the live value on screen makes each capture
 * self-describing — the difference between a usable A/B and a pile of images whose order someone
 * has to remember. Only called when terrain was requested at all, so `null` means the style has
 * not attached it yet rather than that it is off.
 */
export function describeTerrainState(
  exaggeration: number | null,
  baseExaggeration: number,
  ramp: TerrainRamp,
): string {
  const arm = ramp.kind === "off" ? "ramp off" : `ramp ${baseExaggeration}→${ramp.floor}`;
  if (exaggeration === null) return `terrain pending · ${arm}`;
  return `terrain ${exaggeration.toFixed(1)}x · ${arm}`;
}

/** The two sea treatments built for the Step-0 A/B: `clamp` flattens the seafloor to zero,
 *  `bathy` displaces it too. Spike-only — production ships one of them and this goes away. */
export const TERRAIN_VARIANTS = ["clamp", "bathy"] as const;
export type TerrainVariant = (typeof TERRAIN_VARIANTS)[number];

/** Read `?dem=clamp|bathy`, defaulting to the recommended clamp. An unrecognised value returns
 *  the default; the caller warns, so a typo cannot quietly A/B the same variant against itself. */
export function parseTerrainVariant(params: URLSearchParams): TerrainVariant {
  const raw = params.get("dem");
  return TERRAIN_VARIANTS.includes(raw as TerrainVariant) ? (raw as TerrainVariant) : "clamp";
}
