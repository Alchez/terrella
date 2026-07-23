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
 *     usable globe on a weak GPU).
 *
 * The caller owns the sampling loop and applies the actions; each action must
 * earn its own sustained-slow window (the caller resets the samples after
 * acting), so one slow patch never cascades straight to minimum quality.
 */

/** Samples needed before a verdict — ~0.75 s of movement at 60 fps. */
export const MINIMUM_SAMPLE_COUNT = 45;

/** Cap on the rolling window the caller maintains — ~1.5 s at 60 fps. */
export const MAXIMUM_SAMPLE_COUNT = 90;

/** Median frame time above this is "slow" — sustained below ~30 fps. */
export const SLOW_MEDIAN_MILLISECONDS = 34;

/** Where the pixel-ratio lever lands: native resolution, no DPR supersampling. */
export const DEGRADED_PIXEL_RATIO = 1;

export type DegradationAction = "retire-spin" | "lower-pixel-ratio" | null;

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
 * The next lever to pull, cheapest first: retire the spin, then lower the pixel
 * ratio, then nothing (`null` — the ladder is exhausted and the caller should
 * stop measuring). A 1x screen has no pixel-ratio headroom to give back.
 */
export function nextDegradationAction(state: {
  spinning: boolean;
  pixelRatioLowered: boolean;
  devicePixelRatio: number;
}): DegradationAction {
  if (state.spinning) return "retire-spin";
  if (!state.pixelRatioLowered && state.devicePixelRatio > DEGRADED_PIXEL_RATIO) {
    return "lower-pixel-ratio";
  }
  return null;
}
