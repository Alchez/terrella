// Rung selection, shared by every ladder on the site (hero variants, spotlight, border, polar caps).
//
// It lives in its OWN module rather than in manifest.ts, where it started: manifest.ts imports the
// generated `countries.json` at module scope, so importing this helper from there would drag the
// ~9.4 MB manifest into any bundle that wanted it — including the globe's polar-cap chunk, which
// exists precisely to keep first paint small.

/** The smallest rung that can fill `minimumPx` on its long edge, or the largest available when
 *  none can.
 *
 *  Exists for surfaces that no `srcset` chooses for: the country page's hero is a CSS
 *  background-image, and the polar caps are a WebGL texture. Both used to take the ladder's first
 *  entry — correct only for as long as the floor happened to be the right display size, and
 *  silently wrong the moment 640/960/1280 were added below it. A floor states the
 *  requirement instead of relying on the ladder's shape. */
export function smallestRungAtLeast(sizes: number[], minimumPx: number): number {
  const ascending = [...sizes].toSorted((first, second) => first - second);
  return ascending.find((size) => size >= minimumPx) ?? ascending[ascending.length - 1];
}
