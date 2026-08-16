/** The site's name and the glyph that joins it to a page name, spelled once.
 *
 *  WHY AN OWNER FOR A FORMAT STRING. Seven pages each wrote their own `<title>` and had already
 *  drifted into three shapes, two of them putting the site name on opposite ends, so a visitor with
 *  the globe and the About page open read two conventions in one tab strip. Nothing could have
 *  caught it: a `<title>` is a string the build never validates and no rendering test looks at.
 *  `pageTitle.test.ts` now fails if a page spells the site name into a title itself.
 *
 *  THE PAGE COMES FIRST, AND THAT IS WHAT A NARROW TAB SHOWS. Tab labels truncate from the right, so
 *  site-first renders every tab as "Terrella…" and the page name is the half that gets cut — the
 *  worst case being the one that actually happens, several of this site's own tabs open at once.
 */

/** The site's name. Never write it into a `<title>`; compose with `pageTitle`. */
export const SITE_NAME = "Terrella";

/** A middot rather than a dash: the same glyph the legend marks and the licence pills already join
 *  with, so the site has one joining character instead of two that mean the same thing. */
export const TITLE_SEPARATOR = "·";

/** `pageTitle("About")` → `About · Terrella`.
 *
 *  `page` is what THIS page is and nothing more — a body's `label`, a country's name, "Gallery".
 *  A page that also names the site produces `About · Terrella · Terrella`, which is what the guard
 *  in `pageTitle.test.ts` exists to catch. */
export function pageTitle(page: string): string {
  return `${page} ${TITLE_SEPARATOR} ${SITE_NAME}`;
}
