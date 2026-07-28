// The index prefetch: the Worker pulls the archive's whole directory region in ONE read and
// serves every directory lookup out of it, so a cold tile costs one R2 round trip instead of
// three. These tests pin the part that decides which reads are free — because the failure mode
// is not a crash, it is a silent return to three reads that nothing would notice.

import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import type { RangeResponse, Source } from "pmtiles";
import { INDEX_PREFETCH_BYTES, PrefetchedIndexSource, resolveRoute } from "./index";
import { TILE_CONTENT_TYPE } from "../src/lib/reliefTiles";
import { TERRAIN_CONTENT_TYPE } from "../src/lib/terrainSource";

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

// One bucket, two archives, and NOTHING in a tile URL distinguishes them except the prefix: both
// pyramids are lossless WebP over z0-8 on the same tiling scheme. Getting this wrong does not
// 404 — MapLibre would decode relief colour as terrarium elevation and displace the globe by
// whatever those bytes happen to mean. So the router is tested for exclusivity, not just for
// matching.
describe("resolveRoute", () => {
  const env = {
    ARCHIVE: null as never,
    ARCHIVE_KEY: "planet-v2.pmtiles",
    TERRAIN_ARCHIVE_KEY: "terrain-v1.pmtiles",
  };

  it("sends a bare address to the relief archive", () => {
    const route = resolveRoute("/8/189/107.webp", env);
    expect(route?.tile).toEqual({ z: 8, x: 189, y: 107 });
    expect(route?.archiveKey).toBe("planet-v2.pmtiles");
    expect(route?.contentType).toBe(TILE_CONTENT_TYPE);
  });

  it("sends a prefixed address to the terrain archive", () => {
    const route = resolveRoute("/terrain/8/189/107.webp", env);
    expect(route?.tile).toEqual({ z: 8, x: 189, y: 107 });
    expect(route?.archiveKey).toBe("terrain-v1.pmtiles");
    expect(route?.contentType).toBe(TERRAIN_CONTENT_TYPE);
  });

  it("resolves the SAME tile address to two different archives, which is the whole risk", () => {
    const relief = resolveRoute("/6/47/26.webp", env);
    const terrain = resolveRoute("/terrain/6/47/26.webp", env);
    expect(relief?.tile).toEqual(terrain?.tile);
    expect(relief?.archiveKey).not.toBe(terrain?.archiveKey);
  });

  it("falls back to a default key per archive rather than reading the other one's", () => {
    // An unset var must not resolve to the wrong archive. Distinct defaults are what make a
    // missing TERRAIN_ARCHIVE_KEY a 404 rather than a globe displaced by relief colour.
    const bare = { ARCHIVE: null as never };
    const relief = resolveRoute("/0/0/0.webp", bare);
    const terrain = resolveRoute("/terrain/0/0/0.webp", bare);
    expect(relief?.archiveKey).toBe("planet.pmtiles");
    expect(terrain?.archiveKey).toBe("terrain.pmtiles");
    expect(relief?.archiveKey).not.toBe(terrain?.archiveKey);
  });

  it("refuses anything that is not a tile in either pyramid", () => {
    for (const path of [
      "/",
      "/favicon.ico",
      "/terrain",
      "/terrain/",
      "/terrain/bathy_s8_webp/8/189/107.webp", // the retired spike route's shape
      "/8/189/107.png",
      "/9/0/0.webp", // past both pyramids' depth
      "/terrain/9/0/0.webp",
      "/0/1/0.webp", // outside the 2^z grid
    ]) {
      expect(resolveRoute(path, env), path).toBeNull();
    }
  });

  it("names the right constants when an archive's zoom range drifts", () => {
    // The warning has to send someone to the file that is actually wrong; two archives means two
    // sets of constants, and a message naming the relief ones for a terrain drift is a wild goose
    // chase through the wrong module.
    expect(resolveRoute("/0/0/0.webp", env)?.zoomConstants).toContain("reliefTiles.ts");
    expect(resolveRoute("/terrain/0/0/0.webp", env)?.zoomConstants).toContain("terrainSource.ts");
  });

  it("carries each archive's OWN tile-type check, not one shared one", () => {
    // Only the terrain message may talk about losslessness: a mislabelled relief tile is cosmetic
    // (browsers content-sniff past it), while a lossy elevation tile decodes to wrong metres.
    expect(resolveRoute("/terrain/0/0/0.webp", env)?.describeTileTypeMismatch(".png")).toMatch(
      /LOSSLESS/,
    );
    expect(resolveRoute("/0/0/0.webp", env)?.describeTileTypeMismatch(".png")).not.toMatch(
      /LOSSLESS/,
    );
    expect(resolveRoute("/0/0/0.webp", env)?.describeTileTypeMismatch(".webp")).toBeNull();
    expect(resolveRoute("/terrain/0/0/0.webp", env)?.describeTileTypeMismatch(".webp")).toBeNull();
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

  it("sizes the directory cache for both pyramids' leaves, not one's", () => {
    // 22 leaf dirs + a header per archive. At the old 25 the two would evict each other on every
    // alternating request — which costs a gunzip rather than an R2 read, so it would have shown
    // up as nothing at all.
    const capacity = /new ResolvedValueCache\((\d+),/.exec(source);
    expect(capacity).not.toBeNull();
    expect(Number(capacity?.[1])).toBeGreaterThanOrEqual(2 * (22 + 1));
  });
});
