import type {
  CircleLayerSpecification,
  ExpressionSpecification,
  FillLayerSpecification,
  FilterSpecification,
  LineLayerSpecification,
  VectorSourceSpecification,
} from "maplibre-gl";

import {
  COUNTRIES_MAX_ZOOM,
  COUNTRIES_MIN_ZOOM,
  COUNTRY_FILL_LAYER,
  COUNTRY_HIT_LAYER,
  COUNTRY_OUTLINE_LAYER,
} from "./countryTiles";

// The country hover-highlight, factored out of globe.astro so its load-bearing wiring is
// unit-testable (see countryHighlight.test.ts). Two choices here are non-obvious and each
// fixes a globe artifact that a future edit could silently reintroduce, and BOTH are now decided
// at cut time rather than here — see countries_pmtiles.py:
//   - the outline strokes the `country_outline` LINE layer, never the polygon. Clipping a line
//     trims it; clipping a polygon closes the ring along the cut, and a `line` layer would stroke
//     that phantom edge as a stray gold meridian across the hovered country.
//   - the archive is cut with BUFFER=0, otherwise the translucent fill wash double-paints in the
//     tile-buffer overlap — a visibly stronger patch near the pole.

/** The one source id. Exported so the layers below AND the hover feature-state key off the same
 *  string — a typo in either would silently break the highlight.
 *
 *  There used to be three (`country-outlines`, `country-hits`), because the GeoJSON arm needed a
 *  separate source per layer. One vector archive carries all three as SOURCE-LAYERS instead, which
 *  is also what lets a single `setFeatureState` light the fill and the outline together. */
export const COUNTRIES_SOURCE = "countries";

/** Where one country layer reads its features from.
 *
 *  ONE VALUE TODAY, AND STILL WORTH THE INDIRECTION. This carried the difference between the
 *  vector arm and the GeoJSON arm it replaced; what it carries now is the SOURCE-LAYER NAMES,
 *  spelled once. MapLibre renders a layer whose `source-layer` matches nothing as EMPTY — no
 *  error, no warning — so a typo at any of the four call sites would silently blank a layer.
 *  Spelling them here instead makes that a single point of failure with a test on it. */
interface LayerBinding {
  source: string;
  "source-layer"?: string;
}

export interface CountrySourceBinding {
  fill: LayerBinding;
  outline: LayerBinding;
  hit: LayerBinding;
}

/** One vector source, three source-layers. The source id is reused deliberately: the hover
 *  feature-state keys off (source, sourceLayer, id), so fill and outline sharing a source is what
 *  lets one `setFeatureState` light both — the same thing the shared `promoteId` bought before. */
export const VECTOR_BINDING: CountrySourceBinding = {
  fill: { source: COUNTRIES_SOURCE, "source-layer": COUNTRY_FILL_LAYER },
  outline: { source: COUNTRIES_SOURCE, "source-layer": COUNTRY_OUTLINE_LAYER },
  hit: { source: COUNTRIES_SOURCE, "source-layer": COUNTRY_HIT_LAYER },
};

/** What `map.setFeatureState` needs to address one layer's features: MapLibre's own key spelling,
 *  which is `sourceLayer` here and `source-layer` in a layer spec. */
export interface FeatureStateTarget {
  source: string;
  sourceLayer?: string;
}

/**
 * Everywhere the hover flag has to be written for one country to light up whole.
 *
 * DERIVED FROM THE BINDING, AND THAT IS THE FIX RATHER THAN THE TIDYING. The hover painter used to
 * name its two source ids literally, which was correct for the GeoJSON arm and wrong for this one:
 * `country-outlines` did not exist here, and `countries` is a vector source, which
 * `setFeatureState` will not address without a `sourceLayer`. MapLibre answers BOTH by firing an
 * ErrorEvent and RETURNING — no throw — so no state was written, `whenHovered` stayed false
 * everywhere, and the gold outline and the fill wash silently did nothing in production. Three of
 * the four layer call sites took the binding; this one did not, and nothing typed could see it.
 *
 * The hit layer is absent on purpose: it carries no hover paint, and writing state to a layer that
 * cannot show it would only widen the surface for the same mistake.
 *
 * Both entries survive even though they share a source id — fill and outline are different
 * source-layers, and feature state is keyed on (source, sourceLayer, id), so one write cannot
 * serve both.
 */
export function featureStateTargets(binding: CountrySourceBinding): FeatureStateTarget[] {
  return [binding.fill, binding.outline].map((layer) => ({
    source: layer.source,
    sourceLayer: layer["source-layer"],
  }));
}

/** Warm gold reads on all three grounds (teal sea, warm sand, white snow) where the teal
 *  accent would vanish along coasts; the dark casing carries it over snow. */
export const HIGHLIGHT_GOLD = "#eca834";
export const HIGHLIGHT_CASING = "#1c140c";

/** True only while this feature is the one under the pointer (its feature-state `hover`). */
const whenHovered: ExpressionSpecification = ["boolean", ["feature-state", "hover"], false];

/**
 * The country VECTOR source — one archive carrying all three layers.
 *
 * Replaces three GeoJSON sources with one, and the reason is the main thread rather than tidiness:
 * a `vector` source is addressed by URL, so MapLibre's worker fetches, parses, tiles and
 * tessellates, while an object source is deep-rebuilt by `serialize()` and structured-cloned on
 * the main thread. See {@link countriesSource} and countryTiles.ts.
 *
 * `promoteId` is a BARE STRING rather than the per-source-layer object form. The style spec allows
 * either for a vector source, and the string applies to every source-layer — verified live,
 * including the part that could quietly half-work: a country split across tiles (Brazil arrives as
 * two pieces at z1.6) takes one `setFeatureState` across all of them.
 *
 * There is no `buffer` here and there cannot be: tile buffering is baked at cut time, which is why
 * `BUFFER=0` is a `-dsco` in countries_pmtiles.py. Same decision as the `buffer: 0` above, made in
 * the only place a vector pyramid can make it.
 */
export function countryTilesSource(tileUrlTemplate: string): VectorSourceSpecification {
  return {
    type: "vector",
    tiles: [tileUrlTemplate],
    minzoom: COUNTRIES_MIN_ZOOM,
    maxzoom: COUNTRIES_MAX_ZOOM,
    promoteId: "ADMIN",
  };
}

/**
 * The warm silhouette wash over the whole hovered landmass. A FILL over the polygon source —
 * fills never stroke a clipped tile edge, so this one is safe on {@link COUNTRIES_SOURCE}.
 */
export function fillLayer(
  filter: FilterSpecification,
  binding: LayerBinding = VECTOR_BINDING.fill,
): FillLayerSpecification {
  return {
    id: "country-fill",
    type: "fill",
    ...binding,
    filter,
    paint: {
      "fill-color": HIGHLIGHT_GOLD,
      "fill-opacity": ["case", whenHovered, 0.16, 0],
    },
  };
}

/**
 * Casing + gold line for the hovered country's boundary, added ABOVE the borders so the edge
 * stays crisp. Both stroke the `country_outline` LINE layer, never the polygon — that is the
 * stray-meridian fix. Returned casing-first so the caller preserves under/over order.
 */
export function highlightLayers(
  filter: FilterSpecification,
  binding: LayerBinding = VECTOR_BINDING.outline,
): LineLayerSpecification[] {
  return [
    {
      id: "country-hl-casing",
      type: "line",
      ...binding,
      filter,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": HIGHLIGHT_CASING,
        "line-width": ["interpolate", ["linear"], ["zoom"], 0.5, 3.4, 4, 4.8, 8, 6.0],
        "line-blur": 1.2,
        "line-opacity": ["case", whenHovered, 0.5, 0],
      },
    },
    {
      id: "country-hl-line",
      type: "line",
      ...binding,
      filter,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": HIGHLIGHT_GOLD,
        "line-width": ["interpolate", ["linear"], ["zoom"], 0.5, 1.8, 4, 2.8, 8, 3.6],
        "line-blur": 0.4,
        "line-opacity": ["case", whenHovered, 1, 0],
      },
    },
  ];
}

/**
 * Fat, invisible per-island pointing targets. The circle's own radius IS the hit tolerance
 * (~12 px at overview, wider zoomed in), so pointing anywhere near an atoll picks the country —
 * Maldives is 176 sub-pixel atolls and cannot be hit via its real geometry at any zoom.
 *
 * IT NOW TAKES A FILTER, WHICH IT DID NOT BEFORE, and that is a correctness fix rather than
 * symmetry. This was the only one of the four country layers with no runtime filter: it relied on
 * the derived layer having already dropped out-of-scope countries at build time. The archive
 * deliberately carries ALL countries — so that a newly rendered hero does not require re-cutting
 * tiles, and so "which countries are interactive" stays single-homed in the manifest — and without
 * a filter here every unrendered country would become clickable and fly to a page that has no hero.
 *
 * KEEP THIS LAYER LAST in the style. MapLibre drapes only background/fill/line/raster/hillshade/
 * color-relief onto the terrain mesh; a `circle` interrupts the run and starts a new
 * render-to-texture stack, and the pool holds one 1 MiB object per renderable terrain tile PER
 * stack. Sitting mid-order this cost a third of the pool to draw nothing. See drapeStacks.ts,
 * whose canary fails if MapLibre ever starts draping `circle`.
 */
export function hitLayer(
  filter: FilterSpecification,
  binding: LayerBinding = VECTOR_BINDING.hit,
): CircleLayerSpecification {
  return {
    id: "country-hit",
    type: "circle",
    ...binding,
    filter,
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 0.5, 12, 4, 14, 8, 16],
      "circle-opacity": 0,
      "circle-stroke-width": 0,
    },
  };
}
