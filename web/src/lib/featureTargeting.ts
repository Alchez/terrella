/** WHICH named feature a point picks, on a body whose catalogue mixes scales.
 *
 *  Earth needs nothing like this because countries are a PARTITION: one answer per point, every
 *  boundary a real line. Mars's gazetteer is a CATALOGUE — a 22 km crater and a 5,519 km terra are
 *  peers in one flat list, so "the smallest thing containing this point" is a giant almost
 *  everywhere, and drawing it produces a boundary with straight segments answering to nothing on
 *  screen. Measured over a grid at crater zoom, the overwhelming majority of points resolved to
 *  something over a thousand kilometres across.
 *
 *  THE RULE IS THAT A FEATURE IS A TARGET ONLY WHERE IT READS AT THE CURRENT ZOOM — big enough to
 *  aim at, small enough to fit the frame. A terra answers at overview and stops answering once you
 *  are close enough to see it is a bracket; a crater does the reverse. So whatever answers can also
 *  be drawn, and there is no class of feature that names without painting — which was the earlier
 *  proposal and the reason it was dropped: a name with no shape is not a rule a visitor can learn,
 *  it reads as a highlight that is broken on some features.
 *
 *  Over ground whose only container is too big to fit, this returns null and nothing paints. That
 *  is the same answer Earth gives over ocean, which is why it reads as a model rather than a gap.
 *
 *  Pure and dependency-free on purpose: the sizing is arithmetic over a diameter and a scale, so it
 *  is testable without a map, a canvas or a projection.
 */

/** The viewport a feature is being sized against. Both axes, because the reference dimension below
 *  is not either of them on its own. */
export interface ViewportSize {
  width: number;
  height: number;
}

/** One feature the pointer is inside, as the style's own properties describe it. */
export interface FeatureCandidate {
  /** The IAU name. Also the feature-state id, so `promoteId` must select this same field. */
  name: string;
  /**
   * The IAU diameter in km, or null where the gazetteer carries none.
   *
   * Null is UNPICKABLE rather than defaulted. Without a size there is no way to know whether this
   * feature reads here, and either guess is a visible error in one direction — an unsized terra
   * washing the frame, or an unsized crater that can never be pointed at.
   */
  diameterKm: number | null;
  /**
   * Whether this came from the archive's LINE layer rather than its polygons.
   *
   * It changes how the size is read, which is why it is carried rather than inferred. For a crater
   * the gazetteer's diameter is a width; for a vallis the same field is a LENGTH, and a 1,758 km
   * channel twenty kilometres wide is perfectly pointable at a zoom where its length crosses the
   * frame several times over. Ares Vallis was unreachable at every zoom until this existed.
   */
  linear: boolean;
}

/**
 * Below this on-screen extent a feature is too small to aim at, so it stops being a target and its
 * container answers instead.
 *
 * It is a floor on the ANSWER, not a hit tolerance: without it, a sub-pixel crater under the
 * pointer at overview zoom would win over the terra that is actually visible there, and the
 * highlight would land on something the visitor cannot see.
 */
export const MIN_TARGET_PX = 28;

/**
 * Above this fraction of the viewport's reference dimension, a REGION no longer fits the frame and
 * stops being a target.
 *
 * The bound is what makes the rule self-correcting across zoom rather than a per-class exception:
 * the same terra is a legitimate target when the camera can see all of it and a bad one when it
 * cannot, and no list of types has to be maintained to say so.
 *
 * CALIBRATED AGAINST FOUR JUDGEMENTS MADE ON A GLOBE, not chosen: a terra accepted with its whole
 * shape on screen, the same terra rejected one zoom closer, and a crater accepted on both a wide
 * desktop and a portrait phone. Those four leave a comfortable gap around this value against the
 * reference below — and only a couple of percent of room against the viewport's shorter side, which
 * is what this used to divide by.
 */
export const MAX_TARGET_VIEWPORT_FRACTION = 0.7;

/**
 * The viewport's characteristic size — the geometric mean of its two sides.
 *
 * NOT THE SHORTER SIDE, and the difference is a phone. A feature's extent is a single number, so it
 * has to be compared against a single number, and the shorter side makes that comparison depend on
 * the aspect ratio: on a portrait phone a crater filling two-thirds of the width scores as though
 * it overflowed, and a tap on the most obvious thing on screen returned nothing. The geometric mean
 * is aspect-insensitive, which is the property actually wanted.
 */
export function viewportReferencePx({ width, height }: ViewportSize): number {
  return Math.sqrt(Math.max(width, 0) * Math.max(height, 0));
}

/** How wide a feature of this diameter is on screen right now, in CSS pixels. */
export function screenExtentPx(diameterKm: number, metresPerPixel: number): number {
  if (!Number.isFinite(metresPerPixel) || metresPerPixel <= 0) return Number.POSITIVE_INFINITY;
  return (diameterKm * 1000) / metresPerPixel;
}

/** Whether a feature of this size reads at the current scale and viewport. */
export function readsAtThisScale(
  candidate: Pick<FeatureCandidate, "diameterKm" | "linear">,
  metresPerPixel: number,
  viewport: ViewportSize,
): boolean {
  if (candidate.diameterKm === null) return false;
  const extent = screenExtentPx(candidate.diameterKm, metresPerPixel);
  if (!Number.isFinite(extent)) return false;
  if (extent < MIN_TARGET_PX) return false;
  // A LINE HAS NO CEILING. The ceiling exists because a region whose boundary runs off every edge
  // shows the visitor nothing they can use; a channel running off two edges is simply a channel,
  // and the part under the pointer is exactly the part being pointed at.
  if (candidate.linear) return true;
  return extent <= MAX_TARGET_VIEWPORT_FRACTION * viewportReferencePx(viewport);
}

/**
 * The one feature to name and light, or null.
 *
 * The smallest ELIGIBLE candidate wins, not the smallest — that ordering is what makes nesting
 * resolve to the most specific thing a visitor can actually see, and what lets this return a single
 * name so the hover tracker keeps a `string | null` and never grows a stack.
 */
export function pickFeature(
  candidates: readonly FeatureCandidate[],
  metresPerPixel: number,
  viewport: ViewportSize,
): string | null {
  let picked: FeatureCandidate | null = null;
  let pickedDiameter = Number.POSITIVE_INFINITY;
  for (const candidate of candidates) {
    if (!readsAtThisScale(candidate, metresPerPixel, viewport)) continue;
    const diameter = candidate.diameterKm!;
    if (diameter < pickedDiameter) {
      picked = candidate;
      pickedDiameter = diameter;
    }
  }
  return picked?.name ?? null;
}

/**
 * A style feature's properties as a candidate, or null when it carries no usable name.
 *
 * The narrowing lives here rather than at the call site because MVT properties are `unknown` at the
 * type level and wrong at runtime in exactly one interesting way: `diameter` is dropped from a tile
 * when the gazetteer's value is falsy, so its absence is data rather than corruption.
 *
 * `linear` is the CALLER'S answer, taken from which layer the feature was queried through, because
 * nothing in the properties distinguishes a channel's length from a crater's width.
 */
export function candidateFrom(
  properties: Record<string, unknown> | null | undefined,
  linear: boolean,
): FeatureCandidate | null {
  const name = properties?.["name"];
  if (typeof name !== "string" || name === "") return null;
  const diameter = properties?.["diameter"];
  return {
    name,
    diameterKm: typeof diameter === "number" && Number.isFinite(diameter) && diameter > 0
      ? diameter
      : null,
    linear,
  };
}
