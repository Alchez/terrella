import { afterEach, describe, expect, it, vi } from "vitest";
import * as maplibregl from "maplibre-gl";
import { mountGlobe, type MountedGlobe } from "./testing/mountGlobe";
import { pointIsOnPlanet } from "./pointOnPlanet";

/**
 * The defect this exists for: with the pointer on empty space beside the disc, the globe named a
 * place as if the pointer were on it — Earth answering China and Brazil from two corners of a 1920
 * by 1080 window, Mars answering Noachis Terra, Arabia Terra and Terra Sirenum from three.
 *
 * The cause is asserted here rather than described: `queryRenderedFeatures` at a point beyond the
 * limb RETURNS FEATURES, so every hover resolver built on it needs something upstream that knows
 * where the planet ends. That is what makes the first test below the interesting one — it is the
 * bug, reproduced in eight lines of inline GeoJSON, and it stays green after the fix because
 * nothing about the query changed.
 */

let mounted: MountedGlobe | null = null;

afterEach(() => {
  mounted?.dispose();
  mounted = null;
});

/** A fill covering the whole sphere, which is what makes a query off the disc answerable at all. */
async function worldFill(map: maplibregl.Map): Promise<void> {
  map.addSource("world", {
    type: "geojson",
    data: {
      type: "Feature",
      properties: { name: "everywhere" },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [-180, -85],
            [180, -85],
            [180, 85],
            [-180, 85],
            [-180, -85],
          ],
        ],
      },
    },
  });
  map.addLayer({ id: "world-fill", type: "fill", source: "world", paint: { "fill-color": "#fff" } });
  await new Promise<void>((resolve) => map.once("idle", () => resolve()));
}

/** What a round trip may lose to MapLibre's own rounding before the point counts as off the disc. */
const ROUND_TRIP_SLACK_PX = 1;

/**
 * The same question asked through the public projection alone, as the oracle: locate the point,
 * project the location back, and see whether it lands where it was read. Off the disc it does not,
 * because a ray that misses the sphere resolves to the horizon instead.
 */
function roundTripSaysOnPlanet(map: maplibregl.Map, point: maplibregl.Point): boolean {
  const back = map.project(map.unproject(point));
  return Math.hypot(back.x - point.x, back.y - point.y) <= ROUND_TRIP_SLACK_PX;
}

/** Half the disc's width on screen, measured off the transform rather than assumed from the zoom. */
function discRadiusPx(map: maplibregl.Map): number {
  const centre = map.project([0, 0]);
  const limb = map.project([90, 0]);
  return Math.hypot(limb.x - centre.x, limb.y - centre.y);
}

describe("a screen point beside the globe is not a point on the globe", () => {
  it("reproduces the cause: the feature query answers off the disc", async () => {
    mounted = await mountGlobe({ zoom: 1 });
    await worldFill(mounted.map);
    const corner = { x: 0, y: 0 };

    // The fixture's own geometry, so a camera change cannot make this test vacuous by putting the
    // corner back on the planet.
    const centre = mounted.map.project([0, 0]);
    expect(Math.hypot(centre.x - corner.x, centre.y - corner.y)).toBeGreaterThan(
      discRadiusPx(mounted.map),
    );

    expect(
      mounted.map.queryRenderedFeatures([corner.x, corner.y], { layers: ["world-fill"] }).length,
      "if this is 0 the defect is gone from MapLibre and the gate below is dead code",
    ).toBeGreaterThan(0);
  });

  it("says a corner is off the planet and the middle is on it", async () => {
    mounted = await mountGlobe({ zoom: 1 });
    const map = mounted.map;

    expect(pointIsOnPlanet(map, map.project([0, 0]))).toBe(true);
    expect(pointIsOnPlanet(map, new maplibregl.Point(0, 0))).toBe(false);
  });

  it("agrees with a round trip through the public projection", async () => {
    mounted = await mountGlobe({ zoom: 1 });
    const map = mounted.map;

    // Two independent answers to one question: MapLibre's own surface test, and projecting the
    // located ground point back to see whether it lands where it was read. A gate that only ever
    // agreed with itself would be no oracle at all.
    const corners = [new maplibregl.Point(0, 0), new maplibregl.Point(799, 0)];
    for (const point of [map.project([0, 0]), map.project([40, 20]), ...corners]) {
      expect(roundTripSaysOnPlanet(map, point), `${point.x},${point.y}`).toBe(
        pointIsOnPlanet(map, point),
      );
    }
  });

  it("holds along a ray: on near the middle, off past the limb", async () => {
    mounted = await mountGlobe({ zoom: 1 });
    const map = mounted.map;
    const centre = map.project([0, 0]);
    const radius = discRadiusPx(map);

    // Well inside and well outside, leaving the limb itself alone: a pixel either side of the edge
    // is a question about MapLibre's rounding, not about this gate.
    expect(pointIsOnPlanet(map, new maplibregl.Point(centre.x + radius * 0.5, centre.y))).toBe(true);
    expect(pointIsOnPlanet(map, new maplibregl.Point(centre.x + radius * 1.5, centre.y))).toBe(false);
  });

  it("answers without the painter's copy of the transform, which MapLibre's main no longer keeps", async () => {
    mounted = await mountGlobe({ zoom: 1 });
    const map = mounted.map;
    const painter = map.painter as unknown as { transform: unknown };
    expect(painter.transform, "the painter keeps no transform, so this has nothing left to prove").toBeDefined();
    const unproject = vi.spyOn(map, "unproject");

    // Synchronous from here to the restore, so no frame draws without the painter's copy.
    const kept = painter.transform;
    painter.transform = undefined;
    try {
      expect(pointIsOnPlanet(map, map.project([0, 0]))).toBe(true);
      expect(pointIsOnPlanet(map, new maplibregl.Point(0, 0))).toBe(false);
    } finally {
      painter.transform = kept;
    }
    expect(unproject, "fell back to the path that reads the GPU back").not.toHaveBeenCalled();
  });
});
