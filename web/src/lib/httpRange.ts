/** A satisfiable single byte range, inclusive on both ends (RFC 9110 §14.1.2). */
export interface ByteRange {
  start: number;
  end: number;
}

/**
 * Parse an HTTP `Range` header against a resource of `totalSize` bytes.
 *
 * Returns:
 * - `null` — no header, or one the server chooses to ignore (malformed, non-bytes
 *   unit, multi-range, backwards). RFC 9110 lets a server ignore Range and answer
 *   200 with the full body, which is the correct dev-server fallback.
 * - `"unsatisfiable"` — a syntactically valid range with no overlap with the
 *   resource (start past the end, or a zero-length suffix) → answer 416.
 * - a `ByteRange` — the satisfiable slice, with `end` clamped to the last byte.
 *
 * Only single ranges are supported: the pmtiles client never sends multi-range
 * requests, and ignoring them (→ 200) is spec-conformant.
 */
export function parseByteRange(
  header: string | undefined,
  totalSize: number,
): ByteRange | "unsatisfiable" | null {
  if (header === undefined) return null;

  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (match === null) return null;
  const [, startText, endText] = match;
  if (startText === "" && endText === "") return null; // "bytes=-" carries nothing

  if (startText === "") {
    // Suffix form `bytes=-N`: the final N bytes of the resource.
    const suffixLength = Number(endText);
    if (suffixLength === 0) return "unsatisfiable";
    return { start: Math.max(0, totalSize - suffixLength), end: totalSize - 1 };
  }

  const start = Number(startText);
  if (start >= totalSize) return "unsatisfiable";
  const end = endText === "" ? totalSize - 1 : Math.min(Number(endText), totalSize - 1);
  if (start > end) return null; // backwards range — ignore, serve whole
  return { start, end };
}
