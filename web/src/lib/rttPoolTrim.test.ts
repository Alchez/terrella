import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  DEFAULT_RTT_POOL_BOUND,
  attachRttPoolTrim,
  rttHeldBy,
  rttObjectBytes,
  rttPoolBytes,
  rttPoolLine,
  rttPoolOf,
  trimRttPool,
  type RttObject,
} from "./rttPoolTrim";

/** A pooled object that records whether its texture was destroyed, and in what order. */
function fakeObject(size: number, log: string[], name: string): RttObject {
  return { size, texture: { destroy: () => log.push(name) } };
}

/** An RTT object whose destruction is not recorded — for counting, where the log is not read.
 *  `fakeObject` above is the same thing with a name and a log; these tests only need the size. */
const object = (): RttObject => ({ size: 512, texture: { destroy: () => {} } });

function pool(count: number, size = 512, log: string[] = []): RttObject[] {
  return Array.from({ length: count }, (_, index) => fakeObject(size, log, `obj${index}`));
}

/** Minimal stand-in for the private MapLibre surface this module reaches into. */
function fakeMap(options: { pool?: RttObject[] | undefined; moving?: boolean; tiles?: Record<string, { rttObjects?: (RttObject | undefined)[] }> } = {}) {
  const listeners = new Map<string, Set<() => void>>();
  const attachmentSets: (WebGLTexture | null)[] = [];
  return {
    painter: {
      _rttObjectRecyclePool: options.pool,
      _rttSharedFbo: { fbo: { colorAttachment: { set: (v: WebGLTexture | null) => attachmentSets.push(v) } } },
    },
    terrain: options.tiles === undefined ? null : { tileManager: { _tiles: options.tiles } },
    isMoving: () => options.moving === true,
    on(event: string, listener: () => void) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)!.add(listener);
    },
    off(event: string, listener: () => void) {
      listeners.get(event)?.delete(listener);
    },
    emit(event: string) {
      // A snapshot, not a convenience: a listener is allowed to call `off` on itself or a sibling
      // while it runs, and deleting from the live Set mid-iteration silently skips whoever came
      // after. Naming the copy is what says so — the spread reads as removable otherwise.
      const snapshot = [...(listeners.get(event) ?? [])];
      for (const listener of snapshot) listener();
    },
    listenerCount: (event: string) => listeners.get(event)?.size ?? 0,
    attachmentSets,
  };
}

function fakeScheduler() {
  let nextHandle = 1;
  const queued = new Map<number, () => void>();
  return {
    setTimeout(fn: () => void) {
      const handle = nextHandle++;
      queued.set(handle, fn);
      return handle;
    },
    clearTimeout(handle: number) {
      queued.delete(handle);
    },
    runAll() {
      const due = [...queued.entries()];
      queued.clear();
      for (const [, fn] of due) fn();
    },
    pendingCount: () => queued.size,
  };
}

describe("trimRttPool", () => {
  it("destroys exactly the objects beyond the bound and reports the count", () => {
    const log: string[] = [];
    const objects = pool(10, 512, log);
    expect(trimRttPool(objects, 4)).toBe(6);
    expect(objects).toHaveLength(4);
    expect(log).toHaveLength(6);
  });

  it("removes from the array BEFORE destroying, so nothing can acquire a dead texture", () => {
    // The ordering IS the contract: acquireRTT pops, and a popped-but-destroyed object would draw
    // black rather than throw. Asserted by observing array length from inside destroy().
    const observed: number[] = [];
    const objects: RttObject[] = [];
    for (let index = 0; index < 3; index += 1) {
      objects.push({ size: 512, texture: { destroy: () => observed.push(objects.length) } });
    }
    trimRttPool(objects, 0);
    // Each destroy() must see the object already gone: 2, then 1, then 0 — never 3, 2, 1.
    expect(observed).toEqual([2, 1, 0]);
  });

  it("is a no-op when the pool is at or under the bound", () => {
    const log: string[] = [];
    const objects = pool(3, 512, log);
    expect(trimRttPool(objects, 3)).toBe(0);
    expect(trimRttPool(objects, 99)).toBe(0);
    expect(objects).toHaveLength(3);
    expect(log).toEqual([]);
  });

  it("empties the pool at bound 0", () => {
    const objects = pool(5);
    expect(trimRttPool(objects, 0)).toBe(5);
    expect(objects).toHaveLength(0);
  });

  it("rejects a nonsensical bound rather than silently clamping", () => {
    expect(() => trimRttPool(pool(2), -1)).toThrow(RangeError);
    expect(() => trimRttPool(pool(2), 1.5)).toThrow(RangeError);
  });
});

describe("sizing", () => {
  it("prices one 512 object at exactly 1 MiB, RGBA and no mip chain", () => {
    // RTT targets are render destinations, never minified — so unlike the polar caps there is no
    // 4/3 mip tail here. This is the whole reason pool length reads directly as MiB.
    expect(rttObjectBytes({ size: 512, texture: { destroy: () => {} } })).toBe(1_048_576);
  });

  it("sums a mixed-size pool per object rather than assuming one edge", () => {
    const objects: RttObject[] = [
      { size: 512, texture: { destroy: () => {} } },
      { size: 256, texture: { destroy: () => {} } },
    ];
    expect(rttPoolBytes(objects)).toBe(1_048_576 + 262_144);
  });
});

describe("reading MapLibre's private state", () => {
  it("returns the pool when it is there", () => {
    const objects = pool(2);
    expect(rttPoolOf(fakeMap({ pool: objects }))).toBe(objects);
  });

  it("returns null — never throws — when MapLibre has moved it", () => {
    expect(rttPoolOf(fakeMap({ pool: undefined }))).toBeNull();
    expect(rttPoolOf({ on: () => {}, off: () => {} })).toBeNull();
  });

  it("counts objects held by tiles, which are NOT trimmable", () => {
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

describe("attachRttPoolTrim", () => {
  it("trims after the camera settles, not on the moveend itself", () => {
    const objects = pool(10);
    const map = fakeMap({ pool: objects });
    const scheduler = fakeScheduler();
    attachRttPoolTrim(map, { bound: 4, scheduler });

    map.emit("moveend");
    expect(objects, "trim must wait for the settle timer").toHaveLength(10);
    scheduler.runAll();
    expect(objects).toHaveLength(4);
  });

  it("debounces a burst of moveends into ONE trim", () => {
    // The spin is a permanent chain of eases, so moveend fires forever; trimming per event would
    // destroy and reallocate on every spin step.
    const map = fakeMap({ pool: pool(10) });
    const scheduler = fakeScheduler();
    attachRttPoolTrim(map, { bound: 4, scheduler });
    map.emit("moveend");
    map.emit("moveend");
    map.emit("idle");
    expect(scheduler.pendingCount()).toBe(1);
  });

  it("refuses to trim while the map is still moving", () => {
    const objects = pool(10);
    const map = fakeMap({ pool: objects, moving: true });
    const scheduler = fakeScheduler();
    attachRttPoolTrim(map, { bound: 4, scheduler });
    map.emit("moveend");
    scheduler.runAll();
    expect(objects).toHaveLength(10);
  });

  it("clears the shared FBO colour attachment before destroying", () => {
    // A destroyed texture left as the attachment can be skipped by the cached BaseValue if GL
    // recycles the name. One call closes that window.
    const map = fakeMap({ pool: pool(10) });
    const scheduler = fakeScheduler();
    const handle = attachRttPoolTrim(map, { bound: 4, scheduler });
    handle.trimNow();
    expect(map.attachmentSets).toEqual([null]);
  });

  it("does not touch the attachment when there is nothing to trim", () => {
    const map = fakeMap({ pool: pool(3) });
    const handle = attachRttPoolTrim(map, { bound: 4, scheduler: fakeScheduler() });
    handle.trimNow();
    expect(map.attachmentSets).toEqual([]);
  });

  it("is inert and binds NO listeners when the private pool is gone", () => {
    // The upgrade failure mode: degrade to "no trimming", never to a throw inside moveend.
    const map = fakeMap({ pool: undefined });
    const handle = attachRttPoolTrim(map, { scheduler: fakeScheduler() });
    expect(handle.active).toBe(false);
    expect(map.listenerCount("moveend")).toBe(0);
    expect(() => handle.trimNow()).not.toThrow();
    expect(handle.trimNow()).toBe(0);
  });

  it("detaches every listener and cancels a pending trim", () => {
    const objects = pool(10);
    const map = fakeMap({ pool: objects });
    const scheduler = fakeScheduler();
    const handle = attachRttPoolTrim(map, { bound: 4, scheduler });
    map.emit("moveend");
    handle.detach();
    scheduler.runAll();
    expect(objects, "a cancelled trim must not fire after detach").toHaveLength(10);
    expect(map.listenerCount("moveend")).toBe(0);
    expect(map.listenerCount("idle")).toBe(0);
  });

  it("reports a census whose peak survives the trim that reduced it", () => {
    const map = fakeMap({ pool: pool(10), tiles: { a: { rttObjects: [object(), object()] } } });
    const scheduler = fakeScheduler();
    const handle = attachRttPoolTrim(map, { bound: 4, scheduler });
    expect(handle.stats()).toMatchObject({ pooled: 10, held: 2, heldTiles: 1, peakTotal: 12 });
    handle.trimNow();
    const after = handle.stats();
    expect(after.pooled).toBe(4);
    expect(after.peakTotal, "peak is the diagnostic — it must not reset").toBe(12);
    expect(after.destroyedTotal).toBe(6);
  });
});

describe("rttPoolLine", () => {
  it("fits the 53-character phone budget at realistic and pathological widths", () => {
    for (const stats of [
      { pooled: 512, held: 78, heldTiles: 26, peakTotal: 5610, destroyedTotal: 5098 },
      { pooled: 23037, held: 23037, heldTiles: 7679, peakTotal: 23037, destroyedTotal: 999999 },
    ]) {
      expect(rttPoolLine(stats).length, rttPoolLine(stats)).toBeLessThanOrEqual(53);
    }
  });

  it("says so plainly when terrain is off rather than printing zeroes", () => {
    expect(rttPoolLine({ pooled: 0, held: 0, heldTiles: 0, peakTotal: 0, destroyedTotal: 0 })).toBe(
      "rtt — no terrain",
    );
  });
});

describe("canary — the private MapLibre surface this module depends on", () => {
  // These read the SHIPPED bundle, where property names survive minification. A rename upstream
  // makes the trim a silent no-op while VRAM climbs back to crashing, so it must fail HERE.
  const bundle = readFileSync(
    new URL("../../node_modules/maplibre-gl/dist/maplibre-gl.mjs", import.meta.url), "utf8");

  it("still names the pool `_rttObjectRecyclePool`, popped on acquire", () => {
    expect(bundle).toContain("_rttObjectRecyclePool");
    expect(bundle).toMatch(/_rttObjectRecyclePool\.pop\(\)/);
  });

  it("STILL HAS NO CAP on releaseRTT — when this fails, delete this module", () => {
    // The whole reason this module exists. If upstream adds the cap (our report), this assertion
    // is what tells us the workaround is now dead weight rather than leaving it to rot.
    expect(bundle).toMatch(/releaseRTT\(\w+\)\{this\._rttObjectRecyclePool\.push\(\w+\)\}/);
  });

  it("still caps the SIBLING pool at 50, which is the asymmetry being reported", () => {
    expect(bundle).toContain("MAX_TEXTURE_POOL_SIZE_PER_BUCKET");
  });

  it("still clears each tile's references on release, which is what makes trimming safe", () => {
    // A pooled object must be unowned. If Tile.releaseRTT stops zeroing rttObjects, destroying a
    // pooled texture could dangle a live tile reference.
    expect(bundle).toMatch(/rttObjects\.length\s*=\s*0/);
  });

  it("still destroys pooled textures through `.texture.destroy()`", () => {
    expect(bundle).toMatch(/_rttObjectRecyclePool\)\s*\w*\.?\w*\.?texture\.destroy\(\)/);
  });

  it("still keeps one shared FBO whose colour attachment we detach before destroying", () => {
    expect(bundle).toContain("_rttSharedFbo");
    expect(bundle).toMatch(/_rttSharedFbo\.fbo\.colorAttachment/);
  });
});

describe("defaults", () => {
  it("bounds the pool well above the measured working set", () => {
    // 78 objects at a settled camera (26 tiles x 3 stacks), measured 2026-07-30 at 2560x1265.
    expect(DEFAULT_RTT_POOL_BOUND).toBeGreaterThan(78);
  });
});

describe("the ?nortt disable arm", () => {
  it("is a no-op at MAX_SAFE_INTEGER without relying on an early return", () => {
    // earth.astro disables trimming with this exact bound. `trimRttPool` demands an integer, so
    // Infinity would throw if the length guard above it were ever reordered away.
    const objects = pool(10);
    expect(trimRttPool(objects, Number.MAX_SAFE_INTEGER)).toBe(0);
    expect(objects).toHaveLength(10);
  });

  it("still reports a census while trimming nothing", () => {
    const map = fakeMap({ pool: pool(10) });
    const handle = attachRttPoolTrim(map, { bound: Number.MAX_SAFE_INTEGER, scheduler: fakeScheduler() });
    expect(handle.trimNow()).toBe(0);
    expect(handle.stats().pooled).toBe(10);
  });
});
