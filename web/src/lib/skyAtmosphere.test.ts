import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import {
  ATMOSPHERE_PITCH_RAMP_END_DEG,
  ATMOSPHERE_PITCH_RAMP_START_DEG,
  ATMOSPHERE_RAMP_END_ZOOM,
  ATMOSPHERE_RAMP_START_ZOOM,
  BASE_ATMOSPHERE_BLEND,
  DEFAULT_ATMOSPHERE_FLOOR,
  PITCHED_ATMOSPHERE_BLEND,
  atmosphereBlend,
  atmosphereDecayRatio,
  atmosphereNeedsRebuild,
  defaultAtmosphereRamp,
  describeAtmosphereState,
  parseAtmosphereRamp,
  pitchedAtmosphereBase,
  rampedAtmosphereBlend,
  skySpec,
} from "./skyAtmosphere";

const flags = (search: string) => new URLSearchParams(search);

/** MapLibre's own interpolation, transcribed from
 *  @maplibre/maplibre-gl-style-spec/src/expression/definitions/interpolate.ts so the ramp is
 *  checked against the semantics that will actually evaluate it rather than against itself. The
 *  package is a transitive dependency and does not resolve from here, so this is a transcription,
 *  not an import — but it is an algebraically DIFFERENT expression from the geometric form in
 *  rampedAtmosphereBlend, which is the point: if the exponential base were wrong, the two would
 *  disagree everywhere between the stops and agree only at them. */
const maplibreInterpolationFactor = (
  base: number,
  input: number,
  lower: number,
  upper: number,
): number => {
  const difference = upper - lower;
  const progress = input - lower;
  if (difference === 0) return 0;
  if (base === 1) return progress / difference;
  return (base ** progress - 1) / (base ** difference - 1);
};

/** Evaluate the two-stop expression the way MapLibre will, clamping outside the stops. */
const evaluateExpression = (expression: unknown, zoom: number): number => {
  if (typeof expression === "number") return expression;
  const parts = expression as [string, ["exponential", number] | ["linear"], unknown, number, number, number, number];
  const [, interpolation, , lowerZoom, lowerValue, upperZoom, upperValue] = parts;
  if (zoom <= lowerZoom) return lowerValue;
  if (zoom >= upperZoom) return upperValue;
  const base = interpolation[0] === "linear" ? 1 : interpolation[1];
  const t = maplibreInterpolationFactor(base, zoom, lowerZoom, upperZoom);
  return lowerValue + t * (upperValue - lowerValue);
};

describe("the ramp holds its ends and falls between them", () => {
  it("holds the base at and below the start zoom", () => {
    expect(rampedAtmosphereBlend(0.7, 0)).toBe(0.7);
    expect(rampedAtmosphereBlend(0.7, ATMOSPHERE_RAMP_START_ZOOM)).toBe(0.7);
    expect(rampedAtmosphereBlend(0.7, 1.6)).toBe(0.7); // the globe's own opening camera
  });

  it("holds the floor at and above the end zoom", () => {
    expect(rampedAtmosphereBlend(0.7, ATMOSPHERE_RAMP_END_ZOOM)).toBe(DEFAULT_ATMOSPHERE_FLOOR);
    // maxZoom is 8, so everything past the end zoom is reachable and must stay pinned.
    expect(rampedAtmosphereBlend(0.7, 8)).toBe(DEFAULT_ATMOSPHERE_FLOOR);
  });

  it("decreases monotonically across the span", () => {
    let previous = Infinity;
    for (let zoom = 2; zoom <= 7; zoom += 0.1) {
      const blend = rampedAtmosphereBlend(BASE_ATMOSPHERE_BLEND, zoom);
      expect(blend).toBeLessThanOrEqual(previous + 1e-12);
      previous = blend;
    }
  });

  it("spends most of the reduction by z5, which is the measured reason it is geometric", () => {
    // The limb is out of frame by z5 at pitch 0 (0 of 10 sampled rows off-globe), so the
    // atmosphere should be most of the way down by then. Linear would leave 0.333 here.
    expect(rampedAtmosphereBlend(BASE_ATMOSPHERE_BLEND, 4)).toBeCloseTo(0.419, 3);
    expect(rampedAtmosphereBlend(BASE_ATMOSPHERE_BLEND, 5)).toBeCloseTo(0.251, 3);
  });
});

describe("the shipped expression and the JS mirror are the same ramp", () => {
  it("agrees with MapLibre's interpolation at every step, not just at the stops", () => {
    const expression = atmosphereBlend(defaultAtmosphereRamp());
    for (let zoom = 0; zoom <= 8; zoom += 0.1) {
      expect(evaluateExpression(expression, zoom)).toBeCloseTo(
        rampedAtmosphereBlend(BASE_ATMOSPHERE_BLEND, zoom),
        10,
      );
    }
  });

  it("agrees for a floor supplied by ?sky, not only the default", () => {
    const expression = atmosphereBlend({ kind: "ramp", floor: 0.4 });
    for (let zoom = 0; zoom <= 8; zoom += 0.25) {
      expect(evaluateExpression(expression, zoom)).toBeCloseTo(
        rampedAtmosphereBlend(BASE_ATMOSPHERE_BLEND, zoom, 0.4),
        10,
      );
    }
  });

  it("uses the per-level decay ratio as the exponential base — the identity the ramp rests on", () => {
    const expression = atmosphereBlend(defaultAtmosphereRamp()) as unknown as unknown[];
    expect(expression[1]).toEqual(["exponential", atmosphereDecayRatio()]);
    // Three levels of that ratio must carry the base exactly onto the floor.
    expect(BASE_ATMOSPHERE_BLEND * atmosphereDecayRatio() ** 3).toBeCloseTo(
      DEFAULT_ATMOSPHERE_FLOOR,
      12,
    );
  });

  it("falls back to linear for a zero floor, which geometric decay cannot express", () => {
    // MapLibre's exponentialInterpolation divides by base**span - 1; base 0 degenerates it.
    const expression = atmosphereBlend({ kind: "ramp", floor: 0 }) as unknown as unknown[];
    expect(expression[1]).toEqual(["linear"]);
    expect(evaluateExpression(expression, ATMOSPHERE_RAMP_END_ZOOM)).toBe(0);
    expect(evaluateExpression(expression, 4.5)).toBeCloseTo(0.35, 10);
  });

  it("collapses to a plain number when the ramp is off", () => {
    expect(atmosphereBlend({ kind: "off" })).toBe(BASE_ATMOSPHERE_BLEND);
  });
});

describe("?sky parsing refuses to guess", () => {
  it("treats absent and empty as the default ramp", () => {
    expect(parseAtmosphereRamp(flags(""))).toEqual({ kind: "ramp", floor: DEFAULT_ATMOSPHERE_FLOOR });
    expect(parseAtmosphereRamp(flags("?sky="))).toEqual({
      kind: "ramp",
      floor: DEFAULT_ATMOSPHERE_FLOOR,
    });
  });

  it("reads off, case-insensitively", () => {
    expect(parseAtmosphereRamp(flags("?sky=off"))).toEqual({ kind: "off" });
    expect(parseAtmosphereRamp(flags("?sky=OFF"))).toEqual({ kind: "off" });
  });

  it("accepts a floor inside MapLibre's own range, zero included", () => {
    expect(parseAtmosphereRamp(flags("?sky=0.35"))).toEqual({ kind: "ramp", floor: 0.35 });
    // 0 is a legitimate arm here (no atmosphere past the overview), unlike ?terrain=0.
    expect(parseAtmosphereRamp(flags("?sky=0"))).toEqual({ kind: "ramp", floor: 0 });
    expect(parseAtmosphereRamp(flags("?sky=1"))).toEqual({ kind: "ramp", floor: 1 });
  });

  it("returns null for malformed so the caller can warn instead of silently ramping", () => {
    expect(parseAtmosphereRamp(flags("?sky=abc"))).toBeNull();
    expect(parseAtmosphereRamp(flags("?sky=-0.1"))).toBeNull();
    expect(parseAtmosphereRamp(flags("?sky=1.5"))).toBeNull(); // past MapLibre's maximum of 1
  });

  it("hands back a fresh default each call, so a caller cannot mutate the next one's", () => {
    const first = defaultAtmosphereRamp();
    expect(first).not.toBe(defaultAtmosphereRamp());
  });
});

describe("the sky spec carries everything else unchanged", () => {
  it("keeps the committed colours and blends", () => {
    const spec = skySpec(defaultAtmosphereRamp());
    expect(spec["sky-color"]).toBe("#8fb8d6");
    expect(spec["horizon-color"]).toBe("#cbd8dd");
    expect(spec["fog-color"]).toBe("#dfe7ea");
    expect(spec["sky-horizon-blend"]).toBe(0.5);
    expect(spec["horizon-fog-blend"]).toBe(0.5);
    expect(spec["fog-ground-blend"]).toBe(0.1);
  });

  it("puts the ramp on atmosphere-blend and nowhere else", () => {
    expect(skySpec(defaultAtmosphereRamp())["atmosphere-blend"]).toEqual(
      atmosphereBlend(defaultAtmosphereRamp()),
    );
    expect(skySpec({ kind: "off" })["atmosphere-blend"]).toBe(BASE_ATMOSPHERE_BLEND);
  });
});

describe("the perf read-out describes what is on screen", () => {
  it("reports the live value and the arm", () => {
    expect(describeAtmosphereState(1.6, defaultAtmosphereRamp())).toBe("sky 0.70 · ramp 0.7→0.15");
    expect(describeAtmosphereState(8, defaultAtmosphereRamp())).toBe("sky 0.15 · ramp 0.7→0.15");
  });

  it("names the control arm rather than reporting a ramp that is not running", () => {
    expect(describeAtmosphereState(8, { kind: "off" })).toBe("sky 0.70 · ramp off");
    expect(describeAtmosphereState(8, { kind: "off" }, 60)).toBe("sky 0.70 · ramp off");
  });

  it("names the pitch term only where it bites, so the line is not noise", () => {
    const ramp = defaultAtmosphereRamp();
    expect(describeAtmosphereState(1.6, ramp, 30)).toBe("sky 0.70 · ramp 0.7→0.15");
    expect(describeAtmosphereState(1.6, ramp, 60)).toBe(
      "sky 0.25 · ramp 0.7→0.15 · pitch 60°→0.25");
  });

  it("tracks the expression MapLibre evaluates, so the overlay cannot disagree with the pixels", () => {
    const ramp = defaultAtmosphereRamp();
    const expression = atmosphereBlend(ramp);
    for (const zoom of [2, 3.5, 4.4, 5.2, 6, 7.5]) {
      expect(describeAtmosphereState(zoom, ramp)).toBe(
        `sky ${evaluateExpression(expression, zoom).toFixed(2)} · ramp 0.7→0.15`,
      );
    }
  });
});

// ---------------------------------------------------------------------------------------------
// The pitch term. The zoom ramp keys on zoom; the damage is driven by pitch, so a pitched overview
// is a camera neither half of the zoom ramp's reasoning describes. Measured at z2.95 over
// Antarctica against a blend-0 control, on-globe pixels only: +0.0 DN at pitch 0 and 30, +4.6 at
// 45, +30 at 50, +47.5 at 55, +52.7 at 60. Flat, then a cliff.
// ---------------------------------------------------------------------------------------------

describe("pitchedAtmosphereBase", () => {
  it("is EXACTLY the base below the knee, so every unpitched camera is bit-identical", () => {
    // Object.is, not toBeCloseTo. The default camera is the first thing every visitor sees and it
    // takes 0 DN of measured damage — this ramp must be incapable of changing it, not merely
    // unlikely to. Pitch 45 included: the ramp starts AT 45, it does not begin below it.
    for (const pitch of [0, 10, 30, 44.9, ATMOSPHERE_PITCH_RAMP_START_DEG]) {
      expect(Object.is(pitchedAtmosphereBase(pitch), BASE_ATMOSPHERE_BLEND)).toBe(true);
    }
  });

  it("reaches the pitched value at the top of the window and clamps past it", () => {
    expect(pitchedAtmosphereBase(ATMOSPHERE_PITCH_RAMP_END_DEG)).toBe(PITCHED_ATMOSPHERE_BLEND);
    expect(pitchedAtmosphereBase(85)).toBe(PITCHED_ATMOSPHERE_BLEND); // beyond maxPitch
    expect(pitchedAtmosphereBase(-10)).toBe(BASE_ATMOSPHERE_BLEND);   // nonsense pitch
  });

  it("falls monotonically across the window and never leaves the two endpoints", () => {
    let previous = Infinity;
    for (let pitch = 44; pitch <= 61; pitch += 0.5) {
      const value = pitchedAtmosphereBase(pitch);
      expect(value).toBeLessThanOrEqual(previous);
      expect(value).toBeLessThanOrEqual(BASE_ATMOSPHERE_BLEND);
      expect(value).toBeGreaterThanOrEqual(PITCHED_ATMOSPHERE_BLEND);
      previous = value;
    }
  });
});

describe("pitch enters the expression as a new base, not a second ramp", () => {
  it("leaves the unpitched expression untouched", () => {
    const ramp = defaultAtmosphereRamp();
    const flat = atmosphereBlend(ramp, 0);
    for (const pitch of [10, 30, ATMOSPHERE_PITCH_RAMP_START_DEG]) {
      expect(atmosphereBlend(ramp, pitch)).toEqual(flat);
    }
    expect((flat as unknown[])[4]).toBe(BASE_ATMOSPHERE_BLEND); // the z<=3 stop
  });

  it("starts a pitched camera lower while still landing on the floor", () => {
    const ramp = defaultAtmosphereRamp();
    const pitched = atmosphereBlend(ramp, 60) as unknown[];
    expect(pitched[4]).toBe(PITCHED_ATMOSPHERE_BLEND);
    expect(pitched[6]).toBe(DEFAULT_ATMOSPHERE_FLOOR);
    // and MapLibre must still evaluate it as a DECAY, not a rise
    expect(evaluateExpression(pitched, ATMOSPHERE_RAMP_START_ZOOM))
      .toBeGreaterThan(evaluateExpression(pitched, ATMOSPHERE_RAMP_END_ZOOM));
  });

  it("never hands the expression a base below its own floor", () => {
    // ?sky=0.5 plus a pitched camera would otherwise start at 0.25 and end at 0.50 — atmosphere
    // RISING with zoom, the opposite of the whole ramp. Silent, and only on a flag arm.
    const highFloor = { kind: "ramp" as const, floor: 0.5 };
    const pitched = atmosphereBlend(highFloor, 60) as unknown[];
    expect(pitched[4] as number).toBeGreaterThanOrEqual(pitched[6] as number);
  });

  it("leaves the control arm deaf to pitch", () => {
    // ?sky=off exists to isolate both ramps at once; acquiring one of them would make it useless.
    for (const pitch of [0, 60]) expect(atmosphereBlend({ kind: "off" }, pitch))
      .toBe(BASE_ATMOSPHERE_BLEND);
  });
});

describe("atmosphereNeedsRebuild", () => {
  it("says no across every pitch below the knee, so most cameras never call setSky", () => {
    expect(atmosphereNeedsRebuild(0, 30)).toBe(false);
    expect(atmosphereNeedsRebuild(0, ATMOSPHERE_PITCH_RAMP_START_DEG)).toBe(false);
    expect(atmosphereNeedsRebuild(20, 44)).toBe(false);
  });

  it("says yes once the pitch term actually moves the blend", () => {
    expect(atmosphereNeedsRebuild(0, 60)).toBe(true);
    expect(atmosphereNeedsRebuild(45, 50)).toBe(true);
    expect(atmosphereNeedsRebuild(60, 45)).toBe(true); // and on the way back down
  });

  it("ignores a change too small to see, because each setSky restarts a 300 ms transition", () => {
    expect(atmosphereNeedsRebuild(55, 55.1)).toBe(false);
  });
});

describe("globe.astro wires the ramp rather than re-stating it", () => {
  const globe = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");

  it("builds every sky from the module's spec — the page never states one itself", () => {
    // Was "exactly once" until the pitch term landed, and the count was never the point: the
    // guard exists so globe.astro cannot grow its own sky literal. Asserting that EVERY call goes
    // through skySpec says that directly, and survives a second legitimate call site.
    const calls = globe.match(/map\.setSky\([^)]*/g) ?? [];
    expect(calls.length).toBeGreaterThan(0);
    for (const call of calls) expect(call).toContain("skySpec(skyRamp");
  });

  it("rebuilds the sky on moveend, gated, because pitch cannot be an expression", () => {
    // MapLibre expressions read ["zoom"] and nothing else about the camera, so the pitch term has
    // to be driven. `moveend` rather than a pitch handler: the effect is a 300 ms transition, and
    // a camera mid-drag has no settled answer. Scoped to the handler's own branch, so a rebuild
    // moved somewhere it never runs fails here rather than passing on a file-wide substring.
    const handler = globe.match(/map\.on\("moveend",[\s\S]*?\n  \}\);/g)?.find((block) =>
      block.includes("setSky"));
    expect(handler, "a moveend handler must rebuild the sky").toBeTruthy();
    expect(handler).toContain("atmosphereNeedsRebuild(");
    expect(handler).toMatch(/if \(!atmosphereNeedsRebuild\([^)]*\)\) return;/);
  });

  it("keeps the sky colours out of the page, so there is one place they can drift from", () => {
    // The values that used to live inline here. If any reappears, two files own the sky.
    for (const colour of ["#8fb8d6", "#cbd8dd", "#dfe7ea"]) {
      expect(globe).not.toContain(colour);
    }
  });

  it("drives the ramp declaratively, with no per-zoom setSky handler", () => {
    // Style.setSky re-runs the sky transitions on every call at a 300 ms default duration, so a
    // zoom handler would chase the camera a third of a second behind and restart before landing.
    const zoomHandlers = globe.match(/map\.on\("zoom",/g) ?? [];
    expect(zoomHandlers).toHaveLength(1); // terrain's exaggeration ramp, which has no expression
    const [, afterZoomHandler] = globe.split('map.on("zoom",');
    expect(afterZoomHandler.slice(0, 400)).not.toContain("setSky");
  });
});
