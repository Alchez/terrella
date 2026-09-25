import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  renderableTerrainTiles,
  rttHeldBy,
  rttPoolLine,
  rttPoolOf,
  trackRttPool,
  type RttObject,
} from "./rttPool";

/** A pooled object that records whether its texture was destroyed. */
type LoggedObject = RttObject & { texture: { destroy(): void } };

const object = (): RttObject => ({ size: 512 });

function pool(count: number, log: string[] = []): LoggedObject[] {
  return Array.from({ length: count }, (_, index) => ({
    size: 512,
    texture: { destroy: () => log.push(`obj${index}`) },
  }));
}

/** Terrain tiles holding `count` objects between them. */
const tilesHolding = (count: number) => ({
  a: { rttObjects: Array.from({ length: count }, () => object()) },
});

/** The narrowest map that can answer the renderable-tile question, and nothing else. */
const mapWithRenderable = (keys: string[]) => ({
  terrain: { tileManager: { _renderableTilesKeys: keys } },
});

/** Minimal stand-in for the private MapLibre surface this module reads. */
function fakeMap(options: { pool?: RttObject[]; tiles?: Record<string, { rttObjects?: (RttObject | undefined)[] }> } = {}) {
  return {
    painter: { _rttObjectRecyclePool: options.pool },
    terrain: options.tiles === undefined ? null : { tileManager: { _tiles: options.tiles } },
  };
}

describe("the census leaves the pool to MapLibre", () => {
  it("destroys nothing and removes nothing, however often it reads", () => {
    const log: string[] = [];
    const objects = pool(10, log);
    const read = trackRttPool(fakeMap({ pool: objects, tiles: tilesHolding(2) }));
    for (let tick = 0; tick < 5; tick++) read();
    expect(log, "a pooled texture destroyed by the site").toEqual([]);
    expect(objects).toHaveLength(10);
  });
});

describe("reading MapLibre's private state", () => {
  it("returns the pool when it is there", () => {
    const objects = pool(2);
    expect(rttPoolOf(fakeMap({ pool: objects }))).toBe(objects);
  });

  it("returns null — never throws — when MapLibre has moved it", () => {
    expect(rttPoolOf(fakeMap())).toBeNull();
    expect(rttPoolOf({})).toBeNull();
  });

  it("counts objects held by tiles", () => {
    const map = fakeMap({
      pool: [],
      tiles: { a: { rttObjects: [object(), object(), object()] }, b: { rttObjects: [object(), undefined] } },
    });
    expect(rttHeldBy(map)).toEqual({ held: 4, tiles: 2 });
  });

  it("reports nothing held when there is no terrain", () => {
    expect(rttHeldBy(fakeMap({ pool: [] }))).toEqual({ held: 0, tiles: 0 });
  });
});

describe("trackRttPool", () => {
  it("keeps the peak after MapLibre empties the pool at rest", () => {
    const objects = pool(10);
    const read = trackRttPool(fakeMap({ pool: objects, tiles: { a: { rttObjects: [object(), object()] } } }));
    expect(read()).toMatchObject({ pooled: 10, held: 2, heldTiles: 1, peakTotal: 12 });
    objects.length = 0;
    expect(read()).toMatchObject({ pooled: 0, held: 2, peakTotal: 12 });
  });

  it("reads zeros and no renderable count when the private pool is gone", () => {
    expect(trackRttPool(fakeMap())()).toEqual({ pooled: 0, held: 0, heldTiles: 0, peakTotal: 0, renderable: null });
  });
});

describe("rttPoolLine", () => {
  it("fits the 53-character phone budget at realistic and pathological widths", () => {
    for (const stats of [
      { pooled: 512, held: 78, heldTiles: 26, peakTotal: 5610, renderable: 26 },
      { pooled: 23037, held: 23037, heldTiles: 7679, peakTotal: 23037, renderable: 7679 },
    ]) {
      expect(rttPoolLine(stats).length, rttPoolLine(stats)).toBeLessThanOrEqual(53);
    }
  });

  it("leaves the renderable count off the row, whatever it reads", () => {
    // The row is budgeted to 53 characters on a 412 px phone, and at the pathological width above
    // a four-digit count lands it on exactly 53 with a five-digit one over. The count goes in the
    // exported report instead, which is what a harness parses; this pins the row against someone
    // later deciding the most interesting number ought to be on it.
    const wide = { pooled: 23037, held: 23037, heldTiles: 7679, peakTotal: 23037, renderable: 99999 };
    expect(rttPoolLine(wide)).not.toContain("99999");
    expect(rttPoolLine(wide).length).toBeLessThanOrEqual(53);
  });

  it("says so plainly when terrain is off rather than printing zeroes", () => {
    expect(rttPoolLine({ pooled: 0, held: 0, heldTiles: 0, peakTotal: 0, renderable: null })).toBe(
      "rtt — no terrain",
    );
  });
});

describe("renderableTerrainTiles", () => {
  it("reads the count MapLibre is drawing this frame", () => {
    expect(renderableTerrainTiles(mapWithRenderable(["a", "b", "c"]))).toBe(3);
    expect(renderableTerrainTiles(mapWithRenderable([]))).toBe(0);
  });

  it("is null, not 0, when there is nothing to read", () => {
    // 0 means terrain is on and drawing nothing; null means the count was not there. An arm read
    // as a win because it silently had no terrain is the confound this distinction rules out — and
    // it is also what an upstream rename would produce, which the canary below is there to catch.
    expect(renderableTerrainTiles({})).toBeNull();
    expect(renderableTerrainTiles({ terrain: null })).toBeNull();
    expect(renderableTerrainTiles({ terrain: { tileManager: {} } })).toBeNull();
  });
});

describe("canary — the private MapLibre surface this module depends on", () => {
  // These read the SHIPPED bundle, where property names survive minification.
  const bundle = readFileSync(
    new URL("../../node_modules/maplibre-gl/dist/maplibre-gl.mjs", import.meta.url), "utf8");

  it("still frees the pool itself on a frame drawn at rest (#8400)", () => {
    // When this fails, the pool grows back without bound at rest, and a trim is owed again.
    expect(bundle).toMatch(/renderToTexture&&!this\.options\.moving&&this\.clearRTTPool\(\)/);
    expect(bundle).toMatch(/clearRTTPool\(\)\{for\(let \w+ of this\._rttObjectRecyclePool\)/);
  });

  it("still names the pool `_rttObjectRecyclePool`", () => {
    expect(bundle).toMatch(/this\._rttObjectRecyclePool\.pop\(\)/);
  });

  it("still keeps each tile's drapes in `rttObjects`", () => {
    expect(bundle).toMatch(/\.rttObjects\b/);
  });

  it("still names the drawn-tile list `_renderableTilesKeys`", () => {
    // A rename turns `renderableTerrainTiles` into a permanent null, which reads exactly like
    // "this arm had no terrain". It is declared in the shipped .d.ts despite the underscore, so
    // this guards a name upstream is still free to move.
    expect(bundle).toContain("_renderableTilesKeys");
  });
});
