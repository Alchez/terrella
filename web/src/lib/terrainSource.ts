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

/** Elevation tiles must be byte-exact, so the codec must be LOSSLESS — a lossy tile decodes to
 *  plausible-looking bytes and therefore to wrong metres, silently, with no blur to notice.
 *
 *  That requirement is about losslessness, not about PNG, and lossless WebP satisfies it at
 *  **0.67x the bytes** — measured whole-pyramid (0.32 vs 0.48 GB at z0-6) and independent of
 *  `--step`, so it multiplies with quantisation rather than overlapping it. Proven identical at
 *  three levels, each with a positive control: GDAL round-trip, the browser's own
 *  `createImageBitmap` decode (alpha 255 everywhere, so nothing premultiplies), and rendered
 *  frames at 0.0000 mean DN. → HISTORY § the terrain archive gets a third smaller for nothing. */
export const TERRAIN_TILE_EXTENSION = "webp";
export const TERRAIN_CONTENT_TYPE = "image/webp";

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

/** Metres per encoded level, matching the pipeline's `--step`.
 *
 *  8 m, for **0.49x the archive** — and it is nearly free for a structural reason: quantisation
 *  error is largest where displacement is smallest. Measured at five cameras under the shipping
 *  ramp, 1 m vs 8 m differs by 0.011-0.145 mean DN against a ~1 DN noise floor, and the *lowest*
 *  reading is on the Ganges plain, which is the opposite of terracing. We can only spend this
 *  because our shading is BAKED into the colour tiles: anyone computing hillshade client-side
 *  from this DEM would see the steps in their lighting. 16 m buys only another 0.74x, so this is
 *  the knee. → HISTORY § the terrain archive gets a third smaller for nothing. */
export const TERRAIN_QUANTISATION_M = 8;

/** Terrarium's zero point (dem_data.ts hard-codes 32768 for the named encoding). */
const TERRAIN_BASE_SHIFT = 32768;

/** The style-spec fields a `raster-dem` source needs to decode our tiles.
 *
 *  MapLibre decodes as `R*red + G*green + B*blue - baseShift`. At one metre per level that is
 *  bit-for-bit standard `terrarium` and needs no custom fields; every coarser step is expressible
 *  only as `custom`, which is what we ship at TERRAIN_QUANTISATION_M = 8. The 1 m branch stays
 *  because `?quant=1` still selects the 1 m build for comparison.
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

/** Read `?dem=clamp|bathy`, defaulting to the ratified bathymetry. An unrecognised value returns
 *  the default; the caller warns, so a typo cannot quietly A/B the same variant against itself.
 *
 *  The default was `clamp` while both were candidates. Step 0 chose bathymetry on Rohan's eyes —
 *  it costs 2.6x the bytes and reads better, mostly on open ocean — so leaving `clamp` here would
 *  have every unflagged capture measure the arm we rejected. */
export function parseTerrainVariant(params: URLSearchParams): TerrainVariant {
  const raw = params.get("dem");
  return TERRAIN_VARIANTS.includes(raw as TerrainVariant) ? (raw as TerrainVariant) : "bathy";
}

/** Quantisation steps built for the Step-0d size A/B, in metres per encoded level. Spike-only:
 *  production ships one, and this list retires with TERRAIN_VARIANTS. */
export const TERRAIN_QUANTISATION_STEPS = [1, 2, 4, 8] as const;
export type TerrainQuantisation = (typeof TERRAIN_QUANTISATION_STEPS)[number];

/** Read `?quant=1|2|4|8`, defaulting to whatever the pipeline currently writes.
 *
 *  Returns null for malformed ONLY, like parseTerrainRamp, because this is the flag whose silent
 *  failure is worst: a build selected at one step and decoded at another still loads every tile,
 *  still renders, and is simply wrong by that ratio everywhere.
 */
export function parseTerrainQuantisation(params: URLSearchParams): TerrainQuantisation | null {
  const raw = params.get("quant");
  if (raw === null || raw.trim() === "") return TERRAIN_QUANTISATION_M;
  const step = Number(raw);
  return TERRAIN_QUANTISATION_STEPS.includes(step as TerrainQuantisation)
    ? (step as TerrainQuantisation)
    : null;
}

/** Delivery codecs built for the Step-0d size A/B. Both are lossless — see
 *  TERRAIN_TILE_EXTENSION, whose reasoning is about losslessness and not about PNG specifically. */
export const TERRAIN_TILE_FORMATS = ["png", "webp"] as const;
export type TerrainTileFormat = (typeof TERRAIN_TILE_FORMATS)[number];

/** Read `?demfmt=png|webp`, defaulting to the shipping extension. Null for malformed only. */
export function parseTerrainFormat(params: URLSearchParams): TerrainTileFormat | null {
  const raw = params.get("demfmt");
  if (raw === null || raw.trim() === "") return TERRAIN_TILE_EXTENSION;
  return TERRAIN_TILE_FORMATS.includes(raw as TerrainTileFormat)
    ? (raw as TerrainTileFormat)
    : null;
}

/**
 * Directory holding one spike build, matching what `terrain_rgb.py --out` was pointed at.
 *
 * THE INVARIANT: the caller must compose this from the same `quantisation` and `format` values it
 * hands to `terrainEncoding` and `terrainPathTemplate`. Independent flags could disagree, and a
 * disagreement is undetectable at runtime — the tiles decode, so there is no 404 and no console
 * error, only a planet at the wrong scale.
 */
export function terrainBuildDirectory(
  variant: TerrainVariant,
  quantisation: TerrainQuantisation,
  format: TerrainTileFormat,
): string {
  const step = quantisation === 1 ? "" : `_s${quantisation}`;
  const codec = format === "png" ? "" : `_${format}`;
  return `${variant}${step}${codec}`;
}

/** Path portion of a terrain tile URL for one codec — TERRAIN_PATH_TEMPLATE at the default. */
export function terrainPathTemplate(format: TerrainTileFormat): string {
  return `{z}/{x}/{y}.${format}`;
}

/** Declared tile sizes for the axis-B A/B. 512 is honest; 256 is a deliberate misdeclaration that
 *  buys geometry, and the two are the only values worth testing. */
export const TERRAIN_TILE_SIZES = [256, 512] as const;
export type TerrainDeclaredTileSize = (typeof TERRAIN_TILE_SIZES)[number];

/** Read `?demsize=256|512`, defaulting to the shipped declaration. Null for malformed only. */
export function parseTerrainTileSize(params: URLSearchParams): TerrainDeclaredTileSize | null {
  const raw = params.get("demsize");
  if (raw === null || raw.trim() === "") return TERRAIN_TILE_SIZE;
  const size = Number(raw);
  return TERRAIN_TILE_SIZES.includes(size as TerrainDeclaredTileSize)
    ? (size as TerrainDeclaredTileSize)
    : null;
}

/**
 * Which zoom MapLibre will mesh at, and which DEM tile will feed it, for a camera zoom.
 *
 * THIS RESTATES UNDOCUMENTED INTERNALS. The style spec says only that `tileSize` is "the minimum
 * visual size to display tiles" and defaults to 512 — it says nothing about zoom selection. The
 * arithmetic below is read out of the bundle and confirmed against a live map, and the canary in
 * this module's test file fails if MapLibre's own constants move:
 *
 *   render zoom = floor(cameraZoom + log2(512 / (declared * 2)))   // TerrainTileManager doubles
 *   DEM zoom    = min(render zoom - deltaZoom, source maxzoom)     // deltaZoom is 1
 *
 * Measured at camera z6, declared 512: render z5 (four tiles), DEM z4 — one DEM tile feeding all
 * four quadrants. Declaring 256 shifts both up one, which is the whole of axis B: the mesh is
 * fixed at 128x128 per render tile, so covering less ground per render tile is the ONLY way to
 * make facets smaller.
 *
 * THIS RETURNS THE NOMINAL ZOOM, NOT A GUARANTEE ABOUT EVERY TILE. The globe projection allows
 * variable zoom across the covering set, so tiles nearer the limb come back one level coarser.
 * Measured at camera z6 declared 256: 9 render tiles at z6 (nominal) plus 3 at z5, consuming DEM
 * z5 and z4 respectively. So a request-count estimate built by squaring this is an upper bound —
 * the observed set was 12 render tiles against 4 at declared 512, i.e. 3x, not the 4x the
 * arithmetic alone predicts.
 */
export function terrainZoomsFor(
  cameraZoom: number,
  declaredTileSize: number = TERRAIN_TILE_SIZE,
  maxZoom: number = TERRAIN_MAX_ZOOM,
): { renderZoom: number; demZoom: number } {
  const renderZoom = Math.max(0, Math.floor(cameraZoom + Math.log2(512 / (declaredTileSize * 2))));
  return { renderZoom, demZoom: Math.min(Math.max(0, renderZoom - 1), maxZoom) };
}
