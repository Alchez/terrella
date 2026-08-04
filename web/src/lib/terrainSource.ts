/** The terrain-RGB contract — a `raster-dem` source over an elevation pyramid, for Tier 3.
 *
 *  Sibling of reliefTiles.ts rather than a generalisation of it. The two pyramids share a tiling
 *  scheme and a codec and nothing else: one is colour and one is elevation, they are independent
 *  MapLibre sources with their own `maxzoom`, and only one of them may ever be resampled.
 *  Folding them into one parameterised module would put a "which archive am I" branch in the
 *  single file whose job is to have no branches.
 *
 *  Like reliefTiles.ts this is dependency-free and free of `import.meta.env`, because it is
 *  imported from the browser, the Astro dev server (plain Node, before Vite env exists) and the
 *  tile Worker.
 *
 *  ENCODING. The pipeline writes Mapzen terrarium with the blue channel zeroed, so elevation is
 *  `R*256 + G - 32768` metres — see pipeline/tile/terrain_rgb.py, which is the source of truth
 *  for the numbers below and carries the reasoning for zeroing blue.
 */

// Type-only, and erased at run time. The alternative was a second name for one concept — a
// `TerrainTileCoordinate` identical to `TileCoordinate` — which costs more than the import:
// two names for one thing is how a fake distinction gets invented later.
import type { TileCoordinate } from "./reliefTiles";

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
 *  frames at 0.0000 mean DN. */
export const TERRAIN_TILE_EXTENSION = "webp";
export const TERRAIN_CONTENT_TYPE = "image/webp";

/** The path segment that tells the tile server which archive a request is for.
 *
 *  NOT decoration, and NOT what the Tier-3 plan assumed. That plan said terrain needed no prefix
 *  because "the `.png`/`.webp` extension is already the discriminator" — true when terrain was
 *  PNG. Step 0d then ratified lossless WebP for terrain (0.67x the bytes, byte-exact), so the two
 *  pyramids now agree on extension AND on zoom range: `/8/189/107.webp` is a valid address in
 *  both. Nothing in the URL distinguishes colour from elevation any more, so the prefix has to.
 *
 *  Served under the relief tile base rather than its own hostname — one Worker, one bucket, two
 *  object keys — so this costs no new deploy variable and no second custom domain. */
export const TERRAIN_PATH_PREFIX = "terrain";

export const TERRAIN_MIN_ZOOM = 0;

/** Depth of the elevation pyramid, matching the colour pyramid's z8 — which is also the full extent
 *  of the master (`MASTER_ZOOM = 8`, 131072 = 512 x 2^8), so nothing deeper exists without a re-fuse.
 *
 *  Was 6 until 2026-07-28, on the reasoning that depth buys elevation detail but not mesh density
 *  and so was "a size lever, decided on a look that already works". That reasoning was sound and
 *  the conclusion was still wrong, because it treated the pyramid and the declaration as separate
 *  decisions. They are one: `TERRAIN_TILE_SIZE` fixes the DEM at `camera - 1`, so with z6 the
 *  deepest camera clamped and the declaration bought mesh density ONLY. Cutting z7/z8 (41 min,
 *  2.63 GB) is what lets it buy elevation as well.
 *
 *  The sharper form of that, because it bounds what any depth can buy: `deltaZoom = 1` means a DEM
 *  tile always covers 2x the render tile's ground, so 256 of its texels span the 128-quad mesh —
 *  **2 DEM samples per facet along each axis (4 by area), at EVERY declared tile size**. The
 *  declaration moves the mesh and the DEM shelf together and cannot change that ratio, so a deeper
 *  pyramid places those vertices more accurately; it does not give you more of them.
 *
 *  Corrected 2026-07-27: this previously derived "512/128 = 4 DEM samples" per quad, which omits
 *  deltaZoom — 4 is right only read as area, and the per-axis figure is 2. The companion claim that
 *  a facet is ~8 CSS px wide AT EVERY ZOOM was true only of the then-shipping `tileSize: 512`; at
 *  the shipping 128 it is ~2 px.
 *
 *  This ceiling now binds at the deepest camera, and only flat-on. At `tileSize: 128` and camera z8
 *  the DEM wants z8 and gets it at pitch 0 — the mesh refines and the data refines with it. Pitch
 *  takes it back: MapLibre's globe LOD heuristic drops the covering a level, so a pitched z8 view
 *  reads z7 (see terrainZoomsFor). The payoff view is therefore one level shallower than the flag
 *  suggests, which is worth knowing before anyone cuts a z9 that could never load. */
export const TERRAIN_MAX_ZOOM = 8;

/** Built from the prefix and the extension rather than spelled out, so the path we ASK for and
 *  the path we ACCEPT cannot drift apart. */
const TERRAIN_PATH_PATTERN = new RegExp(
  String.raw`^\/?${TERRAIN_PATH_PREFIX}\/(\d{1,2})\/(\d{1,7})\/(\d{1,7})\.${TERRAIN_TILE_EXTENSION}$`,
);

/** Parse `/terrain/8/189/107.webp` (leading slash optional) into a tile address, or null if the
 *  path is not a terrain tile request at all.
 *
 *  Deliberately the same shape as `parseTilePath`, including the out-of-grid rejection: a tile
 *  server should 404 a typo'd URL rather than range-read a 2.6 GB archive for it. The one thing
 *  that must NOT be shared is the acceptance set — a path this returns non-null for is one
 *  `parseTilePath` must reject, and vice versa, or the router would serve elevation as colour. */
export function parseTerrainTilePath(pathname: string): TileCoordinate | null {
  const match = TERRAIN_PATH_PATTERN.exec(pathname);
  if (!match) return null;
  const z = Number(match[1]);
  const x = Number(match[2]);
  const y = Number(match[3]);
  if (z < TERRAIN_MIN_ZOOM || z > TERRAIN_MAX_ZOOM) return null;
  const gridSize = 2 ** z;
  if (x >= gridSize || y >= gridSize) return null;
  return { z, x, y };
}

/** Describe a TERRAIN_TILE_EXTENSION/archive disagreement, or null when they match.
 *
 *  Worth more here than its relief twin, because for elevation a codec swap is not cosmetic: a
 *  browser will content-sniff a mislabelled PNG and decode it fine, but a LOSSY re-encode decodes
 *  to plausible bytes and therefore to wrong metres, with no blur to notice. */
export function describeTerrainTileTypeMismatch(archiveExtension: string): string | null {
  if (archiveExtension === `.${TERRAIN_TILE_EXTENSION}`) return null;
  const declared = archiveExtension || "an encoding this pmtiles build cannot name";
  return (
    `Terrain archive stores ${declared} tiles, but the globe requests ` +
    `.${TERRAIN_TILE_EXTENSION}. Update TERRAIN_TILE_EXTENSION in src/lib/terrainSource.ts to ` +
    `match the re-cut pyramid (its source of truth is TERRAIN_TILE_EXTENSION in ` +
    `pipeline/tile/terrain_rgb.py). Elevation tiles must stay LOSSLESS.`
  );
}

/** DECLARED tile size, and deliberately a quarter of the asset's true 512 px — the same trick the
 *  relief source plays for a different reason (it declares 256 to land 512 px assets @2x at DPR 2;
 *  this declares 128 so a render tile covers a quarter of the ground, making the fixed 128-quad
 *  mesh land ~2 CSS px facets instead of 8).
 *
 *  Was 512 ("declared honestly"). Ratified by eye at z8 pitch 60 against
 *  256 and 512, and these are the numbers that made it affordable rather than merely nicer:
 *    - GPU frame cost is FLAT across declarations — 3.87 / 4.54 / 4.31 ms at 512 / 256 / 128, with
 *      256 and 128 indistinguishable (overlapping IQRs). `rttSize` halves at every step down, so
 *      more render tiles each cost proportionally less and total RTT pixels FALL. Chrome, with a
 *      passing DPR control; treat it as a lower bound on Firefox.
 *    - Seams get MILDER, not worse: 128 sees only the z6|z7 boundary (68 m typical step) where 512
 *      straddles z4|z5 and z5|z6 (150 m and 105 m).
 *  The real price is requests: 27 DEM tiles per view against 9 at 512, which lands on the free
 *  tier and therefore on whoever `decideTier` promotes to `full`.
 *
 *  MapLibre turns tileSize into a zoom offset: `floor(mapZoom + log2(512 / tileSize))`
 *  (covering_tiles.ts, coveringZoomLevel), so relief fetches mapZoom + 1 and an honest 512 fetches
 *  mapZoom. Terrain then takes TWO further discounts, and conflating them is easy: TerrainTileManager
 *  overrides the cache's tileSize to 1024 (tile_manager.ts honours it whenever `usedForTerrain`),
 *  putting the RENDER tile at mapZoom - 1 — and then `getSourceTile` subtracts `deltaZoom = 1`
 *  again, putting the DEM tile at **mapZoom - 2**. At map z7 that is colour z8 against terrain
 *  **z5: three levels apart**. That gap is what made 512 cheap and shallow: 9 DEM tiles per view at
 *  camera z8, against 27 at the shipping 128.
 *
 *  Corrected 2026-07-27: this previously stopped at the first discount and claimed DEM loads at
 *  mapZoom - 1 ("map z7 → terrain z6, two levels apart"). That is the render tile's zoom, not the
 *  DEM's. `terrainZoomsFor` has the arithmetic right and its tests pin it against two live reads. */
export const TERRAIN_TILE_SIZE = 128;

/** Metres per encoded level, matching the pipeline's `--step`.
 *
 *  8 m, for **0.49x the archive** — and it is nearly free for a structural reason: quantisation
 *  error is largest where displacement is smallest. Measured at five cameras under the shipping
 *  ramp, 1 m vs 8 m differs by 0.011-0.145 mean DN against a ~1 DN noise floor, and the *lowest*
 *  reading is on the Ganges plain, which is the opposite of terracing. We can only spend this
 *  because our shading is BAKED into the colour tiles: anyone computing hillshade client-side
 *  from this DEM would see the steps in their lighting. 16 m buys only another 0.74x, so this is
 *  the knee. */
export const TERRAIN_QUANTISATION_M = 8;

/** Terrarium's zero point (dem_data.ts hard-codes 32768 for the named encoding). */
const TERRAIN_BASE_SHIFT = 32768;

/** The style-spec fields a `raster-dem` source needs to decode our tiles.
 *
 *  MapLibre decodes as `R*red + G*green + B*blue - baseShift`. At one metre per level that is
 *  bit-for-bit standard `terrarium` and needs no custom fields; every coarser step is expressible
 *  only as `custom`, which is what we ship at TERRAIN_QUANTISATION_M = 8.
 *
 *  Still takes the step as an argument after `?quant` retired with the archive, because the
 *  parameter tracks `terrain_rgb.py --step`, which is a live pipeline knob — this is the function
 *  that would have to agree with a re-cut at a different step, and the 1 m branch is what states
 *  the relationship to the standard encoding rather than merely asserting factors.
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
  if (raw.trim() === TERRAIN_OFF) return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  if (value <= 0 || value > MAX_TERRAIN_EXAGGERATION) return null;
  return value;
}

/** `?terrain=off` — hold the tier at full and run flat anyway. */
export const TERRAIN_OFF = "off";

/**
 * The exaggeration terrain runs at on the `full` tier, chosen by eye on the frames at Step 0:
 * 40x shreds the mesh into needles, 5x is too subtle to be worth the geometry. This is the value
 * the ramp DECAYS FROM — it holds to z3 and lands at DEFAULT_TERRAIN_RAMP_FLOOR by z8, so no
 * camera below the overview actually renders at 15x.
 *
 * It only became a constant when terrain graduated to a tier. Before that it lived exclusively in
 * `?terrain=15`, which is fine for an A/B and impossible for a tier — nothing was going to type a
 * URL flag on a visitor's behalf.
 */
export const DEFAULT_TERRAIN_EXAGGERATION = 15;

/**
 * Resolve whether terrain runs, and at what exaggeration, from the URL and the decided tier.
 *
 * `?terrain=` wins over the tier IN BOTH DIRECTIONS — a number forces terrain on at any tier (so
 * the whole flag family stays usable for A/B without first talking the probe into `full`), and
 * `?terrain=off` forces it off without demoting the tier. That second form is not decoration: once
 * terrain rides on `full` there is otherwise no way to hold every other variable fixed and remove
 * only the geometry, which is exactly the comparison every future look question needs. Picking
 * "Globe" in the view bar also disables terrain, but it changes the tier as well, so it is a
 * different experiment.
 *
 * Returns `null` for a flat globe. A malformed value is NOT silently upgraded to the tier default:
 * it returns null and the caller warns, because "I asked for 3x and got 15x" is the failure the
 * loud-refusal convention exists to prevent.
 */
export function resolveTerrainExaggeration(
  params: URLSearchParams,
  tierWantsTerrain: boolean,
): number | null {
  const raw = params.get("terrain");
  const requested = raw !== null && raw.trim() !== "";
  if (requested) return parseTerrainExaggeration(params);
  return tierWantsTerrain ? DEFAULT_TERRAIN_EXAGGERATION : null;
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
 *  trades constant apparent slope for more relief at one end.
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

// RETIRED 2026-07-28 WITH THE ARCHIVE — `?dem`, `?quant`, `?demfmt`, `?demdepth` and
// `terrainBuildDirectory`.
//
// All four selected a BUILD DIRECTORY under data/work/planet_terrain, which is a thing that only
// exists while terrain is served as loose tiles off a dev-only route. Step 3 packs one pyramid
// into one PMTiles archive behind one `/terrain/` path, and an archive has no directories to
// choose between: there is exactly one sea treatment (bathymetry), one quantisation (8 m), one
// codec (lossless WebP) and one depth (z8) in it. Keeping the flags would leave four controls
// that work in `astro dev` and 404 in production — the dead runnable entry point this repo bans,
// and the same call that retired `?pmtiles` when the archive became the only relief path.
//
// What each one settled is recorded, so retiring the flag does not retire the answer:
//   ?dem      -> bathymetry, judged by eye at Step 0
//   ?quant    -> 8 m, the knee of the size curve
//   ?demfmt   -> lossless WebP, 0.67x PNG and byte-exact       a third smaller for nothing)
//   ?demdepth -> z0-8, because the declaration made depth spendable
//
//
// The flags that SURVIVE are the ones that never named a directory — `?terrain`, `?ramp`,
// `?demsize` and `?skirt` are all client-side knobs over these same bytes, so each still works
// identically against the archive and stays usable for any future look question.

/** MapLibre's two skirt strategies, and we ship "none". Skirts are vertical curtains hung off every
 *  tile edge to cover the LOD crack where render tiles of different zoom meet — MapLibre documents
 *  this cross-zoom seam tearing as a known limitation.
 *
 *  There is no third option and no length control: MapLibre's docs frame the choice as vertical
 *  artifacts ("auto") against horizontal hairline gaps at boundaries between zoom levels ("none").
 *  Statically the skirts touch only **0.41% of pixels** at z8 pitch 60 (0.13% by more than 8 DN) but
 *  by up to **242 DN** where they do — a thin high-contrast line, not a wash. That static footprint
 *  was never the complaint, though: the tearing is during MOTION, when the covering set churns and
 *  skirts appear and vanish at new boundaries every frame.
 *
 *  RATIFIED "none" by eye, in motion: **basically zero tearing on pan**, traded
 *  for tiny black specks. The specks confirm the mechanism twice over — they sit **only on drastic
 *  elevation changes and never on flatland**, which is exactly where the LOD crack is widest, and
 *  they read BLACK rather than sea-coloured because with terrain on the `space-floor` background is
 *  drawn INTO each render tile's texture, so a gap between tiles is not covered by it at all and
 *  shows the transparent canvas clear behind the globe. No background colour can fix that; only
 *  geometry could. */
export const TERRAIN_SKIRT_MODES = ["auto", "none"] as const;
export type TerrainSkirtMode = (typeof TERRAIN_SKIRT_MODES)[number];

/** Shipping strategy. NOT MapLibre's default — see the ratification note above. */
export const TERRAIN_SKIRT_DEFAULT: TerrainSkirtMode = "none";

/** Read `?skirt=auto|none`, defaulting to the ratified "none". Null for malformed only.
 *
 *  Passed to the Map CONSTRUCTOR — `terrainSkirtLength` is a MapOptions field, and the skirt is
 *  baked into the cached mesh at build time, so it cannot be changed on a live map without
 *  reaching into `_meshCache`. A page load per arm is the honest way to A/B it. */
export function parseTerrainSkirt(params: URLSearchParams): TerrainSkirtMode | null {
  const raw = params.get("skirt");
  if (raw === null || raw.trim() === "") return TERRAIN_SKIRT_DEFAULT;
  return TERRAIN_SKIRT_MODES.includes(raw as TerrainSkirtMode) ? (raw as TerrainSkirtMode) : null;
}

/** Declared tile sizes for the axis-B A/B. 512 is honest; 256 and 128 are deliberate
 *  misdeclarations that buy geometry by making a render tile cover less ground.
 *
 *  Each step down moves the mesh AND the DEM shelf one level together — facets go 8 -> 4 -> 2 CSS
 *  px, and the DEM goes camera-2 -> camera-1 -> camera. 128 was only worth listing once the z0-8
 *  pyramid existed (2026-07-28): against the z0-6 build it asks for z8, clamps to z6, and pays ~4x
 *  the render tiles for elevation it already had. It remains the most expensive arm by far —
 *  render tiles are per-frame framebuffer binds plus a full replay of the layer stack. */
export const TERRAIN_TILE_SIZES = [128, 256, 512] as const;
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
 *
 * PITCH COSTS A DEM LEVEL, and this function cannot see it. `coveringTiles` takes a per-tile
 * desired zoom from `defaultCalculateTileZoom(9.314, 3)`, which subtracts a pitch term and a
 * tile-count penalty. Measured 2026-07-28 at camera z8 against the z0-8 pyramid, deepest DEM
 * actually consumed:
 *
 *              pitch 0   pitch 30   pitch 60
 *     512        z6         z6         z6      <- cannot reach past z6 at any pitch
 *     256        z7         z7         z7
 *     128        z8         z8         z7      <- nominal says z8 at all three
 *
 * So the pitched view — the one terrain exists to make worth looking at — systematically gets
 * less elevation detail than flat-on, and 128's extra level evaporates exactly there.
 */
export function terrainZoomsFor(
  cameraZoom: number,
  declaredTileSize: number = TERRAIN_TILE_SIZE,
  maxZoom: number = TERRAIN_MAX_ZOOM,
): { renderZoom: number; demZoom: number } {
  const renderZoom = Math.max(0, Math.floor(cameraZoom + Math.log2(512 / (declaredTileSize * 2))));
  return { renderZoom, demZoom: Math.min(Math.max(0, renderZoom - 1), maxZoom) };
}
