// The relief tile contract — the shape of a tile request, and the zoom range behind it.
//
// Deliberately dependency-free and free of `import.meta.env`, because this module is imported
// from three runtimes that share nothing else: the browser (earth.astro builds the MapLibre
// source), the Astro dev server (astro.config.ts, which is Node and evaluates before any Vite
// env exists), and eventually the tile Worker. Anything env-shaped belongs in assetBase.ts.

/** The archive's tile encoding, in the three spellings the request path needs. A PMTiles archive
 *  stores ONE encoding for every tile, so these follow `format` in the archive header — set by
 *  pipeline/tile/shade_planet.py's TILE_CUT and carried through by pack_pmtiles.
 *
 *  WebP q95, previously PNG. Changing the extension is also what retires the old
 *  cached tiles: every URL changes, so no zone purge is involved. */
export const TILE_EXTENSION = "webp";
export const TILE_CONTENT_TYPE = "image/webp";

/** Zoom range of the packaged pyramid. The source of truth is the PMTiles header; these are a
 *  copy, so that the browser can request its first tile without a round trip to learn them.
 *  assertZoomRange() below is what stops the copy drifting. */
export const RELIEF_MIN_ZOOM = 0;
export const RELIEF_MAX_ZOOM = 8;

/** Max zoom of the pinned base source that floors the globe (`relief-base` in earth.astro).
 *
 *  It must be **0**, and that is a guarantee rather than a preference. A raster source's covering
 *  set is clamped to its own maxzoom, so at 0 there is exactly one tile — the same tile at every
 *  camera, therefore always ideal, therefore always resident once fetched. Any higher value leaves
 *  the set camera-dependent: measured on production, a pinned z1 (4 tiles, 273 KB) still paints a
 *  blank frame on the first visit to a cold quadrant, and z2 likewise. Raising this trades a
 *  guarantee for sharpness, which is the opposite of what the layer is for. */
export const RELIEF_BASE_MAX_ZOOM = 0;

/** One tile address. */
export interface TileCoordinate {
  z: number;
  x: number;
  y: number;
}

/** Built from TILE_EXTENSION rather than spelled out, so the path we ASK for and the path we
 *  ACCEPT cannot drift apart across a format change. */
const TILE_PATH_PATTERN = new RegExp(
  String.raw`^\/?(\d{1,2})\/(\d{1,7})\/(\d{1,7})\.${TILE_EXTENSION}$`,
);

/** Parse `/3/4/3.webp` (leading slash optional) into a tile address, or null if the path is not
 *  a tile request at all. Rejects anything non-integer, negative, out of the pyramid's zoom
 *  range, or outside the 2^z grid — a tile server should 404 those rather than range-read a
 *  multi-GB archive on a typo'd URL. */
export function parseTilePath(pathname: string): TileCoordinate | null {
  const match = TILE_PATH_PATTERN.exec(pathname);
  if (!match) return null;
  const z = Number(match[1]);
  const x = Number(match[2]);
  const y = Number(match[3]);
  if (z < RELIEF_MIN_ZOOM || z > RELIEF_MAX_ZOOM) return null;
  const gridSize = 2 ** z;
  if (x >= gridSize || y >= gridSize) return null;
  return { z, x, y };
}

/** Describe a TILE_EXTENSION/archive disagreement, or null when they match.
 *
 *  Takes the extension rather than pmtiles' numeric `tileType` so this module stays
 *  dependency-free; both servers already hold a header and can call `tileTypeExt()` on it.
 *
 *  This one is worth a guard precisely because it does NOT announce itself: a pyramid re-cut to
 *  PNG still answers `.webp` URLs, the server still labels them `image/webp`, and browsers
 *  content-sniff the bytes and render them anyway. Everything looks correct until something in
 *  the chain trusts the label — a cache keyed on type, an image pipeline, a stricter client. */
export function describeTileTypeMismatch(archiveExtension: string): string | null {
  if (archiveExtension === `.${TILE_EXTENSION}`) return null;
  const declared = archiveExtension || "an encoding this pmtiles build cannot name";
  return (
    `PMTiles archive stores ${declared} tiles, but the globe requests .${TILE_EXTENSION} and the ` +
    `server labels them ${TILE_CONTENT_TYPE}. Update TILE_EXTENSION in src/lib/reliefTiles.ts to ` +
    `match the re-cut pyramid (its source of truth is TILE_CUT in pipeline/tile/shade_planet.py).`
  );
}

/** Fail loudly when the archive stops matching the constants above. Called by the tile server
 *  once, against the header it has already read — the whole point of duplicating the zooms
 *  into the client is that nothing in the browser can notice they went stale. */
export function assertZoomRange(archiveMinZoom: number, archiveMaxZoom: number): void {
  if (archiveMinZoom !== RELIEF_MIN_ZOOM || archiveMaxZoom !== RELIEF_MAX_ZOOM) {
    throw new Error(
      `PMTiles archive covers z${archiveMinZoom}-z${archiveMaxZoom}, but the globe requests ` +
        `z${RELIEF_MIN_ZOOM}-z${RELIEF_MAX_ZOOM}. Update RELIEF_MIN_ZOOM/RELIEF_MAX_ZOOM in ` +
        `src/lib/reliefTiles.ts to match the re-cut pyramid.`,
    );
  }
}
