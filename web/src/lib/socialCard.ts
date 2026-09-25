/** The link-preview card's own facts, in a module that imports nothing.
 *
 *  Separate from `assetBase.ts`, which composes the URL, because the deploy preflight runs under
 *  plain node rather than Vite: node's ESM resolver needs every specifier spelled with its
 *  extension, and `assetBase.ts` reaches two modules that are not. A leaf is what both a bundler
 *  and node can load.
 */

/** The card's file name, under `SOCIAL_BASE` for the page and `SOCIAL_PREFIX` in the bucket.
 *
 *  A replacement card takes a new name rather than overwriting this one: a platform caches a card
 *  the first time a link is shared, and several never fetch that URL again. */
export const SOCIAL_CARD_FILE = "earth-1.jpg";

/** The card's real pixel size, declared to a scraper that lays out before the bytes arrive. */
export const SOCIAL_CARD_WIDTH = 1200;
export const SOCIAL_CARD_HEIGHT = 630;
