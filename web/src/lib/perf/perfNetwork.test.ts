import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  TRANSFER_SIZE_HEADER_ALLOWANCE,
  type TileTraffic,
  type TimedResource,
  cameraFillLine,
  median,
  newCameraFill,
  onCameraIdle,
  onCameraMoveStart,
  servedFromBrowserCache,
  summariseTileTraffic,
  tileTrafficLine,
  timingIsOpaque,
  wireBytes,
} from "./perfNetwork";

const BASE = "https://tiles.terrella.alchez.dev/";
const PAGE = "https://terrella.alchez.dev/globe/?perf";

/** A network-served entry, built the way production reports one: transferSize = encoded + 300. */
const fetched = (path: string, encodedBytes: number, durationMs = 400): TimedResource => ({
  name: `${BASE}${path}`,
  transferSize: encodedBytes + TRANSFER_SIZE_HEADER_ALLOWANCE,
  encodedBodySize: encodedBytes,
  decodedBodySize: encodedBytes,
  duration: durationMs,
});

/** A browser-cache entry: the allowance alone, with the body size still populated. */
const cached = (path: string, encodedBytes: number): TimedResource => ({
  name: `${BASE}${path}`,
  transferSize: TRANSFER_SIZE_HEADER_ALLOWANCE,
  encodedBodySize: encodedBytes,
  decodedBodySize: encodedBytes,
  duration: 2,
});

describe("wire bytes, measured against how production actually reports them", () => {
  it("subtracts the mandated header allowance, so a byte count means payload", () => {
    // Production, verbatim: a 48,214-byte tile reports transferSize 48,514.
    expect(wireBytes(fetched("5/22/13.webp", 48_214))).toBe(48_214);
  });

  it("reads a browser-cache hit as zero on the wire", () => {
    expect(wireBytes(cached("5/22/13.webp", 48_214))).toBe(0);
    expect(servedFromBrowserCache(cached("5/22/13.webp", 48_214))).toBe(true);
  });

  it("never reports a negative payload, whatever the allowance arithmetic does", () => {
    const odd: TimedResource = {
      name: `${BASE}0/0/0.webp`, transferSize: 12, encodedBodySize: 900, decodedBodySize: 900,
      duration: 1,
    };
    expect(wireBytes(odd)).toBe(0);
  });

  it("separates 'had it already' from 'learned nothing about it'", () => {
    // Both report zero wire bytes and they are NOT the same fact. Counting an opaque entry as a
    // cache hit would understate wire bytes exactly where the reading is least trustworthy.
    const opaque: TimedResource = {
      name: `${BASE}5/22/13.webp`, transferSize: 0, encodedBodySize: 0, decodedBodySize: 0,
      duration: 300,
    };
    expect(timingIsOpaque(opaque)).toBe(true);
    expect(servedFromBrowserCache(opaque)).toBe(false);
    expect(servedFromBrowserCache(cached("5/22/13.webp", 100))).toBe(true);
    expect(timingIsOpaque(cached("5/22/13.webp", 100))).toBe(false);
  });
});

describe("median", () => {
  it("is null for nothing, rather than zero", () => {
    // Zero would read as "instant", which is the opposite of "no measurement".
    expect(median([])).toBeNull();
  });

  it("takes the middle of an odd list and the mean of an even pair", () => {
    expect(median([400, 100, 300])).toBe(300);
    expect(median([100, 200, 300, 500])).toBe(250);
  });
});

describe("summariseTileTraffic", () => {
  it("splits relief from terrain on the path prefix, which is the only thing that differs", () => {
    // Both pyramids are WebP over z0-8, so nothing else in the URL distinguishes them.
    const traffic = summariseTileTraffic(
      [
        fetched("5/22/13.webp", 40_000),
        fetched("6/44/26.webp", 60_000),
        fetched("terrain/5/22/13.webp", 10_000),
      ],
      BASE,
      PAGE,
      3000,
    );
    expect(traffic.relief.count).toBe(2);
    expect(traffic.relief.wireBytes).toBe(100_000);
    expect(traffic.terrain.count).toBe(1);
    expect(traffic.terrain.wireBytes).toBe(10_000);
  });

  it("does not mistake a relief tile at zoom level named like the prefix", () => {
    // A path must start with `terrain/`; a substring anywhere else must not reclassify it.
    const traffic = summariseTileTraffic([fetched("5/22/terrain.webp", 100)], BASE, PAGE, 3000);
    expect(traffic.relief.count).toBe(1);
    expect(traffic.terrain.count).toBe(0);
  });

  it("ignores everything that is not a tile", () => {
    const traffic = summariseTileTraffic(
      [
        { name: "https://terrella.alchez.dev/caps/caps.json", transferSize: 300,
          encodedBodySize: 216, decodedBodySize: 947, duration: 116 },
        fetched("5/22/13.webp", 40_000),
      ],
      BASE,
      PAGE,
      3000,
    );
    expect(traffic.relief.count).toBe(1);
    expect(traffic.relief.wireBytes).toBe(40_000);
  });

  it("keeps cache hits out of the median, so caching cannot look like a faster network", () => {
    // The defect this prevents: a warm reload is mostly ~2 ms cache reads, and folding those in
    // would report the network as having got dramatically quicker between two runs.
    const traffic = summariseTileTraffic(
      [
        fetched("5/22/13.webp", 40_000, 400),
        fetched("5/22/14.webp", 40_000, 600),
        cached("5/22/15.webp", 40_000),
        cached("5/22/16.webp", 40_000),
      ],
      BASE,
      PAGE,
      3000,
    );
    expect(traffic.medianNetworkDurationMs).toBe(500);
    expect(traffic.relief.count).toBe(4);
    expect(traffic.relief.fromBrowserCache).toBe(2);
    // ...and the cached pair contributed nothing to the wire total.
    expect(traffic.relief.wireBytes).toBe(80_000);
  });

  it("reports null rather than 0 ms when every tile came from cache", () => {
    const traffic = summariseTileTraffic([cached("5/22/13.webp", 40_000)], BASE, PAGE, 3000);
    expect(traffic.medianNetworkDurationMs).toBeNull();
  });

  it("counts opaque entries separately instead of folding them into a zero", () => {
    const traffic = summariseTileTraffic(
      [{ name: `${BASE}5/22/13.webp`, transferSize: 0, encodedBodySize: 0, decodedBodySize: 0,
         duration: 300 }],
      BASE,
      PAGE,
      3000,
    );
    expect(traffic.opaqueCount).toBe(1);
    expect(traffic.relief.count).toBe(0);
  });

  it("resolves a RELATIVE tile base, which is what the dev server actually has", () => {
    // Caught live, not imagined. `TILE_BASE` is absolute in production and `/tiles/` on the dev
    // server, while entry names are always absolute — so the unresolved comparison matched nothing
    // and a page holding 55 tile requests rendered `relief 0 · terrain 0 · 0.0 MB wire`. Zero is a
    // plausible reading, which is why nothing looked wrong: the check could not fail.
    const devEntries: TimedResource[] = [
      { name: "http://localhost:4321/tiles/3/4/2.webp", transferSize: 40_300,
        encodedBodySize: 40_000, decodedBodySize: 40_000, duration: 3 },
      { name: "http://localhost:4321/tiles/terrain/3/4/2.webp", transferSize: 10_300,
        encodedBodySize: 10_000, decodedBodySize: 10_000, duration: 2 },
    ];
    const traffic = summariseTileTraffic(
      devEntries, "/tiles/", "http://localhost:4321/globe/?perf", 3000,
    );
    expect(traffic.relief.count).toBe(1);
    expect(traffic.terrain.count).toBe(1);
    expect(traffic.relief.wireBytes).toBe(40_000);
  });

  it("does not match another origin that happens to share the path", () => {
    // The resolution must not degrade into a path-only comparison: a same-path URL on a different
    // host is not our tile, and counting it would import someone else's bytes into our totals.
    const traffic = summariseTileTraffic(
      [{ name: "http://evil.example/tiles/3/4/2.webp", transferSize: 40_300,
         encodedBodySize: 40_000, decodedBodySize: 40_000, duration: 3 }],
      "/tiles/",
      "http://localhost:4321/globe/?perf",
      3000,
    );
    expect(traffic.relief.count).toBe(0);
  });

  it("says the totals are a floor once the buffer is full", () => {
    // The whole point of choosing the size: the default 250 is reached in silence, and there is no
    // API to read the limit back or to learn that an entry was dropped.
    const entries = Array.from({ length: 250 }, (_, index) => fetched(`5/22/${index}.webp`, 10));
    expect(summariseTileTraffic(entries, BASE, PAGE, 250).bufferFull).toBe(true);
    expect(summariseTileTraffic(entries, BASE, PAGE, 3000).bufferFull).toBe(false);
  });
});

/** Just the rendered text — the subsystem tag is asserted once, on its own, below. */
const trafficText = (traffic: TileTraffic) => tileTrafficLine(traffic).text;

describe("tileTrafficLine", () => {
  it("names both pyramids, the wire cost, and the median", () => {
    const line = trafficText(
      summariseTileTraffic(
        [
          fetched("5/22/13.webp", 1_048_576, 411),
          fetched("terrain/5/22/13.webp", 1_048_576, 128),
        ],
        BASE,
        PAGE,
        3000,
      ),
    );
    expect(line).toBe("relief 1 · terrain 1 · 2.0 MB wire · med 270 ms");
  });

  it("is the panel's NETWORK row — the only line that is bytes on the wire and nothing else", () => {
    expect(tileTrafficLine(summariseTileTraffic([], BASE, PAGE, 3000)).group).toBe("network");
  });

  it("shows the cache split only when there is one", () => {
    // A permanent `(0 cached)` is a row the eye learns to skip — the same rule the faults line
    // and the GPU-loss line already follow.
    const warm = trafficText(
      summariseTileTraffic([cached("5/22/13.webp", 40_000)], BASE, PAGE, 3000),
    );
    expect(warm).toContain("relief 1 (1 cached)");
    const cold = trafficText(
      summariseTileTraffic([fetched("5/22/13.webp", 40_000)], BASE, PAGE, 3000),
    );
    expect(cold).toContain("relief 1 ·");
    expect(cold).not.toContain("cached");
  });

  it("shouts when the buffer is full, because the numbers become a floor", () => {
    const entries = Array.from({ length: 250 }, (_, index) => fetched(`5/22/${index}.webp`, 10));
    expect(trafficText(summariseTileTraffic(entries, BASE, PAGE, 250))).toContain("BUFFER FULL");
  });

  it("renders a median of — rather than 0 ms when nothing was fetched", () => {
    expect(trafficText(summariseTileTraffic([], BASE, PAGE, 3000))).toContain("med —");
  });
});

describe("camera fill — movestart to idle", () => {
  it("records nothing for an idle that no move preceded", () => {
    // The defect this prevents: MapLibre fires `idle` after the first load and after a style
    // change too, so an unguarded timer logs a zero-tile fill for each and drags the reading down.
    const settled = onCameraIdle(newCameraFill(), 5000, 97);
    expect(settled.last).toBeNull();
    expect(cameraFillLine(settled)).toBeNull();
  });

  it("times one move and counts the tiles it caused", () => {
    let fill = onCameraMoveStart(newCameraFill(), 1000, 12);
    fill = onCameraIdle(fill, 12_200, 109);
    expect(fill.last).toEqual({ durationMs: 11_200, tilesFetched: 97 });
    // FEEL, not NETWORK, and asserted here rather than in a test of its own: a settle is
    // bandwidth, decode, upload and render pass at once, and the tile count in this very line has
    // already been read as though it meant bandwidth alone.
    expect(cameraFillLine(fill)).toEqual({ group: "feel", text: "fill 11.2s · 97 tiles" });
    // ...and the window is closed, so the next idle cannot re-record it.
    expect(onCameraIdle(fill, 20_000, 200).last).toEqual(fill.last);
  });

  it("treats a second gesture inside an unsettled move as the same fill", () => {
    // Restarting here would report the tail of a long interaction as a short one. What the person
    // doing it experiences is one wait, so it is one fill.
    let fill = onCameraMoveStart(newCameraFill(), 1000, 10);
    fill = onCameraMoveStart(fill, 4000, 50);
    expect(fill.movingSinceMs).toBe(1000);
    expect(fill.tilesAtMoveStart).toBe(10);
    fill = onCameraIdle(fill, 9000, 80);
    expect(fill.last).toEqual({ durationMs: 8000, tilesFetched: 70 });
  });

  it("says it is moving rather than showing a stale duration mid-gesture", () => {
    const moving = onCameraMoveStart(newCameraFill(), 1000, 10);
    expect(cameraFillLine(moving)).toEqual({ group: "feel", text: "fill · moving…" });
  });

  it("never reports negative tiles when the entry buffer evicts mid-window", () => {
    // A negative count would read as a bug in the map rather than as an undercount in the meter.
    let fill = onCameraMoveStart(newCameraFill(), 1000, 3000);
    fill = onCameraIdle(fill, 2000, 2990);
    expect(fill.last?.tilesFetched).toBe(0);
  });
});

describe("the Server-Timing HIT/MISS oracle is NOT used, and that is deliberate", () => {
  it("derives no cache verdict from serverTiming anywhere in this module", () => {
    // MEASURED, not assumed. Tiles ship `immutable` with a one-year max-age, so Cloudflare's edge
    // answers without running the Worker — and the stored response replays the Worker's header
    // verbatim. One tile fetched twice gave `cf-cache-status: HIT` both times, `age: 51949` on the
    // second, and a byte-identical `r2;dur=280;desc="1 read, 87954 B"`. Even the Worker's own
    // `X-Terrella-Cache` said `miss` on a response that never reached it. `r2` is also pushed
    // unconditionally, so "absent means HIT" was wrong twice over.
    //
    // If this module ever grows an r2-derived verdict, it will be confidently wrong on every
    // cached tile, which is most of them. Hence a guard rather than only a comment.
    const text = readFileSync(new URL("./perfNetwork.ts", import.meta.url), "utf8");
    // Only the code, not the header comment — which discusses `r2;dur` at length on purpose.
    const code = text.slice(text.indexOf('import { TERRAIN_PATH_PREFIX'));
    for (const forbidden of ['name === "r2"', 'name: "r2"', "edgeHit", "cacheHit", "r2;dur"]) {
      expect(code, `${forbidden} would revive a falsified oracle`).not.toContain(forbidden);
    }
  });
});
