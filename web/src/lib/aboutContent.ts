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
 *  place, so the component that draws them has a single reader. */
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
      // THE ONE STEP THAT FORKS, WHICH IS WHY THERE IS STILL ONE LIST. Earth ends in two surfaces,
      // the gallery's Cycles stills and the globe's tiles, and everything above and below this is
      // shared between them: one heightfield, one pair of ramps, one sun geometry, borders never
      // baked either way. A per-step "which surface" field was rejected on that — it would exist
      // for one body, since Mars has no heroes at all.
      {
        title: "Light",
        text: "A low north-west sun, a fill from the opposite side, and a sky-view term for enclosed valleys, shared by both surfaces. Only the gallery's stills are ray-traced in Blender's Cycles, so only they cast real shadows.",
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
    sources: [
      {
        name: "Copernicus DEM GLO-30",
        href: "https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM",
        role: "Land elevation",
        license: "Copernicus",
        // Verbatim, not paraphrased: Article 6(b) of the WorldDEM-30 licence requires this exact
        // notice for adapted data. ATTRIBUTIONS.md is the source of truth and a test guards the pair.
        attribution:
          "produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved",
      },
      {
        name: "GEBCO 2026 Grid",
        href: "https://www.gebco.net",
        role: "Bathymetry",
        license: "Public domain",
        attribution: "Reproduced from the GEBCO_2026 Grid, GEBCO Compilation Group (2026).",
      },
      {
        name: "GLOBathy",
        href: "https://springernature.figshare.com/collections/GLOBathy_the_Global_Lakes_Bathymetry_Dataset/5243309",
        role: "Lake depth",
        license: "CC0",
        attribution:
          "GLOBathy global lakes bathymetry (Khazaei et al., Sci Data 9:36, 2022). Public-domain dedication (CC0). Depth is modelled; see the Lake depth note below.",
      },
      {
        name: "ESA WorldCover 2021",
        href: "https://esa-worldcover.org",
        role: "Snow / ice mask",
        license: "CC-BY 4.0",
        attribution:
          "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021), processed by the ESA WorldCover consortium.",
      },
      {
        name: "NSIDC-0791 Snow Persistence",
        href: "https://nsidc.org/data/nsidc-0791",
        role: "Snow persistence",
        license: "Public domain",
        attribution:
          "MODIS snow-persistence climatology (water years 2001–2023), NASA NSIDC DAAC dataset NSIDC-0791.",
      },
      {
        name: "RGI 7.0 Glaciers",
        href: "https://nsidc.org/data/nsidc-0770/versions/7",
        role: "Glaciers",
        license: "CC-BY 4.0",
        attribution:
          "Randolph Glacier Inventory 7.0 (RGI Consortium, 2023), NSIDC-0770 v7.",
      },
      {
        name: "OSI SAF Sea Ice (OSI-450-a)",
        href: "https://osi-saf.eumetsat.int/products/osi-450-a",
        role: "Sea ice",
        license: "CC-BY 4.0",
        attribution:
          "EUMETSAT Ocean and Sea Ice SAF, Global Sea Ice Concentration Climate Data Record (OSI-450-a), reduced to a 1991–2020 frequency climatology. Copyright EUMETSAT.",
      },
      {
        name: "Natural Earth",
        href: "https://www.naturalearthdata.com",
        role: "Borders & coastlines",
        license: "Public domain",
        attribution: "naturalearthdata.com.",
      },
    ],
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
    legal: [
      "The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM-30.",
    ],
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
        title: "Shade",
        text: "One low sun for relief shadows, plus a sky-view term that darkens the insides of craters and canyons the way ambient light really falls off inside them.",
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
    sources: [
      {
        name: "MOLA / HRSC Blended DEM",
        href: "https://astrogeology.usgs.gov/search/map/mars_mgs_mola_mex_hrsc_blended_dem_global_200m",
        role: "Surface elevation",
        // THE PUBLISHER'S OWN WORDS, not our reading of them. USGS states the blend's inputs as
        // "MOLA (CC0) and HRSC (CC BY-SA 3.0 IGO)" and its use constraint as "Please cite authors".
        // The share-alike half is why the whole site's output licence is BY-SA.
        license: "MOLA CC0 · HRSC CC BY-SA 3.0 IGO",
        attribution:
          "Fergason, R. L, Hare, T. M., & Laura, J. (2018). HRSC and MOLA Blended Digital Elevation Model at 200m v2. Astrogeology PDS Annex, U.S. Geological Survey. MOLA flew on NASA's Mars Global Surveyor and HRSC on ESA's Mars Express; HRSC covers 44% of the planet, MOLA the rest.",
      },
      {
        name: "Geologic Map of Mars (SIM 3292)",
        href: "https://pubs.usgs.gov/sim/3292/",
        role: "Where the permanent polar ice is",
        // THE ONE MARS SOURCE WITH A STATED OBLIGATION, and it is an exact-string one: the product's
        // own metadata reads `Use_Constraints: please cite authors.`, so the citation below is
        // quoted from its FGDC `Data_Set_Credit` field rather than composed here.
        license: "Public domain · cite authors",
        attribution:
          "K.L. Tanaka, J.A. Skinner, Jr., J.M. Dohm, R.P. Irwin, III, E.J. Kolb, C.M. Fortezzo, Thomas Platz, G.G. Michael, and T.M. Hare, 2014, Geologic Map of Mars, Scale 1:20,000,000, U.S. Geological Survey Scientific Investigations Map SIM 3292, http://pubs.usgs.gov/sim/3292",
      },
      {
        name: "Viking colour mosaic",
        href: "https://astrogeology.usgs.gov/search/map/mars_viking_colorized_global_mosaic_925m",
        role: "How bright each part of the ice is, and the planet's hue",
        // CREDITED BY COURTESY, NOT BY OBLIGATION, and the distinction is the publisher's own: its
        // constraint fields read `Access Constraints: public domain`, `Use Constraints: None`. That
        // is why this is absent from `REQUIRED_STRINGS` while SIM 3292 above is in it.
        license: "Public domain",
        attribution:
          "U.S. Geological Survey Astrogeology Science Center, Viking Global Color Mosaic 925m. Built for albedo rather than for relief, which is why the ice grades against it.",
      },
    ],
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
    legal: [],
  },
};
