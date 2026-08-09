/** The country vector-tile contract — a `vector` source over the country pyramid.
 *
 *  Third sibling of reliefTiles.ts and terrainSource.ts, and a sibling rather than a
 *  generalisation for the same reason those two are separate: this one is MVT where they are
 *  WebP, it is legitimately SPARSE where they are complete, and its tiles carry named
 *  source-layers where a raster tile carries pixels. Folding them together would put a "which
 *  archive am I" branch in the files whose job is to have no branches.
 *
 *  Like both siblings this is dependency-free and free of `import.meta.env`, because it is
 *  imported from the browser, the Astro dev server (plain Node, before Vite env exists) and the
 *  tile Worker.
 *
 *  WHY THE GLOBE ADDRESSES COUNTRIES BY z/x/y AT ALL. Handing MapLibre a parsed FeatureCollection
 *  makes `Actor.sendAsync` deep-rebuild it in `serialize()` and then structured-clone the rebuilt
 *  copy — two full walks of 413,141 vertices, on the main thread. A URL is a worker request
 *  instead, and the worker does the fetch, the parse, the tiling and the tessellation. Measured
 *  A/B/A/B on the live globe: the session's worst long task, 358 ms, disappears entirely.
 *  pipeline/compose/countries_pmtiles.py is the source of truth for what is inside the archive.
 */

import type { TileCoordinate } from "./reliefTiles";

/** Layer names INSIDE a tile, used as MapLibre `source-layer` values.
 *
 *  Pinned on both sides — the writer is `FILL_LAYER`/`OUTLINE_LAYER`/`HIT_LAYER` in
 *  pipeline/compose/countries_pmtiles.py. A disagreement is silent: MapLibre renders a layer whose
 *  `source-layer` matches nothing as empty, with no error and no warning, so the globe would come
 *  up with no countries and nothing to say about why. */
export const COUNTRY_FILL_LAYER = "country_fill";
export const COUNTRY_OUTLINE_LAYER = "country_outline";
export const COUNTRY_HIT_LAYER = "country_hit";

/** Mapbox Vector Tile. The archive stores these gzipped, but nothing downstream sees that:
 *  `PMTiles.getZxy` decompresses against the header's `tileCompression` before returning, and
 *  both tile servers read through it. So the wire carries plain protobuf and no `Content-Encoding`
 *  is involved — which is what keeps R2's undocumented encoding passthrough out of this path. */
export const COUNTRIES_TILE_EXTENSION = "mvt";
export const COUNTRIES_CONTENT_TYPE = "application/x-protobuf";

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
  String.raw`^\/?${COUNTRIES_PATH_PREFIX}\/(\d{1,2})\/(\d{1,7})\/(\d{1,7})\.${COUNTRIES_TILE_EXTENSION}$`,
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

/** Describe a COUNTRIES_TILE_EXTENSION/archive disagreement, or null when they match.
 *
 *  The failure it catches is the router having been pointed at a RASTER archive: a WebP tile
 *  served as `application/x-protobuf` fails to parse in MapLibre's worker, and the visible result
 *  is a globe with no countries — indistinguishable from a source-layer typo, from an empty
 *  archive, and from a filter that matches nothing. */
export function describeCountriesTileTypeMismatch(archiveExtension: string): string | null {
  if (archiveExtension === `.${COUNTRIES_TILE_EXTENSION}`) return null;
  const declared = archiveExtension || "an encoding this pmtiles build cannot name";
  return (
    `Countries archive stores ${declared} tiles, but the globe requests ` +
    `.${COUNTRIES_TILE_EXTENSION}. Update COUNTRIES_TILE_EXTENSION in src/lib/countryTiles.ts to ` +
    `match the re-cut pyramid (its source of truth is pipeline/compose/countries_pmtiles.py).`
  );
}

