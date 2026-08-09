// The index prefetch: the Worker pulls the archive's whole directory region in ONE read and
// serves every directory lookup out of it, so a cold tile costs one R2 round trip instead of
// three. These tests pin the part that decides which reads are free — because the failure mode
// is not a crash, it is a silent return to three reads that nothing would notice.

import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RangeResponse, Source } from "pmtiles";
import worker, {
  INDEX_PREFETCH_BYTES,
  PrefetchedIndexSource,
  directoryCacheEntries,
  resolveRoute,
} from "./index";
import { TILE_CONTENT_TYPE } from "../src/lib/reliefTiles";
import { TERRAIN_CONTENT_TYPE } from "../src/lib/terrainSource";
import { VECTOR_CONTENT_TYPE } from "../src/lib/vectorTiles";
import { PUBLISHED, archiveFor, tilePathTemplate } from "../src/lib/tileAddress";

/** What one body's published archives cost the Worker's directory cache: a header entry, a root
 *  entry, and one per leaf directory. Restated here rather than imported because the point of the
 *  tests below is to check the Worker's own arithmetic against an independent statement of it. */
const directoryCacheCostOf = (
  layers: Record<string, { indexLeaves: number } | null>,
): number =>
  Object.values(layers)
    .filter((archive) => archive !== null)
    .reduce((total, archive) => total + 2 + archive.indexLeaves, 0);

const INDEX_ETAG = "etag-of-the-shipped-cut";

/** Stands in for R2. Records every call so a test can assert a read did NOT happen — the whole
 *  point of the prefetch is reads that never occur, which only a call counter can see. */
function fakeR2Source(): Source & { calls: { offset: number; length: number }[] } {
  const calls: { offset: number; length: number }[] = [];
  return {
    calls,
    getKey: () => "planet-v2.pmtiles",
    async getBytes(offset: number, length: number): Promise<RangeResponse> {
      calls.push({ offset, length });
      // Byte value encodes position, so a caller can prove WHICH bytes it got, not just how many.
      const data = new Uint8Array(length).map((_, index) => (offset + index) % 251);
      return { data: data.buffer, etag: INDEX_ETAG };
    },
  };
}

/** An index blob whose byte at position i is `i % 251`, matching fakeR2Source, so a slice served
 *  from memory and the same slice served from R2 are directly comparable. */
function indexBytes(length = INDEX_PREFETCH_BYTES): ArrayBuffer {
  return new Uint8Array(length).map((_, index) => index % 251).buffer;
}

function subject(length?: number) {
  const inner = fakeR2Source();
  const source = new PrefetchedIndexSource(
    inner as never,
    { bytes: indexBytes(length), etag: INDEX_ETAG },
  );
  return { inner, source };
}

/** Just the z/x/y of an address, so two routes can be compared on where they point without
 *  their archive keys — which are exactly what must differ. */
const coordinates = ({ z, x, y }: { z: number; x: number; y: number }) => ({ z, x, y });

/** A cache that always answers, with the Content-Type a stored tile carries. */
function hittingCache(): FakeCache {
  return {
    match: vi.fn(async () => new Response("tile-bytes", { headers: { "Content-Type": "image/webp" } })),
    put: vi.fn(async () => undefined),
  };
}

/** The same always-hitting cache with a bare body — for the CORS tests, where the headers under
 *  test are the ones the Worker adds, not the ones the cache stored. */
const hit = () => ({
  match: vi.fn(async () => new Response("tile-bytes")),
  put: vi.fn(async () => undefined),
});

describe("PrefetchedIndexSource", () => {
  it("serves the header read from memory — no R2 call at all", async () => {
    const { inner, source } = subject();
    // [0, 16384) is exactly what pmtiles asks for first: header + root directory in one read.
    const read = await source.getBytes(0, 16384);
    expect(inner.calls).toHaveLength(0);
    expect(read.data.byteLength).toBe(16384);
  });

  it("serves a leaf directory from memory, and returns the RIGHT bytes", async () => {
    const { inner, source } = subject();
    // A leaf lives somewhere between the root and tileDataOffset; 40000 is inside the prefetch.
    const read = await source.getBytes(40_000, 10_000);
    expect(inner.calls).toHaveLength(0);
    const bytes = new Uint8Array(read.data);
    // Correct offset, not merely correct length — an off-by-one here would serve a valid-looking
    // directory from the wrong place, which is the failure this whole ETag dance exists to prevent.
    expect(bytes[0]).toBe(40_000 % 251);
    expect(bytes[9_999]).toBe(49_999 % 251);
  });

  it("forwards a tile read to R2 — tiles live past the prefetch and must not be faked", async () => {
    const { inner, source } = subject();
    await source.getBytes(5_000_000, 148_434, undefined, INDEX_ETAG);
    expect(inner.calls).toEqual([{ offset: 5_000_000, length: 148_434 }]);
  });

  it("forwards a read that STRADDLES the end of the prefetch", async () => {
    const { inner, source } = subject(1_000);
    // Half in, half out. Serving the in-range half would silently truncate the caller's data.
    await source.getBytes(900, 200);
    expect(inner.calls).toEqual([{ offset: 900, length: 200 }]);
  });

  it("serves the boundary read exactly at the end of the span from memory", async () => {
    const { inner, source } = subject(1_000);
    await source.getBytes(900, 100); // ends at exactly 1000 — still inside
    expect(inner.calls).toHaveLength(0);
  });

  it("forwards to R2 when the caller names a DIFFERENT ETag — the staleness guard", async () => {
    const { inner, source } = subject();
    // The library carries the ETag it learned from the header. If that no longer matches the one
    // this index was read under, the archive was swapped: these offsets describe the wrong bytes.
    // Falling through lets R2 answer 412, which is what starts the library's recovery.
    await source.getBytes(0, 16_384, undefined, "etag-of-a-different-cut");
    expect(inner.calls).toEqual([{ offset: 0, length: 16_384 }]);
  });

  it("serves from memory when the caller names no ETag yet", async () => {
    const { inner, source } = subject();
    // The very first read cannot name an ETag — it is the read that discovers it.
    await source.getBytes(0, 127, undefined, undefined);
    expect(inner.calls).toHaveLength(0);
  });

  it("reports the index's ETag on a memory-served read, so the chain stays intact", async () => {
    const { source } = subject();
    const read = await source.getBytes(0, 127);
    expect(read.etag).toBe(INDEX_ETAG);
  });

  it("passes the abort signal through on a forwarded read", async () => {
    const inner = fakeR2Source();
    const spy = vi.spyOn(inner, "getBytes");
    const source = new PrefetchedIndexSource(inner as never, {
      bytes: indexBytes(1_000),
      etag: INDEX_ETAG,
    });
    const controller = new AbortController();
    await source.getBytes(50_000, 10, controller.signal, INDEX_ETAG);
    expect(spy.mock.calls[0]?.[2]).toBe(controller.signal);
  });

  it("keeps the archive key of the source it wraps", () => {
    const { source } = subject();
    expect(source.getKey()).toBe("planet-v2.pmtiles");
  });
});

describe("INDEX_PREFETCH_BYTES", () => {
  it("covers the shipped planet cut's index with headroom", () => {
    // Measured from the shipped archive header: tileDataOffset = 196,621 (root 111 B at 127,
    // leaves 196,285 B at 336). A constant sized to exactly that would degrade silently on the
    // first re-cut that grew the index; this asserts the headroom is real and deliberate.
    const SHIPPED_INDEX_BYTES = 196_621;
    expect(INDEX_PREFETCH_BYTES).toBeGreaterThan(SHIPPED_INDEX_BYTES);
    expect(INDEX_PREFETCH_BYTES / SHIPPED_INDEX_BYTES).toBeGreaterThan(1.2);
  });

  it("covers the terrain cut too, which is a separate archive with its own index", () => {
    // Measured at `pmtiles convert` on the z0-8 terrain build: root 110 B, 22 leaf dirs totalling
    // 196,637 B. Nearly the same size as relief's, which is not a coincidence — both are 87,381
    // addresses over the same grid — but it is a second archive and must be asserted, not assumed
    // to inherit the first one's headroom.
    const TERRAIN_INDEX_BYTES = 196_747;
    expect(INDEX_PREFETCH_BYTES).toBeGreaterThan(TERRAIN_INDEX_BYTES);
    expect(INDEX_PREFETCH_BYTES / TERRAIN_INDEX_BYTES).toBeGreaterThan(1.2);
  });
});

// One bucket, three archives, and NOTHING in a raster tile URL distinguishes two of them except
// the layer segment: both are lossless WebP over z0-8 on the same tiling scheme. Getting this
// wrong does not 404 — MapLibre would decode relief colour as terrarium elevation and displace the
// globe by whatever those bytes happen to mean. So the router is tested for exclusivity, not just
// for matching.
//
// `resolveRoute` TAKES NO ENV. It used to, so it could consult three `*_ARCHIVE_KEY` vars ahead of
// the registry; with those retired the route is a pure function of the path, and the signature says
// so. Nothing about which object a request reaches can now vary per deployment.
describe("resolveRoute", () => {
  it("sends a bare address to the relief archive", () => {
    const route = resolveRoute("/8/189/107.webp");
    expect(route?.address).toMatchObject({ z: 8, x: 189, y: 107 });
    expect(route?.published.objectKey).toBe(archiveFor("earth", "relief").objectKey);
    expect(route?.layer.contentType).toBe(TILE_CONTENT_TYPE);
  });

  it("sends a prefixed address to the terrain archive", () => {
    const route = resolveRoute("/terrain/8/189/107.webp");
    expect(route?.address).toMatchObject({ z: 8, x: 189, y: 107 });
    expect(route?.published.objectKey).toBe(archiveFor("earth", "terrain").objectKey);
    expect(route?.layer.contentType).toBe(TERRAIN_CONTENT_TYPE);
  });

  it("resolves the SAME tile address to two different archives, which is the whole risk", () => {
    const relief = resolveRoute("/6/47/26.webp");
    const terrain = resolveRoute("/terrain/6/47/26.webp");
    expect(coordinates(relief!.address)).toEqual(coordinates(terrain!.address));
    expect(relief?.published.objectKey).not.toBe(terrain?.published.objectKey);
  });

  it("names each archive out of the registry, and never the other one's", () => {
    // Distinct keys per layer are what make a terrain request a 404 when its archive is absent,
    // rather than a globe displaced by relief colour read as elevation.
    //
    // The registry is the only answer now. Before it there were DEFAULT_* constants naming each
    // pyramid's FIRST cut — and the relief one, `planet.pmtiles`, was deleted from the bucket the
    // day its WebP replacement went live, so the "safe" default pointed at nothing at all.
    const relief = resolveRoute("/0/0/0.webp");
    const terrain = resolveRoute("/terrain/0/0/0.webp");
    expect(relief?.published.objectKey).toBe(archiveFor("earth", "relief").objectKey);
    expect(terrain?.published.objectKey).toBe(archiveFor("earth", "terrain").objectKey);
    expect(relief?.published.objectKey).not.toBe(terrain?.published.objectKey);
  });

  it("refuses anything that is not a tile in either pyramid", () => {
    for (const path of [
      "/",
      "/favicon.ico",
      "/terrain",
      "/terrain/",
      "/terrain/bathy_s8_webp/8/189/107.webp", // the retired spike route's shape
      "/8/189/107.png",
      "/9/0/0.webp", // past every pyramid's depth
      "/terrain/9/0/0.webp",
      "/countries/9/0/0.mvt",
      "/0/1/0.webp", // outside the 2^z grid
      "/countries",
      "/countries/",
      "/countries/8/189/107.webp", // right prefix, raster extension
      "/8/189/107.mvt", // vector extension, no prefix
    ]) {
      expect(resolveRoute(path), path).toBeNull();
    }
  });

  it("names the right constants when an archive's zoom range drifts", () => {
    // The warning has to send someone to the file that is actually wrong; two archives means two
    // sets of constants, and a message naming the relief ones for a terrain drift is a wild goose
    // chase through the wrong module.
    expect(resolveRoute("/0/0/0.webp")?.published.zoomConstants).toContain("reliefTiles.ts");
    expect(resolveRoute("/terrain/0/0/0.webp")?.published.zoomConstants).toContain(
      "terrainSource.ts",
    );
  });

  it("sends a MARS relief drift to the pipeline, not to Earth's module", () => {
    // WHY THIS POINTER IS PER BODY. Mars deliberately does not use RELIEF_MIN_ZOOM/RELIEF_MAX_ZOOM
    // — its ceiling follows its own source data — so a message naming reliefTiles.ts would send
    // the reader to a file whose numbers Mars ignores, to edit a constant that would change Earth.
    const mars = resolveRoute(
      `/${tilePathTemplate("mars", "relief").replace("{z}", "0").replace("{x}", "0").replace("{y}", "0")}`,
    );
    expect(mars?.published.zoomConstants).toContain("bodies.py");
    expect(mars?.published.zoomConstants).not.toContain("reliefTiles.ts");
    // The negative alone would pass on an empty string, and the positive alone would pass on a
    // pointer that also named Earth's file.
    expect(resolveRoute("/0/0/0.webp")?.published.zoomConstants).not.toContain("bodies.py");
  });

  it("carries each archive's OWN tile-type check, not one shared one", () => {
    // Only the terrain message may talk about losslessness: a mislabelled relief tile is cosmetic
    // (browsers content-sniff past it), while a lossy elevation tile decodes to wrong metres.
    expect(resolveRoute("/terrain/0/0/0.webp")?.layer.describeTileTypeMismatch(".png")).toMatch(
      /LOSSLESS/,
    );
    expect(resolveRoute("/0/0/0.webp")?.layer.describeTileTypeMismatch(".png")).not.toMatch(
      /LOSSLESS/,
    );
    expect(resolveRoute("/0/0/0.webp")?.layer.describeTileTypeMismatch(".webp")).toBeNull();
    expect(resolveRoute("/terrain/0/0/0.webp")?.layer.describeTileTypeMismatch(".webp")).toBeNull();
  });

  it("sends a countries address to the vector archive", () => {
    const route = resolveRoute("/countries/8/189/107.mvt");
    expect(route?.address).toMatchObject({ z: 8, x: 189, y: 107 });
    expect(route?.published.objectKey).toBe("countries-v1.pmtiles");
    expect(route?.layer.contentType).toBe(VECTOR_CONTENT_TYPE);
    expect(route?.published.zoomConstants).toContain("countryTiles.ts");
  });

  it("gives the countries archive its own key too", () => {
    expect(resolveRoute("/countries/0/0/0.mvt")?.published.objectKey).toBe(
      archiveFor("earth", "vector").objectKey,
    );
  });

  // The distinction the whole route table exists for. A miss is diagnostic on the two COMPLETE
  // raster pyramids and ordinary on the SPARSE vector one, so the status cannot be a shared
  // constant: 404 everywhere would emit tens of thousands of errors for correctly-absent ocean
  // tiles and bury a real packaging fault in that noise, while 204 everywhere would silence the
  // packaging fault outright.
  it("answers a missing tile per ARCHIVE, 404 where complete and 204 where sparse", () => {
    expect(resolveRoute("/0/0/0.webp")?.layer.missingTileStatus).toBe(404);
    expect(resolveRoute("/terrain/0/0/0.webp")?.layer.missingTileStatus).toBe(404);
    expect(resolveRoute("/countries/0/0/0.mvt")?.layer.missingTileStatus).toBe(204);
  });

  it("carries a countries tile-type check that accepts .mvt and rejects the raster codec", () => {
    const route = resolveRoute("/countries/0/0/0.mvt");
    expect(route?.layer.describeTileTypeMismatch(".mvt")).toBeNull();
    // Pointing this route at a raster archive yields a globe with no countries and no error —
    // indistinguishable from a source-layer typo — so the message has to name the constant.
    expect(route?.layer.describeTileTypeMismatch(".webp")).toContain("VECTOR_TILE_EXTENSION");
  });
});

describe("per-archive isolate state", () => {
  // Every one of these was a single value while there was one archive, and every one of them
  // fails SILENTLY with two: a shared latch hides the second archive's warning, and a
  // single-slot memo thrashes on every alternating request rather than erroring.
  const source = readFileSync(new URL("./index.ts", import.meta.url), "utf8");

  it("holds each archive's in-flight index separately", () => {
    expect(source).toContain("const indexInFlight = new Map<string, Promise<ArchiveIndex | null>>");
    expect(source).not.toMatch(/let indexInFlight/);
  });

  it("latches both warnings per archive key, not per isolate", () => {
    expect(source).toContain("const warnedTileTypeMismatch = new Set<string>()");
    expect(source).toContain("const warnedIndexOutgrewPrefetch = new Set<string>()");
  });

  it("sizes the directory cache by SUMMING the registry, not by a literal", () => {
    // The number used to be typed in and re-tallied whenever an archive was added — 25, then 50,
    // then 64 — and the last tally was wrong: terrain has 22 leaf directories and was recorded as
    // 21. Nothing could have caught it by behaviour. An evicted directory costs a gunzip and a
    // deserialize rather than an R2 read, so an undersized cache is a slightly slower Worker with
    // no other symptom, and a body switch is exactly the alternating traffic that provokes it.
    expect(source, "a literal capacity is the thing this replaces").not.toMatch(
      /new ResolvedValueCache\(\d+,/,
    );
    expect(source).toContain("new ResolvedValueCache(directoryCacheEntries()");
  });

  it("covers every published archive at once, with room above the worst case", () => {
    // The arithmetic, against the registry rather than against the source. Every archive costs a
    // header entry, a root entry and one per leaf; the cache has to hold them all SIMULTANEOUSLY,
    // because two bodies' pyramids being asked for alternately is the whole point of the sum.
    const worstCase = Object.values(PUBLISHED)
      .flatMap((layers) => Object.values(layers))
      .filter((archive) => archive !== null)
      .reduce((total, archive) => total + 2 + archive.indexLeaves, 0);
    expect(directoryCacheEntries()).toBeGreaterThan(worstCase);
    // And it is not merely large: a cache sized so far above the need that this test cannot fail
    // would pin nothing. The headroom is a handful of entries, not a multiple.
    expect(directoryCacheEntries()).toBeLessThan(worstCase * 2);
  });

  it("grows when a body publishes a pyramid, which is what makes it self-maintaining", () => {
    // The property worth having, stated as a property — and now OBSERVED rather than anticipated.
    // This test used to assert Mars published nothing and that the number exceeded Earth's own need;
    // both halves passed while the mechanism was untested, because one body is the case a sum over
    // bodies cannot distinguish from a constant. Mars's relief pyramid entered the registry and this
    // number moved by Mars's own cost, with nobody editing the Worker.
    const marsCost = directoryCacheCostOf(PUBLISHED.mars);
    expect(marsCost, "Mars publishes nothing — see PUBLISHED in tileAddress.ts").toBeGreaterThan(0);
    expect(directoryCacheEntries() - directoryCacheCostOf(PUBLISHED.earth))
      .toBeGreaterThanOrEqual(marsCost);
  });
});

// --- the fetch handler ------------------------------------------------------------------------
//
// Everything above tests a piece the handler USES. This tests the handler itself, which is the
// only code path a production tile actually takes, and which nothing reached until now.
//
// TWO HAZARDS SHAPE THESE TESTS.
//
// `indexInFlight`, `warnedTileTypeMismatch` and `warnedIndexOutgrewPrefetch` are module scope —
// that is deliberate (an isolate reuses them across requests) and it means a test leaks into the
// next one through the same doors a real isolate does. So every test that reaches R2 uses its OWN
// archive key. A shared key would make these pass or fail depending on file order, which is the
// kind of green that is worse than red.
//
// And `caches` does not exist in Node at all, so it is stubbed per test rather than shared: a
// single fake cache would let one test's `put` answer another test's `match`.

interface FakeCache {
  match: ReturnType<typeof vi.fn>;
  put: ReturnType<typeof vi.fn>;
}

/** A cache that misses everything and records what was stored. */
function emptyCache(): FakeCache {
  return { match: vi.fn(async () => undefined), put: vi.fn(async () => undefined) };
}

/** A bucket whose every `get` resolves to `null` — R2's "no such object". This is the shape a
 *  missing or mis-keyed archive takes, and it is the ONLY hard failure the Worker claims to turn
 *  into a 404 rather than an exception. */
function emptyBucket() {
  const get = vi.fn(async () => null);
  return { get } as unknown as R2Bucket & { get: typeof get };
}

function callFetch(
  url: string,
  {
    method = "GET",
    origin = null,
    env = {},
    cache = emptyCache(),
    bucket = emptyBucket(),
  }: {
    method?: string;
    origin?: string | null;
    env?: Record<string, unknown>;
    cache?: FakeCache;
    bucket?: R2Bucket;
  } = {},
) {
  vi.stubGlobal("caches", { default: cache });
  const waitUntil = vi.fn();
  const request = new Request(url, {
    method,
    headers: origin === null ? undefined : { Origin: origin },
  });
  const response = worker.fetch(
    request,
    { ARCHIVE: bucket, ...env } as never,
    { waitUntil, passThroughOnException: vi.fn() } as never,
  );
  return { response, waitUntil, cache, bucket };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetch — rejections that must not cost an R2 read", () => {
  // "A typo'd URL must not cost a range read on a 16 GB object" is the stated reason the router
  // runs before the bucket is touched. Only a call counter can see that, so assert the absence.

  it("refuses a write method with 405 and never looks at the bucket", async () => {
    const { response, bucket } = callFetch("https://tiles.example/5/1/2.webp", { method: "POST" });
    expect((await response).status).toBe(405);
    expect(bucket.get).not.toHaveBeenCalled();
  });

  it("serves HEAD, which is not a write and must not be lumped in with one", async () => {
    const { response } = callFetch("https://tiles.example/nope", { method: "HEAD" });
    // Still a 404 (the path is not a tile), but a 404 rather than the 405 a naive GET-only gate
    // would give — the distinction a monitoring probe depends on.
    expect((await response).status).toBe(404);
  });

  it("404s a path that addresses neither pyramid, before any read", async () => {
    const { response, bucket } = callFetch("https://tiles.example/robots.txt");
    expect((await response).status).toBe(404);
    expect(bucket.get).not.toHaveBeenCalled();
  });

  it("404s the index's own cache key, which is why it is safe to park it on this hostname", async () => {
    // indexCacheUrl writes to /__pmtiles-index/<key> on the Worker's own origin. That is only
    // unreachable from outside because the router rejects it here, before the cache is consulted.
    const { response, bucket } = callFetch("https://tiles.example/__pmtiles-index/planet.pmtiles");
    expect((await response).status).toBe(404);
    expect(bucket.get).not.toHaveBeenCalled();
  });

  it("still carries CORS and Server-Timing on a rejection", async () => {
    // Rejections go through `respond` like everything else. A 404 without CORS is a 404 the page
    // cannot read the status of, which turns a clear failure into an opaque one.
    const { response } = callFetch("https://tiles.example/robots.txt", {
      origin: "https://terrella.example",
      env: { ALLOWED_ORIGIN: "https://terrella.example" },
    });
    const headers = (await response).headers;
    expect(headers.get("Access-Control-Allow-Origin")).toBe("https://terrella.example");
    expect(headers.get("Server-Timing")).toContain("worker;dur=");
  });
});

describe("fetch — the addressed grammar", () => {
  // The shape the client moves to next. The Worker has to serve it BEFORE anything asks for it,
  // or the two deploys have to land in the same second — which they cannot, being two Workers.

  it("routes an addressed path to the same archive its legacy address reaches", async () => {
    const addressed = `https://tiles.example/${tilePathTemplate("earth", "relief")
      .replace("{z}", "5")
      .replace("{x}", "1")
      .replace("{y}", "2")}`;
    // NO env override: the archive key comes from the registry, and the bucket is empty either
    // way. These fixtures used to name a distinct key per test so the module-scope directory cache
    // could not carry between them — which the empty bucket already guarantees, since a request
    // that cannot find its archive never reads a directory to cache.
    const { response, bucket } = callFetch(addressed);
    // Past the router — an archive 404, not a route 404, which is what proves it resolved.
    expect(await (await response).text()).toBe("Archive not found");
    expect(bucket.get).toHaveBeenCalled();
  });

  it("refuses an addressed path for a body that publishes nothing, without an R2 read", async () => {
    const { response, bucket } = callFetch("https://tiles.example/venus/relief/4d04db58/5/1/2.webp");
    expect(await (await response).text()).toBe("Not a tile path");
    expect(bucket.get).not.toHaveBeenCalled();
  });

  it("keeps naming the object out of the registry when no var overrides it", () => {
    const route = resolveRoute(
      `/${tilePathTemplate("earth", "vector").replace("{z}", "1").replace("{x}", "0").replace("{y}", "0")}`,
      { ARCHIVE: null as never },
    );
    expect(route?.published.objectKey).toBe(archiveFor("earth", "vector").objectKey);
  });
});

describe("the archive keys live in ONE place", () => {
  // This used to pin three `*_ARCHIVE_KEY` vars in wrangler.jsonc against the registry, because
  // they were two copies of one fact and the failure mode is a Worker that serves the previous cut
  // forever with every gate green. The vars are gone, so the pin is replaced by the stronger
  // statement: there is nothing left to keep in step.
  const workerConfig = readFileSync(new URL("./wrangler.jsonc", import.meta.url), "utf8");

  it("names no archive object in the Worker's config at all", () => {
    // Matched on the `.pmtiles` VALUE rather than on the old variable names — a fourth key under a
    // new name would satisfy a name-based check while reintroducing exactly what was removed.
    expect(workerConfig).not.toMatch(/"[^"]*\.pmtiles"/);
  });

  it("still declares the binding those objects are read through", () => {
    // The counterweight: "no keys" must not be satisfiable by a config that lost the bucket too.
    expect(workerConfig).toMatch(/"binding"\s*:\s*"ARCHIVE"/);
    expect(workerConfig).toMatch(/"bucket_name"\s*:\s*"terrella-tiles"/);
  });

  it("resolves every published archive from the registry instead", () => {
    for (const layer of ["relief", "terrain", "vector"] as const) {
      expect(archiveFor("earth", layer).objectKey).toMatch(/\.pmtiles$/);
    }
  });
});

describe("fetch — the optional /v<N>/ prefix", () => {
  // It exists so a re-cut can ship under a new base URL instead of a cache purge, and purge is
  // ZONE-WIDE — on a shared zone it would evict everything else on the domain. A regex whose
  // failure mode is "404 every versioned URL" deserves to be pinned from both sides.

  it("strips a version segment and routes the address underneath it", async () => {
    const { response } = callFetch("https://tiles.example/v3/5/1/2.webp");
    // Past the router: the archive is missing, so this is the archive 404 and not the route 404.
    expect((await response).status).toBe(404);
    expect(await (await response).text()).toBe("Archive not found");
  });

  it("strips it ahead of the terrain prefix, so both survive together", async () => {
    const { response, bucket } = callFetch("https://tiles.example/v12/terrain/5/1/2.webp");
    // Awaited BEFORE the call assertion: the R2 read is what the response is waiting on, so
    // checking the spy first reads an empty call list and passes for the wrong reason.
    expect(await (await response).text()).toBe("Archive not found");
    expect(bucket.get).toHaveBeenCalled();
  });

  it("does NOT strip a segment that merely looks like one", async () => {
    // Over-eager stripping is the silent direction: `/v3x/...` becoming a valid tile address
    // would serve one pyramid's bytes for another's URL space.
    const { response, bucket } = callFetch("https://tiles.example/v3x/5/1/2.webp");
    expect((await response).status).toBe(404);
    expect(await (await response).text()).toBe("Not a tile path");
    expect(bucket.get).not.toHaveBeenCalled();
  });

  it("strips only the LEADING segment, not one buried mid-path", async () => {
    // The address is chosen so that dropping the `^` would MATTER: strip `/v2/` from the middle
    // of `/5/v2/1/2.webp` and you get `/5/1/2.webp`, a perfectly valid tile that would then be
    // served under a URL nobody minted. A shorter path like `/5/v2/2.webp` cannot show this —
    // it fails to parse either way, so it passes while pinning nothing.
    const { response, bucket } = callFetch("https://tiles.example/5/v2/1/2.webp");
    expect(await (await response).text()).toBe("Not a tile path");
    expect(bucket.get).not.toHaveBeenCalled();
  });
});

describe("fetch — a cached body must not carry the first requester's CORS decision", () => {
  // THE INVARIANT THIS FILE EXISTS FOR. `respond` applies CORS and Server-Timing on the way OUT,
  // never into what is stored, so one cached entry serves every origin. Move
  // `withCrossOriginHeaders` inside `store` and the first requester's Origin is baked into the
  // cache and replayed to everyone after — a real cross-origin defect that is INVISIBLE in dev,
  // where there is only ever one origin, and invisible in any test that uses only one either.

  /** A cache that hits with a body carrying no CORS headers of its own — which is exactly what
   *  `store` writes, and the point is that the hit still comes back correctly labelled. */
  it("gives two different origins two different answers off the SAME cached body", async () => {
    const env = { ALLOWED_ORIGIN: "https://terrella.example" };
    const allowed = callFetch("https://tiles.example/5/1/2.webp", {
      origin: "https://terrella.example",
      env,
      cache: hittingCache(),
    });
    const stranger = callFetch("https://tiles.example/5/1/2.webp", {
      origin: "https://evil.example",
      env,
      cache: hittingCache(),
    });
    expect((await allowed.response).headers.get("Access-Control-Allow-Origin")).toBe(
      "https://terrella.example",
    );
    expect((await stranger.response).headers.get("Access-Control-Allow-Origin")).toBeNull();
    // Both were cache hits, so the difference cannot have come from re-reading the archive.
    expect((await allowed.response).headers.get("X-Terrella-Cache")).toBe("hit");
    expect((await stranger.response).headers.get("X-Terrella-Cache")).toBe("hit");
  });

  it("gives a cache hit THIS request's timings, not the miss's that filled it", async () => {
    // A stored Server-Timing would let a hit replay the timings of the miss behind it, which is
    // worse than no instrument: it would report the cold path's milliseconds as the warm path's.
    const { response } = callFetch("https://tiles.example/5/1/2.webp", { cache: hittingCache() });
    const timing = (await response).headers.get("Server-Timing") ?? "";
    expect(timing).toContain("cache;dur=");
    // Zero reads, because nothing went to R2 — the shape that distinguishes a hit from a miss.
    expect(timing).toContain('r2;dur=0;desc="0 reads, 0 B"');
  });

  it("does not re-read the archive on a hit", async () => {
    const { response, bucket } = callFetch("https://tiles.example/5/1/2.webp", {
      cache: hittingCache(),
    });
    await response;
    expect(bucket.get).not.toHaveBeenCalled();
  });

  it("keeps the cached body intact through the header rewrite", async () => {
    const { response } = callFetch("https://tiles.example/5/1/2.webp", { cache: hittingCache() });
    expect(await (await response).text()).toBe("tile-bytes");
    expect((await response).headers.get("Content-Type")).toBe("image/webp");
  });
});

describe("fetch — the cross-origin allowlist", () => {
  it('honours a wildcard ALLOWED_ORIGIN for an origin it has never seen', async () => {
    const { response } = callFetch("https://tiles.example/5/1/2.webp", {
      origin: "https://anywhere.example",
      env: { ALLOWED_ORIGIN: "*" },
      cache: hit(),
    });
    expect((await response).headers.get("Access-Control-Allow-Origin")).toBe("*");
  });

  it("sends no allow-origin at all when ALLOWED_ORIGIN is unset", async () => {
    // Unset must not read as permissive. A tile without CORS taints the WebGL canvas and never
    // draws, so the failure is loud on the page — but only if we never invent a default here.
    const { response } = callFetch("https://tiles.example/5/1/2.webp", {
      origin: "https://terrella.example",
      cache: hit(),
    });
    expect((await response).headers.get("Access-Control-Allow-Origin")).toBeNull();
  });

  it("always varies on Origin, including when it refuses", async () => {
    // Without `Vary: Origin` an intermediary may hand one origin's allow-header to another —
    // the same defect as caching the decision, arrived at from outside instead of inside.
    const { response } = callFetch("https://tiles.example/5/1/2.webp", {
      origin: "https://evil.example",
      env: { ALLOWED_ORIGIN: "https://terrella.example" },
      cache: hit(),
    });
    expect((await response).headers.get("Vary")).toBe("Origin");
  });

  it("keeps Timing-Allow-Origin wide open even when ACAO is narrowed", async () => {
    // They answer different questions: ACAO decides who may READ a tile, TAO only who may read
    // the timing of a fetch already made. Narrowing TAO would blind Resource Timing everywhere
    // except the production page — which is precisely where measurement does not happen.
    const { response } = callFetch("https://tiles.example/5/1/2.webp", {
      origin: "https://evil.example",
      env: { ALLOWED_ORIGIN: "https://terrella.example" },
      cache: hit(),
    });
    expect((await response).headers.get("Timing-Allow-Origin")).toBe("*");
  });
});

describe("fetch — a missing archive is a 404, not an exception", () => {
  // The handler names ArchiveNotFound explicitly and answers 404 for it. That matters because the
  // alternative is an unhandled throw, which Cloudflare turns into a 500 — and a 500 on every
  // tile in the world reads as "the Worker is broken" rather than "the bucket lost its object".

  it("answers 404 when the bucket has no such object", async () => {
    const { response } = callFetch("https://tiles.example/5/1/2.webp");
    await expect(response).resolves.toBeInstanceOf(Response);
    expect((await response).status).toBe(404);
    expect(await (await response).text()).toBe("Archive not found");
  });

  it("still labels that 404 for the requesting origin", async () => {
    const { response } = callFetch("https://tiles.example/5/1/2.webp", {
      origin: "https://terrella.example",
      env: { ALLOWED_ORIGIN: "https://terrella.example" },
    });
    expect((await response).headers.get("Access-Control-Allow-Origin")).toBe(
      "https://terrella.example",
    );
  });

  it("does not cache the failure — a restored bucket must recover without a purge", async () => {
    const cache = emptyCache();
    const { response, waitUntil } = callFetch("https://tiles.example/5/1/2.webp", { cache });
    await response;
    // `store` is what writes to the cache, and the ArchiveNotFound path deliberately bypasses it.
    // Only the index's own entry may ever be scheduled here, never a 404 for the tile URL.
    for (const call of waitUntil.mock.calls) void call;
    expect(cache.put).not.toHaveBeenCalledWith("https://tiles.example/5/1/2.webp", expect.anything());
  });
});
