// The flags that exist to VARY AN ARM in a measurement, and nothing else.
//
// WHY THESE SHARE A MODULE
// ------------------------
// Not because they are related — one is a tile-refresh policy and the other is LOD geometry — but
// because they share the one property that matters: each is inert without `?perf`, and that rule
// has to be stated once. Spread across two call sites it becomes two spellings of a gate, which is
// how a gate ends up dead on one of them. `?maxreq` and `?skirt` predate this rule and are parsed
// unconditionally; they are not retrofitted here, because widening what a production URL can change
// is the opposite of the point.
//
// WHY THE ARM MUST BE A URL FLAG AND NOT A RUNTIME CALL
// ----------------------------------------------------
// `refreshExpiredTiles` is a MapConstructorOptions field and cannot be toggled on a live map at
// all, which settles it for that one. `?lod=` could have been a runtime call and deliberately is
// not: a sweep that mutates a live map between arms cannot prove which configuration was in force
// when a number was taken, and a sweep that did exactly that produced a conclusion inverted for ten
// days. Read once at setup, never mutated, and recorded in the report's own origin because it is
// part of the URL.

/**
 * Whether arm flags are live at all.
 *
 * The single gate. A `?lod=11` on a production URL parses to null and changes nothing, so a link
 * pasted somewhere public cannot quietly reconfigure a stranger's globe.
 */
function armFlagsArmed(params: URLSearchParams): boolean {
  return params.has("perf");
}

/** Widest `maxZoomLevelsOnScreen` worth offering. MapLibre clamps the low end at 1 itself; the
 *  high end is bounded only so a typo like `?lod=110` reads as a typo rather than as an arm. */
export const LOD_MAX_ZOOM_LEVELS_RANGE = { min: 1, max: 24 } as const;

/**
 * The ratio the `?lod=` arm holds fixed: MapLibre's own default.
 *
 * Held rather than exposed so the arm varies ONE thing. It is also inert for this page at any
 * `maxZoomLevelsOnScreen >= 9.314` — its term is `-scaleZoom(max(1, tileCount/tileCountPitch0/R))/2`
 * and that inner quotient never exceeds 1 at our lens, so the clamp zeroes the term whatever R is.
 * A second axis that cannot move the result is a way to spend arms without learning anything.
 */
export const LOD_DEFAULT_TILE_COUNT_MAX_MIN_RATIO = 3.0;

/**
 * `maxZoomLevelsOnScreen` for `setSourceTileLodParams`, or null for absent, malformed, out of
 * range, or not armed.
 *
 * A FLOAT, because the default is 9.314 and an integer-only parser would make the default itself
 * unexpressible — an arm that cannot state the baseline it is compared against is half an
 * experiment. Null on anything doubtful, exactly as `parseMaxParallelImageRequests` does and for
 * its reason: a run that believes it measured M=11 while running at the default is worse than no
 * run.
 *
 * NOTE for whoever reads a sweep of this: values below about 5.4 INVERT the horizon falloff at our
 * fov 15, and that is a lens property rather than a bug. Deliberately still reachable — the
 * inverted regime is a thing a measurement may want to enter on purpose.
 */
export function parseLodMaxZoomLevelsOnScreen(params: URLSearchParams): number | null {
  if (!armFlagsArmed(params)) return null;
  const raw = params.get("lod");
  if (raw === null || raw.trim() === "") return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  return value >= LOD_MAX_ZOOM_LEVELS_RANGE.min && value <= LOD_MAX_ZOOM_LEVELS_RANGE.max
    ? value
    : null;
}

/** The two spellings `?refresh=` takes. Named rather than 1/0 for the reason `?skirt=` is: a
 *  number invites `?refresh=2`, which has no meaning and would otherwise round to a silent arm. */
export const REFRESH_MODES = ["on", "off"] as const;

/**
 * `refreshExpiredTiles`, or null for absent, malformed, or not armed.
 *
 * `off` is NOT the same as absent, and that asymmetry is the design. Absent leaves the shipped
 * default alone and records nothing; an explicit `?refresh=off` sets the same value but appears in
 * the report's `origin.flags` as `refresh=off`, so the CONTROL arm of a sweep is self-documenting
 * rather than being the arm you can only identify by what it lacks.
 */
export function parseRefreshExpiredTiles(params: URLSearchParams): boolean | null {
  if (!armFlagsArmed(params)) return null;
  const raw = params.get("refresh");
  if (raw === null) return null;
  const mode = raw.trim().toLowerCase();
  return mode === "on" ? true : mode === "off" ? false : null;
}

/**
 * The complaint for a flag that was written but not honoured, or null when there is nothing to say.
 *
 * Exists because the two ways a flag gets ignored are indistinguishable on screen — a typo and a
 * missing `?perf` both produce a globe that looks exactly like the default — and a measurement run
 * against a silently-ignored flag is the failure this whole module is here to stop.
 *
 * `honoured` IS REQUIRED, and the first version of this function did not take it: it complained
 * whenever the flag was present, so a perfectly good `?lod=11` logged "not a value this flag takes"
 * beside the line reporting it applied. The tests exercised a typo and a missing `?perf` and never
 * the case where the flag WORKS, which is how a warning that cried wolf on every valid arm shipped
 * past them. A complaint has to be told what happened; it cannot infer it from presence.
 */
export function armFlagComplaint(
  params: URLSearchParams,
  flag: string,
  honoured: boolean,
): string | null {
  if (!params.has(flag) || honoured) return null;
  const written = params.get(flag) ?? "";
  if (!armFlagsArmed(params)) {
    return `[perf] ignoring ?${flag}=${written} — arm flags need ?perf too`;
  }
  return `[perf] ignoring ?${flag}=${written} — not a value this flag takes`;
}
