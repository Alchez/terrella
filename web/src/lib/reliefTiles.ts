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

/** Zoom range of EARTH's packaged pyramid.
 *
 *  NOT THE GENERAL ANSWER, AND THE SECOND BODY IS WHY. The per-planet answer lives in
 *  `PUBLISHED[body].relief` in tileAddress.ts, because a ceiling follows each body's own source
 *  data. Two callers are left, and both are asking an Earth-only question: the legacy path below,
 *  where an untokened URL is Earth's by definition, and Earth's own registry entry, which these are
 *  the values of. Nothing that has a body in hand reads them — a source spec asks `archiveFor`, and
 *  both servers check each archive's own header against the registry, which is what stops that copy
 *  drifting.
 *
 *  NEITHER NUMBER IS DECIDED HERE. Both restate `pipeline/bodies.py`, which cuts the pyramid, and
 *  `tests/test_bodies.py` reads this file to hold the two together — so a re-cut that moves the
 *  ceiling fails there rather than 404ing a zoom the browser still asks for. Do not restate either
 *  value in prose anywhere: six comments across five modules did, and every one of them was still
 *  claiming the pre-re-cut number long after it changed. */
export const RELIEF_MIN_ZOOM = 0;
export const RELIEF_MAX_ZOOM = 8;

/** Max zoom of the pinned base source that floors the globe.
 *
 *  It must be **0**, and that is a guarantee rather than a preference — the arithmetic behind it is
 *  in reliefSources.ts, beside the source this is the ceiling of. It lives here rather than there
 *  because it is a fact about the relief pyramid and not about MapLibre, and because it is the one
 *  number in that spec which is deliberately NOT the body's. */
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

