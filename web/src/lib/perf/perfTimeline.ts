// A TRAJECTORY, because the defects that cost the most here are not visible in a moment.
//
// The exported capture has always been a snapshot, and the two worst faults this project has chased
// were shapes rather than values: an unbounded render-to-texture pool, and a terrain tile set that
// inflates under one kind of camera movement and not another. Neither reads as wrong in a single
// frame — `renderable: 4999` and `renderable: 35` look equally plausible in a field unless you can
// see which way it was heading. Finding the second took a throwaway script sampling in a loop, and
// the finding was then re-derived weeks later because nothing durable carried the series.
//
// THIS MODULE ADDS TIME AND GPU BYTES, AND DELIBERATELY MEASURES NOTHING ELSE. The terms of the
// model — `pool ≈ renderable tiles × drape stacks` — are already computed once, by `rttPoolTrim.ts`,
// which owns the reach past MapLibre's public API and already ships them in the report. Probing
// them a second time here is the "second reader with no owner" this codebase has paid for
// repeatedly: two copies, both correct where they sit, drifting the moment MapLibre renames a
// private field. So the sampler is handed the stats the page already has.
//
// What genuinely had no owner is the GPU's own accounting, because WebGL exposes no memory query.
// `webgl-memory` answers it and is a DEV-ONLY tool (see `webglMemoryDevTool` in astro.config.ts), so
// `gpu` is null in production by design — an absence, not a fault.

import type { RttPoolStats } from "../rttPoolTrim";

/** The shape this module needs to find a GL context. Structural, so tests need no real map. */
export interface TimelineMapLike {
  painter?: { context?: { gl?: WebGL2RenderingContext | null } | null } | null;
}

/** Bytes the GPU is holding, when `webgl-memory` is attached. Dev only. */
export interface GpuMemory {
  textureBytes: number;
  totalBytes: number;
  textures: number;
}

export interface TimelineSample {
  atMs: number;
  /** Idle objects in the RTT pool. */
  rttPooled: number | null;
  /** Objects currently held by tiles. */
  rttHeld: number | null;
  /** Terrain tiles being drawn — the term that inflates under a drag. Null means no terrain. */
  renderable: number | null;
  /** Null in production, where the accounting library is deliberately not shipped. */
  gpu: GpuMemory | null;
  /** Worst frame IN THIS SLICE, not since load — a cumulative maximum cannot show onset. */
  worstFrameMs: number;
  /** Blocking accumulated in this slice. */
  longTaskMs: number;
}

/**
 * How many samples the ring holds.
 *
 * At the overlay's 300 ms tick this is two minutes of history, which spans the ~60 s of dragging
 * that exhausts a 12 GB card. A HARD bound rather than a target: the instrument must not become the
 * unbounded-growth defect it exists to find.
 */
export const TIMELINE_CAPACITY = 400;

/**
 * Read GPU bytes through `webgl-memory`, or null where it is not attached.
 *
 * Null is NOT a fault and is deliberately not surfaced as one: the library ships in dev only, so
 * every production capture carries null, and an instrument that cried "unavailable" on every one of
 * those would train its reader to ignore the field that matters.
 */
export function probeGpuMemory(map: TimelineMapLike): GpuMemory | null {
  const gl = map.painter?.context?.gl ?? null;
  if (!gl) return null;
  const extension = gl.getExtension("GMAN_webgl_memory") as
    | { getMemoryInfo?: () => { memory?: Record<string, number>; resources?: Record<string, number> } }
    | null;
  const info = extension?.getMemoryInfo?.();
  if (!info?.memory) return null;
  return {
    textureBytes: info.memory.texture ?? 0,
    totalBytes: info.memory.total ?? 0,
    textures: info.resources?.texture ?? 0,
  };
}

/** Fold the stats the page already computes into one sample. */
export function buildSample(input: {
  atMs: number;
  stats: RttPoolStats | null;
  gpu: GpuMemory | null;
  worstFrameMs: number;
  longTaskMs: number;
}): TimelineSample {
  return {
    atMs: input.atMs,
    rttPooled: input.stats?.pooled ?? null,
    rttHeld: input.stats?.held ?? null,
    renderable: input.stats?.renderable ?? null,
    gpu: input.gpu,
    worstFrameMs: input.worstFrameMs,
    longTaskMs: input.longTaskMs,
  };
}

/** A fixed-size ring. Bounded by construction rather than by a caller remembering to trim. */
export class PerfTimeline {
  private readonly ring: TimelineSample[] = [];
  private cursor = 0;

  constructor(private readonly capacity: number = TIMELINE_CAPACITY) {}

  push(sample: TimelineSample): void {
    if (this.ring.length < this.capacity) this.ring.push(sample);
    else {
      this.ring[this.cursor] = sample;
      this.cursor = (this.cursor + 1) % this.capacity;
    }
  }

  /** Oldest first, so the export reads as a trajectory rather than as ring order. */
  samples(): TimelineSample[] {
    if (this.ring.length < this.capacity) return [...this.ring];
    return [...this.ring.slice(this.cursor), ...this.ring.slice(0, this.cursor)];
  }

  get length(): number {
    return this.ring.length;
  }
}

/**
 * Aggregate the slices at or after a mark.
 *
 * A DERIVED reading, and that is the whole design. `PerfSnapshot.worstFrameMs` is deliberately
 * cumulative and never cleared — its docstring says why: the hitch happens during a gesture and the
 * screenshot is taken after it, so a windowed reading has already dropped the number by the time
 * anyone writes it down. A reset button that zeroed those fields would delete exactly the evidence
 * that decision protects.
 *
 * So nothing is reset. The ring already holds per-slice figures, and marking a moment is just
 * choosing where to start adding them up. Both readings then coexist: cumulative for the hitch that
 * already happened, since-mark for the gesture about to be performed.
 */
export function summariseSince(
  samples: readonly TimelineSample[],
  markMs: number | null,
): { worstFrameMs: number; longTaskMs: number; slices: number } | null {
  if (markMs === null) return null;
  let worstFrameMs = 0;
  let longTaskMs = 0;
  let slices = 0;
  for (const sample of samples) {
    if (sample.atMs < markMs) continue;
    worstFrameMs = Math.max(worstFrameMs, sample.worstFrameMs);
    longTaskMs += sample.longTaskMs;
    slices += 1;
  }
  return { worstFrameMs, longTaskMs, slices };
}

const MIB = 1024 * 1024;

/**
 * The panel's row for GPU bytes.
 *
 * Only the bytes: the pool and tile terms already have a row from `rttPoolLine`, and adding a
 * second spelling of them is the duplication this module's header refuses.
 */
export function timelineLines(
  sample: TimelineSample,
  since: { worstFrameMs: number; longTaskMs: number; slices: number } | null = null,
): { group: "gpu" | "feel"; text: string }[] {
  const lines: { group: "gpu" | "feel"; text: string }[] = [];
  if (since !== null) {
    // Seconds, because a mark is set by hand before a gesture and "how long have I been watching"
    // is the question a reader actually has about it.
    const seconds = ((since.slices * 300) / 1000).toFixed(1);
    lines.push({
      group: "feel",
      text: `since mark ${seconds}s — worst ${Math.round(since.worstFrameMs)} ms · blocked ${Math.round(since.longTaskMs)} ms`,
    });
  }
  if (sample.gpu !== null) {
    lines.push({
      group: "gpu",
      text: `gpu ${Math.round(sample.gpu.totalBytes / MIB)} MiB · ${Math.round(
        sample.gpu.textureBytes / MIB,
      )} MiB tex · ${sample.gpu.textures} textures`,
    });
  }
  return lines;
}

/**
 * Hand one sample to Chrome's Performance panel as a custom track.
 *
 * Bought rather than built: the extensibility API renders our series beside the main thread, GPU and
 * frame tracks in the profiler contributors already use, so there is no viewer to write. It is
 * Chrome-only and needs "Show custom tracks" enabled, which is exactly why it is an ADDITION to the
 * exported ring and never a replacement — the JSON is what survives Firefox and a production export.
 */
export function emitDevToolsTrack(sample: TimelineSample): void {
  const timeStamp = (console as unknown as { timeStamp?: (...args: unknown[]) => void }).timeStamp;
  if (typeof timeStamp !== "function") return;
  try {
    if (sample.renderable !== null) {
      timeStamp.call(console, `terrain tiles: ${sample.renderable}`, undefined, undefined, "Terrella", "Terrella");
    }
    if (sample.rttPooled !== null) {
      timeStamp.call(console, `rtt idle: ${sample.rttPooled}`, undefined, undefined, "Terrella", "Terrella");
    }
  } catch {
    // A profiler hook must never be able to break the page it profiles.
  }
}
