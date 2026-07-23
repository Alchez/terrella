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

export const RINGS = 28; // latitude subdivisions (mesh conforms to the sphere's curvature)
export const SECTORS = 160; // longitude subdivisions
const RADIUS = 1.0004; // a hair above the globe surface (radius 1) so it paints over the tiles
const FEATHER_LO = 81; // |lat| where the fade into the real tiles begins — frontend aesthetic
const MESH_EDGE_LAT = 80; // mesh equatorward edge, just outside the visible feather zone

/** One cap's entry in the pipeline-emitted /caps/caps.json contract. */
export interface CapManifestEntry {
  url: string;
  edge_lat: number; // texture inscribed-circle latitude, signed (cap_render CapGrid.edge_lat)
  feather_hi: number; // signed |lat| where the cap goes opaque (shade_planet CAP_NORTH/CAP_SOUTH)
  px: number;
}
export type CapsManifest = Record<"north" | "south", CapManifestEntry>;

/** Per-cap parameters (internal; built from the manifest by capOptionsFrom). */
export interface CapOptions {
  layerId: string;
  textureUrl: string;
  poleLat: number; // +90 (north) or −90 (south)
  latBottom: number; // mesh equatorward edge, signed
  texEdgeLat: number; // texture inscribed-circle latitude, signed
  featherLo: number; // |lat| where alpha starts rising from 0 (into the real tiles)
  featherHi: number; // |lat| where alpha reaches 1 (poleward, over the flat Mercator plug)
}

/** Manifest → the two caps' options. Pure, so the contract mapping is unit-testable. */
export function capOptionsFrom(manifest: CapsManifest): CapOptions[] {
  return (["north", "south"] as const).map((name) => {
    const entry = manifest[name];
    const poleSign = Math.sign(entry.edge_lat);
    return {
      layerId: `polar-cap-${name}`,
      textureUrl: entry.url,
      poleLat: 90 * poleSign,
      latBottom: MESH_EDGE_LAT * poleSign,
      texEdgeLat: entry.edge_lat,
      featherLo: FEATHER_LO,
      featherHi: Math.abs(entry.feather_hi), // shader feathers on |lat|
    };
  });
}

/** GPU texture-size clamp: mobile GPUs commonly cap MAX_TEXTURE_SIZE at 4096–8192, and an
 *  oversized upload fails silently to black. The 8192² production caps downscale on such
 *  devices rather than vanish. */
export function clampedTextureSize(imageSize: number, maxTextureSize: number): number {
  return Math.min(imageSize, maxTextureSize);
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

interface CapLayer extends CustomLayerInterface {
  program?: WebGLProgram;
  vertexBuffer?: WebGLBuffer;
  indexBuffer?: WebGLBuffer;
  texture?: WebGLTexture;
  indexCount?: number;
  aPos?: number;
  aUv?: number;
  aLat?: number;
  uMatrix?: WebGLUniformLocation | null;
  uClip?: WebGLUniformLocation | null;
  uTex?: WebGLUniformLocation | null;
}

/** Upload the cap image, downscaling through a canvas when it exceeds MAX_TEXTURE_SIZE. */
function uploadCapTexture(gl: WebGL2RenderingContext, image: ImageBitmap | HTMLImageElement): void {
  const maxSize = gl.getParameter(gl.MAX_TEXTURE_SIZE) as number;
  const target = clampedTextureSize(image.width, maxSize);
  if (target < image.width) {
    const canvas = document.createElement("canvas");
    canvas.width = target;
    canvas.height = target;
    canvas.getContext("2d")!.drawImage(image, 0, 0, target, target);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, canvas);
    // eslint-disable-next-line no-console
    console.log(`[caps] texture ${image.width} clamped to ${target} (MAX_TEXTURE_SIZE ${maxSize})`);
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

/** Register one cap as a `custom` layer on the (already-loaded) map. */
function addPolarCap(map: MaplibreMap, opts: CapOptions): void {
  if (map.getLayer(opts.layerId)) return; // idempotent — style.load can fire more than once
  const layer: CapLayer = {
    id: opts.layerId,
    type: "custom",
    renderingMode: "2d", // paint-over, no depth fight; drawn last so it sits above the tiles

    onAdd(_map, gl: WebGL2RenderingContext) {
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
      void loadCapImage(opts.textureUrl)
        .then((bitmap) => {
          gl.bindTexture(gl.TEXTURE_2D, this.texture!);
          uploadCapTexture(gl, bitmap);
          // Mipmapped minification, not plain LINEAR: at low zoom the cap shrinks ~100:1 on
          // screen, and bilinear sampling of 4 texels per ~40×40-texel block aliases the fine relief
          // detail — on this radial polar mapping the alias energy reads as CONCENTRIC RINGS around
          // the pole, strongest zoomed out and gone by ~z8 (diagnosed 2026-07-22 after every
          // texture-side tone fix left the ring visually unchanged).
          gl.generateMipmap(gl.TEXTURE_2D);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
          const size = bitmap.width; // read before close() — a closed bitmap reports 0×0
          if ("close" in bitmap) bitmap.close(); // release the ~268 MB decode — the GPU has its copy
          map.triggerRepaint();
          // eslint-disable-next-line no-console
          console.log(`[caps] ${opts.layerId} texture loaded`, size, "x", size);
        })
        .catch((err: unknown) =>
          console.error(`[caps] ${opts.layerId} texture failed`, opts.textureUrl, err),
        );
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
  };
  map.addLayer(layer);
}

/** Fetch the pipeline's caps.json contract and register both polar caps on the loaded map.
 *  A missing/invalid manifest logs and leaves the globe capless — never breaks the page. */
export async function addPolarCaps(map: MaplibreMap): Promise<void> {
  let manifest: CapsManifest;
  try {
    const response = await fetch("/caps/caps.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    manifest = (await response.json()) as CapsManifest;
  } catch (err) {
    console.error("[caps] manifest fetch failed — globe renders capless", err);
    return;
  }
  for (const options of capOptionsFrom(manifest)) {
    addPolarCap(map, options);
  }
}
