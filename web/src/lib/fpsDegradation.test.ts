import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  CATASTROPHIC_FRAME_MS,
  CATASTROPHIC_RUN_LENGTH,
  DEGRADED_PIXEL_RATIO,
  MAXIMUM_SAMPLE_COUNT,
  MINIMUM_SAMPLE_COUNT,
  SLOW_MEDIAN_MILLISECONDS,
  isDegradationWarranted,
  isSustainedSlow,
  newFrameWindow,
  nextDegradationAction,
  onFrameRendered,
} from "./fpsDegradation";

/** Feed a window a run of renders `gapMs` apart, starting from a clean stamp. */
const renderEvery = (gapMs: number, count: number, from = newFrameWindow()) => {
  let frames = from;
  let stampMs = 1000;
  // One extra render, because the first only sets the stamp — `count` INTERVALS is what a caller
  // means, and off-by-one here would silently weaken every threshold below.
  for (let index = 0; index <= count; index += 1) {
    frames = onFrameRendered(frames, stampMs);
    stampMs += gapMs;
  }
  return frames;
};

/** A decision from the shipping defaults, with the terrain rung fixed per describe.
 *
 *  A factory rather than two near-identical helpers: the two blocks below differ only in whether
 *  terrain is on, and the four fields they share are the shipping config — a second copy of them
 *  could drift and quietly change what the other block is testing. */
const degradationWith =
  (terrainEnabled: boolean) =>
  (overrides: Partial<Parameters<typeof nextDegradationAction>[0]>) =>
    nextDegradationAction({
      spinning: false,
      pixelRatioLowered: false,
      devicePixelRatio: 2,
      terrainEnabled,
      ...overrides,
    });

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

describe("the frame window, which decides what gets judged at all", () => {
  it("records nothing from the first render — there is no interval yet", () => {
    const frames = onFrameRendered(newFrameWindow(), 1000);
    expect(frames.intervalsMs).toEqual([]);
    expect(frames.previousStampMs).toBe(1000);
  });

  it("FORGETS THE STAMP ON RESET, so a quiet spell is not booked as one enormous frame", () => {
    // The load-bearing test of this block. `idle` resets the window, and the map may then sit
    // untouched for minutes; if the stamp survived, the next render would record the whole silence
    // as a single frame and trip every threshold at once. A sleeping map must not read as a
    // stalled one — which is the same distinction the whole gate change turns on.
    const busy = renderEvery(16, 5);
    expect(busy.previousStampMs).not.toBeNull();
    const afterIdle = newFrameWindow();
    const firstRenderMuchLater = onFrameRendered(afterIdle, 9_999_999);
    expect(firstRenderMuchLater.intervalsMs).toEqual([]);
    expect(isDegradationWarranted(firstRenderMuchLater)).toBe(false);
  });

  it("bounds the window, so an hour-long session is judged on its recent past", () => {
    const frames = renderEvery(16, MAXIMUM_SAMPLE_COUNT + 40);
    expect(frames.intervalsMs).toHaveLength(MAXIMUM_SAMPLE_COUNT);
  });

  it("counts a stall run and breaks it on ONE fast frame", () => {
    const stalling = renderEvery(CATASTROPHIC_FRAME_MS + 1, CATASTROPHIC_RUN_LENGTH - 1);
    expect(stalling.slowRun).toBe(CATASTROPHIC_RUN_LENGTH - 1);
    const recovered = onFrameRendered(stalling, stalling.previousStampMs! + 16);
    expect(recovered.slowRun, "one good frame ends the run").toBe(0);
  });

  it("does not count a frame exactly on the catastrophic threshold", () => {
    const frames = renderEvery(CATASTROPHIC_FRAME_MS, CATASTROPHIC_RUN_LENGTH + 2);
    expect(frames.slowRun).toBe(0);
    expect(isDegradationWarranted(frames)).toBe(false);
  });
});

describe("the two triggers, and that neither loosens the other", () => {
  it("fires on a run of stalls long before the sustained rule could", () => {
    // THE WHOLE POINT. At cliff frame rates the sustained rule needs MINIMUM_SAMPLE_COUNT frames
    // that are seconds apart — over a minute — so it is not the rule that can rescue a page that
    // has already stopped answering. Three stalled frames is ~4 s of real time.
    const frames = renderEvery(1500, CATASTROPHIC_RUN_LENGTH);
    expect(frames.intervalsMs.length).toBeLessThan(MINIMUM_SAMPLE_COUNT);
    expect(isSustainedSlow(frames.intervalsMs), "the sustained rule cannot have fired").toBe(false);
    expect(isDegradationWarranted(frames)).toBe(true);
  });

  it("still fires on a merely mediocre device, by the rule that always shipped", () => {
    const frames = renderEvery(SLOW_MEDIAN_MILLISECONDS + 6, MINIMUM_SAMPLE_COUNT);
    expect(frames.slowRun, "no single frame is anywhere near catastrophic").toBe(0);
    expect(isDegradationWarranted(frames)).toBe(true);
  });

  it("IS NOT MORE TRIGGER-HAPPY: a healthy map never warrants a rung, however long it runs", () => {
    // The requirement in one test — the ladder must only fire when necessary. A 60 fps session of
    // any length, and a 30 fps one that stays the right side of the median threshold, must both
    // leave the ladder alone.
    expect(isDegradationWarranted(renderEvery(16, 500))).toBe(false);
    expect(isDegradationWarranted(renderEvery(SLOW_MEDIAN_MILLISECONDS - 1, 500))).toBe(false);
  });

  it("ignores an isolated stall, however brutal — the shape has to be a RUN", () => {
    // A 1.1 s cap texture upload on Firefox, a GC pause, an interrupted frame: each is ONE
    // interval. Requiring consecutive stalls is what makes those unable to degrade the globe,
    // and it is why this trigger can afford to sit 15x above the sustained threshold.
    let frames = renderEvery(16, 30);
    frames = onFrameRendered(frames, frames.previousStampMs! + 1800);
    frames = onFrameRendered(frames, frames.previousStampMs! + 16);
    expect(frames.slowRun).toBe(0);
    expect(isDegradationWarranted(frames)).toBe(false);
  });
});

describe("nextDegradationAction", () => {
  // Every existing case now has to say whether terrain is on. Default it OFF here, because that
  // is the shipping state today (terrain is still behind ?terrain=N) and it keeps these five
  // tests about the levers they were written for.
  const state = degradationWith(false);

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
  const state = degradationWith(true);

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
  const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");

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

  it("DRIVES THE WATCHDOG FROM `render`, AND NEVER FROM A MOTION GATE", () => {
    // The defect this whole change exists for, pinned where it lived. `spinning || map.isMoving()`
    // asks whether the CAMERA is animating; the question is whether the MAIN THREAD is starved,
    // and a page parked at the covering-tiles cliff draws continuously without ever moving. The
    // shipped ladder therefore sat on `disable-terrain` for 55 s collecting zero samples.
    //
    // Bounded and the bound asserted, per this file's other scans: a lazy match that overruns its
    // subject still contains the right substring and still passes.
    const watchdog = globe.match(/function judgeFrame\(\)[\s\S]{0,6000}?\n {2}\}/)?.[0];
    expect(watchdog, "the watchdog's handler must exist under this name").toBeTruthy();
    expect(watchdog!.length, "matched a runaway span, not the handler").toBeLessThan(6000);
    // Reached the handler's own end rather than being truncated by the bound above — a short match
    // would satisfy every `not.toMatch` below by simply never getting as far as the offending line.
    expect(watchdog, "the match stopped before the handler ended").toContain(
      "ladderExhausted = true",
    );
    expect(watchdog).toContain("onFrameRendered(frames, performance.now())");
    expect(
      watchdog,
      "the motion gate is the defect — it must not come back in any form",
    ).not.toMatch(/isMoving\(\)/);
    // And the handler has to actually be subscribed, or every assertion above describes dead code.
    expect(globe).toContain('map.on("render", judgeFrame)');
  });

  it("resets the window on the map's own `idle`, which is the only honest reset", () => {
    // `idle` means MapLibre has drawn everything it wanted. Measured to fire once at 396 ms on a
    // healthy overview and NOT ONCE in 14.8 s at the cliff, so it clears exactly where there is
    // nothing left to judge. A timer would clear the cliff's window out from under it.
    //
    // The handler is NAMED, and that is what makes this checkable: the page has several `idle`
    // subscriptions and the first draft of this test matched the GL-state sampler instead. A
    // regex cannot decide which of several identical-looking regions it is standing in, so the
    // structure was changed rather than the pattern.
    const idleHandler = globe.match(/function forgetJudgedFrames\(\)[\s\S]{0,200}?\n {2}\}/)?.[0];
    expect(idleHandler, "the idle reset must exist under this name").toBeTruthy();
    expect(idleHandler).toContain("newFrameWindow()");
    expect(globe).toContain('map.on("idle", forgetJudgedFrames)');
  });

  it("keeps the dead-globe notice above the ?perf panel", () => {
    // Reported from a phone: the notice had unhidden and the expanded diagnostic panel covered it.
    const notice = globe.match(/\.globe-lost \{[\s\S]*?\n  \}/)?.[0];
    expect(notice, "the notice's rule must exist").toBeTruthy();
    const noticeZ = Number(notice!.match(/z-index: (\d+)/)?.[1]);
    const panelZ = Number(
      readFileSync(new URL("./perf/perfOverlay.ts", import.meta.url), "utf8").match(
        /"z-index:(\d+)"/,
      )?.[1],
    );
    expect(Number.isFinite(noticeZ) && Number.isFinite(panelZ)).toBe(true);
    expect(noticeZ).toBeGreaterThan(panelZ);
  });
});
