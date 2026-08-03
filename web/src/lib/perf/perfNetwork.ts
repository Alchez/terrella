// What the tiles actually cost on the wire, from Resource Timing.
//
// WHY THIS EXISTS
// ---------------
// Two readings were misreported in one evening for the same missing fact. A phone's `bootMs 2792`
// was called the largest number in the capture and presented as a real startup cost; the next two
// arms read 1442 and 1504, because the first was a cold cache. A desktop cap reading was quoted
// before noticing that four of its five files came from cache and only one was downloaded. Nothing
// in the report distinguished "fetched" from "already had it", so every absolute in it was
// ambiguous by construction.
//
// THE HIT/MISS ORACLE THIS WAS SUPPOSED TO USE DOES NOT WORK — MEASURED, NOT ASSUMED
// ---------------------------------------------------------------------------------
// The plan for this module said: the tile Worker emits `Server-Timing`, so `r2;dur` present means
// an edge MISS and absent means a HIT, giving a free per-tile cache oracle. Both halves are false.
//
//   1. `r2` is pushed UNCONDITIONALLY by the Worker's serverTimingHeader. On a Cache API hit
//      `timing.reads` is empty, so it emits `r2;dur=0;desc="0 reads, 0 B"` — present, not absent.
//   2. Far worse, the header is a FOSSIL on an edge hit. Tiles ship
//      `Cache-Control: public, max-age=31536000, immutable`, so Cloudflare's edge answers without
//      running the Worker at all. Fetching one tile twice returned `cf-cache-status: HIT` both
//      times, `age: 51949` on the second, and a byte-identical
//      `cache;dur=7, r2;dur=280;desc="1 read, 87954 B", worker;dur=287` — a ~14-hour-old
//      measurement replayed verbatim. Even the Worker's own `X-Terrella-Cache` header said
//      `miss` on a response that never reached the Worker.
//
// The Worker's own comment predicted this ("a stored Server-Timing would let a cache HIT replay the
// timings of the MISS that filled it, which is worse than no instrument at all") — it just applies
// to the edge cache in front of the Worker, not only to the Cache API inside it.
//
// So `serverTiming` is recorded verbatim and NEVER reduced to a verdict. Edge HIT/MISS is
// fundamentally unobservable from the page: `cf-cache-status` is a response header, MapLibre loads
// tiles as `img`, and no response header is readable through Resource Timing.
//
// WHAT IS READABLE, AND IT IS THE THING WE ACTUALLY NEEDED
// -------------------------------------------------------
// The browser's own cache is visible, which is the confound that caused the misreports. Measured on
// production across seven tiles and one cached asset, exactly:
//
//   fetched over the network   transferSize === encodedBodySize + 300
//   served from browser cache  transferSize === 300, with encodedBodySize still populated
//
// 300 is the header allowance the Resource Timing spec requires implementations to add, which is
// why it is subtracted here rather than treated as payload.

import { type LayerId, resolveTileRequest } from "../tileAddress";
import type { PerfLine } from "./perfLines";

/**
 * The fixed allowance Resource Timing adds to `transferSize` for response headers.
 *
 * Not a fudge factor: the spec mandates it so a body size cannot be recovered exactly from a
 * cross-origin timing. It is the difference between a 48,214-byte tile reporting 48,514 and
 * reporting its real payload, and subtracting it is what makes "bytes on the wire" mean that.
 */
export const TRANSFER_SIZE_HEADER_ALLOWANCE = 300;

/** The subset of `PerformanceResourceTiming` this module reads, so it tests without a browser. */
export interface TimedResource {
  name: string;
  transferSize: number;
  encodedBodySize: number;
  decodedBodySize: number;
  duration: number;
  serverTiming?: readonly { name: string; duration: number; description?: string }[];
}

/** Bytes that crossed the network for one resource. Zero means the browser already had it. */
export function wireBytes(entry: TimedResource): number {
  return Math.max(0, entry.transferSize - TRANSFER_SIZE_HEADER_ALLOWANCE);
}

/**
 * Whether the browser served this from its own cache rather than the network.
 *
 * `wireBytes === 0` alone is not enough: a resource that genuinely failed, or one whose timing is
 * opaque because `Timing-Allow-Origin` is missing, also reports zero. Requiring a populated
 * `encodedBodySize` separates "had it already" from "learned nothing about it" — and those must
 * stay separable, because counting an unreadable entry as a cache hit would understate wire bytes
 * exactly where the numbers are least trustworthy.
 */
export function servedFromBrowserCache(entry: TimedResource): boolean {
  return wireBytes(entry) === 0 && entry.encodedBodySize > 0;
}

/** A reading whose timing is cross-origin-opaque: nothing about its size is knowable. */
export function timingIsOpaque(entry: TimedResource): boolean {
  return entry.transferSize === 0 && entry.encodedBodySize === 0;
}

export interface TrafficSlice {
  count: number;
  wireBytes: number;
  /** Cache-served requests, counted separately so `count` stays "requests the map made". */
  fromBrowserCache: number;
}

/** One slice per pyramid, and a `Record` over the layer union rather than named fields — so a
 *  fourth pyramid is a compile error in the initialiser below instead of traffic that quietly
 *  lands in whichever slice the classifier falls through to. The split used to be
 *  `startsWith("terrain/") ? terrain : relief`, a two-way branch over three layers.
 *
 *  `countries` NORMALLY READS ZERO, and that is not the vector pyramid failing to load. Measured
 *  on the live globe: 407 tile entries with the country pyramid fully resident (276 features,
 *  France hit-testing), and not one of them an `.mvt` — every entry's `initiatorType` is `img`.
 *  MapLibre fetches raster tiles as images on the main thread and vector tiles from its worker,
 *  and a worker's fetches populate the WORKER's Resource Timing buffer, not the page's. The slice
 *  exists because the classifier now answers the layer question honestly rather than folding an
 *  unrecognised answer into relief; it is not evidence about vector traffic either way. */
export interface TileTraffic extends Record<LayerId, TrafficSlice> {
  /** Requests whose size is unknowable, kept visible rather than folded into a zero. */
  opaqueCount: number;
  /** Requests under the tile base that are not tile addresses at all.
   *
   *  Counted rather than dropped, for the reason `opaqueCount` exists: silently discarding an
   *  entry makes a wrong total look like a small one. A non-zero reading here means something is
   *  asking the tile server for a URL it will not serve. */
  unaddressedCount: number;
  /** Median of `duration` over network-served tiles only — a cache hit's ~0 ms would otherwise
   *  drag the median toward zero and read as the network getting faster. */
  medianNetworkDurationMs: number | null;
  /** True when the entry buffer is at capacity, so these totals are a floor and not a total.
   *  The default is 250 and one globe session passes it in silence. */
  bufferFull: boolean;
}

const emptySlice = (): TrafficSlice => ({ count: 0, wireBytes: 0, fromBrowserCache: 0 });

/** Median, or null for an empty list. Even-length takes the mean of the middle pair. */
export function median(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((first, second) => first - second);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

/**
 * Split the tile traffic in one buffer of Resource Timing entries.
 *
 * Pure. `tileBase` is passed in rather than imported so a test can describe any deployment, and so
 * the dev server's same-origin `/tiles/` and production's `tiles.` subdomain are the same code path.
 *
 * THE SPLIT IS THE TILE SERVERS' OWN PARSER, not a string test against it. Nothing else in a tile
 * URL tells relief from terrain — both are WebP over z0-8 on one grid — so the layer segment is the
 * whole discriminator, and reading it with anything but `resolveTileRequest` is a second copy of the
 * grammar that drifts silently. It already had: a `startsWith("terrain/")` test survived the move to
 * `{body}/{layer}/{token}/…` untouched and would have counted EVERY terrain tile as relief, on a
 * panel whose entire job is telling those two apart.
 */
export function summariseTileTraffic(
  entries: readonly TimedResource[],
  tileBase: string,
  pageUrl: string,
  bufferSize: number,
): TileTraffic {
  // RESOLVED, not compared as given, and this is not defensive tidying — it was a live bug.
  // `TILE_BASE` is absolute in production (`https://tiles.…/`) and RELATIVE on the dev server
  // (`/tiles/`), while `PerformanceResourceTiming.name` is always an absolute URL. Comparing the
  // relative form matched nothing, so a page with 55 tile requests in its buffer rendered
  // `tiles relief 0 · terrain 0 · 0.0 MB wire` — and zero is a plausible reading, so nothing about
  // it looked wrong. Taking `pageUrl` as a parameter rather than reading `location` keeps this pure
  // AND makes the resolution unforgettable: there is no call shape that skips it.
  const base = new URL(tileBase, pageUrl).href;
  const tiles = entries.filter((entry) => entry.name.startsWith(base));
  const traffic: TileTraffic = {
    relief: emptySlice(),
    terrain: emptySlice(),
    countries: emptySlice(),
    opaqueCount: 0,
    unaddressedCount: 0,
    medianNetworkDurationMs: null,
    bufferFull: entries.length >= bufferSize,
  };
  const networkDurations: number[] = [];
  for (const entry of tiles) {
    if (timingIsOpaque(entry)) {
      traffic.opaqueCount++;
      continue;
    }
    const path = entry.name.slice(base.length);
    // Both grammars, because both are in flight: a page built before the address switch keeps
    // asking the old shape until its tab is reloaded, and its bytes are as real as any other's.
    const address = resolveTileRequest(path);
    if (!address) {
      traffic.unaddressedCount++;
      continue;
    }
    const slice = traffic[address.layer];
    slice.count++;
    slice.wireBytes += wireBytes(entry);
    if (servedFromBrowserCache(entry)) slice.fromBrowserCache++;
    else networkDurations.push(entry.duration);
  }
  traffic.medianNetworkDurationMs = median(networkDurations);
  return traffic;
}

// HOW LONG A CAMERA MOVE TAKES TO SETTLE
// --------------------------------------
// The metric for the original complaint — "tiles take a long time to load in" — which until now was
// only ever measured by hand, once, with a bespoke rig. `movestart → idle` is the user-perceived
// unit: the moment they stop being able to see what they asked for, to the moment it is all there.
//
// It must only count when a move actually preceded the idle. MapLibre fires `idle` after any
// settling work at all, including the first load and a style change, so an unguarded timer records
// a fill for every one of them — mostly zero-tile fills that drag the reading toward nothing and
// make a slow pan look like an outlier rather than the norm.

/** A move in progress, plus the last one that completed. */
export interface CameraFill {
  /** `performance.now()` when the current move began; null when the camera is settled. */
  movingSinceMs: number | null;
  /** Tile-entry count at that moment, so the window's own fetches can be differenced out. */
  tilesAtMoveStart: number | null;
  /** The most recent completed fill, or null before one has finished. */
  last: { durationMs: number; tilesFetched: number } | null;
}

export const newCameraFill = (): CameraFill => ({
  movingSinceMs: null,
  tilesAtMoveStart: null,
  last: null,
});

/**
 * Begin a fill window, or leave one already open alone.
 *
 * Not a reset: MapLibre fires `movestart` again for a second gesture that begins before the first
 * has settled, and restarting there would report the tail of a long interaction as a short one. One
 * continuous interaction is one fill, which is how the person doing it experiences it.
 */
export function onCameraMoveStart(fill: CameraFill, nowMs: number, tileCount: number): CameraFill {
  if (fill.movingSinceMs !== null) return fill;
  return { ...fill, movingSinceMs: nowMs, tilesAtMoveStart: tileCount };
}

/** Close a fill window, recording it only if a move actually opened one. */
export function onCameraIdle(fill: CameraFill, nowMs: number, tileCount: number): CameraFill {
  if (fill.movingSinceMs === null || fill.tilesAtMoveStart === null) return fill;
  return {
    movingSinceMs: null,
    tilesAtMoveStart: null,
    last: {
      durationMs: nowMs - fill.movingSinceMs,
      // Differenced, and clamped: the buffer can evict between the two reads, and a negative
      // "tiles fetched" would be worse than an undercount because it reads as a bug in the map.
      tilesFetched: Math.max(0, tileCount - fill.tilesAtMoveStart),
    },
  };
}

/**
 * The fill line, or null when there is nothing to report — a caller omits the row entirely.
 *
 * Grouped with FEEL rather than NETWORK, even though it counts tiles. How long a camera move takes
 * to settle is an outcome with no single owner: it is bandwidth, decode, upload and render pass at
 * once, and the tile-count half of this line has already been read as though it meant bandwidth —
 * the arm that pulled 340 KB from cache out-janked the one that pulled 1.90 MB fresh.
 */
export function cameraFillLine(fill: CameraFill): PerfLine | null {
  if (fill.movingSinceMs !== null) return { group: "feel", text: "fill · moving…" };
  if (fill.last === null) return null;
  const seconds = (fill.last.durationMs / 1000).toFixed(1);
  return { group: "feel", text: `fill ${seconds}s · ${fill.last.tilesFetched} tiles` };
}

/** The panel line. Bytes as whole MiB via the shared formatter's rules, not a second policy. */
export function tileTrafficLine(traffic: TileTraffic): PerfLine {
  const slice = (label: string, part: TrafficSlice) => {
    const cached = part.fromBrowserCache > 0 ? ` (${part.fromBrowserCache} cached)` : "";
    return `${label} ${part.count}${cached}`;
  };
  // EVERY layer's bytes, including the ones with no label below: "MB wire" means bytes that crossed
  // the network under the tile base, and a total that quietly omitted a pyramid would understate
  // exactly the number this panel is read for.
  const wire = traffic.relief.wireBytes + traffic.terrain.wireBytes + traffic.countries.wireBytes;
  const median =
    traffic.medianNetworkDurationMs === null
      ? "med —"
      : `med ${Math.round(traffic.medianNetworkDurationMs)} ms`;
  // Warnings are appended rather than replacing anything: a truncated buffer still has real numbers
  // in it, and an opaque or unaddressed entry is a known unknown, not a reason to distrust the rest.
  const truncated = traffic.bufferFull ? " · BUFFER FULL, totals are a floor" : "";
  const opaque = traffic.opaqueCount > 0 ? ` · ${traffic.opaqueCount} opaque` : "";
  // Silent until it fires, and when it fires it is a bug: something is asking the tile server for a
  // URL neither grammar can parse, so the server will not serve it either.
  const unaddressed =
    traffic.unaddressedCount > 0 ? ` · ${traffic.unaddressedCount} unaddressed` : "";
  // No leading "tiles": the NETWORK heading says what these are, and the word cost one character
  // more than a 412 px phone has (54 against a measured 53-character budget).
  //
  // TWO LABELS FOR THREE SLICES. The line is already 49 of its 53 characters at typical values, so
  // a third `· countries N` (14) would wrap on the phone the budget was measured against — and it
  // would spend that width on a number measured to be zero on this page, since vector tiles are
  // fetched from MapLibre's worker and never enter this buffer (see TileTraffic). Relief and
  // terrain are the pair the panel exists to compare: same codec, same grid, so confusing them is
  // the failure worth reading for. `traffic.countries` is there for any caller that wants it.
  return {
    group: "network",
    text:
      `${slice("relief", traffic.relief)} · ${slice("terrain", traffic.terrain)} · ` +
      `${(wire / (1024 * 1024)).toFixed(1)} MB wire · ${median}${opaque}${unaddressed}${truncated}`,
  };
}
