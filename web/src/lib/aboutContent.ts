// What the About page says about each planet, as data rather than as markup.
//
// WHY A MODULE AND NOT A PAGE. `about.astro` used to carry all of this inline, and the page was
// already the wrong shape for it: the credits were grouped by body while the pipeline story, the
// lede and the notes were Earth's with no notion that a second planet existed. A third body should
// be a declaration here, not an editing job in a template.
//
// KEYED BY `BodySlug`, WHICH IS THE WHOLE GUARD. `Record<BodySlug, BodyAbout>` makes adding a
// planet a compile error until it answers every field, exactly as `bodies.ts` does for the chrome.
// `aboutCredits.test.ts` then reads this module rather than scraping the page's source, so the rule
// "every body the site ships has credits" is checked against structured data instead of a regex.
//
// EVERY PLANET TAKES ONLY THE SPACE IT NEEDS, and the types say so without optional fields. The
// lists are required and may be EMPTY — Mars has no boundary note and Earth no smooth-poles note,
// and neither is a gap. `legend` is `| null` on `bodies.ts`'s own reasoning for `atmosphere`: null
// is a statement about a body, not a missing value, and a body drawn from something other than a
// hypsometric ramp would say so there rather than inherit a key that misdescribes it.

import { MARS_RAMP, rampGradient, type RampStop } from "./palette.ts";
import type { BodySlug } from "./bodies.ts";
// The cards and the disclaimers, generated from `pipeline/attribution.py` by
// `scripts/gen_attributions.py` and committed. A stage that stamps an archive needs these in
// Python and a card needs them here, and only one of those directions can generate: this file
// used to keep its own list, and the two had drifted in both directions at once. SCAR ADD is
// CC-BY and was on no card; NSIDC, RGI and OSI SAF were worded differently from the notices.
import CREDITS from "../data/attributions.json";

/** One numbered stage of a body's pipeline, as a visitor reads it. */
export interface AboutStep {
  title: string;
  text: string;
}

/** One dataset, its job, its licence and the credit its publisher asks for.
 *
 *  `attribution` IS QUOTED, NEVER COMPOSED, wherever a publisher states an exact form —
 *  `tests/test_attributions.py` sweeps this module for those strings and `ATTRIBUTIONS.md` for the
 *  same ones, so a reworded notice fails in both directions. A courtesy credit is deliberately not
 *  in that sweep: asserting an obligation the publisher does not state is its own kind of wrong. */
export interface AboutSource {
  name: string;
  href: string;
  role: string;
  license: string;
  attribution: string;
}

/** A caveat callout. Kept short on purpose — these explain what the map is not, and a reader who
 *  wanted the full argument is reading the wrong document. */
export interface AboutNote {
  heading: string;
  paragraphs: string[];
}

/** The elevation key beside a body's relief.
 *
 *  THE TWO BODIES' LEGENDS DIFFER IN KIND, not only in colour, which is why this carries its own
 *  labels rather than three fixed ones. Earth's ramp spans two surfaces meeting at a real hinge —
 *  the shoreline — so its marks are sea floor, coast and peak. Mars has no sea to hinge on, so its
 *  ramp is one surface across the planet's own range and its marks are elevations. */
export interface AboutLegend {
  /** A CSS `linear-gradient(...)`, left end low. */
  gradient: string;
  /** The marks under the ramp, left to right. Three on both bodies today; the array is what lets a
   *  body with a different story use a different number. */
  marks: string[];
  /** One line saying what kind of ramp this is, since the gradient alone cannot. */
  caption: string;
}

/** One body's account of itself. Every field required; the lists may be empty. */
export interface BodyAbout {
  /** The one-sentence answer to "what am I looking at". */
  lede: string;
  /** The elevation key, or `null` for a body whose relief is not drawn from a hypsometric ramp. */
  legend: AboutLegend | null;
  /** The pipeline, in order. Numbered on the page because a pipeline really is a sequence. */
  steps: AboutStep[];
  /** Every dataset this body's imagery is built from. */
  sources: AboutSource[];
  /** What this body's map is not. */
  notes: AboutNote[];
  /** Disclaimers this body's OWN data licences oblige, drawn with that body's sources.
   *
   *  BODY-SCOPED BECAUSE THE OBLIGATION IS. The Copernicus Article 6(c) liability sentence used to
   *  sit in the page's shared block, under the tools, where it read as a statement about the whole
   *  site: it is about WorldDEM-30, which only Earth is built from. Mars's publishers ask for no
   *  such notice, so its list is EMPTY rather than filled with something reworded to fit.
   *  File a line under the body whose licence asks for it. One put under the wrong planet still
   *  renders, and tells a reader that planet's data carries terms it does not. */
  legal: string[];
}

/** Earth's ramp, exactly as `global.css` has drawn it since before this module existed.
 *
 *  DECLARED RATHER THAN DERIVED, AND UNPINNED, WHICH MARS'S IS NOT. These nine stops are a
 *  hand-authored approximation spanning BOTH of Earth's ramps across the shoreline hinge, so there
 *  is no single stop list in `palette.py` to recompute them from — and this legend is ratified
 *  visible output, so deriving it now would risk changing what ships in order to tidy how it is
 *  stored. Moving it here buys the one thing worth having today: both bodies' legends come from one
 *  place, so the component that draws them has a single reader.
 *
 *  IT DID NOT GO STALE WHEN EARTH'S TILES CHANGED PRODUCER, AND THAT WAS WORTH MEASURING BEFORE
 *  ANYONE "FIXED" IT. `MARS_RAMP` did, by up to 16 DN, because it WAS a derivation of the
 *  composite's output. These stops never were: measured against every colour on either producer's
 *  land and sea ramps, the nearest match to each of the nine sits 1.5 to 60 DN away, and that is a
 *  LOWER bound because it ignores where along the ramp each stop claims to be. So the producer
 *  switch is not this legend's largest error and re-deriving it would be a look change wearing a
 *  correctness fix's clothes. It is also drawn on every country page through `Masthead`, not only
 *  on About, so changing it is a site-wide call rather than a page's. */
const EARTH_RAMP: readonly RampStop[] = [
  { at: 0.0, hex: "#2F5B68" },
  { at: 0.14, hex: "#4D8886" },
  { at: 0.25, hex: "#8BBCB7" },
  { at: 0.34, hex: "#CFE0D3" },
  { at: 0.45, hex: "#ECDFC6" },
  { at: 0.6, hex: "#DDC3A2" },
  { at: 0.74, hex: "#C49A72" },
  { at: 0.89, hex: "#96693F" },
  { at: 1.0, hex: "#F1ECE0" },
];

export const ABOUT: Record<BodySlug, BodyAbout> = {
  earth: {
    // NO COUNT OF DATASETS HERE, and that is the same rule the "Site-wide" mark is written under:
    // this said "fused from eight datasets into one seamless heightfield", which counted the CREDITS
    // and attached them to the HEIGHTFIELD. Two datasets enter it. The rest are warped on at
    // composite time and never reach the fusion master, which `look/lake_depth.py` states outright.
    lede:
      "Every country on Earth, with the land and the sea floor fused into one seamless heightfield, " +
      "so shelves and trenches read as terrain rather than as a blue background. Snow, sea ice, " +
      "lake beds and borders are drawn on top of it.",
    legend: {
      gradient: rampGradient(EARTH_RAMP),
      marks: ["Sea floor", "Coast", "Peak"],
      caption: "Two surfaces meeting at a real hinge: on Earth, the shoreline is where the colour turns.",
    },
    steps: [
      {
        title: "Fusion",
        text: "Copernicus GLO-30 land elevation is fused with GEBCO bathymetry into one seamless heightfield. The sea floor is part of the picture, so shelves and trenches read as terrain.",
      },
      // NO STEP FORKS ANY MORE, WHICH IS WHY THERE IS STILL ONE LIST. Earth ends in two surfaces,
      // the gallery's Cycles stills and the globe's tiles, and every step is shared between them:
      // one heightfield, one pair of ramps, one sun geometry, one renderer, borders never baked
      // either way. A per-step "which surface" field was rejected and should stay rejected: it
      // would exist for one body, since Mars has no heroes at all.
      //
      // KEEP THIS CARD SHORT. The grid is `align-items: stretch`, so the longest step pads all six
      // to its height; this one ran 370 characters against neighbours at 144 and cost 338px of row
      // for four lines. The temptation is that this is the most interesting step and deserves more
      // words. It is the one that can least afford them, and prose about what was REJECTED belongs
      // in a note below, which is not in the grid. The sky-view burn is hero-only and is docs/ART.md's.
      {
        title: "Light",
        text: "A low north-west sun with a fill from the opposite side. Both surfaces are ray traced in Blender's Cycles off one rig, so the globe's tiles cast the same real shadows the gallery's stills do.",
      },
      {
        title: "Colour",
        text: "One pair of ramps, keyed to elevation on land and to depth at sea, shared by both surfaces so a given height carries the same colour on the globe as in a gallery render.",
      },
      {
        title: "Borders",
        text: "Natural Earth boundaries composite on top as crisp vector lines. They are never baked into the terrain, so they stay sharp and toggle on demand.",
      },
      // WAS "a permanent snow and ice mask from ESA WorldCover", which the tiles REPLACED: class 70
      // is permanent ice only and left mid- and high-latitude ranges bare (`tile/shade.py` says so
      // where it swaps them). WorldCover still dresses the heroes, so it keeps its credit below.
      {
        title: "Snow",
        text: "Permanent snow from a MODIS persistence climatology and the Randolph glacier inventory, faded at its margins so the edges take the hillshade. Antarctica is painted white outright: the climatology saturates over the continent but leaves clustered gaps, and the glacier inventory only reaches its coastal fringe.",
      },
      {
        title: "Sea ice",
        text: "At the poles, translucent white sea ice floats over the real ocean-floor relief. It is a 1991–2020 average of how often each stretch of sea freezes, not a live snapshot.",
      },
    ],
    sources: CREDITS.bodies.earth.sources,
    notes: [
      {
        heading: "Boundaries",
        paragraphs: [
          "Borders use Natural Earth's <strong>de-facto</strong> worldview, disputed lines dashed. A cartographic default rather than a political claim: Kashmir keeps its shape whichever side you arrive from.",
          "It also produces results that look like bugs. Highlight Kazakhstan and a hole opens mid-country: the <strong>Baikonur Cosmodrome</strong>, leased to Russia.",
        ],
      },
      {
        heading: "Lake depth",
        paragraphs: [
          "Lake beds are <strong>modelled, not surveyed</strong>. All 1.43 million of GLOBathy's lakes get the same synthetic cone, which correlates about <strong>0.53</strong> against the Caspian's real soundings, and only <strong>0.8%</strong> of lakes here have a measured depth at all.",
          "Modelling them alike is deliberate: showing only surveyed lakes would draw survey funding as geology, since ~85% of them sit in the USA.",
        ],
      },
    ],
    // Article 6(c) of the WorldDEM-30 licence, quoted rather than summarised, and guarded as an
    // exact string by `tests/test_attributions.py`. It belongs to Earth because WorldDEM-30 does.
    legal: CREDITS.bodies.earth.legal,
  },

  mars: {
    lede:
      "The same pipeline pointed at another planet, drawn from altimetry rather than photographs, " +
      "at 200 metres to the pixel and lit by the same low sun. No sea, no borders, and a colour " +
      "that means height rather than what your eye would see.",
    legend: {
      gradient: rampGradient(MARS_RAMP),
      marks: ["−6,000 m", "Areoid", "+6,100 m"],
      caption:
        "One surface and no shoreline to hinge on, so the ramp spans the elevations holding 98% of the planet.",
    },
    steps: [
      {
        title: "Acquire",
        text: "The blended MOLA/HRSC elevation model, pinned to one published edition. USGS republishes mosaics in place under the same filename, so the download refuses anything whose size, date or sphere has moved.",
      },
      {
        title: "Relabel",
        text: "The grid is declared to be lon/lat rather than reprojected. That is an identity on the angles, so not one pixel is resampled and no copy of 10.6 GB is made.",
      },
      {
        title: "Light",
        text: "One low sun, ray traced in Blender's Cycles on the same rig Earth uses, so craters and canyons carry the real shadows they cast rather than an approximation of them.",
      },
      {
        title: "Colour",
        text: "An elevation ramp keyed to Mars's own range. Its hue is measured from the Viking colour mosaic; its shape is a convention, and the note below says why.",
      },
      {
        title: "Poles",
        text: "Web Mercator dies before it reaches a pole, so each cap is rendered on its own projection and dropped in. The permanent ice is the mapped cap, graded by how bright the Viking orbiters photographed it.",
      },
    ],
    sources: CREDITS.bodies.mars.sources,
    notes: [
      {
        // GUARDED BY `aboutCredits.test.ts`, which asserts the CLAIMS rather than the sentences —
        // a named albedo feature the map cannot show, and the elevation-not-appearance statement
        // with the cause behind it. Reword freely; do not remove either claim.
        heading: "Mars colour",
        paragraphs: [
          "Mars is coloured <strong>by elevation, not by appearance</strong>. Its real colour comes from wind-blown dust, which pays no attention to height. So <strong>Syrtis Major</strong> and <strong>Acidalia</strong>, the dark markings visible from Earth through a small telescope, are not here.",
          "The hue is measured from the Viking mosaic; the rise with elevation is chosen. Mars is genuinely brightest at both extremes (Hellas, its deepest basin, is a dust trap), and drawing that faithfully would make the bottom of the planet look like the top.",
        ],
      },
      {
        heading: "The smooth patch at each pole",
        paragraphs: [
          "The laser that measured Mars's heights rode an orbit that <strong>never crossed higher than about 87°</strong>. Inside that circle, <strong>96% of the map's cells never received a single measurement</strong>.",
          "So the last stretch to each pole is drawn smooth, on purpose. Earlier versions rendered the gap-filling as a <strong>starburst of ridges</strong>, an artefact of the arithmetic rather than a landscape.",
        ],
      },
      {
        heading: "The white at the poles",
        paragraphs: [
          "Mars's frost advances and retreats with the seasons, so this is <strong>not any single moment</strong>. It marks the ice that stays all year, shaded by how bright the Viking orbiters photographed each part of it. The two caps differ in colour because the ice does.",
        ],
      },
    ],
    // Empty, and that is a statement rather than a gap: every Mars source here is USGS or NASA
    // public domain, and the one with a use constraint asks for a citation, not a disclaimer.
    legal: CREDITS.bodies.mars.legal,
  },
};

/** The site-wide note on which version a visitor gets. Data rather than markup so its claims can be
 *  held against the probe and the step-down ladder that make them. */
export const TIER_NOTE: AboutNote = {
  heading: "Lite, Globe or Full",
  paragraphs: [
    "Terrella picks one of three versions when you arrive. Lite, without the globe, is for browsers that can't draw it well or have asked to save data. Globe is for devices short on memory, slow connections, and anyone who has asked for reduced motion. Everyone else gets Full, which adds raised terrain and a slow spin.",
    "If the globe struggles, it steps down on its own: first the spin stops, then the image softens, then the terrain flattens. The Lite, Globe and Full buttons override that pick, and your choice stays in this browser until you clear this site's data.",
  ],
};
