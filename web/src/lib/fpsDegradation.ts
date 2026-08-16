/**
 * The globe's runtime-degradation ladder, factored out of earth.astro so the
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

/**
 * WHICH FRAMES ARE JUDGED, AND WHY IT IS NOT "IS THE CAMERA MOVING"
 * ----------------------------------------------------------------
 * The rules above decide when a window is slow and what to pull. {@link FrameWindow} decides what
 * gets into the window, and it is a separate idea because the first version of the caller answered
 * it with `spinning || map.isMoving()` — which asks whether the CAMERA is animating when the
 * question is whether the MAIN THREAD is starved. Those come apart exactly where it matters:
 * a camera parked in a pathological view renders continuously without ever moving, so the gate
 * stayed shut, and the window was emptied on every frame it was shut for.
 *
 * Measured on the shipping build at the covering-tiles cliff, parked and untouched: 97.9% of the
 * window inside long tasks, `areTilesLoaded` false, and the ladder sitting on `disable-terrain` —
 * the rung that recovers frame time 79x — for 55 s while collecting ZERO samples.
 *
 * So the window is fed by the map's own `render` event and cleared by its `idle`:
 *
 *   render ─▶ record the interval since the previous render
 *   idle   ─▶ the map has drawn everything it wanted; clear, and forget the stamp
 *
 * `idle` is the right reset and that is a measurement rather than a reading of the docs: it fires
 * once at 396 ms on a healthy overview and NOT ONCE in 14.8 s at the cliff. The window therefore
 * clears exactly where there is nothing left to judge and survives exactly where there is.
 *
 * Forgetting the stamp matters as much as clearing the samples. Without it the first render after
 * a quiet spell records the whole spell as one enormous frame, which is a sleeping map wearing the
 * costume of a stalled one.
 *
 * A NOTE ON THE REJECTED SIMPLER FORM: keeping the caller's rAF loop and merely widening its gate
 * does not work. At the cliff the page delivers 22 rAF callbacks per 13 renders, so a rule that
 * empties the window on any callback that did not draw never accumulates a verdict at all.
 *
 * TWO TRIGGERS, FOR TWO REGIMES
 * -----------------------------
 * {@link isSustainedSlow} answers "this device is mediocre" — a 45-sample median against 34 ms,
 * deliberately slow to convince and robust to hitches. It is unchanged, and it is not the rule that
 * can save the cliff: at ~0.65 renders per second a 45-sample minimum is a 70-second wait, because
 * the count is a count and the frames it counts are seconds long. **The worse the frame rate, the
 * later that alarm rings.**
 *
 * {@link FrameWindow.slowRun} answers the other regime — "this page is not working at all" — with
 * consecutive intervals over {@link CATASTROPHIC_FRAME_MS}. It is far STRICTER in amplitude than
 * the sustained rule (15x its threshold), and it is what makes the ladder reach the cliff in ~4 s
 * instead of never. Neither trigger loosens the other; a device that is merely slow is judged by
 * exactly the rule that judged it before.
 */

/** Samples needed before a verdict — ~0.75 s of movement at 60 fps. */
export const MINIMUM_SAMPLE_COUNT = 45;

/** Cap on the rolling window the caller maintains — ~1.5 s at 60 fps. */
export const MAXIMUM_SAMPLE_COUNT = 90;

/** Median frame time above this is "slow" — sustained below ~30 fps. */
export const SLOW_MEDIAN_MILLISECONDS = 34;

/** Where the pixel-ratio lever lands: native resolution, no DPR supersampling. */
export const DEGRADED_PIXEL_RATIO = 1;

/**
 * A frame this slow is not a hitch, it is a stall — the page has stopped answering.
 *
 * 10x `perf/perfOverlay.ts`'s SLOW_FRAME_MS and 15x {@link SLOW_MEDIAN_MILLISECONDS}, so this is a
 * deliberately extreme reading rather than a second opinion about mediocrity. Set against what the
 * cliff actually produces: intervals of 1138-1597 ms, an order of magnitude clear of it.
 */
export const CATASTROPHIC_FRAME_MS = 500;

/**
 * Consecutive stalled frames before the fast path acts.
 *
 * A run rather than a count anywhere in the window, because a run is the shape no ordinary hitch
 * can forge: one 1.1 s cap-texture upload, one GC pause or one interrupted frame is a single
 * interval, and three IN SEQUENCE means at least 1.5 s of a main thread that never came back.
 * Three fires at 4.2 s against the measured cliff; two would fire at ~2.8 s and is the knob to
 * turn if that proves too patient on a phone.
 */
export const CATASTROPHIC_RUN_LENGTH = 3;

/** The frames under judgement, and how far the current stall has run. */
export interface FrameWindow {
  /** Intervals between consecutive renders, newest last, bounded by {@link MAXIMUM_SAMPLE_COUNT}. */
  intervalsMs: number[];
  /** When the map last drew, or null when it has drawn nothing since the last idle. */
  previousStampMs: number | null;
  /** Consecutive intervals over {@link CATASTROPHIC_FRAME_MS}, newest first. */
  slowRun: number;
}

export function newFrameWindow(): FrameWindow {
  return { intervalsMs: [], previousStampMs: null, slowRun: 0 };
}

/**
 * The map drew a frame at `stampMs`.
 *
 * The first render after a reset records no interval — there is nothing to measure it against, and
 * inventing one from a stale stamp is the failure this function exists to avoid.
 */
export function onFrameRendered(frames: FrameWindow, stampMs: number): FrameWindow {
  if (frames.previousStampMs === null) return { ...frames, previousStampMs: stampMs };
  const intervalMs = stampMs - frames.previousStampMs;
  const intervalsMs = [...frames.intervalsMs, intervalMs];
  if (intervalsMs.length > MAXIMUM_SAMPLE_COUNT) intervalsMs.shift();
  return {
    intervalsMs,
    previousStampMs: stampMs,
    slowRun: intervalMs > CATASTROPHIC_FRAME_MS ? frames.slowRun + 1 : 0,
  };
}

/**
 * Whether this window has earned a rung.
 *
 * Two regimes, either of which is sufficient: a sustained mediocre median (the rule that has always
 * shipped, unchanged), or a run of outright stalls. See the header for why one rule cannot be both.
 */
export function isDegradationWarranted(frames: FrameWindow): boolean {
  return isSustainedSlow(frames.intervalsMs) || frames.slowRun >= CATASTROPHIC_RUN_LENGTH;
}

export type DegradationAction =
  | "retire-spin"
  | "lower-pixel-ratio"
  | "disable-terrain"
  | null;

/** True when a full window of frame durations has a slow median. */
export function isSustainedSlow(frameDurationsMs: number[]): boolean {
  if (frameDurationsMs.length < MINIMUM_SAMPLE_COUNT) return false;
  const sortedDurations = [...frameDurationsMs].toSorted(
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
