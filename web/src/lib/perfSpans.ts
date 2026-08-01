// Opening and closing named performance spans, which has to be possible from always-shipped code.
//
// WHY THIS IS NOT IN lib/perf/ WITH THE REST OF THE INSTRUMENT
// -----------------------------------------------------------
// Same split, and the same reason, as `resourceTimingBuffer.ts` next door. The spans this project
// wants most are around cap decode/upload in `polarCaps.ts` and the countries GeoJSON parse — both
// ordinary always-shipped code, and both running from `style.load`, which can fire before a lazily
// imported module has resolved. A call site cannot `await import(...)` per span, and a static import
// of anything in `lib/perf/` would place that whole directory in the main chunk: that is precisely
// how 268 lines of instrument once shipped to every visitor for +2,362 bytes.
//
// So the RUNTIME half lives here — arming, opening, closing — and stays small. The ANALYSIS half
// (interval union, long-task intersection, summarising) is report-time only and stays behind the
// lazy boundary in `lib/perf/perfTrace.ts`, where a visitor without `?perf` never downloads it.
//
// Splitting the import site does not split the chunk. Splitting the MODULE does.

/** A span's close function. Calling it twice records nothing the second time. */
export type EndSpan = () => void;

/** The shape this module needs from a `PerformanceMeasure`, so analysis tests need no browser. */
export interface SpanEntry {
  name: string;
  startTime: number;
  duration: number;
}

/**
 * The spans this app places, as one list so the writer and the reader cannot drift.
 *
 * Chosen from what the measurements already accuse: the caps chain is Firefox's main-thread blocker
 * (~1.1 s of decode + upload), and the countries GeoJSON is both the largest single asset (3.08 MB,
 * larger than all 36 tiles combined) and the ~355 ms LoAF already named.
 */
export const TRACED_SPANS = [
  "caps:fetch",
  "caps:decode",
  "caps:upload",
  "caps:mipmap",
  "caps:elev",
  // The one LoAF actually accused. It named the countries post-fetch CHAIN at ~355 ms — 54% of all
  // long-frame script time — and a Zen capture showed the JSON parse was only 46 ms of that, so the
  // cost was source and layer CONSTRUCTION rather than parsing. `countries:fetch` and
  // `countries:parse` sat here beside it and are gone with the GeoJSON path they timed: the vector
  // archive is addressed by URL, so the worker does the fetching and parsing and the main thread
  // has nothing left to price. This span survives because it is what stayed measurable — and what
  // it now measures is 1–3 ms rather than 20.
  "countries:layers",
] as const;

export type TracedSpan = (typeof TRACED_SPANS)[number];

const NOOP_END: EndSpan = () => {};

let tracing = false;
let sequence = 0;

/**
 * Whether this browser implements User Timing well enough to trace.
 *
 * Feature-tested rather than try/caught, for the same reason `longTaskApiSupported` is: a browser
 * that ignores an unsupported call without throwing leaves the panel printing confident zeros from
 * an instrument that never registered, and a zero from an instrument that never ran is
 * indistinguishable from a genuinely quiet main thread.
 */
export function userTimingSupported(
  performanceApi: Partial<Performance> | undefined = globalThis.performance,
): boolean {
  return (
    typeof performanceApi?.mark === "function" &&
    typeof performanceApi?.measure === "function" &&
    typeof performanceApi?.getEntriesByType === "function"
  );
}

/**
 * Arm tracing. Call SYNCHRONOUSLY during page setup, ahead of `new maplibregl.Map`.
 *
 * Returns whether tracing actually came on, so a caller records the instrument's own state beside
 * its numbers instead of assuming it ran — the habit that would have caught a two-night finding
 * produced by an instrument that was itself the load.
 */
export function enablePerfTrace(
  performanceApi: Partial<Performance> | undefined = globalThis.performance,
): boolean {
  tracing = userTimingSupported(performanceApi);
  return tracing;
}

/** Disarm. Exists for the instrument-off control arm, and to keep tests independent. */
export function disablePerfTrace(): void {
  tracing = false;
}

export function perfTraceEnabled(): boolean {
  return tracing;
}

/**
 * Open a named span; call the returned function to close it.
 *
 * A hard no-op until {@link enablePerfTrace}, so a visitor without `?perf` pays one boolean read per
 * call site and nothing else. Mark names carry a sequence number because the same span can be open
 * twice concurrently — two cap textures decode at once — and `performance.measure` would otherwise
 * close the wrong one.
 */
export function beginSpan(
  name: string,
  performanceApi: Partial<Performance> | undefined = globalThis.performance,
): EndSpan {
  if (!tracing || !performanceApi?.mark || !performanceApi?.measure) return NOOP_END;
  sequence += 1;
  const startMark = `${name}:start:${sequence}`;
  performanceApi.mark(startMark);
  let closed = false;
  return () => {
    if (closed) return;
    closed = true;
    try {
      performanceApi.measure?.(name, startMark);
    } finally {
      // Marks accumulate for the life of the document and the entry buffer is finite; a span opened
      // per tile would otherwise evict the very entries this exists to read.
      performanceApi.clearMarks?.(startMark);
    }
  };
}
