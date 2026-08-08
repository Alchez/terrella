// The relief pyramid's two MapLibre sources, built from what the body in question publishes.
//
// FACTORED OUT OF earth.astro FOR THE REASON countryHighlight.ts WAS: a page is unit-testable by
// nobody. What made it urgent is that the zoom range in these specs is a PER-BODY fact — Earth's
// relief is cut to z8 and Mars's to z6, because a ceiling follows each body's own source data. A
// spec built from `RELIEF_MAX_ZOOM`, which is Earth's answer, makes a Mars globe ask for z7 and z8
// tiles that were never cut, and that failure is silent in the way this project keeps meeting:
// `parseTileAddress` refuses an address outside the archive's range without touching storage, so
// the browser gets a 404 and paints nothing — indistinguishable from a tile still in flight.
//
// THE BROWSER NEVER TOUCHES THE ARCHIVE. It asks a tile endpoint for z/x/y and gets one tile back;
// the multi-GB archive is opened and ranged server-side (dev: the middleware in astro.config.ts,
// prod: a Worker over R2). The earlier `pmtiles://` path did that ranging in the browser, which
// cannot survive a CDN — Workers Caching strips `Range` and would fetch the whole archive per tile.
// Dropping it also dropped the pmtiles client from the bundle entirely.
//
// So minzoom/maxzoom, which used to come free from the archive header that the pmtiles client read
// before the first tile, are stated here instead. That trades one round trip for a copy of a number,
// and the copy is held honest at the far end: both servers check every archive's own header against
// the registry these specs read, and say which file to edit when they disagree.

import type { RasterSourceSpecification } from "maplibre-gl";
import type { BodySlug } from "./bodies";
import { RELIEF_BASE_MAX_ZOOM } from "./reliefTiles";
import { archiveFor } from "./tileAddress";

/** What MapLibre is TOLD one relief tile measures, against 512px assets on disk.
 *
 *  Halving it is what serves them @2x: MapLibre chooses the zoom whose tiles are about `tileSize`
 *  CSS pixels across, so a 512px asset declared at 256 lands one level sharper than its nominal
 *  zoom. That centres the whole scheme on DPR 2, which is a choice with a cost on DPR-1 screens —
 *  → FUTURE § Raster tile resolution vs device pixel ratio. */
export const DECLARED_TILE_SIZE = 256;

/**
 * The relief source: one body's whole published pyramid, and the map itself.
 *
 * `attribution` is required here and has no counterpart on {@link reliefBaseTilesSource}, which is
 * the structural version of a rule that used to be a comment. MapLibre renders the attribution of
 * every source it draws, and both of these draw the same archive — so a credit on each would put
 * the same control on screen twice.
 */
export function reliefTilesSource(
  body: BodySlug,
  tileUrlTemplate: string,
  attribution: string,
): RasterSourceSpecification {
  const archive = archiveFor(body, "relief");
  return {
    type: "raster",
    tiles: [tileUrlTemplate],
    minzoom: archive.minZoom,
    maxzoom: archive.maxZoom,
    tileSize: DECLARED_TILE_SIZE,
    attribution,
  };
}

/**
 * The same archive capped at z0, drawn UNDER the relief source as a floor that is a map rather
 * than a colour.
 *
 * ITS CEILING IS THE ONE NUMBER HERE THAT IS NOT THE BODY'S, and that is the whole point. A raster
 * source's covering set is clamped to its own maxzoom, so at 0 there is exactly one tile at every
 * camera — always ideal, therefore always resident once fetched, therefore never missing. A z1 pin
 * (4 tiles, 273 KB) does not have that property: its covering set is still camera-dependent, and
 * measured on production a first visit to a cold quadrant painted nothing. Raising it trades a
 * guarantee for sharpness, which is the opposite of what the layer is for.
 *
 * Its FLOOR is the body's, so this stays honest for a pyramid that does not begin at z0. None does
 * today, and one that skipped z0 could not floor a globe at all — but reading the registry for it
 * costs nothing and keeps one source of truth rather than two.
 */
export function reliefBaseTilesSource(
  body: BodySlug,
  tileUrlTemplate: string,
): RasterSourceSpecification {
  const archive = archiveFor(body, "relief");
  return {
    type: "raster",
    tiles: [tileUrlTemplate],
    minzoom: archive.minZoom,
    maxzoom: RELIEF_BASE_MAX_ZOOM,
    tileSize: DECLARED_TILE_SIZE,
  };
}
