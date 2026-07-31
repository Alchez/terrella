// Grouping for the ?perf panel. The panel renders fourteen lines in one colour, and nothing on it
// said which subsystem a number belonged to — `caps 68 MB` is GPU memory, `tiles … 1.9 MB wire` is
// network, `long tasks 13` is the main thread, and all three looked identical. A reader was doing
// the attribution from memory instead of from the screen, which is the one job the panel has.
//
// This module owns the grouping and nothing else: it is pure, has no DOM dependency, and does not
// know what any line says. The producers tag; this renders.

/**
 * Which subsystem a panel line describes.
 *
 * `gpu` and `ram` are SEPARATE because the panel was conflating them under one "GPU · MEMORY"
 * heading, which is the exact false attribution this grouping exists to remove. `caps` is texture
 * bytes resident on the GPU; the DEM cache is JS-heap bytes in system RAM (`DEMData` holds a
 * `Uint32Array` over the padded image). That the DEM cache's 384 MiB ceiling was chosen to bound a
 * VRAM failure — heap bytes standing in as a proxy, because no web API reports VRAM headroom — is a
 * fact about the budget, not about where the bytes live, and belongs in HISTORY rather than on a
 * heading.
 *
 * `alarm` and `origin` are not subsystems and that is deliberate. Faults must render FIRST and
 * without a heading, because a heading is exactly what teaches the eye to skip a block — the same
 * reasoning that already keeps `FAULT` off the panel entirely when there is nothing wrong. The
 * origin line is last for the complementary reason: whatever else is cropped out of a screenshot,
 * the arm the numbers came from should not be.
 */
export type PerfGroup =
  | "alarm"
  | "feel"
  | "cpu"
  | "network"
  | "gpu"
  | "ram"
  | "device"
  | "config"
  | "origin";

/** One tagged line. `text` is already formatted by whichever module owns that reading. */
export interface PerfLine {
  group: PerfGroup;
  text: string;
}

/**
 * The heading each group renders above its lines; null means the lines render bare.
 *
 * A `Record` over the union rather than a list of pairs, so adding a member to `PerfGroup` without
 * deciding its heading is a COMPILE error rather than a group that quietly renders headerless and
 * reads as a continuation of whatever precedes it.
 */
export const PERF_GROUP_HEADINGS: Record<PerfGroup, string | null> = {
  alarm: null,
  feel: "FEEL",
  cpu: "CPU · MAIN THREAD",
  network: "NETWORK",
  gpu: "GPU · VRAM",
  ram: "RAM",
  device: "DEVICE",
  config: "CONFIG",
  origin: null,
};

/**
 * Render sequence.
 *
 * Kept as its own constant rather than derived from `Object.keys(PERF_GROUP_HEADINGS)`, which would
 * need a cast back to `PerfGroup[]` — and a cast is the thing that hides the mistake it is standing
 * in for. The cost of two constants is that a group can be dropped from this array while lines
 * still tag it, in which case those lines vanish silently; that case is a named test rather than a
 * runtime throw, because a panel that throws mid-tick is worse than one missing a row.
 */
export const PERF_GROUP_ORDER: readonly PerfGroup[] = [
  "alarm",
  "feel",
  "cpu",
  "network",
  "gpu",
  "ram",
  "device",
  "config",
  "origin",
];

/**
 * Lay tagged lines out as labelled blocks, ready to join with newlines.
 *
 * A group with no lines is omitted ENTIRELY — heading included. An empty `NETWORK` heading is a row
 * that says nothing while costing a line of a 412 px phone screen, and a panel of headings with no
 * numbers under them reads as an instrument that failed rather than one with nothing to report.
 *
 * Within a group, lines keep the order they were composed in. One ordering rule, not two.
 */
export function groupPerfLines(lines: readonly PerfLine[]): string[] {
  const rendered: string[] = [];
  for (const group of PERF_GROUP_ORDER) {
    const inGroup = lines.filter((line) => line.group === group);
    if (inGroup.length === 0) continue;
    // Blank lines separate groups rather than introduce them: none before the first, none after
    // the last. Trailing whitespace in a `pre-wrap` panel is a visible empty row.
    if (rendered.length > 0) rendered.push("");
    const heading = PERF_GROUP_HEADINGS[group];
    if (heading !== null) rendered.push(heading);
    for (const line of inGroup) rendered.push(line.text);
  }
  return rendered;
}
