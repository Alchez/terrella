/**
 * A census of MapLibre's render-to-texture pool, for the `?perf` panel and the exported report.
 *
 * With terrain on, MapLibre paints each terrain tile's draped layers into an offscreen texture, one
 * per tile per layer stack, taken from `Painter._rttObjectRecyclePool` and returned to it when the
 * tile lets go. At our declared sizes each is a 512 px RGBA target, exactly 1 MiB, so the counts
 * read directly as MiB.
 *
 * Counting only, never trimming: MapLibre frees the pool itself on every frame drawn at rest and
 * when terrain is removed (#8400), so a trim here would fight it for nothing. The case that would
 * want one back is upstream ceasing to free it, and a canary on the shipped bundle fails then.
 *
 * Every symbol read below is private MapLibre state, and the canaries fail when any of it moves: a
 * silent rename turns a reading into a steady 0 or null that looks like "no terrain".
 */

/** One pooled render-to-texture object, as far as the census needs to see it. */
export interface RttObject {
  readonly size: number;
}

/** The private MapLibre surface this module reads, named so the dependency is legible. */
interface RttMap {
  painter?: { _rttObjectRecyclePool?: RttObject[] };
  terrain?: {
    tileManager?: {
      _tiles?: Record<string, { rttObjects?: (RttObject | undefined)[] }>;
      _renderableTilesKeys?: string[];
    };
  } | null;
}

/** Live census of the pool, in objects. `held` is owned by tiles; `pooled` waits to be reused. */
export interface RttPoolStats {
  pooled: number;
  held: number;
  heldTiles: number;
  peakTotal: number;
  /**
   * Terrain tiles being DRAWN this frame, or null when there is no terrain to count.
   *
   * The multiplier on the per-tile main-thread work, so an arm that changes it changes the cost and
   * an arm that does not, does not. It is NOT `heldTiles`, which counts the manager's whole cache.
   * Null rather than 0 because "this page has no terrain" and "terrain is on and drawing nothing"
   * are different readings, and a 0 that means the former is how an arm gets read as a win.
   */
  renderable: number | null;
}

/** The pool, or null when MapLibre has moved it: a rename must read as absent, never throw. */
export function rttPoolOf(map: RttMap): RttObject[] | null {
  const pool = map.painter?._rttObjectRecyclePool;
  return Array.isArray(pool) ? pool : null;
}

/**
 * Terrain tiles being drawn this frame, or null when the count is not there to be read.
 *
 * `_renderableTilesKeys` is underscore-prefixed but IS declared in the shipped `.d.ts`, so this is
 * typed rather than cast. The canary still guards it: a rename would turn this reading into a
 * permanent null, which reads exactly like "terrain is off".
 */
export function renderableTerrainTiles(map: RttMap): number | null {
  const keys = map.terrain?.tileManager?._renderableTilesKeys;
  return Array.isArray(keys) ? keys.length : null;
}

/** Objects currently owned by terrain tiles: the working set. */
export function rttHeldBy(map: RttMap): { held: number; tiles: number } {
  const tiles = map.terrain?.tileManager?._tiles;
  if (tiles === undefined) return { held: 0, tiles: 0 };
  let held = 0;
  let count = 0;
  for (const key in tiles) {
    count += 1;
    for (const object of tiles[key].rttObjects ?? []) if (object) held += 1;
  }
  return { held, tiles: count };
}

/**
 * The census reader, keeping the peak across reads.
 *
 * Reads are the only samples. MapLibre empties the pool on the first frame at rest, before
 * `moveend` fires, so an event listener would only ever see it empty; the `?perf` panel reads on
 * every tick, moving or not, which is what catches the peak.
 */
export function trackRttPool(map: RttMap): () => RttPoolStats {
  let peakTotal = 0;
  return () => {
    const pooled = rttPoolOf(map)?.length ?? 0;
    const { held, tiles } = rttHeldBy(map);
    peakTotal = Math.max(peakTotal, pooled + held);
    return { pooled, held, heldTiles: tiles, peakTotal, renderable: renderableTerrainTiles(map) };
  };
}

/**
 * One `?perf` row, under GPU · VRAM. Kept inside the 53-character phone budget.
 *
 * `renderable` is deliberately NOT here: at the widths this line is tested against it lands the row
 * on exactly 53 characters with a four-digit count and over it with five. It goes in the exported
 * report instead, which is what a harness parses.
 */
export function rttPoolLine(stats: RttPoolStats): string {
  if (stats.pooled === 0 && stats.held === 0) return "rtt — no terrain";
  return `rtt ${stats.pooled} idle · ${stats.held} held · peak ${stats.peakTotal}`;
}
