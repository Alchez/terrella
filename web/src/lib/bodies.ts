// The single home for what differs between one planet and the next, browser-side.
//
// The pipeline has `pipeline/bodies.py` for the same job: one module states the facts, a test
// refuses to let a second copy grow, and every consumer derives. This is that module's counterpart
// for the things only the browser knows about — how a body is spelled in a URL, and how the chrome
// around it is coloured.
//
// WHY A RECORD OVER A UNION, AND WHY NO OPTIONAL FIELDS. `Record<BodySlug, BodyDescriptor>` makes
// adding a planet a COMPILE error until it answers every question, and adding a field a compile
// error at every planet already in the record. An optional field, or an index signature, turns both
// of those into silent inheritance: the new body takes Earth's answer and the diff that added the
// field looks complete. That is the same rule the Python registry states as "no field may carry a
// default", enforced here by the type system instead of by a test.
//
// The accent is the only colour here today because it is the only one the CHROME uses. Colours the
// map itself draws with live in `palette.ts`, which restates the pipeline's own ramp stops and is
// pinned against them; a body's map palette will join this descriptor when the caller that needs it
// does.

import { DEEP_SEA } from "./palette";

/** Every body the site knows how to draw. Widening this union is what makes the compiler ask the
 *  record below for a full descriptor. */
export type BodySlug = "earth";

/** One body's browser-side facts. Every field required — see the module note. */
export interface BodyDescriptor {
  /** URL and attribute spelling. Matches `pipeline/bodies.py`'s `Body.name`, because the same word
   *  names this body's directories, its archive keys and its route; two spellings would be two
   *  bodies to everything downstream. */
  slug: BodySlug;
  /** The chrome accent, per colour scheme.
   *
   *  DERIVED FROM THE MAP, NOT CHOSEN BESIDE IT. Earth's is the hero ramp's deep-sea teal, which is
   *  why the site reads as one piece rather than as a map inside someone else's shell. A second
   *  body's accent is therefore downstream of its palette, and is not a free choice. */
  accent: { light: string; dark: string };
  /** What the globe's `space-floor` layer is painted, i.e. what shows through where no tile has
   *  arrived yet.
   *
   *  Its job is to read as MORE OF THIS PLANET rather than as a hole to space — which is why it is
   *  a body fact and not a style constant. A gap in Earth's tiles should look like open ocean; a
   *  gap in another body's has to look like whatever that body mostly is, and Earth's abyssal teal
   *  under a missing Martian tile would read as data loss, which is exactly the impression this
   *  layer exists to prevent. */
  spaceFloor: string;
}

/** The registry. Keyed by slug, which a test pins so one body cannot acquire two spellings. */
export const BODIES: Record<BodySlug, BodyDescriptor> = {
  earth: {
    slug: "earth",
    accent: { light: "#3a6e7d", dark: "#7cb8b8" },
    // IMPORTED, never re-typed. `palette.ts` restates the pipeline's own ramp stops and is pinned
    // against them by tests/test_palette.py; a hex copied to here instead would be a third copy
    // with nothing comparing it back to the sea it is meant to match.
    spaceFloor: DEEP_SEA,
  },
};

/** Look a body up by slug, or throw.
 *
 *  NO FALLBACK, deliberately, for the reason the Python registry gives: a page that quietly borrows
 *  Earth's identity because a slug was misspelled renders completely and is wrong throughout. The
 *  argument is typed, so this only fires on a value that came from outside the type system — a URL
 *  segment, a stored preference, an attribute read back off the DOM.
 */
export function bodyFor(slug: string): BodyDescriptor {
  const body = (BODIES as Record<string, BodyDescriptor | undefined>)[slug];
  if (!body) {
    throw new Error(`unknown body ${JSON.stringify(slug)}; known bodies are: ${Object.keys(BODIES).join(", ")}`);
  }
  return body;
}

// `currentBody()` lives in ./currentBody.ts, and NOT here. This file is imported — for `BodySlug`
// — by tileAddress.ts, which the tile Worker compiles under a runtime that has no DOM, so a single
// `document` reference here fails that program. See that module's header for why adding `DOM` to
// the Worker's lib is not the way out.
