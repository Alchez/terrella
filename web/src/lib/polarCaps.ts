// Polar caps (production; /globe?nocaps disables): the REAL bathymetry + sea-ice caps on the globe.
// Web-Mercator tiles die at ~85° (1/cos φ sends the pole to infinity), so each pole is an
// azimuthal-equidistant image built from source (pipeline/tile/cap_render.py → public/caps/*.webp),
// reaching ±90° with no hole.
//
// The pipeline is the single author of every value it renders into the textures: this layer
// FETCHES /caps/caps.json (edge_lat, the ±84 feather ceiling = shade_planet's Mercator plug
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

import { smallestRungAtLeast } from "./rungs";

export const RINGS = 28; // latitude subdivisions (mesh conforms to the sphere's curvature)
export const SECTORS = 160; // longitude subdivisions
const RADIUS = 1.0004; // a hair above the globe surface (radius 1) so it paints over the tiles
const FEATHER_LO = 81; // |lat| where the fade into the real tiles begins — frontend aesthetic
const MESH_EDGE_LAT = 80; // mesh equatorward edge, just outside the visible feather zone

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
}
export type CapsManifest = Record<"north" | "south", CapManifestEntry>;

/** The rung to FETCH for a device budget: the largest that fits, or the smallest shipped when
 *  none does. Choosing here rather than at upload is the whole point of the rung — a phone used
 *  to download the full 8192 texture and then canvas-downscale it to its budget, paying for
 *  every byte and every decoded pixel it threw away. Pure, so the tier rule is unit-testable. */
export function pickRung(rungs: CapRung[], budgetPx: number): CapRung {
  const ascending = [...rungs].sort((a, b) => a.px - b.px);
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
}

/** Manifest → the two caps' options. Pure, so the contract mapping is unit-testable. */
export function capOptionsFrom(manifest: CapsManifest, budgetPx: number = Infinity): CapOptions[] {
  return (["north", "south"] as const).map((name) => {
    const entry = manifest[name];
    const poleSign = Math.sign(entry.edge_lat);
    return {
      layerId: `polar-cap-${name}`,
      rungs: entry.rungs,
      budgetPx,
      poleLat: 90 * poleSign,
      latBottom: MESH_EDGE_LAT * poleSign,
      texEdgeLat: entry.edge_lat,
      featherLo: FEATHER_LO,
      featherHi: Math.abs(entry.feather_hi), // shader feathers on |lat|
    };
  });
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
 *  (measured 2026-07-25). Harmless at DPR 1, but ×3 it crosses into the 4096 rung, which would
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

/** UA-Client-Hints when the engine ships them (Chromium), else the coarse-pointer heuristic —
 *  which sweeps in tablets too, deliberately: they share the upload constraint. Guarded so the
 *  module stays importable in node (vitest). */
function isMobileClassDevice(): boolean {
  if (typeof navigator !== "undefined") {
    const uaData = (navigator as Navigator & { userAgentData?: { mobile?: boolean } })
      .userAgentData;
    if (typeof uaData?.mobile === "boolean") return uaData.mobile;
  }
  return typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;
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

const VERTEX_SRC = `#version 300 es
precision highp float;
uniform mat4 u_matrix;   // mainMatrix: unit-sphere → clip space
uniform vec4 u_clip;     // clippingPlane: the globe's horizon plane (unit-sphere space)
in vec3 a_pos;
in vec2 a_uv;
in float a_lat;
out vec2 v_uv;
out float v_clip;
out float v_lat;
void main() {
    v_uv = a_uv;
    v_lat = a_lat;
    v_clip = dot(u_clip.xyz, a_pos) + u_clip.w; // >0 near side / <0 far side
    gl_Position = u_matrix * vec4(a_pos, 1.0);
}`;

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
    // quantization then rendered as concentric contour arcs — THE polar ring (2026-07-22),
    // which tracked the cap↔tile boundary through the Antarctica re-fuse.
    float a = c.a * feather;
    fragColor = vec4(c.rgb * a, a);
}`;
}

/** Build a cap mesh: a (RINGS+1)×(SECTORS+1) grid from latBottom to the pole. Each vertex carries
 *  its unit-sphere position, its AEQD texture UV, and its signed latitude (for the feather). */
export function buildMesh(opts: CapOptions): { vertices: Float32Array; indices: Uint16Array } {
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
  return { vertices: new Float32Array(vertices), indices: new Uint16Array(indices) };
}

export interface CapLayer extends CustomLayerInterface {
  program?: WebGLProgram;
  vertexBuffer?: WebGLBuffer;
  indexBuffer?: WebGLBuffer;
  texture?: WebGLTexture;
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
    // eslint-disable-next-line no-console
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
 *  double-apply it — the same alpha chemistry as the 2026-07-22 polar ring.
 *
 *  Firefox does not implement the `premultiplyAlpha` member (WebIDL drops unimplemented
 *  dictionary members silently); that is safe here because the mesh only samples the cap's
 *  fully-opaque disc, where premultiplication state cannot show. If `createImageBitmap`
 *  itself rejects (older/exotic engines), fall back to the HTMLImageElement path — the
 *  original sync-decode route: slower, never wrong. Network errors propagate (no fallback
 *  that would mask a 404 as a decode problem). */
async function loadCapImage(url: string): Promise<ImageBitmap | HTMLImageElement> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const blob = await response.blob();
  try {
    return await createImageBitmap(blob, { premultiplyAlpha: "none" });
  } catch (decodeErr) {
    console.warn(`[caps] off-thread decode unavailable, using Image fallback`, decodeErr);
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error(`Image decode failed: ${url}`));
      image.src = url; // browser cache makes this a re-decode, not a re-download
    });
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
 *  camera", and that is exactly what the 2026-07-23 onAdd multiplier bug got wrong unobserved. */
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
    gl.bindTexture(gl.TEXTURE_2D, layer.texture!);
    uploadCapTexture(gl, bitmap);
    // Mipmapped minification, not plain LINEAR: at low zoom the cap shrinks ~100:1 on screen, and
    // bilinear sampling of 4 texels per ~40×40-texel block aliases the fine relief detail — on this
    // radial polar mapping the alias energy reads as CONCENTRIC RINGS around the pole, strongest
    // zoomed out and gone by ~z8 (diagnosed 2026-07-22 after every texture-side tone fix left the
    // ring visually unchanged).
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const size = bitmap.width; // read before close() — a closed bitmap reports 0×0
    if ("close" in bitmap) bitmap.close(); // release the decode — the GPU has its copy
    layer.loadedRungPx = rung.px; // only on success, so a failure can be retried by the next move
    map.triggerRepaint();
    // eslint-disable-next-line no-console
    console.log(`[caps] ${opts.layerId} texture loaded`, size, "x", size,
      `(demand ${Math.round(demandPx)} px)`);
  } catch (err: unknown) {
    console.error(`[caps] ${opts.layerId} texture failed`, rung.url, err);
  } finally {
    layer.rungLoading = undefined;
  }
}

/** The live `moveend` listener per cap, keyed by layer id.
 *
 *  A `moveend` listener is MAP state; a custom layer is STYLE state. A WebGL context loss destroys
 *  the style — so the layer object is discarded and rebuilt — while every `map.on` listener
 *  survives untouched. Without this registry each loss stranded a listener still closed over the
 *  dead layer, and because `rungLoading` is per-layer the strays could not even dedupe against the
 *  live one: every later upgrade was fetched once per stray. Measured live 2026-07-26 — one forced
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
      gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX_SRC));
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
      this.gl = gl;
      this.loadedRungPx = 0;
      void syncCapRung(this, opts, map); // the initial fetch IS the first upgrade, from 0
      // eslint-disable-next-line no-console
      console.log(`[caps] ${opts.layerId} added; mesh`, this.indexCount! / 3, "triangles");
    },

    render(glCtx: WebGL2RenderingContext | WebGLRenderingContext, args: CustomRenderMethodInput) {
      const gl = glCtx as WebGL2RenderingContext; // globe.astro's canvas is WebGL2 (capability probe)
      // Only meaningful in globe mode; on the flat Mercator map there is no pole to draw.
      if (args.defaultProjectionData.projectionTransition < 1) return;
      gl.useProgram(this.program!);
      gl.uniformMatrix4fv(this.uMatrix!, false, args.defaultProjectionData.mainMatrix);
      gl.uniform4f(this.uClip!, ...args.defaultProjectionData.clippingPlane);

      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture!);
      gl.uniform1i(this.uTex!, 0);

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
      // Premultiplied-color blend (pairs with the shader's premultiplied output), and the alpha
      // channel pinned to the DESTINATION: the old SRC_ALPHA blend also wrote α²+(1−α) into the
      // canvas's own alpha, making the map canvas translucent along the feather band — Chrome then
      // composited the dark starfield page through the globe there (the ring's second ingredient).
      gl.blendFuncSeparate(gl.ONE, gl.ONE_MINUS_SRC_ALPHA, gl.ZERO, gl.ONE);
      gl.drawElements(gl.TRIANGLES, this.indexCount!, gl.UNSIGNED_SHORT, 0);

      // Restore GL state (custom-layer contract): don't leak BLEND or the attrib arrays downstream.
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
 *  **THIS FUNCTION IS ALSO THE WEBGL CONTEXT-LOSS RECOVERY PATH — do not move its call site.**
 *  MapLibre recovers a lost context by re-applying a *serialized* style snapshot, and a `custom`
 *  layer has no serialized form. The library says so itself, by name, on every loss:
 *  `Custom layer with id 'polar-cap-north' cannot be restored after WebGL context loss.`
 *  The caps come back only because globe.astro calls this from `map.on("style.load")` and the
 *  restore's internal `setStyle` re-fires that event. Verified on the live site 2026-07-26: forced
 *  loss + restore, both warnings logged, globe visually identical afterwards.
 *  Rebinding this to a one-shot `load` handler would leave every recovered globe permanently
 *  capless, with no error — the map looks fine, the poles are just holes. A test guards the
 *  binding; the failure it prevents is silent, which is exactly why it is a test and not a note.
 *
 *  `cache: "no-cache"` (revalidate, don't skip the cache) is load-bearing, not caution. The
 *  manifest is a CONTRACT DOCUMENT, not an asset: the textures it names are content-addressed
 *  by size (cap_north_8192.webp), so a stale texture is impossible, but a stale manifest
 *  describes a world that no longer exists. Caught live 2026-07-25 — adding the rung list
 *  broke the caps on this very browser, which was holding a week-old manifest under the
 *  stores' 1-week cache class and reading `entry.rungs` as undefined. The failure is silent
 *  by design (capless globe, one console error), which is exactly why it must not be
 *  reachable. Cost is one conditional GET of ~500 bytes on an already-warm H2 connection. */
export async function addPolarCaps(map: MaplibreMap): Promise<void> {
  let manifest: CapsManifest;
  try {
    const response = await fetch("/caps/caps.json", { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    manifest = (await response.json()) as CapsManifest;
  } catch (err) {
    console.error("[caps] manifest fetch failed — globe renders capless", err);
    return;
  }
  for (const options of capOptionsFrom(manifest, capTextureBudget(isMobileClassDevice()))) {
    addPolarCap(map, options);
  }
}
