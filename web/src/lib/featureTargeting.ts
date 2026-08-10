/** WHICH named feature a point picks, and at WHAT SCALE it should be shown — one band, read both ways.
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
 *  THE FRAMING LIVES HERE BECAUSE IT IS THE SAME QUESTION ASKED BACKWARDS. Deciding that a feature
 *  reads at the current scale and deciding what scale to show it at are one relationship, measured
 *  against one reference dimension — so the fly-to fraction and the ceiling it must stay under are
 *  adjacent constants a test can compare, rather than two numbers in two files that agree by habit.
 *  Split them and the first edit to either lands the camera exactly where the feature stops
 *  answering.
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

/**
 * MapLibre's own tile size in CSS pixels — the unit `2^zoom` scales the world by.
 *
 * NOT the 512 px rasters we serve, which the style is told are 256; this is the projection's
 * internal unit and is independent of anything we publish. `scaleRuler.browser.test.ts` carries its
 * own copy of this number and THAT COPY MUST NOT BE COLLAPSED INTO THIS ONE: it is the independent
 * oracle over a live transform, and an oracle importing the constant it is checking agrees with
 * itself no matter how wrong both are.
 */
const MERCATOR_TILE_PX = 512;

/**
 * The furthest north or south the camera CENTRE can be placed. Measured, because nothing exports it.
 *
 * MapLibre clamps here on every route into the transform — asked for 86, 88 and 89.9 degrees it
 * returns this latitude each time — and it is the Web Mercator limit rather than a globe one, so it
 * binds even though the sphere plainly has ground beyond it. Seven adopted centres lie past it, and
 * for those the scale to frame against is the scale AT THE CLAMP: computing from the feature's own
 * latitude would size the view for a camera position that cannot be reached, and arrive too close.
 */
export const MAX_CENTRE_LATITUDE = 85.0511;

/**
 * The share of the viewport's reference dimension a feature's diameter spans when the camera lands.
 *
 * IT MUST STAY BELOW `MAX_TARGET_VIEWPORT_FRACTION`, and that is the only hard constraint on it.
 * The two measure the same quantity against the same reference, so framing at or above the ceiling
 * puts the camera exactly where the feature stops being a target — fly to a crater and watch its
 * highlight disappear on arrival. The gap also absorbs an irregular polygon that overruns its
 * nominal diameter, which the gazetteer's regions routinely do.
 *
 * Judged on the globe at 0.5, which lands the crossover with the zoom ceiling near the catalogue's
 * own scale break: the features that clamp are craters, the ones framed as asked are landmarks.
 */
export const FLY_TO_VIEWPORT_FRACTION = 0.5;

/** Ground metres one CSS pixel spans at `zoom` and `latitude`, on a sphere of `groundRadiusM`. */
function groundMetresPerPixel(zoom: number, latitude: number, groundRadiusM: number): number {
  const circumferenceAtLatitude =
    2 * Math.PI * groundRadiusM * Math.cos((latitude * Math.PI) / 180);
  return circumferenceAtLatitude / (MERCATOR_TILE_PX * 2 ** zoom);
}

/**
 * The zoom that frames this feature at `FLY_TO_VIEWPORT_FRACTION`, or null when it cannot be sized.
 *
 * NULL IS "CENTRE IT AND CHANGE NOTHING ELSE", not an error. Two features carry no diameter, and
 * for those the honest camera knows where but not how big — the same asymmetry `candidateFrom`
 * already encodes by refusing to guess a size.
 *
 * The caller still has to clamp against the map's own zoom range. Deliberately not done here: the
 * ceiling is a property of the body's pyramid, this is a property of the catalogue, and folding one
 * into the other is what makes a constant turn up in a file that has no business knowing it.
 * Clamping is also what a visitor sees as the rule breaking down — a small crater arrives smaller
 * than asked, and no arithmetic here can change that.
 */
export function framingZoom(
  diameterKm: number | null,
  latitude: number,
  viewport: ViewportSize,
  groundRadiusM: number,
): number | null {
  if (diameterKm === null || !(diameterKm > 0)) return null;
  const reference = viewportReferencePx(viewport);
  if (!(reference > 0)) return null;
  const targetMetresPerPixel =
    (diameterKm * 1000) / (FLY_TO_VIEWPORT_FRACTION * reference);
  const reachableLatitude = Math.max(
    -MAX_CENTRE_LATITUDE,
    Math.min(MAX_CENTRE_LATITUDE, latitude),
  );
  return Math.log2(
    groundMetresPerPixel(0, reachableLatitude, groundRadiusM) / targetMetresPerPixel,
  );
}
