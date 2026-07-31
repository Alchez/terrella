// Where the site's heavy assets are addressed from.
//
// The site shell — HTML, CSS, JS, the polar cap textures in public/caps — is small enough to
// ship inside the build and stays same-origin. Three stores do not: hero variants (tens of
// GB), the border GeoJSON (countries.geojson alone is 9.2 MB), and the relief pyramid (a
// 16 GB PMTiles archive). Those three move to object storage behind their own hostnames when
// the site deploys, and each gets a base URL here.
//
// Unset means same-origin, which is exactly what `astro dev` and the nginx prod-sim serve —
// so a fresh checkout needs no configuration, and the deploy is the only thing that has to
// know these hostnames exist.
//
// The tile base is the one that is not simply "a directory of files": the archive is never
// fetched by the browser. A tile server addresses it by z/x/y and answers with one tile (in
// dev, the middleware in astro.config.ts; in production, a Worker reading R2). The browser must
// never range-request the archive itself: edge caching strips the Range header and asks the origin
// for the whole multi-GB body, once per tile.

import { TILE_PATH_TEMPLATE } from "./reliefTiles";
import { TERRAIN_PATH_TEMPLATE } from "./terrainSource";

/** Normalise a configured base to a directory prefix that can be concatenated safely.
 *  An empty or whitespace-only value counts as unset — a blank line in a deploy's env
 *  should behave like no line at all, not like the site root. */
export function resolveAssetBase(configured: string | undefined, fallback: string): string {
  const trimmed = configured?.trim();
  const base = trimmed ? trimmed : fallback;
  return base.endsWith("/") ? base : `${base}/`;
}

/** Hero renders and their per-country variants: `${HERO_BASE}${slug}-${longEdge}.webp`. */
export const HERO_BASE = resolveAssetBase(import.meta.env.PUBLIC_HERO_BASE, "/heroes/");

/** Natural Earth GeoJSON: boundary_lines.geojson (border overlay) and countries.geojson
 *  (hit-testing and per-island markers). */
export const BORDERS_BASE = resolveAssetBase(import.meta.env.PUBLIC_BORDERS_BASE, "/borders/");

/** Root of the relief tile endpoint — a tile server, not a directory listing. */
export const TILE_BASE = resolveAssetBase(import.meta.env.PUBLIC_TILE_BASE, "/tiles/");

/** MapLibre raster-source template. The placeholders are MapLibre's, substituted per tile. */
export const TILE_URL_TEMPLATE = `${TILE_BASE}${TILE_PATH_TEMPLATE}`;

/** MapLibre raster-dem template for the Tier-3 elevation pyramid.
 *
 *  Derived from TILE_BASE rather than given a `PUBLIC_TERRAIN_BASE` of its own, because it is not
 *  a fourth store: both archives sit in one R2 bucket behind one tile Worker, and
 *  TERRAIN_PATH_TEMPLATE's own prefix is what tells that Worker which of the two a request is
 *  for. A separate base would let the two halves of one server be addressed at different
 *  hostnames — configuration for a deployment nobody intends. It also keeps
 *  `build:deploy` at three variables, which the assetBase test asserts against the source. */
export const TERRAIN_URL_TEMPLATE = `${TILE_BASE}${TERRAIN_PATH_TEMPLATE}`;
