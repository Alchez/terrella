import { afterEach, describe, expect, it } from "vitest";
import * as maplibregl from "maplibre-gl";
import { mountGlobe, type MountedGlobe } from "./testing/mountGlobe";
import { attachTerrain } from "./attachTerrain";

const DEM_PROTOCOL = "attach-terrain-test";

/** Flat ground at 500 m in terrarium encoding (R*256 + G + B/256 - 32768), drawn here so the
 *  fixture carries no elevation data. */
let demTile: Promise<ArrayBuffer> | null = null;
function flatDemTile(): Promise<ArrayBuffer> {
  demTile ??= (async () => {
    const canvas = new OffscreenCanvas(256, 256);
    const context = canvas.getContext("2d");
    if (!context) throw new Error("no 2D context to draw the test DEM tile");
    context.fillStyle = "rgb(129, 244, 0)";
    context.fillRect(0, 0, 256, 256);
    return (await canvas.convertToBlob({ type: "image/png" })).arrayBuffer();
  })();
  return demTile;
}
maplibregl.addProtocol(DEM_PROTOCOL, async () => ({ data: (await flatDemTile()).slice(0) }));

const DEM_SOURCE: maplibregl.SourceSpecification = {
  type: "raster-dem",
  tiles: [`${DEM_PROTOCOL}://{z}/{x}/{y}`],
  encoding: "terrarium",
  tileSize: 256,
  maxzoom: 6,
};

type Drape = { texture: { texture: WebGLTexture } } | null;
type TerrainInternals = {
  painter: { context: { gl: WebGL2RenderingContext } };
  terrain: { tileManager: { _tiles: Record<string, { rttObjects: Drape[] }> } } | null;
};

/** Drapes the terrain's tiles hold, and how many of those point at a texture the current context
 *  does not own, which is what a drape kept across a context loss does. */
function drapes(map: maplibregl.Map): { held: number; dead: number } {
  const internals = map as unknown as TerrainInternals;
  const gl = internals.painter.context.gl;
  let held = 0;
  let dead = 0;
  for (const tile of Object.values(internals.terrain?.tileManager._tiles ?? {})) {
    for (const drape of tile.rttObjects) {
      if (!drape) continue;
      held++;
      if (!gl.isTexture(drape.texture.texture)) dead++;
    }
  }
  return { held, dead };
}

function next(map: maplibregl.Map, type: "idle" | "webglcontextlost", label: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`no ${type} within 30 s ${label}`)), 30_000);
    map.once(type, () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

/** A globe with terrain under a drapeable layer, settled, with drapes held. */
async function mountWithTerrain(globe: MountedGlobe, exaggeration: number): Promise<void> {
  const { map } = globe;
  map.jumpTo({ center: [10, 46], zoom: 4, pitch: 50 });
  map.addLayer({ id: "ground", type: "background", paint: { "background-color": "#c8a27a" } });
  const settled = next(map, "idle", "after the terrain was attached");
  attachTerrain(map, DEM_SOURCE, exaggeration);
  await settled;
  const before = drapes(map);
  expect(before.held, "the terrain holds no drapes, so a restore has nothing to break").toBeGreaterThan(0);
  expect(before.dead).toBe(0);
}

async function loseAndRestore(map: maplibregl.Map): Promise<void> {
  const gl = (map as unknown as TerrainInternals).painter.context.gl;
  const extension = gl.getExtension("WEBGL_lose_context");
  if (!extension) throw new Error("no WEBGL_lose_context in this runner");
  const lost = next(map, "webglcontextlost", "after loseContext()");
  extension.loseContext();
  await lost;
  // Called from inside the lost event's dispatch, where this await resumes, restoreContext() never
  // restores in this runner, and the test times out waiting for idle.
  await new Promise((resolve) => setTimeout(resolve, 300));
  const settled = next(map, "idle", "after restoreContext()");
  extension.restoreContext();
  await settled;
}

let globe: MountedGlobe | null = null;
afterEach(() => {
  globe?.dispose();
  globe = null;
});

describe("terrain after a WebGL context restore", () => {
  it("comes back from the page's style.load handler with live drapes and its last exaggeration", async () => {
    globe = await mountGlobe();
    const { map } = globe;
    let exaggeration = 3;
    await mountWithTerrain(globe, exaggeration);
    const thrown: unknown[] = [];
    map.on("style.load", () => {
      try {
        attachTerrain(map, DEM_SOURCE, exaggeration);
      } catch (error) {
        thrown.push(error);
      }
    });
    // What the page's zoom ramp does between style loads: the live value moves off the spec's.
    exaggeration = 4;
    if (map.terrain) map.terrain.exaggeration = exaggeration;

    await loseAndRestore(map);

    expect.soft(thrown.map((error) => String(error))).toEqual([]);
    const after = drapes(map);
    expect.soft(after.held).toBeGreaterThan(0);
    expect.soft(after.dead, "drapes pointing at textures from the lost context").toBe(0);
    expect.soft(map.terrain?.exaggeration).toBe(exaggeration);
  }, 90_000);

  // The canary for the workaround in attachTerrain. MapLibre 6.x keeps the old terrain across a
  // context loss and destroys it into the restored painter's drape pool, so the new terrain's tiles
  // draw with dead textures. When this goes red, MapLibre restores terrain cleanly on its own and
  // attachTerrain's setTerrain(null) can go.
  it("still comes back with dead drapes when MapLibre restores it alone", async () => {
    globe = await mountGlobe();
    await mountWithTerrain(globe, 3);

    await loseAndRestore(globe.map);

    expect(drapes(globe.map).dead).toBeGreaterThan(0);
  }, 90_000);
});
