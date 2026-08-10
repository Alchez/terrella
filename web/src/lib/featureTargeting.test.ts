import { describe, expect, it } from "vitest";
import {
  FLY_TO_VIEWPORT_FRACTION,
  MAX_CENTRE_LATITUDE,
  MAX_TARGET_VIEWPORT_FRACTION,
  MIN_TARGET_PX,
  candidateFrom,
  framingZoom,
  pickFeature,
  readsAtThisScale,
  screenExtentPx,
  viewportReferencePx,
} from "./featureTargeting";

/**
 * The pick rule that stands in for Earth's "one country per point".
 *
 * The scenarios at the bottom are the ones judged on a real globe, carried here as arithmetic so
 * the decision survives the screenshots that produced it. They are the reason this rule exists in
 * the shape it does, and a change that quietly re-admits a continent-sized bracket — or that makes
 * the most obvious thing on a phone screen untappable — fails there rather than in someone's eye
 * six commits later.
 */

const DESKTOP = { width: 1400, height: 760 };
const PHONE = { width: 390, height: 844 };

/** A crater-shaped candidate: the gazetteer's diameter is a width. */
const region = (name: string, diameterKm: number | null) => ({ name, diameterKm, linear: false });
/** A channel-shaped candidate: the same field is a length. */
const channel = (name: string, diameterKm: number | null) => ({ name, diameterKm, linear: true });

describe("sizing a feature against the current scale", () => {
  it("converts a diameter and a scale into pixels", () => {
    expect(screenExtentPx(100, 1000)).toBe(100);
  });

  it("treats a nonsensical scale as unsized rather than as enormous", () => {
    // A zero or negative metres-per-pixel is a broken reading, and dividing by it yields Infinity
    // either way. What matters is that the feature comes back UNPICKABLE, because the alternative
    // is a highlight landing on whatever the arithmetic happened to favour.
    expect(screenExtentPx(100, 0)).toBe(Number.POSITIVE_INFINITY);
    expect(readsAtThisScale(region("x", 100), 0, DESKTOP)).toBe(false);
    expect(readsAtThisScale(region("x", 100), Number.NaN, DESKTOP)).toBe(false);
  });

  it("measures the viewport by the geometric mean of its sides, not the shorter one", () => {
    // The property that matters is aspect-insensitivity: a tall narrow frame and a wide short one
    // of the same area get the same reference, so the same feature at the same zoom is judged the
    // same way on both. Dividing by the shorter side did not, and a phone paid for it.
    expect(viewportReferencePx({ width: 400, height: 900 }))
      .toBeCloseTo(viewportReferencePx({ width: 900, height: 400 }), 6);
    expect(viewportReferencePx({ width: 1000, height: 1000 })).toBe(1000);
  });

  it("holds the band at both ends", () => {
    // Exactly at each bound is IN, so the constants read as the band's edges rather than as values
    // one pixel outside it.
    expect(readsAtThisScale(region("x", MIN_TARGET_PX), 1000, DESKTOP)).toBe(true);
    expect(readsAtThisScale(region("x", MIN_TARGET_PX - 0.001), 1000, DESKTOP)).toBe(false);

    const ceilingKm = (MAX_TARGET_VIEWPORT_FRACTION * viewportReferencePx(DESKTOP) * 1000) / 1000;
    expect(readsAtThisScale(region("x", ceilingKm), 1000, DESKTOP)).toBe(true);
    expect(readsAtThisScale(region("x", ceilingKm + 1), 1000, DESKTOP)).toBe(false);
  });

  it("gives a linear feature no ceiling, because its diameter is a length", () => {
    // A channel running off both edges is still a channel, and the part under the pointer is the
    // part being pointed at. Ares Vallis is 1,758 km end to end and was unreachable at every zoom
    // while the ceiling applied to it.
    const enormous = 5000;
    expect(readsAtThisScale(region("a region", enormous), 1000, DESKTOP)).toBe(false);
    expect(readsAtThisScale(channel("a channel", enormous), 1000, DESKTOP)).toBe(true);
    // The FLOOR still applies to both — a channel too small to see is no more pointable than a
    // crater too small to see.
    expect(readsAtThisScale(channel("a channel", 1), 1000, DESKTOP)).toBe(false);
  });
});

describe("reading a style feature's properties", () => {
  it("takes a name and a diameter, and the kind from the caller", () => {
    expect(candidateFrom({ name: "Gale", diameter: 154 }, false))
      .toEqual({ name: "Gale", diameterKm: 154, linear: false });
    expect(candidateFrom({ name: "Nirgal Vallis", diameter: 610 }, true))
      .toEqual({ name: "Nirgal Vallis", diameterKm: 610, linear: true });
  });

  it("treats a missing diameter as unsized rather than as zero", () => {
    // The cutter drops a falsy diameter from the tile, so absence is data. Zero would sail under
    // the floor and read as "too small", which is a different and wrong answer.
    expect(candidateFrom({ name: "Gale" }, false))
      .toEqual({ name: "Gale", diameterKm: null, linear: false });
    expect(candidateFrom({ name: "Gale", diameter: 0 }, false))
      .toEqual({ name: "Gale", diameterKm: null, linear: false });
  });

  it("refuses anything without a usable name, because the name is the feature-state id", () => {
    expect(candidateFrom({ diameter: 12 }, false)).toBeNull();
    expect(candidateFrom({ name: "", diameter: 12 }, false)).toBeNull();
    expect(candidateFrom({ name: 7, diameter: 12 }, false)).toBeNull();
    expect(candidateFrom(null, false)).toBeNull();
  });
});

describe("picking the one feature to name", () => {
  it("returns null when nothing is under the pointer", () => {
    expect(pickFeature([], 1000, DESKTOP)).toBeNull();
  });

  it("picks the SMALLEST ELIGIBLE, not the smallest", () => {
    // The whole rule in one case: a sub-pixel crater must not beat the region actually on screen.
    const picked = pickFeature(
      [region("a speck", 5), region("the one you can see", 300), region("the container", 4000)],
      2000,
      DESKTOP,
    );
    expect(picked).toBe("the one you can see");
  });

  it("answers with the container once the finer feature stops reading", () => {
    const nested = [region("crater", 60), region("terra", 4000)];
    expect(pickFeature(nested, 200, DESKTOP)).toBe("crater");
    expect(pickFeature(nested, 9000, DESKTOP)).toBe("terra");
  });

  it("returns null over ground whose only container is too big to fit", () => {
    // Deliberately not a fallback to the container. This is the state that makes the rule
    // learnable: nothing is named because nothing on screen is the thing you are pointing at.
    expect(pickFeature([region("terra", 4000)], 1000, DESKTOP)).toBeNull();
  });

  it("never picks an unsized feature, even when it is the only candidate", () => {
    expect(pickFeature([region("unsized", null)], 1000, DESKTOP)).toBeNull();
    expect(pickFeature([region("unsized", null), region("sized", 100)], 1000, DESKTOP))
      .toBe("sized");
  });
});

describe("the judgements made on a real globe", () => {
  /**
   * Metres per pixel at the cameras the look was ratified at, taken from the scale ruler's own
   * reading in each frame. Approximate by nature — what they pin is which SIDE of the band each
   * camera fell on, which is what was decided by eye.
   */
  const SCALE = {
    overview: 13_500, // whole disc, Terra Sabaea comfortably inside the frame
    regional: 9_000, // the terra's full shape on screen
    tooClose: 6_150, // the frame where its straight edges start slicing visible craters
    crater: 1_250, // Schiaparelli filling a good part of the view
  };
  const TERRA_SABAEA = region("Terra Sabaea", 4688);
  const SCHIAPARELLI = region("Schiaparelli", 459);
  const ARES_VALLIS = channel("Ares Vallis", 1758);

  it("paints a terra at the zooms where it was judged acceptable", () => {
    expect(pickFeature([TERRA_SABAEA], SCALE.overview, DESKTOP)).toBe("Terra Sabaea");
    expect(pickFeature([TERRA_SABAEA], SCALE.regional, DESKTOP)).toBe("Terra Sabaea");
  });

  it("drops the terra at the zoom where it was judged wrong", () => {
    // The frame that killed the earlier proposal: fully legal by any rule that only asked whether
    // it fitted the shorter side, and visibly arbitrary against the terrain.
    expect(pickFeature([TERRA_SABAEA], SCALE.tooClose, DESKTOP)).toBeNull();
  });

  it("prefers the crater over its terra once the crater reads", () => {
    expect(pickFeature([SCHIAPARELLI, TERRA_SABAEA], SCALE.crater, DESKTOP)).toBe("Schiaparelli");
  });

  it("still prefers a 459 km crater at overview, because it is not a speck there", () => {
    // Checked rather than assumed: at the overview scale Schiaparelli is still a few tens of pixels
    // across, which is a target anyone can point at. The first version of this test asserted the
    // terra won here on the strength of the word "overview", and the arithmetic disagreed.
    expect(screenExtentPx(SCHIAPARELLI.diameterKm!, SCALE.overview)).toBeGreaterThan(MIN_TARGET_PX);
    expect(pickFeature([SCHIAPARELLI, TERRA_SABAEA], SCALE.overview, DESKTOP)).toBe("Schiaparelli");
  });

  it("prefers the terra at overview where the crater really is a speck", () => {
    expect(pickFeature([region("a 22 km crater", 22), TERRA_SABAEA], SCALE.overview, DESKTOP))
      .toBe("Terra Sabaea");
  });

  it("answers the same crater on a portrait phone, which is where this was caught", () => {
    // A LIVE FAILURE, not a hypothetical: a tap on the most obvious thing on a phone screen
    // returned nothing, because the ceiling divided by the shorter side and a 390 px-wide frame
    // made a perfectly visible crater score as an overflow.
    expect(pickFeature([SCHIAPARELLI], SCALE.crater, PHONE)).toBe("Schiaparelli");
    expect(pickFeature([SCHIAPARELLI], SCALE.crater, DESKTOP)).toBe("Schiaparelli");
  });

  it("answers a channel whose length crosses the frame several times", () => {
    // The other live failure. Ares Vallis is longer than any zoom that shows its width can fit.
    expect(pickFeature([ARES_VALLIS], SCALE.crater, DESKTOP)).toBe("Ares Vallis");
    expect(pickFeature([ARES_VALLIS], SCALE.crater, PHONE)).toBe("Ares Vallis");
  });
});

describe("framing a feature the camera has to fly to", () => {
  const MARS_RADIUS_M = 3396190;

  /** What the feature actually spans on screen once the camera is at `zoom`. */
  function arrivalExtentPx(diameterKm: number, zoom: number, latitude: number): number {
    const metresPerPixel =
      (2 * Math.PI * MARS_RADIUS_M * Math.cos((latitude * Math.PI) / 180)) / (512 * 2 ** zoom);
    return screenExtentPx(diameterKm, metresPerPixel);
  }

  it("stays under the ceiling that decides a feature can be pointed at", () => {
    // THE ONE HARD CONSTRAINT, and the reason both constants live in one file. Framing at or above
    // the ceiling lands the camera exactly where the feature stops being a target — the highlight
    // would vanish on arrival, on the feature you just asked to be taken to.
    expect(FLY_TO_VIEWPORT_FRACTION).toBeLessThan(MAX_TARGET_VIEWPORT_FRACTION);
  });

  it("lands the diameter on the chosen share of the viewport reference", () => {
    for (const viewport of [DESKTOP, PHONE]) {
      for (const diameterKm of [154, 610, 2299, 4852]) {
        const zoom = framingZoom(diameterKm, 0, viewport, MARS_RADIUS_M)!;
        const wanted = FLY_TO_VIEWPORT_FRACTION * viewportReferencePx(viewport);
        expect(arrivalExtentPx(diameterKm, zoom, 0)).toBeCloseTo(wanted, 6);
      }
    }
  });

  it("still answers the pointer on arrival", () => {
    // The property the fraction exists to protect, asserted through the picker rather than restated
    // as arithmetic: fly to a landmark and it must still be the thing under the cursor.
    for (const viewport of [DESKTOP, PHONE]) {
      const zoom = framingZoom(4852, 0, viewport, MARS_RADIUS_M)!;
      const metresPerPixel =
        (2 * Math.PI * MARS_RADIUS_M) / (512 * 2 ** zoom);
      expect(pickFeature([region("Arabia Terra", 4852)], metresPerPixel, viewport))
        .toBe("Arabia Terra");
    }
  });

  it("frames a polar feature for where the camera can actually go", () => {
    // Seven adopted centres sit past the Mercator clamp. Sizing the view from the feature's own
    // latitude computes for a camera position that cannot be reached and arrives too close, so a
    // centre at 87.7 must be framed exactly as one at the clamp.
    const past = framingZoom(1000, 87.73, DESKTOP, MARS_RADIUS_M);
    const atClamp = framingZoom(1000, MAX_CENTRE_LATITUDE, DESKTOP, MARS_RADIUS_M);
    expect(past).toBe(atClamp);
    expect(past).toBeLessThan(framingZoom(1000, 87.73, DESKTOP, MARS_RADIUS_M * 2)!);
  });

  it("takes cos(latitude) into account rather than framing every feature as equatorial", () => {
    // The globe's ground scale falls off with latitude exactly as Mercator's does — measured on a
    // real transform across z0-z8 — so the same feature needs a lower zoom the further north it is.
    expect(framingZoom(500, 60, DESKTOP, MARS_RADIUS_M)!)
      .toBeCloseTo(framingZoom(500, 0, DESKTOP, MARS_RADIUS_M)! - 1, 3);
  });

  it("declines to size a feature the gazetteer publishes at zero", () => {
    // Null is "centre it and change nothing else" — the same refusal to guess a size that
    // `candidateFrom` makes, and the two must agree or one catalogue disagrees with itself.
    expect(framingZoom(null, 0, DESKTOP, MARS_RADIUS_M)).toBeNull();
    expect(framingZoom(0, 0, DESKTOP, MARS_RADIUS_M)).toBeNull();
  });

  it("declines a viewport that has not been laid out yet", () => {
    // A map in a zero-height element builds a transform that projects every ground point onto one
    // screen point; a zoom computed against it would be Infinity and the camera would never return.
    expect(framingZoom(100, 0, { width: 0, height: 0 }, MARS_RADIUS_M)).toBeNull();
  });
});
