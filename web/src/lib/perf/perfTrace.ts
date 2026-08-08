/**
 * Turning raw spans into "of the blocked time, how much was ours".
 *
 * WHY THIS EXISTS
 * ---------------
 * The panel reports `long tasks 200 · 12,645 ms`, which says time was lost and nothing about to
 * what. LoAF closed part of the gap — it named the `countries.geojson` post-fetch chain at ~355 ms,
 * ~54% of long-frame script time — but it attributes to a CHUNK URL rather than a function, and it
 * is Chromium-only. **Firefox has neither Long Tasks nor LoAF**, and Firefox is where this project
 * is judged: a Zen capture of a 4,650 ms stall could attribute nothing at all. `performance.mark`
 * and `measure` are universal, so spans are the only instrument that reports in both browsers.
 *
 * The RUNTIME half — arming, opening and closing spans — is deliberately not here. It lives in
 * `lib/perfSpans.ts`, outside this lazy boundary, because its call sites are ordinary always-shipped
 * code. See that file's header for the chunking argument. Only report-time analysis belongs here.
 *
 * THE REMAINDER IS AN INTERSECTION, NOT A SUBTRACTION
 * ---------------------------------------------------
 * The obvious formula, `longTaskTotalMs - sum(span durations)`, subtracts two quantities measured
 * over different populations. A span that runs across many SHORT tasks adds to the sum while
 * contributing nothing to the long-task total, so that "remainder" goes negative and means nothing
 * when it does. What a reader wants is *of the blocked time, how much was ours*, so span intervals
 * are unioned (nested and overlapping spans must not count twice), intersected with the long-task
 * intervals, and only the overlap is subtracted. The result cannot go negative, and
 * `attributedMs + unattributedMs === longTaskTotalMs` holds by construction.
 *
 * WHAT NO SPAN WILL EVER ENCLOSE
 * ------------------------------
 * MapLibre's internals cannot be instrumented from here, and neither can a driver stall — the
 * current suspect for the single 2.4 s task is texture eviction under VRAM pressure. A breakdown
 * omitting that remainder would read as complete while being anything but, which is why
 * `unattributedMs` is always reported and is null, never 0, where there is nothing to subtract from.
 */

import type { SpanEntry } from "../perfSpans";

/** One span's aggregate across a session. */
export interface SpanSummary {
  name: string;
  /** Wall-clock total of every occurrence, including any overlap with other spans. */
  totalMs: number;
  count: number;
  /** Longest single occurrence — a mean hides the one stall that matches the feeling. */
  maxMs: number;
}

export interface TraceSummary {
  /** Descending by `totalMs`, so the first row is the subsystem worth looking at. */
  spans: SpanSummary[];
  /** Long-task time enclosed by at least one span. Never exceeds `longTaskTotalMs`. */
  attributedMs: number;
  /**
   * Long-task time no span enclosed — MapLibre internals, driver stalls, work never wrapped.
   *
   * Null, never zero, where there is no long-task figure to subtract from (Firefox). A zero would be
   * indistinguishable from a fully attributed session, the class of lie `longTaskApiSupported`
   * already exists to prevent one level up.
   */
  unattributedMs: number | null;
}

/** A half-open interval on the navigation clock. */
export interface Interval {
  startMs: number;
  endMs: number;
}

/** Merge overlapping and touching intervals, so unioned time is never counted twice. */
export function mergeIntervals(intervals: readonly Interval[]): Interval[] {
  const sorted = [...intervals]
    .filter((interval) => interval.endMs > interval.startMs)
    .toSorted((left, right) => left.startMs - right.startMs);
  const merged: Interval[] = [];
  for (const interval of sorted) {
    const last = merged[merged.length - 1];
    if (last && interval.startMs <= last.endMs) {
      last.endMs = Math.max(last.endMs, interval.endMs);
    } else {
      merged.push({ ...interval });
    }
  }
  return merged;
}

/**
 * Total time covered by BOTH interval lists.
 *
 * Each side is merged first, so the result is a true set intersection and does not depend on how
 * many spans or tasks happened to overlap one another.
 */
export function overlapMs(left: readonly Interval[], right: readonly Interval[]): number {
  const leftMerged = mergeIntervals(left);
  const rightMerged = mergeIntervals(right);
  let total = 0;
  let leftIndex = 0;
  let rightIndex = 0;
  while (leftIndex < leftMerged.length && rightIndex < rightMerged.length) {
    const first = leftMerged[leftIndex];
    const second = rightMerged[rightIndex];
    const start = Math.max(first.startMs, second.startMs);
    const end = Math.min(first.endMs, second.endMs);
    if (end > start) total += end - start;
    if (first.endMs < second.endMs) leftIndex += 1;
    else rightIndex += 1;
  }
  return total;
}

const toInterval = (entry: SpanEntry): Interval => ({
  startMs: entry.startTime,
  endMs: entry.startTime + entry.duration,
});

/**
 * Group span entries by name, and price the long-task time they do and do not explain.
 *
 * Pure, so the whole contract is testable without a browser — the same split the rest of this
 * directory uses. Pass `longTasks: null` where the API is unavailable; the summary then reports the
 * spans and declines to invent a remainder.
 */
export function summariseSpans(
  entries: readonly SpanEntry[],
  longTasks: readonly Interval[] | null,
  longTaskTotalMs: number | null = null,
): TraceSummary {
  const byName = new Map<string, SpanSummary>();
  for (const entry of entries) {
    const existing = byName.get(entry.name);
    if (existing) {
      existing.totalMs += entry.duration;
      existing.count += 1;
      existing.maxMs = Math.max(existing.maxMs, entry.duration);
    } else {
      byName.set(entry.name, {
        name: entry.name,
        totalMs: entry.duration,
        count: 1,
        maxMs: entry.duration,
      });
    }
  }
  const spans = [...byName.values()].toSorted((left, right) => right.totalMs - left.totalMs);

  if (longTasks === null) {
    return { spans, attributedMs: 0, unattributedMs: null };
  }
  // Prefer the caller's own total over one re-derived here: the long-task observer replays with
  // `buffered: true`, so its total is authoritative over whatever window we happen to hold.
  const blockedTotal =
    longTaskTotalMs ??
    mergeIntervals(longTasks).reduce((sum, interval) => sum + (interval.endMs - interval.startMs), 0);
  const attributedMs = Math.min(overlapMs(entries.map(toInterval), longTasks), blockedTotal);
  return { spans, attributedMs, unattributedMs: blockedTotal - attributedMs };
}

/** Read back the named spans recorded so far. Returns [] where User Timing is absent. */
export function collectSpans(
  names: readonly string[],
  performanceApi: Partial<Performance> | undefined = globalThis.performance,
): SpanEntry[] {
  if (!performanceApi?.getEntriesByType) return [];
  const wanted = new Set(names);
  return (performanceApi.getEntriesByType("measure") as PerformanceEntry[])
    .filter((entry) => wanted.has(entry.name))
    .map((entry) => ({ name: entry.name, startTime: entry.startTime, duration: entry.duration }));
}
