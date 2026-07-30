// The report is the thing that gets exported and read a week later, so the tests here are mostly
// about what it REFUSES to do: infer an origin, present a stale sample as fresh, bill VRAM for a
// texture that is still downloading, or render "nothing was measured" as a measurement.

import { describe, expect, it } from "vitest";
import type { CapabilitySignals } from "./capability";
import type { GlLossSnapshot } from "./glDiagnostics";
import type { PerfSnapshot } from "./perfOverlay";
import {
  PERF_REPORT_SCHEMA,
  buildPerfReport,
  originLine,
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
  fps: 58,
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
    perfReportLines(buildPerfReport({ ...INPUTS, ...overrides })).join("\n");

  it("carries the device verdict WITH the signal that produced it", () => {
    expect(render()).toContain("device mobile-class (ua-client-hints) · mobile budget · tier full");
  });

  it("never renders an unmeasured device class as a desktop reading", () => {
    // `no-signal` resolves to mobileClass:false and buys the Infinity texture budget. The panel
    // has to show that the budget came from an absence, or the 512 MB looks like a decision.
    expect(render({ deviceClass: { mobileClass: false, via: "no-signal" } })).toContain(
      "device desktop-class (no-signal) · desktop budget",
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
    expect(lines[lines.length - 1]).toBe(originLine(ORIGIN));
  });
});

describe("originLine", () => {
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
