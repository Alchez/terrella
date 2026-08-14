import { readFileSync } from "node:fs";
import { describe, it, expect } from "vitest";
import type { FilterSpecification } from "maplibre-gl";
import { requireSourceLayer } from "./sourceLayers";

// Earth's three, read through the descriptor rather than restated. What the assertions below are
// for is the PLUMBING — that each builder reads its name off the binding — which is the half that
// shipped dead once: the hover wrote to a literal source id, MapLibre answered with an ErrorEvent
// and no throw, and nothing painted. The names' own values are pinned in sourceLayers.test.ts and,
// across the language seam, in tests/test_source_layers.py.
const COUNTRY_FILL_LAYER = requireSourceLayer("earth", "fill");
const COUNTRY_OUTLINE_LAYER = requireSourceLayer("earth", "outline");
const COUNTRY_HIT_LAYER = requireSourceLayer("earth", "hit");
import {
  COUNTRIES_SOURCE,
  VECTOR_BINDING,
  WASH_CLEAR_ZOOM,
  WASH_FULL_ZOOM,
  WASH_OPACITY,
  featureStateTargets,
  fillLayer,
  highlightLayers,
  hitLayer,
} from "./countryHighlight";

const filter: FilterSpecification = ["in", ["get", "ADMIN"], ["literal", ["Testland"]]];

// --- layer wiring ----------------------------------------------------------------------------
// All four layers read one vector source and differ only by SOURCE-LAYER. MapLibre renders a layer
// whose `source-layer` matches nothing as empty — no error, no warning — so a wrong name here is
// an invisible defect, which is why every layer's binding is asserted rather than just its type.
describe("layer wiring — one source, four source-layers", () => {
  it("the fill wash is a fill on the fill layer (fills never stroke a clipped edge)", () => {
    const layer = fillLayer(filter);
    expect(layer.type).toBe("fill");
    expect(layer.source).toBe(COUNTRIES_SOURCE);
    expect(layer["source-layer"]).toBe(COUNTRY_FILL_LAYER);
  });

  it("BOTH highlight layers are lines on the OUTLINE layer — this is the stray-meridian fix", () => {
    const layers = highlightLayers(filter);
    expect(layers.map((l) => l.id)).toEqual(["country-hl-casing", "country-hl-line"]);
    for (const layer of layers) {
      expect(layer.type).toBe("line");
      // The regression these guard: stroking the POLYGON layer instead draws the ring MapLibre
      // closes along a tile cut, as a stray gold meridian across the hovered country. Clipping a
      // line only trims it, which is why the archive carries the rings as their own line layer.
      expect(layer["source-layer"]).toBe(COUNTRY_OUTLINE_LAYER);
      expect(layer["source-layer"]).not.toBe(COUNTRY_FILL_LAYER);
    }
  });

  it("the hit targets are circles on the hit layer, and carry the in-scope filter", () => {
    // The filter is a correctness fix rather than symmetry: the archive deliberately carries ALL
    // countries so a newly rendered hero needs no re-cut, so without it every unrendered country
    // would become clickable and fly to a page that has no hero.
    const layer = hitLayer(filter);
    expect(layer.type).toBe("circle");
    expect(layer["source-layer"]).toBe(COUNTRY_HIT_LAYER);
    expect(layer.filter).toEqual(filter);
  });

  it("every layer reads the same source, which is what lets one write light them together", () => {
    const layers = [fillLayer(filter), ...highlightLayers(filter), hitLayer(filter)];
    expect(new Set(layers.map((layer) => layer.source))).toEqual(new Set([COUNTRIES_SOURCE]));
    expect(new Set(layers.map((layer) => layer["source-layer"])).size).toBe(3);
  });
});

// --- the wash's zoom fade ----------------------------------------------------------------------
// READS THE SHIPPED EXPRESSION RATHER THAN RESTATING IT. Everything below goes through this walker,
// so a curve that no longer has zoom as its top-level input throws here instead of quietly being
// re-derived from the constants — which is the failure the fade is most likely to take, because
// MapLibre answers a wrongly-nested `["zoom"]` with an ErrorEvent and no throw at all.
function washOpacityAt(zoom: number, hovered: boolean): number {
  const expression = fillLayer(filter).paint?.["fill-opacity"];
  if (!Array.isArray(expression)) throw new Error("the wash's opacity is no longer an expression");
  const [operator, interpolation, input, ...stopPairs] = expression as unknown[];
  if (operator !== "interpolate") {
    throw new Error(`the zoom curve must be outermost, found \`${String(operator)}\` there`);
  }
  if (JSON.stringify(interpolation) !== JSON.stringify(["linear"])) {
    throw new Error(`unreadable interpolation: ${JSON.stringify(interpolation)}`);
  }
  if (JSON.stringify(input) !== JSON.stringify(["zoom"])) {
    throw new Error(`the curve's input must be ["zoom"], found ${JSON.stringify(input)}`);
  }

  const stops: [number, unknown][] = [];
  for (let index = 0; index < stopPairs.length; index += 2) {
    stops.push([stopPairs[index] as number, stopPairs[index + 1]]);
  }
  if (stops.length < 2) throw new Error("a fade needs at least two stops");

  // A stop's output is either a bare number or the hover `case` — anything else means the shape
  // moved and the reader should fail rather than guess at it.
  const outputAt = (output: unknown): number => {
    if (typeof output === "number") return output;
    if (Array.isArray(output) && output[0] === "case") return (hovered ? output[2] : output[3]) as number;
    throw new Error(`unreadable stop output: ${JSON.stringify(output)}`);
  };

  if (zoom <= stops[0][0]) return outputAt(stops[0][1]);
  const last = stops[stops.length - 1];
  if (zoom >= last[0]) return outputAt(last[1]);
  for (let index = 0; index < stops.length - 1; index += 1) {
    const [lowZoom, lowOutput] = stops[index];
    const [highZoom, highOutput] = stops[index + 1];
    if (zoom < lowZoom || zoom > highZoom) continue;
    const progress = (zoom - lowZoom) / (highZoom - lowZoom);
    return outputAt(lowOutput) + progress * (outputAt(highOutput) - outputAt(lowOutput));
  }
  throw new Error(`no stop pair covers z${zoom}`);
}

describe("the wash fades out with zoom, and the outline does not", () => {
  it("holds the ratified strength at every zoom a country still reads as a shape", () => {
    // 0.16 is the strength that was judged on the globe. It is pinned as a NUMBER rather than
    // compared against itself, because a suite that only ever checks ratios stays green while the
    // whole curve is rescaled — every relative assertion below would survive a doubled wash.
    expect(WASH_OPACITY).toBe(0.16);
    expect(washOpacityAt(0, true)).toBeCloseTo(WASH_OPACITY, 5);
    expect(washOpacityAt(3, true)).toBeCloseTo(WASH_OPACITY, 5);
    expect(washOpacityAt(WASH_FULL_ZOOM, true)).toBeCloseTo(WASH_OPACITY, 5);
  });

  it("is gone once the viewport is inside one country, and stays gone above that", () => {
    expect(washOpacityAt(WASH_CLEAR_ZOOM, true)).toBeCloseTo(0, 5);
    expect(washOpacityAt(8, true)).toBeCloseTo(0, 5);
  });

  it("still paints in the frame a clicked country lands in", () => {
    // THE ONE ASSERTION TIED TO SOMETHING OUTSIDE THIS CURVE. `flyToCountry` caps its fit at z6, so
    // that zoom is where a clicked country is framed and where the wash is most worth having. A
    // fade that started earlier would pass every other test here and land its own flight on a
    // country with nothing lit.
    const FLY_TO_LANDING_CAP = 6;
    expect(WASH_FULL_ZOOM).toBeLessThan(FLY_TO_LANDING_CAP);
    expect(WASH_CLEAR_ZOOM).toBeGreaterThan(FLY_TO_LANDING_CAP);
    expect(washOpacityAt(FLY_TO_LANDING_CAP, true)).toBeGreaterThan(WASH_OPACITY / 2);
  });

  it("falls monotonically across the fade rather than jumping at its ends", () => {
    const zooms = [WASH_FULL_ZOOM, 5.9, 6.25, 6.6, WASH_CLEAR_ZOOM];
    const opacities = zooms.map((zoom) => washOpacityAt(zoom, true));
    for (let index = 1; index < opacities.length; index += 1) {
      expect(opacities[index], `z${zooms[index]} against z${zooms[index - 1]}`).toBeLessThan(
        opacities[index - 1],
      );
    }
  });

  it("paints nothing at all without a hover, at every zoom", () => {
    for (const zoom of [0, 3, WASH_FULL_ZOOM, 6, WASH_CLEAR_ZOOM, 8]) {
      expect(washOpacityAt(zoom, false), `z${zoom} un-hovered`).toBe(0);
    }
  });

  it("leaves the outline's width untouched, because it never grew in the first place", () => {
    // The outline is interpolated in SCREEN px, so it cannot swamp anything — the asymmetry is the
    // whole design, and a future edit that "makes them consistent" would delete the highlight at
    // exactly the zooms where it is the only thing left saying where the border is.
    for (const layer of highlightLayers(filter)) {
      const opacity = layer.paint?.["line-opacity"];
      expect(Array.isArray(opacity) && opacity[0], layer.id).toBe("case");
      const width = layer.paint?.["line-width"];
      expect(Array.isArray(width) && width[0], layer.id).toBe("interpolate");
    }
  });
});

// --- featureStateTargets: where the hover flag is written -------------------------------------
// The regression these exist for shipped to production: the hover painter named its source ids
// literally, so it addressed a source that does not exist here AND a vector source without a
// `sourceLayer`. MapLibre answers both by firing an ErrorEvent and returning — no throw, nothing a
// unit test could catch from the outside — so the outline and the wash simply never painted.
describe("featureStateTargets — the hover flag reaches both painted layers", () => {
  it("addresses the fill and the outline, and never the hit layer", () => {
    const targets = featureStateTargets(VECTOR_BINDING);
    expect(targets).toHaveLength(2);
    // The hit circles carry no hover paint; a write there could only mask a missing one here.
    expect(targets).not.toContainEqual({
      source: VECTOR_BINDING.hit.source,
      sourceLayer: VECTOR_BINDING.hit["source-layer"],
    });
  });

  it("every target carries a sourceLayer — MapLibre refuses a vector target without one", () => {
    const targets = featureStateTargets(VECTOR_BINDING);
    for (const target of targets) {
      expect(target.sourceLayer, JSON.stringify(target)).toBeTruthy();
    }
    expect(targets).toEqual([
      { source: COUNTRIES_SOURCE, sourceLayer: COUNTRY_FILL_LAYER },
      { source: COUNTRIES_SOURCE, sourceLayer: COUNTRY_OUTLINE_LAYER },
    ]);
  });

  it("the two targets are distinct, because feature state keys on (source, sourceLayer, id)", () => {
    // Same source id twice is correct and must NOT be deduplicated: fill and outline live in
    // different source-layers, so one setFeatureState cannot light both.
    const [fill, outline] = featureStateTargets(VECTOR_BINDING);
    expect(fill.source).toBe(outline.source);
    expect(fill.sourceLayer).not.toBe(outline.sourceLayer);
  });

  it("the hover painter derives its targets rather than naming source ids", () => {
    // The unit tests above cannot see the call site, and the call site is where this went wrong.
    // A literal `source:` inside a setFeatureState call is that mistake, in the only shape it takes.
    const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");
    const calls = globe.match(/setFeatureState\([^)]*\)/g) ?? [];
    expect(calls.length, "earth.astro must still paint the hover highlight").toBeGreaterThan(0);
    for (const call of calls) {
      expect(call, "spread a featureStateTargets entry instead").not.toMatch(/\bsource:/);
    }
  });
});
