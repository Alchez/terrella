/** How many tile requests may be in flight at once, and `?maxreq=N` to override it.
 *
 *  MapLibre keeps ONE global FIFO queue for every image request — raster tiles, raster-dem tiles,
 *  sprites, icons — and runs at most `MAX_PARALLEL_IMAGE_REQUESTS` of them at a time. Anything past
 *  that waits in MapLibre's own queue, which is invisible to Resource Timing: an entry only exists
 *  once the browser issues the request, so a queued tile looks like a tile nobody asked for yet.
 *
 *  THIS MODULE USED TO ARGUE THE OPPOSITE, AND PREDICTED "leave it at 16". The argument was that
 *  over HTTP/2 every tile shares one connection, so concurrency divides bandwidth rather than
 *  adding to it. That is true and it is not what dominates. Measured on production, 11 cold
 *  full-viewport loads at z6 across separated regions, arms interleaved:
 *
 *      cap   achieved concurrency (median of n)   vs 16
 *       16                 10.4  (n=3)              —
 *       32                 21.5  (n=3)            2.1x
 *       48                 30.4  (n=2)            2.9x
 *       64                 37.5  (n=3)            3.6x
 *
 *  Achieved concurrency tracks the cap at a steady ~60-65% with NO knee below 64, because a tile
 *  is latency-bound rather than bandwidth-bound: it is a range read through the tile Worker into
 *  R2, measured at 700-1370 ms TTFB when the edge is cold. Parallelism is what overlaps that wait.
 *  Raw first-idle could not see this — per-tile latency varies 3.3x by region and swamps it — so
 *  the numbers above are `tiles/sec x median tile latency`, which divides the region out.
 *
 *  WHY 32 AND NOT 64. 64 measured better and is not what ships. Every one of those runs is one
 *  desktop, one browser, one network, one edge PoP; 32 captures the large, safe half of the win
 *  (2.1x) while 64's efficiency was already drifting down (65% -> 59%) and more streams in flight
 *  is exactly what hurts on a lossy radio link. Raise it when a phone has been measured, not
 *  before.
 *
 *  `?maxreq=N` remains the measurement override and still beats the default in both directions,
 *  in the `?perf` / `?bare` / `?nocaps` tradition.
 */

/** MapLibre's own default, from its shipped type declarations. Duplicated here only so a
 *  measurement run can state its control value; the library is still the one that applies it. */
export const MAPLIBRE_DEFAULT_MAX_PARALLEL_IMAGE_REQUESTS = 16;

/** Upper bound for the override. Not a MapLibre limit — a guard against a typo'd URL opening
 *  hundreds of streams on one HTTP/2 connection, which is a way to make the page worse, not a
 *  measurement. It is now also the top of the measured ladder rather than "well above any rung
 *  worth testing": the sweep found no saturation below it, so testing past 64 means raising this
 *  first, and the next thing to check would be the server's concurrent-stream limit. */
export const MAX_PARALLEL_IMAGE_REQUESTS_CEILING = 64;

/** What an unconstrained visitor gets instead of MapLibre's 16. See the module header for the
 *  ladder this was chosen from, and for why it is not 64. */
export const RAISED_MAX_PARALLEL_IMAGE_REQUESTS = 32;

/** The conditions that decide whether a visitor gets the raised cap.
 *
 *  These are SIGNALS, not the resolved tier, and that is deliberate — for two reasons that have
 *  both been demonstrated rather than argued. An explicit `full` choice **bypasses the ladder's
 *  soft checks entirely**, so a visitor who picked Full on a metered connection is `full` tier on
 *  exactly the link that must not get 32 streams; gating on tier would have raised the cap for
 *  them. And the ladder's own answer for `slowNetwork` has since MOVED — it used to mean `gallery`
 *  and now means `globe` — which would silently have changed this cap had it keyed on the verdict
 *  instead of the fact. The bottleneck here is the network path, so the network facts are what it
 *  keys on, and that is what made this survive a change to the thing it does not read. */
export interface ConcurrencyConditions {
  /** `navigator.connection.saveData` or `prefers-reduced-data` — an explicit ask for restraint. */
  saveData: boolean;
  /** A slow effective connection, where more streams in flight compete rather than overlap. */
  slowNetwork: boolean;
  /** A phone or tablet. Unmeasured, therefore unchanged: every run behind the raised value was a
   *  desktop on wired broadband, and a lossy radio link is the case where extra concurrency is
   *  most likely to cost rather than pay. */
  mobileClass: boolean;
}

/**
 * The cap to install when no `?maxreq` override is present.
 *
 * Conservative by construction: it returns MapLibre's own default for every constrained case, so
 * this change is a strict no-op on any device it was not measured on. The only visitors who move
 * are the ones the sweep actually covered.
 */
export function defaultMaxParallelImageRequests(conditions: ConcurrencyConditions): number {
  if (conditions.saveData || conditions.slowNetwork || conditions.mobileClass) {
    return MAPLIBRE_DEFAULT_MAX_PARALLEL_IMAGE_REQUESTS;
  }
  return RAISED_MAX_PARALLEL_IMAGE_REQUESTS;
}

/**
 * Read `?maxreq=N`, returning the override or `null`.
 *
 * `null` means "no valid override" — absent, malformed, or out of range are deliberately not
 * distinguished here, so the parser stays pure. Callers that want to complain about a typo can
 * check `params.has("maxreq")` themselves; silently running at the default after someone asked
 * for 8 is the outcome worth avoiding, because it produces a measurement of the wrong thing.
 */
export function parseMaxParallelImageRequests(params: URLSearchParams): number | null {
  const raw = params.get("maxreq");
  if (raw === null || raw.trim() === "") return null;
  // Number() rather than parseInt(): parseInt("8tiles") is 8, and a URL that says "8tiles" is a
  // mistake we want to reject rather than reinterpret.
  const value = Number(raw);
  if (!Number.isInteger(value)) return null;
  if (value < 1 || value > MAX_PARALLEL_IMAGE_REQUESTS_CEILING) return null;
  return value;
}
