/**
 * How far the idle spin turns the globe in one step.
 *
 * The spin is a chain of one-second linear `easeTo`s that decrement the centre longitude, so a step
 * is also a second and this function's output is a speed.
 *
 * THE RATE IS CONSTANT IN PIXELS, NOT IN DEGREES, and that is the whole content of this module.
 * At the point the eye is on — the centre of the screen — the surface travels
 * `512 * 2**zoom / 360 * step` CSS px per second. A step fixed in degrees therefore doubles the
 * on-screen speed with every zoom level, which is why a fixed step had to be forbidden above a
 * ceiling instead of merely slowed. Halving the step per level cancels the term exactly, so one
 * ratified speed holds everywhere and there is no zoom at which the control misbehaves.
 *
 * ZOOM IS THE ONLY TERM, AND THAT IS A MEASUREMENT RATHER THAN A SIMPLIFICATION. Latitude, pitch and
 * terrain were each swept against this quantity and each came back flat — latitude because a
 * mercator x is linear in longitude, so the scale stretch cancels the ground-distance shrink and a
 * `cos(lat)` correction would be a bug rather than a refinement; pitch because tilt pivots about the
 * centre, which leaves the centre's scale alone. Do not add any of the three back without a sweep
 * that disagrees.
 */

/** The zoom whose speed every other zoom is held equal to. */
export const SPIN_REFERENCE_ZOOM = 3;

/**
 * Degrees of longitude per step AT the reference zoom — the rate that shipped for a year behind the
 * old ceiling and is therefore the one already judged acceptable on screen. Changing this changes
 * the speed at every zoom at once, which is the point of expressing it here rather than per level.
 */
export const SPIN_REFERENCE_DEGREES = 2;

/**
 * Degrees of longitude the spin should advance for one step at `zoom`.
 *
 * Always positive, so the caller owns the direction; the globe turns west because `spin()`
 * subtracts.
 */
export function spinStepDegrees(zoom: number): number {
  return SPIN_REFERENCE_DEGREES * 2 ** (SPIN_REFERENCE_ZOOM - zoom);
}
