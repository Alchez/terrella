/**
 * Bound MapLibre's render-to-texture recycle pool, which is unbounded upstream.
 *
 * WHAT THE POOL IS
 * ----------------
 * With terrain on, MapLibre renders each terrain tile's draped layers into an offscreen texture
 * and drapes the result on the mesh. One texture is taken per tile PER LAYER STACK, from
 * `Painter._rttObjectRecyclePool`:
 *
 *   acquireRTT(size)   pool.pop() ?? new Texture(size, size)   <- creates only when the pool is EMPTY
 *   releaseRTT(obj)    pool.push(obj)                          <- no cap, no eviction
 *
 * The sibling pool in the same class caps itself — `saveTileTexture` keeps at most
 * `MAX_TEXTURE_POOL_SIZE_PER_BUCKET = 50` per size and destroys the rest. `releaseRTT` has no
 * such branch, and the only thing that ever empties the pool is `Painter.destroy()`, reachable
 * only from `map.remove()` and from a lost context. `Terrain.destroy()` does not touch it: it
 * calls `tileManager.destruct()` -> `releaseAllRTT()`, which PUSHES every tile's objects in. So
 * `setTerrain(null)` — the degradation ladder's most drastic rung — grows the pool instead of
 * draining it.
 *
 * WHAT THIS FIXES, AND WHAT IT CANNOT
 * -----------------------------------
 * `acquireRTT` only allocates when the pool is empty, so the number of objects ever created is
 * exactly the high-water mark of objects held SIMULTANEOUSLY by tiles. That is a property of the
 * algorithm, not an observation, and it has a hard consequence: **trimming cannot lower the peak.**
 * A single pan that renders 7,679 terrain tiles across 3 stacks holds 23,037 objects at once, and
 * no pool policy changes that.
 *
 * What trimming fixes is everything after the peak. Measured on this page at 2560x1265, globe,
 * pitch 60: at rest after a pan, 20 tiles hold 60 objects while **5,550 sit idle in the pool** —
 * 99% slack, retained until the tab closes. That resting occupancy is what left one Chrome tab
 * holding 8.2 GB of a 12 GB card with nothing on screen, starving every other GL client on the
 * machine.
 *
 * The peak is the renderable-tile count, and that is MapLibre issue #5368 — a design problem,
 * open over a year. This module is hygiene, deliberately not a cure.
 *
 * WHY `moveend` AND NOT `idle`
 * ----------------------------
 * This page's idle spin means `idle` may never fire at all: starting an ease cancels it, and the
 * spin is a permanent chain of eases at tier `full` — the only tier that has terrain. `moveend`
 * fires for every gesture AND for every spin step, so it is the hook that exists in both states.
 * `idle` is bound too, but only as an opportunistic extra.
 *
 * EVERY SYMBOL BELOW IS PRIVATE MAPLIBRE STATE. The canary tests in `rttPoolTrim.test.ts` read the
 * shipped bundle and fail loudly when any of it moves, because the failure mode of a silent rename
 * is a trim that quietly stops running while VRAM climbs back — the same shape as a guard that
 * encodes a bug rather than catching it.
 */

/** One pooled render-to-texture object: a square RGBA texture plus the edge length it was cut to. */
export interface RttObject {
  readonly size: number;
  readonly texture: { destroy(): void };
}

/** The private MapLibre surface this module reaches into, named so the dependency is legible. */
interface RttPainter {
  _rttObjectRecyclePool?: RttObject[];
  _rttSharedFbo?: { fbo?: { colorAttachment?: { set(value: WebGLTexture | null): void } } } | null;
}

interface RttMap {
  painter?: RttPainter;
  terrain?: {
    tileManager?: {
      _tiles?: Record<string, { rttObjects?: (RttObject | undefined)[] }>;
      _renderableTilesKeys?: string[];
    };
  } | null;
  isMoving?(): boolean;
  on(event: string, listener: () => void): unknown;
  off(event: string, listener: () => void): unknown;
}

/** Live census of the pool, in objects. `held` is owned by tiles and is NOT trimmable. */
export interface RttPoolStats {
  pooled: number;
  held: number;
  heldTiles: number;
  peakTotal: number;
  destroyedTotal: number;
  /**
   * Terrain tiles being DRAWN this frame, or null when there is no terrain to count.
   *
   * The quantity the profile accuses. Per-tile main-thread work — a `Float64Array(16)` per
   * renderable tile per call, then texture upload, then `uniformMatrix4fv` — makes this number the
   * multiplier on everything else, so an arm that changes it changes the cost and an arm that does
   * not, does not. It is NOT `heldTiles`: that counts the manager's whole cache, which is a
   * superset and moves for different reasons.
   *
   * Null rather than 0 because "this page has no terrain" and "terrain is on and drawing nothing"
   * are different readings, and a 0 that means the former is how an arm gets read as a win.
   */
  renderable: number | null;
}

/**
 * Objects to keep in the pool. 512 MiB of slack against a measured working set of 78 objects at a
 * settled camera — generous enough that ordinary panning re-uses rather than reallocates, small
 * enough that a resting tab returns the card. Tunable: the cost of going lower is GPU allocation
 * churn on the next gesture, which is exactly what upstream PR #7549 bought by growing this pool.
 */
export const DEFAULT_RTT_POOL_BOUND = 512;

/** How long after the last `moveend` to trim. Long enough that a flick of several eases settles. */
export const RTT_TRIM_SETTLE_MS = 400;

/** Bytes one pooled object pins: a square RGBA texture, no mip chain (RTT targets are not mipped). */
export function rttObjectBytes(object: RttObject): number {
  return object.size * object.size * 4;
}

/** Total bytes a pool is holding. Sums per object rather than assuming one size — the pool mixes
 *  sizes whenever `acquireRTT` re-cuts a recycled object to a different edge. */
export function rttPoolBytes(pool: readonly RttObject[]): number {
  let bytes = 0;
  for (const object of pool) bytes += rttObjectBytes(object);
  return bytes;
}

/**
 * Destroy pooled objects beyond `bound`, and return how many were destroyed.
 *
 * Removal happens BEFORE destruction, never the other way round: an object still in the array is
 * reachable by `acquireRTT`, and handing out a destroyed texture would draw black rather than
 * throw. Pure and GL-free, so the ordering is unit-testable without a canvas.
 */
export function trimRttPool(pool: RttObject[], bound: number): number {
  if (!Number.isInteger(bound) || bound < 0) {
    throw new RangeError(`rtt pool bound must be a non-negative integer, got ${bound}`);
  }
  let destroyed = 0;
  while (pool.length > bound) {
    const object = pool.pop();
    if (object === undefined) break;
    object.texture.destroy();
    destroyed += 1;
  }
  return destroyed;
}

/** The pool, or null when MapLibre has moved it — a rename must degrade to "no trimming", never
 *  to a throw inside a `moveend` handler. */
export function rttPoolOf(map: RttMap): RttObject[] | null {
  const pool = map.painter?._rttObjectRecyclePool;
  return Array.isArray(pool) ? pool : null;
}

/**
 * Terrain tiles being drawn this frame, or null when the count is not there to be read.
 *
 * `_renderableTilesKeys` is underscore-prefixed but IS declared in the shipped `.d.ts`, so this is
 * typed rather than cast. The canary still guards it: a name upstream is free to change is one that
 * would otherwise turn this reading into a permanent null nobody notices, which reads exactly like
 * "terrain is off" — the same false-negative shape as the trim quietly ceasing to run.
 */
export function renderableTerrainTiles(map: RttMap): number | null {
  const keys = map.terrain?.tileManager?._renderableTilesKeys;
  return Array.isArray(keys) ? keys.length : null;
}

/** Objects currently owned by terrain tiles. Not trimmable — this is the working set. */
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
 * Detach the shared FBO's colour attachment before destroying textures.
 *
 * `bindRTT` leaves the last-rendered texture attached to `_rttSharedFbo`. Destroying that texture
 * while it is still the attachment leaves the FBO referencing a deleted name — and because
 * `colorAttachment` is a cached `BaseValue`, a later `set()` of a RECYCLED GL name would compare
 * equal and skip the rebind. Clearing it costs one call and closes that window.
 */
function detachSharedFboColour(painter: RttPainter): void {
  painter._rttSharedFbo?.fbo?.colorAttachment?.set(null);
}

export interface RttPoolTrimOptions {
  bound?: number;
  settleMs?: number;
  /** Injected by tests; defaults to the real timers. */
  scheduler?: { setTimeout(fn: () => void, ms: number): number; clearTimeout(handle: number): void };
}

export interface RttPoolTrimHandle {
  detach(): void;
  stats(): RttPoolStats;
  /** Trim now, ignoring the settle timer. Returns objects destroyed. */
  trimNow(): number;
  /** False when MapLibre's private surface has moved and trimming is inert. */
  readonly active: boolean;
}

/**
 * Trim the pool whenever the camera settles. Returns a handle exposing a live census for the
 * `?perf` panel — the panel row matters as much as the trim, because once the crash stops the
 * 295x tile overdraw underneath it becomes invisible, which is how it went unnoticed for weeks.
 */
export function attachRttPoolTrim(map: RttMap, options: RttPoolTrimOptions = {}): RttPoolTrimHandle {
  const bound = options.bound ?? DEFAULT_RTT_POOL_BOUND;
  const settleMs = options.settleMs ?? RTT_TRIM_SETTLE_MS;
  const timers = options.scheduler ?? {
    setTimeout: (fn: () => void, ms: number) => window.setTimeout(fn, ms),
    clearTimeout: (handle: number) => window.clearTimeout(handle),
  };
  const active = rttPoolOf(map) !== null;
  let peakTotal = 0;
  let destroyedTotal = 0;
  let pending: number | null = null;

  const census = (): RttPoolStats => {
    const pool = rttPoolOf(map);
    const { held, tiles } = rttHeldBy(map);
    const pooled = pool?.length ?? 0;
    peakTotal = Math.max(peakTotal, pooled + held);
    return {
      pooled,
      held,
      heldTiles: tiles,
      peakTotal,
      destroyedTotal,
      renderable: renderableTerrainTiles(map),
    };
  };

  const trimNow = (): number => {
    const pool = rttPoolOf(map);
    if (pool === null) return 0;
    if (map.isMoving?.() === true) return 0; // a moving map is about to re-acquire; let it settle
    if (pool.length <= bound) return 0;
    const painter = map.painter;
    if (painter !== undefined) detachSharedFboColour(painter);
    const destroyed = trimRttPool(pool, bound);
    destroyedTotal += destroyed;
    return destroyed;
  };

  const schedule = (): void => {
    if (pending !== null) timers.clearTimeout(pending);
    pending = timers.setTimeout(() => {
      pending = null;
      trimNow();
    }, settleMs);
  };

  const onSettle = (): void => {
    census(); // keep the peak honest even when nothing needs trimming
    schedule();
  };

  if (active) {
    map.on("moveend", onSettle);
    map.on("idle", onSettle);
  }

  return {
    detach() {
      if (pending !== null) timers.clearTimeout(pending);
      pending = null;
      if (active) {
        map.off("moveend", onSettle);
        map.off("idle", onSettle);
      }
    },
    stats: census,
    trimNow,
    active,
  };
}

/**
 * One `?perf` row, under GPU · VRAM. Kept inside the 53-character phone budget.
 *
 * `renderable` is deliberately NOT here. It is the most useful number in this census, and at the
 * pathological widths this line is tested against it lands the row on exactly 53 characters with a
 * four-digit count and over it with five. The budget is a measured phone constraint rather than a
 * preference, so the count goes where it is actually read instead — the exported report, which is
 * what a harness parses. A panel row is for a glance; a field is for an arm.
 */
export function rttPoolLine(stats: RttPoolStats): string {
  if (stats.pooled === 0 && stats.held === 0) return "rtt — no terrain";
  return `rtt ${stats.pooled} idle · ${stats.held} held · peak ${stats.peakTotal}`;
}
