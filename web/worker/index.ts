// The tile server: one tile per request, ranged out of a PMTiles archive in R2.
//
// TWO archives since Tier 3 step 3, in one bucket behind one router — `{z}/{x}/{y}.webp` is the
// relief pyramid and `terrain/{z}/{x}/{y}.webp` the elevation one. Everything below the router is
// archive-agnostic: the index prefetch, the directory cache and the ETag chain all key on the
// archive key, so the second pyramid cost a route and some per-key bookkeeping, not a second
// server.
//
// This is the production half of the pair whose dev half is the /tiles middleware in
// astro.config.ts. Both answer the same contract — parsed by the same reliefTiles.ts and
// terrainSource.ts — and differ only in where the bytes come from: a local file there, an R2
// binding here. The browser never opens an archive itself, because Workers Caching strips
// `Range` and would ask for the full multi-GB body.
//
// Written rather than adopted from protomaps/PMTiles `serverless/cloudflare`, which is
// `"private": true` and unpublished — adopting it means vendoring a fork of two files, not
// taking a dependency. What that worker gets right and a naive one would not, we take from the
// `pmtiles` library instead: the cross-request directory cache and the ETag guard below.
//.

import {
  Compression,
  EtagMismatch,
  PMTiles,
  ResolvedValueCache,
  type RangeResponse,
  type Source,
  bytesToHeader,
  tileTypeExt,
} from "pmtiles";
import {
  RELIEF_MAX_ZOOM,
  RELIEF_MIN_ZOOM,
  TILE_CONTENT_TYPE,
  type TileCoordinate,
  describeTileTypeMismatch,
  parseTilePath,
} from "../src/lib/reliefTiles";
import {
  TERRAIN_CONTENT_TYPE,
  TERRAIN_MAX_ZOOM,
  TERRAIN_MIN_ZOOM,
  describeTerrainTileTypeMismatch,
  parseTerrainTilePath,
} from "../src/lib/terrainSource";

interface Env {
  /** R2 binding for the bucket holding BOTH archives (bucket `terrella-tiles`). One binding, two
   *  keys: the archives differ by object, not by bucket, so a second binding would buy nothing
   *  and add a second place for the bucket name to drift. */
  ARCHIVE: R2Bucket;
  /** Object key of the relief archive within that bucket. */
  ARCHIVE_KEY?: string;
  /** Object key of the terrain-RGB archive within that bucket. */
  TERRAIN_ARCHIVE_KEY?: string;
  /** Origin allowed to read tiles — the site's own hostname. MapLibre uploads tiles as WebGL
   *  textures, so a cross-origin tile without CORS taints the canvas and never draws. */
  ALLOWED_ORIGIN?: string;
  /** Overrides the immutable default; see TILE_CACHE_CONTROL below. */
  TILE_CACHE_CONTROL?: string;
}

const DEFAULT_ARCHIVE_KEY = "planet.pmtiles";
const DEFAULT_TERRAIN_ARCHIVE_KEY = "terrain.pmtiles";

/** The pyramid is immutable for the life of a cut — the globe already sets
 *  `refreshExpiredTiles: false` on the same reasoning. A re-cut therefore requires purging the
 *  zone cache; that is the price of not paying revalidation on every tile forever. */
const DEFAULT_CACHE_CONTROL = "public, max-age=31536000, immutable";

/** Directory pages resolved by one request, reused by the next request this isolate serves.
 *  Without it every tile re-reads the root directory and a leaf from R2 before it can find its
 *  own bytes — three round trips per tile instead of one. Module scope is the point: the cache
 *  outlives the request.
 *
 *  Shared across both archives, which is safe because the library keys entries by
 *  `source.getKey()` (the archive key) plus the ETag, offset and length — so the two pyramids
 *  namespace themselves and cannot serve each other's directories.
 *
 *  50, raised from 25 when terrain shipped. 25 was sized for exactly one archive: each cut has
 *  **22 leaf directories** plus its header, so one fits with two entries to spare and two do not
 *  fit at all. Left at 25 the two would evict each other on every alternating request — which
 *  costs a gunzip and a deserialize rather than an R2 read (PrefetchedIndexSource already holds
 *  the bytes), so it would have shown up as nothing but a slightly slower Worker. */
const DIRECTORY_CACHE = new ResolvedValueCache(50, undefined, nativeDecompress);

/** Archive keys whose tile-type disagreement has already been logged — latched so a mismatch
 *  says so once per isolate rather than once per tile, since a global mismatch shouted 40,000
 *  times buries every other line in the log. Keyed rather than a boolean because a mismatch on
 *  the relief archive must not silence one on terrain, where the consequence is worse. */
const warnedTileTypeMismatch = new Set<string>();

/** How much of the archive's front to pull in one read so that EVERY directory lookup is served
 *  from memory instead of from R2.
 *
 *  A PMTiles archive is laid out header → root directory → JSON metadata → leaf directories →
 *  tile data, so `tileDataOffset` is the exact size of "everything that is not a tile". For the
 *  shipped planet cut that is **196,621 bytes** — root is 111 B, every leaf together is 196,285 B.
 *  The whole index is smaller than one mid-zoom tile.
 *
 *  Without this the library reads three times per cold tile: `[0,16384)` for header+root (it
 *  slices both out of one read, then DISCARDS the leaf bytes it already paid for), then a ~10 KB
 *  leaf, then the tile. Those reads are LATENCY-bound, not bandwidth-bound — 10 KB and 138 KB both
 *  land in 250–700 ms, because the bucket is APAC and the Worker runs wherever the request landed.
 *  So collapsing two round trips into one costs almost nothing and saves almost everything.
 *
 *  256 KiB, not 196,621: a constant sized exactly to today's archive would silently degrade the
 *  first time a re-cut grew the index. The headroom is ~33%, and `warnIfIndexOutgrewPrefetch`
 *  turns "silently degraded" into a log line if a future cut ever exceeds it. */
export const INDEX_PREFETCH_BYTES = 262_144;

/** Latched per isolate, per archive; see INDEX_PREFETCH_BYTES. */
const warnedIndexOutgrewPrefetch = new Set<string>();

/** Read the archive's own `tileDataOffset` out of the bytes we already hold and complain if the
 *  index no longer fits. Costs one header parse per isolate and nothing per request — the point is
 *  that the failure mode it guards is invisible: everything keeps WORKING, just three reads deep
 *  again, which looks exactly like the problem this constant was introduced to fix. */
function warnIfIndexOutgrewPrefetch(index: ArrayBuffer, archiveKey: string): void {
  if (warnedIndexOutgrewPrefetch.has(archiveKey) || index.byteLength < 127) return;
  const tileDataOffset = bytesToHeader(index.slice(0, 127)).tileDataOffset;
  if (tileDataOffset > index.byteLength) {
    warnedIndexOutgrewPrefetch.add(archiveKey);
    console.warn(
      `${archiveKey}: index is ${tileDataOffset} B but INDEX_PREFETCH_BYTES is ` +
        `${INDEX_PREFETCH_BYTES} — leaf reads are falling through to R2 again. Raise it in ` +
        `web/worker/index.ts.`,
    );
  }
}

/** Decompress with the platform's own stream rather than the library's bundled fallback, which
 *  would pull fflate into a Worker that already has DecompressionStream. */
async function nativeDecompress(buffer: ArrayBuffer, compression: Compression): Promise<ArrayBuffer> {
  if (compression === Compression.None || compression === Compression.Unknown) return buffer;
  if (compression === Compression.Gzip) {
    const decompressed = new Response(buffer).body?.pipeThrough(new DecompressionStream("gzip"));
    return new Response(decompressed).arrayBuffer();
  }
  throw new Error(`Unsupported PMTiles internal compression: ${compression}`);
}

class ArchiveNotFound extends Error {}

/** One range read against R2, as observed. */
interface ArchiveRead {
  ms: number;
  bytes: number;
}

/** What a single request spent, split at the boundaries that can actually differ.
 *
 *  A Worker's clock only advances on I/O (Cloudflare's timing-attack mitigation), so these
 *  numbers are I/O time and nothing else — pure CPU between two awaits reads as 0. That suits
 *  the question being asked (is the cold path all R2?) and would be useless for a CPU one. */
interface RequestTiming {
  startedAt: number;
  cacheLookupMs: number | null;
  reads: ArchiveRead[];
}

/** Adapts an R2 binding to the byte-range interface the PMTiles reader wants.
 *
 *  Constructed per request, which is what makes `timing` a per-request record while
 *  DIRECTORY_CACHE stays module-scope — so a directory served from that cache produces NO entry
 *  here, and the read count alone says whether the isolate was warm. */
class R2ArchiveSource implements Source {
  constructor(
    private readonly bucket: R2Bucket,
    private readonly key: string,
    private readonly timing: RequestTiming,
  ) {}

  getKey(): string {
    return this.key;
  }

  async getBytes(
    offset: number,
    length: number,
    _signal?: AbortSignal,
    etag?: string,
  ): Promise<RangeResponse> {
    const startedAt = Date.now();
    let bytes = 0;
    // Recorded in `finally` so a read that THREW still appears. Counting only successes would
    // report "0 reads" for a request that spent a full round trip discovering the archive was
    // missing — an instrument that reads as "did nothing" when it did the expensive thing.
    try {
      // `onlyIf` is the load-bearing part. A cached directory entry is a byte OFFSET, and offsets
      // are meaningless against a different archive — so if the pyramid is re-cut and re-uploaded
      // while an isolate holds warm directories, reading at those offsets would return real bytes
      // from the wrong place and serve a corrupt tile with a 200. Instead R2 refuses the read when
      // the ETag has moved, and PMTiles.getZxy catches EtagMismatch, drops its cache and retries.
      const object = await this.bucket.get(this.key, {
        range: { offset, length },
        onlyIf: { etagMatches: etag },
      });
      if (!object) throw new ArchiveNotFound(`No ${this.key} in the bound bucket`);

      const body = object as R2ObjectBody;
      if (!body.body) throw new EtagMismatch();

      // Timed around the arrayBuffer() too, not just the get(): `get` resolves on headers, so
      // stopping there would measure the round trip and charge the body transfer to nobody.
      const data = await body.arrayBuffer();
      bytes = data.byteLength;

      return {
        data,
        etag: object.etag,
        cacheControl: object.httpMetadata?.cacheControl,
        expires: object.httpMetadata?.cacheExpiry?.toISOString(),
      };
    } finally {
      this.timing.reads.push({ ms: Date.now() - startedAt, bytes });
    }
  }
}

/** The archive's index, plus the ETag it was read under. The ETag travels WITH the bytes because
 *  the two are only meaningful together: an offset from one cut applied to another cut's bytes
 *  reads real data from the wrong place and serves a corrupt tile with a 200. Handing this ETag
 *  back to the library means every subsequent tile read carries `onlyIf`, so a swapped archive
 *  fails loudly (412 → EtagMismatch → refetch) instead of quietly. */
export interface ArchiveIndex {
  bytes: ArrayBuffer;
  etag: string;
}

/** Serves any read that lies entirely inside the prefetched index from memory, and everything
 *  else — which is every tile — from R2.
 *
 *  The test is purely by RANGE, so this wrapper never needs to know what a directory is: the
 *  library asks for `[0,16384)` and then a leaf somewhere below `tileDataOffset`, and both fall
 *  inside the prefetch. A read that straddles or exceeds the span falls through to R2 unchanged,
 *  which is what makes an undersized INDEX_PREFETCH_BYTES a slowdown rather than a failure. */
export class PrefetchedIndexSource implements Source {
  constructor(
    private readonly inner: R2ArchiveSource,
    private readonly index: ArchiveIndex,
  ) {}

  getKey(): string {
    return this.inner.getKey();
  }

  async getBytes(
    offset: number,
    length: number,
    signal?: AbortSignal,
    etag?: string,
  ): Promise<RangeResponse> {
    const servableFromIndex = offset >= 0 && offset + length <= this.index.bytes.byteLength;
    // A stale prefetch must not be papered over. If the caller names an ETag that is not the one
    // this index was read under, the archive moved: fall through to R2, which answers 412 and
    // starts the library's own recovery, rather than returning bytes from the superseded cut.
    if (servableFromIndex && (etag === undefined || etag === this.index.etag)) {
      return { data: this.index.bytes.slice(offset, offset + length), etag: this.index.etag };
    }
    return this.inner.getBytes(offset, length, signal, etag);
  }
}

/** `Server-Timing`, so the cold path can be split from outside instead of guessed at. Readable
 *  by `curl` and — because Timing-Allow-Origin now ships — by the page itself, through
 *  `PerformanceResourceTiming.serverTiming`.
 *
 *  `r2` counts reads as well as milliseconds because the two answers are different diagnoses:
 *  three reads means a cold isolate walking header → leaf → tile, one means the directory cache
 *  did its job and the time is a single long-haul fetch. */
function serverTimingHeader(timing: RequestTiming): string {
  const metrics: string[] = [];
  if (timing.cacheLookupMs !== null) metrics.push(`cache;dur=${timing.cacheLookupMs}`);
  const readMs = timing.reads.reduce((total, read) => total + read.ms, 0);
  const readBytes = timing.reads.reduce((total, read) => total + read.bytes, 0);
  const label = timing.reads.length === 1 ? "read" : "reads";
  // The per-read split only says something once there is more than one — with a single read it
  // just repeats `dur`, and a diagnostic that repeats itself is one people stop reading.
  const split = timing.reads.length > 1 ? ` (${timing.reads.map((read) => read.ms).join("+")})` : "";
  metrics.push(`r2;dur=${readMs};desc="${timing.reads.length} ${label}${split}, ${readBytes} B"`);
  metrics.push(`worker;dur=${Date.now() - timing.startedAt}`);
  return metrics.join(", ");
}

/** Applied on the way out, never stored — for the same reason as the cross-origin headers, and
 *  it matters more here: a stored `Server-Timing` would let a cache HIT replay the timings of
 *  the MISS that filled it, which is worse than no instrument at all. */
function withServerTiming(response: Response, timing: RequestTiming): Response {
  const headers = new Headers(response.headers);
  headers.set("Server-Timing", serverTimingHeader(timing));
  return new Response(response.body, { status: response.status, headers });
}

/** Marks where the body came from, so a deploy can be verified rather than assumed. */
function tagCache(response: Response, state: "hit" | "miss"): Response {
  const headers = new Headers(response.headers);
  headers.set("X-Terrella-Cache", state);
  return new Response(response.body, { status: response.status, headers });
}

/** In-isolate hold on each archive's index, so a burst of tiles shares ONE fetch instead of racing
 *  to do the same work. A promise rather than a value: the second tile through arrives while the
 *  first is still awaiting R2, and awaiting the same promise is what makes it free rather than
 *  duplicated. Keyed by archive key, so the re-cut convention (a new key per cut) retires an entry
 *  automatically.
 *
 *  A MAP rather than the single slot this was before terrain shipped. Terrain and relief tiles
 *  arrive interleaved for the whole of a Tier-3 session, so one slot would have been re-keyed on
 *  practically every request — re-fetching 256 KiB from R2 each time, i.e. the exact cost this
 *  hold exists to remove, while still looking like it was working. */
const indexInFlight = new Map<string, Promise<ArchiveIndex | null>>();

/** The index's cache entry lives on this Worker's own hostname under a path `parseTilePath`
 *  rejects, so it can never be reached from outside — a request for it 404s at the router above,
 *  before the cache is consulted. Keyed by archive key because a re-cut ships under a new one. */
function indexCacheUrl(request: Request, archiveKey: string): string {
  return new URL(`/__pmtiles-index/${encodeURIComponent(archiveKey)}`, request.url).toString();
}

/** Fetch the archive's whole index — once per isolate, once per colo — or null if it cannot be
 *  read, in which case the caller falls back to reading directly from R2 exactly as before.
 *
 *  Null rather than throw is deliberate: this is an OPTIMISATION, and a Worker that 500s every
 *  tile because a cache entry misbehaved would be strictly worse than the three-read path it
 *  replaced. The only hard failure it forwards is "archive missing", which the caller already
 *  handles — anything else degrades to the old behaviour. */
async function loadArchiveIndex(
  bucket: R2Bucket,
  archiveKey: string,
  r2Source: R2ArchiveSource,
  cache: Cache,
  ctx: ExecutionContext,
  request: Request,
): Promise<ArchiveIndex | null> {
  const held = indexInFlight.get(archiveKey);
  if (held) return held;

  const index = (async (): Promise<ArchiveIndex | null> => {
    const cacheUrl = indexCacheUrl(request, archiveKey);
    try {
      const cached = await cache.match(cacheUrl);
      const cachedEtag = cached?.headers.get("ETag");
      if (cached && cachedEtag) {
        const bytes = await cached.arrayBuffer();
        warnIfIndexOutgrewPrefetch(bytes, archiveKey);
        return { bytes, etag: cachedEtag };
      }
    } catch {
      // A cache read that failed is a cache miss. Fall through to R2.
    }

    const read = await r2Source.getBytes(0, INDEX_PREFETCH_BYTES);
    if (!read.etag) return null; // No ETag means no staleness guard; refuse to hold the bytes.
    warnIfIndexOutgrewPrefetch(read.data, archiveKey);

    // Stored WITH its ETag, which is what lets a later isolate hand the pair to the library and
    // keep the `onlyIf` chain intact. Immutable: the key changes when the archive does.
    const headers = new Headers({
      ETag: read.etag,
      "Cache-Control": "public, max-age=31536000, immutable",
      "Content-Type": "application/octet-stream",
    });
    ctx.waitUntil(cache.put(cacheUrl, new Response(read.data, { headers })));
    return { bytes: read.data, etag: read.etag };
  })().catch((error: unknown) => {
    // An isolate must not be left holding a rejected promise forever — the next request would
    // inherit this failure instead of retrying. Clear the hold, then let the caller degrade.
    indexInFlight.delete(archiveKey);
    if (error instanceof ArchiveNotFound) throw error;
    return null;
  });

  indexInFlight.set(archiveKey, index);
  return index;
}

/** Cross-origin response headers, applied on the way out and never stored — so one cached entry
 *  serves every origin and the allowlist can change without a purge. `Vary: Origin` keeps
 *  intermediaries honest.
 *
 *  `Timing-Allow-Origin` is `*` even though ACAO is narrowed, because they answer different
 *  questions: ACAO decides who may read a tile, TAO only who may read the TIMING of a fetch
 *  already made. Without it Resource Timing reports `transferSize` and `decodedBodySize` as 0 —
 *  blind in the direction that reads as "free" rather than as "unknown" — and narrowing it to
 *  ALLOWED_ORIGIN would re-blind every vantage that is not the production page, which is exactly
 *  where measuring happens. A constant value, so it adds nothing to the cache key. */
function withCrossOriginHeaders(
  response: Response,
  env: Env,
  requestOrigin: string | null,
): Response {
  const headers = new Headers(response.headers);
  const allowed = env.ALLOWED_ORIGIN;
  if (allowed && (allowed === "*" || allowed === requestOrigin)) {
    headers.set("Access-Control-Allow-Origin", allowed);
  }
  headers.set("Vary", "Origin");
  headers.set("Timing-Allow-Origin", "*");
  return new Response(response.body, { status: response.status, headers });
}

/** One resolved request: which tile, out of which archive, labelled and decoded how. */
interface TileRoute {
  tile: TileCoordinate;
  archiveKey: string;
  contentType: string;
  /** Names the constants a zoom disagreement should send someone to. */
  zoomConstants: string;
  describeTileTypeMismatch: (archiveExtension: string) => string | null;
}

/**
 * Decide which pyramid a path addresses, or null if it addresses neither.
 *
 * THE PREFIX IS THE WHOLE DISCRIMINATOR AND IT HAS TO BE. Both archives are lossless WebP over
 * z0-8 on the same tiling scheme, so `/8/189/107.webp` is a valid address in both — there is
 * nothing else in a tile URL left to tell them apart. Serving the wrong one is not a visible
 * failure either: MapLibre would decode relief colour as terrarium elevation and displace the
 * globe by whatever those bytes happen to mean.
 *
 * The two parsers cannot both match, in either direction: `parseTilePath` requires the first
 * segment to be a zoom, and `parseTerrainTilePath` requires the literal prefix.
 */
export function resolveRoute(pathname: string, env: Env): TileRoute | null {
  const relief = parseTilePath(pathname);
  if (relief) {
    return {
      tile: relief,
      archiveKey: env.ARCHIVE_KEY ?? DEFAULT_ARCHIVE_KEY,
      contentType: TILE_CONTENT_TYPE,
      zoomConstants: `RELIEF_MIN_ZOOM/RELIEF_MAX_ZOOM (z${RELIEF_MIN_ZOOM}-z${RELIEF_MAX_ZOOM}) in web/src/lib/reliefTiles.ts`,
      describeTileTypeMismatch,
    };
  }
  const terrain = parseTerrainTilePath(pathname);
  if (terrain) {
    return {
      tile: terrain,
      archiveKey: env.TERRAIN_ARCHIVE_KEY ?? DEFAULT_TERRAIN_ARCHIVE_KEY,
      contentType: TERRAIN_CONTENT_TYPE,
      zoomConstants: `TERRAIN_MIN_ZOOM/TERRAIN_MAX_ZOOM (z${TERRAIN_MIN_ZOOM}-z${TERRAIN_MAX_ZOOM}) in web/src/lib/terrainSource.ts`,
      describeTileTypeMismatch: describeTerrainTileTypeMismatch,
    };
  }
  return null;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const requestOrigin = request.headers.get("Origin");
    const timing: RequestTiming = { startedAt: Date.now(), cacheLookupMs: null, reads: [] };

    /** The single exit. Everything applied here is computed per request and never stored, so a
     *  cached body carries this request's CORS decision and this request's timings — not the
     *  ones frozen into the response that filled the cache. */
    const respond = (response: Response) =>
      withServerTiming(withCrossOriginHeaders(response, env, requestOrigin), timing);

    if (request.method !== "GET" && request.method !== "HEAD") {
      return respond(new Response("Method not allowed", { status: 405 }));
    }

    // Rejected before any R2 read: a typo'd URL must not cost a range read on a 16 GB object.
    // An optional leading /v<N>/ is tolerated and ignored. Nothing requires it today, but it
    // means a future re-cut can ship under a NEW base URL instead of purging the cache — and
    // purge is zone-wide, so on a shared zone it would evict everything else on alchez.dev too.
    // Tolerating it now costs one regex; retrofitting it later costs a purge.
    const route = resolveRoute(new URL(request.url).pathname.replace(/^\/v\d+\//, "/"), env);
    if (!route) {
      return respond(new Response("Not a tile path", { status: 404 }));
    }
    const { tile, archiveKey } = route;

    const cache = caches.default;
    const cacheLookupStartedAt = Date.now();
    const hit = await cache.match(request.url);
    timing.cacheLookupMs = Date.now() - cacheLookupStartedAt;
    // An explicit marker, because `cf-cache-status` describes Cloudflare's own edge cache and
    // says nothing about a Cache API hit inside the Worker — the thing we actually want to see.
    if (hit) return respond(tagCache(hit, "hit"));

    const r2Source = new R2ArchiveSource(env.ARCHIVE, archiveKey, timing);

    /** Store in the edge cache, then serve. The body is an ArrayBuffer, so the two Responses can
     *  share it. `waitUntil` keeps the put off the response's critical path. */
    const store = (body: ArrayBuffer | string | null, status: number, contentType?: string) => {
      const headers = new Headers();
      if (contentType) headers.set("Content-Type", contentType);
      headers.set("Cache-Control", env.TILE_CACHE_CONTROL ?? DEFAULT_CACHE_CONTROL);
      ctx.waitUntil(cache.put(request.url, new Response(body, { status, headers })));
      return respond(tagCache(new Response(body, { status, headers }), "miss"));
    };

    // THE INDEX LOAD IS INSIDE THIS TRY, AND THAT IS THE WHOLE POINT OF WHERE THE BRACE SITS.
    // `loadArchiveIndex` is the FIRST thing to touch R2 on a cold request, so a missing or
    // mis-keyed archive throws ArchiveNotFound here — before `getHeader` is ever reached. With
    // the try starting below it, that throw escaped the handler written to answer it and became
    // an unhandled rejection, i.e. a 500 on every tile in the world where a 404 was intended.
    try {
      // The index is fetched whole, once, and then reused three ways: within this request, across
      // requests in this isolate (DIRECTORY_CACHE), and across isolates (the Cache API entry below,
      // which is colo-local and long-lived — live tiles come back with `age` in the tens of
      // thousands of seconds, far longer than any isolate survives).
      const index = await loadArchiveIndex(env.ARCHIVE, archiveKey, r2Source, cache, ctx, request);
      const archive = new PMTiles(
        index ? new PrefetchedIndexSource(r2Source, index) : r2Source,
        DIRECTORY_CACHE,
        nativeDecompress,
      );

      const header = await archive.getHeader();

      // The globe hardcodes the zoom range so it can request z0 without a round trip first
      // (RELIEF_MIN_ZOOM/RELIEF_MAX_ZOOM). Here the archive is the authority, and disagreement
      // is a 404 plus a log line — NOT the throw assertZoomRange() raises in the dev server.
      // A dev server should refuse to start on drift; a live tile server should serve what it
      // has and make the drift visible, rather than 500 every tile in the world.
      if (tile.z < header.minZoom || tile.z > header.maxZoom) {
        console.warn(
          `z${tile.z} requested but ${archiveKey} covers z${header.minZoom}-z${header.maxZoom} — ` +
            `${route.zoomConstants} is stale`,
        );
        return store(null, 404);
      }

      // Encoding drift gets a warning and nothing else. Unlike a zoom outside the archive, the
      // bytes here are servable — only the label is wrong, and browsers content-sniff past it.
      // 404ing the planet over a mislabel would be a self-inflicted outage; the dev server's
      // throw is where this is meant to be caught, and this is the net under it.
      if (!warnedTileTypeMismatch.has(archiveKey)) {
        const mismatch = route.describeTileTypeMismatch(tileTypeExt(header.tileType));
        if (mismatch) {
          warnedTileTypeMismatch.add(archiveKey);
          console.warn(`${archiveKey}: ${mismatch}`);
        }
      }

      const entry = await archive.getZxy(tile.z, tile.x, tile.y);
      // Both pyramids are complete (87,381 addresses each, z0-z8), so a miss means the packaging
      // is wrong, not that the region is empty. 404 rather than an empty 200, so it is visible.
      if (!entry) return store(null, 404);

      return store(entry.data, 200, route.contentType);
    } catch (error) {
      if (error instanceof ArchiveNotFound) {
        console.error(`${archiveKey} missing from the bound bucket`);
        return respond(new Response("Archive not found", { status: 404 }));
      }
      throw error;
    }
  },
};
