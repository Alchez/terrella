// One structured reading of everything the page already knows about its own performance.
//
// WHY THIS EXISTS
// ---------------
// Every number in this module was ALREADY being computed before it was written. `snapshotGlLoss`
// runs a full device + cap + per-source read on every `idle` and throws it away unless the GPU
// dies; `demCacheCapFault`, `restoreFault`, `probeSignals` and `currentTier` were console-only or
// unread. The cost of that was not the missing measurement — it was that answering "is the phone
// GPU-bound?" meant building a one-off instrument in a console and reading the result off a
// photograph of a screen, once per question. This composes what exists into something that can be
// exported whole.
//
// PURE BY CONSTRUCTION
// --------------------
// Every input is injected. Nothing here reads a global, touches a Map, or calls `performance.now()`
// — so the whole report unit-tests without a DOM, and so the ORIGIN of a reading is a value that
// had to be supplied rather than a fact silently inherited from wherever the code happened to run.
//
// THE ORIGIN IS PART OF THE MEASUREMENT
// -------------------------------------
// Learned the expensive way: a set of phone numbers was quoted for three exchanges before anyone
// established they came from the Vite dev server rather than production. Dev serves hundreds of
// unminified modules (which inflates every main-thread total) while serving tiles from a local file
// in ~1 ms (which understates every network figure). Deltas between two arms of the same build
// survive that; absolutes do not transfer at all. A report that does not state where it was taken
// invites exactly that mistake again, so `origin` is not optional and `devServer` is not inferred.

import type { DegradationAction } from "../fpsDegradation";
import type { CapabilitySignals, Tier } from "../capability";
import type { CapLayerState, GlLossSnapshot } from "../glDiagnostics";
import type { PerfSnapshot } from "./perfOverlay";
import type { CameraFill, TileTraffic } from "./perfNetwork";
import type { PerfLine } from "./perfLines";
import type { DeviceClass } from "../polarCaps";
import { megabytes } from "../format";

/** Bumped when a field changes meaning, so an exported file can be read against the right rules.
 *
 *  2 adds `traffic` and `fill`. Additive, so a v1 file still reads correctly — but the bump earns its keep by
 *  making the absence explicit: a v1 export cannot say whether its byte and timing numbers were
 *  cold or warm, and that ambiguity is exactly what caused two misreadings on 2026-07-30. */
export const PERF_REPORT_SCHEMA = 2;

/** Where and under what conditions a reading was taken. */
export interface PerfOrigin {
  /** Full URL including the flag query, so the arm is recoverable from the file alone. */
  href: string;
  /** `import.meta.env.DEV` at the call site — the build's own answer, NOT a port heuristic.
   *  A heuristic would go wrong on exactly the setup that caused the confusion: the LAN dev
   *  server, reached by IP on a phone, which looks like an ordinary host from inside the page. */
  devServer: boolean;
  userAgent: string;
  /** The map's REQUESTED ratio (`map.getPixelRatio()`), not the display's — the FPS ladder's
   *  middle rung lowers it, which is exactly when the two disagree. */
  devicePixelRatio: number;
  /**
   * What the canvas actually got: `canvas.width / canvas.clientWidth`.
   *
   * Not the same number, and MapLibre says so in its own `.d.ts`: "the pixel ratio actually applied
   * may be lower to respect maxCanvasSize" (default `[4096, 4096]`). Measured on a 2560 px canvas
   * asked for ratio 2: `getPixelRatio()` reported 2 while the buffer was 4096 wide — a realised
   * 1.6. Any DPR-2 display wider than 2048 CSS px hits this. Reporting only the request would put a
   * number on screen that the render never used, which is what this report exists to stop.
   */
  realisedPixelRatio: number;
  viewportCssWidth: number;
  viewportCssHeight: number;
  /** Diagnostic flags in effect (`nocaps`, `bare`, `demcache=off`…), sorted. */
  flags: string[];
  /**
   * Whether the panel was EXPANDED when this was taken.
   *
   * The instrument's own state is part of the reading, and this field exists because that was
   * learned the hard way: the expanded panel used to re-probe capabilities on every 300 ms tick,
   * creating WebGL contexts fast enough to force-lose the map's own — five "GPU context losses" per
   * phone run, a dead globe, and a confident false conclusion that terrain was at fault. The bug is
   * fixed, but the deeper problem was that **nothing in the exported file recorded whether the
   * instrument was displaying**, so two runs that differed only in that respect were compared as
   * though they were the same experiment. An observer effect you cannot see in the data is one you
   * cannot rule out.
   */
  panelExpanded: boolean;
}

/** How far down the FPS degradation ladder this page has walked. */
export interface LadderPosition {
  spinning: boolean;
  pixelRatioLowered: boolean;
  terrainRetired: boolean;
  /** What the ladder would pull next; null means exhausted. */
  nextAction: DegradationAction;
}

export interface PerfReportInputs {
  nowMs: number;
  origin: PerfOrigin;
  timing: PerfSnapshot;
  /** The last healthy `idle` sample, or null before the first one lands. */
  gl: GlLossSnapshot | null;
  deviceClass: DeviceClass;
  signals: CapabilitySignals;
  tier: Tier;
  ladder: LadderPosition;
  demCacheFault: string | null;
  restoreFault: string | null;
  /** WebGL context losses since this page loaded. Distinct from the recovery budget's charged
   *  losses, which expire after an amnesty window — this one never forgets, because the question
   *  it answers is "did the map rebuild itself while I was watching", and a page that recovers
   *  cleanly leaves no other trace once the notice comes down. */
  glLossCount: number;
  /** `performance.now()` at the most recent loss, or null if there has not been one. */
  lastGlLossMs: number | null;
  /**
   * Tile bytes and counts from Resource Timing, split relief/terrain, with browser-cache hits
   * counted separately.
   *
   * The field that makes every absolute in this report interpretable. Two numbers were misreported
   * in one evening for want of it: a phone `bootMs` of 2792 quoted as a startup cost when the next
   * two arms read ~1450 because the first was a cold cache, and a desktop cap total quoted before
   * anyone noticed four of its five files came from cache. "Fetched" and "already had it" are not
   * the same measurement and the report could not tell them apart.
   */
  traffic: TileTraffic;
  /**
   * The most recent `movestart → idle` wait, and whether one is in progress.
   *
   * The metric for the complaint that started all of this — "tiles take a long time to load in" —
   * which had only ever been measured once, by hand, with a rig built for the occasion.
   */
  fill: CameraFill;
}

export interface PerfReport extends PerfReportInputs {
  schema: number;
  /** Age of the `gl` sample when this report was built; null when there is no sample.
   *  Stated rather than left to the reader, because a stale sample presented as a live one is
   *  the failure the GL diagnostics module was written to make impossible. */
  glSampleAgeMs: number | null;
  /** Cap texture resident on the GPU, in whole MiB. Null when no sample has been taken yet —
   *  distinct from 0, which means the caps are genuinely absent (`?nocaps`). */
  capTextureMb: number | null;
  /** Poles with a fetch in flight. A cap mid-climb is still spending main thread; a settled one
   *  is not, and the two are indistinguishable in a still image of the map. */
  capsClimbing: string[];
  /** Every non-null fault, collected so a caller can ask "is anything wrong" without knowing
   *  which fields are faults. Empty is the healthy answer, and it is an answer — but only once
   *  `faultsReadable` is true. Before that it is empty because nothing was asked, not because
   *  nothing is wrong. */
  faults: string[];
  /**
   * Whether the fault checks were in a position to mean anything yet.
   *
   * Both of them have a precondition that the first seconds of a page load do not meet.
   * `demCacheCapFault`'s own docstring says it: `updateCacheSize` runs per render, so calling it
   * before the first frame "reports a fault that is only a stale reading". `restoreFault` is worse
   * — it reports a style with no projection, which is true and alarming during load and means
   * nothing. Seen live on the first run of this panel, which sat there reading
   * `FAULT no terrain tile manager · the style has no projection — every render and every unproject
   * will throw` on a perfectly healthy page that had simply not finished loading.
   *
   * The raw readings stay in the report either way; what is withheld is the VERDICT, and the flag
   * says which case a reader is looking at. Crying wolf here would be the same mistake the DEM
   * cap's `terrainRetired` flag was added to stop.
   */
  faultsReadable: boolean;
}

/** Compose the report. Pure: same inputs, same output, no clock and no globals. */
export function buildPerfReport(inputs: PerfReportInputs): PerfReport {
  const caps: readonly CapLayerState[] = inputs.gl?.caps ?? [];
  // The first idle is when both fault checks become meaningful — the cache size is recomputed per
  // render, and the style has a projection. Not `mapLoadMs`: `load` fires before the first frame.
  const faultsReadable = inputs.timing.firstIdleMs !== null;
  return {
    ...inputs,
    schema: PERF_REPORT_SCHEMA,
    faultsReadable,
    glSampleAgeMs: inputs.gl === null ? null : inputs.nowMs - inputs.gl.msSinceLoad,
    capTextureMb: inputs.gl === null ? null : Number(megabytes(inputs.gl.capTextureBytes)),
    capsClimbing: caps
      .filter((cap) => cap.rungLoading !== null)
      .map((cap) => cap.layerId.replace("polar-cap-", "")),
    faults: faultsReadable
      ? [inputs.demCacheFault, inputs.restoreFault].filter(
          (fault): fault is string => fault !== null,
        )
      : [],
  };
}

/**
 * The lines this module contributes to the on-screen panel.
 *
 * Deliberately only the facts that had NO on-screen home before — device class, tier, ladder
 * position, faults, origin. The terrain / DEM-cache / sky lines already say what they say well and
 * are left where they are; rewriting them here would trade a real improvement for churn.
 */
export function perfReportLines(report: PerfReport): PerfLine[] {
  const lines: PerfLine[] = [];

  // A verdict WITH its provenance. `no-signal` is not "desktop" and must never render as one:
  // it is the state where nothing was measured and the budget defaulted to Infinity anyway — which
  // is what `(no-signal)` says, and the reason that half is load-bearing.
  //
  // The `mobile budget` / `desktop budget` half was DELETED, and it is worth saying why it was not
  // merely shortened: it read `mobileClass ? "mobile budget" : "desktop budget"` beside a class
  // printed from the same boolean, so it restated its neighbour and carried no information at all.
  // It was worth its width when nothing else on the panel grouped by device; the DEVICE heading
  // now does that job, and the line was 67 characters against a 53-character phone budget.
  lines.push({
    group: "device",
    text:
      `${report.deviceClass.mobileClass ? "mobile-class" : "desktop-class"}` +
      ` (${report.deviceClass.via}) · tier ${report.tier}`,
  });

  // The ladder is the loudest confound in any capture: a reading taken after two rungs fired is
  // not a reading of the page as shipped, and nothing else on the panel says so.
  const rungs = [
    report.ladder.spinning ? null : "spin retired",
    report.ladder.pixelRatioLowered ? "dpr lowered" : null,
    report.ladder.terrainRetired ? "terrain retired" : null,
  ].filter((rung): rung is string => rung !== null);
  // The ladder is CONFIG, not a cost: it says which rungs have fired, i.e. which page this reading
  // is even of. `dpr lowered` changes what every number below it means.
  lines.push({
    group: "config",
    text: `ladder ${rungs.length ? rungs.join(" · ") : "unfired"} · next ${report.ladder.nextAction ?? "—"}`,
  });

  // Only when it has happened. A permanent `losses 0` is a row the eye learns to skip, and this is
  // the row that explains a globe that "keeps reloading" without the page ever reloading.
  //
  // Tagged `alarm` rather than `gpu`, so it renders above the headings with the faults. It is a
  // "this reading is compromised" warning of the same class as one, and putting it under a GPU
  // heading demotes it exactly the way grouping demotes anything.
  if (report.glLossCount > 0) {
    const since =
      report.lastGlLossMs === null
        ? ""
        : ` · last ${((report.nowMs - report.lastGlLossMs) / 1000).toFixed(0)}s ago`;
    lines.push({
      group: "alarm",
      text: `GPU CONTEXT LOST ${report.glLossCount}x this page${since}`,
    });
  }

  if (report.capTextureMb !== null) {
    const climbing = report.capsClimbing.length
      ? ` · climbing ${report.capsClimbing.join("+")}`
      : "";
    const age = report.glSampleAgeMs === null ? "" : ` (${(report.glSampleAgeMs / 1000).toFixed(0)}s old)`;
    lines.push({ group: "gpu", text: `caps ${report.capTextureMb} MB${climbing}${age}` });
  }

  // Faults get a line only when there are some. A permanent `faults none` trains the eye to skip
  // the row, which is the one row that must never be skipped. Before the first idle the checks
  // cannot mean anything, and that gets said rather than rendered as a clean bill of health.
  if (!report.faultsReadable) {
    lines.push({ group: "alarm", text: "faults not checked yet — before first idle" });
  } else if (report.faults.length) {
    lines.push({ group: "alarm", text: `FAULT ${report.faults.join(" · ")}` });
  }

  // Last, and unconditional. Whatever else is cropped out of a screenshot, the arm the numbers
  // came from should not be.
  for (const text of originLines(report.origin)) lines.push({ group: "origin", text });
  return lines;
}

/**
 * The provenance lines: server, screen and flags — everything needed to say what a number means.
 *
 * TWO lines, because the single line ran to 95 characters against a measured 53-character phone
 * budget and wrapped mid-fact. The split is at the natural seam: which SERVER produced the numbers,
 * then the geometry and flags they were produced under. Wrapping cost the same height and read
 * worse, so the second row is spent deliberately.
 */
export function originLines(origin: PerfOrigin): string[] {
  const flags = origin.flags.length ? origin.flags.join(",") : "none";
  // "DEV SERVER" in capitals on purpose: it is a warning about the numbers above it, not a label.
  const server = origin.devServer ? "DEV SERVER — absolutes not comparable to prod" : "static build";
  // Shown only when the canvas did not get what was asked for. Rounded before comparing, because
  // float noise between a requested 2 and a realised 2 is not a finding — a clamp to 1.6 is.
  const realised =
    Math.round(origin.realisedPixelRatio * 100) === Math.round(origin.devicePixelRatio * 100)
      ? ""
      : ` (realised ${origin.realisedPixelRatio.toFixed(2)} — clamped by maxCanvasSize)`;
  return [
    server,
    `${origin.viewportCssWidth}x${origin.viewportCssHeight} @ DPR ` +
      `${origin.devicePixelRatio}${realised} · flags ${flags}` +
      ` · panel ${origin.panelExpanded ? "expanded" : "collapsed"}`,
  ];
}
