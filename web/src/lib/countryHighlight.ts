import type { Feature, FeatureCollection } from "geojson";
import type {
  ExpressionSpecification,
  FillLayerSpecification,
  FilterSpecification,
  GeoJSONSourceSpecification,
  LineLayerSpecification,
} from "maplibre-gl";

// The country hover-highlight, factored out of globe.astro so its load-bearing wiring is
// unit-testable (see countryHighlight.test.ts). Two choices here are non-obvious and each
// fixes a globe artifact that a future edit could silently reintroduce:
//   - the outline strokes a LINE source (OUTLINE_SOURCE), never the polygon — otherwise a
//     clipped tile edge is drawn as a stray gold meridian;
//   - the `countries` polygon source sets buffer:0 — otherwise the translucent fill wash
//     double-paints in the default tile-buffer overlap, a stronger patch near the pole.

/** Source ids. Exported so the layers below AND the hover feature-state key off the same
 *  strings — a typo in either would silently break the highlight. */
export const COUNTRIES_SOURCE = "countries";
export const OUTLINE_SOURCE = "country-outlines";

/** Warm gold reads on all three grounds (teal sea, warm sand, white snow) where the teal
 *  accent would vanish along coasts; the dark casing carries it over snow. */
export const HIGHLIGHT_GOLD = "#eca834";
export const HIGHLIGHT_CASING = "#1c140c";

/** True only while this feature is the one under the pointer (its feature-state `hover`). */
const whenHovered: ExpressionSpecification = ["boolean", ["feature-state", "hover"], false];

/**
 * Each in-scope country polygon re-expressed as its boundary LINES — every ring, outer
 * coasts and inner holes alike. The hover outline strokes THESE, never the polygon:
 * clipping a line at a tile edge only trims it, whereas clipping a polygon closes the ring
 * along the cut and a `line` layer would stroke that phantom edge (the stray gold meridian).
 * Same reason the white `borders` — a line source — never show it. ADMIN is carried through
 * so feature-state hover keys the whole country as one.
 *
 * @param inScope predicate selecting the rendered (interactive) countries by ADMIN name.
 */
export function outlinesFrom(
  countries: FeatureCollection,
  inScope: (admin: string) => boolean,
): FeatureCollection {
  const features: Feature[] = [];
  for (const feature of countries.features) {
    const admin = feature.properties?.ADMIN;
    if (typeof admin !== "string" || !inScope(admin)) continue;
    const geometry = feature.geometry;
    const polygons =
      geometry.type === "MultiPolygon"
        ? geometry.coordinates
        : geometry.type === "Polygon"
          ? [geometry.coordinates]
          : [];
    const rings = polygons.flat();
    if (!rings.length) continue;
    features.push({
      type: "Feature",
      properties: { ADMIN: admin },
      geometry: { type: "MultiLineString", coordinates: rings },
    });
  }
  return { type: "FeatureCollection", features };
}

/**
 * The `countries` polygon source, feeding the fill wash and the pointer hit-test.
 * `buffer: 0` is load-bearing — see the module note above.
 */
export function countriesSource(data: FeatureCollection): GeoJSONSourceSpecification {
  return {
    type: "geojson",
    data,
    promoteId: "ADMIN", // feature id = ADMIN string, for feature-state hover
    buffer: 0,
    attribution: "Natural Earth",
  };
}

/**
 * The `country-outlines` LINE source the hover outline strokes. `data` must be the output of
 * {@link outlinesFrom}. Same ADMIN promoteId as {@link countriesSource}, so one
 * setFeatureState id drives the fill wash and this outline together.
 */
export function outlineSource(data: FeatureCollection): GeoJSONSourceSpecification {
  return { type: "geojson", data, promoteId: "ADMIN" };
}

/**
 * The warm silhouette wash over the whole hovered landmass. A FILL over the polygon source —
 * fills never stroke a clipped tile edge, so this one is safe on {@link COUNTRIES_SOURCE}.
 */
export function fillLayer(filter: FilterSpecification): FillLayerSpecification {
  return {
    id: "country-fill",
    type: "fill",
    source: COUNTRIES_SOURCE,
    filter,
    paint: {
      "fill-color": HIGHLIGHT_GOLD,
      "fill-opacity": ["case", whenHovered, 0.16, 0],
    },
  };
}

/**
 * Casing + gold line for the hovered country's boundary, added ABOVE the borders so the edge
 * stays crisp. Both stroke {@link OUTLINE_SOURCE} (a line source), never the polygon — that
 * is the stray-meridian fix. Returned casing-first so the caller preserves under/over order.
 */
export function highlightLayers(filter: FilterSpecification): LineLayerSpecification[] {
  return [
    {
      id: "country-hl-casing",
      type: "line",
      source: OUTLINE_SOURCE,
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
      source: OUTLINE_SOURCE,
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
