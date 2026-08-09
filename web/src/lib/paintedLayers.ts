/** EVERY STYLE LAYER THIS GLOBE CAN ADD, AND WHETHER IT PUTS PIXELS ON THE PLANET.
 *
 *  ── READ THIS BEFORE ADDING AN ENTRY ────────────────────────────────────────────────────────────
 *  Every layer below was seen on a globe and approved by the maintainer. Adding a layer to the code
 *  without adding it here turns `paintedLayers.test.ts` red, and that is the entire point: this file
 *  is a consent gate, not a correctness one.
 *
 *  WHY IT EXISTS, WHICH IS A FAILURE AND NOT A PRINCIPLE. Mars's named features shipped as a
 *  permanently painted fill-outline-line overlay that the maintainer had never seen. Nothing caught
 *  it, and nothing could have: the repo's guards ask "is this correct?" — the layer names were
 *  pinned across the language seam, the new guards were mutation-tested, four linters were at zero
 *  and 4,000 tests were green. Not one of them asks "did anyone agree to this?", and those two
 *  questions are orthogonal. A plan saying a layer is "drawn" is not approval to paint it.
 *
 *  THIS IS A LEDGER, NOT A RENDERER. Nothing imports these entries to build a style — the specs
 *  live with the code that adds them, exactly where they were. Deriving the style from here would
 *  make the ledger agree with the code by construction, which is the one thing it must not do.
 */

import type { BodySlug } from "./bodies";

/** When a layer's pixels reach the screen.
 *
 *  The distinction that matters is not visible/invisible but WHOSE CHOICE it is — a wash that only
 *  appears under the pointer is a different thing to consent to than one always on the planet. */
export type PaintTiming =
  /** On the planet from first paint, for every visitor who gets this layer at all. */
  | "always"
  /** Only under the pointer, via feature-state. Invisible until the visitor points at something. */
  | "on-hover"
  /** Only when the visitor switches it on, and off by default. */
  | "opt-in"
  /** Never. A hit or hover surface, held at a literal zero opacity — which the test enforces, so
   *  this value cannot quietly become a lie. */
  | "never";

export interface RatifiedLayer {
  /** The layer id as MapLibre sees it. */
  id: string;
  /** Which bodies can add it. `"all"` where every planet gets it. */
  bodies: BodySlug[] | "all";
  timing: PaintTiming;
  /** What it looks like, in one line — enough that a reader can tell whether the thing on screen is
   *  the thing that was approved. Not a description of the code; a description of the pixels. */
  looks: string;
}

/** The ledger. Ordered by what a visitor meets first, not alphabetically. */
export const RATIFIED_LAYERS: RatifiedLayer[] = [
  {
    id: "space-floor",
    bodies: "all",
    timing: "always",
    looks: "flat space colour behind the planet, per body — never seen except as the gap around it",
  },
  {
    id: "relief-base",
    bodies: "all",
    timing: "always",
    looks: "the z0 tile stretched under everything, so a slow fill reads as the planet's own colour",
  },
  { id: "relief", bodies: "all", timing: "always", looks: "the shaded relief raster — the planet" },
  {
    id: "polar-cap-north",
    bodies: "all",
    timing: "always",
    looks: "azimuthal cap repairing Mercator above ~85°; Earth's snow white, Mars's two ice whites",
  },
  {
    id: "polar-cap-south",
    bodies: "all",
    timing: "always",
    looks: "the same repair at the other pole, in that body's southern white",
  },
  {
    id: "b-casing-solid",
    bodies: ["earth"],
    timing: "opt-in",
    looks: "dark casing under the white border line, so the border reads over sand and sea alike",
  },
  {
    id: "b-casing-dashed",
    bodies: ["earth"],
    timing: "opt-in",
    looks: "the same casing on disputed segments, dashed",
  },
  { id: "b-ink-solid", bodies: ["earth"], timing: "opt-in", looks: "the white border line itself" },
  {
    id: "b-ink-dashed",
    bodies: ["earth"],
    timing: "opt-in",
    looks: "the white border line on disputed segments, dashed — the worldview note on About",
  },
  {
    id: "country-fill",
    bodies: ["earth"],
    timing: "on-hover",
    looks: "warm gold silhouette wash at 0.16 over the whole hovered country",
  },
  {
    id: "country-hl-casing",
    bodies: ["earth"],
    timing: "on-hover",
    looks: "soft dark casing under the gold outline of the hovered country",
  },
  {
    id: "country-hl-line",
    bodies: ["earth"],
    timing: "on-hover",
    looks: "gold line tracing the hovered country's coast and borders",
  },
  {
    id: "country-hit",
    bodies: ["earth"],
    timing: "never",
    looks: "nothing — fat invisible circles per island, so an atoll nation is pointable at",
  },
  {
    id: "feature-fill",
    bodies: ["mars"],
    timing: "never",
    looks:
      "nothing. Mars's named features are INTERACTION DATA, not paint: this was permanently drawn "
      + "for one commit and reverted, because the outlines traced crater rims the relief already "
      + "renders in shadow, better. It is the surface a tap will land on once hit-testing exists",
  },
];

/** Ids only, for the set comparisons the test makes. */
export function ratifiedLayerIds(): Set<string> {
  return new Set(RATIFIED_LAYERS.map((layer) => layer.id));
}

/** The layers whose `timing` claims they put no pixels anywhere, which the test then verifies
 *  against the opacity in their actual spec. */
export function neverPaintingLayerIds(): Set<string> {
  return new Set(RATIFIED_LAYERS.filter((l) => l.timing === "never").map((l) => l.id));
}
