import * as maplibregl from "maplibre-gl";
// v6 resolves its worker at runtime from `import.meta.url`, which does not survive bundling. The
// page hits the same problem and solves it the same way — `?worker&url` emits one self-contained
// asset and hands back its hashed href. Kept identical to `globe.astro` on purpose: a fixture that
// wires MapLibre up differently from the page is testing a configuration nobody ships.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

/**
 * Mount a real MapLibre globe in the browser test project.
 *
 * NO SOURCES, AND THAT IS THE DESIGN. The assertions this exists for are camera-derived — the
 * scale ruler unprojects two screen points, the hover chip queries rendered features — and the
 * camera is fully real with zero tiles loaded. Wiring the fixture to the local asset stores would
 * make it unrunnable on CI and couple every future test to a multi-gigabyte archive being present
 * on the machine. A test that genuinely needs features should add an inline GeoJSON source of its
 * own, which is hermetic and states its own fixture data.
 *
 * The container is sized EXPLICITLY. A MapLibre map in a zero-height element builds a transform
 * that projects every ground point onto one screen point, so every geometric assertion above it
 * would pass by collapsing rather than by agreeing.
 */

/** Default viewport. Wide enough that two ruler sample points are far apart in ground terms. */
export const FIXTURE_WIDTH_PX = 800;
export const FIXTURE_HEIGHT_PX = 600;

export interface MountedGlobe {
  map: maplibregl.Map;
  container: HTMLDivElement;
  /** Release the WebGL context and detach the container. Must run in an `afterEach`. */
  dispose: () => void;
}

export interface MountGlobeOptions {
  zoom?: number;
  center?: [number, number];
  width?: number;
  height?: number;
}

let workerUrlSet = false;

/**
 * The style the fixture mounts: globe projection, nothing drawn.
 *
 * `projection` is declared IN THE STYLE rather than via `setProjection` after load, because that is
 * how the page declares it and the two paths differ in when the transform becomes a globe.
 */
function emptyGlobeStyle(): maplibregl.StyleSpecification {
  return { version: 8, projection: { type: "globe" }, sources: {}, layers: [] };
}

export async function mountGlobe(options: MountGlobeOptions = {}): Promise<MountedGlobe> {
  if (!workerUrlSet) {
    maplibregl.setWorkerUrl(maplibreWorkerUrl);
    workerUrlSet = true;
  }

  const container = document.createElement("div");
  container.style.width = `${options.width ?? FIXTURE_WIDTH_PX}px`;
  container.style.height = `${options.height ?? FIXTURE_HEIGHT_PX}px`;
  // Out of the way of anything else a test has mounted, and never affected by page flow.
  container.style.position = "fixed";
  container.style.top = "0";
  container.style.left = "0";
  document.body.appendChild(container);

  // PRE-FLIGHT, so a GL-less runner says so instead of timing out. MapLibre's own failure here is
  // late and indirect, and on CI a bare "test timed out" would send the next reader looking at the
  // assertions rather than at the browser. Measured on the binary CI installs
  // (`playwright install --only-shell chromium`, HeadlessChrome/151): WebGL2 is present and backed
  // by SwiftShader through ANGLE/Vulkan — software, deterministic, and exactly what we want here.
  if (!document.createElement("canvas").getContext("webgl2")) {
    container.remove();
    throw new Error(
      "no WebGL2 context in this runner — the globe fixture cannot mount. " +
        "Check the browser binary supports GL (CI: playwright install --only-shell chromium).",
    );
  }

  const map = new maplibregl.Map({
    container,
    style: emptyGlobeStyle(),
    center: options.center ?? [0, 0],
    zoom: options.zoom ?? 2,
    // Deterministic geometry: no inertial drift between an action and the assertion after it.
    fadeDuration: 0,
    attributionControl: false,
  });

  await new Promise<void>((resolve, reject) => {
    map.once("load", () => resolve());
    // Without this a WebGL failure in the runner surfaces as a bare timeout, which reads as "the
    // test is slow" rather than "this environment has no GL".
    map.once("error", (event) => reject(event.error ?? new Error("map failed to load")));
  });

  return {
    map,
    container,
    dispose: () => {
      map.remove();
      container.remove();
    },
  };
}
