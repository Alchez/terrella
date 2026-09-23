/**
 * The tectonic plate boundary overlay: one GeoJSON drawn as one line.
 *
 * Shaped like the border overlay rather than the vector pyramid. It is a plain GeoJSON fetched from
 * `BORDERS_BASE`, which serves a directory rather than one file, so this needs no archive, no
 * source-layer and no Worker.
 *
 * Nothing here filters. The one attribute styled on is `level`, fading minor boundaries in on zoom
 * through opacity, and a value it does not know draws as major rather than vanishing.
 * `pipeline/compose/tectonics_geojson.py` is where both vocabularies are checked and where
 * `inferred` segments are dropped, so the served file holds only observed boundaries.
 *
 * The overlay is off by default and reached through the view bar. There is no URL flag beside it:
 * one was carried while the layer had no control, and a second way to answer "is this on" is the
 * thing that would let the button and the map disagree.
 */

import type {
  ExpressionSpecification,
  GeoJSONSourceSpecification,
  LineLayerSpecification,
} from "maplibre-gl";

import { BORDERS_BASE } from "./assetBase";

/** The one source id, keyed off by both layers below. */
export const TECTONICS_SOURCE = "tectonics";

/** The file the browser fetches, beside the border overlay in the same served directory. */
export const TECTONICS_FILE = "tectonic_boundaries.geojson";

/**
 * The ink and the dark rim under it.
 *
 * Both are dark and the ink is the narrower at every zoom, so the stroke reads as one dark thread
 * with a warm core. The border overlay is white ink over `CASING_INK`, which is what keeps the two
 * apart with no colour spent on the job. Neither may be the hover gold `#eca834`.
 */
export const TECTONIC_INK = "#4c1300";
export const CASING_INK = "#2b2118";

/** Narrower than the border ink at every stop. */
const INK_WIDTH: ExpressionSpecification = [
  "interpolate", ["linear"], ["zoom"], 1, 0.5, 4, 0.9, 8, 1.5,
];

/** Narrower than the border casing at every stop, and wider than the ink above it. */
const CASING_WIDTH: ExpressionSpecification = [
  "interpolate", ["linear"], ["zoom"], 1, 1.9, 4, 2.9, 8, 4.3,
];

/** The source's `level` for a minor boundary; `pipeline/compose/tectonics_geojson.py` owns the
 *  vocabulary and a test there holds this equal to it. */
export const MINOR_LEVEL = 2;

/** Minor boundaries are hidden at or below the first zoom and drawn as major ones from the second. */
export const MINOR_FADE_START_ZOOM = 2;
export const MINOR_FADE_END_ZOOM = 3.5;

/**
 * A layer's opacity: `full` for a major boundary at every zoom, and for a minor one faded in
 * between the two stops. Any `level` other than the minor one draws as major, so a respelt
 * attribute shows more lines rather than fewer.
 */
function levelOpacity(full: number): ExpressionSpecification {
  return [
    "interpolate", ["linear"], ["zoom"],
    MINOR_FADE_START_ZOOM, ["case", ["==", ["get", "level"], MINOR_LEVEL], 0, full],
    MINOR_FADE_END_ZOOM, full,
  ];
}

/** Every layer this adds, in the order it adds them. The visibility setter walks this, so a spec
 *  that is not named here is a layer nothing can hide. */
export const TECTONIC_LAYERS = ["tectonic-casing", "tectonic-ink"] as const;

/** The localStorage key. Same string as the event, deliberately: one name for one concept. */
export const TECTONICS_KEY = "rg:tectonics";

/**
 * The document event the layout broadcasts on a change.
 *
 * Declared here rather than at each end, on `highlightPreference.ts`'s reasoning and not on the
 * border toggle's, which spells `"rg:borders"` once in the layout and again in the globe with
 * nothing holding the two equal.
 */
export const TECTONICS_EVENT = "rg:tectonics";

/**
 * Off for a visitor who has never pressed the toggle, so the default globe fetches no plate
 * geometry at all.
 *
 * Takes the storage so a test can answer without touching the real one; production passes nothing.
 */
export function tectonicsOn(storage: Pick<Storage, "getItem"> = localStorage): boolean {
  return storage.getItem(TECTONICS_KEY) === "1";
}

/** The value to persist. Spelled here so the writer and {@link tectonicsOn} cannot drift over
 *  which string means on. */
export function tectonicsStorageValue(on: boolean): string {
  return on ? "1" : "0";
}

/**
 * The source spec.
 *
 * No `attribution` key, and that is load-bearing rather than an omission. MapLibre concatenates
 * every source's attribution with " | ", so a string here would make the on-map credit change width
 * as this layer is toggled, on a row that shares space with the centred view bar. The credit
 * belongs on the About page with every other source.
 */
export function tectonicsSource(): GeoJSONSourceSpecification {
  return {
    type: "geojson",
    data: BORDERS_BASE + TECTONICS_FILE,
    maxzoom: 8,
    tolerance: 0.375,
    buffer: 256,
  };
}

/**
 * The two layers, casing first so the caller preserves under-over order.
 *
 * Written out twice rather than mapped over a table, and the repetition is load-bearing: the
 * consent ledger is checked by reading this file for literal `id` and `type` pairs, so a spec
 * assembled in a callback is a layer that ledger cannot see.
 */
export function tectonicLayers(): LineLayerSpecification[] {
  const layout: LineLayerSpecification["layout"] = {
    "line-cap": "round",
    "line-join": "round",
  };
  return [
    {
      id: "tectonic-casing",
      type: "line",
      source: TECTONICS_SOURCE,
      layout: { ...layout },
      paint: {
        "line-color": CASING_INK,
        "line-width": CASING_WIDTH,
        "line-blur": 0.4,
        "line-opacity": levelOpacity(0.85),
      },
    },
    {
      id: "tectonic-ink",
      type: "line",
      source: TECTONICS_SOURCE,
      layout: { ...layout },
      paint: {
        "line-color": TECTONIC_INK,
        "line-width": INK_WIDTH,
        "line-opacity": levelOpacity(1),
      },
    },
  ];
}
