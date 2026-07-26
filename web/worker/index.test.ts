// The index prefetch: the Worker pulls the archive's whole directory region in ONE read and
// serves every directory lookup out of it, so a cold tile costs one R2 round trip instead of
// three. These tests pin the part that decides which reads are free — because the failure mode
// is not a crash, it is a silent return to three reads that nothing would notice.

import { describe, expect, it, vi } from "vitest";
import type { RangeResponse, Source } from "pmtiles";
import { INDEX_PREFETCH_BYTES, PrefetchedIndexSource } from "./index";

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
});
