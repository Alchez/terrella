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
