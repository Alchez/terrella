import type * as maplibregl from "maplibre-gl";

/**
 * Is this screen point on the planet, or on the space beside it?
 *
 * Every picker on the globe needs this and nothing else answers it: `queryRenderedFeatures` returns
 * features for a point beyond the limb, and `screenPointToLocation` hands back a location for any
 * point on the canvas, its return type never being null.
 *
 * Asked of the camera's transform, which MapLibre types but does not document. Read per call,
 * because MapLibre replaces it when the style sets the projection.
 */
export function pointIsOnPlanet(map: maplibregl.Map, point: maplibregl.Point): boolean {
  // No terrain argument: passing one makes this read the draped surface back off the GPU, which
  // is a stall on a listener that runs per pointer move. The sphere is the right question anyway.
  return map._camera.transform.isPointOnMapSurface(point);
}
