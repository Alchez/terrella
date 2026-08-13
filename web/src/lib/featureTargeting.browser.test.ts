import { afterEach, describe, expect, it } from "vitest";
import { datumLocator, mountGlobe, type MountedGlobe } from "./testing/mountGlobe";
import { RULER_WIDTH_PX, rulerGroundDistance } from "./scaleRuler";
import {
  FLY_TO_VIEWPORT_FRACTION,
  MAX_CENTRE_LATITUDE,
  MAX_TARGET_VIEWPORT_FRACTION,
  MIN_TARGET_PX,
  framingZoom,
  screenExtentPx,
  viewportReferencePx,
} from "./featureTargeting";
import { BODIES } from "./bodies";

/**
 * The framing arithmetic against a REAL globe transform, which is the only thing that can falsify it.
 *
 * `featureTargeting.test.ts` checks that the algebra inverts — feed the zoom back through the same
 * ground-resolution law and the extent comes out where it was asked for. That is a round trip of one
 * formula and it would pass just as cleanly if the formula did not describe MapLibre's globe at all.
 * WHAT IS UNVERIFIABLE THERE IS THE PREMISE: that zoom maps to ground scale on a GLOBE the way it
 * does on a Mercator plane. Measured here across the zooms and latitudes the catalogue actually
 * needs, through the same reading the hover picker takes at runtime.
 *
 * THE INSTRUMENT IS THE PAGE'S OWN, DELIBERATELY. `featureAt` sizes a candidate by unprojecting two
 * screen points and dividing, so a framing checked any other way could agree with the transform and
 * still disagree with the thing that decides whether a feature answers. Flying and then asking the
 * picker closes exactly that gap.
 *
 * WHAT THAT INSTRUMENT CANNOT SEE, and the last test here is about: it reads the scale AT THE SCREEN
 * CENTRE and everything above extrapolates that across the whole feature, which is a FLAT-PLANE
 * step. On a sphere a feature spanning tens of degrees curves away from the camera, so it projects
 * to less than the flat extrapolation — measured on the shipped page, Gale (2.6 degrees of arc)
 * lands within a pixel of its target while Arabia Terra (82 degrees) comes in 12% under. Every
 * assertion above would pass unchanged if that error ran the other way, which is why the direction
 * is pinned separately.
 */

const MARS = BODIES.mars;
const WIDTH = 800;
const HEIGHT = 600;
const VIEWPORT = { width: WIDTH, height: HEIGHT };

let mounted: MountedGlobe | null = null;
afterEach(() => {
  mounted?.dispose();
  mounted = null;
});

/** Ground metres per CSS pixel as the RUNTIME reads it — unproject, subtract, divide. */
function measuredMetresPerPixel(globe: MountedGlobe): number {
  return (
    rulerGroundDistance(datumLocator(globe), MARS.groundRadiusM, WIDTH, HEIGHT) / RULER_WIDTH_PX
  );
}

/** Landmarks spanning the catalogue's scale range, with the latitudes they actually sit at. */
const LANDMARKS: [name: string, diameterKm: number, latitude: number][] = [
  ["Gale", 154, -5.0],
  ["Olympus Mons", 610, 18.4],
  ["Hellas Planitia", 2299, -42.4],
  ["Arabia Terra", 4852, 21.0],
];

describe("the framing zoom lands where it says on a real globe", () => {
  it("puts each landmark's diameter on the chosen share of the viewport", async () => {
    mounted = await mountGlobe({ zoom: 2, center: [0, 0], width: WIDTH, height: HEIGHT });
    const wanted = FLY_TO_VIEWPORT_FRACTION * viewportReferencePx(VIEWPORT);
    for (const [name, diameterKm, latitude] of LANDMARKS) {
      const zoom = framingZoom(diameterKm, latitude, VIEWPORT, MARS.groundRadiusM);
      expect(zoom, `${name} could not be sized`).not.toBeNull();
      mounted.map.jumpTo({ center: [0, latitude], zoom: zoom! });
      const extent = screenExtentPx(diameterKm, measuredMetresPerPixel(mounted));
      // 2%, and the residual is not uniform: measured 0.02% at z6.6, 0.08% at z4.5, 0.4% at z2.2
      // and 1.2% at z1.5. It grows as zoom falls, which is the shape of the effect
      // `scaleRuler.browser.test.ts` already documents in its own oracle — the ruler reads a 96 px
      // chord as flat ground. A tighter bound would pass for craters and fail for continents.
      expect(
        Math.abs(extent / wanted - 1),
        `${name} arrived at ${extent.toFixed(0)}px, wanted ${wanted.toFixed(0)}`,
      ).toBeLessThan(0.02);
    }
  });

  it("leaves every landmark still pickable at the scale it arrives on", async () => {
    // The property a visitor sees. It is asserted through the picker's own thresholds rather than
    // as a number, so a change to either constant fails here on the outcome rather than on a
    // restatement of it.
    mounted = await mountGlobe({ zoom: 2, center: [0, 0], width: WIDTH, height: HEIGHT });
    const reference = viewportReferencePx(VIEWPORT);
    for (const [name, diameterKm, latitude] of LANDMARKS) {
      mounted.map.jumpTo({
        center: [0, latitude],
        zoom: framingZoom(diameterKm, latitude, VIEWPORT, MARS.groundRadiusM)!,
      });
      const extent = screenExtentPx(diameterKm, measuredMetresPerPixel(mounted));
      expect(extent, `${name} arrived too small to aim at`).toBeGreaterThan(MIN_TARGET_PX);
      expect(extent, `${name} arrived too big to be a target`)
        .toBeLessThan(MAX_TARGET_VIEWPORT_FRACTION * reference);
    }
  });

  it("frames a polar feature for the latitude the camera is actually allowed to reach", async () => {
    // Boreales Scopuli's centre is 88.88N and the transform refuses to go past 85.0511. Sizing from
    // the feature's own latitude would compute for a camera that cannot exist and arrive too close,
    // so this asserts the camera really is clamped AND that the arrival still respects the ceiling.
    mounted = await mountGlobe({ zoom: 2, center: [0, 0], width: WIDTH, height: HEIGHT });
    const zoom = framingZoom(1075, 88.88, VIEWPORT, MARS.groundRadiusM)!;
    mounted.map.jumpTo({ center: [0, 88.88], zoom });
    expect(mounted.map.getCenter().lat).toBeCloseTo(MAX_CENTRE_LATITUDE, 3);
    const extent = screenExtentPx(1075, measuredMetresPerPixel(mounted));
    expect(extent).toBeLessThan(MAX_TARGET_VIEWPORT_FRACTION * viewportReferencePx(VIEWPORT));
    expect(extent).toBeGreaterThan(MIN_TARGET_PX);
  });

  it("never overfills the frame once the sphere's curvature is taken into account", async () => {
    // THE TARGET IS AN UPPER BOUND ON A SPHERE, NOT AN EQUALITY, and the direction is the safety
    // property: a feature that projects SMALLER than asked is further from the ceiling and still a
    // target, where one projecting larger would arrive unpickable. Measured by projecting the
    // feature's own edges rather than extrapolating the centre scale, which is the step every
    // assertion above takes and none of them can check.
    mounted = await mountGlobe({ zoom: 2, center: [0, 0], width: WIDTH, height: HEIGHT });
    const wanted = FLY_TO_VIEWPORT_FRACTION * viewportReferencePx(VIEWPORT);
    const projectedSpanPx = (longitude: number, latitude: number, diameterKm: number): number => {
      const halfDegrees = (((diameterKm * 1000) / 2 / MARS.groundRadiusM) * 180) / Math.PI;
      const halfLongitude = halfDegrees / Math.cos((latitude * Math.PI) / 180);
      const left = mounted!.map.project([longitude - halfLongitude, latitude]);
      const right = mounted!.map.project([longitude + halfLongitude, latitude]);
      return Math.hypot(right.x - left.x, right.y - left.y);
    };
    for (const [name, diameterKm, latitude] of LANDMARKS) {
      mounted.map.jumpTo({
        center: [0, latitude],
        zoom: framingZoom(diameterKm, latitude, VIEWPORT, MARS.groundRadiusM)!,
      });
      const span = projectedSpanPx(0, latitude, diameterKm);
      expect(span, `${name} projected ${span.toFixed(0)}px, over the ${wanted.toFixed(0)}px target`)
        .toBeLessThanOrEqual(wanted + 1);
      expect(span, `${name} projected ${span.toFixed(0)}px — too far under to be the same rule`)
        .toBeGreaterThan(0.8 * wanted);
    }
  });

  it("can fail — a zoom one level off misses the target extent", async () => {
    // The control. Every assertion above compares a measurement to a target, and a measurement that
    // silently returned the target would pass all of them; one octave of zoom must move it by 2x.
    mounted = await mountGlobe({ zoom: 2, center: [0, 0], width: WIDTH, height: HEIGHT });
    const zoom = framingZoom(610, 18.4, VIEWPORT, MARS.groundRadiusM)!;
    mounted.map.jumpTo({ center: [0, 18.4], zoom });
    const onTarget = screenExtentPx(610, measuredMetresPerPixel(mounted));
    mounted.map.jumpTo({ center: [0, 18.4], zoom: zoom - 1 });
    const oneOut = screenExtentPx(610, measuredMetresPerPixel(mounted));
    expect(onTarget / oneOut).toBeCloseTo(2, 1);
  });
});
