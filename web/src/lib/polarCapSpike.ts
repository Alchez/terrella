// Polar caps (behind /globe?polarspike): draws the REAL bathymetry + sea-ice caps on the globe.
// Web-Mercator tiles die at ~85° (1/cos φ sends the pole to infinity), so each pole is an
// azimuthal-equidistant image built from source (pipeline/tile/cap_render.py →
// public/dev-assets/cap_{north,south}.png), reaching ±90° with no hole.
//
// Geometry: a tessellated mesh on the unit sphere (latBottom → pole) placed via
// args.defaultProjectionData.mainMatrix — the manual path, because Mercator/projectTile can't
// reach the pole. UVs map each vertex to its AEQD position in the texture (AEQD radius is LINEAR
// in colatitude, so it matches a (90−|lat|) radial law). The seam is feathered by latitude, and the
// cap is culled behind the globe's horizon via clippingPlane.
//
// One factory drives BOTH poles: `poleSign` flips the pole vertex, the v/cos handedness (the south
// AEQD winds the opposite way, y = +ρ·cos), and the feather latitude. NORTH is the small ~78° cap
// the Mercator tiles reach; SOUTH is the big −55°→−90° Antarctica cap (the fused planet stops at
// −60, so its texture is GEBCO-direct — see cap_render.py). Removed once the caps are productionised.

import type { CustomLayerInterface, CustomRenderMethodInput, Map as MaplibreMap } from "maplibre-gl";

const RINGS = 28; // latitude subdivisions (mesh conforms to the sphere's curvature)
const SECTORS = 160; // longitude subdivisions
const RADIUS = 1.0004; // a hair above the globe surface (radius 1) so it paints over the tiles

/** Per-cap parameters. `texEdgeLat` MUST equal the matching cap_render.py CapGrid `edge_lat`. */
interface CapOptions {
  layerId: string;
  textureUrl: string;
  poleLat: number; // +90 (north) or −90 (south)
  latBottom: number; // mesh equatorward edge, signed (just outside the visible feather zone)
  texEdgeLat: number; // texture inscribed-circle latitude, signed — MUST match cap_render.py
  featherLo: number; // |lat| where alpha starts rising from 0 (into the real tiles)
  featherHi: number; // |lat| where alpha reaches 1 (poleward, over the flat Mercator plug)
}

const NORTH_CAP: CapOptions = {
  layerId: "polar-cap-north",
  textureUrl: "/dev-assets/cap_north.png",
  poleLat: 90,
  latBottom: 80, // mesh 80°N → 90°N
  texEdgeLat: 78, // cap_render.py NORTH edge_lat
  featherLo: 81,
  featherHi: 84, // opaque above 84°N (covers the flat Mercator cap), transparent by 81°N
};

const SOUTH_CAP: CapOptions = {
  layerId: "polar-cap-south",
  textureUrl: "/dev-assets/cap_south.png",
  poleLat: -90,
  latBottom: -56.5, // mesh 56.5°S → 90°S (just equatorward of the feather, inside the texture)
  texEdgeLat: -55, // cap_render.py SOUTH edge_lat
  featherLo: 57,
  // Opaque poleward of 59.5°S, aligned EXACTLY to shade_planet CAP_SOUTH = −59.5 (where the pale
  // Mercator plug begins), so that bright plug never bleeds through a partly-transparent cap as a
  // halo ring — the north does the same (featherHi 84 == CAP_NORTH 84). Transparent by 57°S.
  featherHi: 59.5,
};

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
    throw new Error("[polarspike] shader compile failed: " + gl.getShaderInfoLog(shader));
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
    v_clip = dot(u_clip.xyz, a_pos) + u_clip.w; // >0 near side / <0 far side (verify the sign)
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
    fragColor = vec4(c.rgb, c.a * feather);
}`;
}

/** Build a cap mesh: a (RINGS+1)×(SECTORS+1) grid from latBottom to the pole. Each vertex carries
 *  its unit-sphere position, its AEQD texture UV, and its signed latitude (for the feather). */
function buildMesh(opts: CapOptions): { vertices: Float32Array; indices: Uint16Array } {
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
        throw new Error("[polarspike] link failed: " + gl.getProgramInfoLog(program));
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
      const image = new Image();
      image.onload = () => {
        gl.bindTexture(gl.TEXTURE_2D, this.texture!);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        map.triggerRepaint();
        // eslint-disable-next-line no-console
        console.log(`[polarspike] ${opts.layerId} texture loaded`, image.width, "x", image.height);
      };
      image.onerror = () => console.error(`[polarspike] ${opts.layerId} texture failed`, opts.textureUrl);
      image.src = opts.textureUrl;
      // eslint-disable-next-line no-console
      console.log(`[polarspike] ${opts.layerId} added; mesh`, this.indexCount! / 3, "triangles");
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
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
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

/** Register both polar caps (north + south) on the already-loaded map. */
export function addPolarCaps(map: MaplibreMap): void {
  addPolarCap(map, NORTH_CAP);
  addPolarCap(map, SOUTH_CAP);
}
