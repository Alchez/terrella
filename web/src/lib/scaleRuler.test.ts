import { describe, it, expect } from "vitest";
import { formatGroundDistance, rulerSamplePoints, RULER_WIDTH_PX } from "./scaleRuler";

describe("formatGroundDistance", () => {
  it("reports kilometres above a kilometre and metres below it", () => {
    expect(formatGroundDistance(1_800_000)).toBe("1,800 km");
    expect(formatGroundDistance(4_800)).toBe("4.8 km");
    expect(formatGroundDistance(1_000)).toBe("1 km");
    expect(formatGroundDistance(940)).toBe("940 m");
    expect(formatGroundDistance(480)).toBe("480 m");
  });

  it("holds to two significant figures, so the last digit does not churn during a drag", () => {
    // A raw reading changes every frame of a pan. Three figures would also imply a precision a
    // sphere cannot give — scale is only true at the point you measure it.
    expect(formatGroundDistance(1_847_213)).toBe("1,800 km");
    expect(formatGroundDistance(1_852_004)).toBe("1,900 km");
    expect(formatGroundDistance(47_318)).toBe("47 km");
  });

  it("crosses the unit boundary when rounding pushes it there", () => {
    // Anything from ~995 m up rounds to 1000 at two significant figures, and "1,000 m" is a unit
    // the label has already left behind — so the branch re-derives it as "1 km".
    expect(formatGroundDistance(999.6)).toBe("1 km");
    expect(formatGroundDistance(995)).toBe("1 km");
    // Just below, it stays in metres rather than reporting a spurious "1 km".
    expect(formatGroundDistance(994)).toBe("990 m");
  });

  it("blanks rather than inventing a zero for a reading that is not a distance", () => {
    // A camera mid-flight or a sample that missed the globe. A plausible "0 m" is worse than an
    // obvious blank, because only one of them is visibly wrong.
    for (const bad of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(formatGroundDistance(bad)).toBe("—");
    }
  });
});

describe("rulerSamplePoints", () => {
  it("straddles the centre of the viewport, spanning exactly the ruler's width", () => {
    // Centred, not anchored at x=0 like MapLibre's control: on a globe the viewport's left edge is
    // frequently off the sphere, where unprojecting returns a point on the plane behind it.
    const [left, right] = rulerSamplePoints(1000, 800);
    expect(left).toEqual([500 - RULER_WIDTH_PX / 2, 400]);
    expect(right).toEqual([500 + RULER_WIDTH_PX / 2, 400]);
    expect(right[0] - left[0]).toBe(RULER_WIDTH_PX);
  });

  it("keeps both samples on screen at the narrowest viewport the site supports", () => {
    // 320 px is the floor the chrome is swept against. A ruler wider than the frame would sample
    // off-canvas and read a distance for pixels nobody can see.
    const [left, right] = rulerSamplePoints(320, 568);
    expect(left[0]).toBeGreaterThanOrEqual(0);
    expect(right[0]).toBeLessThanOrEqual(320);
  });

  it("honours an explicit span, so the constant is not baked into the geometry", () => {
    const [left, right] = rulerSamplePoints(1000, 800, 40);
    expect(right[0] - left[0]).toBe(40);
  });
});
