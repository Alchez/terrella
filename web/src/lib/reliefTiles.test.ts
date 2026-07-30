// parseTilePath is the front door of every tile server we run — the dev middleware and the R2
// Worker. Anything it accepts becomes a range read against a multi-GB archive, so the rejections
// matter more than the acceptances: a bad path must cost a 404, not a seek.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  RELIEF_BASE_MAX_ZOOM,
  RELIEF_MAX_ZOOM,
  RELIEF_MIN_ZOOM,
  TILE_CONTENT_TYPE,
  TILE_EXTENSION,
  TILE_PATH_TEMPLATE,
  assertZoomRange,
  describeTileTypeMismatch,
  parseTilePath,
} from "./reliefTiles";

/** Paths are BUILT from the constant so the suite follows a format change instead of pinning one
 *  spelling in twelve places — with `declares the archive's encoding` below as the one test that
 *  asserts the concrete value, which is what stops the rest going tautological. */
const tile = (path: string) => `${path}.${TILE_EXTENSION}`;

describe("the tile encoding", () => {
  it("declares the archive's encoding, and declares it once", () => {
    expect(TILE_EXTENSION).toBe("webp");
    expect(TILE_CONTENT_TYPE).toBe("image/webp");
    expect(TILE_PATH_TEMPLATE).toBe("{z}/{x}/{y}.webp");
  });

  it("keeps the template, the content type and the parser on the same format", () => {
    expect(TILE_CONTENT_TYPE).toBe(`image/${TILE_EXTENSION}`);
    expect(TILE_PATH_TEMPLATE.endsWith(`.${TILE_EXTENSION}`)).toBe(true);
    expect(parseTilePath(tile("/3/4/3"))).not.toBeNull();
  });
});

describe("parseTilePath", () => {
  it("reads a tile address, with or without the leading slash", () => {
    expect(parseTilePath(tile("/3/4/3"))).toEqual({ z: 3, x: 4, y: 3 });
    expect(parseTilePath(tile("3/4/3"))).toEqual({ z: 3, x: 4, y: 3 });
  });

  it("accepts the corners of the pyramid", () => {
    expect(parseTilePath(tile("/0/0/0"))).toEqual({ z: 0, x: 0, y: 0 });
    expect(parseTilePath(tile(`/${RELIEF_MAX_ZOOM}/255/255`))).toEqual({ z: 8, x: 255, y: 255 });
  });

  it("rejects a zoom outside the packaged pyramid", () => {
    expect(parseTilePath(tile(`/${RELIEF_MAX_ZOOM + 1}/0/0`))).toBeNull();
  });

  it("rejects coordinates outside the 2^z grid at that zoom", () => {
    expect(parseTilePath(tile("/0/1/0"))).toBeNull();
    expect(parseTilePath(tile("/8/256/0"))).toBeNull();
    expect(parseTilePath(tile("/8/0/256"))).toBeNull();
  });

  it("rejects negative, non-numeric and traversal-shaped paths", () => {
    expect(parseTilePath(tile("/-1/0/0"))).toBeNull();
    expect(parseTilePath(tile("/3/x/3"))).toBeNull();
    expect(parseTilePath("/3/4/../../etc/passwd")).toBeNull();
    expect(parseTilePath("/../planet.pmtiles")).toBeNull();
  });

  it("rejects any other extension — the archive stores one encoding and nothing else", () => {
    expect(parseTilePath("/3/4/3.png")).toBeNull();
    expect(parseTilePath("/3/4/3.jpg")).toBeNull();
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

describe("describeTileTypeMismatch", () => {
  it("returns null when the archive stores what the globe asks for", () => {
    expect(describeTileTypeMismatch(`.${TILE_EXTENSION}`)).toBeNull();
  });

  it("reports a re-cut to a different encoding, naming both files to edit", () => {
    const message = describeTileTypeMismatch(".png");
    expect(message).toContain(".png");
    expect(message).toContain("reliefTiles.ts");
    expect(message).toContain("shade_planet.py");
  });

  it("still reports when pmtiles cannot name the encoding at all", () => {
    // tileTypeExt() returns "" for TileType.Unknown — an empty extension must not read as a
    // match, which is exactly what a bare `archiveExtension === TILE_EXTENSION` would do.
    expect(describeTileTypeMismatch("")).toContain("cannot name");
  });

  it("does not accept the extension without its dot", () => {
    // The callers pass tileTypeExt() output (".webp"), so a bare "webp" means someone wired a
    // different source in — that should fail loudly rather than silently pass.
    expect(describeTileTypeMismatch(TILE_EXTENSION)).not.toBeNull();
  });
});

describe("the pinned base source — a floor that is a map, not a colour", () => {
  const globe = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");

  it("caps the base source at z0, because that is what makes it unmissable", () => {
    // The guarantee is arithmetic, not luck: a raster source's covering set is clamped to its own
    // maxzoom, so at 0 there is exactly ONE tile, ideal at every camera, therefore never absent
    // after first load. At z1 the set is still camera-dependent and a first visit to a cold
    // quadrant paints nothing — measured on production, so this constant is load-bearing.
    expect(RELIEF_BASE_MAX_ZOOM).toBe(0);
    const source = globe.match(/const reliefBaseSource[\s\S]*?\n  \};/)?.[0];
    expect(source, "the base source must exist").toBeTruthy();
    expect(source).toContain("maxzoom: RELIEF_BASE_MAX_ZOOM");
    // A second attribution would render CREDITS twice in the control.
    expect(source).not.toContain("attribution");
  });

  it("draws the base UNDER relief and OVER the background, or it is pointless", () => {
    // Above relief it would hide the real tiles; below the background it would never be seen.
    const layers = globe.match(/layers: \[[\s\S]*?\n      \],/)?.[0];
    expect(layers, "the style's layer list must exist").toBeTruthy();
    const floor = layers!.indexOf('id: "space-floor"');
    const base = layers!.indexOf('id: "relief-base"');
    const relief = layers!.indexOf('id: "relief", type: "raster"');
    expect(floor).toBeGreaterThanOrEqual(0);
    expect(base).toBeGreaterThan(floor);
    expect(relief).toBeGreaterThan(base);
    expect(globe).toContain('"relief-base": reliefBaseSource');
  });
});
