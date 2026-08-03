import { afterEach, describe, expect, it } from "vitest";
import type { Map as MapLibreMap } from "maplibre-gl";
import { FIXTURE_HEIGHT_PX, FIXTURE_WIDTH_PX, mountGlobe, type MountedGlobe } from "./testing/mountGlobe";
import { createHoverTracker } from "./hoverTracking";

/**
 * Hover resolved against a REAL map, which is the half the unit tests structurally cannot reach.
 *
 * `hoverTracking.test.ts` drives the tracker with a fake `resolve` and a hand-cranked frame clock,
 * and that is the right way to test the coalescing, the leave-cancels-a-queued-resolve rule and the
 * change-only callback. What it cannot test is `resolve` itself — in production that is
 * `queryRenderedFeatures` against the country hit layer, and a fake stands in for exactly the part
 * that needs geometry on screen to mean anything.
 *
 * THE BUG THIS PINS IS IN THE MODULE'S OWN HISTORY. Hover was once recomputed on pointer movement
 * alone, so a camera move under a parked pointer left the answer on the country that used to be
 * there — unbounded after a drag, 2.2 s after a fly-to, one step per frame during auto-spin. It was
 * invisible while the highlight was an anonymous outline and stopped being invisible the moment a
 * chip stated the name. `viewChanged()` exists for it, and until now nothing asserted that the
 * answer actually moves when only the camera does.
 *
 * FEATURES COME FROM INLINE GEOJSON, never the tile network. Two labelled boxes are enough to ask
 * every question here, they make the fixture data legible in the file that depends on it, and they
 * keep this runnable on CI with no asset store present.
 */

/** Two well-separated boxes on the equator, standing in for two countries. */
const ALPHA_CENTRE: [number, number] = [-30, 0];
const BETA_CENTRE: [number, number] = [30, 0];
/** Open ocean between them carries no feature, which is what a null hover means here. */
const EMPTY_CENTRE: [number, number] = [0, 0];

const HIT_LAYER = "test-hit";

function box(west: number, east: number, admin: string) {
  return {
    type: "Feature" as const,
    properties: { ADMIN: admin },
    geometry: {
      type: "Polygon" as const,
      coordinates: [
        [
          [west, -10],
          [east, -10],
          [east, 10],
          [west, 10],
          [west, -10],
        ],
      ],
    },
  };
}

function waitForIdle(map: MapLibreMap): Promise<void> {
  return new Promise((resolve) => map.once("idle", () => resolve()));
}

/** Mount the globe and give it two queryable countries. */
async function mountWithCountries(): Promise<MountedGlobe> {
  const globe = await mountGlobe({ zoom: 2, center: ALPHA_CENTRE });
  globe.map.addSource("test-countries", {
    type: "geojson",
    data: { type: "FeatureCollection", features: [box(-40, -20, "ALPHA"), box(20, 40, "BETA")] },
  });
  globe.map.addLayer({
    id: HIT_LAYER,
    type: "fill",
    source: "test-countries",
    paint: { "fill-color": "#ff0000" },
  });
  await waitForIdle(globe.map);
  return globe;
}

/** The centre of the viewport — the one screen point guaranteed to be on the sphere.
 *
 *  A TUPLE, not `{x, y}`. `queryRenderedFeatures` takes `PointLike`, and handed a plain object it
 *  returns ZERO FEATURES rather than throwing — measured, and it read exactly like a map with
 *  nothing rendered on it. (`screenPointToLocation`, which the ruler uses, does accept a plain
 *  object, so the two APIs disagree and only one of them says so.) */
const CENTRE_POINT: [number, number] = [FIXTURE_WIDTH_PX / 2, FIXTURE_HEIGHT_PX / 2];

let mounted: MountedGlobe | null = null;

afterEach(() => {
  mounted?.dispose();
  mounted = null;
});

/**
 * Build the tracker over the real map, with the frame clock held by hand.
 *
 * A hand-cranked clock rather than the browser's, for the reason the module documents: an
 * auto-flushing frame would make "queued" and "ran" indistinguishable, and the coalesce is exactly
 * that difference. Here it also removes every timing race from the assertions below.
 */
function trackerOver(globe: MountedGlobe) {
  const frames: (() => void)[] = [];
  const changes: (string | null)[] = [];
  const tracker = createHoverTracker<[number, number]>({
    resolve: (point) => {
      const [feature] = globe.map.queryRenderedFeatures(point, { layers: [HIT_LAYER] });
      return (feature?.properties?.ADMIN as string | undefined) ?? null;
    },
    onChange: (admin) => changes.push(admin),
    scheduleFrame: (callback) => frames.push(callback),
  });
  const flush = () => {
    const queued = frames.splice(0);
    for (const callback of queued) callback();
  };
  return { tracker, flush, changes };
}

describe("hover resolves against a real map", () => {
  it("finds the country actually under the pointer, which every other case depends on", async () => {
    mounted = await mountWithCountries();
    const { tracker, flush } = trackerOver(mounted);

    tracker.pointerMoved(CENTRE_POINT);
    flush();

    // The positive control. Without it every assertion below could be satisfied by a map that
    // renders nothing at all and answers null to everything.
    expect(tracker.current()).toBe("ALPHA");
  });

  it("answers null over open sea rather than the last country it saw", async () => {
    mounted = await mountWithCountries();
    const { tracker, flush } = trackerOver(mounted);

    tracker.pointerMoved(CENTRE_POINT);
    flush();
    expect(tracker.current()).toBe("ALPHA");

    mounted.map.jumpTo({ center: EMPTY_CENTRE });
    await waitForIdle(mounted.map);
    tracker.viewChanged();
    flush();

    expect(tracker.current()).toBeNull();
  });

  it("FOLLOWS THE CAMERA under a parked pointer, which is the bug viewChanged exists for", async () => {
    mounted = await mountWithCountries();
    const { tracker, flush, changes } = trackerOver(mounted);

    tracker.pointerMoved(CENTRE_POINT);
    flush();
    expect(tracker.current()).toBe("ALPHA");

    // The pointer does not move. Only the world underneath it does — a drag, a fly-to, or one step
    // of the idle spin. The stale-hover bug is entirely invisible to any test that moves a pointer.
    mounted.map.jumpTo({ center: BETA_CENTRE });
    await waitForIdle(mounted.map);
    tracker.viewChanged();
    flush();

    expect(tracker.current()).toBe("BETA");
    expect(changes, "the change must be announced, not merely readable").toEqual(["ALPHA", "BETA"]);
  });

  it("clears synchronously when the pointer leaves, with no frame of lingering chip", async () => {
    mounted = await mountWithCountries();
    const { tracker, flush } = trackerOver(mounted);

    tracker.pointerMoved(CENTRE_POINT);
    flush();
    expect(tracker.current()).toBe("ALPHA");

    // No flush: leaving must not wait for a frame. The chip and the outline sit over empty canvas
    // for that whole frame otherwise, which is the one place the latency is visible.
    tracker.pointerLeft();

    expect(tracker.current()).toBeNull();
  });

  it("does not revive a hover when the camera moves after the pointer has left", async () => {
    mounted = await mountWithCountries();
    const { tracker, flush } = trackerOver(mounted);

    tracker.pointerMoved(CENTRE_POINT);
    flush();
    tracker.pointerLeft();

    mounted.map.jumpTo({ center: BETA_CENTRE });
    await waitForIdle(mounted.map);
    tracker.viewChanged();
    flush();

    // A camera move with no pointer on the canvas must resolve nothing — reviving here would put a
    // chip back on screen naming a country the user is not pointing at.
    expect(tracker.current()).toBeNull();
  });
});
