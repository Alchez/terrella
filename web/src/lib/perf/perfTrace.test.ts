import { describe, expect, it } from "vitest";

import type { SpanEntry } from "../perfSpans";
import {
  collectSpans,
  mergeIntervals,
  overlapMs,
  summariseSpans,
  type Interval,
} from "./perfTrace";

const span = (name: string, startTime: number, duration: number): SpanEntry => ({
  name,
  startTime,
  duration,
});
const interval = (startMs: number, endMs: number): Interval => ({ startMs, endMs });

describe("mergeIntervals", () => {
  it("unions overlapping, nested and touching intervals", () => {
    expect(mergeIntervals([interval(0, 10), interval(5, 15)])).toEqual([interval(0, 15)]);
    expect(mergeIntervals([interval(0, 20), interval(5, 10)])).toEqual([interval(0, 20)]);
    expect(mergeIntervals([interval(0, 10), interval(10, 20)])).toEqual([interval(0, 20)]);
  });

  it("keeps disjoint intervals apart and sorts them", () => {
    expect(mergeIntervals([interval(30, 40), interval(0, 10)])).toEqual([
      interval(0, 10),
      interval(30, 40),
    ]);
  });

  it("drops zero-length and inverted intervals", () => {
    expect(mergeIntervals([interval(5, 5), interval(10, 4)])).toEqual([]);
  });
});

describe("overlapMs", () => {
  it("counts only the shared time", () => {
    expect(overlapMs([interval(0, 100)], [interval(60, 200)])).toBe(40);
  });

  it("is zero for disjoint lists", () => {
    expect(overlapMs([interval(0, 10)], [interval(20, 30)])).toBe(0);
  });

  it("does not double-count two spans covering the same blocked window", () => {
    expect(overlapMs([interval(0, 50), interval(0, 50)], [interval(0, 50)])).toBe(50);
  });

  it("sums across several disjoint windows", () => {
    expect(overlapMs([interval(0, 10), interval(20, 30)], [interval(5, 25)])).toBe(10);
  });
});

describe("summariseSpans", () => {
  it("groups by name with total, count and max", () => {
    const summary = summariseSpans(
      [span("caps:decode", 0, 30), span("caps:decode", 40, 70), span("caps:fetch", 0, 5)],
      null,
    );
    expect(summary.spans[0]).toEqual({ name: "caps:decode", totalMs: 100, count: 2, maxMs: 70 });
    expect(summary.spans[1].name).toBe("caps:fetch");
  });

  it("sorts by total descending, so the first row is the subsystem to look at", () => {
    const summary = summariseSpans([span("small", 0, 1), span("large", 0, 900)], null);
    expect(summary.spans.map((entry) => entry.name)).toEqual(["large", "small"]);
  });

  it("reports a NULL remainder where there is no long-task figure, never zero", () => {
    // Firefox. A zero here is indistinguishable from a fully attributed session.
    const summary = summariseSpans([span("caps:decode", 0, 30)], null);
    expect(summary.unattributedMs).toBeNull();
    expect(summary.attributedMs).toBe(0);
  });

  it("attributes only the span time that lands INSIDE a long task", () => {
    const summary = summariseSpans([span("countries:parse", 0, 100)], [interval(60, 100)], 40);
    expect(summary.attributedMs).toBe(40);
    expect(summary.unattributedMs).toBe(0);
  });

  it("leaves MapLibre's own blocked time in the remainder", () => {
    const summary = summariseSpans(
      [span("caps:decode", 0, 20)],
      [interval(0, 20), interval(500, 700)],
      220,
    );
    expect(summary.attributedMs).toBe(20);
    expect(summary.unattributedMs).toBe(200);
  });

  it("does not go negative when a span runs across SHORT tasks", () => {
    // The defect in the naive `longTaskTotalMs - sum(durations)`: a 5,000 ms span that never lands
    // in a long task would drive that remainder to -4,900 and mean nothing at all.
    const summary = summariseSpans([span("countries:parse", 0, 5000)], [interval(9000, 9100)], 100);
    expect(summary.attributedMs).toBe(0);
    expect(summary.unattributedMs).toBe(100);
  });

  it("holds attributed + unattributed === the long-task total, over many shapes", () => {
    const shapes: Array<[SpanEntry[], Interval[], number]> = [
      [[span("a", 0, 10)], [interval(0, 10)], 10],
      [[span("a", 0, 10), span("b", 5, 20)], [interval(0, 30)], 30],
      [[span("a", 100, 10)], [interval(0, 30)], 30],
      [[], [interval(0, 45)], 45],
      [[span("a", 0, 1000)], [interval(10, 20), interval(40, 60)], 30],
    ];
    for (const [entries, tasks, total] of shapes) {
      const summary = summariseSpans(entries, tasks, total);
      expect(summary.attributedMs + (summary.unattributedMs ?? 0)).toBe(total);
      expect(summary.attributedMs).toBeGreaterThanOrEqual(0);
      expect(summary.unattributedMs).toBeGreaterThanOrEqual(0);
    }
  });
});

describe("collectSpans", () => {
  const withMeasures = (measures: SpanEntry[]) =>
    ({
      getEntriesByType: (type: string) =>
        type === "measure" ? (measures as unknown as PerformanceEntry[]) : [],
    }) as unknown as Partial<Performance>;

  it("returns only the named spans", () => {
    const api = withMeasures([span("caps:decode", 0, 5), span("something:else", 0, 5)]);
    expect(collectSpans(["caps:decode"], api).map((entry) => entry.name)).toEqual(["caps:decode"]);
  });

  it("returns [] rather than throwing where the API is absent", () => {
    expect(collectSpans(["caps:decode"], {} as unknown as Partial<Performance>)).toEqual([]);
  });
});
