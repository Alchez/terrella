import { describe, it, expect } from "vitest";
import type { Feature, FeatureCollection } from "geojson";
import type { FilterSpecification } from "maplibre-gl";
import {
  COUNTRIES_SOURCE,
  OUTLINE_SOURCE,
  outlinesFrom,
  countriesSource,
  outlineSource,
  fillLayer,
  highlightLayers,
} from "./countryHighlight";

// --- fixtures -------------------------------------------------------------------------------
// Rings are closed (first === last), the way GeoJSON polygons come; outlinesFrom passes them
// through verbatim, so the tests assert the exact ring arrays survive.
const squareRing = [
  [0, 0],
  [2, 0],
  [2, 2],
  [0, 2],
  [0, 0],
];
const holeRing = [
  [0.5, 0.5],
  [1.5, 0.5],
  [1.5, 1.5],
  [0.5, 1.5],
  [0.5, 0.5],
];
const otherRing = [
  [10, 10],
  [12, 10],
  [12, 12],
  [10, 10],
];

const polygonCountry = (admin: string, rings = [squareRing]): Feature => ({
  type: "Feature",
  properties: { ADMIN: admin },
  geometry: { type: "Polygon", coordinates: rings },
});

const collection = (features: Feature[]): FeatureCollection => ({
  type: "FeatureCollection",
  features,
});

const all = () => true;
const filter: FilterSpecification = ["in", ["get", "ADMIN"], ["literal", ["Testland"]]];

// --- outlinesFrom: the polygon -> boundary-lines conversion ----------------------------------
describe("outlinesFrom — polygon rings become boundary lines", () => {
  it("a Polygon becomes a MultiLineString of its rings (outer + every hole)", () => {
    const out = outlinesFrom(collection([polygonCountry("Testland", [squareRing, holeRing])]), all);
    expect(out.features).toHaveLength(1);
    const geometry = out.features[0].geometry;
    expect(geometry.type).toBe("MultiLineString");
    // holes are stroked too — the old inline `line`-over-polygon did, so parity is preserved.
    expect(geometry).toMatchObject({ coordinates: [squareRing, holeRing] });
  });

  it("a MultiPolygon flattens ALL parts' rings into one MultiLineString", () => {
    const multi: Feature = {
      type: "Feature",
      properties: { ADMIN: "Archipelago" },
      geometry: { type: "MultiPolygon", coordinates: [[squareRing], [otherRing]] },
    };
    const out = outlinesFrom(collection([multi]), all);
    expect(out.features[0].geometry).toMatchObject({
      type: "MultiLineString",
      coordinates: [squareRing, otherRing],
    });
  });

  it("carries ADMIN through so feature-state hover keys the whole country", () => {
    const out = outlinesFrom(collection([polygonCountry("Testland")]), all);
    expect(out.features[0].properties?.ADMIN).toBe("Testland");
  });

  it("keeps only in-scope countries (the predicate selects rendered/interactive ones)", () => {
    const fc = collection([polygonCountry("Testland"), polygonCountry("Elsewhere")]);
    const out = outlinesFrom(fc, (admin) => admin === "Testland");
    expect(out.features.map((f) => f.properties?.ADMIN)).toEqual(["Testland"]);
  });

  it("skips features with a non-string ADMIN", () => {
    const bad: Feature = {
      type: "Feature",
      properties: { ADMIN: 42 },
      geometry: { type: "Polygon", coordinates: [squareRing] },
    };
    expect(outlinesFrom(collection([bad]), all).features).toHaveLength(0);
  });

  it("skips non-polygon geometry (e.g. the hit-point Points)", () => {
    const point: Feature = {
      type: "Feature",
      properties: { ADMIN: "Testland" },
      geometry: { type: "Point", coordinates: [0, 0] },
    };
    expect(outlinesFrom(collection([point]), all).features).toHaveLength(0);
  });
});

// --- wiring guards: the two non-obvious config choices that fix globe artifacts --------------
// If either of these regresses, the corresponding artifact returns on /globe (and it only shows
// looking down the pole, which is easy to miss in review) — so lock them here.
describe("countriesSource — the polygon source's buffer:0 stops the fill double-paint", () => {
  it("sets buffer:0 (default 128px tile buffers make the translucent fill paint twice)", () => {
    expect(countriesSource(collection([])).buffer).toBe(0);
  });

  it("promotes ADMIN to the feature id for feature-state hover", () => {
    expect(countriesSource(collection([])).promoteId).toBe("ADMIN");
  });
});

describe("layer wiring — the hover outline must stroke the LINE source, never the polygon", () => {
  it("the fill wash is a fill on the polygon source (fills never stroke a clipped edge)", () => {
    const layer = fillLayer(filter);
    expect(layer.type).toBe("fill");
    expect(layer.source).toBe(COUNTRIES_SOURCE);
  });

  it("BOTH highlight layers are lines on the outline source — this is the stray-meridian fix", () => {
    const layers = highlightLayers(filter);
    expect(layers.map((l) => l.id)).toEqual(["country-hl-casing", "country-hl-line"]);
    for (const layer of layers) {
      expect(layer.type).toBe("line");
      // the regression: pointing these back at COUNTRIES_SOURCE strokes the polygon's clipped
      // tile edge as a stray gold meridian across the hovered country.
      expect(layer.source).toBe(OUTLINE_SOURCE);
      expect(layer.source).not.toBe(COUNTRIES_SOURCE);
    }
  });

  it("the outline source is a distinct id from the polygon source, both promoting ADMIN", () => {
    expect(OUTLINE_SOURCE).not.toBe(COUNTRIES_SOURCE);
    expect(outlineSource(collection([])).promoteId).toBe("ADMIN");
  });
});
