import { readFileSync } from "node:fs";
import { describe, it, expect } from "vitest";
import {
  formatGroundDistance,
  rulerGroundDistance,
  rulerSamplePoints,
  RULER_WIDTH_PX,
} from "./scaleRuler";
import globeSource from "../components/Globe.astro?raw";
import { BODIES } from "./bodies";

/**
 * The body of a named function in earth.astro, matched by BRACES rather than by a text span.
 *
 * A span matcher cannot tell what encloses a statement — it happily reports a line that has been
 * moved out of the block it was guarding. Counting braces is the only reading that answers
 * "is this statement still inside this function".
 */
function functionBody(source: string, signature: string): string {
  const start = source.indexOf(signature);
  expect(start, `earth.astro no longer contains \`${signature}\``).toBeGreaterThan(-1);
  let depth = 0;
  for (let index = start + signature.length - 1; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    else if (source[index] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  throw new Error(`unbalanced braces after \`${signature}\``);
}

/** A locator that answers with fixed coordinates and records what it was asked for. */
function fixedLocator(coordinates: { lng: number; lat: number }[]) {
  const asked: [number, number][] = [];
  let call = 0;
  return {
    asked,
    locate: (point: [number, number]) => {
      asked.push(point);
      const answer = coordinates[Math.min(call, coordinates.length - 1)];
      call += 1;
      return answer!;
    },
  };
}

describe("rulerGroundDistance", () => {
  it("measures between the two sample points and asks the locator for nothing else", () => {
    const locator = fixedLocator([
      { lng: 0, lat: 0 },
      { lng: 0, lat: 0 },
    ]);
    rulerGroundDistance(locator.locate, 6_371_008.8, 1000, 600);
    expect(locator.asked).toEqual(rulerSamplePoints(1000, 600));
    expect(locator.asked).toHaveLength(2);
  });

  it("turns the angle between them into an arc on the radius it was handed", () => {
    // One degree of longitude at the equator is exactly one degree of arc, so the expected answer
    // is the definition of a radian rather than a number copied from the implementation.
    const locator = fixedLocator([
      { lng: 0, lat: 0 },
      { lng: 1, lat: 0 },
    ]);
    expect(rulerGroundDistance(locator.locate, 1, 1000, 600)).toBeCloseTo(Math.PI / 180, 12);
  });

  it("scales with the body, which is the defect this argument exists for", () => {
    // THE FAILURE THIS REPLACES. The distance used to come from the locator's own point type, and
    // MapLibre's multiplies by a hardcoded 6371008.8 — so every planet reported Earth's distances.
    // Same angle, two bodies: the readings must differ by exactly the ratio of the radii.
    const separated = () =>
      fixedLocator([
        { lng: 10, lat: 45 },
        { lng: 11, lat: 45 },
      ]).locate;
    const onEarth = rulerGroundDistance(separated(), BODIES.earth.groundRadiusM, 1000, 600);
    const onMars = rulerGroundDistance(separated(), BODIES.mars.groundRadiusM, 1000, 600);
    expect(onMars / onEarth).toBeCloseTo(
      BODIES.mars.groundRadiusM / BODIES.earth.groundRadiusM,
      12,
    );
    // Stated as a magnitude too, because a ratio test passes just as happily when both are zero.
    expect(onEarth).toBeGreaterThan(onMars);
    expect(onEarth / onMars).toBeCloseTo(1.8759, 3);
  });

  it("survives two samples landing on the same point, where the cosine can exceed 1", () => {
    // THE LATITUDE IS MEASURED, NOT PICKED, and the first version of this test was vacuous for
    // exactly that reason: at a latitude I chose for looking plausible, `sin² + cos²` happens to
    // land at or below 1, so removing the clamp changed nothing and the harness reported MISSED.
    //
    // Swept at 2,000,000 latitudes, the sum exceeds 1 by one ulp at ~1% of them, spread across
    // every band rather than bunched at the poles. There `Math.acos` returns NaN, which the
    // formatter renders as the em-dash it keeps for "not a distance" — so the ruler would blank
    // itself rather than read zero.
    const locator = fixedLocator([{ lng: 12, lat: -59.98536 }]);
    expect(rulerGroundDistance(locator.locate, 6_371_008.8, 1000, 600)).toBe(0);
  });
});

/**
 * THE COST OF THIS PATH IS INVISIBLE TO EVERY OTHER CHECK.
 *
 * Reverting to `map.unproject` throws nothing, renders identically, and changes no test's output —
 * it just spends two synchronous GPU readbacks on every frame of every drag, which was measured at
 * 9.8% of the main thread. Source is the only place that difference is legible without a GPU, so
 * this reads the page's own text.
 */
describe("the ruler's measurement never resolves against terrain", () => {
  // Resolved INSIDE each test, never in the describe body. A throw out here is reported as a file
  // error with no test name attached, which both takes the other cases down with it and leaves the
  // mutation harness unable to say which guard fired — a guard that cannot be attributed is one
  // nobody can prove still works. Measured: the harness read it as `(unparsed)`.
  const locatorBody = () =>
    functionBody(globeSource, "function locateOnDatum([x, y]: [number, number]): maplibregl.LngLat {");
  const rulerBody = () => functionBody(globeSource, "function updateRuler(): void {");

  it("measures through the transform, not through map.unproject", () => {
    const body = locatorBody();
    expect(body).toContain("screenPointToLocation");
    // The returned locator must be the transform call itself, not merely a mention of it — the
    // first draft asserted only that `unproject` appeared after the symbol check, and the degraded
    // path satisfies that no matter what the primary branch does. Counting is what closes it.
    expect(body).toContain("locate.call(transform,");
    // IT IS `map.painter.transform`. `map.transform` reads plausibly, type-checks against a cast,
    // and is UNDEFINED at runtime — the first version of this fix reached for it, silently took the
    // degraded branch, and measured as no fix at all. Pinned so that costs a red test, not a rerun.
    expect(body).toContain("map.painter");
    expect(body).not.toMatch(/\bmap\.transform\b/);
    // AND THE READ MUST BE INSIDE THIS FUNCTION, i.e. per call. MapLibre replaces
    // `painter.transform` after our script runs, so a hoisted reference answers from a frozen
    // camera: the label sat at its startup reading at every zoom, silently, with the readback
    // correctly gone. Because this body is the per-call function, `map.painter` appearing in it IS
    // the assertion that the lookup was not hoisted out.
    expect(globeSource).not.toContain("const locateOnDatum =");
    const unprojects = body.match(/unproject/g) ?? [];
    expect(unprojects, "the only unproject allowed here is the degraded path").toHaveLength(1);
    const check = body.indexOf('typeof transform?.screenPointToLocation !== "function"');
    expect(check, "the fallback is no longer guarded by a symbol check").toBeGreaterThan(-1);
    expect(body.indexOf("unproject")).toBeGreaterThan(check);
  });

  it("names no terrain, which is the only way to make that call read back the GPU", () => {
    // `screenPointToLocation(point, terrain)` is the expensive overload, and terrain cannot be
    // passed without naming it. Case-insensitive so `getTerrain` and `map.terrain` both trip it.
    expect(locatorBody().toLowerCase()).not.toContain("terrain");
  });

  it("keeps the per-frame path free of any unproject at all", () => {
    expect(rulerBody()).not.toContain("unproject");
    expect(rulerBody()).toContain("rulerGroundDistance");
    expect(globeSource).toContain('from "../lib/scaleRuler"');
  });

  it("takes the radius from the body it is drawing, not from a number", () => {
    // The module is correct for any radius, so the call site is what decides which planet the
    // readout is about — and a literal here is indistinguishable from a correct page on Earth. Only
    // source can see it: the reading it produces is right for the one body anyone tests against.
    const body = rulerBody();
    expect(body).toContain("body.groundRadiusM");
    // A digit in this call is a radius that came from somewhere other than the registry. Matched
    // inside `rulerGroundDistance(...)` alone, so the `clientWidth`/`clientHeight` arguments and
    // any future numeric span are not what trips it.
    const call = body.slice(body.indexOf("rulerGroundDistance("));
    expect(call.slice(0, call.indexOf(")")), "a numeric literal reached the radius").not.toMatch(
      /\d/,
    );
  });

  it("canary — MapLibre still exposes the terrain-free conversion we reach for", () => {
    // The shipped bundle, where property names survive minification. `transform` is untyped on
    // `Map`, so a rename upstream would otherwise surface as a silent fallback to the slow path.
    const bundle = readFileSync(
      new URL("../../node_modules/maplibre-gl/dist/maplibre-gl.mjs", import.meta.url),
      "utf8",
    );
    expect(bundle).toContain("screenPointToLocation");
    expect(bundle).toMatch(/screenPointToLocation\(\w+(,\s*\w+)?\)\{/);
  });
});

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
