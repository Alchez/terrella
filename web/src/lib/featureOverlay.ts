/** MARS's named-feature overlay — the vector source, its two hit surfaces, and its hover linework.
 *
 *  The sibling of countryHighlight.ts, and deliberately not a generalisation of it. Both draw one
 *  body's vector archive, and there the resemblance stops: Earth's stack is filtered to the hero
 *  manifest and hit-tested against fat per-island circles baked into the archive, neither of which
 *  Mars's can answer — there is no manifest to filter by and no `hit` layer to point at. What the
 *  two share is the transport (vectorTiles.ts) and the role vocabulary (sourceLayers.ts), which is
 *  exactly what those two modules were split out to hold.
 *
 *  NOTHING HERE PAINTS UNTIL THE POINTER ASKS, and that is the decision rather than a gap. A vector
 *  pyramid is INTERACTION DATA on this globe, not first-paint content — Earth's `country-fill` has
 *  sat at opacity 0 since it was written. Mars was drawn permanently for one commit and it was wrong
 *  twice over: it broke that rule, and the outlines it painted traced crater rims the RELIEF ALREADY
 *  RENDERS, in shadow, better.
 *
 *  WHICH feature the pointer picks is featureTargeting.ts's question, not this module's. That split
 *  matters here more than it does on Earth: the catalogue mixes scales so badly that the naive
 *  answer is a continent almost everywhere, and the rule that fixes it is arithmetic over a diameter
 *  rather than anything about a layer spec.
 *
 *  THERE ARE TWO OF EVERYTHING BECAUSE THE ARCHIVE HAS TWO KINDS OF FEATURE, and they are disjoint
 *  sets rather than two views of one. The polygons carry a ring in `feature_outline`; the valles,
 *  rupes and fossae carry no polygon at all and live only in `feature_line`. A style layer reads one
 *  source-layer, so a hit surface and a highlight that must cover both is four layers, not two.
 */

import type {
  ExpressionSpecification,
  FillLayerSpecification,
  LineLayerSpecification,
  VectorSourceSpecification,
} from "maplibre-gl";

import { requireSourceLayer } from "./sourceLayers";
import type { PublishedArchive } from "./tileAddress";

/** The one source id, keyed off by every layer below. Distinct from Earth's `countries` because a
 *  globe draws one body and the two ids never coexist — the separation is for the reader. */
export const FEATURES_SOURCE = "features";

/** The hovered feature's hairline, and the dark separator that carries it.
 *
 *  JUDGED ON THE GLOBE, against rust ground and against the north cap's ice. Gold — Earth's accent —
 *  is mud here, and Mars's own warm accents are worse; a cool near-white is the one that reads on
 *  both. The pairing is load-bearing rather than decorative: over bright ice the pale line vanishes
 *  entirely on its own, and it is the CASING'S OPACITY, not the line's width, that rescues it. That
 *  is why the ink stays thin. */
export const HIGHLIGHT_INK = "#dfe8ef";
export const HIGHLIGHT_CASING = "#141a20";

/** True only while this feature is the one under the pointer (its feature-state `hover`). */
const whenHovered: ExpressionSpecification = ["boolean", ["feature-state", "hover"], false];

/** The hairline's width ramp, judged on screen. Thin on purpose — at the weight legibility alone
 *  would suggest, the outline competes with the crater rims it sits among and reads as cartoon. */
const INK_WIDTH: ExpressionSpecification = [
  "interpolate", ["linear"], ["zoom"], 0.5, 1.3, 4, 2.0, 8, 2.5,
];

/** The casing's ramp. Wider than the ink at every stop, so the dark reads as a separator under the
 *  line rather than as a second line beside it. */
const CASING_WIDTH: ExpressionSpecification = [
  "interpolate", ["linear"], ["zoom"], 0.5, 2.9, 4, 4.1, 8, 5.1,
];

/** How wide a linear feature's invisible hit stroke is. The stroke's own width IS the pointing
 *  tolerance, exactly as the radius is on Earth's hit circles — a vallis at its true width is a
 *  hairline nobody can put a cursor on, let alone a fingertip. */
const LINEAR_HIT_WIDTH: ExpressionSpecification = [
  "interpolate", ["linear"], ["zoom"], 0.5, 14, 4, 18, 8, 22,
];

/**
 * Mars's feature source.
 *
 * TAKES THE ARCHIVE RATHER THAN READING CONSTANTS, which is the thing Earth's equivalent still owes.
 * `countryTilesSource` reads `COUNTRIES_MIN_ZOOM/MAX_ZOOM` — Earth's numbers, correct only because
 * Earth was the only body cutting vectors — and its own docstring records that the way in is to
 * thread the archive instead of a slug, so a test can hand it a range that belongs to nobody.
 *
 * `promoteId` IS WHAT LETS ONE WRITE LIGHT A WHOLE FEATURE. Feature state is keyed on
 * (source, sourceLayer, id), and without a promoted id a vector feature has none that survives
 * being split across tiles. It is a bare string rather than the per-source-layer object form, so it
 * applies to every layer in the archive — which is required, because a hovered feature's ring and
 * its fill live in different source-layers.
 *
 * A NAME IS NOT GUARANTEED UNIQUE in the gazetteer, so one hover can light more than one feature.
 * That is the same behaviour Earth has for a country arriving as several polygons, and it is
 * accepted rather than worked around. What the identity DOES require is that every feature has a
 * name at all, and the cutter enforces that at build time — a feature without one never reaches a
 * tile, so there is no state where `promoteId` resolves to nothing.
 */
export function featureTilesSource(
  tileUrlTemplate: string,
  archive: PublishedArchive,
): VectorSourceSpecification {
  return {
    type: "vector",
    tiles: [tileUrlTemplate],
    minzoom: archive.minZoom,
    maxzoom: archive.maxZoom,
    promoteId: "name",
  };
}

/** What `map.setFeatureState` needs to address one layer's features: MapLibre's own key spelling,
 *  which is `sourceLayer` here and `source-layer` in a layer spec.
 *
 *  NAMED FOR HOVER RATHER THAN FOR FEATURE STATE, unlike countryHighlight.ts's equivalent, because
 *  on this body "feature" is already taken — it is the gazetteer's word for a crater or a vallis,
 *  not MapLibre's word for a row in a tile. Two meanings of one word in one component is how a
 *  reader ends up at the wrong module. */
export interface HoverStateTarget {
  source: string;
  sourceLayer: string;
}

/**
 * Everywhere the hover flag has to be written for one feature to light whole.
 *
 * Feature state is keyed on (source, sourceLayer, id), so a shared source id is NOT enough — each
 * source-layer that carries hover paint needs its own write. The fill is absent deliberately: it
 * carries no hover paint, and writing state to a layer that cannot show it only widens the surface
 * for the mistake this list exists to prevent.
 */
export function hoverStateTargets(): HoverStateTarget[] {
  return [
    { source: FEATURES_SOURCE, sourceLayer: requireSourceLayer("mars", "outline") },
    { source: FEATURES_SOURCE, sourceLayer: requireSourceLayer("mars", "line") },
  ];
}

/**
 * Every named region, invisible.
 *
 * A FILL over the polygon source, which is safe against a clipped tile edge for the reason
 * countryHighlight.ts records: fills never stroke the cut, so an outline needs its own line layer
 * rather than a stroke on this one.
 *
 * `fill-opacity: 0` is a LITERAL rather than a hover expression, and stays one: this layer is a hit
 * surface, not paint. `queryRenderedFeatures` reads an opacity-0 fill, which is how the pointer
 * resolves a polygon feature at all.
 */
export function featureFillLayer(): FillLayerSpecification {
  return {
    id: "feature-fill",
    type: "fill",
    source: FEATURES_SOURCE,
    "source-layer": requireSourceLayer("mars", "fill"),
    paint: {
      "fill-color": HIGHLIGHT_INK,
      "fill-opacity": 0,
    },
  };
}

/**
 * The pointing target for features that exist ONLY as lines.
 *
 * The valles, rupes and fossae in `feature_line` carry no polygon anywhere in the archive, so the
 * fill above cannot answer for them and without this they are unreachable at every zoom — not hard
 * to hit, impossible. Invisible for the same reason Earth's hit circles are: it exists to be
 * queried, never seen.
 */
export function featureLinearHitLayer(): LineLayerSpecification {
  return {
    id: "feature-linear-hit",
    type: "line",
    source: FEATURES_SOURCE,
    "source-layer": requireSourceLayer("mars", "line"),
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": HIGHLIGHT_INK,
      "line-width": LINEAR_HIT_WIDTH,
      "line-opacity": 0,
    },
  };
}

/**
 * The hovered feature's linework — casing first so the caller preserves under/over order.
 *
 * Four layers for two kinds of geometry. The ring pair strokes `feature_outline` rather than the
 * polygon, which is the stray-meridian fix countryHighlight.ts records: clipping a line trims it,
 * clipping a polygon closes the ring along the cut and a `line` layer would stroke that phantom
 * edge. The axis pair strokes `feature_line`, whose features have no ring to trace.
 *
 * Every one of them is transparent until its feature's `hover` state is set, so this returns paint
 * that draws nothing at all until the pointer picks something — see featureTargeting.ts for what
 * "picks" means when the catalogue mixes scales.
 *
 * WRITTEN OUT FOUR TIMES RATHER THAN MAPPED OVER A TABLE, and the repetition is load-bearing.
 * `paintedLayers.test.ts` reads this source for `id`/`type` pairs, so a spec assembled in a
 * `.map()` callback is a layer the consent ledger cannot see — which is exactly the state that let
 * an unratified overlay ship in the first place. The table version of this function was written,
 * and the guard caught it.
 */
export function featureHighlightLayers(): LineLayerSpecification[] {
  const ring = requireSourceLayer("mars", "outline");
  const axis = requireSourceLayer("mars", "line");
  return [
    {
      id: "feature-hl-casing",
      type: "line",
      source: FEATURES_SOURCE,
      "source-layer": ring,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": HIGHLIGHT_CASING,
        "line-width": CASING_WIDTH,
        "line-blur": 1.2,
        "line-opacity": ["case", whenHovered, 0.92, 0],
      },
    },
    {
      id: "feature-hl-line",
      type: "line",
      source: FEATURES_SOURCE,
      "source-layer": ring,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": HIGHLIGHT_INK,
        "line-width": INK_WIDTH,
        "line-blur": 0.4,
        "line-opacity": ["case", whenHovered, 1, 0],
      },
    },
    {
      id: "feature-linear-hl-casing",
      type: "line",
      source: FEATURES_SOURCE,
      "source-layer": axis,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": HIGHLIGHT_CASING,
        "line-width": CASING_WIDTH,
        "line-blur": 1.2,
        "line-opacity": ["case", whenHovered, 0.92, 0],
      },
    },
    {
      id: "feature-linear-hl-line",
      type: "line",
      source: FEATURES_SOURCE,
      "source-layer": axis,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": HIGHLIGHT_INK,
        "line-width": INK_WIDTH,
        "line-blur": 0.4,
        "line-opacity": ["case", whenHovered, 1, 0],
      },
    },
  ];
}
