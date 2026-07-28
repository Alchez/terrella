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
  /** Module-eval → overlay mount: the JS startup cost paid before the map exists. */
  bootMs: number;
  mapLoadMs: number | null;
  firstIdleMs: number | null;
  longTaskCount: number;
  longTaskTotalMs: number;
  longTaskMaxMs: number;
  longTaskApiAvailable: boolean;
  /** Rendered frames per second over the last FPS_WINDOW_MS, or null when the map is idle. */
  fps: number | null;
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
  const rate = snapshot.fps === null ? "fps — (idle)" : `fps ${snapshot.fps}`;
  lines.push(
    `${rate} · worst ${ms(snapshot.worstFrameMs)} · slow ${snapshot.slowFrameCount}` +
      ` · z${snapshot.zoom.toFixed(2)}`,
  );
  return lines;
}

/** Mount the overlay and start observing. Buffered observation is load-bearing: the heaviest
 *  long tasks (JS parse/eval, first JSON.parse) happen BEFORE this module loads, and
 *  `buffered: true` replays them into the observer. Map-event timing comes from
 *  `eventStamps` when the page provides it (see PerfEventStamps); own listeners are the
 *  fallback for callers that don't. */
export function mountPerfOverlay(
  map: MaplibreMap,
  eventStamps?: PerfEventStamps,
  extraLines?: () => string[],
): void {
  const snapshot: PerfSnapshot = {
    bootMs: performance.now(),
    mapLoadMs: null,
    firstIdleMs: null,
    longTaskCount: 0,
    longTaskTotalMs: 0,
    longTaskMaxMs: 0,
    longTaskApiAvailable: true,
    fps: null,
    worstFrameMs: null,
    slowFrameCount: 0,
    zoom: map.getZoom(),
  };

  const panel = document.createElement("div");
  panel.style.cssText = [
    "position:fixed",
    "top:4.2rem",
    "left:1.2rem",
    "z-index:40",
    "padding:0.5rem 0.7rem",
    "background:rgba(10,14,16,0.78)",
    "color:#9fe8a0",
    "font:11px/1.6 ui-monospace,monospace",
    "border-radius:8px",
    "pointer-events:none",
    "white-space:pre",
  ].join(";");
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
    snapshot.zoom = map.getZoom();
    while (renderStamps.length && now - renderStamps[0] > FPS_WINDOW_MS * 2) renderStamps.shift();
    panel.textContent = [...perfSummaryLines(snapshot), ...(extraLines?.() ?? [])].join("\n");
  }, 300);
}
