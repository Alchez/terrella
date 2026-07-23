import { describe, expect, it } from "vitest";
import {
  DEGRADED_PIXEL_RATIO,
  MINIMUM_SAMPLE_COUNT,
  SLOW_MEDIAN_MILLISECONDS,
  isSustainedSlow,
  nextDegradationAction,
} from "./fpsDegradation";

describe("isSustainedSlow", () => {
  it("stays quiet below the minimum sample count, however slow the frames", () => {
    const tooFewSlowFrames = Array(MINIMUM_SAMPLE_COUNT - 1).fill(50);
    expect(isSustainedSlow(tooFewSlowFrames)).toBe(false);
  });

  it("fires once a full window's median is slow", () => {
    const sustainedSlowFrames = Array(MINIMUM_SAMPLE_COUNT).fill(40);
    expect(isSustainedSlow(sustainedSlowFrames)).toBe(true);
  });

  it("ignores slow spikes when the median stays fast (median, not mean)", () => {
    // 50 fast frames + 10 big hitches: the mean (~42 ms) crosses the threshold,
    // the median (10 ms) does not — hitches alone must never degrade the globe.
    const fastWithHitches = [...Array(50).fill(10), ...Array(10).fill(200)];
    expect(isSustainedSlow(fastWithHitches)).toBe(false);
  });

  it("does not fire when the median sits exactly on the threshold", () => {
    const borderlineFrames = Array(MINIMUM_SAMPLE_COUNT).fill(SLOW_MEDIAN_MILLISECONDS);
    expect(isSustainedSlow(borderlineFrames)).toBe(false);
  });
});

describe("nextDegradationAction", () => {
  it("retires the spin first — the cheapest lever", () => {
    const action = nextDegradationAction({
      spinning: true,
      pixelRatioLowered: false,
      devicePixelRatio: 2,
    });
    expect(action).toBe("retire-spin");
  });

  it("drops the pixel ratio once the spin is already retired on a hi-DPI screen", () => {
    const action = nextDegradationAction({
      spinning: false,
      pixelRatioLowered: false,
      devicePixelRatio: 2,
    });
    expect(action).toBe("lower-pixel-ratio");
  });

  it("has nothing to drop on a 1x screen", () => {
    const action = nextDegradationAction({
      spinning: false,
      pixelRatioLowered: false,
      devicePixelRatio: DEGRADED_PIXEL_RATIO,
    });
    expect(action).toBe(null);
  });

  it("is exhausted once both levers are pulled", () => {
    const action = nextDegradationAction({
      spinning: false,
      pixelRatioLowered: true,
      devicePixelRatio: 2,
    });
    expect(action).toBe(null);
  });

  it("retires a user-restarted spin even after the pixel ratio was lowered", () => {
    const action = nextDegradationAction({
      spinning: true,
      pixelRatioLowered: true,
      devicePixelRatio: 2,
    });
    expect(action).toBe("retire-spin");
  });
});
