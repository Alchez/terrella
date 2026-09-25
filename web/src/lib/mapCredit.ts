/**
 * The globe's on-map credit, handed to MapLibre as the relief source's `attribution`: an ⓘ linking
 * to /about, which carries the notices the sources' licences require.
 *
 * The glyph is painted by `globe.css` onto the empty span, never carried here as an SVG or a `data:`
 * image. MapLibre passes attribution through an allow-list that has no `svg` and refuses `data:`
 * URLs, so either leaves the link rendering empty with no error.
 */
export const CREDITS =
  '<a href="/about/" title="Data sources" aria-label="Data sources">' +
  '<span class="credit-glyph" aria-hidden="true"></span>' +
  "</a>";
