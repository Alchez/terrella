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
