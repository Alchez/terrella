// The report is the thing that gets exported and read a week later, so the tests here are mostly
// about what it REFUSES to do: infer an origin, present a stale sample as fresh, bill VRAM for a
// texture that is still downloading, or render "nothing was measured" as a measurement.

import { describe, expect, it } from "vitest";
import type { CapabilitySignals } from "../capability";
import type { GlLossSnapshot } from "../glDiagnostics";
import type { PerfSnapshot } from "./perfOverlay";
import {
  PERF_REPORT_SCHEMA,
  buildPerfReport,
  originLines,
  perfReportLines,
  type PerfOrigin,
  type PerfReportInputs,
} from "./perfSnapshot";

const SIGNALS: CapabilitySignals = {
  webgl2: true,
  softwareGpu: false,
  performanceCaveat: false,
  saveData: false,
  slowNetwork: false,
  lowMemory: false,
  reducedMotion: false,
};

const TIMING: PerfSnapshot = {
  bootMs: 120,
  mapLoadMs: 800,
  firstIdleMs: 2400,
  longTaskCount: 12,
  longTaskTotalMs: 900,
  longTaskMaxMs: 210,
  longTaskApiAvailable: true,
  longTaskIntervals: [],
  longTaskIntervalsDropped: 0,
  fps: 58,
  // A live rate, so the retained one is the same reading at age zero — the state during a gesture.
  lastActiveFps: 58,
  lastActiveFpsAgeMs: 0,
  worstFrameMs: 90,
  slowFrameCount: 4,
  zoom: 2.5,
};

const ORIGIN: PerfOrigin = {
  href: "https://terrella.alchez.dev/globe?perf",
  devServer: false,
  userAgent: "test",
  devicePixelRatio: 2,
  realisedPixelRatio: 2,
  viewportCssWidth: 412,
  viewportCssHeight: 915,
  flags: ["perf"],
  panelExpanded: true,
};

const GL: GlLossSnapshot = {
  phase: "sampled",
  libraryVersion: "6.0.0",
  coveringTiles: 40,
  msSinceLoad: 10_000,
  cssWidth: 412,
  cssHeight: 915,
  bufferWidth: 824,
  bufferHeight: 1830,
  devicePixelRatio: 2,
  statusMessage: null,
  terrainOn: true,
  sources: [],
  caps: [
    { layerId: "polar-cap-north", loadedRungPx: 4096, rungLoading: 8192, elevLoaded: true },
    { layerId: "polar-cap-south", loadedRungPx: 4096, rungLoading: null, elevLoaded: true },
  ],
  capTextureBytes: 2 * 4096 * 4096 * 4,
};

const INPUTS: PerfReportInputs = {
  nowMs: 25_000,
  origin: ORIGIN,
  timing: TIMING,
  gl: GL,
  deviceClass: { mobileClass: true, via: "ua-client-hints" },
  signals: SIGNALS,
  tier: "full",
  probedTier: "full",
  ladder: {
    spinning: true,
    pixelRatioLowered: false,
    terrainRetired: false,
    nextAction: "retire-spin",
  },
  demCacheFault: null,
  restoreFault: null,
  glLossCount: 0,
  lastGlLossMs: null,
  traffic: {
    relief: { count: 73, wireBytes: 6_500_000, fromBrowserCache: 0 },
    terrain: { count: 24, wireBytes: 1_500_000, fromBrowserCache: 0 },
    opaqueCount: 0,
    medianNetworkDurationMs: 411,
    bufferFull: false,
  },
  fill: { movingSinceMs: null, tilesAtMoveStart: null, last: { durationMs: 11_200, tilesFetched: 97 } },
  traceSpans: [],
  longTaskIntervals: null,
  traceArmed: true,
};

describe("buildPerfReport", () => {
  it("stamps a schema, so an exported file can be read against the rules that produced it", () => {
    expect(buildPerfReport(INPUTS).schema).toBe(PERF_REPORT_SCHEMA);
  });

  it("states how old the GL sample is instead of leaving the reader to subtract", () => {
    // The sample is taken on `idle` and the report can be built long after. Presenting a stale
    // reading as a live one is the failure glDiagnostics was written to make impossible.
    expect(buildPerfReport(INPUTS).glSampleAgeMs).toBe(15_000);
  });

  it("reports NO sample as null rather than as a zeroed one", () => {
    const report = buildPerfReport({ ...INPUTS, gl: null });
    expect(report.glSampleAgeMs).toBeNull();
    expect(report.capTextureMb).toBeNull();
    expect(report.capsClimbing).toEqual([]);
  });

  it("bills only the texture actually uploaded, and names the pole still climbing", () => {
    const report = buildPerfReport(INPUTS);
    // 2 x 4096² x 4 = 128 MiB. The north pole's in-flight 8192 is NOT added: it is not on the GPU.
    expect(report.capTextureMb).toBe(128);
    expect(report.capsClimbing).toEqual(["north"]);
  });

  it("collects faults into one list a caller can test without knowing the field names", () => {
    expect(buildPerfReport(INPUTS).faults).toEqual([]);
    const broken = buildPerfReport({
      ...INPUTS,
      demCacheFault: "cap did not stick",
      restoreFault: "no painter",
    });
    expect(broken.faults).toEqual(["cap did not stick", "no painter"]);
    expect(broken.faultsReadable).toBe(true);
  });

  it("withholds the fault VERDICT before the first idle, but keeps the raw readings", () => {
    // Caught live: the panel's first run sat reading `FAULT no terrain tile manager · the style has
    // no projection` on a healthy page that had simply not finished loading. Both checks state the
    // precondition — the cache size is recomputed per render, and a loading style has no
    // projection — so a reading taken before the first frame is not a fault, it is an artefact.
    const loading = buildPerfReport({
      ...INPUTS,
      timing: { ...TIMING, firstIdleMs: null },
      demCacheFault: "no terrain tile manager",
      restoreFault: "the style has no projection",
    });
    expect(loading.faultsReadable).toBe(false);
    expect(loading.faults).toEqual([]);
    // Withheld from the verdict, NOT discarded — the export still records what was read.
    expect(loading.demCacheFault).toBe("no terrain tile manager");
    expect(loading.restoreFault).toBe("the style has no projection");
  });

  it("does not use map LOAD as the gate — `load` fires before the first frame", () => {
    // mapLoadMs being set is not enough: `updateCacheSize` runs per render, so the cap cannot have
    // been read back yet. Only an idle proves a frame happened.
    const loaded = buildPerfReport({
      ...INPUTS,
      timing: { ...TIMING, mapLoadMs: 800, firstIdleMs: null },
      demCacheFault: "cap did not stick",
    });
    expect(loaded.faultsReadable).toBe(false);
  });

  it("is pure — the same inputs twice give equal reports", () => {
    expect(buildPerfReport(INPUTS)).toEqual(buildPerfReport(INPUTS));
  });
});

describe("perfReportLines", () => {
  const render = (overrides: Partial<PerfReportInputs> = {}) =>
    perfReportLines(buildPerfReport({ ...INPUTS, ...overrides }))
      .map((line) => line.text)
      .join("\n");

  /** Which subsystem each line was filed under, in render order. */
  const groupsOf = (overrides: Partial<PerfReportInputs> = {}) =>
    perfReportLines(buildPerfReport({ ...INPUTS, ...overrides })).map((line) => line.group);

  it("carries the device verdict WITH the signal that produced it", () => {
    expect(render()).toContain("mobile-class (ua-client-hints) · tier full");
  });

  it("stays quiet about the raw probe while it agrees with what the page is running", () => {
    // Habituation is the failure mode this panel already designs against — the GPU-loss line is
    // absent until there is a loss. A permanent "(probe: full)" beside "tier full" would train the
    // reader to skip the one place the disagreement can ever appear.
    expect(render()).toContain("tier full");
    expect(render()).not.toContain("probe:");
  });

  it("prints the raw probe verdict the moment it disagrees with the running tier", () => {
    // The whole reason `probedTier` is carried separately. `decideGlobeTier` clamps a soft
    // `gallery` verdict away so it cannot reach the view bar — which also means this line is the
    // only surviving evidence that a soft signal tried to send a visitor to the gallery from a
    // page already showing them the globe. That string, `tier gallery` on a globe running at
    // 243 fps, is how the downlink defect was found; after the clamp it lives here or nowhere.
    expect(render({ tier: "globe", probedTier: "gallery" })).toContain(
      "tier globe (probe: gallery)",
    );
  });

  it("never renders an unmeasured device class as a desktop reading", () => {
    // `no-signal` resolves to mobileClass:false and buys the Infinity texture budget. The panel
    // has to show that the budget came from an absence, or the 512 MB looks like a decision.
    // `(no-signal)` is what carries this, and it is why the redundant "desktop budget" could go:
    // that half was printed from the same boolean as the class beside it.
    expect(render({ deviceClass: { mobileClass: false, via: "no-signal" } })).toContain(
      "desktop-class (no-signal) · tier full",
    );
  });

  it("says the ladder is unfired, rather than saying nothing", () => {
    // Silence here would be read as "no ladder", and a capture taken after two rungs fired is not
    // a capture of the page as shipped.
    expect(render()).toContain("ladder unfired · next retire-spin");
  });

  it("names every rung that has fired, and that the ladder is exhausted", () => {
    const line = render({
      ladder: {
        spinning: false,
        pixelRatioLowered: true,
        terrainRetired: true,
        nextAction: null,
      },
    });
    expect(line).toContain("spin retired");
    expect(line).toContain("dpr lowered");
    expect(line).toContain("terrain retired");
    expect(line).toContain("next —");
  });

  it("shows a fault line only when there is a fault", () => {
    // A permanent `faults none` row trains the eye to skip the one row that must not be skipped.
    expect(render()).not.toContain("FAULT");
    expect(render({ demCacheFault: "cap not enforced" })).toContain("FAULT cap not enforced");
  });

  it("names a context-loss loop, which nothing else on the panel can", () => {
    // The symptom that motivated this: a phone reported the globe "reloading every so often" while
    // `nowMs` ran monotonically, proving the PAGE never reloaded. A map rebuilding after a
    // recovered loss leaves no trace once the notice comes down — the count is the only witness.
    expect(render()).not.toContain("GPU CONTEXT LOST");
    const looping = render({ nowMs: 26_000, glLossCount: 4, lastGlLossMs: 21_000 });
    expect(looping).toContain("GPU CONTEXT LOST 4x this page · last 5s ago");
  });

  it("still reports the count when the timestamp is missing, rather than dropping the line", () => {
    expect(render({ glLossCount: 2, lastGlLossMs: null })).toContain("GPU CONTEXT LOST 2x");
  });

  it("says the checks have not run yet, instead of implying a clean page", () => {
    const loading = render({
      timing: { ...TIMING, firstIdleMs: null },
      demCacheFault: "no terrain tile manager",
    });
    expect(loading).toContain("faults not checked yet — before first idle");
    expect(loading).not.toContain("FAULT");
  });

  it("always ends with the origin, whatever else is on the panel", () => {
    const lines = perfReportLines(buildPerfReport(INPUTS));
    expect(lines.slice(-2).map((line) => line.text)).toEqual(originLines(ORIGIN));
    expect(lines.slice(-2).every((line) => line.group === "origin")).toBe(true);
  });

  it("files the two alarm rows OUTSIDE any subsystem, so no heading can demote them", () => {
    // Both are "this reading is compromised", not readings. A GPU context loss is filed with the
    // faults rather than under GPU · MEMORY for exactly that reason: a heading is what teaches the
    // eye to skip a block, and these are the rows that must never be skipped.
    expect(groupsOf({ nowMs: 26_000, glLossCount: 4, lastGlLossMs: 21_000 })).toEqual([
      "device",
      "config",
      "cpu",
      "alarm",
      "gpu",
      "origin",
      "origin",
    ]);
    expect(groupsOf({ demCacheFault: "cap not enforced" })).toContain("alarm");
    expect(groupsOf({ timing: { ...TIMING, firstIdleMs: null } })).toContain("alarm");
  });

  it("files the ladder as CONFIG and the cap textures as GPU VRAM", () => {
    // The ladder says which page this reading is even OF — `dpr lowered` changes the meaning of
    // every number beside it — while the cap figure is a cost with an owner, and that owner is the
    // GPU. The DEM cache is NOT in this list: it is heap bytes, tagged `ram` at its own call site.
    expect(groupsOf()).toEqual(["device", "config", "cpu", "gpu", "origin", "origin"]);
  });

  it("always states the unattributed remainder, so the breakdown cannot read as complete", () => {
    // No span can wrap MapLibre's internals or a driver stall. A spans list printed without its
    // remainder would claim to account for the blocked time while accounting for part of it.
    const lines = perfReportLines(
      buildPerfReport({
        ...INPUTS,
        traceSpans: [{ name: "caps:decode", startTime: 0, duration: 300 }],
        longTaskIntervals: [{ startMs: 0, endMs: 1000 }],
      }),
    );
    const cpu = lines.filter((line) => line.group === "cpu").map((line) => line.text);
    expect(cpu.some((text) => text.includes("caps:decode 300 ms ×1"))).toBe(true);
    // 900 comes from `timing.longTaskTotalMs`, NOT from the interval passed in: the observer
    // replays with `buffered: true`, so its total outranks any window this call happens to hold.
    expect(cpu.some((text) => text.includes("unattributed 600 ms"))).toBe(true);
  });

  it("distinguishes an instrument that never armed from one that found nothing", () => {
    // A browser without User Timing records no spans. Printing the ordinary empty breakdown would
    // make that indistinguishable from a session where the traced work genuinely never ran — the
    // same lie the `long tasks n/a` line already exists to prevent one field over.
    const lines = perfReportLines(buildPerfReport({ ...INPUTS, traceArmed: false }));
    expect(lines.filter((line) => line.group === "cpu").map((line) => line.text)).toEqual([
      "spans not armed — no User Timing in this browser",
    ]);
  });

  it("flags a PARTIAL attribution when long-task windows were dropped", () => {
    // Dropping windows biases the remainder upward — toward blaming code we did not write. The
    // reading must say it is partial rather than let the bias pass as a finding.
    const lines = perfReportLines(
      buildPerfReport({
        ...INPUTS,
        timing: { ...TIMING, longTaskIntervalsDropped: 12 },
        traceSpans: [{ name: "caps:decode", startTime: 0, duration: 100 }],
        longTaskIntervals: [{ startMs: 0, endMs: 100 }],
      }),
    );
    expect(lines.some((line) => line.text.includes("PARTIAL, 12 windows dropped"))).toBe(true);
  });

  it("says the spans are UNPRICED rather than reporting a zero remainder", () => {
    // Two cases reach this line — Firefox, which has no Long Tasks API at all, and a build whose
    // spans are not yet placed. A `0 ms unattributed` in either would read as a fully explained
    // session, so the wording blames neither the browser nor the reader.
    const lines = perfReportLines(buildPerfReport({ ...INPUTS, longTaskIntervals: null }));
    expect(lines.filter((line) => line.group === "cpu").map((line) => line.text)).toEqual([
      "spans unpriced — no long-task windows to attribute against",
    ]);
  });
});

/** The two provenance rows joined the way they used to be one row, so every assertion below
 *  stays about WORDING — the split is asserted once, on its own, above. */
const originLine = (origin: PerfOrigin) => originLines(origin).join(" · ");

describe("originLines", () => {
  it("splits the server warning from the geometry, so neither wraps on a phone", () => {
    // 95 characters against a measured 53-character budget: it wrapped mid-fact.
    const [server, geometry] = originLines({ ...ORIGIN, devServer: true });
    expect(server).toBe("DEV SERVER — absolutes not comparable to prod");
    expect(geometry).toContain("412x915 @ DPR 2");
    expect(Math.max(server.length, geometry.length)).toBeLessThanOrEqual(53);
  });

  it("shouts when the numbers came from the dev server", () => {
    // Three exchanges were spent quoting dev-server phone numbers as if they were production.
    // The warning belongs ON the reading, not in someone's memory of how it was taken.
    expect(originLine({ ...ORIGIN, devServer: true })).toContain("DEV SERVER");
    expect(originLine({ ...ORIGIN, devServer: true })).toContain("not comparable to prod");
  });

  it("labels a real build as a build, rather than staying silent", () => {
    expect(originLine(ORIGIN)).toContain("static build");
    expect(originLine(ORIGIN)).not.toContain("DEV SERVER");
  });

  it("flags a ratio the canvas did NOT get, and stays quiet when it did", () => {
    // MapLibre's own .d.ts: "the pixel ratio actually applied may be lower to respect
    // maxCanvasSize" (default 4096). Measured live — a 2560 px canvas asked for ratio 2 reported
    // DPR 2 while its buffer was 4096 wide, a realised 1.6; any DPR-2 display wider than 2048 CSS
    // px hits it. A panel showing the REQUEST as though it were the render is the failure this
    // whole report exists to prevent.
    expect(originLine(ORIGIN)).not.toContain("realised");
    const clamped = originLine({ ...ORIGIN, devicePixelRatio: 2, realisedPixelRatio: 1.6 });
    expect(clamped).toContain("@ DPR 2 (realised 1.60 — clamped by maxCanvasSize)");
  });

  it("records whether the INSTRUMENT was displaying — the variable that invalidated two nights", () => {
    // The expanded panel used to re-probe capabilities every 300 ms, creating WebGL contexts fast
    // enough to force-lose the map's own. Nothing in the exported file said which state it was in,
    // so two runs differing only in that were compared as one experiment. An observer effect you
    // cannot see in the data is one you cannot rule out.
    expect(originLine(ORIGIN)).toContain("panel expanded");
    expect(originLine({ ...ORIGIN, panelExpanded: false })).toContain("panel collapsed");
  });

  it("does not cry clamp over float noise", () => {
    expect(originLine({ ...ORIGIN, realisedPixelRatio: 2.0000001 })).not.toContain("realised");
  });

  it("records the viewport, the ratio and the flags that shaped the numbers", () => {
    expect(originLine(ORIGIN)).toContain("412x915 @ DPR 2");
    expect(originLine({ ...ORIGIN, flags: ["nocaps", "perf"] })).toContain("flags nocaps,perf");
    expect(originLine({ ...ORIGIN, flags: [] })).toContain("flags none");
  });
});
