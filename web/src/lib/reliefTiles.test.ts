// parseTilePath is the front door of every tile server we run — the dev middleware and the R2
// Worker. Anything it accepts becomes a range read against a multi-GB archive, so the rejections
// matter more than the acceptances: a bad path must cost a 404, not a seek.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  RELIEF_MAX_ZOOM,
  TILE_CONTENT_TYPE,
  TILE_EXTENSION,
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
  });

  it("keeps the content type and the parser on the same format", () => {
    // The template that used to be pinned here has moved to tileAddress.ts, which composes this
    // extension into `{body}/{layer}/{token}/{z}/{x}/{y}.webp` and is pinned there. What is left in
    // this module is the encoding itself and the parser that must follow it.
    expect(TILE_CONTENT_TYPE).toBe(`image/${TILE_EXTENSION}`);
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

describe("describeTileTypeMismatch", () => {
  it("returns null when the archive stores what the globe asks for", () => {
    expect(describeTileTypeMismatch(`.${TILE_EXTENSION}`)).toBeNull();
  });

  it("reports a re-cut to a different encoding, naming both files to edit", () => {
    const message = describeTileTypeMismatch(".png");
    expect(message).toContain(".png");
    expect(message).toContain("reliefTiles.ts");
    expect(message).toContain("cut_tiles.py");
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

// The two source SPECS moved to reliefSources.ts, where they can be asserted as objects rather than
// as page text — see reliefSources.test.ts. What has to stay a source scan is the one thing that is
// genuinely a property of the page: the order the style draws them in.
describe("the pinned base source in the page's style", () => {
  const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");

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
