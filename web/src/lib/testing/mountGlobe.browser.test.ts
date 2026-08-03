import { afterEach, describe, expect, it } from "vitest";
import { FIXTURE_HEIGHT_PX, FIXTURE_WIDTH_PX, mountGlobe, type MountedGlobe } from "./mountGlobe";

/**
 * The first test in this suite that instantiates a real MapLibre map.
 *
 * WHY THIS EXISTS. Every frontend guard here is a unit test over a pure function, a source-text
 * assertion over `earth.astro?raw`, or a canary over the shipped bundle. None of them can watch the
 * map DO anything, and that gap has shipped a defect: the scale ruler went to production frozen —
 * one label at every zoom — with the unit tests green, the source guards green, the bundle
 * byte-identical to the local build, and the metric the fix targeted reading a perfect 0 readPixels
 * per frame. The only observation that could have caught it was the label changing when the camera
 * changed. That whole class — "renders plausibly and never updates" — is invisible to everything
 * else we own, and the body parameterisation is about to move the radius, the exaggeration and the
 * ruler's distance function, which are exactly the inputs that fail this way.
 *
 * THE TILE-SOURCE DECISION, WHICH IS THE REAL DESIGN WORK. The fixture mounts NO sources at all.
 * A fixture that needs the local asset stores is not a fixture — it cannot run on CI, and it
 * couples every future assertion to a 3 GB archive being present. The things worth asserting here
 * are camera-derived (the ruler reads `unproject`; the chip reads `queryRenderedFeatures` against
 * whatever is loaded), and the camera is real without a single tile. Where a test genuinely needs
 * features, it should add its own source from inline GeoJSON rather than reach for the network.
 *
 * WEBGL IS SOFTWARE-RENDERED HERE and that is deliberate. Playwright's headless chromium gives
 * SwiftShader, which the site's own capability probe correctly rejects for real visitors — but it
 * is the *more* deterministic backend for a test, and nothing asserted here is a pixel.
 */

let mounted: MountedGlobe | null = null;

afterEach(() => {
  // Not hygiene — a budget. This project has already killed a map by leaking WebGL contexts (an
  // instrument once created 13.3 a second), and browsers cap them at ~16 before evicting the
  // oldest. A fixture that forgets this poisons every test that runs after it, in file order.
  mounted?.dispose();
  mounted = null;
});

describe("the globe fixture mounts a real map", () => {
  it("reaches load, which is the whole proof that WebGL works in this environment", async () => {
    mounted = await mountGlobe();
    expect(mounted.map.loaded()).toBe(true);
  });

  it("carries the globe projection the page ships, not the default mercator", async () => {
    mounted = await mountGlobe();
    // Asserted through the public getter rather than by reading back the style we passed in, which
    // would only prove the object literal round-tripped.
    expect(mounted.map.getProjection()?.type).toBe("globe");
  });

  it("has a camera that actually moves, which is what every later assertion rests on", async () => {
    mounted = await mountGlobe();
    // NOT the map centre. [0,0] is where the camera is pointed, so it projects to the middle of
    // the viewport at every zoom — it cannot move, and asserting that it does fails against a
    // perfectly healthy camera. An OFF-CENTRE ground point is the only one whose screen position
    // carries any information about the transform.
    const offCentre: [number, number] = [45, 30];
    const before = mounted.map.project(offCentre);
    mounted.map.jumpTo({ zoom: mounted.map.getZoom() + 2 });
    const after = mounted.map.project(offCentre);

    expect(mounted.map.getZoom()).toBeGreaterThan(1);
    // If this ever passes with identical points the camera is inert, and every camera-tracking
    // assertion built on this fixture is vacuous.
    expect({ x: after.x, y: after.y }).not.toEqual({ x: before.x, y: before.y });
  });

  it("builds the map at the size the fixture asked for, not merely a non-zero one", async () => {
    mounted = await mountGlobe();
    const canvas = mounted.map.getCanvas();
    // MEASURED, because the obvious assertion is vacuous. The first version of this test asked
    // only for a non-zero box — and deleting the container's height still passed it: the fixture
    // does not inject MapLibre's stylesheet, so the canvas flows normally and hands the div a
    // height back. The map built an 800x158 strip and every geometric assertion above it would
    // have been measuring that. What matters is not that the viewport exists but that it is the
    // one the fixture declared, so downstream tests can reason about a known frame.
    expect({ width: canvas.clientWidth, height: canvas.clientHeight }).toEqual({
      width: FIXTURE_WIDTH_PX,
      height: FIXTURE_HEIGHT_PX,
    });
  });

  it("removes the map and its container on dispose", async () => {
    const globe = await mountGlobe();
    const { container } = globe;
    globe.dispose();
    mounted = null;
    expect(container.isConnected).toBe(false);
  });
});
