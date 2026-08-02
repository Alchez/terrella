import { readFileSync } from "node:fs";
import { describe, it, expect } from "vitest";
import {
  formatGroundDistance,
  rulerGroundDistance,
  rulerSamplePoints,
  RULER_WIDTH_PX,
} from "./scaleRuler";
import globeSource from "../pages/globe.astro?raw";

/**
 * The body of a named function in globe.astro, matched by BRACES rather than by a text span.
 *
 * A span matcher cannot tell what encloses a statement — it happily reports a line that has been
 * moved out of the block it was guarding. Counting braces is the only reading that answers
 * "is this statement still inside this function".
 */
function functionBody(source: string, signature: string): string {
  const start = source.indexOf(signature);
  expect(start, `globe.astro no longer contains \`${signature}\``).toBeGreaterThan(-1);
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

describe("rulerGroundDistance", () => {
  it("measures between the two sample points and asks the locator for nothing else", () => {
    const asked: [number, number][] = [];
    const distance = rulerGroundDistance(
      (point) => {
        asked.push(point);
        return { distanceTo: () => 4_800 };
      },
      1000,
      600,
    );
    expect(distance).toBe(4_800);
    expect(asked).toEqual(rulerSamplePoints(1000, 600));
    expect(asked).toHaveLength(2);
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
