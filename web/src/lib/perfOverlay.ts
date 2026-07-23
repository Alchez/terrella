// On-screen performance overlay for /globe?perf — phones have no devtools console, so the
// numbers render into a corner panel the user can screenshot. Long tasks (main-thread blocks
// >50 ms, the Long Tasks API) are the jank currency: their count/total/max during the first
// seconds attribute "it lags" to real main-thread stalls, while map load / first idle separate
// download completion from responsiveness. Combined with the layer-stripping flags (?nocaps,
// ?bare) the differences between reloads attribute the stalls to a subsystem.

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
  /** When the most recent long task ENDED — quiet time since ≈ "usable since". */
  lastLongTaskEndMs: number | null;
  longTaskApiAvailable: boolean;
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
      `last long task ended ${ms(snapshot.lastLongTaskEndMs)}`,
    );
  } else {
    lines.push("long-task API unavailable");
  }
  return lines;
}

/** Mount the overlay and start observing. Buffered observation is load-bearing: the heaviest
 *  long tasks (JS parse/eval, first JSON.parse) happen BEFORE this module loads, and
 *  `buffered: true` replays them into the observer. Map-event timing comes from
 *  `eventStamps` when the page provides it (see PerfEventStamps); own listeners are the
 *  fallback for callers that don't. */
export function mountPerfOverlay(map: MaplibreMap, eventStamps?: PerfEventStamps): void {
  const snapshot: PerfSnapshot = {
    bootMs: performance.now(),
    mapLoadMs: null,
    firstIdleMs: null,
    longTaskCount: 0,
    longTaskTotalMs: 0,
    longTaskMaxMs: 0,
    lastLongTaskEndMs: null,
    longTaskApiAvailable: true,
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

  try {
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        snapshot.longTaskCount += 1;
        snapshot.longTaskTotalMs += entry.duration;
        snapshot.longTaskMaxMs = Math.max(snapshot.longTaskMaxMs, entry.duration);
        snapshot.lastLongTaskEndMs = entry.startTime + entry.duration;
      }
    });
    observer.observe({ type: "longtask", buffered: true });
  } catch {
    snapshot.longTaskApiAvailable = false;
  }

  // A slow textContent refresh — the overlay must never contribute the jank it measures.
  // Page-recorded stamps are copied here each tick: the object is live, so stamps that
  // land after mount still appear.
  window.setInterval(() => {
    if (eventStamps) {
      snapshot.mapLoadMs = eventStamps.mapLoadMs;
      snapshot.firstIdleMs = eventStamps.firstIdleMs;
    }
    panel.textContent = perfSummaryLines(snapshot).join("\n");
  }, 300);
}
