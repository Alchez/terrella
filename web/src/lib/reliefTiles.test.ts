// parseTilePath is the front door of every tile server we run — the dev middleware today, the
// R2 Worker next. Anything it accepts becomes a range read against a 16 GB archive, so the
// rejections matter more than the acceptances: a bad path must cost a 404, not a seek.

import { describe, expect, it } from "vitest";
import { RELIEF_MAX_ZOOM, RELIEF_MIN_ZOOM, assertZoomRange, parseTilePath } from "./reliefTiles";

describe("parseTilePath", () => {
  it("reads a tile address, with or without the leading slash", () => {
    expect(parseTilePath("/3/4/3.png")).toEqual({ z: 3, x: 4, y: 3 });
    expect(parseTilePath("3/4/3.png")).toEqual({ z: 3, x: 4, y: 3 });
  });

  it("accepts the corners of the pyramid", () => {
    expect(parseTilePath("/0/0/0.png")).toEqual({ z: 0, x: 0, y: 0 });
    expect(parseTilePath(`/${RELIEF_MAX_ZOOM}/255/255.png`)).toEqual({ z: 8, x: 255, y: 255 });
  });

  it("rejects a zoom outside the packaged pyramid", () => {
    expect(parseTilePath(`/${RELIEF_MAX_ZOOM + 1}/0/0.png`)).toBeNull();
  });

  it("rejects coordinates outside the 2^z grid at that zoom", () => {
    expect(parseTilePath("/0/1/0.png")).toBeNull();
    expect(parseTilePath("/8/256/0.png")).toBeNull();
    expect(parseTilePath("/8/0/256.png")).toBeNull();
  });

  it("rejects negative, non-numeric and traversal-shaped paths", () => {
    expect(parseTilePath("/-1/0/0.png")).toBeNull();
    expect(parseTilePath("/3/x/3.png")).toBeNull();
    expect(parseTilePath("/3/4/../../etc/passwd")).toBeNull();
    expect(parseTilePath("/../planet.pmtiles")).toBeNull();
  });

  it("rejects a different extension — the archive stores PNG and nothing else", () => {
    expect(parseTilePath("/3/4/3.webp")).toBeNull();
    expect(parseTilePath("/3/4/3")).toBeNull();
  });
});

describe("assertZoomRange", () => {
  it("passes when the archive matches the range the globe requests", () => {
    expect(() => assertZoomRange(RELIEF_MIN_ZOOM, RELIEF_MAX_ZOOM)).not.toThrow();
  });

  it("names the file to edit when a re-cut pyramid changes the range", () => {
    expect(() => assertZoomRange(0, 10)).toThrow(/reliefTiles\.ts/);
  });
});
