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

import { BODIES, type BodySlug } from "./bodies";
import { type LayerId, tilePathTemplate } from "./tileAddress";

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

/** The real pixel WIDTH of a variant, which is what an `srcset` w-descriptor means.
 *
 *  NOT THE LONG EDGE. A rung is keyed to the long edge, so a portrait hero keyed "1920" is only
 *  ~450 px wide; advertising it as `1920w` makes the browser under-select and upscale. `aspect` is
 *  width/height, so the width is the long edge for a landscape render and `longEdge * aspect` for
 *  a portrait one.
 *
 *  ONE OWNER, because this was written twice and tested once on the copy that did not ship. */
export function variantWidth(longEdge: number, aspect: number): number {
  return Math.round(longEdge * Math.min(1, aspect));
}

/** Natural Earth GeoJSON. The browser fetches ONE file from here — `boundary_lines.geojson`, the
 *  white border overlay. `countries.geojson` sits in the same store at 9.2 MB and is no longer
 *  fetched by anything: hit-testing and the highlight moved to the countries MVT pyramid, and it
 *  survives as the input that pyramid is cut from. */
export const BORDERS_BASE = resolveAssetBase(import.meta.env.PUBLIC_BORDERS_BASE, "/borders/");

/** Root of the relief tile endpoint — a tile server, not a directory listing. */
export const TILE_BASE = resolveAssetBase(import.meta.env.PUBLIC_TILE_BASE, "/tiles/");

/** A MapLibre source template — where one body's cut of one layer is addressed.
 *
 *  ALL THREE PYRAMIDS RIDE `TILE_BASE`, and none gets a `PUBLIC_` base of its own. They are not
 *  three stores: the archives sit in one R2 bucket behind one tile Worker, and the address itself
 *  is what tells that Worker which of them a request means. A `PUBLIC_TERRAIN_BASE` would let one
 *  server's halves be addressed at different hostnames — configuration for a deployment nobody
 *  intends — and would be a fourth variable for `build:deploy` to forget, which is the failure
 *  assetBase.test.ts exists to prevent: an unsupplied base does not error, it silently becomes
 *  same-origin and every URL under it 404s in production.
 *
 *  THE BODY IS A REQUIRED ARGUMENT, so this cannot be read at module scope and cannot default to
 *  Earth. That is the point: a module-level template would be one planet's address baked into a
 *  file that has no idea which page imported it, and a second body served at the first body's
 *  address does not 404 — it renders completely and is wrong throughout.
 *
 *  The path comes from the same registry both tile servers parse with, so the address the browser
 *  ASKS for and the address they ACCEPT cannot drift across a re-cut, a new layer or a new planet.
 *  The one thing this module adds is the base, which is the only env-shaped part of a tile URL. */
export function tileUrlTemplate(body: BodySlug, layer: LayerId): string {
  return `${TILE_BASE}${tilePathTemplate(body, layer)}`;
}

/** Where one body's polar-cap contract is fetched from — `caps.json`, the file the pipeline writes
 *  last beside the textures it describes.
 *
 *  NO BASE, AND THAT IS THE ONE THING THIS SHARES WITH NOTHING ABOVE. The three pyramids move to
 *  object storage on deploy because they are too big to ship; the caps are ~17 MB of WebP that ride
 *  inside the build and stay same-origin, which is why the module note lists them with the HTML and
 *  the CSS rather than with the stores. So this is a path, not a base plus a path.
 *
 *  ONLY THE MANIFEST IS ADDRESSED HERE. Every texture URL — four rungs a pole, plus the elevation
 *  texture — comes out of the manifest itself, already absolute, because the producer that wrote
 *  those files is the only thing that can say where it put them. Building a texture URL here would
 *  be this module guessing at a layout the pipeline owns.
 *
 *  THE BODY IS REQUIRED FOR THE REASON `tileUrlTemplate` STATES, only worse. A tile URL built for
 *  the wrong body 404s eventually; this one SUCCEEDS. Earth's prefix is empty, so a caller that lost
 *  the body — or a descriptor that answered `""` — resolves to `/caps/caps.json`, which exists,
 *  parses, and names Earth's Arctic textures. The globe then draws sea ice and Greenland over
 *  another planet's pole, at the right size, in the right place, feathered correctly into the
 *  tiles. There is no error anywhere in that sequence. */
export function capsManifestUrl(body: BodySlug): string {
  // Filtered so an empty prefix COLLAPSES rather than doubling the separator, which is the same
  // thing `Path / ""` does on the pipeline side and the reason Earth's URL is unchanged.
  return `/${["caps", BODIES[body].pathPrefix, "caps.json"].filter(Boolean).join("/")}`;
}
