import { BODIES, type BodySlug } from "./bodies";

/**
 * The two pages every body has, and the comparison that decides which of them a visitor is on.
 *
 * WHY THIS EXISTS AT ALL. Three places used to answer "where is the globe" and "where do you go
 * instead" by matching the literal `/earth`: the pre-paint tier guard, the view bar's tier picker,
 * and the redirect targets inside both. That was correct while there was one globe, and it fails in
 * a way the second body makes vivid rather than subtle — on `/mars/` the picker took its gallery
 * branch, so the chip read "Lite" under a spinning globe, and its Globe and Full buttons navigated
 * to Earth. A control that sends you to a different planet is not a routing bug you notice in a
 * test; it is one you notice by being on the page.
 *
 * ONLY ONE OF THE TWO ROUTES IS STORED, and the asymmetry is deliberate. A body's globe is the page
 * at its own slug — `bodies.browser.test.ts` already refuses a registry entry with no
 * `src/pages/<slug>.astro` behind it — so a `globeRoute` field would be that same fact written a
 * second time, free to disagree with the file system while every gate stayed green. The lite route
 * is derivable from nothing: Earth's is the gallery at `/` because the gallery was the front page
 * before there was a second body, and Mars's is a page written for the purpose because a gallery is
 * a wall of hero renders and Mars has none.
 *
 * THE PRE-PAINT GUARD CANNOT IMPORT THIS, and carries a one-line copy of `isSamePath` instead. That
 * is the same forced duplication `capable()` already lives with: the guard is `is:inline` precisely
 * so it runs before any bundle exists, so there is nothing for it to import from. What keeps the two
 * honest is not a comment but `capability.test.ts`, which EXECUTES the guard's own source and
 * asserts its verdict matches this function's over a table of path spellings.
 */

/** Where one body's two pages live. Absolute, and in the form a redirect should navigate to. */
export interface BodyRoutes {
  /** This body's globe. */
  globe: string;
  /** Where a visitor goes who cannot, or will not, run that globe. */
  lite: string;
}

/**
 * Both of a body's routes, in the spelling a redirect should use.
 *
 * Returned as a record rather than as two functions for the reason `globeSubsystems` is one: the
 * two answers are consumed together at every call site, and a caller that reaches for one field
 * directly off the descriptor and derives the other loses the only place that says how they relate.
 */
export function bodyRoutes(slug: BodySlug): BodyRoutes {
  return { globe: `/${slug}/`, lite: BODIES[slug].liteRoute };
}

/**
 * Whether two pathnames name the same page, ignoring a trailing slash.
 *
 * BOTH SPELLINGS REALLY ARRIVE. `astro.config.ts` sets no `trailingSlash`, so the default `ignore`
 * serves `/earth` and `/earth/` alike and either can be typed, linked or restored from history. An
 * `===` against one spelling is therefore a check that passes most of the time, which is the worst
 * kind: the guard would let a Lite visitor sit on a globe they cannot run, but only when they
 * reached it by the spelling nobody tests with.
 */
export function isSamePath(a: string, b: string): boolean {
  return a.replace(/\/+$/, "") === b.replace(/\/+$/, "");
}
