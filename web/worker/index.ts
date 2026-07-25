// The relief tile server: one PNG per request, ranged out of the 16 GB PMTiles archive in R2.
//
// This is the production half of the pair whose dev half is the /tiles middleware in
// astro.config.ts. Both answer the same contract — `{z}/{x}/{y}.png`, parsed by the same
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
import { parseTilePath } from "../src/lib/reliefTiles";

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

/** Adapts an R2 binding to the byte-range interface the PMTiles reader wants. */
class R2ArchiveSource implements Source {
  constructor(
    private readonly bucket: R2Bucket,
    private readonly key: string,
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

    return {
      data: await body.arrayBuffer(),
      etag: object.etag,
      cacheControl: object.httpMetadata?.cacheControl,
      expires: object.httpMetadata?.cacheExpiry?.toISOString(),
    };
  }
}

/** Marks where the body came from, so a deploy can be verified rather than assumed. */
function tagCache(response: Response, state: "hit" | "miss"): Response {
  const headers = new Headers(response.headers);
  headers.set("X-Terrella-Cache", state);
  return new Response(response.body, { status: response.status, headers });
}

/** CORS is applied on the way out, never stored — so one cached entry serves every origin and
 *  the allowlist can change without a purge. `Vary: Origin` keeps intermediaries honest. */
function withCors(response: Response, env: Env, requestOrigin: string | null): Response {
  const headers = new Headers(response.headers);
  const allowed = env.ALLOWED_ORIGIN;
  if (allowed && (allowed === "*" || allowed === requestOrigin)) {
    headers.set("Access-Control-Allow-Origin", allowed);
  }
  headers.set("Vary", "Origin");
  return new Response(response.body, { status: response.status, headers });
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const requestOrigin = request.headers.get("Origin");
    if (request.method !== "GET" && request.method !== "HEAD") {
      return withCors(new Response("Method not allowed", { status: 405 }), env, requestOrigin);
    }

    // Rejected before any R2 read: a typo'd URL must not cost a range read on a 16 GB object.
    // An optional leading /v<N>/ is tolerated and ignored. Nothing requires it today, but it
    // means a future re-cut can ship under a NEW base URL instead of purging the cache — and
    // purge is zone-wide, so on a shared zone it would evict everything else on alchez.dev too.
    // Tolerating it now costs one regex; retrofitting it later costs a purge.
    const tile = parseTilePath(new URL(request.url).pathname.replace(/^\/v\d+\//, "/"));
    if (!tile) {
      return withCors(new Response("Not a tile path", { status: 404 }), env, requestOrigin);
    }

    const cache = caches.default;
    const hit = await cache.match(request.url);
    // An explicit marker, because `cf-cache-status` describes Cloudflare's own edge cache and
    // says nothing about a Cache API hit inside the Worker — the thing we actually want to see.
    if (hit) return withCors(tagCache(hit, "hit"), env, requestOrigin);

    const archiveKey = env.ARCHIVE_KEY ?? DEFAULT_ARCHIVE_KEY;
    const archive = new PMTiles(
      new R2ArchiveSource(env.ARCHIVE, archiveKey),
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
      return withCors(tagCache(new Response(body, { status, headers }), "miss"), env, requestOrigin);
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

      return store(entry.data, 200, "image/png");
    } catch (error) {
      if (error instanceof ArchiveNotFound) {
        console.error(`${archiveKey} missing from the bound bucket`);
        return withCors(new Response("Archive not found", { status: 404 }), env, requestOrigin);
      }
      throw error;
    }
  },
};
