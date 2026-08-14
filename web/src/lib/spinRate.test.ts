import { describe, expect, it } from "vitest";
import { SPIN_REFERENCE_DEGREES, SPIN_REFERENCE_ZOOM, spinStepDegrees } from "./spinRate";

/**
 * The oracle is deliberately NOT the formula under test. `spinStepDegrees` exists to hold one
 * quantity constant — screen speed — and that quantity is computed here from MapLibre's own scale
 * relation, so a test can fail while the arithmetic in the module still "looks right".
 *
 * 512 is MapLibre's internal transform tile size, which is fixed and unrelated to the 256 the raster
 * sources declare; getting that wrong is the one substitution that would make this agree with a
 * broken module.
 */
const screenPxPerSecond = (zoom: number) => ((512 * 2 ** zoom) / 360) * spinStepDegrees(zoom);

/** The camera's real range — `minZoom: 0.4`, `maxZoom: 8` in Globe.astro. */
const CAMERA_ZOOMS = [0.4, 1, 1.6, 2.5, 3, 3.5, 4, 5, 5.66, 6, 7, 8];

describe("spinStepDegrees — one speed at every zoom", () => {
  it("holds the screen speed constant across the camera's whole range", () => {
    const speeds = CAMERA_ZOOMS.map(screenPxPerSecond);
    for (const speed of speeds) expect(speed).toBeCloseTo(speeds[0], 6);
  });

  it("is the ratified rate at the reference zoom, which is what pins the constant to the globe", () => {
    expect(spinStepDegrees(SPIN_REFERENCE_ZOOM)).toBe(SPIN_REFERENCE_DEGREES);
  });

  /**
   * THE ABSOLUTE SPEED, not a ratio — every other test here is relative and would go on passing if
   * both constants moved together. 22.76 px/s is the rate judged on the globe and is the only
   * number in this file a reader cannot re-derive from the other assertions.
   */
  it("holds the speed that was actually ratified on screen, not merely a self-consistent one", () => {
    expect(screenPxPerSecond(SPIN_REFERENCE_ZOOM)).toBeCloseTo(22.76, 2);
    expect(screenPxPerSecond(8)).toBeCloseTo(22.76, 2);
  });

  it("halves for every zoom level gained, which is the property that cancels the scale term", () => {
    for (const zoom of CAMERA_ZOOMS) {
      expect(spinStepDegrees(zoom + 1)).toBeCloseTo(spinStepDegrees(zoom) / 2, 12);
    }
  });

  it("never returns zero or a negative step, so direction stays the caller's to choose", () => {
    for (const zoom of CAMERA_ZOOMS) expect(spinStepDegrees(zoom)).toBeGreaterThan(0);
  });

  it("answers fractional zooms, because a wheel gesture never lands on an integer", () => {
    expect(spinStepDegrees(5.66)).toBeGreaterThan(spinStepDegrees(6));
    expect(spinStepDegrees(5.66)).toBeLessThan(spinStepDegrees(5));
  });

  /**
   * The regression this module exists to prevent. Under the old fixed step the surface crossed
   * 28% of a 2560 px viewport every second at z8 — the reason a ceiling had to forbid the control
   * rather than slow it. Asserting the RATIO to the reference keeps the claim true if the reference
   * speed is ever re-judged.
   */
  it("does not let the deep end run away from the reference the way a fixed step did", () => {
    const fixedStepSpeedAtZ8 = ((512 * 2 ** 8) / 360) * SPIN_REFERENCE_DEGREES;
    expect(fixedStepSpeedAtZ8 / screenPxPerSecond(SPIN_REFERENCE_ZOOM)).toBeCloseTo(32, 1);
    expect(screenPxPerSecond(8) / screenPxPerSecond(SPIN_REFERENCE_ZOOM)).toBeCloseTo(1, 6);
  });
});
