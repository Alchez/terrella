// FEASIBILITY SPIKE → 2a integration (still behind /globe?polarspike): draws the REAL bathymetry
// polar cap on the globe. The cap texture is an azimuthal-equidistant image built from source
// (scratchpad/cap_render.py → public/dev-assets/cap_north.png), reaching 90°N with no hole.
//
// Geometry: a tessellated mesh on the unit sphere (LAT_BOTTOM→pole) placed via
// args.defaultProjectionData.mainMatrix — the manual path, because Mercator/projectTile can't
// reach the pole. UVs map each vertex to its AEQD position in the texture (AEQD radius is LINEAR
// in colatitude, so it matches a (90−lat) radial law). The seam is feathered by latitude, and the
// cap is culled behind the globe's horizon via clippingPlane.
//
// Removed once the real cap layer is productionised.

import type { CustomLayerInterface, CustomRenderMethodInput, Map as MaplibreMap } from "maplibre-gl";

const LAT_BOTTOM = 80; // mesh covers LAT_BOTTOM°N → 90°N (the pole)
const TEX_EDGE_LAT = 78; // latitude at the texture's inscribed circle — MUST match cap_render.py
const RINGS = 28; // latitude subdivisions (mesh conforms to the sphere's curvature)
const SECTORS = 160; // longitude subdivisions
const RADIUS = 1.0004; // a hair above the globe surface (radius 1) so it paints over the tiles
const TEXTURE_URL = "/dev-assets/cap_north.png";

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

// Feather: opaque above 84°N (covers the flat Mercator cap), fading to transparent by 81°N so the
// cap dissolves into the real tiles instead of ending in a ring.
const FRAGMENT_SRC = `#version 300 es
precision highp float;
uniform sampler2D u_tex;
in vec2 v_uv;
in float v_clip;
in float v_lat;
out vec4 fragColor;
void main() {
    if (v_clip < 0.0) discard;              // drop the cap where it is behind the globe's horizon
    vec4 c = texture(u_tex, v_uv);
    float feather = smoothstep(81.0, 84.0, v_lat);
    fragColor = vec4(c.rgb, c.a * feather);
}`;

/** Build the cap mesh: a (RINGS+1)×(SECTORS+1) grid from LAT_BOTTOM to the pole. Each vertex carries
 *  its unit-sphere position, its AEQD texture UV, and its latitude (for the feather). */
function buildMesh(): { vertices: Float32Array; indices: Uint16Array } {
  const vertices: number[] = [];
  for (let ring = 0; ring <= RINGS; ring++) {
    const lat = LAT_BOTTOM + ((90 - LAT_BOTTOM) * ring) / RINGS;
    const uvRadius = (90 - lat) / (90 - TEX_EDGE_LAT); // AEQD: radius ∝ colatitude
    for (let sector = 0; sector <= SECTORS; sector++) {
      const lng = -180 + (360 * sector) / SECTORS;
      const lngRad = (lng * Math.PI) / 180;
      const [x, y, z] = spherePosition(lng, lat);
      // AEQD north (matches cap_render.py): x = ρ·sin(lng), y = −ρ·cos(lng); image row 0 is +y (top),
      // uploaded un-flipped so texture v=0 is the top → u = 0.5+0.5·r·sin, v = 0.5+0.5·r·cos.
      const u = 0.5 + 0.5 * uvRadius * Math.sin(lngRad);
      const v = 0.5 + 0.5 * uvRadius * Math.cos(lngRad);
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

interface SpikeLayer extends CustomLayerInterface {
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

/** Register the cap as a `custom` layer on the (already-loaded) map. */
export function addPolarCapSpike(map: MaplibreMap): void {
  if (map.getLayer("polar-cap-spike")) return; // idempotent — style.load can fire more than once
  const layer: SpikeLayer = {
    id: "polar-cap-spike",
    type: "custom",
    renderingMode: "2d", // paint-over, no depth fight; drawn last so it sits above the tiles

    onAdd(_map, gl: WebGL2RenderingContext) {
      const program = gl.createProgram()!;
      gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX_SRC));
      gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SRC));
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

      const { vertices, indices } = buildMesh();
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
        console.log("[polarspike] cap texture loaded", image.width, "x", image.height);
      };
      image.onerror = () => console.error("[polarspike] cap texture failed to load", TEXTURE_URL);
      image.src = TEXTURE_URL;
      // eslint-disable-next-line no-console
      console.log("[polarspike] layer added; cap mesh", this.indexCount! / 3, "triangles");
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

      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.drawElements(gl.TRIANGLES, this.indexCount!, gl.UNSIGNED_SHORT, 0);
    },
  };
  map.addLayer(layer);
}
