// What the globe's detail card shows, as data rather than as a country.
//
// THE PANEL WAS TYPED ON EARTH'S MANIFEST RECORD, which is the thing this module exists to undo.
// `openPanel(country: Country)` reached for `slug`, `continent`, `aspect`, `sizes`, `borderSizes`
// and `hasBorder` — six fields no other body has and one of which (`slug`) is a route Mars has no
// page behind. A second body could not open the card without either growing `Country` with fields
// that mean nothing on Earth, or forking the panel. `PanelContent` is the third answer: the card
// takes what it renders, and each body owns the builder that produces it.
//
// THE NOTE IS A FIELD BECAUSE IT MAKES A CLAIM ABOUT THE PICTURE. It sat in the markup as a
// sentence about a ray-traced render — true wherever a hero exists, false on a body with none, and
// invisible as a problem for exactly as long as one body had heroes. A static string cannot be
// wrong on one planet and right on another, so it stops being static.

import { HERO_BASE } from "./assetBase";
import type { SearchEntry } from "./catalogueSearch";
import type { NamedFeature } from "./featureIndex";
import type { Country } from "./manifest";

/** The hero render at the top of the card, or absent on a body that has none. */
export interface PanelFigure {
  /** width / height, used to reserve the box before the image decodes. */
  aspect: number;
  src: string;
  srcset: string;
  alt: string;
  /** The white border overlay, when this place has one rendered. `body.borders-on` decides whether
   *  it is SHOWN; this decides whether it exists at all. */
  border: { src: string; srcset: string } | null;
}

/** Everything the card renders, with no field that names a body. */
export interface PanelContent {
  /** The uppercase line above the name — a continent on Earth, a feature type elsewhere. */
  eyebrow: string;
  name: string;
  /** The sentence under the name. Describes whatever the card is actually showing. */
  note: string;
  /** Absent on a body with no renders, which is what hides the figure. */
  figure: PanelFigure | null;
  /** Where the card sends a reader next, or absent when there is nowhere to go. */
  link: PanelLink | null;
}

/**
 * The card's one outbound link, named by whoever built the card.
 *
 * THE LABEL IS A FIELD FOR THE REASON `note` IS ONE. It sat in the markup as "Open full-size
 * render →", which is a claim about where the link goes — true while the only destination was a
 * hero page, false the moment a body with no heroes points at a catalogue entry instead. A static
 * string cannot be right on one planet and wrong on another, so it stops being static.
 *
 * `external` IS DECLARED RATHER THAN SNIFFED FROM THE HREF. A builder knows whether it is sending a
 * reader off the site; a consumer testing for "http" is inferring that from a string, which is the
 * guess this repo refuses everywhere else. It decides the new tab, and a new tab is not cosmetic
 * here — leaving the page tears down a WebGL context that costs seconds and gigabytes to rebuild.
 */
export interface PanelLink {
  href: string;
  /** The link's own text, ending in the → the card's typography expects. */
  label: string;
  external: boolean;
}

/** Where a Mars card sends a reader: the IAU's entry for the feature it is describing. */
export const GAZETTEER_LINK_LABEL = "IAU Gazetteer entry →";

/** Earth's: the country's own page, with the full-size render on it. */
export const HERO_LINK_LABEL = "Open full-size render →";

/**
 * How much horizontal room the open card takes from the map, in CSS pixels.
 *
 * ONE FACT, TWO CAMERA APIs, AND THAT IS WHY IT LIVES HERE. Earth frames a country with
 * `fitBounds`, which takes PADDING and so wants this added to the frame edge; Mars flies to a
 * feature with `flyTo`, which has no padding at all and takes an OFFSET, so it wants half of this
 * as a leftward shift of the target. Both are the same sentence — "leave the card its side of the
 * screen" — and written as two literals a change to the card's width would silently correct one
 * framing and leave the other pushing its subject under the panel.
 *
 * The card itself is `min(420px, 100vw - 2.4rem)` in the stylesheet, which this deliberately does
 * not recompute: what the camera needs is clearance with a margin, not the element's exact box.
 */
export const PANEL_CLEARANCE_PX = 400;

/** Breathing room between a framed subject and the edge of the map, in CSS pixels. */
export const FRAME_EDGE_PX = 60;

/**
 * Below this viewport width the card stops being something to frame AROUND.
 *
 * It goes full-bleed there (`100vw - 2.4rem`), so there is no clear area left to aim at and a
 * camera still shifting its subject leftward would push it off the screen to make room for a panel
 * covering the screen anyway. Both bodies centre normally below this and accept the overlap.
 */
export const PANEL_BESIDE_MIN_WIDTH_PX = 640;

/** Earth's note: the card shows a render, and the render is not what the globe is drawing. */
export const COUNTRY_PANEL_NOTE =
  "A ray-traced relief render — softer shadows and heightened terrain than the globe's live tiles.";

/** The real pixel WIDTH of a variant, which is what an `srcset` w-descriptor means.
 *
 *  NOT THE LONG EDGE. A portrait variant is narrower than the number naming it, so descriptors
 *  taken from the key alone overstate every portrait hero and the browser picks a rung too small.
 *  Mirrors the gallery detail page, which is where the convention was set. */
export function variantWidth(longEdge: number, aspect: number): number {
  return Math.round(longEdge * Math.min(1, aspect));
}

/** Build one hero's `srcset` across its rendered rungs. */
export function heroSrcset(
  slug: string,
  sizes: readonly number[],
  aspect: number,
  border = false,
): string {
  return sizes
    .map((size) => {
      const suffix = border ? `-border-${size}.png` : `-${size}.webp`;
      return `${HERO_BASE}${slug}${suffix} ${variantWidth(size, aspect)}w`;
    })
    .join(", ");
}

/**
 * The IAU descriptor as one word: `"Crater, craters"` becomes `"Crater"`.
 *
 * The gazetteer publishes the singular and plural as one field, which is a dictionary headword and
 * not a label — every one of the catalogue's types carries the comma, so this is a total rule and
 * not a special case with a fallback. The plural is what the field is FOR upstream, where a type
 * heads a list; a card names one feature.
 */
export function featureTypeLabel(type: string): string {
  return type.split(",")[0]!.trim();
}

/**
 * A feature's published diameter as a card label: `"1,472 km"`, `"71 km"`, `"4.6 km"`, `"230 m"`.
 *
 * DELIBERATELY NOT `scaleRuler.formatGroundDistance`, WHICH MEASURES THE SAME UNIT. That one holds
 * two significant figures because its subject is a scale read off a sphere — true only at the point
 * sampled, and re-sampled every frame of a drag, so a third digit would be both false precision and
 * visible churn. Neither reason survives the trip here: this number is PUBLISHED, it is exact, the
 * card is quoting it rather than measuring it, and nothing about it changes while the card is open.
 * Under the ruler's rule Capri Chasma's 1,471.6 km would read "1,500 km", which is not a rounding of
 * the IAU's answer so much as a different one.
 */
export function formatFeatureDiameter(diameterKm: number): string {
  if (diameterKm < 1) return `${Math.round(diameterKm * 1000).toLocaleString("en-US")} m`;
  if (diameterKm < 10) return `${diameterKm.toFixed(1)} km`;
  return `${Math.round(diameterKm).toLocaleString("en-US")} km`;
}

/**
 * Mars's one-line summary of a feature: the kind, and the size where the gazetteer publishes one.
 *
 * ONE STRING FOR TWO PLACES — the card's eyebrow and the search row's second line. They describe the
 * same feature to the same reader moments apart, and they were two copies of this expression until
 * the row's builder moved here; the search box held the second one and reached into this module for
 * the formatters to write it, which is a duplicate that type-checks and reads correctly right up to
 * the day one side gains a unit and the other does not.
 */
export function featureSummary(feature: NamedFeature): string {
  const type = featureTypeLabel(feature.type);
  return feature.diameterKm === null
    ? type
    : `${type} · ${formatFeatureDiameter(feature.diameterKm)}`;
}

/**
 * Mars's search row: one gazetteer row becomes one `SearchEntry`.
 *
 * BESIDE THE CARD'S BUILDER BECAUSE IT IS THE SAME JOB — this module's opening note is that the card
 * takes what it renders and each body owns the builder that produces it, and a search row is that
 * sentence again one size smaller. Putting it here is also what lets the row and the eyebrow share
 * `featureSummary` rather than agreeing by hand.
 *
 * `terms` IS THE RAW GAZETTEER TYPE, NOT THE LABEL. `"Crater, craters"` is a singular/plural pair,
 * and the matcher splits it so both spellings are typeable; passing `featureTypeLabel`'s output here
 * would leave "craters" matching nothing while every other query kept working.
 */
export function featureSearchEntry(feature: NamedFeature): SearchEntry {
  return {
    name: feature.name,
    // The IAU's punctuation-flattened form, which is a DIFFERENT string from the diacritic-free one
    // — the fold already handles diacritics, so this earns its place on screen rather than in the
    // token set. `catalogueSearch`'s own note carries why that split matters.
    alias: feature.cleanName === feature.name ? null : feature.cleanName,
    descriptor: featureSummary(feature),
    terms: [feature.type],
    weight: feature.diameterKm,
  };
}

/**
 * Mars's builder: one gazetteer row becomes one card.
 *
 * TAKES THE INDEX ROW RATHER THAN THE PICKED TILE FEATURE, and that is not a preference. The click
 * path has to consult the index anyway — a tile carries no centre, so there is nothing to fly to
 * without it (see `featureIndex.featureNamed`) — and the search box has no picked feature at all.
 * One builder over one source is what keeps the card a visitor searched to and the card they tapped
 * from being two slightly different cards.
 *
 * `figure` IS ALWAYS NULL, because this body has no heroes — the resolution floor rules them out
 * for every feature small enough to be a destination. That is the panel's own absent case rather
 * than anything special here.
 *
 * THE LINK LEAVES THE SITE, WHICH EARTH'S NEVER DOES, and that is the whole reason `PanelLink`
 * carries a label and a flag instead of an href. There is no per-feature page here to open, so the
 * only thing a reader can be sent to is the IAU's own entry — and the card is already quoting that
 * entry's etymology, so the link is where the sentence it is showing came from.
 */
export function featurePanelContent(feature: NamedFeature): PanelContent {
  return {
    eyebrow: featureSummary(feature),
    name: feature.name,
    // The IAU's etymology, published as a finished sentence — "Town in Mexico.", "Konstantin
    // Iosifovich; Russian cosmophysicist (1918–1993)." It is the whole content of the card, which
    // is why `features_geojson` carries it into the tiles too rather than making it a second fetch.
    note: feature.origin,
    figure: null,
    link: { href: feature.gazetteer, label: GAZETTEER_LINK_LABEL, external: true },
  };
}

/** Earth's builder: one country becomes one card.
 *
 *  An unrendered country yields `figure: null` rather than a broken image — `sizes` is empty for
 *  those, and the old code asked for `${slug}-undefined.webp` behind a spinner. */
export function countryPanelContent(country: Country): PanelContent {
  const { slug, name, continent, aspect, sizes, borderSizes, hasBorder } = country;
  const figure: PanelFigure | null =
    sizes.length === 0
      ? null
      : {
          aspect,
          src: `${HERO_BASE}${slug}-${sizes[0]}.webp`,
          srcset: heroSrcset(slug, sizes, aspect),
          alt: `Ray-traced relief map of ${name}`,
          border:
            hasBorder && borderSizes.length
              ? {
                  src: `${HERO_BASE}${slug}-border-${borderSizes[0]}.png`,
                  srcset: heroSrcset(slug, borderSizes, aspect, true),
                }
              : null,
        };
  return {
    eyebrow: continent || "",
    name,
    note: COUNTRY_PANEL_NOTE,
    figure,
    link: { href: `/${slug}/`, label: HERO_LINK_LABEL, external: false },
  };
}
