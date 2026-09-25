import { afterEach, describe, expect, it } from "vitest";
import type * as maplibregl from "maplibre-gl";
import { mountGlobe, type MountedGlobe } from "./testing/mountGlobe";
import { pointIsOnPlanet, roundTripSaysOnPlanet } from "./pointOnPlanet";

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
    expect(pointIsOnPlanet(map, { x: 0, y: 0 })).toBe(false);
  });

  it("agrees with a round trip through the public projection, which is the degraded path", async () => {
    mounted = await mountGlobe({ zoom: 1 });
    const map = mounted.map;

    // Two independent answers to one question: MapLibre's own surface test, and projecting the
    // located ground point back to see whether it lands where it was read. A gate that only ever
    // agreed with itself would be no oracle at all.
    for (const point of [map.project([0, 0]), map.project([40, 20]), { x: 0, y: 0 }, { x: 799, y: 0 }]) {
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
    expect(pointIsOnPlanet(map, { x: centre.x + radius * 0.5, y: centre.y })).toBe(true);
    expect(pointIsOnPlanet(map, { x: centre.x + radius * 1.5, y: centre.y })).toBe(false);
  });
});
