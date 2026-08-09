/** EARTH's country pyramid — what is inside its tiles, how deep it was cut, and its legacy URL.
 *
 *  The transport half moved to vectorTiles.ts, which is the contract every body's vector pyramid
 *  answers. What is left here is the half that is Earth's alone, and the split is what stops the
 *  next planet importing a country to reach an extension.
 *
 *  Dependency-free and free of `import.meta.env`, like its siblings, because it is imported from
 *  the browser, the Astro dev server (plain Node, before Vite env exists) and the tile Worker.
 *
 *  WHY THE GLOBE ADDRESSES COUNTRIES BY z/x/y AT ALL. Handing MapLibre a parsed FeatureCollection
 *  makes `Actor.sendAsync` deep-rebuild it in `serialize()` and then structured-clone the rebuilt
 *  copy — two full walks of 413,141 vertices, on the main thread. A URL is a worker request
 *  instead, and the worker does the fetch, the parse, the tiling and the tessellation. Measured
 *  A/B/A/B on the live globe: the session's worst long task, 358 ms, disappears entirely.
 *  pipeline/compose/countries_pmtiles.py is the source of truth for what is inside the archive.
 */

import type { TileCoordinate } from "./reliefTiles";
import { VECTOR_TILE_EXTENSION } from "./vectorTiles";

/** The path segment telling the tile server which of the three archives a request is for.
 *
 *  The extension already differs from the two raster pyramids, so unlike `terrain` this prefix is
 *  not strictly load-bearing today. It is here anyway because the alternative — relying on `.mvt`
 *  alone — makes the router's safety depend on a codec choice rather than on an address, and the
 *  codec is exactly the thing a re-cut is allowed to change. */
export const COUNTRIES_PATH_PREFIX = "countries";

export const COUNTRIES_MIN_ZOOM = 0;

/** Matches EARTH's relief ceiling, and not by coincidence: the hover outline is judged against the
 *  raster coastline at that ceiling, so the vector detail has to reach where the raster does.
 *  MapLibre overzooms past this by re-using the deepest tiles, which is correct — past the relief's
 *  own ceiling there is no more detail to disagree with.
 *
 *  EARTH'S, THOUGH THE COUPLING IT DESCRIBES IS EVERY BODY'S. The per-planet answer is
 *  `PUBLISHED[body].countries` in tileAddress.ts, and each planet's relief stops where its own
 *  source data runs out — so "matches the relief ceiling" resolves to a different number per
 *  planet, while this constant cannot.
 *
 *  It is still what `countryTilesSource` reads, and that is a deferral rather than an oversight:
 *  Earth is the only body publishing vectors, so a version taking its zooms from the registry would
 *  produce byte-identical output forever and a test for it could not fail. The way in is to thread
 *  the ARCHIVE into that function instead of a body slug — then a test can hand it a range that is
 *  nobody's, and the guard bites without waiting for a second vector pyramid to exist. */
export const COUNTRIES_MAX_ZOOM = 8;

const COUNTRIES_PATH_PATTERN = new RegExp(
  String.raw`^\/?${COUNTRIES_PATH_PREFIX}\/(\d{1,2})\/(\d{1,7})\/(\d{1,7})\.${VECTOR_TILE_EXTENSION}$`,
);

/** Parse `/countries/8/189/107.mvt` (leading slash optional) into a tile address, or null if the
 *  path is not a country tile request at all.
 *
 *  Same shape and same out-of-grid rejection as its two siblings: a typo'd URL must 404 without
 *  costing a range read against a multi-GB object. */
export function parseCountriesTilePath(pathname: string): TileCoordinate | null {
  const match = COUNTRIES_PATH_PATTERN.exec(pathname);
  if (!match) return null;
  const z = Number(match[1]);
  const x = Number(match[2]);
  const y = Number(match[3]);
  if (z < COUNTRIES_MIN_ZOOM || z > COUNTRIES_MAX_ZOOM) return null;
  const gridSize = 2 ** z;
  if (x >= gridSize || y >= gridSize) return null;
  return { z, x, y };
}

