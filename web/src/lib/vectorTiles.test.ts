import { describe, it, expect } from "vitest";
import * as vectorTiles from "./vectorTiles";
import {
  VECTOR_CONTENT_TYPE,
  VECTOR_TILE_EXTENSION,
  describeVectorTileTypeMismatch,
} from "./vectorTiles";

describe("describeVectorTileTypeMismatch", () => {
  it("is silent when the archive stores what the globe asks for", () => {
    expect(describeVectorTileTypeMismatch(`.${VECTOR_TILE_EXTENSION}`)).toBeNull();
  });

  it("names the constant to change when the archive stores a raster codec", () => {
    const message = describeVectorTileTypeMismatch(".webp");
    expect(message).toContain("VECTOR_TILE_EXTENSION");
    expect(message).toContain("vectorTiles.ts");
  });

  it("names NO body and NO producer, because one function answers for every planet", () => {
    // It sat on countryTiles.ts and said "Countries archive stores …", naming
    // pipeline/compose/countries_pmtiles.py as the source of truth. Both are Earth's answers, and
    // this function is reached through `TileLayer`, which is the half of the registry that is the
    // same on every planet — so a Mars mismatch would have read as a fault in Earth's cutter.
    const message = describeVectorTileTypeMismatch(".webp") ?? "";
    expect(message).not.toContain("ountries");
    expect(message).not.toContain("countries_pmtiles");
    // The positive control: the sentence still has to be useful, not merely body-free.
    expect(message).toContain("webp");
  });

  it("says so even when pmtiles cannot name the encoding at all", () => {
    // tileTypeExt returns "" for an unknown type, and an empty string interpolated into the
    // message reads as the archive storing nothing rather than something unrecognised.
    expect(describeVectorTileTypeMismatch("")).toContain("cannot name");
  });
});

describe("the transport every body's vector pyramid shares", () => {
  it("declares protobuf, not an image type", () => {
    expect(VECTOR_CONTENT_TYPE).toBe("application/x-protobuf");
  });

  it("carries no per-body constant, which is the whole reason this module exists", () => {
    // Read off the MODULE, never off a literal listed here — a hand-kept list is exactly what a
    // new export slips past. A zoom range, a source-layer name or a producer path appearing here
    // would be one planet's answer on a contract every planet reads, which is the shape this split
    // was made to prevent and the one a later edit can undo with nothing else going red.
    const exported = Object.keys(vectorTiles);
    expect(exported.length, "the module exports nothing, so this guard sees nothing").toBeGreaterThan(0);
    for (const name of exported) {
      expect(name, `${name} names one planet's answer`).not.toMatch(/COUNTR|EARTH|MARS|ZOOM|LAYER/i);
    }
  });
});
