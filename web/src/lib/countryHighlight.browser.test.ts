import { afterEach, describe, expect, it } from "vitest";
import type { ErrorEvent, Map as MapLibreMap } from "maplibre-gl";
import {
  FIXTURE_HEIGHT_PX,
  FIXTURE_WIDTH_PX,
  mountGlobe,
  type MountedGlobe,
} from "./testing/mountGlobe";
import { WASH_CLEAR_ZOOM, fillLayer } from "./countryHighlight";

/**
 * The wash's zoom fade, handed to a real MapLibre rather than inspected as data.
 *
 * TWO THINGS HERE ARE STRUCTURALLY INVISIBLE TO `countryHighlight.test.ts`, and both of them are
 * how this change would ship dead.
 *
 * The first is whether MapLibre ACCEPTS the expression at all. `["zoom"]` may only be the input of
 * a top-level `interpolate` or `step`, so the hover `case` has to nest inside a stop rather than
 * wrap the curve — and written the intuitive way round MapLibre answers with an ErrorEvent and no
 * throw. A unit test never hands the spec to a map, so it would keep reading a perfectly
 * well-formed object while the layer painted nothing. That is the same silent-failure shape this
 * module already carries a scar for: the hover once addressed a source that did not exist here and
 * the whole highlight was dead in production with every test green.
 *
 * The second is that the fill STAYS PICKABLE once it is invisible. `countryAt` queries this layer
 * first and falls back to the hit circles only for geometry too small to point at, so if the fade
 * ever reached `visibility` instead of opacity, every large country would become unpickable — and
 * only at the high zooms the fade applies to, which is the hardest place to notice it.
 *
 * The layer under test is built by the SHIPPED builder with a fixture binding, so the paint
 * expression is production's and only the data it reads is local. Features come from inline GeoJSON
 * so this runs on CI with no asset store present.
 */

const TEST_SOURCE = "test-countries";
const WASH_LAYER = "country-fill";

/** One country, wide enough to still be under the viewport centre at the zooms that matter here. */
const COUNTRY_CENTRE: [number, number] = [10, 5];
/** Open ocean, far from it — the negative arm that keeps a successful query from being vacuous. */
const OPEN_SEA: [number, number] = [-150, -40];

const filter = ["in", ["get", "ADMIN"], ["literal", ["Testland"]]] as never;

function testland() {
  return {
    type: "FeatureCollection" as const,
    features: [
      {
        type: "Feature" as const,
        properties: { ADMIN: "Testland" },
        geometry: {
          type: "Polygon" as const,
          coordinates: [
            [
              [-5, -10],
              [25, -10],
              [25, 20],
              [-5, 20],
              [-5, -10],
            ],
          ],
        },
      },
    ],
  };
}

const CENTRE_POINT: [number, number] = [FIXTURE_WIDTH_PX / 2, FIXTURE_HEIGHT_PX / 2];

function waitForIdle(map: MapLibreMap): Promise<void> {
  return new Promise((resolve) => map.once("idle", () => resolve()));
}

/**
 * Mount the globe with the real wash layer over one fixture country, collecting every style error.
 *
 * The error listener is attached BEFORE `addLayer`, because a rejected layer spec is reported
 * during that call and a listener added afterwards would see an empty list and agree with itself.
 */
async function mountWithWash(zoom: number, center: [number, number] = COUNTRY_CENTRE) {
  const globe = await mountGlobe({ zoom, center });
  const errors: string[] = [];
  globe.map.on("error", (event: ErrorEvent) => errors.push(event.error?.message ?? String(event)));
  globe.map.addSource(TEST_SOURCE, { type: "geojson", data: testland() });
  globe.map.addLayer(fillLayer(filter, { source: TEST_SOURCE }));
  await waitForIdle(globe.map);
  return { globe, errors };
}

let mounted: MountedGlobe | null = null;

afterEach(() => {
  mounted?.dispose();
  mounted = null;
});

describe("the faded wash against a real map", () => {
  it("is a spec MapLibre accepts, which no assertion over the object can tell you", async () => {
    const { globe, errors } = await mountWithWash(3);
    mounted = globe;

    expect(errors, errors.join("\n")).toEqual([]);
    // The layer surviving `addLayer` is not the same as it being in the style — a rejected spec
    // leaves the map running and the id absent, which is what the ErrorEvent path looks like.
    expect(globe.map.getLayer(WASH_LAYER)).toBeTruthy();
  });

  it("keeps the country pickable at a zoom where the wash has faded to nothing", async () => {
    // Past WASH_CLEAR_ZOOM the layer paints zero alpha over the whole viewport. This is the
    // assertion that would fail the day the fade reaches `visibility` instead of opacity.
    const { globe, errors } = await mountWithWash(WASH_CLEAR_ZOOM + 1);
    mounted = globe;
    expect(errors, errors.join("\n")).toEqual([]);

    const picked = globe.map.queryRenderedFeatures(CENTRE_POINT, { layers: [WASH_LAYER] });
    expect(picked.length, "the invisible wash must still answer the pick").toBeGreaterThan(0);
    expect(picked[0]?.properties?.ADMIN).toBe("Testland");
  });

  it("answers nothing where there is no country, so the pick above is not vacuous", async () => {
    // Without this arm, a query that returns features for every point on the sphere would satisfy
    // the test above just as well as a correct one.
    const { globe } = await mountWithWash(WASH_CLEAR_ZOOM + 1, OPEN_SEA);
    mounted = globe;

    expect(globe.map.queryRenderedFeatures(CENTRE_POINT, { layers: [WASH_LAYER] })).toEqual([]);
  });

  it("is pickable at the low zooms too, so the fade is not what makes it answer", async () => {
    const { globe } = await mountWithWash(3);
    mounted = globe;

    const picked = globe.map.queryRenderedFeatures(CENTRE_POINT, { layers: [WASH_LAYER] });
    expect(picked.length).toBeGreaterThan(0);
  });
});
