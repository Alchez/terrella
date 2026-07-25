// The relief tile server: one tile per request, ranged out of the PMTiles archive in R2.
//
// This is the production half of the pair whose dev half is the /tiles middleware in
// astro.config.ts. Both answer the same contract — `{z}/{x}/{y}.webp`, parsed by the same
// reliefTiles.ts — and differ only in where the bytes come from: a local file there, an R2
// binding here. The browser never opens the archive itself, because Workers Caching strips
// `Range` and would ask for the full 16 GB body (→ HISTORY § the deploy target moves to R2).
//
// Written rather than adopted from protomaps/PMTiles `serverless/cloudflare`, which is
// `"private": true` and unpublished — adopting it means vendoring a fork of two files, not
// taking a dependency. What that worker gets right and a naive one would not, we take from the
// `pmtiles` library instead: the cross-request directory cache and the ETag guard below.
// → HISTORY § the tile Worker is ours.

import {
  Compression,
  EtagMismatch,
  PMTiles,
  ResolvedValueCache,
  type RangeResponse,
  type Source,
} from "pmtiles";
import { TILE_CONTENT_TYPE, parseTilePath } from "../src/lib/reliefTiles";

interface Env {
  /** R2 binding for the bucket holding the archive (bucket `terrella-tiles`). */
  ARCHIVE: R2Bucket;
  /** Object key of the archive within that bucket. */
  ARCHIVE_KEY?: string;
  /** Origin allowed to read tiles — the site's own hostname. MapLibre uploads tiles as WebGL
   *  textures, so a cross-origin tile without CORS taints the canvas and never draws. */
  ALLOWED_ORIGIN?: string;
  /** Overrides the immutable default; see TILE_CACHE_CONTROL below. */
  TILE_CACHE_CONTROL?: string;
}

const DEFAULT_ARCHIVE_KEY = "planet.pmtiles";

/** The pyramid is immutable for the life of a cut — the globe already sets
 *  `refreshExpiredTiles: false` on the same reasoning. A re-cut therefore requires purging the
 *  zone cache; that is the price of not paying revalidation on every tile forever. */
const DEFAULT_CACHE_CONTROL = "public, max-age=31536000, immutable";

/** Directory pages resolved by one request, reused by the next request this isolate serves.
 *  Without it every tile re-reads the root directory and a leaf from R2 before it can find its
 *  own bytes — three round trips per tile instead of one. Module scope is the point: the cache
 *  outlives the request. */
const DIRECTORY_CACHE = new ResolvedValueCache(25, undefined, nativeDecompress);

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
    const tile = parseTilePath(new URL(request.url).pathname.replace(/^\/v\d+\//, "/"));
    if (!tile) {
      return respond(new Response("Not a tile path", { status: 404 }));
    }

    const cache = caches.default;
    const cacheLookupStartedAt = Date.now();
    const hit = await cache.match(request.url);
    timing.cacheLookupMs = Date.now() - cacheLookupStartedAt;
    // An explicit marker, because `cf-cache-status` describes Cloudflare's own edge cache and
    // says nothing about a Cache API hit inside the Worker — the thing we actually want to see.
    if (hit) return respond(tagCache(hit, "hit"));

    const archiveKey = env.ARCHIVE_KEY ?? DEFAULT_ARCHIVE_KEY;
    const archive = new PMTiles(
      new R2ArchiveSource(env.ARCHIVE, archiveKey, timing),
      DIRECTORY_CACHE,
      nativeDecompress,
    );

    /** Store in the edge cache, then serve. The body is an ArrayBuffer, so the two Responses can
     *  share it. `waitUntil` keeps the put off the response's critical path. */
    const store = (body: ArrayBuffer | string | null, status: number, contentType?: string) => {
      const headers = new Headers();
      if (contentType) headers.set("Content-Type", contentType);
      headers.set("Cache-Control", env.TILE_CACHE_CONTROL ?? DEFAULT_CACHE_CONTROL);
      ctx.waitUntil(cache.put(request.url, new Response(body, { status, headers })));
      return respond(tagCache(new Response(body, { status, headers }), "miss"));
    };

    try {
      const header = await archive.getHeader();

      // The globe hardcodes the zoom range so it can request z0 without a round trip first
      // (RELIEF_MIN_ZOOM/RELIEF_MAX_ZOOM). Here the archive is the authority, and disagreement
      // is a 404 plus a log line — NOT the throw assertZoomRange() raises in the dev server.
      // A dev server should refuse to start on drift; a live tile server should serve what it
      // has and make the drift visible, rather than 500 every tile in the world.
      if (tile.z < header.minZoom || tile.z > header.maxZoom) {
        console.warn(
          `z${tile.z} requested but ${archiveKey} covers z${header.minZoom}-z${header.maxZoom} — ` +
            `RELIEF_MIN_ZOOM/RELIEF_MAX_ZOOM in web/src/lib/reliefTiles.ts are stale`,
        );
        return store(null, 404);
      }

      const entry = await archive.getZxy(tile.z, tile.x, tile.y);
      // The pyramid is complete (87,381 addresses, z0-z8), so a miss means the packaging is
      // wrong, not that the region is empty. 404 rather than an empty 200, so it is visible.
      if (!entry) return store(null, 404);

      return store(entry.data, 200, TILE_CONTENT_TYPE);
    } catch (error) {
      if (error instanceof ArchiveNotFound) {
        console.error(`${archiveKey} missing from the bound bucket`);
        return respond(new Response("Archive not found", { status: 404 }));
      }
      throw error;
    }
  },
};
