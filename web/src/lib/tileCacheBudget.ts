/**
 * How much heap MapLibre's tile cache is allowed to pin for a raster-dem source, and how much it
 * is pinning right now.
 *
 * THE ROOT CAUSE, IN ONE SENTENCE
 * ------------------------------
 * MapLibre sizes a source's out-of-view cache from `_source.tileSize` but FILLS it at
 * `tileManager.tileSize`, and for a terrain source those are not the same number.
 *
 * The two call sites, both in `tile_manager.ts` and both read out of the shipped v6 bundle:
 *
 *   updateCacheSize()   (ceil(w / this._source.tileSize) + 1) * (ceil(h / this._source.tileSize) + 1)
 *                       * MAX_TILE_CACHE_ZOOM_LEVELS  ->  _outOfViewCache.setMaxSize(...)
 *
 *   update()            coveringTiles(transform, {
 *                         tileSize: this.usedForTerrain ? this.tileSize : this._source.tileSize, ... })
 *
 * `TerrainTileManager`'s constructor sets `this.tileSize = tileManager._source.tileSize * 2 **
 * deltaZoom` with `deltaZoom = 1`, then writes it back as `tileManager.tileSize`. So a source
 * declaring 128 is filled from a screen tiled at 256 and sized for a screen tiled at 128 —
 * **4x the tiling density the fill rate can ever use**. Nothing about this is terrain-specific
 * reasoning on MapLibre's part: it is one field read in two places, and `usedForTerrain` is
 * honoured in only one of them.
 *
 * The realised ratio is lower than 4 at any real canvas, because each factor carries a `+ 1`
 * border term that does not halve with the tile size — 1,260 slots against 385 at 2500x1300, so
 * 3.27x. Four is the limit as the canvas grows, not the number to quote.
 *
 * WHY THAT COSTS A GIGABYTE RATHER THAN A ROUNDING ERROR
 * -----------------------------------------------------
 * A cached tile pins `tile.dem`, a `Uint32Array` over the padded RGBA image, and that buffer is
 * sized by the ASSET (512 px, so a 514 stride, 1,056,784 bytes) with no reference to the
 * declaration. Slots therefore scale as 1/declared^2 while the bytes behind each slot do not move
 * at all. Going from declaring 512 to declaring 128 multiplied the ceiling ~16x on paper and ~10x
 * in practice, and the change was priced out loud as costing REQUESTS.
 *
 * A slot is only freed on eviction: `TileCache`'s onRemove is `_unloadTile` -> the raster-dem
 * source's `unloadTile`, which is the sole `delete tile.dem`. Until the cap is reached, nothing
 * evicts.
 *
 * WHAT THIS MODULE IS FOR
 * -----------------------
 * {@link terrainCacheSlotBound} is the cap that cancels the mismatch — the slot count MapLibre
 * would have computed had `updateCacheSize` honoured `usedForTerrain` like `update` does.
 * {@link summariseDemCache} reads what is actually resident, so the bound is chosen against a
 * measurement rather than against this arithmetic.
 *
 * The canary in the test file reads the shipped bundle: if MapLibre ever makes the two call sites
 * agree, this cap becomes an over-constraint and the canary fails rather than the globe quietly
 * losing cache it should have kept.
 */

import { megabytes } from "./format";

/** `config.MAX_TILE_CACHE_ZOOM_LEVELS`, which `Map` also installs as the default option value. */
export const MAPLIBRE_MAX_TILE_CACHE_ZOOM_LEVELS = 5;

/** `TerrainTileManager.deltaZoom`, a hard-coded 1 — the doubling behind the whole mismatch. */
export const TERRAIN_DELTA_ZOOM = 1;

/** The padding `RGBAImage` carries on every side, which is why a 512 px tile has a 514 stride. */
export const DEM_TILE_PADDING_PX = 1;

/**
 * Heap bytes one cached DEM tile pins, from the tile's ASSET size in pixels.
 *
 * `DEMData` keeps `new Uint32Array(data.data.buffer)` over the padded RGBA image, so this is the
 * whole cost and it is indifferent to the declared tile size. Stated as arithmetic rather than as
 * a constant because the 256 px-asset arm is a live option, and there the answer is 4x smaller.
 */
export function demSlotBytes(assetTilePixels: number): number {
  const stride = assetTilePixels + 2 * DEM_TILE_PADDING_PX;
  return stride * stride * 4;
}

/**
 * MapLibre's own `updateCacheSize` arithmetic, restated so a change to it fails a test.
 *
 * `tileSizeForSizing` is deliberately a parameter rather than "the declared size": the entire
 * defect is that MapLibre passes the declared size here and a different one to `coveringTiles`.
 */
export function viewDependentCacheSlots(
  canvasWidthPx: number,
  canvasHeightPx: number,
  tileSizeForSizing: number,
  zoomLevels: number = MAPLIBRE_MAX_TILE_CACHE_ZOOM_LEVELS,
): number {
  const tilesAcross = Math.ceil(canvasWidthPx / tileSizeForSizing) + 1;
  const tilesDown = Math.ceil(canvasHeightPx / tileSizeForSizing) + 1;
  return Math.floor(tilesAcross * tilesDown * zoomLevels);
}

/** The tile size MapLibre actually COVERS a terrain source at: the declaration, doubled. */
export function terrainFillTileSize(declaredTileSize: number): number {
  return declaredTileSize * 2 ** TERRAIN_DELTA_ZOOM;
}

/** The public shape of `Map.coveringTiles`. */
export interface CoveringTilesReader {
  coveringTiles?: (options: {
    tileSize: number;
    minzoom?: number;
    maxzoom?: number;
    roundZoom?: boolean;
  }) => unknown[];
}

/**
 * How many tiles this camera ACTUALLY needs — MapLibre's own answer, not our restatement of it.
 *
 * `Map.coveringTiles` is public and is literally the function `TileManager.update` fills from
 * (both reach the same internal `coveringTiles`), so this is the fill side of the mismatch read
 * directly instead of estimated. It matters because `viewDependentCacheSlots` is a RECTANGLE —
 * `(ceil(w/tileSize)+1) × (ceil(h/tileSize)+1) × 5` — and a globe view is not one. Measured on a
 * 2560×1265 canvas at z5: **52 tiles at tileSize 256 against the formula's 330**, and 129 against
 * 1155 at 128. The formula over-counts by ~6×, which is why the byte budget it feeds had no
 * defensible upper bound.
 *
 * TWO REASONS THIS IS A LOWER BOUND, NOT THE EXACT FILL SET — read it as such:
 *  - The public options accept only `{tileSize, minzoom, maxzoom, roundZoom}`. The internal call
 *    also passes `terrain`, which feeds `allowVariableZoom`, so an elevated camera can cover
 *    differently than this reports.
 *  - `TileManager.update` then runs `_addTerrainIdealTiles` on the result, which only ADDS.
 *
 * Both gaps are visible rather than hidden: the perf line prints this beside the realized in-view
 * count from `summariseDemCache`, and the difference between them IS the terrain addition
 * (measured 52 → 67, about +29% at that camera).
 */
export function terrainCoveringTileCount(
  map: CoveringTilesReader | undefined,
  declaredTileSize: number,
  minZoom: number,
  maxZoom: number,
): number | null {
  if (typeof map?.coveringTiles !== "function") return null;
  try {
    const covering = map.coveringTiles({
      // The FILL size, which is the whole point — the declared size is what MapLibre wrongly
      // sizes the cache from, and reading it here would reproduce the bug in the instrument.
      tileSize: terrainFillTileSize(declaredTileSize),
      minzoom: minZoom,
      maxzoom: maxZoom,
      roundZoom: false, // `!usedForTerrain && source.roundZoom` — always false for a terrain source
    });
    return Array.isArray(covering) ? covering.length : null;
  } catch {
    // A camera mid-transition can throw inside the covering walk. Null, not zero: an unreadable
    // camera and a camera needing nothing are different facts.
    return null;
  }
}

/**
 * The cap that makes the cache match the fill rate — `viewDependentCacheSlots` at the size
 * `coveringTiles` uses, not the size `updateCacheSize` uses.
 *
 * Derived from the live canvas rather than hard-coded, because the quantity it corrects is
 * canvas-dependent: a fixed integer would over-constrain a large screen and under-constrain a
 * small one, and MapLibre applies it as `Math.min(cap, viewDependentMaxSize)` so it can only ever
 * shrink the cache, never grow it.
 */
export function terrainCacheSlotBound(
  canvasWidthPx: number,
  canvasHeightPx: number,
  declaredTileSize: number,
  zoomLevels: number = MAPLIBRE_MAX_TILE_CACHE_ZOOM_LEVELS,
): number {
  return viewDependentCacheSlots(
    canvasWidthPx,
    canvasHeightPx,
    terrainFillTileSize(declaredTileSize),
    zoomLevels,
  );
}

/**
 * How far ABOVE {@link terrainCacheSlotBound} the shipped cap sits, and the only number here that
 * was chosen rather than derived.
 *
 * The bound alone is too tight, and that was measured rather than reasoned — it is the one
 * prediction in this module that the A/B refuted. Sweeping caps on a 12-position regional tour
 * whose working set was 294 tiles, revisiting the same ground:
 *
 *     cap      605    450    300    240    180
 *     refetch    3      3      3    303    338
 *
 * The knee is exactly "cap >= working set", and it is a cliff rather than a slope. The derived
 * bound on that canvas was 180 — below the knee, so a visitor who tours a few regions and comes
 * back would re-download the neighbourhood. A smooth drag across ~30 degrees has a working set of
 * only 50-83 and backtracks free at every cap tested, so ordinary panning never sees this.
 *
 * Two is the smallest integer multiple that clears the measured knee (360 against 294, ~23%
 * margin) while still scaling with the canvas. It is not a derivation: the knee is a property of
 * how far the USER roams, which no canvas measurement can predict. What the multiple buys is
 * headroom over the hardest realistic route measured, and `?demcache=` exists so the next person
 * to doubt it can sweep it without a rebuild.
 *
 * Why the bound under-predicts at all: MapLibre's flat formula expected 36 tiles in view where the
 * globe projection actually produced 45, because a sphere admits variable zoom toward the limb.
 */
export const TERRAIN_CACHE_SLOT_MULTIPLIER = 2;

/** The pixel size of a shipped terrain tile — `terrain_params.json`'s `tile_size`. Stated once so
 *  the 256 px arm is a one-line change and so no byte figure is spelled inline. */
export const TERRAIN_ASSET_TILE_PX = 512;

/**
 * A hard ceiling in BYTES on what the DEM cache may hold, and the reason a slot formula alone is
 * not a memory guard.
 *
 * The multiplier above scales with canvas AREA, so on a large screen it grants a larger cache —
 * exactly backwards. Every other GPU consumer grows with the canvas too (render-to-texture tiles,
 * relief textures, the polar cap rungs), so the DEM cache's share should SHRINK as the screen
 * grows, not expand. Left unbounded the formula gives:
 *
 *     1235x1175    360 slots    363 MB
 *     2560x1321    770 slots    813 MB
 *     3840x2160   1600 slots   1.69 GB   <- more than an uncapped laptop screen
 *
 * That was measured on a real failure, not imagined: at 2560x1321 Chrome's GPU process reached
 * 6.2 GB of VRAM, lost the WebGL context four times, and each restore left MapLibre with an empty
 * style and a painter that threw on every frame. No NVRM Xid, so the driver was healthy and the
 * budget was ours to overspend.
 *
 * 384 MiB is chosen so the ceiling does NOT bind at laptop sizes — 2x derived is 360 slots there,
 * under the 381 this allows, so today's measured behaviour is unchanged — and binds above roughly
 * 1300 px square, where the formula starts outrunning the machine.
 *
 * The trade is explicit and it is the right way round: above that size we accept REFETCHES, which
 * cost network and decode and recover on their own, rather than context loss, which does not
 * recover at all. A cache miss is a slower frame; a lost context is a dead tab.
 */
export const TERRAIN_CACHE_BYTE_BUDGET = 384 * 1024 * 1024;

/** How many slots fit a byte budget, given what one slot actually costs. */
export function slotsWithinByteBudget(
  budgetBytes: number,
  assetTilePixels: number = TERRAIN_ASSET_TILE_PX,
): number {
  return Math.max(1, Math.floor(budgetBytes / demSlotBytes(assetTilePixels)));
}

/**
 * The cap the globe actually installs: the canvas-derived bound times the measured margin, then
 * clamped to {@link TERRAIN_CACHE_BYTE_BUDGET}.
 *
 * Two governors with different jobs. Below the budget the formula rules, so a small screen keeps a
 * cache proportional to what it can actually revisit. Above it the budget rules, flatly, because
 * past that point the failure being avoided stops being "a refetch" and starts being "a dead tab".
 */
export function shippedTerrainCacheSlots(
  canvasWidthPx: number,
  canvasHeightPx: number,
  declaredTileSize: number,
  multiplier: number = TERRAIN_CACHE_SLOT_MULTIPLIER,
  budgetBytes: number = TERRAIN_CACHE_BYTE_BUDGET,
  assetTilePixels: number = TERRAIN_ASSET_TILE_PX,
): number {
  const derived =
    terrainCacheSlotBound(canvasWidthPx, canvasHeightPx, declaredTileSize) * multiplier;
  return Math.min(derived, slotsWithinByteBudget(budgetBytes, assetTilePixels));
}

/** `?demcache=` — `off` for the uncapped control, an integer to pin a slot count, absent for the
 *  canvas-derived default. The three arms of the A/B, addressable from Zen without a rebuild. */
export type DemCacheSetting =
  | { kind: "derived" }
  | { kind: "fixed"; slots: number }
  | { kind: "off" };

/** Read `?demcache=off|<slots>`, defaulting to the derived cap. Null for malformed only, which the
 *  caller turns into a loud warning — same contract as `parseTerrainTileSize`. */
export function parseDemCacheSetting(params: URLSearchParams): DemCacheSetting | null {
  const raw = params.get("demcache");
  if (raw === null || raw.trim() === "") return { kind: "derived" };
  if (raw.trim() === "off") return { kind: "off" };
  const slots = Number(raw);
  if (!Number.isInteger(slots) || slots < 1) return null;
  return { kind: "fixed", slots };
}

/** The slot cap to install, or null to leave MapLibre's own sizing alone. */
export function resolveDemCacheSlots(
  setting: DemCacheSetting,
  canvasWidthPx: number,
  canvasHeightPx: number,
  declaredTileSize: number,
): number | null {
  if (setting.kind === "off") return null;
  if (setting.kind === "fixed") return setting.slots;
  return shippedTerrainCacheSlots(canvasWidthPx, canvasHeightPx, declaredTileSize);
}

/** What {@link summariseDemCache} reports. Bytes are heap only — GPU textures are pooled separately
 *  by the painter (`saveTileTexture`/`getTileTexture`) and do not grow per cached tile.
 *
 *  Cached and in-view bytes are kept APART rather than summed, because only the cached ones are
 *  subject to the cap. Reporting one total against the ceiling reads as an overflow the moment the
 *  cache is full — "659 MB (ceiling 610 MB)" was the first thing the running overlay printed. */
export interface DemCacheSummary {
  /** Tiles sitting in the out-of-view cache. These are what `maxSlots` bounds. */
  cachedTiles: number;
  /** Tiles currently in view. They hold their `dem` too, and no cap applies to them. */
  inViewTiles: number;
  /** `TileCache.max` — the live ceiling `updateCacheSize` last wrote. */
  maxSlots: number;
  /** Summed `tile.dem.data.byteLength` over the out-of-view cache. */
  cachedBytes: number;
  /** Summed `tile.dem.data.byteLength` over the in-view tiles. */
  inViewBytes: number;
}

/**
 * The shape {@link summariseDemCache} needs. Structural rather than MapLibre's own `TileManager`
 * so the tests can build an honest fake, and so a rename upstream surfaces as a `null` return
 * instead of a plausible zero.
 */
export interface TileManagerLike {
  _maxTileCacheSize?: number | null;
  _outOfViewCache?: {
    max?: unknown;
    data?: Record<string, Array<{ value?: { dem?: { data?: { byteLength?: unknown } } } }>>;
  };
  _inViewTiles?: {
    getAllTiles?: () => Array<{ dem?: { data?: { byteLength?: unknown } } }>;
  };
}

/**
 * Install the cap, or report that there was nothing to install it on.
 *
 * `_maxTileCacheSize` is underscore-prefixed but present in MapLibre's public `.d.ts`, so this
 * needs no cast. It is re-read on every `updateCacheSize` — i.e. every render — which is what
 * makes a post-`addSource` write take effect at all, and what lets a resize re-derive it. Verified
 * live: dropping it to 1 drained a full 605-slot cache within six frames.
 *
 * Returns false rather than throwing, because the caller runs inside a `style.load` handler where
 * a throw would take the rest of the terrain wiring with it.
 */
export function applyDemCacheCap(
  tileManager: TileManagerLike | undefined,
  slots: number | null,
): boolean {
  if (!tileManager || typeof tileManager !== "object") return false;
  if (!("_maxTileCacheSize" in tileManager)) return false;
  tileManager._maxTileCacheSize = slots;
  return true;
}

/**
 * Did the cap actually take EFFECT? Returns a description of the fault, or null if all is well.
 *
 * Writing the field and assuming is not verification. Two things can go wrong independently and
 * neither throws: the write can fail to stick (a getter-only property, a renamed field, the wrong
 * source), and MapLibre can decline to honour it (if `updateCacheSize` ever stops applying the
 * `Math.min`). This checks both, against the live cache rather than against our own intent —
 * `_outOfViewCache.max` is the number MapLibre is really enforcing.
 *
 * Call it after MapLibre has rendered at least once, since `updateCacheSize` runs per render;
 * calling it before the first frame reports a fault that is only a stale reading.
 */
export function demCacheCapFault(
  tileManager: TileManagerLike | undefined,
  intendedSlots: number | null,
): string | null {
  if (!tileManager || typeof tileManager !== "object") return "no terrain tile manager";
  if (intendedSlots === null) return null; // the uncapped arm asks for nothing to enforce
  const written = tileManager._maxTileCacheSize;
  if (written !== intendedSlots) {
    return `cap did not stick — wrote ${intendedSlots}, field reads ${String(written)}`;
  }
  const enforced = tileManager._outOfViewCache?.max;
  if (typeof enforced !== "number") return "cache reports no max — MapLibre internals moved";
  if (enforced > intendedSlots) {
    return `cap not enforced — asked ${intendedSlots}, MapLibre is holding ${enforced}`;
  }
  return null;
}

function demByteLength(tile: { dem?: { data?: { byteLength?: unknown } } } | undefined): number {
  const byteLength = tile?.dem?.data?.byteLength;
  return typeof byteLength === "number" ? byteLength : 0;
}

/**
 * Read a source's resident DEM heap directly, or `null` if the structures are not what this
 * expects.
 *
 * Null rather than zero is the whole point: an empty cache and a renamed field are the same
 * number, and only one of them is news. Callers surface the null (the perf overlay prints
 * "dem cache n/a") rather than reporting a reassuring 0 MB.
 */
export function summariseDemCache(tileManager: TileManagerLike | undefined): DemCacheSummary | null {
  const outOfViewCache = tileManager?._outOfViewCache;
  if (!outOfViewCache || typeof outOfViewCache.data !== "object" || outOfViewCache.data === null) {
    return null;
  }
  if (typeof outOfViewCache.max !== "number") return null;

  const getAllTiles = tileManager?._inViewTiles?.getAllTiles;
  if (typeof getAllTiles !== "function") return null;
  const inViewTiles = getAllTiles.call(tileManager._inViewTiles);
  if (!Array.isArray(inViewTiles)) return null;

  let cachedTiles = 0;
  let cachedBytes = 0;
  for (const entries of Object.values(outOfViewCache.data)) {
    if (!Array.isArray(entries)) continue;
    for (const entry of entries) {
      cachedTiles += 1;
      cachedBytes += demByteLength(entry?.value);
    }
  }
  let inViewBytes = 0;
  for (const tile of inViewTiles) inViewBytes += demByteLength(tile);

  return {
    cachedTiles,
    inViewTiles: inViewTiles.length,
    maxSlots: outOfViewCache.max,
    cachedBytes,
    inViewBytes,
  };
}

/**
 * The `?perf` rows: cached bytes against the cap, then the uncapped in-view tiles separately.
 *
 * Names the arm as well as the numbers. A capture that does not say whether it was capped is
 * unreadable a week later, and this is a flag whose whole point is being swept.
 *
 * TWO rows rather than one, and measured rather than judged by eye: the single line ran to 121
 * characters against the 53 the panel's own font allows on a 412 px phone, so it wrapped into three
 * screen rows mid-fact. Split at the seam that already existed — what the cache HOLDS, then what
 * the camera needs and which arm set the bound.
 *
 * These are **system RAM**, not VRAM: `demSlotBytes` prices the `Uint32Array` that `DEMData` keeps
 * over the padded image. The panel groups them under RAM for that reason. That the 384 MiB ceiling
 * exists to bound a *VRAM* failure is a fact about the budget's derivation, not about where these
 * bytes live
 */
export function demCacheLines(
  summary: DemCacheSummary | null,
  setting?: DemCacheSetting,
  coveringTiles?: number | null,
): string[] {
  if (summary === null) return ["dem cache n/a — MapLibre internals moved"];
  // What the camera needs against what the cap allows. The ratio is the number the byte budget
  // never had: "381 slots" is unreadable, "5.7x what this camera needs" prices the headroom.
  const need =
    typeof coveringTiles === "number"
      ? `needs ${coveringTiles} (${(summary.maxSlots / Math.max(1, coveringTiles)).toFixed(1)}x headroom)`
      : "";
  const arm =
    setting === undefined
      ? ""
      : setting.kind === "off"
        ? "uncapped (?demcache=off)"
        : setting.kind === "fixed"
          ? `capped ${setting.slots} (?demcache)`
          : `capped ${TERRAIN_CACHE_SLOT_MULTIPLIER}x derived, ` +
            `${megabytes(TERRAIN_CACHE_BYTE_BUDGET)} MB budget`;
  // Three rows, split where the facts already divide: what the cache HOLDS, what this camera puts
  // in view against what it needs, and which arm set the bound. Two rows still overran — holding
  // plus in-view came to 57 characters against the 53 the panel's font allows on a 412 px phone.
  const inView =
    `view +${megabytes(summary.inViewBytes)} MB / ${summary.inViewTiles} tiles` +
    (need === "" ? "" : ` · ${need}`);
  return [
    `dem ${megabytes(summary.cachedBytes)}/` +
      `${megabytes(summary.maxSlots * demSlotBytes(TERRAIN_ASSET_TILE_PX))} MB · ` +
      `${summary.cachedTiles}/${summary.maxSlots} slots`,
    inView,
    // Omitted entirely when no setting was passed, rather than rendered as an empty row.
    ...(arm === "" ? [] : [arm]),
  ];
}

/**
 * The `?perf` line for a source that may not exist yet.
 *
 * THREE outcomes, not two, and collapsing the first two is a real defect: the terrain source is
 * added on `style.load`, so "no source yet" is the ordinary state for the first frames and for
 * every `?terrain=off` visit — printing "MapLibre internals moved" there cries wolf on a page that
 * is working perfectly, and would train the reader to ignore the one message that is news.
 * (Caught by reading the overlay rather than the tests: both cases returned null, and only one of
 * them deserved the alarming string.)
 */
export function describeDemCacheState(
  tileManager: TileManagerLike | undefined,
  setting?: DemCacheSetting,
  coveringTiles?: number | null,
): string[] {
  if (tileManager === undefined || tileManager === null) return ["dem cache — no terrain source"];
  return demCacheLines(summariseDemCache(tileManager), setting, coveringTiles);
}
