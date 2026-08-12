// Naming a `?perf` capture on disk.
//
// WHY THIS IS NOT IN lib/perf/
// ----------------------------
// Same exemption as `perfSpans.ts` and `resourceTimingBuffer.ts`, for a different reason. Those two
// are out because they must run before the lazy chunk resolves; this one is out because it never
// runs in a browser at all — its only caller is the dev-server endpoint in `astro.config.ts`.
// `lib/perf/` means "client instrument behind the lazy boundary", and its guard enforces exactly
// that: every module in there must be reachable from `Globe.astro`'s dynamic import. A module that
// only the config imports could not satisfy that rule and should not be asked to.
//
// Nothing in the client graph imports this, so it ships no bytes to a visitor.

/**
 * Longest arm label kept in a filename.
 *
 * Not a safety bound — {@link slugifyArm} is what makes the value safe, and it is safe at any
 * length. This is a legibility bound: the timestamp is already 24 characters and a directory
 * listing stops being scannable when one column runs past the terminal.
 */
export const PERF_CAPTURE_ARM_MAX = 40;

/**
 * Reduce a caller's arm label to something that can be a filename, or null if nothing survives.
 *
 * The label crosses a network boundary from the page to the dev server, so it is UNTRUSTED input
 * being spliced into a path. This allow-lists rather than escaping: `..` and `/` do not need
 * special cases because a dot and a slash are simply not in the output alphabet, which is a
 * property of the function rather than a list of attacks someone remembered.
 *
 * Null rather than a fallback string like `arm`, because a label that slugs to nothing means the
 * caller sent something meaningless — and a capture silently named for a label that was never
 * usable is the kind of record this whole instrument exists to stop.
 */
export function slugifyArm(arm: string | null | undefined): string | null {
  if (arm === null || arm === undefined) return null;
  const slug = arm
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, PERF_CAPTURE_ARM_MAX)
    // A cap can land mid-run and leave a trailing separator, which reads as a truncation the
    // filename cannot otherwise show. Trim again rather than before, so the cap decides the cut.
    .replace(/-+$/, "");
  return slug === "" ? null : slug;
}

/**
 * The filename for one capture: always the timestamp, then the arm when there is one.
 *
 * TIMESTAMP FIRST, and it is a deliberate trade. Arm-first would group every run of a sweep by arm,
 * which is the wrong grouping: the comparison that matters is between the arms of ONE run, and a
 * lexical sort must keep those adjacent. Timestamp-first also leaves the existing chronological
 * reading of this directory intact for the ad-hoc captures that carry no arm at all.
 */
export function perfCaptureName(stamp: string, arm: string | null | undefined): string {
  const slug = slugifyArm(arm);
  return slug === null ? `${stamp}.json` : `${stamp}-${slug}.json`;
}
