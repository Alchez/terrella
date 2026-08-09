/** MARS's named-feature overlay — the vector source, and the one layer drawn over it.
 *
 *  The sibling of countryHighlight.ts, and deliberately not a generalisation of it. Both draw one
 *  body's vector archive, and there the resemblance stops: Earth's stack is filtered to the hero
 *  manifest, hit-tested against fat per-island circles and lit by hover feature-state, none of which
 *  Mars's archive can answer — it carries no `hit` layer and there is no manifest to filter by. What
 *  the two share is the transport (vectorTiles.ts) and the role vocabulary (sourceLayers.ts), which
 *  is exactly what those two modules were split out to hold.
 *
 *  NOTHING HERE PAINTS, AND THAT IS THE DECISION RATHER THAN A GAP. A vector pyramid is INTERACTION
 *  DATA on this globe, not first-paint content — Earth's `country-fill` has sat at opacity 0 since
 *  it was written, lighting only under the pointer. Mars was drawn permanently for one commit and it
 *  was wrong twice over: it broke that rule, and the outlines it painted traced crater rims the
 *  RELIEF ALREADY RENDERS, in shadow, better. Tracing a rim adds exactly one fact — that this one has
 *  a name — and hover and labels both say that far better than a permanent line does.
 *
 *  SO THE FILL IS THE WHOLE OVERLAY UNTIL HIT-TESTING LANDS. It is invisible and it is not dead:
 *  `queryRenderedFeatures` reads an opacity-0 fill, which is how Earth's `countryAt` resolves a
 *  country, so this is the surface a tap will land on. The hover commit turns its `fill-opacity`
 *  into the same `["case", whenHovered, …]` expression Earth uses and adds outline and line above
 *  it; the archive already carries both, because a style can always narrow and an archive cannot
 *  widen without a re-cut.
 */

import type { FillLayerSpecification, VectorSourceSpecification } from "maplibre-gl";

import { requireSourceLayer } from "./sourceLayers";
import type { PublishedArchive } from "./tileAddress";

/** The one source id, keyed off by every layer below. Distinct from Earth's `countries` because a
 *  globe draws one body and the two ids never coexist — the separation is for the reader. */
export const FEATURES_SOURCE = "features";

/**
 * Mars's feature source.
 *
 * TAKES THE ARCHIVE RATHER THAN READING CONSTANTS, which is the thing Earth's equivalent still owes.
 * `countryTilesSource` reads `COUNTRIES_MIN_ZOOM/MAX_ZOOM` — Earth's numbers, correct only because
 * Earth was the only body cutting vectors — and its own docstring records that the way in is to
 * thread the archive instead of a slug, so a test can hand it a range that belongs to nobody. Mars
 * starts there rather than inheriting the constant and needing the same repair later.
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
  };
}

/**
 * Every named region, invisible.
 *
 * A FILL over the polygon source, which is safe against a clipped tile edge for the reason
 * countryHighlight.ts records: fills never stroke the cut, so an outline needs its own line layer
 * rather than a stroke on this one.
 *
 * `fill-opacity: 0` is a LITERAL rather than Earth's hover expression, because Mars has no hover
 * writer yet and an expression reading a feature-state nothing sets would be wiring with no reader.
 * The colour is what a hover wash will use, so the hover commit changes one number.
 */
export function featureFillLayer(): FillLayerSpecification {
  return {
    id: "feature-fill",
    type: "fill",
    source: FEATURES_SOURCE,
    "source-layer": requireSourceLayer("mars", "fill"),
    paint: {
      // Mars's own ratified accent, so the wash cannot introduce a second warm brown to the page.
      "fill-color": "#8c4a32",
      "fill-opacity": 0,
    },
  };
}
