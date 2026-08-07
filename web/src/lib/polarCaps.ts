// Polar caps (production; /earth?nocaps disables): the REAL bathymetry + sea-ice caps on the globe.
// Web-Mercator tiles die at ~85° (1/cos φ sends the pole to infinity), so each pole is an
// azimuthal-equidistant image built from source (pipeline/tile/cap_render.py → public/caps/*.webp),
// reaching ±90° with no hole.
//
// The pipeline is the single author of every value it renders into the textures: this layer
// FETCHES this body's caps.json (edge_lat, the ±84 feather ceiling = shade_planet's Mercator plug
// boundary, texture URLs) instead of hand-copying them as literals — the copy-drift species that
// bit the hero/tile colour constants four times. Only frontend aesthetics stay here (FEATHER_LO,
// mesh extent, tessellation).
//
// Geometry: a tessellated mesh on the unit sphere (latBottom → pole) placed via
// args.defaultProjectionData.mainMatrix — the manual path, because Mercator/projectTile can't
// reach the pole. UVs map each vertex to its AEQD position in the texture (AEQD radius is LINEAR
// in colatitude, so it matches a (90−|lat|) radial law). The seam is feathered by latitude, and the
// cap is culled behind the globe's horizon via clippingPlane.
//
// One factory drives BOTH poles: `poleSign` flips the pole vertex, the v/cos handedness (the south
// AEQD winds the opposite way, y = +ρ·cos), and the feather latitude.

import type { CustomLayerInterface, CustomRenderMethodInput, Map as MaplibreMap } from "maplibre-gl";

import { capsManifestUrl } from "./assetBase";
import type { BodySlug } from "./bodies";
import { smallestRungAtLeast } from "./rungs";
// `perfSpans`, NOT anything in `lib/perf/`: a static import from there would place the whole
// instrument directory in the main chunk, which is how 268 lines once shipped to every visitor.
// `beginSpan` is a no-op returning a shared no-op function until `?perf` arms it.
import { beginSpan } from "./perfSpans";

/** Latitude subdivisions (the mesh conforms to the sphere's curvature).
 *
 *  Was 28x160 while the cap was a FLAT disc, where tessellation bought nothing but a rounder
 *  silhouette. Once the mesh displaces, every vertex is a sample of the terrain and the count is
 *  the cap's entire vertical resolution: at 28 rings the 10-degree mesh band is ~40 km per ring,
 *  against ~1-2 km on the terrain-displaced tiles it crossfades into, so the two surfaces would
 *  ghost apart across the feather however exactly they agree in metres.
 *
 *  160x640 gives ~7 km rings and ~11 km sectors at the mesh edge (the widest they get), which
 *  sits just under the elevation texture's 5.2 km/px — so the MESH is the limit and the texture
 *  is not the thing to spend on. Cost is 103,201 vertices and 4.9 MB of buffers per cap, and it
 *  lands on mobile with everything else. This is the knob to judge the look on. */
export const RINGS = 160;
/** Longitude subdivisions. See RINGS.
 *
 *  These two together are what pushed the index buffer past 65,535 — see buildMesh. */
export const SECTORS = 640;
const RADIUS = 1.0004; // a hair above the globe surface (radius 1) so it paints over the tiles
export const FEATHER_LO = 81; // |lat| where the fade into the real tiles begins — frontend aesthetic
export const MESH_EDGE_LAT = 80; // mesh equatorward edge, just outside the visible feather zone
// Equals cap_render.CAP_EDGE_LAT, the texture disc's inscribed circle: the mesh samples nothing
// outside the disc, so lowering MESH_EDGE_LAT below the served `edge_lat` reads past the texture.
// `asserts the cap latitude ladder` in polarCaps.test.ts pins the whole chain against caps.json.

/** MapLibre's own globe radius in metres, from its `_projection.vertex.glsl`:
 *  `#define GLOBE_RADIUS 6371008.8`, used as `spherePos * (1.0 + elevation / GLOBE_RADIUS)`.
 *
 *  NOT `cap_render.SPHERE_R` (6371000.0), which is the AEQD projection radius the texture's UV law
 *  assumes. Two radii doing two jobs, 8.8 m apart: collapsing them would put the cap that far off
 *  the tiles it blends into. The pipeline's constant carries the same warning from its side. */
export const MAPLIBRE_GLOBE_RADIUS_M = 6371008.8;

/** Terrarium's zero point — `terrain_rgb.BASE_SHIFT`, and MapLibre's hard-coded `baseShift`. */
const ELEVATION_BASE_SHIFT = 32768;

/** One shipped texture size for a cap (cap_render CAP_RUNGS). */
export interface CapRung {
  px: number;
  url: string;
}

/** One cap's entry in the pipeline-emitted /caps/caps.json contract. */
export interface CapManifestEntry {
  rungs: CapRung[]; // ascending by px; every rung is the same picture, downsampled
  edge_lat: number; // texture inscribed-circle latitude, signed (cap_render CapGrid.edge_lat)
  feather_hi: number; // signed |lat| where the cap goes opaque (shade_planet CAP_NORTH/CAP_SOUTH)
  elev_url: string; // terrain-RGB displacement texture (cap_render cap_elev_asset)
  elev_step: number; // metres per encoded level (cap_render reads terrain_rgb.QUANTISATION_M)
}
/** The two poles, in the order their caps are added. */
export const CAP_POLES = ["north", "south"] as const;

export type CapPole = (typeof CAP_POLES)[number];

/** The style layer id for a pole's cap.
 *
 *  One spelling of the string, because it is now a HANDLE and not just a label: `glDiagnostics`
 *  looks caps up by id to read the texture rung resident on the GPU at the moment a context is
 *  lost. A second module retyping `polar-cap-north` would work right up until this one changed. */
export function capLayerId(pole: CapPole): string {
  return `polar-cap-${pole}`;
}

export type CapsManifest = Record<CapPole, CapManifestEntry>;

/** The rung to FETCH for a device budget: the largest that fits, or the smallest shipped when
 *  none does. Choosing here rather than at upload is the whole point of the rung — a phone used
 *  to download the full 8192 texture and then canvas-downscale it to its budget, paying for
 *  every byte and every decoded pixel it threw away. Pure, so the tier rule is unit-testable. */
export function pickRung(rungs: CapRung[], budgetPx: number): CapRung {
  const ascending = [...rungs].toSorted((a, b) => a.px - b.px);
  const withinBudget = ascending.filter((rung) => rung.px <= budgetPx);
  return withinBudget.length ? withinBudget[withinBudget.length - 1] : ascending[0];
}

/** Per-cap parameters (internal; built from the manifest by capOptionsFrom). Carries the whole
 *  rung list rather than one resolved URL: which rung this cap needs is a function of the CAMERA,
 *  which changes after the layer is built. */
export interface CapOptions {
  layerId: string;
  rungs: CapRung[];
  budgetPx: number; // upload ceiling for this device class; never exceeded however close the camera
  poleLat: number; // +90 (north) or −90 (south)
  latBottom: number; // mesh equatorward edge, signed
  texEdgeLat: number; // texture inscribed-circle latitude, signed
  featherLo: number; // |lat| where alpha starts rising from 0 (into the real tiles)
  featherHi: number; // |lat| where alpha reaches 1 (poleward, over the flat Mercator plug)
  elevUrl: string; // displacement texture, one size (the mesh samples it far coarser than it is)
  elevStep: number; // metres per encoded level, from the pipeline that packed the bytes
}

/** Manifest → the two caps' options. Pure, so the contract mapping is unit-testable. */
export function capOptionsFrom(manifest: CapsManifest, budgetPx: number = Infinity): CapOptions[] {
  return CAP_POLES.map((pole) => {
    const entry = manifest[pole];
    const poleSign = Math.sign(entry.edge_lat);
    return {
      layerId: capLayerId(pole),
      rungs: entry.rungs,
      budgetPx,
      poleLat: 90 * poleSign,
      latBottom: MESH_EDGE_LAT * poleSign,
      texEdgeLat: entry.edge_lat,
      featherLo: FEATHER_LO,
      featherHi: Math.abs(entry.feather_hi), // shader feathers on |lat|
      elevUrl: entry.elev_url,
      elevStep: entry.elev_step,
    };
  });
}

/** Metres from one terrain-RGB texel's bytes, in the exact form MapLibre's own `custom` encoding
 *  applies it: `R*(256*step) + G*step + B*0 - baseShift`. Blue is zeroed by the pipeline (its
 *  1/256 m fraction is noise at this resolution), so it is absent here rather than multiplied by
 *  zero — a term that must never contribute is clearer as a term that is not written.
 *
 *  Exported because the shader cannot be unit-tested and this is the arithmetic that matters: the
 *  GLSL below is generated from the same constants, so a test can pin both against one another. */
export function decodeCapElevation(red: number, green: number, stepMetres: number): number {
  return red * 256 * stepMetres + green * stepMetres - ELEVATION_BASE_SHIFT;
}

/** The factor a unit-sphere vertex is scaled by to sit at its true elevation — MapLibre's
 *  `1.0 + elevation / GLOBE_RADIUS`, with `elevation` already exaggerated (its terrain shader
 *  receives the exaggerated value, so the multiply belongs on this side of the divide too).
 *
 *  At exaggeration 0 this is EXACTLY 1.0, and a multiply by exactly 1.0 is exact in IEEE754 — so
 *  a flat globe reproduces the pre-displacement vertex bit-for-bit rather than approximately. That
 *  is what makes `?terrain=off` and the degradation rung honest controls rather than a third
 *  slightly-different rendering. */
export function capDisplacementScale(elevationMetres: number, exaggeration: number): number {
  return 1 + (elevationMetres * exaggeration) / MAPLIBRE_GLOBE_RADIUS_M;
}

/** Canvas alpha after the cap paints over it: the premultiplied "over" the blend implements,
 *  `src + dst*(1 - src)`.
 *
 *  Written down because both of this layer's compositing bugs were alpha bugs, in opposite
 *  directions, and each fix looked safe until the other regime appeared:
 *    - dst = 1 (the flat globe, where the background layer has already filled the frame): the
 *      result is identically 1 for every src, so nothing can make the canvas translucent. That is
 *      the polar-ring failure, and it is now impossible rather than avoided.
 *    - dst = 0 (with terrain on, poleward of the Mercator limit, where nothing has drawn): the
 *      result is src, so an opaque cap yields an opaque canvas. That is the bright-disc failure —
 *      leaving alpha at 0 made the browser add the cap's colour to the page behind it. */
export function compositedAlpha(sourceAlpha: number, destinationAlpha: number): number {
  return sourceAlpha + destinationAlpha * (1 - sourceAlpha);
}

/** The RGBA byte quadruple that decodes to exactly 0 m at this step — the placeholder the
 *  elevation texture holds until the real one arrives.
 *
 *  A transparent-black 1x1 (what the colour texture uses) would be catastrophic here: it decodes
 *  to -32768 m, which at 15x shrinks the cap to 92% of the globe radius and drops it INSIDE the
 *  planet for however many frames the fetch takes. Zero is the only safe initial elevation, and it
 *  is step-dependent, so it is computed rather than written as bytes. */
export function zeroElevationTexel(stepMetres: number): Uint8Array {
  const packed = Math.round(ELEVATION_BASE_SHIFT / stepMetres);
  return new Uint8Array([(packed >> 8) & 0xff, packed & 0xff, 0, 255]);
}

/** Longitude step for the extent sample. 5° = 72 points around the parallel; finer steps move the
 *  measured extent by well under 1%, and this runs on every `moveend`. */
const EXTENT_SAMPLE_STEP_DEG = 5;

export interface ScreenPoint {
  x: number;
  y: number;
}

/** Great-circle angular distance in degrees — used only to ask "is this point on the near side?" */
function angularDistanceDeg(fromLngLat: [number, number], toLngLat: [number, number]): number {
  const toRad = Math.PI / 180;
  const [lngA, latA] = fromLngLat;
  const [lngB, latB] = toLngLat;
  const cosDistance =
    Math.sin(latA * toRad) * Math.sin(latB * toRad) +
    Math.cos(latA * toRad) * Math.cos(latB * toRad) * Math.cos((lngB - lngA) * toRad);
  return Math.acos(Math.min(1, Math.max(-1, cosDistance))) / toRad;
}

/** How large this cap draws on screen right now, in CSS px: the bounding box of its
 *  inscribed-circle parallel plus the pole.
 *
 *  Only FRONT-FACING samples count (angular distance from the camera centre < 90°). MapLibre's
 *  `project()` answers for points behind the globe too — projected through the sphere — so a cap on
 *  the far side reports a bounded but non-zero box that SATURATES near 970 px however far you zoom
 *  (measured). Harmless at DPR 1, but ×3 it crosses into the 4096 rung, which would
 *  fetch a megabyte of texture for a cap the viewer cannot see. Returns 0 when the cap is entirely
 *  behind the globe, which reads as "needs nothing". */
export function capProjectedExtentPx(
  project: (lngLat: [number, number]) => ScreenPoint,
  centerLngLat: [number, number],
  edgeLat: number,
  poleLat: number,
): number {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  let sampled = 0;
  const consider = (lngLat: [number, number]): void => {
    if (angularDistanceDeg(centerLngLat, lngLat) >= 90) return; // behind the globe
    const { x, y } = project(lngLat);
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
    sampled++;
  };
  for (let lng = -180; lng < 180; lng += EXTENT_SAMPLE_STEP_DEG) consider([lng, edgeLat]);
  consider([0, poleLat]);
  return sampled === 0 ? 0 : Math.max(maxX - minX, maxY - minY);
}

/** The canvas's REAL device-pixel ratio, read from the backing store rather than
 *  `window.devicePixelRatio`. That way the FPS watchdog's `setPixelRatio(1)` lowers cap demand for
 *  free: a degraded canvas genuinely has fewer pixels to fill, so it should also pull less texture. */
export function canvasBackingRatio(canvas: { width: number; clientWidth: number }): number {
  return canvas.clientWidth > 0 ? canvas.width / canvas.clientWidth : 1;
}

/** The rung to load for a measured device-pixel demand: the smallest that covers it, then clamped
 *  to the device's upload budget. Composed from the two existing pickers rather than a third rule —
 *  `smallestRungAtLeast` states the requirement, `pickRung` enforces the ceiling. */
export function rungForDemand(rungs: CapRung[], demandPx: number, budgetPx: number): CapRung {
  const wanted = smallestRungAtLeast(rungs.map((rung) => rung.px), demandPx);
  return pickRung(rungs, Math.min(wanted, budgetPx));
}

/** GPU texture-size clamp: the upload target is the smallest of the image itself, the GPU's
 *  MAX_TEXTURE_SIZE (an oversized upload fails silently to black — weak mobile GPUs cap at
 *  4096–8192), and the device budget (below). */
export function clampedTextureSize(
  imageSize: number,
  maxTextureSize: number,
  deviceBudgetSize: number = Infinity,
): number {
  return Math.min(imageSize, maxTextureSize, deviceBudgetSize);
}

/** The mobile texture rung. Phones can RESOLVE 8192 zoomed to a pole (their physical pixel
 *  counts rival desktops), so this is a quality↔cost tier, not a resolvability limit: a full
 *  8192² upload pushes ~268 MB of texels through texImage2D on exactly the thread phones are
 *  slowest at — a prime suspect in the OnePlus first-load jank. 4096 quarters the upload and
 *  is the rung the cap A/B already judged (the pre-8192 candidate), so mobile ships a look
 *  that was ratified, just not the top rung. */
export const MOBILE_CAP_BUDGET_PX = 4096;

/** Budget by device class — pure, so the tier rule is unit-testable. */
export function capTextureBudget(isMobileClass: boolean): number {
  return isMobileClass ? MOBILE_CAP_BUDGET_PX : Infinity;
}

/** Which signal produced a device-class verdict. `no-signal` is not a synonym for desktop: it is
 *  the honest reading when neither source exists, and it is reported rather than folded into the
 *  boolean because a false from no evidence and a false from a measurement are different facts. */
export type DeviceClassSignal = "ua-client-hints" | "pointer-coarse" | "no-signal";

export interface DeviceClass {
  mobileClass: boolean;
  via: DeviceClassSignal;
}

/**
 * The device-class rule, with its inputs injected so it is testable without stubbing globals.
 *
 * UA-Client-Hints wins when the engine ships them (Chromium, including Brave); everything else
 * falls through to the coarse-pointer heuristic, which sweeps in tablets too — deliberately, since
 * they share the upload constraint. The two arms disagreeing is normal and is exactly why `via` is
 * carried: the same phone reports through different signals in different browsers, so a capture
 * that does not name the signal cannot be compared with one taken elsewhere.
 */
export function classifyDevice(
  uaMobile: boolean | undefined,
  pointerCoarse: boolean | undefined,
): DeviceClass {
  if (typeof uaMobile === "boolean") return { mobileClass: uaMobile, via: "ua-client-hints" };
  if (typeof pointerCoarse === "boolean") {
    return { mobileClass: pointerCoarse, via: "pointer-coarse" };
  }
  return { mobileClass: false, via: "no-signal" };
}

/** The live verdict. Guarded so the module stays importable in node (vitest). */
export function deviceClass(): DeviceClass {
  const uaData =
    typeof navigator === "undefined"
      ? undefined
      : (navigator as Navigator & { userAgentData?: { mobile?: boolean } }).userAgentData;
  const pointerCoarse =
    typeof matchMedia === "function" ? matchMedia("(pointer: coarse)").matches : undefined;
  return classifyDevice(uaData?.mobile, pointerCoarse);
}

export function isMobileClassDevice(): boolean {
  return deviceClass().mobileClass;
}

/** Unit-sphere position for a lng/lat, in MapLibre's globe convention (North Pole = (0, 1, 0)). */
function spherePosition(lngDeg: number, latDeg: number): [number, number, number] {
  const lng = (lngDeg * Math.PI) / 180;
  const lat = (latDeg * Math.PI) / 180;
  const cosLat = Math.cos(lat);
  return [RADIUS * cosLat * Math.sin(lng), RADIUS * Math.sin(lat), RADIUS * cosLat * Math.cos(lng)];
}

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type)!;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error("[caps] shader compile failed: " + gl.getShaderInfoLog(shader));
  }
  return shader;
}

/** Vertex shader for one cap: lift each vertex to its true elevation, then project.
 *
 *  THE CAP CANNOT INHERIT DISPLACEMENT, WHICH IS WHY THIS EXISTS. MapLibre drapes a layer onto the
 *  terrain mesh only if its type is in `LAYERS_TO_TEXTURES` (render_to_texture.ts) — background,
 *  fill, line, raster, hillshade, color-relief. `custom` is not among them and cannot be, so while
 *  every tile around the cap rose with the terrain the cap stayed pinned at sea level: the flat,
 *  brighter disc with a hard edge, at both poles, found on the live site.
 *
 *  The step and the radius are INTERPOLATED FROM CONSTANTS rather than written as GLSL literals —
 *  the step from the manifest (the pipeline packed these bytes, so the pipeline states how to read
 *  them) and the radius from MAPLIBRE_GLOBE_RADIUS_M. That keeps this shader and the exported pure
 *  functions above the same statement of the same arithmetic, which is the only way a test can
 *  reach it.
 *
 *  `textureLod(..., 0.0)` and not `texture(...)`: implicit derivatives do not exist in a vertex
 *  shader, so the mip level has to be stated. The sampler is NEAREST for a reason that is not
 *  performance — see loadCapElevation. */
export function vertexSrc(opts: CapOptions): string {
  return `#version 300 es
precision highp float;
uniform mat4 u_matrix;   // mainMatrix: unit-sphere → clip space
uniform vec4 u_clip;     // clippingPlane: the globe's horizon plane (unit-sphere space)
uniform sampler2D u_elev;      // terrain-RGB displacement texture, same AEQD framing as the colour
uniform float u_exaggeration;  // map.terrain.exaggeration, live; 0 when terrain is off
in vec3 a_pos;
in vec2 a_uv;
in float a_lat;
out vec2 v_uv;
out float v_clip;
out float v_lat;
void main() {
    v_uv = a_uv;
    v_lat = a_lat;
    vec4 texel = textureLod(u_elev, a_uv, 0.0) * 255.0;   // normalized [0,1] back to bytes
    // 256.0 is the encoding's radix (red is the high byte) — structural, not a knob; the step and
    // the base shift are the knobs, and both come from constants.
    float metres = (texel.r * 256.0 + texel.g) * ${opts.elevStep.toFixed(6)}
                 - ${ELEVATION_BASE_SHIFT.toFixed(1)};
    vec3 pos = a_pos * (1.0 + metres * u_exaggeration / ${MAPLIBRE_GLOBE_RADIUS_M.toFixed(1)});
    // The horizon test uses the DISPLACED position, deliberately: a peak near the limb genuinely
    // does clear the horizon plane a flat vertex would sit behind, and testing the undisplaced
    // point would clip it while the tiles beside it stayed visible.
    v_clip = dot(u_clip.xyz, pos) + u_clip.w; // >0 near side / <0 far side
    gl_Position = u_matrix * vec4(pos, 1.0);
}`;
}

/** Fragment shader for one cap: sample the AEQD texture, feather by |lat| (poleSign·v_lat maps both
 *  poles' signed latitude to |lat|), cull behind the globe's horizon. */
function fragmentSrc(opts: CapOptions): string {
  const poleSign = Math.sign(opts.poleLat).toFixed(1);
  return `#version 300 es
precision highp float;
uniform sampler2D u_tex;
in vec2 v_uv;
in float v_clip;
in float v_lat;
out vec4 fragColor;
void main() {
    if (v_clip < 0.0) discard;              // drop the cap where it is behind the globe's horizon
    vec4 c = texture(u_tex, v_uv);
    float absLat = ${poleSign} * v_lat;     // |lat| for either pole
    float feather = smoothstep(${opts.featherLo.toFixed(1)}, ${opts.featherHi.toFixed(1)}, absLat);
    // PREMULTIPLIED output — the custom-layer contract: MapLibre's framebuffer holds
    // premultiplied colors. The straight-alpha vec4(c.rgb, a) + SRC_ALPHA blending violated it
    // and painted a brighter-than-both-layers swell along the feather band, which 8-bit
    // quantization then rendered as concentric contour arcs — THE polar ring,
    // which tracked the cap↔tile boundary through the Antarctica re-fuse.
    float a = c.a * feather;
    fragColor = vec4(c.rgb * a, a);
}`;
}

/** Build a cap mesh: a (RINGS+1)×(SECTORS+1) grid from latBottom to the pole. Each vertex carries
 *  its unit-sphere position, its AEQD texture UV, and its signed latitude (for the feather).
 *
 *  INDICES ARE 32-BIT, and that is a consequence of displacement rather than a preference. The
 *  tessellation the flat disc needed (28x160 = 4,669 vertices) fits a Uint16Array with room to
 *  spare; the tessellation the displaced cap needs (160x640 = 103,201) does not, and a 16-bit
 *  index buffer does not fail on overflow — it WRAPS, so vertex 65,536 becomes vertex 0 and the
 *  mesh folds through the pole while still drawing happily. WebGL2 has UNSIGNED_INT indices in
 *  core (no OES_element_index_uint to probe), so the only thing this costs is the draw call
 *  agreeing with it — see the `gl.UNSIGNED_INT` in `render`. */
export function buildMesh(opts: CapOptions): { vertices: Float32Array; indices: Uint32Array } {
  const poleSign = Math.sign(opts.poleLat);
  const texColat = 90 - Math.abs(opts.texEdgeLat); // colatitude at the texture's inscribed circle
  const vertices: number[] = [];
  for (let ring = 0; ring <= RINGS; ring++) {
    const lat = opts.latBottom + ((opts.poleLat - opts.latBottom) * ring) / RINGS;
    const uvRadius = (90 - Math.abs(lat)) / texColat; // AEQD: radius ∝ colatitude
    for (let sector = 0; sector <= SECTORS; sector++) {
      const lng = -180 + (360 * sector) / SECTORS;
      const lngRad = (lng * Math.PI) / 180;
      const [x, y, z] = spherePosition(lng, lat);
      // AEQD (matches cap_render.py): x = ρ·sin(lng); y = −ρ·cos(lng) north / +ρ·cos(lng) south.
      // image row 0 is +y (top), uploaded un-flipped so texture v=0 is the top → the v/cos term
      // carries poleSign (north +cos, south −cos); u is the same for both.
      const u = 0.5 + 0.5 * uvRadius * Math.sin(lngRad);
      const v = 0.5 + 0.5 * poleSign * uvRadius * Math.cos(lngRad);
      vertices.push(x, y, z, u, v, lat);
    }
  }
  const indices: number[] = [];
  const stride = SECTORS + 1;
  for (let ring = 0; ring < RINGS; ring++) {
    for (let sector = 0; sector < SECTORS; sector++) {
      const a = ring * stride + sector;
      const b = a + 1;
      const c = a + stride;
      const d = c + 1;
      indices.push(a, c, b, b, c, d);
    }
  }
  return { vertices: new Float32Array(vertices), indices: new Uint32Array(indices) };
}

export interface CapLayer extends CustomLayerInterface {
  program?: WebGLProgram;
  vertexBuffer?: WebGLBuffer;
  indexBuffer?: WebGLBuffer;
  texture?: WebGLTexture;
  /** Displacement texture. Separate from `texture` and not a rung: one size, fetched once. */
  elevTexture?: WebGLTexture;
  /** True once the real elevation image has replaced the zero-metre placeholder. */
  elevLoaded?: boolean;
  indexCount?: number;
  /** Captured in onAdd so `moveend` can upload without a render pass. Safe to hold, but NOT for
   *  the reason this comment used to give. It claimed "a real context loss re-runs onAdd" — true
   *  in effect, wrong in mechanism, and the wrong mechanism is the dangerous part. MapLibre does
   *  not re-run `onAdd` on a surviving layer: it rebuilds the style from a serialized snapshot,
   *  which cannot carry a `custom` layer, so THIS OBJECT IS DISCARDED and `addPolarCaps` builds a
   *  new one against the new context. Holding `gl` is safe because the object never outlives its
   *  context — see the recovery contract on `addPolarCaps`. */
  gl?: WebGL2RenderingContext;
  /** Rung currently ON the GPU. 0 until the first load lands, so the initial fetch is simply the
   *  first upgrade — one code path, not two that can drift. */
  loadedRungPx?: number;
  /** Rung being fetched right now, if any. A fast zoom fires many `moveend`s; without this the
   *  cap would start a second 5 MB fetch before the first arrived. */
  rungLoading?: number;
  aPos?: number;
  aUv?: number;
  aLat?: number;
  uMatrix?: WebGLUniformLocation | null;
  uClip?: WebGLUniformLocation | null;
  uTex?: WebGLUniformLocation | null;
  uElev?: WebGLUniformLocation | null;
  uExaggeration?: WebGLUniformLocation | null;
}

/** Upload the cap image, downscaling through a canvas when it exceeds the GPU's limit or the
 *  device budget. Since the fetch already picks a rung within the device budget, this is now a
 *  BACKSTOP, not the normal path — it still earns its place because `MAX_TEXTURE_SIZE` is a
 *  per-GPU fact no manifest can predict (an oversized upload fails silently to black). */
function uploadCapTexture(gl: WebGL2RenderingContext, image: ImageBitmap | HTMLImageElement): void {
  const maxSize = gl.getParameter(gl.MAX_TEXTURE_SIZE) as number;
  const budget = capTextureBudget(isMobileClassDevice());
  const target = clampedTextureSize(image.width, maxSize, budget);
  if (target < image.width) {
    const canvas = document.createElement("canvas");
    canvas.width = target;
    canvas.height = target;
    canvas.getContext("2d")!.drawImage(image, 0, 0, target, target);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, canvas);
    console.log(
      `[caps] texture ${image.width} downscaled to ${target} ` +
        `(MAX_TEXTURE_SIZE ${maxSize}, device budget ${budget})`,
    );
  } else {
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
  }
}

/** Decode a cap image OFF the main thread. `texImage2D` on an HTMLImageElement forces a
 *  synchronous main-thread decode — measured 396 ms per 8192² cap (≈800 ms of first-load
 *  stall across both poles); `createImageBitmap` moves that to Chrome's worker pool, leaving
 *  only the ~117 ms GPU upload on the main thread. `premultiplyAlpha: "none"` is load-bearing:
 *  the fragment shader premultiplies in-shader, and a premultiply at decode time would
 *  double-apply it — the same alpha chemistry as the polar ring.
 *
 *  Firefox does not implement the `premultiplyAlpha` member (WebIDL drops unimplemented
 *  dictionary members silently); that is safe here because the mesh only samples the cap's
 *  fully-opaque disc, where premultiplication state cannot show. If `createImageBitmap`
 *  itself rejects (older/exotic engines), fall back to the HTMLImageElement path — the
 *  original sync-decode route: slower, never wrong. Network errors propagate (no fallback
 *  that would mask a 404 as a decode problem). */
async function loadCapImage(
  url: string,
  options: ImageBitmapOptions = { premultiplyAlpha: "none" },
): Promise<ImageBitmap | HTMLImageElement> {
  // `caps:fetch` is mostly network WAIT, not main thread — which is the point of pricing spans
  // against long-task windows rather than reporting their wall clock as a cost. A 900 ms fetch that
  // blocks nothing attributes ~0 ms, and that is the correct answer.
  const endFetch = beginSpan("caps:fetch");
  let blob: Blob;
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    blob = await response.blob();
  } finally {
    endFetch();
  }
  const endDecode = beginSpan("caps:decode");
  try {
    return await createImageBitmap(blob, options);
  } catch (decodeErr) {
    console.warn(`[caps] off-thread decode unavailable, using Image fallback`, decodeErr);
    // `return await`, not `return`: inside try/finally an un-awaited promise closes the span the
    // moment it is CONSTRUCTED, so the fallback — the slow, synchronous-decode path this span most
    // needs to catch — would be recorded as taking no time at all.
    return await new Promise<HTMLImageElement>((resolve, reject) => {
      const image = new Image();
      // `addEventListener` over `onload =` even though this Image is local and nothing else can
      // assign to it: the assignment form is only safe while that stays true, and the day this
      // element is hoisted or shared, a second handler silently replaces the first with nothing
      // reporting it. `once` because a settled promise ignores the second call anyway.
      image.addEventListener("load", () => resolve(image), { once: true });
      image.addEventListener(
        "error",
        () => reject(new Error(`Image decode failed: ${url}`)),
        { once: true },
      );
      image.src = url; // browser cache makes this a re-decode, not a re-download
    });
  } finally {
    endDecode();
  }
}

/** Bring this cap's texture up to the rung the current camera needs, if that is bigger than what is
 *  already on the GPU. Both the first load and every later upgrade go through here, so there is one
 *  fetch/upload path rather than two that can drift apart.
 *
 *  It only ever goes UP. Downgrading on zoom-out would save nothing (the bytes are already spent and
 *  cached) and would cost a second decode plus a visible softening, so a session pays for the
 *  sharpest view it actually asked for and nothing more.
 *
 *  Exported only as a test seam: its whole contract is "how many uploads, of which rung, under which
 *  camera", and that is exactly what the onAdd multiplier bug got wrong unobserved. */
export async function syncCapRung(
  layer: CapLayer,
  opts: CapOptions,
  map: MaplibreMap,
): Promise<void> {
  const gl = layer.gl;
  if (!gl || layer.rungLoading !== undefined) return;
  const center = map.getCenter();
  const extentPx = capProjectedExtentPx(
    (lngLat) => map.project(lngLat),
    [center.lng, center.lat],
    opts.texEdgeLat,
    opts.poleLat,
  );
  const demandPx = extentPx * canvasBackingRatio(map.getCanvas());
  const rung = rungForDemand(opts.rungs, demandPx, opts.budgetPx);
  if (rung.px <= (layer.loadedRungPx ?? 0)) return;

  layer.rungLoading = rung.px;
  try {
    const bitmap = await loadCapImage(rung.url);
    // Synchronous GL, so no try/finally: if either throws, the outer catch handles it and the span
    // simply records nothing — which is the honest outcome, since the work did not complete.
    const endUpload = beginSpan("caps:upload");
    gl.bindTexture(gl.TEXTURE_2D, layer.texture!);
    uploadCapTexture(gl, bitmap);
    endUpload();
    // Mipmapped minification, not plain LINEAR: at low zoom the cap shrinks ~100:1 on screen, and
    // bilinear sampling of 4 texels per ~40×40-texel block aliases the fine relief detail — on this
    // radial polar mapping the alias energy reads as CONCENTRIC RINGS around the pole, strongest
    // zoomed out and gone by ~z8 (diagnosed after every texture-side tone fix left the
    // ring visually unchanged).
    const endMipmap = beginSpan("caps:mipmap");
    gl.generateMipmap(gl.TEXTURE_2D);
    endMipmap();
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const size = bitmap.width; // read before close() — a closed bitmap reports 0×0
    if ("close" in bitmap) bitmap.close(); // release the decode — the GPU has its copy
    layer.loadedRungPx = rung.px; // only on success, so a failure can be retried by the next move
    map.triggerRepaint();
    console.log(`[caps] ${opts.layerId} texture loaded`, size, "x", size,
      `(demand ${Math.round(demandPx)} px)`);
  } catch (err: unknown) {
    console.error(`[caps] ${opts.layerId} texture failed`, rung.url, err);
  } finally {
    layer.rungLoading = undefined;
  }
}

/** Fetch this cap's displacement texture and replace the zero-metre placeholder. Once, not per
 *  camera: it ships in one size because the mesh samples it far coarser than it is stored.
 *
 *  NEAREST FILTERING IS CORRECTNESS, NOT A PERFORMANCE CHOICE, and it is the single easiest thing
 *  to get wrong here. These texels are not colour: elevation is `(R*256 + G) * step`, so the green
 *  byte WRAPS every 256 levels — 2,048 m at our step. Bilinear filtering across a wrap interpolates
 *  R=16,G=255 with R=17,G=0 and produces R≈16.5,G≈127.5, which decodes about 1 km away from either
 *  neighbour: a phantom cliff, in the middle of a smooth slope, with nothing on screen to say why.
 *  The pipeline refuses the same operation on its side (write_cap_elevation downsamples in metres
 *  and never in encoded bytes; the tile pyramid cuts every zoom with `nearest`). This is that rule
 *  reaching the GPU, which is the last place it can be broken.
 *
 *  No mipmaps for the same reason — a mip chain is an average of encoded bytes — and none are
 *  needed: the vertex shader states `textureLod(..., 0.0)` and nothing samples this per fragment.
 *
 *  `colorSpaceConversion: "none"` asks the decoder not to touch the bytes. It is a request, not a
 *  guarantee (an engine that does not implement the member drops it silently, exactly as Firefox
 *  does with `premultiplyAlpha`), so it is a cheap extra defence rather than the reason this works:
 *  a WebP with no embedded profile has nothing to convert from. */
export async function loadCapElevation(
  layer: CapLayer,
  opts: CapOptions,
  map: MaplibreMap,
): Promise<void> {
  const gl = layer.gl;
  if (!gl || layer.elevLoaded) return;
  // Deliberately ENCLOSES the `caps:fetch`/`caps:decode` spans inside `loadCapImage`. Nested spans
  // are correct here and cannot double-count: each span's own total is wall clock, while the share
  // of blocked time is computed from the UNION of all span intervals.
  const endElev = beginSpan("caps:elev");
  try {
    const bitmap = await loadCapImage(opts.elevUrl, {
      premultiplyAlpha: "none",
      colorSpaceConversion: "none",
    });
    gl.bindTexture(gl.TEXTURE_2D, layer.elevTexture!);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bitmap);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const size = bitmap.width;
    if ("close" in bitmap) bitmap.close();
    layer.elevLoaded = true;
    map.triggerRepaint();
    console.log(`[caps] ${opts.layerId} elevation loaded`, size, "x", size,
      `(${opts.elevStep} m/level)`);
  } catch (err: unknown) {
    // The cap stays FLAT rather than disappearing — the placeholder decodes to 0 m, so a failed
    // fetch degrades to exactly the pre-displacement behaviour instead of collapsing the mesh.
    console.error(`[caps] ${opts.layerId} elevation failed`, opts.elevUrl, err);
  } finally {
    endElev();
  }
}

/** The live `moveend` listener per cap, keyed by layer id.
 *
 *  A `moveend` listener is MAP state; a custom layer is STYLE state. A WebGL context loss destroys
 *  the style — so the layer object is discarded and rebuilt — while every `map.on` listener
 *  survives untouched. Without this registry each loss stranded a listener still closed over the
 *  dead layer, and because `rungLoading` is per-layer the strays could not even dedupe against the
 *  live one: every later upgrade was fetched once per stray. Measured — one forced
 *  loss, one camera move, `cap_north_4096.webp` requested TWICE. It compounds at N+1 fetches after
 *  N losses, and it is invisible on screen because the winning upload is correct either way. */
const capMoveHandlers = new Map<string, () => void>();

/** Register one cap as a `custom` layer on the (already-loaded) map. */
export function addPolarCap(map: MaplibreMap, opts: CapOptions): void {
  if (map.getLayer(opts.layerId)) return; // idempotent — style.load can fire more than once
  let onMoveEnd: (() => void) | undefined;
  const layer: CapLayer = {
    id: opts.layerId,
    type: "custom",
    renderingMode: "2d", // paint-over, no depth fight; drawn last so it sits above the tiles

    onAdd(_map, gl: WebGL2RenderingContext) {
      // MapLibre re-invokes onAdd on every projection transition (globe ⇄ mercator — bursts
      // of up to 5 during page load). A naive re-init recompiled the shaders, rebuilt the
      // mesh, re-fetched + re-decoded the texture, and re-pushed the ~268 MB texImage2D
      // upload — while orphaning the previous GL objects. Desktop shrugged; on phones those
      // stacked uploads were a prime suspect in the first-load jank. The GL context SURVIVES
      // projection transitions, so if our program is still valid in this context every other
      // resource on the layer is too — skip the whole re-init. gl.isProgram goes false
      // exactly when a rebuild is genuinely needed (a fresh context after loss/swap).
      if (this.program && gl.isProgram(this.program)) return;
      const program = gl.createProgram()!;
      gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, vertexSrc(opts)));
      gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, fragmentSrc(opts)));
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        throw new Error("[caps] link failed: " + gl.getProgramInfoLog(program));
      }
      this.program = program;
      this.aPos = gl.getAttribLocation(program, "a_pos");
      this.aUv = gl.getAttribLocation(program, "a_uv");
      this.aLat = gl.getAttribLocation(program, "a_lat");
      this.uMatrix = gl.getUniformLocation(program, "u_matrix");
      this.uClip = gl.getUniformLocation(program, "u_clip");
      this.uTex = gl.getUniformLocation(program, "u_tex");
      this.uElev = gl.getUniformLocation(program, "u_elev");
      this.uExaggeration = gl.getUniformLocation(program, "u_exaggeration");

      const { vertices, indices } = buildMesh(opts);
      this.indexCount = indices.length;
      this.vertexBuffer = gl.createBuffer()!;
      gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);
      this.indexBuffer = gl.createBuffer()!;
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);

      // Texture: a transparent 1×1 placeholder until the AEQD cap image loads asynchronously.
      this.texture = gl.createTexture()!;
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE,
        new Uint8Array([0, 0, 0, 0]));

      // Elevation: a 1x1 placeholder that decodes to ZERO METRES, not to transparent black. The
      // colour texture's placeholder is invisible; this one is geometry, and the wrong bytes here
      // put the cap 32 km inside the planet until the fetch lands (zeroElevationTexel).
      this.elevTexture = gl.createTexture()!;
      gl.bindTexture(gl.TEXTURE_2D, this.elevTexture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE,
        zeroElevationTexel(opts.elevStep));
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);

      this.gl = gl;
      this.loadedRungPx = 0;
      this.elevLoaded = false;
      void syncCapRung(this, opts, map); // the initial fetch IS the first upgrade, from 0
      void loadCapElevation(this, opts, map);
      console.log(`[caps] ${opts.layerId} added; mesh`, this.indexCount! / 3, "triangles");
    },

    render(glCtx: WebGL2RenderingContext | WebGLRenderingContext, args: CustomRenderMethodInput) {
      const gl = glCtx as WebGL2RenderingContext; // earth.astro's canvas is WebGL2 (capability probe)
      // Only meaningful in globe mode; on the flat Mercator map there is no pole to draw.
      if (args.defaultProjectionData.projectionTransition < 1) return;
      gl.useProgram(this.program!);
      gl.uniformMatrix4fv(this.uMatrix!, false, args.defaultProjectionData.mainMatrix);
      gl.uniform4f(this.uClip!, ...args.defaultProjectionData.clippingPlane);

      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture!);
      gl.uniform1i(this.uTex!, 0);
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, this.elevTexture!);
      gl.uniform1i(this.uElev!, 1);

      // ONE source of truth for exaggeration, read live every frame. `map.terrain` is the object
      // the ramp writes (earth.astro mutates `terrain.exaggeration` on zoom rather than re-calling
      // setTerrain, which would leak framebuffers), so `map.getTerrain()` — the spec handed in
      // once — goes stale after the first ramp step and must not be used here. Absent terrain
      // gives 0, which makes `capDisplacementScale` exactly 1.0: `?terrain=off`, the Globe tier
      // and the FPS watchdog's disable-terrain rung all flatten the cap for free, with no wiring.
      gl.uniform1f(this.uExaggeration!, map.terrain?.exaggeration ?? 0);

      gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer!);
      gl.enableVertexAttribArray(this.aPos!);
      gl.vertexAttribPointer(this.aPos!, 3, gl.FLOAT, false, 24, 0);
      gl.enableVertexAttribArray(this.aUv!);
      gl.vertexAttribPointer(this.aUv!, 2, gl.FLOAT, false, 24, 12);
      gl.enableVertexAttribArray(this.aLat!);
      gl.vertexAttribPointer(this.aLat!, 1, gl.FLOAT, false, 24, 20);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer!);

      const blendWas = gl.isEnabled(gl.BLEND);
      gl.enable(gl.BLEND);
      // Premultiplied "over", on ALL FOUR channels — the alpha factors are the colour factors, not
      // a separate rule. This is THE BRIGHT POLAR DISC, and the disc was a compositing bug rather
      // than the geometry bug it looked like.
      //
      // The alpha channel used to be pinned to the destination (`ZERO, ONE`), to stop a
      // straight-alpha shader writing α²+(1−α) into the canvas and making it translucent along the
      // feather band. That was the right fix for the wrong layer of the problem: the shader now
      // emits PREMULTIPLIED colour, for which `ONE, ONE_MINUS_SRC_ALPHA` on alpha is the exact
      // over-composite — `dst = src + dst*(1-src)` is identically 1 wherever dst was already 1, so
      // it cannot bring that translucency back (compositedAlpha states the algebra, with a test).
      //
      // What "don't touch alpha" could not survive was TERRAIN. `background` is in MapLibre's
      // LAYERS_TO_TEXTURES, so with terrain on the space-floor is drawn INTO each render tile's
      // texture instead of as a full-screen pass — and render tiles stop at the Mercator limit.
      // Poleward of ±85.0511° the canvas is therefore never written at all: alpha 0. The cap then
      // painted its colour there and left the 0 in place, and a `premultipliedAlpha: true` canvas
      // composites RGB-over-zero-alpha ADDITIVELY — the page's dark starfield plus a near-white
      // cap. Measured: alpha steps 255 to 0 at exactly -85.02° with terrain on, and stays 255 to
      // the pole with `?terrain=off`, which is why the disc only ever appeared on one arm.
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      gl.drawElements(gl.TRIANGLES, this.indexCount!, gl.UNSIGNED_INT, 0); // 32-bit — see buildMesh

      // Restore GL state (custom-layer contract): don't leak BLEND or the attrib arrays downstream.
      // The active texture unit is part of that contract too: leaving TEXTURE1 selected would send
      // MapLibre's next bind to the wrong unit.
      gl.activeTexture(gl.TEXTURE0);
      gl.disableVertexAttribArray(this.aPos!);
      gl.disableVertexAttribArray(this.aUv!);
      gl.disableVertexAttribArray(this.aLat!);
      if (!blendWas) gl.disable(gl.BLEND);
    },

    /** Documented only for `Map.removeLayer`, so it is a bonus path and not the one the registry
     *  above relies on — a style destroyed by context loss may never call this. */
    onRemove(removedFrom: MaplibreMap) {
      if (!onMoveEnd) return;
      removedFrom.off("moveend", onMoveEnd);
      // Clear the registry only if this layer's handler is still the registered one. A re-add may
      // already have replaced it, and deleting that entry would disable rung upgrades silently.
      if (capMoveHandlers.get(opts.layerId) === onMoveEnd) capMoveHandlers.delete(opts.layerId);
    },
  };
  map.addLayer(layer);
  // Re-evaluate once the camera settles, not on every frame of a drag: the check is cheap (72
  // projections) but a fetch is not, and an in-flight zoom has no stable answer to give.
  const stranded = capMoveHandlers.get(opts.layerId);
  if (stranded) map.off("moveend", stranded);
  onMoveEnd = () => void syncCapRung(layer, opts, map);
  capMoveHandlers.set(opts.layerId, onMoveEnd);
  map.on("moveend", onMoveEnd);
}

/** Fetch the pipeline's caps.json contract and register both polar caps on the loaded map.
 *  A missing/invalid manifest logs and leaves the globe capless — never breaks the page.
 *
 *  THE BODY IS A REQUIRED ARGUMENT AND THE MANIFEST URL IS DERIVED FROM IT. It used to be the
 *  literal `/caps/caps.json`, which was correct while one planet had caps and is the worst kind of
 *  wrong the moment a second one does: Earth's path prefix is empty, so that literal is not a URL
 *  that fails for another body — it is Earth's manifest, served with a 200, naming Earth's Arctic
 *  textures. The globe would draw sea ice and Greenland over another planet's pole and log nothing.
 *  `capsManifestUrl` reads the prefix off the registry, which `tests/test_bodies.py` holds against
 *  the pipeline that writes the files.
 *
 *  The textures are NOT re-addressed here. Every rung URL and the elevation URL come out of the
 *  manifest already absolute, which is what keeps this module ignorant of the served layout.
 *
 *  **THIS FUNCTION IS ALSO THE WEBGL CONTEXT-LOSS RECOVERY PATH — do not move its call site.**
 *  MapLibre recovers a lost context by re-applying a *serialized* style snapshot, and a `custom`
 *  layer has no serialized form. The library says so itself, by name, on every loss:
 *  `Custom layer with id 'polar-cap-north' cannot be restored after WebGL context loss.`
 *  The caps come back only because earth.astro calls this from `map.on("style.load")` and the
 *  restore's internal `setStyle` re-fires that event. Verified on the live site: forced
 *  loss + restore, both warnings logged, globe visually identical afterwards.
 *  Rebinding this to a one-shot `load` handler would leave every recovered globe permanently
 *  capless, with no error — the map looks fine, the poles are just holes. A test guards the
 *  binding; the failure it prevents is silent, which is exactly why it is a test and not a note.
 *
 *  `cache: "no-cache"` (revalidate, don't skip the cache) is load-bearing, not caution. The
 *  manifest is a CONTRACT DOCUMENT, not an asset: the textures it names are content-addressed
 *  by size (cap_north_8192.webp), so a stale texture is impossible, but a stale manifest
 *  describes a world that no longer exists. Caught — adding the rung list
 *  broke the caps on this very browser, which was holding a week-old manifest under the
 *  stores' 1-week cache class and reading `entry.rungs` as undefined. The failure is silent
 *  by design (capless globe, one console error), which is exactly why it must not be
 *  reachable. Cost is one conditional GET of ~500 bytes on an already-warm H2 connection. */
export async function addPolarCaps(map: MaplibreMap, body: BodySlug): Promise<void> {
  let manifest: CapsManifest;
  const manifestUrl = capsManifestUrl(body);
  try {
    const response = await fetch(manifestUrl, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    manifest = (await response.json()) as CapsManifest;
  } catch (err) {
    // The URL is in the message because the interesting failure is not "the fetch broke" but "the
    // fetch went to the wrong planet's manifest", and those two are indistinguishable without it.
    console.error(`[caps] manifest fetch failed (${manifestUrl}) — globe renders capless`, err);
    return;
  }
  for (const options of capOptionsFrom(manifest, capTextureBudget(isMobileClassDevice()))) {
    addPolarCap(map, options);
  }
}
