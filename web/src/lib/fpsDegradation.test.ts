import { readFileSync } from "node:fs";
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
  // Every existing case now has to say whether terrain is on. Default it OFF here, because that
  // is the shipping state today (terrain is still behind ?terrain=N) and it keeps these five
  // tests about the levers they were written for.
  const state = (overrides: Partial<Parameters<typeof nextDegradationAction>[0]>) =>
    nextDegradationAction({
      spinning: false,
      pixelRatioLowered: false,
      devicePixelRatio: 2,
      terrainEnabled: false,
      ...overrides,
    });

  it("retires the spin first — the cheapest lever", () => {
    expect(state({ spinning: true })).toBe("retire-spin");
  });

  it("drops the pixel ratio once the spin is already retired on a hi-DPI screen", () => {
    expect(state({})).toBe("lower-pixel-ratio");
  });

  it("has nothing to drop on a 1x screen with no terrain", () => {
    expect(state({ devicePixelRatio: DEGRADED_PIXEL_RATIO })).toBe(null);
  });

  it("is exhausted once both levers are pulled", () => {
    expect(state({ pixelRatioLowered: true })).toBe(null);
  });

  it("retires a user-restarted spin even after the pixel ratio was lowered", () => {
    expect(state({ spinning: true, pixelRatioLowered: true })).toBe("retire-spin");
  });
});

describe("the terrain rung, and why it is last", () => {
  const state = (overrides: Partial<Parameters<typeof nextDegradationAction>[0]>) =>
    nextDegradationAction({
      spinning: false,
      pixelRatioLowered: false,
      devicePixelRatio: 2,
      terrainEnabled: true,
      ...overrides,
    });

  it("LOWERS THE PIXEL RATIO BEFORE DISABLING TERRAIN, which is not the intuitive order", () => {
    // The load-bearing test in this file. Terrain sounds like the heaviest lever, so the obvious
    // ladder puts it second and pixel ratio last. That is backwards: terrain swaps a DPR-scaled
    // cost for a DPR-INVARIANT one (rttSize = tileManager.tileSize * qualityFactor — no DPR term).
    // Measured live at the shipping config: canvas pixels went 1,451,125 -> 13,060,125 across
    // DPR 1 -> 3 (exactly 9x) while total RTT pixels stayed at 4,194,304 in both. So terrain's
    // relative cost FALLS as DPR rises, and pulling this rung first on a hi-DPI screen can make
    // frames slower. Lowering the pixel ratio is what earns the terrain rung its value.
    expect(state({})).toBe("lower-pixel-ratio");
    expect(state({ pixelRatioLowered: true })).toBe("disable-terrain");
  });

  it("goes straight to terrain on a 1x screen — where the rung is worth the most", () => {
    // No pixel-ratio headroom to give back, and DPR 1 is exactly the regime where the RTT path is
    // overhead rather than a saving.
    expect(state({ devicePixelRatio: DEGRADED_PIXEL_RATIO })).toBe("disable-terrain");
  });

  it("still retires the spin before anything else", () => {
    expect(state({ spinning: true, devicePixelRatio: DEGRADED_PIXEL_RATIO })).toBe("retire-spin");
  });

  it("is exhausted once terrain is off too", () => {
    expect(state({ pixelRatioLowered: true, terrainEnabled: false })).toBe(null);
  });

  it("never offers the rung when terrain was never on", () => {
    // The ordinary case today: terrain is behind ?terrain=N, so the ladder must end where it
    // always did rather than emit an action the caller would apply to nothing.
    expect(state({ pixelRatioLowered: true, terrainEnabled: false })).toBe(null);
    expect(state({ devicePixelRatio: DEGRADED_PIXEL_RATIO, terrainEnabled: false })).toBe(null);
  });

  it("walks the whole ladder in order, spin -> pixel ratio -> terrain -> done", () => {
    // Pins the SEQUENCE, not just each rung: a reordering that kept every individual assertion
    // above true would still fail here.
    const walked: (string | null)[] = [];
    let spinning = true;
    let pixelRatioLowered = false;
    let terrainEnabled = true;
    for (let step = 0; step < 4; step += 1) {
      const action = nextDegradationAction({
        spinning,
        pixelRatioLowered,
        devicePixelRatio: 2,
        terrainEnabled,
      });
      walked.push(action);
      if (action === "retire-spin") spinning = false;
      if (action === "lower-pixel-ratio") pixelRatioLowered = true;
      if (action === "disable-terrain") terrainEnabled = false;
    }
    expect(walked).toEqual(["retire-spin", "lower-pixel-ratio", "disable-terrain", null]);
  });
});

describe("the page reads the pixel ratio from the right place", () => {
  const globe = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");

  it("feeds the ladder the MAP's ratio, never the display's", () => {
    // The ladder LOWERS the map's ratio itself, so after its middle rung the two disagree.
    // Reading the display's would report headroom already spent and re-pull a no-op rung
    // instead of reaching terrain.
    const ladderInputs = [...globe.matchAll(/nextDegradationAction\(\{[\s\S]{0,240}?\}\)/g)].map(
      (match) => match[0],
    );
    expect(ladderInputs.length, "the ladder must be called").toBeGreaterThan(0);
    for (const call of ladderInputs) {
      expect(call).toContain("devicePixelRatio: map.getPixelRatio()");
      expect(call).not.toContain("window.devicePixelRatio");
    }
  });

  it("reports the MAP's ratio in the perf snapshot too, not the display's", () => {
    // Found by a sabotage that missed its target: the 10-space needle aimed at the ladder is a
    // SUBSTRING of this 14-space line, so it corrupted the report's origin instead — and nothing
    // failed. A snapshot whose `devicePixelRatio` silently means the display would misattribute
    // every phone reading taken after the ladder lowered the ratio, which is the one moment the
    // two disagree and the one moment the number matters.
    const origin = globe.match(/origin: \{[\s\S]{0,1600}?\n {12}\},/)?.[0];
    expect(origin, "the report's origin block must exist").toBeTruthy();
    // Bounded AND the bound asserted, per the lesson that produced this file's other guards: a
    // lazy match that overruns its subject still contains the right substring and still passes.
    expect(origin!.length, "matched a runaway span, not the origin block").toBeLessThan(1600);
    expect(origin).toContain("devicePixelRatio: map.getPixelRatio()");
    expect(origin).not.toContain("window.devicePixelRatio");
  });

  it("keeps the dead-globe notice above the ?perf panel", () => {
    // Reported from a phone: the notice had unhidden and the expanded diagnostic panel covered it.
    const notice = globe.match(/\.globe-lost \{[\s\S]*?\n  \}/)?.[0];
    expect(notice, "the notice's rule must exist").toBeTruthy();
    const noticeZ = Number(notice!.match(/z-index: (\d+)/)?.[1]);
    const panelZ = Number(
      readFileSync(new URL("./perfOverlay.ts", import.meta.url), "utf8").match(
        /"z-index:(\d+)"/,
      )?.[1],
    );
    expect(Number.isFinite(noticeZ) && Number.isFinite(panelZ)).toBe(true);
    expect(noticeZ).toBeGreaterThan(panelZ);
  });
});
