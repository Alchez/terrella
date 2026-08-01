import { afterEach, describe, expect, it } from "vitest";

import {
  beginSpan,
  disablePerfTrace,
  enablePerfTrace,
  perfTraceEnabled,
  userTimingSupported,
  type SpanEntry,
} from "./perfSpans";

/** A `performance` stand-in that records what was called. No browser, no globals touched. */
export function fakePerformance() {
  const marks: string[] = [];
  const measures: SpanEntry[] = [];
  const cleared: string[] = [];
  let clock = 0;
  const startedAt = new Map<string, number>();
  return {
    marks,
    measures,
    cleared,
    advance(ms: number) {
      clock += ms;
    },
    api: {
      mark(name: string) {
        marks.push(name);
        startedAt.set(name, clock);
      },
      measure(name: string, startMark: string) {
        const start = startedAt.get(startMark);
        if (start === undefined) throw new Error(`no such mark: ${startMark}`);
        measures.push({ name, startTime: start, duration: clock - start });
      },
      clearMarks(name: string) {
        cleared.push(name);
      },
      getEntriesByType(type: string) {
        return type === "measure" ? (measures as unknown as PerformanceEntry[]) : [];
      },
    } as unknown as Partial<Performance>,
  };
}

afterEach(disablePerfTrace);

describe("userTimingSupported", () => {
  it("is false when any of the three calls is missing", () => {
    // NOT `userTimingSupported(undefined)`: passing undefined explicitly re-triggers the default
    // parameter and falls back to the REAL `globalThis.performance`, which node implements — so
    // that call would assert the opposite of what it reads like. An object missing the methods is
    // the honest stand-in for a browser without User Timing.
    expect(userTimingSupported({} as unknown as Partial<Performance>)).toBe(false);
    expect(userTimingSupported({ mark: () => undefined } as unknown as Partial<Performance>)).toBe(
      false,
    );
    expect(
      userTimingSupported({
        mark: () => undefined,
        measure: () => undefined,
      } as unknown as Partial<Performance>),
    ).toBe(false);
  });

  it("is true for a complete implementation", () => {
    expect(userTimingSupported(fakePerformance().api)).toBe(true);
  });
});

describe("beginSpan", () => {
  it("is a hard no-op until enabled, so a visitor without ?perf pays nothing", () => {
    const performanceApi = fakePerformance();
    expect(perfTraceEnabled()).toBe(false);
    beginSpan("caps:decode", performanceApi.api)();
    expect(performanceApi.marks).toEqual([]);
    expect(performanceApi.measures).toEqual([]);
  });

  it("records a measure once armed", () => {
    const performanceApi = fakePerformance();
    enablePerfTrace(performanceApi.api);
    const end = beginSpan("caps:decode", performanceApi.api);
    performanceApi.advance(42);
    end();
    expect(performanceApi.measures).toEqual([{ name: "caps:decode", startTime: 0, duration: 42 }]);
  });

  it("gives concurrent spans of one name distinct marks", () => {
    // Two cap textures decode at once; a shared mark name would close the wrong span.
    const performanceApi = fakePerformance();
    enablePerfTrace(performanceApi.api);
    const first = beginSpan("caps:decode", performanceApi.api);
    performanceApi.advance(10);
    const second = beginSpan("caps:decode", performanceApi.api);
    performanceApi.advance(5);
    first();
    second();
    expect(new Set(performanceApi.marks).size).toBe(2);
    expect(performanceApi.measures.map((entry) => entry.duration)).toEqual([15, 5]);
  });

  it("clears its mark, so a per-tile span cannot evict the entry buffer", () => {
    const performanceApi = fakePerformance();
    enablePerfTrace(performanceApi.api);
    beginSpan("caps:upload", performanceApi.api)();
    expect(performanceApi.cleared).toEqual(performanceApi.marks);
  });

  it("ignores a second close instead of recording a duplicate", () => {
    const performanceApi = fakePerformance();
    enablePerfTrace(performanceApi.api);
    const end = beginSpan("caps:upload", performanceApi.api);
    end();
    end();
    expect(performanceApi.measures).toHaveLength(1);
  });

  it("stays a no-op on a browser without User Timing", () => {
    expect(enablePerfTrace({} as unknown as Partial<Performance>)).toBe(false);
    expect(perfTraceEnabled()).toBe(false);
  });
});
