import type { Map as MaplibreMap, SourceSpecification } from "maplibre-gl";
import { TERRAIN_SOURCE } from "./terrainSource";

/**
 * Put the DEM source and terrain on the map's current style. Called from every `style.load`.
 *
 * A WebGL context restore reloads a style that already carries the source, and MapLibre 6.x has
 * already rebuilt terrain from it, handing the old terrain's drapes, dead with the lost context, to
 * the new painter's drape pool. Removing the terrain empties that pool, so a restore takes the
 * source as found and sets terrain from nothing. Once MapLibre restores terrain cleanly on its own,
 * a canary beside this module goes red and the `setTerrain(null)` can go.
 */
export function attachTerrain(
  map: MaplibreMap,
  source: SourceSpecification,
  exaggeration: number,
): void {
  if (map.getSource(TERRAIN_SOURCE)) map.setTerrain(null);
  else map.addSource(TERRAIN_SOURCE, source);
  map.setTerrain({ source: TERRAIN_SOURCE, exaggeration });
}
