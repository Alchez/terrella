// On-screen performance overlay for /globe?perf — phones have no devtools console, so the
// numbers render into a corner panel the user can screenshot. Long tasks (main-thread blocks
// >50 ms, the Long Tasks API) are the jank currency: their count/total/max during the first
// seconds attribute "it lags" to real main-thread stalls, while map load / first idle separate
// download completion from responsiveness. Combined with the layer-stripping flags (?nocaps,
// ?bare) the differences between reloads attribute the stalls to a subsystem. Firefox implements
// no Long Tasks API at all, so that line reports its own absence rather than a zero — see
// longTaskApiSupported.

import type { Map as MaplibreMap } from "maplibre-gl";

/** Map-event stamps recorded by the PAGE at map construction (globe.astro), not by this
 *  module: the overlay is dynamically imported and loses the race on fast (prod-built)
 *  pages — "load" can fire before the module mounts, and the idle-triggered spin then
 *  keeps the map from ever idling again. The page fills this live object; the overlay
 *  only reads it. */
export interface PerfEventStamps {
  mapLoadMs: number | null;
  firstIdleMs: number | null;
}

export interface PerfSnapshot {
  /**
   * `performance.now()` at overlay mount — a TIMESTAMP on the navigation clock, not a duration,
   * and the same clock `mapLoadMs` and `firstIdleMs` are stamped from.
   *
   * This used to claim it was "the JS startup cost paid before the map exists". The second half is
   * false and production falsified it: the overlay arrives as a lazy chunk, so on a warm cache the
   * map can load first — measured `bootMs` 1504.4 against `mapLoadMs` 1494.8 on the same run.
   * `mapLoadMs - bootMs` is therefore not a phase duration and goes negative; the long-task totals
   * are unaffected either way, because the observer replays with `buffered: true`.
   */
  bootMs: number;
  mapLoadMs: number | null;
  firstIdleMs: number | null;
  longTaskCount: number;
  longTaskTotalMs: number;
  longTaskMaxMs: number;
  longTaskApiAvailable: boolean;
  /** Rendered frames per second over the last FPS_WINDOW_MS, or null when the map is idle. */
  fps: number | null;
  /**
   * The most recent non-null `fps`, kept after the map goes idle. Null until the map has drawn
   * two frames in one window.
   *
   * Exists because the two things a reader is told to do before exporting are otherwise mutually
   * exclusive. Letting the map settle is what makes the GL sample current — and settling is
   * exactly what drops `fps` to null, so the frame rate for the gesture just performed is gone at
   * the moment it gets written down. Measured on production: three phone runs, and the only one
   * carrying an `fps` was the one exported mid-pan, whose GL sample was 25.7 s stale in exchange.
   *
   * `fps` itself stays honest and still reads null when idle. This is a SECOND field rather than a
   * retained value in the first, because a rate presented as live while nothing is drawing is the
   * class of lie this module exists to prevent.
   */
  lastActiveFps: number | null;
  /** How long ago `lastActiveFps` was measured. Zero while the map is still drawing, and the
   *  reason the retained value cannot masquerade as a live one — same contract as
   *  `glSampleAgeMs` in the report. Null when there is no reading to date. */
  lastActiveFpsAgeMs: number | null;
  /** Longest genuine frame interval since the map became usable — what "janky" means. A mean
   *  hides a single 120 ms stall; this is the number that matches the feeling. Deliberately
   *  cumulative and never cleared: the hitch happens during a gesture and the screenshot is
   *  taken after it, by which point a windowed reading has already dropped it. */
  worstFrameMs: number | null;
  /** Frames slower than SLOW_FRAME_MS over the same span. Reported BESIDE the max because a max
   *  alone cannot be interpreted: one interrupted frame — a screenshot, the URL bar, the
   *  notification shade — pauses rAF and lands as a 400 ms "worst frame" that no amount of
   *  rendering work explains. `worst 428 ms · slow 1` is that artifact; `worst 90 ms · slow 24`
   *  is real jank. The pair is self-diagnosing where either number alone misleads. */
  slowFrameCount: number;
  /** Live camera zoom, so a screenshot says where it was taken. */
  zoom: number;
}

/** Whether this browser implements the Long Tasks API.
 *
 *  Feature-tested rather than try/caught, because **Firefox does not throw on an unsupported entry
 *  type**: `observe({type: "longtask"})` logs "Ignoring unsupported entryTypes: longtask" to the
 *  console and returns normally. A try/catch therefore leaves the panel printing a confident
 *  `long tasks 0 · 0 ms total · 0 ms max` from an observer that never registered — and a zero from
 *  an instrument that never ran is indistinguishable from a genuinely clean main thread. That is
 *  not hypothetical: it was read as proof a stall was *not* on the main thread, in a browser where
 *  the number could never have been anything but zero.
 *
 *  Takes the constructor as an argument so the unsupported branch is testable without stubbing a
 *  global.
 */
export function longTaskApiSupported(
  observerConstructor: typeof PerformanceObserver | undefined = globalThis.PerformanceObserver,
): boolean {
  const supported = observerConstructor?.supportedEntryTypes;
  return Array.isArray(supported) && supported.includes("longtask");
}

/** A frame this slow is visible as a hitch. Matched to the Long Tasks threshold so the two
 *  lines of the panel are commensurable — and it is ~3 dropped frames at 60 Hz, ~6 at 120. */
export const SLOW_FRAME_MS = 50;

/** Rolling window for the frame-rate readout. One second is long enough to be stable at 60 Hz
 *  and short enough that a stall is still visible when the screenshot is taken. */
export const FPS_WINDOW_MS = 1000;

/** Frames per second from render timestamps, newest last, relative to `now`.
 *
 *  Returns null when the window holds fewer than two frames. That is the honest reading of an
 *  idle map rather than a zero: MapLibre renders on demand, so "no frames" means nothing needed
 *  drawing, not that drawing was slow.
 */
export function frameRate(
  stamps: readonly number[],
  now: number,
  windowMs: number = FPS_WINDOW_MS,
): number | null {
  const recent = stamps.filter((stamp) => now - stamp <= windowMs);
  if (recent.length < 2) return null;
  const span = recent[recent.length - 1] - recent[0];
  if (span <= 0) return null;
  return Math.round(((recent.length - 1) / span) * 1000);
}

/** The last rate measured while the map was actually drawing, and when. */
export interface RetainedFrameRate {
  fps: number | null;
  /** On the same clock as the tick that recorded it. Null while there is nothing to date. */
  measuredAtMs: number | null;
}

/**
 * Carry the last active rate across an idle map.
 *
 * Pure, and extracted rather than left inline in the tick for the reason every other helper here
 * was: nothing mounts the overlay in a test, so logic inside `mountPerfOverlay` is logic no test
 * can reach. An earlier version of this lived in the tick, and a deliberate sabotage of its
 * condition went completely uncaught.
 */
export function retainFrameRate(
  retained: RetainedFrameRate,
  liveFps: number | null,
  nowMs: number,
): RetainedFrameRate {
  return liveFps === null ? retained : { fps: liveFps, measuredAtMs: nowMs };
}

/**
 * The genuine frame interval ending at `stampMs`, or null when there wasn't one.
 *
 * The rule that makes both readings mean anything: a gap between two renders is a slow FRAME only
 * if the map was trying to draw across it. MapLibre renders on demand, so the gap between the
 * last render of a gesture and the first render of the next one is idleness — counting it would
 * put a 3-second "worst frame" on screen every time someone stopped to look at the map. `idle`
 * fires exactly at that boundary, so a gap that spans one is discarded.
 *
 * A null `previousStampMs` means this is the first render, so there is no interval yet.
 */
export function frameInterval(
  previousStampMs: number | null,
  stampMs: number,
  spannedIdle: boolean,
): number | null {
  if (previousStampMs === null || spannedIdle) return null;
  const interval = stampMs - previousStampMs;
  return interval > 0 ? interval : null;
}

/** Running state behind the persisted frame readings. Kept out of the mount closure so the
 *  rules can be tested without a DOM — this module's only browser dependency is the panel. */
export interface FrameTracker {
  peakMs: number | null;
  slowCount: number;
  previousStampMs: number | null;
  idleSinceLastRender: boolean;
  seenFirstIdle: boolean;
}

export function newFrameTracker(): FrameTracker {
  return {
    peakMs: null,
    slowCount: 0,
    previousStampMs: null,
    idleSinceLastRender: false,
    seenFirstIdle: false,
  };
}

export function onRender(tracker: FrameTracker, stampMs: number): FrameTracker {
  const interval = frameInterval(tracker.previousStampMs, stampMs, tracker.idleSinceLastRender);
  const peakMs =
    interval === null
      ? tracker.peakMs
      : tracker.peakMs === null
        ? interval
        : Math.max(tracker.peakMs, interval);
  return {
    peakMs,
    slowCount: tracker.slowCount + (interval !== null && interval > SLOW_FRAME_MS ? 1 : 0),
    previousStampMs: stampMs,
    idleSinceLastRender: false,
    seenFirstIdle: tracker.seenFirstIdle,
  };
}

/**
 * The map has finished drawing everything it wanted to.
 *
 * The FIRST idle also clears the peak, so the reading means "worst frame since the map became
 * usable". Loading reliably produces the slowest frame of the session — style parse, first tile
 * decodes — and leaving it in place sets a floor that hides every later hitch beneath it. That
 * cost is not lost: it is exactly what the long-task line measures.
 */
export function onIdle(tracker: FrameTracker): FrameTracker {
  return {
    ...tracker,
    idleSinceLastRender: true,
    peakMs: tracker.seenFirstIdle ? tracker.peakMs : null,
    slowCount: tracker.seenFirstIdle ? tracker.slowCount : 0,
    seenFirstIdle: true,
  };
}

/** Below this CSS width the panel starts collapsed. A phone screen is ~390–430 px wide, and a
 *  ten-line panel over a globe is a panel that gets dismissed rather than read. */
export const NARROW_VIEWPORT_PX = 640;

/** Pure, so the "does it cover the map" decision is testable without a viewport. */
export function startsCollapsed(viewportCssWidth: number): boolean {
  return viewportCssWidth < NARROW_VIEWPORT_PX;
}

/**
 * The two lines worth showing when the panel is collapsed.
 *
 * Chosen as the pair that answers "is it janky, and is the main thread why" — the question every
 * session starts with. Everything else is one tap away, and the export carries all of it regardless
 * of what is on screen, so nothing is lost by collapsing.
 */
export function perfCollapsedLines(snapshot: PerfSnapshot): string[] {
  const ms = (value: number | null) => (value === null ? "—" : `${Math.round(value)} ms`);
  const rate = snapshot.fps === null ? "fps —" : `fps ${snapshot.fps}`;
  const tasks = snapshot.longTaskApiAvailable
    ? `blocked ${ms(snapshot.longTaskTotalMs)} in ${snapshot.longTaskCount}`
    : "blocked n/a";
  return [
    `${rate} · worst ${ms(snapshot.worstFrameMs)} · slow ${snapshot.slowFrameCount}`,
    `${tasks} · z${snapshot.zoom.toFixed(2)}`,
  ];
}

/** Pure formatter, unit-tested: null renders as an em-dash, times round to whole ms. */
export function perfSummaryLines(snapshot: PerfSnapshot): string[] {
  const ms = (value: number | null) => (value === null ? "—" : `${Math.round(value)} ms`);
  const lines = [
    `boot ${ms(snapshot.bootMs)}`,
    `map load ${ms(snapshot.mapLoadMs)} · first idle ${ms(snapshot.firstIdleMs)}`,
  ];
  if (snapshot.longTaskApiAvailable) {
    lines.push(
      `long tasks ${snapshot.longTaskCount} · ${ms(snapshot.longTaskTotalMs)} total · ${ms(snapshot.longTaskMaxMs)} max`,
    );
  } else {
    // Names the browser as the reason, so this cannot be read as "the observer failed to mount"
    // — and above all cannot be confused with a measured zero.
    lines.push("long tasks n/a — no Long Tasks API in this browser");
  }
  // Worst and slow both show in either state, because they survive the gesture that produced them.
  // An idle map reports the rate it last drew at, dated — never as though it were current, and
  // never in place of saying it is idle.
  const seconds = (value: number) => `${(value / 1000).toFixed(0)}s`;
  const idle =
    snapshot.lastActiveFps === null || snapshot.lastActiveFpsAgeMs === null
      ? "fps — (idle)"
      : `fps — (idle · was ${snapshot.lastActiveFps}, ${seconds(snapshot.lastActiveFpsAgeMs)} ago)`;
  const rate = snapshot.fps === null ? idle : `fps ${snapshot.fps}`;
  lines.push(
    `${rate} · worst ${ms(snapshot.worstFrameMs)} · slow ${snapshot.slowFrameCount}` +
      ` · z${snapshot.zoom.toFixed(2)}`,
  );
  return lines;
}

/** Where a snapshot POST goes. Same-origin and dev-only by design — see the endpoint's own
 *  comment in astro.config.ts for why this is not configurable. */
export const PERF_EXPORT_PATH = "/__perf";

/** What the export did, rendered onto the button so a phone with no console still gets an answer.
 *  Every branch is a distinct string: "it silently did nothing" must not be reachable. */
export type PerfExportOutcome = "saved" | "copied" | "failed";

/**
 * Send the report somewhere the reader can actually get at it.
 *
 * Two paths because there are two situations. On the dev server a POST lands in `web/.perf/` and
 * can be read straight off disk — which is the whole point, since the alternative has been
 * transcribing numbers from a photograph of a phone screen. On a static build there is no endpoint,
 * so the report goes to the clipboard instead and the reader pastes it. The clipboard is the
 * FALLBACK rather than the default because it needs a user gesture and a secure context, and
 * because `navigator.clipboard` is simply absent over plain http on a LAN address — which is
 * exactly where the phone runs.
 *
 * Dependencies are injected so both branches and both failures are testable.
 */
export async function exportPerfReport(options: {
  report: unknown;
  fetchFn?: typeof fetch;
  writeClipboard?: (text: string) => Promise<void>;
  path?: string;
}): Promise<PerfExportOutcome> {
  const body = JSON.stringify(options.report, null, 2);
  try {
    const response = await options.fetchFn?.(options.path ?? PERF_EXPORT_PATH, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
    });
    if (response?.ok) return "saved";
  } catch {
    // A missing endpoint is the ORDINARY case in production, not an error worth surfacing.
  }
  try {
    await options.writeClipboard?.(body);
    return options.writeClipboard ? "copied" : "failed";
  } catch {
    return "failed";
  }
}

/** Mount the overlay and start observing. Buffered observation is load-bearing: the heaviest
 *  long tasks (JS parse/eval, first JSON.parse) happen BEFORE this module loads, and
 *  `buffered: true` replays them into the observer. Map-event timing comes from
 *  `eventStamps` when the page provides it (see PerfEventStamps); own listeners are the
 *  fallback for callers that don't. */
export interface PerfOverlayOptions {
  eventStamps?: PerfEventStamps;
  /** Both callbacks receive the LIVE snapshot this module owns, rather than the page keeping its
   *  own copy of the long-task and frame counters. One number, one owner: a panel line and an
   *  exported file taken in the same moment cannot then disagree. */
  extraLines?: (timing: PerfSnapshot) => string[];
  /** Called on export, at the moment of the tap, so the report carries the state the reader is
   *  looking at rather than the state at mount. Absent means the export control is not offered —
   *  a button that produces nothing is worse than no button.
   *
   *  `panel.expanded` is handed over because the INSTRUMENT'S OWN STATE is part of the reading:
   *  an expanded panel does strictly more work than a collapsed one, and a file that does not say
   *  which it was cannot rule out an observer effect. One already happened. */
  buildReport?: (timing: PerfSnapshot, panel: { expanded: boolean }) => unknown;
}

export function mountPerfOverlay(map: MaplibreMap, options: PerfOverlayOptions = {}): void {
  const { eventStamps, extraLines, buildReport } = options;

  // A seam for scripted diagnosis: without a map handle, a driven browser can reach the camera only
  // through synthetic gestures or hash jumps, and an A/B whose arms cannot be given the identical
  // camera route is the confound this project keeps paying for.
  //
  // It lives HERE, not in globe.astro, and that is what gates it. This module is dynamically
  // imported inside the `?perf` branch alone, so an ordinary visit never downloads it, let alone
  // runs this line — the module boundary IS the gate, and no edit to a page can accidentally widen
  // it. The first version sat in globe.astro behind the flag with a test asserting the assignment
  // appeared within the flag block's text span; a sabotage that moved it out of the block while
  // leaving it inside the span passed that test cleanly. A guard that matches a region cannot
  // decide what encloses a statement.
  (window as unknown as { terrellaMap?: MaplibreMap }).terrellaMap = map;
  const snapshot: PerfSnapshot = {
    bootMs: performance.now(),
    mapLoadMs: null,
    firstIdleMs: null,
    longTaskCount: 0,
    longTaskTotalMs: 0,
    longTaskMaxMs: 0,
    longTaskApiAvailable: true,
    fps: null,
    lastActiveFps: null,
    lastActiveFpsAgeMs: null,
    worstFrameMs: null,
    slowFrameCount: 0,
    zoom: map.getZoom(),
  };

  // LAYOUT, AND WHY THE OLD ONE WAS UNREADABLE ON THE DEVICE IT EXISTS FOR
  // ----------------------------------------------------------------------
  // The panel was `white-space:pre` with no max-width inside `body{overflow:hidden}`. On a phone
  // the long lines therefore ran off the right edge into overflow that could not be reached by
  // any gesture — not merely off-screen, but structurally unreachable. `pre-wrap` plus a width
  // bound is what makes the text exist at all on a 412 px screen.
  //
  // POINTER EVENTS ARE PER-ROW, NOT PER-PANEL
  // -----------------------------------------
  // The container stays `none` so the collapsed panel never eats a map drag. Only the controls,
  // and the body once it is EXPANDED (where scrolling is the point and covering the map is
  // expected), opt back in. A blanket `auto` would have made the top-left of the globe undraggable
  // for anyone with `?perf` on.
  const panel = document.createElement("div");
  panel.style.cssText = [
    "position:fixed",
    "top:4.2rem",
    "left:1.2rem",
    "z-index:40",
    "max-width:min(44rem,calc(100vw - 2.4rem))",
    "background:rgba(10,14,16,0.82)",
    "color:#9fe8a0",
    "font:11px/1.6 ui-monospace,monospace",
    "border-radius:8px",
    "pointer-events:none",
  ].join(";");

  const body = document.createElement("div");
  body.style.cssText = [
    "padding:0.5rem 0.7rem",
    "white-space:pre-wrap",
    "overflow-wrap:anywhere",
    "max-height:min(60vh,32rem)",
    "overflow-y:auto",
  ].join(";");

  const controls = document.createElement("div");
  controls.style.cssText = [
    "display:flex",
    "gap:0.4rem",
    "padding:0 0.7rem 0.5rem",
    "pointer-events:auto",
  ].join(";");

  const button = (label: string) => {
    const element = document.createElement("button");
    element.type = "button";
    element.textContent = label;
    // 28px min-height: a tap target, since this is operated by thumb on the device it matters on.
    element.style.cssText = [
      "min-height:28px",
      "padding:0 0.6rem",
      "background:rgba(159,232,160,0.12)",
      "color:#9fe8a0",
      "border:1px solid rgba(159,232,160,0.4)",
      "border-radius:6px",
      "font:11px/1 ui-monospace,monospace",
      "cursor:pointer",
    ].join(";");
    controls.appendChild(element);
    return element;
  };

  let collapsed = startsCollapsed(document.documentElement.clientWidth);
  const toggle = button("");
  const applyCollapse = () => {
    toggle.textContent = collapsed ? "expand" : "collapse";
    toggle.setAttribute("aria-expanded", String(!collapsed));
    body.style.pointerEvents = collapsed ? "none" : "auto";
  };
  toggle.addEventListener("click", () => {
    collapsed = !collapsed;
    applyCollapse();
  });
  applyCollapse();

  if (buildReport) {
    const exportButton = button("export");
    exportButton.addEventListener("click", () => {
      exportButton.textContent = "…";
      void exportPerfReport({
        report: buildReport(snapshot, { expanded: !collapsed }),
        fetchFn: typeof fetch === "function" ? fetch.bind(globalThis) : undefined,
        writeClipboard: navigator.clipboard
          ? (text) => navigator.clipboard.writeText(text)
          : undefined,
        // The outcome stays on the button rather than reverting: on a phone the tap and the
        // reading of the result are the same glance, and a label that flicked back to "export"
        // would leave "did that work?" unanswered.
      }).then((outcome) => {
        exportButton.textContent = outcome;
      });
    });
  }

  panel.append(body, controls);
  document.body.appendChild(panel);

  if (!eventStamps) {
    map.once("load", () => {
      snapshot.mapLoadMs = performance.now();
    });
    map.once("idle", () => {
      snapshot.firstIdleMs = performance.now();
    });
  }

  if (!longTaskApiSupported()) {
    snapshot.longTaskApiAvailable = false;
  } else {
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          snapshot.longTaskCount += 1;
          snapshot.longTaskTotalMs += entry.duration;
          snapshot.longTaskMaxMs = Math.max(snapshot.longTaskMaxMs, entry.duration);
        }
      });
      observer.observe({ type: "longtask", buffered: true });
    } catch {
      snapshot.longTaskApiAvailable = false; // engines that DO throw, kept honest the same way
    }
  }

  // Frame cadence is sampled from MapLibre's own "render" event, NOT from a requestAnimationFrame
  // loop. A bare rAF loop would report a steady 60 on a map that rendered nothing, and worse, it
  // would hold the page at 60 Hz and so change the thing being measured. The map renders on
  // demand, so this counts real frames and reads idle when there are none.
  //
  // Caveat this cannot see: "render" is one per displayed frame only while frames come from the
  // rAF loop, which is every gesture, fly-to and idle spin. A direct map.redraw() renders
  // synchronously outside that loop and would be counted too, inflating the rate. Nothing on the
  // page calls redraw(); scripted diagnosis does, and should read this number accordingly.
  const renderStamps: number[] = [];
  // Age is recomputed every tick from this stamp rather than stored, so it cannot go stale.
  let retainedRate: RetainedFrameRate = { fps: null, measuredAtMs: null };
  let tracker = newFrameTracker();
  map.on("idle", () => {
    tracker = onIdle(tracker);
    snapshot.worstFrameMs = tracker.peakMs;
    snapshot.slowFrameCount = tracker.slowCount;
  });
  map.on("render", () => {
    const stamp = performance.now();
    tracker = onRender(tracker, stamp);
    snapshot.worstFrameMs = tracker.peakMs;
    snapshot.slowFrameCount = tracker.slowCount;
    renderStamps.push(stamp);
    if (renderStamps.length > 512) renderStamps.splice(0, renderStamps.length - 256);
  });

  // A slow textContent refresh — the overlay must never contribute the jank it measures.
  // Page-recorded stamps are copied here each tick: the object is live, so stamps that
  // land after mount still appear.
  window.setInterval(() => {
    if (eventStamps) {
      snapshot.mapLoadMs = eventStamps.mapLoadMs;
      snapshot.firstIdleMs = eventStamps.firstIdleMs;
    }
    const now = performance.now();
    snapshot.fps = frameRate(renderStamps, now);
    retainedRate = retainFrameRate(retainedRate, snapshot.fps, now);
    snapshot.lastActiveFps = retainedRate.fps;
    snapshot.lastActiveFpsAgeMs =
      retainedRate.measuredAtMs === null ? null : now - retainedRate.measuredAtMs;
    snapshot.zoom = map.getZoom();
    while (renderStamps.length && now - renderStamps[0] > FPS_WINDOW_MS * 2) renderStamps.shift();
    // The collapsed view is a SUBSET of the same live snapshot, not a second reading — nothing on
    // the panel can disagree with the export because all three come from this one object.
    body.textContent = collapsed
      ? perfCollapsedLines(snapshot).join("\n")
      : [...perfSummaryLines(snapshot), ...(extraLines?.(snapshot) ?? [])].join("\n");
  }, 300);
}
