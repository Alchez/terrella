import { afterEach, expect, it } from "vitest";
import { mountGlobe, type MountedGlobe } from "./testing/mountGlobe";

/**
 * The effect half of the vendored MapLibre patch guard — `vendoredPatches.test.ts` is the presence
 * half, and its head carries what the patch is and when to delete both.
 *
 * A regex over the bundle proves an expression is there. It cannot prove the expression does
 * anything, and the whole reason this patch needs a guard is that dropping it changes no picture and
 * raises no error. So this file asks the shipped bundle the question the patch exists to answer:
 * having asked for zoom Z, does the frame come back at zoom Z?
 *
 * TWO INVARIANTS, because a mislocated camera surfaces two ways and one assertion catches half of it:
 *
 *   maxZ <= nominal + 1   part of the frame refined far past what it asked for
 *   minZ <= nominal       the WHOLE frame refined deeper than it asked for
 *
 * Neither is claimed as a bound that holds at every camera anywhere; both are what these cameras
 * should return, and both were measured to hold at all of them with the patch applied.
 *
 * THE SWEEPS ARE LAWS, NOT COORDINATES. The seam block walks the antimeridian because the defect
 * peaked there; the ridge block walks `u = cameraToCenterDistance * sin(pitch) / globeRadiusPixels`
 * rather than a remembered zoom, because the cliff zoom moves with canvas height and a number copied
 * from the 2560x1265 rig lands off the ridge in this 900x900 fixture — where it would pass while
 * measuring nothing. `u` is solved for THIS canvas on every run.
 *
 * MUTATION-PROVEN, and worth re-running if these numbers are ever doubted: copy an unpatched 6.3.0
 * `dist/maplibre-gl.mjs` over the installed one, `rm -rf node_modules/.vite` — without which Vite
 * serves its pre-bundled copy and the mutation never reaches the test — and re-run. Measured:
 * 13 violations unpatched against 0 patched, the worst being 1,663 tiles at z11-z12 where the
 * camera asked for z7, and 229 tiles at z6-z8 on the ridge where it asked for z5.
 */

const FOV_DEG = 15; // the app's lens — VERTICAL_FIELD_OF_VIEW_DEG in Globe.astro
const PITCH_DEG = 60;
const FIXTURE_PX = 900;
const TILE_SIZE = 512;

/** Globe consults the camera position only above this; at or below it every assertion here is vacuous. */
const VARIABLE_ZOOM_GATE = 4;

let globe: MountedGlobe | undefined;
afterEach(() => {
  globe?.dispose();
  globe = undefined;
});

const rad = (deg: number) => (deg * Math.PI) / 180;

it("selects no tile deeper than the zoom the camera asked for", async () => {
  globe = await mountGlobe({
    width: FIXTURE_PX,
    height: FIXTURE_PX,
    center: [0, 0],
    zoom: 7.5,
  });
  const map = globe.map;
  map.setVerticalFieldOfView(FOV_DEG);
  // The lens is the axis the defect is keyed to, so a silently ignored setter would move every
  // camera below out of regime and report a clean pass.
  expect(map.getVerticalFieldOfView()).toBe(FOV_DEG);

  const canvasHeight = map.getCanvas().clientHeight;
  expect(
    canvasHeight,
    "the fixture canvas is not the height it declared, so every zoom solved from it is wrong",
  ).toBe(FIXTURE_PX);

  const cameraToCenter = (0.5 * canvasHeight) / Math.tan(rad(FOV_DEG) / 2);
  /** Zoom placing this canvas, lens and pitch at `u` on the curve. */
  const ridgeZoom = (u: number, lat: number) =>
    Math.log2(
      (cameraToCenter * Math.sin(rad(PITCH_DEG)) * 2 * Math.PI * Math.cos(rad(lat))) /
        u /
        TILE_SIZE,
    );

  const cameras: { center: [number, number]; zoom: number; bearing: number }[] = [];
  for (let lon = -180; lon < 180; lon += 5) {
    for (const bearing of [0, 45, 90, 135, 180, 225, 270, 315]) {
      cameras.push({ center: [lon, 0], zoom: 7.5, bearing });
    }
  }
  for (let u = 0.4; u <= 1.0001; u += 0.005) {
    cameras.push({ center: [-140, -52], zoom: ridgeZoom(u, -52), bearing: 0 });
  }

  const violations: string[] = [];
  let inRegime = 0;
  for (const camera of cameras) {
    map.jumpTo({ ...camera, pitch: PITCH_DEG });
    // Read the camera back rather than trusting what was asked for: a jumpTo that did not take
    // would otherwise be scored under the label of a camera that never ran.
    const nominal = Math.floor(map.getZoom());
    if (nominal <= VARIABLE_ZOOM_GATE) continue;
    inRegime++;

    const levels = map.coveringTiles({ tileSize: TILE_SIZE }).map((tile) => tile.canonical.z);
    const maxZ = Math.max(...levels);
    const minZ = Math.min(...levels);
    if (maxZ > nominal + 1 || minZ > nominal) {
      violations.push(
        `lon ${map.getCenter().lng.toFixed(0)} z${map.getZoom().toFixed(3)} ` +
          `bearing ${camera.bearing}: asked z${nominal}, got ${levels.length} tiles ` +
          `spanning z${minZ}-z${maxZ}`,
      );
    }
  }

  // Without this the whole sweep could fall below the gate — every camera skipped, no violation
  // possible, and a green run that measured nothing.
  expect(
    inRegime,
    "too few cameras cleared the allowVariableZoom gate for this sweep to mean anything",
  ).toBeGreaterThan(500);

  expect(
    violations,
    "coveringTiles refined past the zoom it was asked for, which is what the vendored patch " +
      "exists to prevent — see vendoredPatches.test.ts for what the patch is and how to restore it",
  ).toEqual([]);
});
