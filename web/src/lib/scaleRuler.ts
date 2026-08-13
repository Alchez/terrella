/**
 * The globe's scale readout — a FIXED-WIDTH ruler whose value changes, sitting on the view bar's
 * top edge.
 *
 * WHY NOT MapLibre's `ScaleControl`. It works the other way round: it picks a round distance
 * (500 km, 2000 km) and sets the element's width to whatever that measures on screen, rewriting an
 * inline `width` on every camera change. On a control docked in a corner that is invisible; on a
 * ruler resting against a centred pill it is a span that twitches between 40 and 120 px as you
 * zoom, which reads as instability in the chrome rather than as information about the map.
 *
 * Fixing the width inverts the arithmetic: the span is a constant, and the number becomes whatever
 * that span measures. The cost is a number that is not round, so it is reported to two significant
 * figures — stable to read, and already more precision than a scale bar on a sphere can honestly
 * claim.
 */

/** The ruler's span. Constant by design — see the module note. */
export const RULER_WIDTH_PX = 96;

/**
 * The two screen points whose ground separation the ruler reports, centred in the viewport.
 *
 * CENTRED, not anchored at x=0 like MapLibre's control. On a globe the left edge of the viewport
 * is frequently off the sphere entirely, where unprojecting returns a point on the plane behind
 * it — a distance that is not a distance on any map. The middle of the frame is the one place
 * guaranteed to be on the globe whenever the globe is visible at all.
 */
export function rulerSamplePoints(
  width: number,
  height: number,
  spanPx: number = RULER_WIDTH_PX,
): [[number, number], [number, number]] {
  const midX = width / 2;
  const midY = height / 2;
  return [
    [midX - spanPx / 2, midY],
    [midX + spanPx / 2, midY],
  ];
}

/** The one screen→ground result the ruler needs. Structural, so this module still imports nothing.
 *
 *  IT USED TO BE `{ distanceTo(other) }`, AND THAT IS THE WHOLE BUG. Taking the locator injected
 *  read as body-agnostic, and it is not: a library's point type carries its own idea of a metre —
 *  MapLibre's multiplies by a hardcoded 6371008.8 — so the seam injected WHERE THE POINTS ARE and
 *  never WHAT A METRE IS WORTH. Every planet got Earth's distances, off by the ratio of the radii,
 *  plausible at every zoom. Narrowing this to coordinates moves the conversion here, where the body
 *  can be an argument. `maplibregl.LngLat` satisfies it unchanged. */
export interface GroundLocation {
  lng: number;
  lat: number;
}

/**
 * Ground metres spanned by the ruler, measured through `locate`.
 *
 * `locate` MUST NOT BE `map.unproject`, and that is a performance contract rather than a style
 * preference. `unproject` resolves a screen point against the DRAPED surface, which on a terrain
 * map means rendering tile coordinates into an offscreen framebuffer and reading them back —
 * a synchronous GPU stall. This runs on `move`, so it was paid TWICE PER FRAME of every drag and
 * every ease: measured at 1.9 `readPixels` per frame, 9.8% of the main thread, and 0.00 per frame
 * with the listener detached. Pass the transform's own `screenPointToLocation(point)` with no
 * terrain argument — same answer on the datum, no GPU work.
 *
 * Living here rather than at the call site so the measurement has ONE home that a test can reach;
 * the caller supplies only the conversion, and `scaleRuler.test.ts` pins which conversion that is.
 *
 * `groundRadiusM` IS REQUIRED AND HAS NO DEFAULT, which is the whole shape of the fix. A default
 * would be Earth's, and a body that forgot to pass one would read plausibly rather than fail — the
 * same reason the pipeline's entry points take a required `--body`. Passing it makes the compiler
 * name every call site instead of leaving one to be remembered.
 *
 * THE ARC IS COMPUTED HERE, deliberately by the spherical law of cosines and in that exact order of
 * operations, because that is what `LngLat.distanceTo` does — so on Earth, with the mean radius the
 * registry now holds, this returns the same double the ruler has always shown. Earth's readings are
 * unchanged by identity rather than by tolerance, and `scaleRuler.test.ts` proves it against the
 * library over a table of pairs. Haversine would be better conditioned for tiny separations and is
 * not worth losing that: at the ruler's widest zoom the angle is ~9e-3 rad, where the loss is ~1e-8
 * relative, against a label rounded to two significant figures.
 *
 * The `Math.min(…, 1)` is not defensive tidiness: floating-point can push the cosine a hair above 1
 * for two points at the same place, and `Math.acos` of that is NaN — which the formatter would
 * render as the em-dash placeholder for a camera that is simply parked.
 */
export function rulerGroundDistance(
  locate: (point: [number, number]) => GroundLocation,
  groundRadiusM: number,
  width: number,
  height: number,
  spanPx: number = RULER_WIDTH_PX,
): number {
  const [leftPoint, rightPoint] = rulerSamplePoints(width, height, spanPx);
  const from = locate(leftPoint);
  const to = locate(rightPoint);
  const radiansPerDegree = Math.PI / 180;
  const fromLatitude = from.lat * radiansPerDegree;
  const toLatitude = to.lat * radiansPerDegree;
  const cosineOfArc =
    Math.sin(fromLatitude) * Math.sin(toLatitude) +
    Math.cos(fromLatitude) *
      Math.cos(toLatitude) *
      Math.cos((to.lng - from.lng) * radiansPerDegree);
  return groundRadiusM * Math.acos(Math.min(cosineOfArc, 1));
}

/**
 * A ground distance in metres as a short label: "1,800 km", "480 km", "4.8 km", "480 m".
 *
 * Two significant figures throughout. Three would imply a precision the projection does not have
 * (scale on a sphere is only true at the point you measure it), and a raw value would churn the
 * last digit on every frame of a drag.
 */
export function formatGroundDistance(metres: number): string {
  // An em dash rather than "0 m" for the states that are not a distance — a camera mid-flight, a
  // sample that missed the globe. A plausible-looking zero is worse than an obvious blank.
  if (!Number.isFinite(metres) || metres <= 0) return "—";

  let value = metres;
  let unit = "m";
  if (value >= 1000) {
    value /= 1000;
    unit = "km";
  }
  let rounded = Number(value.toPrecision(2));
  // Rounding can push a sub-kilometre distance up through the boundary: 999.6 m to two significant
  // figures is 1000, and "1,000 m" is a unit the label should have already left behind.
  if (unit === "m" && rounded >= 1000) {
    rounded = Number((rounded / 1000).toPrecision(2));
    unit = "km";
  }
  return `${rounded.toLocaleString("en-US")} ${unit}`;
}

export interface ScaleRuler {
  readonly element: HTMLElement;
  /** Write a new reading. A no-op when the label has not changed, so a drag costs no DOM writes. */
  setDistance(metres: number): void;
}

/**
 * Build the ruler. Ours rather than MapLibre's, so the markup carries no inline width to fight
 * and the element can be a plain readout.
 */
export function createScaleRuler(): ScaleRuler {
  const element = document.createElement("div");
  element.className = "view-bar-ruler";
  // THE WIDTH IS SET FROM THE SAME CONSTANT THE SAMPLE SPAN USES, not restated in CSS. The drawn
  // span and the measured span are the same claim — a stylesheet free to disagree with this file
  // would make the ruler quietly lie, which is the one thing a scale bar must not do.
  element.style.width = `${RULER_WIDTH_PX}px`;
  // A readout, not a control: it must never eat a drag aimed at the globe behind it, and it is
  // decorative to a screen reader that has just been told the zoom level by the map itself.
  element.setAttribute("aria-hidden", "true");

  let shown = "";
  return {
    element,
    setDistance(metres: number): void {
      const next = formatGroundDistance(metres);
      if (next === shown) return;
      shown = next;
      element.textContent = next;
    },
  };
}
