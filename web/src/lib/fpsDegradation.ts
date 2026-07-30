/**
 * The globe's runtime-degradation ladder, factored out of globe.astro so the
 * decision logic is unit-testable (see fpsDegradation.test.ts).
 *
 * Two ideas, kept separate on purpose:
 *   - {@link isSustainedSlow} decides WHEN to act: a full sample window whose
 *     MEDIAN frame time is slow. The median (not mean) is load-bearing — GC or
 *     tile-decode hitches produce huge single frames that would drag a mean over
 *     any threshold while the experienced frame rate is fine.
 *   - {@link nextDegradationAction} decides WHAT to do next: retire the idle
 *     spin first (free — the globe just stops moving on its own), then drop the
 *     canvas to 1x pixel ratio (visible softness on hi-DPI screens, but ~4x
 *     fewer fragments at DPR 2 — the difference between a slideshow and a
 *     usable globe on a weak GPU), and only then disable terrain.
 *
 * The caller owns the sampling loop and applies the actions; each action must
 * earn its own sustained-slow window (the caller resets the samples after
 * acting), so one slow patch never cascades straight to minimum quality.
 *
 * WHY TERRAIN COMES LAST, AND NOT FIRST
 * ------------------------------------
 * The intuitive order puts terrain first — it is the heaviest-sounding feature,
 * and pixel ratio is the most visible loss. That is backwards, because the two
 * levers are COUPLED rather than independent.
 *
 * With terrain on, MapLibre stops drawing the globe straight to the canvas and
 * instead renders each tile into a fixed-size render-to-texture buffer, then
 * composites those. `rttSize = tileManager.tileSize * qualityFactor` — no term
 * in that is the device pixel ratio. So terrain swaps a DPR-scaled cost for a
 * DPR-INVARIANT one. Measured live at the shipping configuration (declared 128,
 * z0-8, 16 render tiles): canvas 1,451,125 px at DPR 1 and 13,060,125 at DPR 3
 * (exactly 9x), while total RTT pixels stayed at 4,194,304 in BOTH.
 *
 * The consequence: terrain's relative cost falls monotonically as DPR rises.
 * At DPR 1 the RTT path is ~2.9x the canvas's own pixel work and dropping it is
 * a clear win; at DPR 3 it is 0.32x, and dropping it hands the full 13 Mpx
 * canvas the whole layer stack instead — terrain measured 43% CHEAPER than off
 * at DPR 3 (HISTORY, the exaggeration-ramp entry). Pulling this rung first on a
 * hi-DPI phone could therefore make frames SLOWER.
 *
 * Lowering the pixel ratio is precisely what moves a device into the regime
 * where dropping terrain pays. Hence: spin, then pixel ratio, then terrain.
 *
 * THIS RUNG IS THE LADDER'S ONLY LEVER ON MEMORY
 * ----------------------------------------------
 * The two rungs above move frame time alone. This one moves both, but only
 * because the caller releases the raster-dem SOURCE as well as the terrain —
 * dropping the geometry by itself leaves every cached DEM tile resident.
 *
 * That residue is not a rounding error. MapLibre bounds a source's out-of-view
 * cache at `(ceil(W / D) + 1) * (ceil(H / D) + 1) * MAX_TILE_CACHE_ZOOM_LEVELS`
 * slots for DECLARED tile size D, while `DEMData` holds each tile as a Uint32Array
 * over the padded 514x514 RGBA buffer — ~1 MiB of heap apiece, fixed by the 512 px
 * ASSET and indifferent to the declaration. Slots scale as 1/D^2 while the bytes
 * behind them do not, so the ceiling grew ~10x when the terrain source went from
 * declaring 512 to declaring 128, reaching ~1 GiB on a desktop-sized canvas.
 *
 * Note what this does NOT settle: the rung is a last resort that fires only after
 * sustained slow frames, so it bounds the worst case rather than the ordinary one.
 * Keeping the cache from reaching that size in the first place is a separate
 * decision (a cache bound, or a smaller DEM asset) that this ladder does not make.
 */

/** Samples needed before a verdict — ~0.75 s of movement at 60 fps. */
export const MINIMUM_SAMPLE_COUNT = 45;

/** Cap on the rolling window the caller maintains — ~1.5 s at 60 fps. */
export const MAXIMUM_SAMPLE_COUNT = 90;

/** Median frame time above this is "slow" — sustained below ~30 fps. */
export const SLOW_MEDIAN_MILLISECONDS = 34;

/** Where the pixel-ratio lever lands: native resolution, no DPR supersampling. */
export const DEGRADED_PIXEL_RATIO = 1;

export type DegradationAction =
  | "retire-spin"
  | "lower-pixel-ratio"
  | "disable-terrain"
  | null;

/** True when a full window of frame durations has a slow median. */
export function isSustainedSlow(frameDurationsMs: number[]): boolean {
  if (frameDurationsMs.length < MINIMUM_SAMPLE_COUNT) return false;
  const sortedDurations = [...frameDurationsMs].sort(
    (first, second) => first - second,
  );
  const medianMs = sortedDurations[sortedDurations.length >> 1];
  return medianMs > SLOW_MEDIAN_MILLISECONDS;
}

/**
 * The next lever to pull: retire the spin, then lower the pixel ratio, then
 * disable terrain, then nothing (`null` — the ladder is exhausted and the
 * caller should stop measuring).
 *
 * A 1x screen has no pixel-ratio headroom to give back, so it skips straight to
 * the terrain rung — which is also the screen where that rung is worth the most
 * (see the module header). `terrainEnabled: true` is now the ordinary case for a
 * `full`-tier visitor, since terrain rides the tier rather than sitting behind
 * `?terrain=N`, so this rung is a real last resort rather than a theoretical one.
 * `?terrain=off` is what makes it false without demoting the tier.
 *
 * `devicePixelRatio` is the ratio the MAP is rendering at (`map.getPixelRatio()`), not the
 * display's. They agree today, since the map is constructed at the display ratio — but the ladder
 * itself lowers the map's, so reading the display's would report headroom already spent and burn
 * the middle rung on a no-op instead of reaching terrain.
 */
export function nextDegradationAction(state: {
  spinning: boolean;
  pixelRatioLowered: boolean;
  devicePixelRatio: number;
  terrainEnabled: boolean;
}): DegradationAction {
  if (state.spinning) return "retire-spin";
  if (!state.pixelRatioLowered && state.devicePixelRatio > DEGRADED_PIXEL_RATIO) {
    return "lower-pixel-ratio";
  }
  if (state.terrainEnabled) return "disable-terrain";
  return null;
}
