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
// THE COLOURS HERE ARE THE ONES NOTHING ELSE CAN ANSWER — the chrome accent, what shows under a
// missing tile, and the air the globe is seen through. The body's own RAMP is not among them: that
// lives in `palette.ts`, which restates the pipeline's ramp stops and is pinned against them by a
// Python test, and it will join this descriptor when the caller that needs it does.
//
// A COLOUR EARNS A FIELD BY BEING WRONG ON THE NEXT PLANET, not by being a colour. Every value
// below is applied to a body's own pixels and has no derivation, so a second planet that did not
// answer would wear Earth's — silently, and looking like a rendering bug rather than a missing
// declaration. Constants that describe the RAMP rather than the body stay where they are measured;
// `skyAtmosphere.ts` names that line for the atmosphere's own knobs.

// Explicit `.ts` for the reason `devStores.ts` states: this module is reachable from a plain-node
// script, which does not resolve a bare specifier the way Vite does.
import { DEEP_SEA, MARS_MODAL_GROUND, TRENCH_FLOOR } from "./palette.ts";

/** Every body the site knows how to draw. Widening this union is what makes the compiler ask the
 *  record below for a full descriptor — and the same of every other `Record<BodySlug, …>` in the
 *  codebase: the tile registry, the dev server's work-tree prefixes. That is the whole mechanism
 *  by which a second planet cannot be half-added. */
export type BodySlug = "earth" | "mars";

/** The air a body is seen through — the three colours MapLibre's globe atmosphere composites with.
 *
 *  NOT A HALO, WHICH IS WHY THESE ARE THE BODY'S AND NOT THE PAGE'S. MapLibre ray-marches the air
 *  column from the camera and truncates the integral at the planet surface, so one uniform scales
 *  BOTH the glow at the limb and full aerial perspective over the ground. These colours therefore
 *  end up composited over this body's own pixels, at every zoom — which is exactly why a ramp
 *  judged under another planet's air is judged against the wrong surround.
 *
 *  THE RAMP'S NUMBERS ARE DELIBERATELY NOT HERE. `skyAtmosphere.ts` holds the strength, its zoom
 *  decay and its pitch term, every one of them picked off measured clipping damage on Earth's
 *  tiles. Those describe how the ramp trades glow against a bleached frame across the camera; these
 *  describe what the air LOOKS like. A second body that declares an atmosphere is the moment the
 *  numbers get a real second instance to be measured against, and that measurement is made by
 *  looking — so pre-empting it here would be inventing three numbers with nothing to check them. */
export interface BodyAtmosphere {
  /** Zenith colour, furthest from the surface. */
  sky: string;
  /** The band where the air meets the limb. */
  horizon: string;
  /** What aerial perspective lays over the ground — the one that reaches the map's own pixels, and
   *  the one that fills the hole the Mercator projection leaves at a pole with no cap. */
  fog: string;
}

/** One body's browser-side facts. Every field required — see the module note. */
export interface BodyDescriptor {
  /** URL and attribute spelling. Matches `pipeline/bodies.py`'s `Body.name`, because the same word
   *  names this body's directories, its archive keys and its route; two spellings would be two
   *  bodies to everything downstream. */
  slug: BodySlug;
  /** How this body is NAMED on screen, as distinct from how it is spelled in a URL.
   *
   *  DERIVABLE BY CAPITALISING `slug` ON BOTH BODIES THAT EXIST, and stated anyway, because the
   *  derivation lets the URL grammar decide the typography. `slug` is constrained from three
   *  directions at once — it names directories, archive keys and a route, and must match
   *  `pipeline/bodies.py`'s `Body.name` — so it is lowercase ASCII with no spaces. A display name
   *  is under none of that, and the first body whose name carries a space, a digit or a diacritic
   *  would have to choose between reading wrong on screen and renaming an archive key.
   *
   *  Which makes its guard weaker than the rest of this record's, and it says so rather than
   *  implying otherwise: `bodies.test.ts` checks the labels are non-empty and distinct — the
   *  copy-pasted row — and not that a derivation would have been wrong, which no body here can
   *  show. */
  label: string;
  /** Where a visitor goes who cannot, or will not, run this body's globe.
   *
   *  READ THROUGH `bodyRoutes()` RATHER THAN DIRECTLY — that module answers both of a body's routes
   *  in one call, and it is the globe half that explains why only this half is stored: a body's
   *  globe lives at its own slug, which `bodies.browser.test.ts` already enforces, so storing it
   *  here would be the same fact in a second place. This one is not derivable from anything. Earth's
   *  is the gallery at `/`, which existed long before there was a second body to have one; Mars has
   *  no gallery to point at, so it points at a page written for the purpose.
   *
   *  The "or else" is invisible by construction: this route is a destination for a redirect the
   *  pre-paint guard fires BEFORE the page paints, so pointing it at a path with no page behind it
   *  bounces a visitor into a 404 with nothing on screen to say what happened, and only on the
   *  devices that cannot run a globe — which are not the ones we develop on. */
  liteRoute: string;
  /** Directory segment this body's SERVED assets nest under, mirroring `pipeline/bodies.py`'s
   *  `Body.path_prefix` — which is the authority, and which a test in `tests/test_bodies.py` holds
   *  this against. Earth's is empty and collapses, keeping `/caps/caps.json` the exact URL it has
   *  always been; a second body nests one level in.
   *
   *  NOT DERIVABLE FROM THE SLUG, which is the trap. Mars's prefix and slug are the same word, so
   *  `slug` looks like it would do — and then Earth, whose prefix is deliberately empty against a
   *  slug of `earth`, is the one body it is wrong for. The asymmetry is a measured decision on the
   *  pipeline side (its un-prefixed work tree already holds ~100 GB), not something to tidy away.
   *
   *  THE "OR ELSE" IS A 200, NOT A 404, and that is why this is a registry field with a test rather
   *  than a copy beside its consumer. `devStores.ts` restates the same pipeline field for the dev
   *  server's disk paths and argues it needs no test because drift there names a directory nothing
   *  wrote, so the first request 500s with the path it looked at. Served assets invert that: a body
   *  that resolved its prefix to Earth's empty string fetches Earth's `caps.json`, gets it, and
   *  draws Earth's Arctic Ocean over another planet's pole. Successful, plausible, and silent. */
  pathPrefix: string;
  /** The sphere this body's ground distances are measured on, in metres.
   *
   *  WHAT IT IS FOR. Every reading the site gives in metres starts as an ANGLE — two lng/lat pairs
   *  the projection handed back — and an angle becomes a length only against a radius. There is
   *  exactly one such reading today, the scale ruler, and it used to take that radius from MapLibre:
   *  `LngLat.distanceTo` multiplies by a hardcoded 6371008.8 inside the shipped bundle. So the
   *  ruler reported Earth's distances on every planet, and on Mars that is 1.876x long — at every
   *  zoom, in a plausible-looking font, with nothing to compare it against.
   *
   *  THE SEAM LOOKED PARAMETERISED AND WAS NOT, which is why this field had to exist rather than
   *  being derivable. `rulerGroundDistance` already took its locator injected, so it read as
   *  body-agnostic; what it injected was WHERE THE POINTS ARE, never what a metre is worth, and the
   *  metre was pinned one layer down inside a dependency.
   *
   *  EARTH'S VALUE IS THE MEAN RADIUS, AND IT DELIBERATELY DISAGREES WITH `pipeline/bodies.py`,
   *  which carries 6378137 in a field of nearly this name. The two convert different things. The
   *  pipeline turns Mercator MAP UNITS into ground metres, and those units are defined on the
   *  projection's 6378137 sphere, so Earth's ratio there is exactly 1.0 by construction. This turns
   *  an ANGLE into an arc, where the mean radius is the right sphere — and it is also the sphere
   *  MapLibre draws the globe on, so the ruler and the geometry it is measuring agree.
   *
   *  The disagreement is Earth's alone, and only because Earth is the one body here that is not a
   *  sphere: Mars's DEM is published on a true sphere of 3,396,190 m with flattening 0, so its
   *  equatorial, mean and polar radii are one number and both registries carry it. */
  groundRadiusM: number;
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
  /** The air this body is seen through, or `null` for a body that declares none.
   *
   *  `null` IS A STATEMENT, NOT A GAP, and the distinction is the whole reason this field is
   *  nullable rather than three optional colours. A body with no atmosphere gets no `setSky` at
   *  all: no glow at the limb, no aerial perspective over the ground, the sphere read directly
   *  against the starfield. That is a declaration about the planet, and it is falsifiable — Mars
   *  answers `null` today and Earth does not, so the code path has both arms exercised.
   *
   *  MARS'S `null` IS THE PHYSICS, NOT A PLACEHOLDER. Its surface pressure is well under 1% of
   *  Earth's, so a faithful blend against Earth's tuning rounds to nothing on screen; the honest
   *  rendering of that is no atmosphere rather than a token one. If the look loop decides a wisp
   *  reads better than none, it says so by writing three colours here — which is a one-line change
   *  and a reload, not a refactor. That is what this field exists to make cheap.
   *
   *  The "or else" is what was true until this field existed: Earth's pale blue-grey haloed Mars's
   *  limb and filled the hole at each pole, on every visit, with nothing anywhere declaring it. */
  atmosphere: BodyAtmosphere | null;
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
   *  different product from the countries MVT pyramid that `PUBLISHED[body].vector` covers, and
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
    label: "Earth",
    // The gallery, under the same `/<slug>/lite/` name Mars uses, so a third body copies a row
    // rather than a special case. It renders exactly what `/` renders and says so with a canonical
    // link: the gallery is the site's FRONT PAGE first and Earth's lite fallback second, and those
    // are two jobs one URL was doing until this field separated them.
    //
    // WHICH MEANS `/` IS AN ALIAS OF THIS ROUTE, AND ONLY THE PAGE KNOWS IT. Nothing derivable
    // from this string says that the site root also serves Earth's lite content — so the pre-paint
    // guard cannot find out by comparing paths, and does not try: `Base.astro`'s `pageRole` is
    // where both pages declare it. Pointing this field at `/` instead is what used to make that
    // comparison work, and it read as the rule rather than as the coincidence it was.
    liteRoute: "/earth/lite/",
    // Empty, and it is the empty one that carries the history: `/caps/caps.json` and
    // `/caps/cap_north_8192.webp` are URLs the frontend has fetched since before there was a second
    // body, and the pipeline keeps them by giving Earth no segment at all.
    pathPrefix: "",
    // The IUGG mean radius, which is the number the readout has always used — it is MapLibre's own
    // `GLOBE_RADIUS`, in the shader that draws the sphere and in `LngLat.distanceTo` alike. Holding
    // it explicitly changes no reading and moves the constant somewhere a second body can differ.
    groundRadiusM: 6371008.8,
    // Light half is `SEA_STOPS[5]`, imported. Dark half is NOT a ramp stop — `#7cb8b8` was picked
    // by eye over `SEA_STOPS[0]` (#85b9b7).
    accent: { light: TRENCH_FLOOR, dark: "#7cb8b8" },
    // `palette.ts` restates the pipeline's own ramp stops and is pinned against them by
    // tests/test_palette.py; a hex copied to here instead would be a third copy with nothing
    // comparing it back to the sea it is meant to match.
    spaceFloor: DEEP_SEA,
    // The three colours the globe has always been drawn under, moved here unchanged. Browser-only
    // aesthetic values with no pipeline counterpart — deliberately NOT palette.ts, whose contract
    // is "colours the PIPELINE owns, restated for the browser", each pinned by a Python test that
    // recomputes it. Nothing here has such a source, so filing them there would put unguarded
    // values under a guarded banner.
    atmosphere: { sky: "#8fb8d6", horizon: "#cbd8dd", fog: "#dfe7ea" },
    // All three true, because Earth is the reference body and every one of these subsystems was
    // built against it. Written out rather than defaulted for the reason the Python registry
    // spells its layer set out: "whatever the reference body happens to have" is how the next
    // planet inherits an answer nobody gave.
    rendersPolarCaps: true,
    hasBorders: true,
    hasHeroes: true,
  },
  // MARS'S ACCENTS ARE EYE-RATIFIED AGAINST THE SHIPPED GLOBE, not ramp-derived. Deriving them from
  // ramp stops was tried, measured and reverted — the authored stops read visibly cooler than the
  // tiles, which `shade.KNOBS` resaturates and warms. Do not retry it. Earth's `accent.dark` is the
  // same shape: no ramp stop.
  //
  // THE THREE BOOLEANS ARE DECISIONS. Each says what Mars ships today, and each has a reason that
  // is not "we have not got to it yet".
  mars: {
    slug: "mars",
    label: "Mars",
    // A page written for the purpose, because the thing Earth points at does not exist here: a
    // gallery is a wall of hero renders, and Mars has none. Deliberately its own route rather than
    // Earth's `/`, which would answer "this device cannot run the Mars globe" by showing a visitor
    // a different planet.
    liteRoute: "/mars/lite/",
    // One level in, so every served asset of this body sits under `/caps/mars/…` and can never be
    // reached by a URL built for Earth. The pipeline writes them there already — this is the half
    // that has to agree, and the reason it is stated rather than derived from `slug` above.
    pathPrefix: "mars",
    // The IAU 2015 sphere the blended MOLA/HRSC DEM declares in its own CRS, and the same number
    // `pipeline/bodies.py` carries — unlike Earth's above, because this one really is a sphere.
    // `pipeline/acquire/download_mars_dem.py` refuses a source that says anything else, so the two
    // registries and the data agree or the download stops.
    groundRadiusM: 3396190,
    accent: { light: "#8c4a32", dark: "#d08b6a" },
    // Imported, unlike the accents: this answers to a rule, not an eye. The `#6b3a2a` that stood
    // here was darker than any Mars tile, so a gap read as the hole to space this layer prevents.
    spaceFloor: MARS_MODAL_GROUND,
    // NONE, AND UNLIKE THE TWO COLOURS ABOVE THIS ONE IS A DECISION. Mars's surface pressure is
    // ~0.6% of Earth's, so an atmosphere faithful to Earth's tuning is invisible at every zoom the
    // globe reaches; the honest rendering of that is no sky pass rather than a token haze. It
    // replaces something that was never declared at all — Earth's pale blue-grey haloing this
    // planet's limb. NOT the pale band at each pole, which reads as the same colour and is not:
    // deleting the sky outright left that band untouched, because it is `shade_planet.CAP_RGB`
    // baked into the tiles rather than air showing through.
    //
    // Reversible in one line if the look loop decides a wisp reads better, which is the point of
    // the field being nullable rather than the sky being skipped by a flag somewhere.
    atmosphere: null,
    // Matches `pipeline/bodies.py`'s `MARS.renders_polar_caps`, which is what actually decides it —
    // this side only says whether to FETCH what that side wrote. Held false while the ramps were
    // unratified; on now that they are.
    //
    // It buys a projection repair, not ice. Mars declares no surface layers, so the two discs are
    // the same bare relief as the tiles; what they replace is `shade_planet.CAP_RGB`, the flat pale
    // plug above 84° that MapLibre stretched across the pole.
    rendersPolarCaps: true,
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
