import { describe, it, expect } from "vitest";
import {
  COUNTRIES_CONTENT_TYPE,
  COUNTRIES_PATH_PREFIX,
  COUNTRIES_TILE_EXTENSION,
  COUNTRY_FILL_LAYER,
  COUNTRY_HIT_LAYER,
  COUNTRY_OUTLINE_LAYER,
  describeCountriesTileTypeMismatch,
  parseCountriesTilePath,
} from "./countryTiles";
import { parseTilePath } from "./reliefTiles";
import { parseTerrainTilePath } from "./terrainSource";

describe("parseCountriesTilePath", () => {
  it("parses a country tile address, with or without the leading slash", () => {
    expect(parseCountriesTilePath("/countries/8/189/107.mvt")).toEqual({ z: 8, x: 189, y: 107 });
    expect(parseCountriesTilePath("countries/0/0/0.mvt")).toEqual({ z: 0, x: 0, y: 0 });
  });

  it("rejects addresses outside the archive's zoom range", () => {
    expect(parseCountriesTilePath("/countries/9/0/0.mvt")).toBeNull();
  });

  it("rejects coordinates outside the 2^z grid", () => {
    // A typo'd URL must not cost a range read against the archive — same rule as both siblings.
    expect(parseCountriesTilePath("/countries/0/1/0.mvt")).toBeNull();
    expect(parseCountriesTilePath("/countries/1/0/2.mvt")).toBeNull();
  });

  it("rejects the raster codec under its own prefix", () => {
    expect(parseCountriesTilePath("/countries/8/189/107.webp")).toBeNull();
  });

  // The property the router leans on. Three parsers share one mount, and a path any two of them
  // both accept would serve one archive's bytes under another's content type — which for vector
  // vs raster means a globe with no countries and no error to say why.
  it("cannot match anything the relief or terrain parsers match, in either direction", () => {
    const countryPaths = ["/countries/0/0/0.mvt", "/countries/8/189/107.mvt"];
    const otherPaths = ["/0/0/0.webp", "/8/189/107.webp", "/terrain/8/189/107.webp"];
    for (const path of countryPaths) {
      expect(parseTilePath(path), path).toBeNull();
      expect(parseTerrainTilePath(path), path).toBeNull();
    }
    for (const path of otherPaths) {
      expect(parseCountriesTilePath(path), path).toBeNull();
    }
  });
});

describe("describeCountriesTileTypeMismatch", () => {
  it("is silent when the archive stores what the globe asks for", () => {
    expect(describeCountriesTileTypeMismatch(`.${COUNTRIES_TILE_EXTENSION}`)).toBeNull();
  });

  it("names the constant to change when the archive stores a raster codec", () => {
    const message = describeCountriesTileTypeMismatch(".webp");
    expect(message).toContain("COUNTRIES_TILE_EXTENSION");
    expect(message).toContain("countries_pmtiles.py");
  });

  it("says so even when pmtiles cannot name the encoding at all", () => {
    // tileTypeExt returns "" for an unknown type, and an empty string interpolated into the
    // message reads as the archive storing nothing rather than something unrecognised.
    expect(describeCountriesTileTypeMismatch("")).toContain("cannot name");
  });
});

describe("the archive contract the pipeline writes", () => {
  it("keeps the prefix its own parser reads, which is the legacy grammar's discriminator", () => {
    // The prefix no longer appears in anything the browser ASKS for — tileAddress.ts builds those
    // from `{body}/{layer}/…`, where `countries` is the layer segment. It survives here because
    // `parseCountriesTilePath` is what still accepts the shape pages built before the switch are
    // asking for, and it goes when that branch does.
    expect(COUNTRIES_PATH_PREFIX).toBe("countries");
    expect(parseCountriesTilePath(`${COUNTRIES_PATH_PREFIX}/3/4/3.mvt`)).toEqual({ z: 3, x: 4, y: 3 });
  });

  it("declares protobuf, not an image type", () => {
    expect(COUNTRIES_CONTENT_TYPE).toBe("application/x-protobuf");
  });

  // These three strings are MapLibre `source-layer` values, and their writer is a Python file no
  // type system reaches. A disagreement renders every country layer empty, with no error and no
  // warning — so pin them here and in tests/test_countries_pmtiles.py, which reads the same names
  // out of the pipeline module.
  it("pins the source-layer names the cutter writes", () => {
    expect([COUNTRY_FILL_LAYER, COUNTRY_OUTLINE_LAYER, COUNTRY_HIT_LAYER]).toEqual([
      "country_fill",
      "country_outline",
      "country_hit",
    ]);
  });
});
