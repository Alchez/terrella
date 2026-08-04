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
 *  record below for a full descriptor — and the same of every other `Record<BodySlug, …>` in the
 *  codebase: the tile registry, the dev server's work-tree prefixes. That is the whole mechanism
 *  by which a second planet cannot be half-added. */
export type BodySlug = "earth" | "mars";

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
  /** Whether this body publishes the two azimuthal-equidistant polar caps.
   *
   *  MIRRORS `pipeline/bodies.py`'s `renders_polar_caps`, and a test holds the two together —
   *  neither registry can import the other, and they are the two halves of one fact. The pipeline
   *  decides whether to spend ~14 GB per pole rendering them; this side decides whether to fetch
   *  them. Disagree in one direction and the globe carries holes it has textures for; disagree in
   *  the other and it asks for a `caps.json` nobody wrote, which arrives as a 404 the console
   *  swallows.
   *
   *  `renders_` rather than `polarCaps`, taking the pipeline's word for the pipeline's reason: MARS
   *  HAS REAL POLAR ICE CAPS, so a field spelled `polarCaps: false` would read as a factual error
   *  about the planet rather than a statement about what we ship.
   *
   *  The cost of `false` is visible and deliberate: a cap is a PROJECTION REPAIR — Web Mercator
   *  dies at ~85° — so a body without one carries a hole at each pole. */
  rendersPolarCaps: boolean;
  /** Whether this body has political boundaries to draw over the relief.
   *
   *  NOT ANSWERABLE FROM THE TILE REGISTRY, which is why it is here. The overlay is Natural Earth
   *  `boundary_lines.geojson` fetched from `BORDERS_BASE`, a plain GeoJSON in its own store — a
   *  different product from the countries MVT pyramid that `PUBLISHED[body].countries` covers, and
   *  a body could plausibly publish either without the other.
   *
   *  It is also the only one of these three with no coherence partner: borders need no pyramid and
   *  no cap, so nothing else has to be true for this to be. That absence is stated because an
   *  unexplained gap in a rule set reads as an oversight. */
  hasBorders: boolean;
  /** Whether this body has ray-traced hero renders — the gallery's cards, the detail pages, and the
   *  in-globe panel.
   *
   *  A BODY FACT AND NOT A LOOKUP, for the reason the pipeline's optional layers had to become one:
   *  the manifest is a single global import, so "does the manifest have entries" is `true` on every
   *  body alike and would answer Earth's question for Mars. The same shape as asking the filesystem
   *  whether a dataset was downloaded.
   *
   *  Coherent only with a countries pyramid, because on the globe a panel opens exactly one way —
   *  a map click resolved through `countryAt()` against the countries MVT. Heroes without that
   *  pyramid is a subsystem nothing can reach. */
  hasHeroes: boolean;
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
    // All three true, because Earth is the reference body and every one of these subsystems was
    // built against it. Written out rather than defaulted for the reason the Python registry
    // spells its layer set out: "whatever the reference body happens to have" is how the next
    // planet inherits an answer nobody gave.
    rendersPolarCaps: true,
    hasBorders: true,
    hasHeroes: true,
  },
  // MARS: BOTH COLOURS ARE PROVISIONAL AND NEITHER IS A DECISION.
  //
  // Earth's accent is not a choice — it is the hero ramp's deep-sea teal, imported, which is why
  // the chrome reads as part of the map rather than as a shell around it. Mars has no ramp yet: its
  // palette is the deepest open question about the second body, and it gets answered by rendering
  // candidate looks on the sphere, not by picking a hex in a registry. These two hold the shape of
  // the answer so the type system stays satisfied and the route can exist; they are the FIRST thing
  // to replace once a look is ratified, and they must become imports from the Mars palette exactly
  // as Earth's are — a hand-typed hex that survives into production is the copied-look-constant
  // failure that has already cost this project an overnight re-render of every hero.
  //
  // THE THREE BOOLEANS ARE DECISIONS, NOT PLACEHOLDERS, and they differ from the colours above in
  // exactly that. Each says what Mars ships today, and each has a reason that is not "we have not
  // got to it yet".
  mars: {
    slug: "mars",
    accent: { light: "#8c4a32", dark: "#d08b6a" },
    spaceFloor: "#6b3a2a",
    // Matches `pipeline/bodies.py`'s `MARS.renders_polar_caps`, which is what actually decides it:
    // a cap's colours come from the same unratified ramps as the tiles, so a Mars cap today would
    // wear Earth's palette. The globe therefore shows a hole above ~85° at each pole, which is the
    // honest cost of a look that has not been decided.
    rendersPolarCaps: false,
    // Mars has no nations. Whatever eventually divides this planet on screen — the geologic units
    // of SIM 3292 are the candidate — is a different product from a political boundary line, so it
    // will arrive as its own layer rather than by flipping this.
    hasBorders: false,
    // No Blender pass has ever run for Mars, and whether one should is deliberately parked until a
    // look is ratified: a hero is the most expensive thing to re-render after a palette changes.
    hasHeroes: false,
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
