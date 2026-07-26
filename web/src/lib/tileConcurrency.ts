/** `?maxreq=N` — override MapLibre's parallel image-request cap, for measurement.
 *
 *  MapLibre caps concurrent image loads (raster tiles, sprites, icons) at 16 by default. Whether
 *  16 is right for a globe that asks for ~36–40 tiles per cold view is genuinely open, and the
 *  sign is not obvious in either direction:
 *
 *  - Over HTTP/2 every tile shares ONE connection, so concurrency **divides** the bandwidth
 *    rather than adding to it. Sixteen streams all crawl and none finishes early; fewer streams
 *    finish sooner, and a tile that has finished is a tile that has painted.
 *  - But an edge-cold tile is **latency**-bound — ~440 ms TTFB measured — and
 *    parallelism is exactly what overlaps latency. Fewer streams means more serialised waiting.
 *
 *  Which effect dominates depends on cache state and link speed, so this exists to be *measured*
 *  rather than guessed, and a likely honest outcome is "leave it at 16". It is a diagnostic in the
 *  `?perf` / `?bare` / `?nocaps` tradition, not a feature: nothing reads it unless a URL asks.
 */

/** MapLibre's own default, from its shipped type declarations. Duplicated here only so a
 *  measurement run can state its control value; the library is still the one that applies it. */
export const MAPLIBRE_DEFAULT_MAX_PARALLEL_IMAGE_REQUESTS = 16;

/** Upper bound for the override. Not a MapLibre limit — a guard against a typo'd URL opening
 *  hundreds of streams on one HTTP/2 connection, which is a way to make the page worse, not a
 *  measurement. Well above any rung worth testing. */
export const MAX_PARALLEL_IMAGE_REQUESTS_CEILING = 64;

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
