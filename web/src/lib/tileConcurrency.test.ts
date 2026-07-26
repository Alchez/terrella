// The ?maxreq parser. Every rejection here exists because the alternative — silently running at
// MapLibre's default 16 after the URL asked for something else — produces a measurement of the
// wrong configuration, which is worse than no measurement.

import { describe, expect, it } from "vitest";
import {
  MAPLIBRE_DEFAULT_MAX_PARALLEL_IMAGE_REQUESTS,
  MAX_PARALLEL_IMAGE_REQUESTS_CEILING,
  parseMaxParallelImageRequests,
} from "./tileConcurrency";

const parse = (search: string) => parseMaxParallelImageRequests(new URLSearchParams(search));

describe("parseMaxParallelImageRequests", () => {
  it("reads the ladder values a measurement run uses", () => {
    expect(parse("?maxreq=4")).toBe(4);
    expect(parse("?maxreq=8")).toBe(8);
    expect(parse("?maxreq=16")).toBe(16);
    expect(parse("?maxreq=32")).toBe(32);
  });

  it("returns null when the flag is absent, so the default path is untouched", () => {
    expect(parse("")).toBeNull();
    expect(parse("?perf&bare")).toBeNull();
  });

  it("rejects a value that parseInt would silently truncate", () => {
    // parseInt("8tiles") is 8. A URL saying "8tiles" is a mistake, not a request for 8.
    expect(parse("?maxreq=8tiles")).toBeNull();
    // Number("1e3") is a valid integer 1000 — caught by the ceiling, not by the integer check.
    expect(parse("?maxreq=1e3")).toBeNull();
  });

  it("rejects non-integers — a fractional stream count is a typo, not a setting", () => {
    expect(parse("?maxreq=8.5")).toBeNull();
    expect(parse("?maxreq=NaN")).toBeNull();
    expect(parse("?maxreq=Infinity")).toBeNull();
  });

  it("rejects values that would make the page worse rather than measure it", () => {
    expect(parse("?maxreq=0")).toBeNull(); // would stall every tile forever
    expect(parse("?maxreq=-4")).toBeNull();
    expect(parse(`?maxreq=${MAX_PARALLEL_IMAGE_REQUESTS_CEILING}`)).toBe(
      MAX_PARALLEL_IMAGE_REQUESTS_CEILING,
    );
    expect(parse(`?maxreq=${MAX_PARALLEL_IMAGE_REQUESTS_CEILING + 1}`)).toBeNull();
  });

  it("treats an empty value as absent rather than as zero", () => {
    expect(parse("?maxreq=")).toBeNull();
    expect(parse("?maxreq=%20")).toBeNull();
  });

  it("states MapLibre's default, so a run can record its own control", () => {
    expect(MAPLIBRE_DEFAULT_MAX_PARALLEL_IMAGE_REQUESTS).toBe(16);
  });
});
