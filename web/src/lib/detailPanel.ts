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
  /** Where "open full-size" points, or absent when there is no page to open. */
  link: string | null;
}

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
 * Mars's builder: one gazetteer row becomes one card.
 *
 * TAKES THE INDEX ROW RATHER THAN THE PICKED TILE FEATURE, and that is not a preference. The click
 * path has to consult the index anyway — a tile carries no centre, so there is nothing to fly to
 * without it (see `featureIndex.featureNamed`) — and the search box has no picked feature at all.
 * One builder over one source is what keeps the card a visitor searched to and the card they tapped
 * from being two slightly different cards.
 *
 * `figure` IS ALWAYS NULL AND `link` ALWAYS NULL, because this body has neither. Mars renders no
 * heroes — the resolution floor rules them out for every feature small enough to be a destination —
 * and there is no per-feature page to open. Both are the panel's own absent cases rather than
 * anything special here.
 */
export function featurePanelContent(feature: NamedFeature): PanelContent {
  const type = featureTypeLabel(feature.type);
  return {
    eyebrow:
      feature.diameterKm === null
        ? type
        : `${type} · ${formatFeatureDiameter(feature.diameterKm)}`,
    name: feature.name,
    // The IAU's etymology, published as a finished sentence — "Town in Mexico.", "Konstantin
    // Iosifovich; Russian cosmophysicist (1918–1993)." It is the whole content of the card, which
    // is why `features_geojson` carries it into the tiles too rather than making it a second fetch.
    note: feature.origin,
    figure: null,
    link: null,
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
    link: `/${slug}/`,
  };
}
