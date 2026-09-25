import type * as maplibregl from "maplibre-gl";

/** A screen point, in the shape MapLibre's own `Point` and a raw `{x, y}` both satisfy. */
export interface ScreenPoint {
  x: number;
  y: number;
}

/** What a round trip may lose to MapLibre's own rounding before the point counts as off the disc. */
const ROUND_TRIP_SLACK_PX = 1;

let warnedAboutFallback = false;

/**
 * Is this screen point on the planet, or on the space beside it?
 *
 * Every picker on the globe needs this and nothing else answers it: `queryRenderedFeatures` returns
 * features for a point beyond the limb, and `screenPointToLocation` hands back a location for any
 * point on the canvas, its return type never being null.
 *
 * `painter.transform`, per call and not `map.transform`, for the two reasons `locateOnDatum` in
 * `Globe.astro` carries: `map.transform` is undefined at runtime, and MapLibre replaces
 * `painter.transform` after page scripts run, so a hoisted reference answers from a frozen camera.
 */
export function pointIsOnPlanet(map: maplibregl.Map, point: ScreenPoint): boolean {
  const transform = (map as unknown as { painter?: { transform?: Record<string, unknown> } })
    .painter?.transform;
  const onSurface = transform?.["isPointOnMapSurface"];
  if (typeof onSurface === "function") {
    // No terrain argument: passing one makes this read the draped surface back off the GPU, which
    // is a stall on a listener that runs per pointer move. The sphere is the right question anyway.
    return (onSurface as (p: ScreenPoint) => boolean).call(transform, point);
  }
  if (!warnedAboutFallback) {
    warnedAboutFallback = true;
    console.warn("[hover] painter.transform.isPointOnMapSurface is gone — projecting instead");
  }
  return roundTripSaysOnPlanet(map, point);
}

/**
 * The same question asked through the public projection alone: locate the point, project the
 * location back, and see whether it lands where it was read. Off the disc it does not, because a
 * ray that misses the sphere resolves to the horizon instead.
 *
 * Slower than the transform call and correct without it, which is what makes it both the degraded
 * path and the independent oracle the tests check the fast one against.
 */
export function roundTripSaysOnPlanet(map: maplibregl.Map, point: ScreenPoint): boolean {
  const back = map.project(map.unproject([point.x, point.y]));
  return Math.hypot(back.x - point.x, back.y - point.y) <= ROUND_TRIP_SLACK_PX;
}
