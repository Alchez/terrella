import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  FPS_WINDOW_MS,
  NARROW_VIEWPORT_PX,
  PERF_EXPORT_PATH,
  SLOW_FRAME_MS,
  exportPerfReport,
  frameInterval,
  frameRate,
  longTaskApiSupported,
  newFrameTracker,
  onIdle,
  onRender,
  perfCollapsedLines,
  retainFrameRate,
  perfSummaryLines,
  startsCollapsed,
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
  lastActiveFps: null,
  lastActiveFpsAgeMs: null,
  worstFrameMs: null,
  slowFrameCount: 0,
  zoom: 3,
};

/** `count` frames ending at `now`, spaced `stepMs` apart. */
const evenFrames = (count: number, stepMs: number, now: number) =>
  Array.from({ length: count }, (_, index) => now - (count - 1 - index) * stepMs);

/** Just the rendered text of each summary line. The lines carry a subsystem tag now, and every
 *  assertion below it that predates the grouping is about wording, not about placement — those
 *  are asserted once, on the sequence, rather than repeated on every case. */
const summaryTexts = (snapshot: PerfSnapshot) =>
  perfSummaryLines(snapshot).map((line) => line.text);

describe("perfSummaryLines", () => {
  it("renders pending timings as em-dashes and rounds real ones", () => {
    const lines = summaryTexts(BASE);
    expect(lines[0]).toBe("boot 1235 ms");
    expect(lines[1]).toBe("map load — · first idle —");
  });

  it("summarizes long tasks once they arrive", () => {
    const lines = summaryTexts({
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

  it("stays four lines, and files the load timeline apart from the frame outcome", () => {
    // Renegotiated, not dropped. The original rationale ("so the panel fits a phone corner") had
    // already stopped holding — the panel wraps, scrolls, starts collapsed on a narrow screen, and
    // the page appends its own lines below these. What the bound is worth keeping FOR is that these
    // four are the core reading and a fifth belongs in `extraLines`, where it can be attributed.
    //
    // The sequence is the half that matters now. `boot` / `map load` / `first idle` are main-thread
    // work and sit directly above the `long tasks` line that explains them; the frame line is an
    // outcome with no owner, so it is FEEL. A tag drifting between the two would put a number under
    // a heading that claims an attribution this panel cannot make — the exact false precision the
    // grouping exists to avoid.
    expect(perfSummaryLines(BASE).map((line) => line.group)).toEqual([
      "cpu",
      "cpu",
      "cpu",
      "feel",
    ]);
  });

  it("says so plainly when the long-task API is missing", () => {
    const lines = summaryTexts({ ...BASE, longTaskApiAvailable: false });
    expect(lines[2]).toBe("long tasks n/a — no Long Tasks API in this browser");
    expect(lines).toHaveLength(4);
  });

  it("never renders an unmeasured browser as a measured zero", () => {
    // The whole point of the line: a Firefox screenshot once read `long tasks 0 · 0 ms total ·
    // 0 ms max` from an observer that never registered, and that zero was taken as evidence the
    // main thread was clean. The unavailable line must share no prefix with a real reading.
    const unavailable = summaryTexts({ ...BASE, longTaskApiAvailable: false })[2];
    const measuredZero = summaryTexts({ ...BASE, longTaskApiAvailable: true })[2];
    expect(measuredZero).toBe("long tasks 0 · 0 ms total · 0 ms max");
    expect(unavailable).not.toBe(measuredZero);
    expect(unavailable).toContain("n/a");
    expect(unavailable).not.toMatch(/\b0\b/);
  });
});

describe("perfCollapsedLines — what the panel shows before anyone taps it", () => {
  it("stays two lines, which is the bound that actually protects a phone screen", () => {
    expect(perfCollapsedLines(BASE)).toHaveLength(2);
    expect(perfCollapsedLines({ ...BASE, fps: 58, longTaskCount: 200 })).toHaveLength(2);
  });

  it("leads with jank and blocked time — the pair every session starts by asking about", () => {
    const lines = perfCollapsedLines({
      ...BASE,
      fps: 58,
      worstFrameMs: 90,
      slowFrameCount: 24,
      longTaskCount: 200,
      longTaskTotalMs: 12_645,
    });
    expect(lines[0]).toBe("fps 58 · worst 90 ms · slow 24");
    expect(lines[1]).toBe("blocked 12645 ms in 200 · z3.00");
  });

  it("carries the missing-API honesty into the collapsed view too", () => {
    // A collapsed `blocked 0 ms in 0` in Firefox would recreate the exact confusion the expanded
    // line was rewritten to prevent — a zero from an observer that never registered.
    const lines = perfCollapsedLines({ ...BASE, longTaskApiAvailable: false });
    expect(lines[1]).toContain("blocked n/a");
    expect(lines[1]).not.toMatch(/\b0\b/);
  });
});

describe("startsCollapsed", () => {
  it("collapses on a phone and stays open on a desktop", () => {
    expect(startsCollapsed(412)).toBe(true); // the OnePlus this was built for
    expect(startsCollapsed(NARROW_VIEWPORT_PX - 1)).toBe(true);
    expect(startsCollapsed(NARROW_VIEWPORT_PX)).toBe(false);
    expect(startsCollapsed(2560)).toBe(false);
  });
});

describe("exportPerfReport", () => {
  const ok = () => Promise.resolve({ ok: true } as Response);
  const notFound = () => Promise.resolve({ ok: false } as Response);

  it("posts the report as pretty JSON to the dev endpoint", async () => {
    let seenPath: string | undefined;
    let seenBody: string | undefined;
    const fetchFn = ((path: string, init: RequestInit) => {
      seenPath = path;
      seenBody = init.body as string;
      return ok();
    }) as unknown as typeof fetch;
    expect(await exportPerfReport({ report: { a: 1 }, fetchFn })).toBe("saved");
    expect(seenPath).toBe(PERF_EXPORT_PATH);
    // Pretty-printed on purpose: the file is read by a human in an editor, not parsed by a tool.
    expect(seenBody).toBe('{\n  "a": 1\n}');
  });

  it("falls back to the clipboard when there is no endpoint — the production case", async () => {
    // A static build has no `/__perf`, and that is ordinary, not a failure to report.
    let copied: string | undefined;
    const outcome = await exportPerfReport({
      report: { a: 1 },
      fetchFn: notFound as unknown as typeof fetch,
      writeClipboard: async (text) => {
        copied = text;
      },
    });
    expect(outcome).toBe("copied");
    expect(copied).toContain('"a": 1');
  });

  it("falls back when the POST throws, not only when it returns a bad status", async () => {
    const outcome = await exportPerfReport({
      report: {},
      fetchFn: (() => Promise.reject(new Error("network"))) as unknown as typeof fetch,
      writeClipboard: async () => {},
    });
    expect(outcome).toBe("copied");
  });

  it("reports FAILED rather than a silent success when neither path exists", async () => {
    // `navigator.clipboard` is simply absent over plain http on a LAN address, which is exactly
    // where the phone runs. A button that quietly did nothing there would be worse than no button.
    expect(await exportPerfReport({ report: {}, fetchFn: notFound as unknown as typeof fetch })).toBe(
      "failed",
    );
    expect(await exportPerfReport({ report: {} })).toBe("failed");
  });

  it("reports FAILED when the clipboard write itself is refused", async () => {
    const outcome = await exportPerfReport({
      report: {},
      fetchFn: notFound as unknown as typeof fetch,
      writeClipboard: () => Promise.reject(new Error("denied")),
    });
    expect(outcome).toBe("failed");
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
    expect(summaryTexts({ ...BASE, zoom: 6.5 }).at(-1)).toBe(
      "fps — (idle) · worst — · slow 0 · z6.50",
    );
  });

  it("keeps the worst frame on screen after the map goes idle", () => {
    // The whole point: the hitch happens during a gesture, the screenshot is taken after it.
    const line = summaryTexts({
      ...BASE, fps: null, worstFrameMs: 132.4, slowFrameCount: 9, zoom: 7.238,
    }).at(-1);
    expect(line).toBe("fps — (idle) · worst 132 ms · slow 9 · z7.24");
  });

  it("carries the last active rate across an idle map, and dates it", () => {
    // The transition itself, which no test could reach while it lived inside the 300 ms tick.
    const fresh = { fps: null, measuredAtMs: null };
    const moving = retainFrameRate(fresh, 39, 1000);
    expect(moving).toEqual({ fps: 39, measuredAtMs: 1000 });

    // Idle: the reading survives AND keeps its original timestamp, which is what makes the age grow.
    const settled = retainFrameRate(moving, null, 5200);
    expect(settled).toEqual({ fps: 39, measuredAtMs: 1000 });

    // Drawing again replaces both, so a stale rate can never outlive a newer one.
    expect(retainFrameRate(settled, 55, 6000)).toEqual({ fps: 55, measuredAtMs: 6000 });
  });

  it("has nothing to retain until the map has drawn", () => {
    // Zero would claim a measured rate of zero; null is "never measured". Different facts.
    expect(retainFrameRate({ fps: null, measuredAtMs: null }, null, 400)).toEqual({
      fps: null,
      measuredAtMs: null,
    });
  });

  it("reports the rate an idle map last drew at, because settling is what erases it", () => {
    // The defect this closes: a reader is told to let the map settle so the GL sample is current,
    // and settling is exactly what nulls `fps`. Measured on production — of three phone runs, the
    // only one carrying an fps was the one exported mid-pan, whose GL sample was 25.7 s stale.
    const line = summaryTexts({
      ...BASE,
      fps: null,
      lastActiveFps: 39,
      lastActiveFpsAgeMs: 4200,
      worstFrameMs: 132.4,
      slowFrameCount: 9,
      zoom: 7.238,
    });
    // TWO rows now, and measured rather than styled: combined, this read 61 characters against the
    // 53 the panel's font allows on a 412 px phone, so it wrapped — at the same height a second row
    // costs, while splitting a single fact across the fold.
    expect(line.at(-2)).toBe("fps — (idle) · worst 132 ms · slow 9 · z7.24");
    expect(line.at(-1)).toBe("last drew 39 fps, 4s ago");
    for (const row of line) expect(row.length).toBeLessThanOrEqual(53);
  });

  it("still says idle, and still dates the retained rate", () => {
    // Two failure modes in one assertion. Dropping "idle" would present a retained rate as live —
    // the exact class of lie `glSampleAgeMs` exists to prevent on the other half of the report.
    const rows = summaryTexts({
      ...BASE, fps: null, lastActiveFps: 60, lastActiveFpsAgeMs: 300,
    });
    // Both halves still have to be present, just on their own rows: "idle" on the reading itself,
    // so a retained rate can never be read as live, and the age beside the retained number.
    expect(rows.join("\n")).toContain("(idle)");
    expect(rows.at(-1)).toMatch(/last drew 60 fps, \d+s ago/);
  });

  it("does not show a retained rate while a live one exists", () => {
    // Both present is the ordinary case during a gesture: the live number wins outright, because
    // two rates on one line invite the reader to compare them as if they measured different things.
    const line = summaryTexts({
      ...BASE, fps: 52, lastActiveFps: 39, lastActiveFpsAgeMs: 0, zoom: 4,
    }).at(-1);
    expect(line).toBe("fps 52 · worst — · slow 0 · z4.00");
    expect(line).not.toContain("was 39");
  });

  it("falls back to a bare idle when there has never been a rate to retain", () => {
    // A first load that never moved. `was —` would imply a reading was taken and lost.
    expect(summaryTexts({ ...BASE, lastActiveFps: null, lastActiveFpsAgeMs: null }).at(-1))
      .toContain("fps — (idle) ·");
  });

  it("keeps the retained rate out of the collapsed view, which has a two-line budget", () => {
    const collapsed = perfCollapsedLines({
      ...BASE, fps: null, lastActiveFps: 39, lastActiveFpsAgeMs: 4200,
    });
    expect(collapsed).toHaveLength(2);
    expect(collapsed.join("\n")).not.toContain("was 39");
  });

  it("puts the worst frame beside the rate, since the rate alone hides a stall", () => {
    const line = summaryTexts({
      ...BASE, fps: 58, worstFrameMs: 47.4, slowFrameCount: 2, zoom: 7.238,
    }).at(-1);
    expect(line).toBe("fps 58 · worst 47 ms · slow 2 · z7.24");
  });

  it("makes a one-off interruption distinguishable from real jank", () => {
    // The whole reason the count sits beside the max. A screenshot pauses rAF and lands as a
    // 400 ms frame; without the count that is indistinguishable from a map that stutters.
    const artifact = summaryTexts({
      ...BASE, fps: null, worstFrameMs: 428, slowFrameCount: 1, zoom: 6.45,
    }).at(-1);
    const jank = summaryTexts({
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
