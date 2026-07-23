import { describe, expect, it } from "vitest";
import { parseByteRange } from "./httpRange";

// RFC 9110 §14: single byte-range parsing for the dev PMTiles server. The pmtiles
// client only ever sends simple `bytes=start-end` ranges, but the parser handles the
// full single-range grammar so a curl probe or a future client can't surprise it.
const ARCHIVE_SIZE = 1_000_000;

describe("parseByteRange", () => {
  it("returns null when there is no Range header (serve the whole file)", () => {
    expect(parseByteRange(undefined, ARCHIVE_SIZE)).toBeNull();
  });

  it("parses a bounded range: bytes=0-16383 → first 16 KiB", () => {
    expect(parseByteRange("bytes=0-16383", ARCHIVE_SIZE)).toEqual({ start: 0, end: 16383 });
  });

  it("parses an interior range: bytes=500-999", () => {
    expect(parseByteRange("bytes=500-999", ARCHIVE_SIZE)).toEqual({ start: 500, end: 999 });
  });

  it("parses an open-ended range: bytes=900-  → through the last byte", () => {
    expect(parseByteRange("bytes=900-", ARCHIVE_SIZE)).toEqual({
      start: 900,
      end: ARCHIVE_SIZE - 1,
    });
  });

  it("parses a suffix range: bytes=-500 → the last 500 bytes", () => {
    expect(parseByteRange("bytes=-500", ARCHIVE_SIZE)).toEqual({
      start: ARCHIVE_SIZE - 500,
      end: ARCHIVE_SIZE - 1,
    });
  });

  it("clamps a suffix range longer than the file to the whole file", () => {
    expect(parseByteRange("bytes=-2000000", ARCHIVE_SIZE)).toEqual({
      start: 0,
      end: ARCHIVE_SIZE - 1,
    });
  });

  it("clamps an end beyond the file to the last byte", () => {
    expect(parseByteRange("bytes=999000-9999999", ARCHIVE_SIZE)).toEqual({
      start: 999_000,
      end: ARCHIVE_SIZE - 1,
    });
  });

  it("reports a start at or past the file size as unsatisfiable (→ 416)", () => {
    expect(parseByteRange(`bytes=${ARCHIVE_SIZE}-`, ARCHIVE_SIZE)).toBe("unsatisfiable");
    expect(parseByteRange("bytes=5000000-", ARCHIVE_SIZE)).toBe("unsatisfiable");
  });

  it("reports a zero-length suffix (bytes=-0) as unsatisfiable", () => {
    expect(parseByteRange("bytes=-0", ARCHIVE_SIZE)).toBe("unsatisfiable");
  });

  it("ignores non-bytes units (RFC: a server MAY ignore Range → 200 whole file)", () => {
    expect(parseByteRange("items=0-10", ARCHIVE_SIZE)).toBeNull();
  });

  it("ignores multi-range requests (pmtiles never sends them)", () => {
    expect(parseByteRange("bytes=0-99,200-299", ARCHIVE_SIZE)).toBeNull();
  });

  it("ignores a backwards range (start > end)", () => {
    expect(parseByteRange("bytes=500-100", ARCHIVE_SIZE)).toBeNull();
  });

  it("ignores garbage", () => {
    expect(parseByteRange("bytes=abc-def", ARCHIVE_SIZE)).toBeNull();
    expect(parseByteRange("bytes=", ARCHIVE_SIZE)).toBeNull();
    expect(parseByteRange("0-100", ARCHIVE_SIZE)).toBeNull();
  });
});
