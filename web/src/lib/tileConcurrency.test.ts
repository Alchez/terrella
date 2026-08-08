// The ?maxreq parser. Every rejection here exists because the alternative — silently running at
// MapLibre's default 16 after the URL asked for something else — produces a measurement of the
// wrong configuration, which is worse than no measurement.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  MAPLIBRE_DEFAULT_MAX_PARALLEL_IMAGE_REQUESTS,
  MAX_PARALLEL_IMAGE_REQUESTS_CEILING,
  RAISED_MAX_PARALLEL_IMAGE_REQUESTS,
  defaultMaxParallelImageRequests,
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

describe("defaultMaxParallelImageRequests", () => {
  const unconstrained = { saveData: false, slowNetwork: false, mobileClass: false };

  it("raises the cap for an unconstrained visitor", () => {
    expect(defaultMaxParallelImageRequests(unconstrained)).toBe(
      RAISED_MAX_PARALLEL_IMAGE_REQUESTS,
    );
  });

  // The no-regression property, and the reason this function returns a number rather than a
  // boolean: every constrained case must land on the value the page already shipped, so the
  // change cannot move a device the sweep never covered.
  it.each([
    ["save-data", { ...unconstrained, saveData: true }],
    ["a slow connection", { ...unconstrained, slowNetwork: true }],
    ["a phone", { ...unconstrained, mobileClass: true }],
    ["all three at once", { saveData: true, slowNetwork: true, mobileClass: true }],
  ])("leaves MapLibre's default in place for %s", (_label, conditions) => {
    expect(defaultMaxParallelImageRequests(conditions)).toBe(
      MAPLIBRE_DEFAULT_MAX_PARALLEL_IMAGE_REQUESTS,
    );
  });

  it("ships a raised value that is actually raised, and within the override ceiling", () => {
    // Guards the pair rather than the constant: setting RAISED below the library default would
    // silently make every unconstrained visitor slower while every test above still passed.
    expect(RAISED_MAX_PARALLEL_IMAGE_REQUESTS).toBeGreaterThan(
      MAPLIBRE_DEFAULT_MAX_PARALLEL_IMAGE_REQUESTS,
    );
    expect(RAISED_MAX_PARALLEL_IMAGE_REQUESTS).toBeLessThanOrEqual(
      MAX_PARALLEL_IMAGE_REQUESTS_CEILING,
    );
  });
});

describe("the call site installs the resolved cap", () => {
  // `?maxreq` must still beat the default in BOTH directions — a measurement run that asked for 8
  // and silently got 32 would be the same failure the parser's rejections exist to prevent, one
  // layer up. Unit tests cannot see Globe.astro, so this reads it.
  const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");

  it("prefers the ?maxreq override over the resolved default", () => {
    expect(globe).toMatch(/requestedMaxParallelImageRequests\s*\?\?\s*\n?\s*defaultMaxParallelImageRequests/);
  });

  it("resolves a default rather than only acting when the flag is present", () => {
    expect(globe).toContain("defaultMaxParallelImageRequests({");
  });

  it("sets the cap before the Map is constructed, or the first tiles go out at the old value", () => {
    expect(globe.indexOf("setMaxParallelImageRequests")).toBeGreaterThan(-1);
    expect(globe.indexOf("setMaxParallelImageRequests")).toBeLessThan(
      globe.indexOf("new maplibregl.Map("),
    );
  });
});
