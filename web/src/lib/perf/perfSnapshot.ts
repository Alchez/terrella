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
import type { RttPoolStats } from "../rttPoolTrim";
import type { TimelineSample } from "./perfTimeline";
import type { SpanEntry } from "../perfSpans";
import { megabytes } from "../format";
import { summariseSpans, type Interval, type TraceSummary } from "./perfTrace";

/** Bumped when a field changes meaning, so an exported file can be read against the right rules.
 *
 *  2 adds `traffic` and `fill`. Additive, so a v1 file still reads correctly — but the bump earns its keep by
 *  making the absence explicit: a v1 export cannot say whether its byte and timing numbers were
 *  cold or warm, and that ambiguity is exactly what caused two misreadings on 2026-07-30.
 *
 *  3 adds `trace`: named spans, and the share of blocked time they do and do not explain. A v2 file
 *  carries long-task totals with no attribution at all, so the two cannot be compared on "how much
 *  of this was ours" — the absence is the point of the bump again.
 *
 *  4 narrows what `traffic.relief` MEANS. In a v3 export it was the fall-through: anything under
 *  the tile base that did not start `terrain/` counted as relief, including entries that are no
 *  tile at all. It is now what the tile servers' own parser calls relief, with `countries` and
 *  `unaddressedCount` as the answers it used to absorb. The field did not move, so nothing about a
 *  v3 file looks different — which is exactly why the number has to say so.
 *
 *  How much this changed in practice is MEASURED, not assumed: on the live globe, all 407 tile
 *  entries were `img`-initiated raster, so a v3 relief count was inflated only by whatever failed
 *  to parse. Vector tiles are fetched from MapLibre's worker and never reach this buffer at all.
 *
 *  5 gives `origin.flags` its VALUES. Up to v4 the field held bare keys, so two arms of the same
 *  sweep that differed only in what a flag was set TO — the ordinary case for a valued flag —
 *  produced byte-identical origins. `href` still separated them in an exported file, but the panel
 *  never prints `href`, so the arm was unrecoverable from the screenshot that is this instrument's
 *  whole reason for existing on a phone. See {@link describeFlags}.
 *
 *  6 adds `rttPool`, and with it the renderable terrain tile count. That census already existed and
 *  was formatted straight onto the panel, so it reached a human's glance and never the exported
 *  file — a report was readable by eye and unparseable by a harness on the one quantity that
 *  multiplies every per-tile cost the profiler attributes. A v5 file carries no tile count at all,
 *  which is the absence the bump makes explicit.
 *
 *  7 adds `timeline`: the same terms sampled over time rather than at the instant of export, plus
 *  GPU bytes where the dev-only accounting library is attached. A v6 file can say the pool is large
 *  and cannot say whether it is growing, which is the question every reading of it actually asks.
 *  It also carries `timelineMarkMs`, the moment a reader chose to measure from — a MARK rather than
 *  a reset, because the cumulative frame fields are deliberately never cleared. */
export const PERF_REPORT_SCHEMA = 7;

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
  /** Diagnostic flags in effect, as {@link describeFlags} renders them: `nocaps`, `demcache=off`. */
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

/**
 * Render the query string as the flag list {@link PerfOrigin.flags} carries.
 *
 * A bare flag stays a bare key; a flag with a value becomes `key=value`. That distinction is the
 * whole point of the function: this page's diagnostic flags are mostly VALUED (`?maxreq=`,
 * `?skirt=`, `?terrain=`, `?lod=`), and a list of keys says two arms of a sweep were configured
 * identically when the values are the only thing that differed between them.
 *
 * An empty value reads as bare — `?perf` and `?perf=` mean the same thing to every parser on this
 * page, so they must not describe differently. Repeated keys yield one entry each rather than being
 * collapsed, because `URLSearchParams` hands the whole list to whoever reads it and the last-wins
 * behaviour a reader might assume is not universal.
 *
 * Values are NOT truncated. A long one wraps the panel, which is a legibility cost; a shortened one
 * is a false record, which is the class of defect the schema note above exists to stop.
 */
export function describeFlags(params: URLSearchParams): string[] {
  const described: string[] = [];
  for (const key of new Set(params.keys())) {
    const values = params.getAll(key).filter((value) => value.trim() !== "");
    if (values.length === 0) described.push(key);
    else for (const value of values) described.push(`${key}=${value}`);
  }
  return described.toSorted();
}

/** How far down the FPS degradation ladder this page has walked. */
export interface LadderPosition {
  spinning: boolean;
  pixelRatioLowered: boolean;
  terrainRetired: boolean;
  /** What the ladder would pull next; null means exhausted. */
  nextAction: DegradationAction;
  /** Frame intervals currently under judgement.
   *
   *  Carried because `nextAction` alone cannot distinguish the two states that matter most on a
   *  struggling page: a ladder poised on a rung it is about to pull, and one poised on a rung it
   *  will never reach because nothing is feeding its window. Both print the same action, and the
   *  second is the defect this field exists to make visible — it read `disable-terrain` for 55 s
   *  at the cliff while collecting nothing. */
  samples: number;
  /** Consecutive frames over `CATASTROPHIC_FRAME_MS`, i.e. how far into a stall the page is. */
  slowRun: number;
}

export interface PerfReportInputs {
  nowMs: number;
  origin: PerfOrigin;
  timing: PerfSnapshot;
  /** The last healthy `idle` sample, or null before the first one lands. */
  gl: GlLossSnapshot | null;
  deviceClass: DeviceClass;
  signals: CapabilitySignals;
  /** The tier the page is actually running at — `decideGlobeTier`, so never `gallery` for a soft
   *  signal. This is the one that describes behaviour. */
  tier: Tier;
  /** What the raw probe said before the globe-page clamp, i.e. `decideTier`. Carried SEPARATELY
   *  and on purpose: the clamp is what stops a contradiction reaching the view bar, and it is
   *  therefore also what would stop anyone ever seeing the contradiction again. `tier gallery` on
   *  a globe running at 243 fps is how the downlink defect was found, and after the clamp that
   *  string only exists here. An instrument that reports the corrected value is an instrument that
   *  cannot find the next one of these. */
  probedTier: Tier;
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
  /**
   * Named spans recorded since page setup, and the long-task windows to price them against.
   *
   * Raw rather than pre-summarised, so the report — not the caller — owns the arithmetic that
   * decides what "attributed" means. `longTaskIntervals` is null where the Long Tasks API is
   * absent (Firefox), which is exactly the browser the spans exist to serve: the spans still
   * report, and the report declines to invent a remainder it cannot compute.
   */
  traceSpans: readonly SpanEntry[];
  longTaskIntervals: readonly Interval[] | null;
  /**
   * The RTT pool census, whose `renderable` is the tile count every per-tile cost multiplies.
   *
   * Null when terrain never came up, which is distinct from a census reading zero: one says the arm
   * had no terrain, the other says terrain is on and drawing nothing, and an arm read as a win
   * because it was silently terrain-less is the confound this field exists to rule out.
   */
  rttPool: RttPoolStats | null;
  /**
   * Whether span tracing actually armed.
   *
   * Separate from "there are no spans", and the distinction is the whole point: a browser without
   * User Timing records nothing, and an empty list from an instrument that never ran is
   * indistinguishable from a session where the traced work genuinely never happened.
   */
  traceArmed: boolean;
  /**
   * The last two minutes of the pool model's terms, oldest first.
   *
   * The rest of this report is a MOMENT, and the two costliest defects this instrument has been
   * pointed at were trajectories: an unbounded RTT pool, and a terrain tile set that inflates under
   * a drag and not under a scripted pan. `renderable: 4999` and `renderable: 35` are equally
   * plausible as single readings — only the series says which way it was going, and reconstructing
   * one previously meant a throwaway script.
   *
   * Empty is a real state (a capture taken before the first tick), not a fault.
   */
  timeline: TimelineSample[];
  /**
   * When the reader marked a moment to measure from, or null if they never did.
   *
   * The INSTRUMENT'S OWN STATE is part of the reading — the same argument `panelExpanded` exists
   * for. A capture whose panel was showing a since-mark figure and one showing only cumulative
   * numbers are different readings of the same session, and nothing else in the file distinguishes
   * them.
   */
  timelineMarkMs: number | null;
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
  /** Span totals, plus how much of the blocked time they explain. See `perfTrace`. */
  trace: TraceSummary;
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
    trace: summariseSpans(
      inputs.traceSpans,
      inputs.longTaskIntervals,
      inputs.longTaskIntervals === null ? null : inputs.timing.longTaskTotalMs,
    ),
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
  // The probe's raw verdict is appended ONLY when it disagrees with what the page is running. A
  // permanent `(probe: globe)` beside `tier globe` is the habituation this panel already refuses
  // elsewhere — the GPU-loss line is absent until there is a loss, for the same reason. Here the
  // disagreement is the whole signal: it means a soft demotion tried to send a visitor to the
  // gallery from a page already showing them the globe.
  const probeDisagrees = report.probedTier !== report.tier;
  lines.push({
    group: "device",
    text:
      `${report.deviceClass.mobileClass ? "mobile-class" : "desktop-class"}` +
      ` (${report.deviceClass.via}) · tier ${report.tier}` +
      (probeDisagrees ? ` (probe: ${report.probedTier})` : ""),
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
  //
  // THE SAMPLE COUNT IS PRINTED BESIDE THE NEXT ACTION BECAUSE THE ACTION ALONE IS AMBIGUOUS in
  // exactly the case worth catching. `next disable-terrain` describes both a ladder about to pull
  // that rung and one that will never pull it because nothing is feeding its window, and the
  // second read `next disable-terrain` for 55 s on a page at 1 fps. `· 0 frames` is what tells
  // those apart on sight; a stall in progress shows its run length instead.
  const windowText =
    report.ladder.slowRun > 0
      ? `${report.ladder.samples} frames · ${report.ladder.slowRun} stalled`
      : `${report.ladder.samples} frames`;
  lines.push({
    group: "config",
    text: `ladder ${rungs.length ? rungs.join(" · ") : "unfired"} · next ${report.ladder.nextAction ?? "—"} · ${windowText}`,
  });

  // Attribution, and the line that keeps it honest. No span can wrap MapLibre's internals or a
  // driver stall, so a breakdown printed WITHOUT its remainder would read as a complete account of
  // the blocked time while being nothing of the sort. The remainder is therefore not optional, and
  // it says "unavailable" rather than 0 where there is no long-task total to subtract from.
  if (!report.traceArmed) {
    lines.push({ group: "cpu", text: "spans not armed — no User Timing in this browser" });
  } else {
    if (report.trace.spans.length > 0) {
      const top = report.trace.spans
        .slice(0, 3)
        .map((span) => `${span.name} ${Math.round(span.totalMs)} ms ×${span.count}`)
        .join(" · ");
      lines.push({ group: "cpu", text: `spans ${top}` });
    }
    // A dropped WINDOW costs attribution detail, never the blocked headline — but it biases the
    // remainder upward, i.e. toward blaming code we did not write. Say so rather than let a
    // partial reading pass as a whole one.
    const dropped = report.timing.longTaskIntervalsDropped;
    const partial = dropped > 0 ? ` · PARTIAL, ${dropped} windows dropped` : "";
    lines.push({
      group: "cpu",
      text:
        report.trace.unattributedMs === null
          ? "spans unpriced — no long-task windows to attribute against"
          : `blocked ours ${Math.round(report.trace.attributedMs)} ms · unattributed ` +
            `${Math.round(report.trace.unattributedMs)} ms${partial}`,
    });
  }

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
