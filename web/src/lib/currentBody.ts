// Which body THIS page draws, read off the DOM. One function, in its own file, and the reason is
// the runtime boundary rather than tidiness.
//
// `bodies.ts` is the registry: slugs, accents, the space floor. `tileAddress.ts` imports `BodySlug`
// from it, and the tile Worker imports `tileAddress.ts` — so the registry is compiled by a runtime
// with no DOM at all, under `@cloudflare/workers-types`. A single `document` reference anywhere in
// that file therefore fails the Worker's own type-check, and adding `DOM` to its lib is not the
// escape: DOM's `CacheStorage` has no `default`, which is the Cloudflare-specific property the
// Worker's cache path is built on. Measured, both ways.
//
// So the DOM reader lives here, where only the browser ever imports it, and the registry stays
// something every runtime can read.

import { type BodyDescriptor, bodyFor } from "./bodies";

/** The body THIS page draws, read off the attribute the layout declared.
 *
 *  `data-body` is already load-bearing for the stylesheet — it selects the token block that carries
 *  the accent — so reading it here does not invent a second channel: it makes one declaration serve
 *  both the CSS and the script, which is the point of putting it on `<html>` rather than in a
 *  `define:vars` the styles could not see.
 *
 *  THROWS RATHER THAN ASSUMING EARTH. The attribute is server-rendered by a layout every page goes
 *  through and `astro check` refuses a page that omits it, so reaching the throw means the invariant
 *  is already broken — and a globe that drew the wrong planet's sea colour under its missing tiles,
 *  or asked for the wrong planet's pyramid, would look like slow loading rather than like a bug.
 */
export function currentBody(): BodyDescriptor {
  const slug = document.documentElement.dataset.body;
  if (slug === undefined) {
    throw new Error(
      "<html> carries no data-body: the page's layout must declare which body it draws",
    );
  }
  return bodyFor(slug);
}
