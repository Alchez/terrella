import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  FPS_WINDOW_MS,
  SLOW_FRAME_MS,
  frameInterval,
  frameRate,
  longTaskApiSupported,
  newFrameTracker,
  onIdle,
  onRender,
  perfSummaryLines,
  type PerfSnapshot,
} from "./perfOverlay";

const BASE: PerfSnapshot = {
  bootMs: 1234.6,
  mapLoadMs: null,
  firstIdleMs: null,
  longTaskCount: 0,
  longTaskTotalMs: 0,
  longTaskMaxMs: 0,
  longTaskApiAvailable: true,
  fps: null,
  worstFrameMs: null,
  slowFrameCount: 0,
  zoom: 3,
};

/** `count` frames ending at `now`, spaced `stepMs` apart. */
const evenFrames = (count: number, stepMs: number, now: number) =>
  Array.from({ length: count }, (_, index) => now - (count - 1 - index) * stepMs);

describe("perfSummaryLines", () => {
  it("renders pending timings as em-dashes and rounds real ones", () => {
    const lines = perfSummaryLines(BASE);
    expect(lines[0]).toBe("boot 1235 ms");
    expect(lines[1]).toBe("map load — · first idle —");
  });

  it("summarizes long tasks once they arrive", () => {
    const lines = perfSummaryLines({
      ...BASE,
      mapLoadMs: 2100,
      firstIdleMs: 3400.4,
      longTaskCount: 14,
      longTaskTotalMs: 2210.7,
      longTaskMaxMs: 480.2,
    });
    expect(lines[1]).toBe("map load 2100 ms · first idle 3400 ms");
    expect(lines[2]).toBe("long tasks 14 · 2211 ms total · 480 ms max");
  });

  it("stays four lines, so the panel fits a phone corner", () => {
    expect(perfSummaryLines(BASE)).toHaveLength(4);
  });

  it("says so plainly when the long-task API is missing", () => {
    const lines = perfSummaryLines({ ...BASE, longTaskApiAvailable: false });
    expect(lines[2]).toBe("long tasks n/a — no Long Tasks API in this browser");
    expect(lines).toHaveLength(4);
  });

  it("never renders an unmeasured browser as a measured zero", () => {
    // The whole point of the line: a Firefox screenshot once read `long tasks 0 · 0 ms total ·
    // 0 ms max` from an observer that never registered, and that zero was taken as evidence the
    // main thread was clean. The unavailable line must share no prefix with a real reading.
    const unavailable = perfSummaryLines({ ...BASE, longTaskApiAvailable: false })[2];
    const measuredZero = perfSummaryLines({ ...BASE, longTaskApiAvailable: true })[2];
    expect(measuredZero).toBe("long tasks 0 · 0 ms total · 0 ms max");
    expect(unavailable).not.toBe(measuredZero);
    expect(unavailable).toContain("n/a");
    expect(unavailable).not.toMatch(/\b0\b/);
  });
});

describe("longTaskApiSupported", () => {
  const withEntryTypes = (types: string[]) =>
    ({ supportedEntryTypes: types }) as unknown as typeof PerformanceObserver;

  it("accepts a browser that lists longtask", () => {
    expect(longTaskApiSupported(withEntryTypes(["mark", "measure", "longtask"]))).toBe(true);
  });

  it("rejects Firefox, which lists every OTHER entry type and silently ignores longtask", () => {
    // The regression this whole change exists for: `observe({type: "longtask"})` does NOT throw
    // there, so a try/catch reports the API as available and the panel prints a fake zero.
    expect(longTaskApiSupported(withEntryTypes(["mark", "measure", "navigation", "resource"]))).toBe(
      false,
    );
  });

  it("rejects a browser with no PerformanceObserver at all", () => {
    expect(longTaskApiSupported(undefined)).toBe(false);
  });

  it("rejects an implementation whose supportedEntryTypes is missing", () => {
    expect(longTaskApiSupported({} as unknown as typeof PerformanceObserver)).toBe(false);
  });

  it("is what mountPerfOverlay actually gates the observer on", () => {
    // A correct helper nobody calls is the same bug in a new place: the original code already
    // had a longTaskApiAvailable flag and a formatter that handled it, and still printed a fake
    // zero, because the only thing that could clear the flag was a throw that never came.
    const source = readFileSync(new URL("./perfOverlay.ts", import.meta.url), "utf8");
    expect(source).toMatch(/if\s*\(!longTaskApiSupported\(\)\)/);
    expect(source).toContain('observer.observe({ type: "longtask", buffered: true })');
  });

  it("reports idle rather than zero when nothing has been rendered", () => {
    // Zero fps would read as "the map is failing to draw". It renders on demand, so no frames
    // means nothing needed drawing — a different fact, and the one worth showing.
    expect(perfSummaryLines({ ...BASE, zoom: 6.5 }).at(-1)).toBe(
      "fps — (idle) · worst — · slow 0 · z6.50",
    );
  });

  it("keeps the worst frame on screen after the map goes idle", () => {
    // The whole point: the hitch happens during a gesture, the screenshot is taken after it.
    const line = perfSummaryLines({
      ...BASE, fps: null, worstFrameMs: 132.4, slowFrameCount: 9, zoom: 7.238,
    }).at(-1);
    expect(line).toBe("fps — (idle) · worst 132 ms · slow 9 · z7.24");
  });

  it("puts the worst frame beside the rate, since the rate alone hides a stall", () => {
    const line = perfSummaryLines({
      ...BASE, fps: 58, worstFrameMs: 47.4, slowFrameCount: 2, zoom: 7.238,
    }).at(-1);
    expect(line).toBe("fps 58 · worst 47 ms · slow 2 · z7.24");
  });

  it("makes a one-off interruption distinguishable from real jank", () => {
    // The whole reason the count sits beside the max. A screenshot pauses rAF and lands as a
    // 400 ms frame; without the count that is indistinguishable from a map that stutters.
    const artifact = perfSummaryLines({
      ...BASE, fps: null, worstFrameMs: 428, slowFrameCount: 1, zoom: 6.45,
    }).at(-1);
    const jank = perfSummaryLines({
      ...BASE, fps: null, worstFrameMs: 90, slowFrameCount: 24, zoom: 6.45,
    }).at(-1);
    expect(artifact).toBe("fps — (idle) · worst 428 ms · slow 1 · z6.45");
    expect(jank).toBe("fps — (idle) · worst 90 ms · slow 24 · z6.45");
  });
});

describe("frameInterval", () => {
  it("measures the gap between consecutive renders", () => {
    expect(frameInterval(1000, 1016, false)).toBe(16);
  });

  it("has no interval on the very first render", () => {
    expect(frameInterval(null, 1000, false)).toBeNull();
  });

  it("DISCARDS a gap that spans an idle — that is the load-bearing rule", () => {
    // Without this, every pause to look at the map records a multi-second "worst frame" AND a
    // phantom slow frame, and both numbers become noise within seconds of loading the page.
    expect(frameInterval(1000, 9000, true)).toBeNull();
  });

  it("ignores a non-advancing clock rather than reporting a zero-length frame", () => {
    expect(frameInterval(1000, 1000, false)).toBeNull();
    expect(frameInterval(1000, 990, false)).toBeNull();
  });
});

describe("the frame tracker across a page's life", () => {
  /** Replay a script of events through the tracker and return the peak after each one. */
  const replay = (script: ReadonlyArray<number | "idle">) => {
    let tracker = newFrameTracker();
    for (const event of script) {
      tracker = event === "idle" ? onIdle(tracker) : onRender(tracker, event);
    }
    return { peakMs: tracker.peakMs, slowCount: tracker.slowCount };
  };

  const step = (script: ReadonlyArray<number | "idle">) => {
    let tracker = newFrameTracker();
    return script.map((event) => {
      tracker = event === "idle" ? onIdle(tracker) : onRender(tracker, event);
      return tracker.peakMs;
    });
  };

  it("clears the load-time peak at the first idle, and only the first", () => {
    // Frames at 0/200/216 — a 200 ms load frame — then the map settles. The 200 must go, or it
    // sets a floor no later gesture can beat and the readout is stuck for the whole session.
    const peaks = step([0, 200, 216, "idle", 1000, 1016, "idle", 2000, 2140]);
    expect(peaks[1]).toBe(200); // load frame recorded
    expect(peaks[3]).toBeNull(); // first idle wipes it
    expect(peaks[5]).toBe(16); // post-idle frames start a fresh peak
    expect(peaks[6]).toBe(16); // a LATER idle must not wipe anything
    expect(peaks[8]).toBe(140); // and a real gesture hitch survives
  });

  it("clears the slow count at the first idle too, so both readings share a span", () => {
    // Two slow load frames, then a settle, then one slow gesture frame. Reporting 3 would
    // attribute load cost to the gesture and make the arms incomparable.
    expect(replay([0, 200, 400, "idle", 1000, 1016, 1200])).toEqual({
      peakMs: 184,
      slowCount: 1,
    });
  });

  it("counts every slow frame, not just the worst one", () => {
    const frames = [1000, 1100, 1200, 1300, 1316, 1332];
    expect(replay(frames)).toEqual({ peakMs: 100, slowCount: 3 });
  });

  it("uses a strict threshold, so a frame exactly at the bound is not slow", () => {
    expect(replay([1000, 1000 + SLOW_FRAME_MS]).slowCount).toBe(0);
    expect(replay([1000, 1000 + SLOW_FRAME_MS + 1]).slowCount).toBe(1);
  });

  it("does not charge the pause between two gestures as a frame", () => {
    // Gesture, idle for 8 s while the user looks at the map, gesture again. That 8 s gap must
    // raise neither the peak nor the count — it is the exact artifact the pair exists to reject.
    expect(replay([1000, 1016, "idle", 9000, 9016])).toEqual({ peakMs: 16, slowCount: 0 });
  });

  it("survives an idle that arrives before any render", () => {
    expect(step(["idle", 1000, 1016])).toEqual([null, null, 16]);
  });
});

describe("frameRate", () => {
  it("computes the rate from gaps between frames, not from the frame count", () => {
    // 61 stamps 16.67 ms apart span exactly 1000 ms: 60 intervals, so 60 fps. Counting stamps
    // instead of intervals would report 61 and be wrong by a frame at every rate.
    expect(frameRate(evenFrames(61, 1000 / 60, 5000), 5000)).toBe(60);
    expect(frameRate(evenFrames(31, 1000 / 30, 5000), 5000)).toBe(30);
  });

  it("reports idle for an empty or single-frame window", () => {
    expect(frameRate([], 5000)).toBeNull();
    expect(frameRate([4999], 5000)).toBeNull();
  });

  it("ignores frames older than the window, so the rate follows the present", () => {
    expect(frameRate([1000, 1016, 1032], 5000)).toBeNull();
  });

  it("uses a one-second window by default", () => {
    expect(FPS_WINDOW_MS).toBe(1000);
    // 990 ms and 10 ms old: both inside the default window, one interval between them.
    expect(frameRate([4010, 4990], 5000)).toBe(1);
    // The same pair against a 100 ms window keeps only the newer stamp, so there is no interval.
    expect(frameRate([4010, 4990], 5000, 100)).toBeNull();
    // And a stamp 1010 ms old is outside the default window, by one interval's worth of margin.
    expect(frameRate([3990, 4990], 5000)).toBeNull();
  });
});
