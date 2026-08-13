import { describe, expect, it } from "vitest";

import type { RttPoolStats } from "../rttPoolTrim";
import {
  buildSample,
  emitDevToolsTrack,
  PerfTimeline,
  probeGpuMemory,
  summariseSince,
  TIMELINE_CAPACITY,
  timelineLines,
  type TimelineMapLike,
  type TimelineSample,
} from "./perfTimeline";

const stats = (over: Partial<RttPoolStats> = {}): RttPoolStats => ({
  pooled: 12,
  held: 3,
  heldTiles: 3,
  peakTotal: 40,
  destroyedTotal: 0,
  renderable: 35,
  ...over,
});

const sample = (over: Partial<TimelineSample> = {}): TimelineSample => ({
  atMs: 0,
  rttPooled: 1,
  rttHeld: 1,
  renderable: 1,
  gpu: null,
  worstFrameMs: 0,
  longTaskMs: 0,
  ...over,
});

describe("buildSample — time added to numbers that already have an owner", () => {
  it("carries the census through unchanged", () => {
    const built = buildSample({
      atMs: 1234,
      stats: stats(),
      gpu: null,
      worstFrameMs: 17,
      longTaskMs: 80,
    });
    expect(built).toEqual({
      atMs: 1234,
      rttPooled: 12,
      rttHeld: 3,
      renderable: 35,
      gpu: null,
      worstFrameMs: 17,
      longTaskMs: 80,
    });
  });

  it("keeps a null census null rather than inventing zeros", () => {
    // Zero and absent are different readings — a 0 that means "no terrain on this page" is how an
    // arm gets read as a win. `rttPoolTrim.ts` makes the same distinction and this must not undo it.
    const built = buildSample({ atMs: 0, stats: null, gpu: null, worstFrameMs: 0, longTaskMs: 0 });
    expect(built.rttPooled).toBeNull();
    expect(built.renderable).toBeNull();
  });

  it("preserves a genuine zero", () => {
    const built = buildSample({
      atMs: 0,
      stats: stats({ pooled: 0, renderable: 0 }),
      gpu: null,
      worstFrameMs: 0,
      longTaskMs: 0,
    });
    expect(built.rttPooled).toBe(0);
    expect(built.renderable).toBe(0);
  });
});

const mapWithGl = (getExtension: (name: string) => unknown): TimelineMapLike => ({
  painter: { context: { gl: { getExtension } as unknown as WebGL2RenderingContext } },
});

describe("probeGpuMemory — present in dev, absent in production", () => {
  it("reads bytes and counts when the dev-only extension is attached", () => {
    const map = mapWithGl(() => ({
      getMemoryInfo: () => ({
        memory: { texture: 345_409_512, total: 442_222_014 },
        resources: { texture: 268 },
      }),
    }));
    expect(probeGpuMemory(map)).toEqual({
      textureBytes: 345_409_512,
      totalBytes: 442_222_014,
      textures: 268,
    });
  });

  it("asks for the extension by the name the library registers", () => {
    // Pinned because the whole dev tool is unreachable if this string drifts, and the symptom is a
    // quiet null that reads exactly like production.
    let asked: string | null = null;
    probeGpuMemory(
      mapWithGl((name) => {
        asked = name;
        return null;
      }),
    );
    expect(asked).toBe("GMAN_webgl_memory");
  });

  it("returns null where the library is not shipped, and where there is no context", () => {
    expect(probeGpuMemory(mapWithGl(() => null))).toBeNull();
    expect(probeGpuMemory({ painter: { context: { gl: null } } })).toBeNull();
    expect(probeGpuMemory({})).toBeNull();
  });
});

describe("PerfTimeline — bounded by construction", () => {
  it("cannot grow past its capacity", () => {
    const timeline = new PerfTimeline(4);
    for (let index = 0; index < 100; index++) timeline.push(sample({ atMs: index }));
    expect(timeline.length).toBe(4);
    expect(timeline.samples()).toHaveLength(4);
  });

  it("keeps the NEWEST samples, oldest first", () => {
    const timeline = new PerfTimeline(3);
    for (let index = 0; index < 5; index++) timeline.push(sample({ atMs: index }));
    expect(timeline.samples().map((entry) => entry.atMs)).toEqual([2, 3, 4]);
  });

  it("reads in order before it has wrapped", () => {
    const timeline = new PerfTimeline(3);
    timeline.push(sample({ atMs: 7 }));
    timeline.push(sample({ atMs: 8 }));
    expect(timeline.samples().map((entry) => entry.atMs)).toEqual([7, 8]);
  });

  it("ships a bound, so the instrument cannot become the growth it measures", () => {
    expect(TIMELINE_CAPACITY).toBeLessThanOrEqual(1000);
    expect(new PerfTimeline().samples()).toEqual([]);
  });
});

describe("summariseSince — a mark, which adds a reading rather than destroying one", () => {
  const series = [
    sample({ atMs: 100, worstFrameMs: 900, longTaskMs: 500 }),
    sample({ atMs: 200, worstFrameMs: 20, longTaskMs: 0 }),
    sample({ atMs: 300, worstFrameMs: 60, longTaskMs: 90 }),
  ];

  it("is null until a mark is set, so the panel shows only the cumulative reading", () => {
    expect(summariseSince(series, null)).toBeNull();
  });

  it("aggregates only the slices at or after the mark", () => {
    expect(summariseSince(series, 200)).toEqual({ worstFrameMs: 60, longTaskMs: 90, slices: 2 });
  });

  it("EXCLUDES an earlier hitch, which is the entire point of marking", () => {
    // The 900 ms frame before the mark must not be attributed to the gesture after it — that
    // conflation is what makes a cumulative-only panel unable to answer "what did THAT cost".
    expect(summariseSince(series, 200)?.worstFrameMs).toBe(60);
  });

  it("does not mutate or clear the samples it reads", () => {
    // The cumulative fields are protected BY not being touched. If this ever aggregates
    // destructively, `PerfSnapshot.worstFrameMs`'s stated guarantee quietly stops holding.
    const before = structuredClone(series);
    summariseSince(series, 100);
    expect(series).toEqual(before);
  });

  it("reports zero slices for a mark in the future rather than pretending to have data", () => {
    expect(summariseSince(series, 9999)).toEqual({ worstFrameMs: 0, longTaskMs: 0, slices: 0 });
  });
});

describe("timelineLines — the panel gains bytes and nothing already shown", () => {
  it("shows the since-mark line only once a mark exists", () => {
    expect(timelineLines(sample(), null).map((line) => line.text).join()).not.toContain("since mark");
    const marked = timelineLines(sample(), { worstFrameMs: 61.4, longTaskMs: 90, slices: 10 });
    expect(marked[0].text).toBe("since mark 3.0s — worst 61 ms · blocked 90 ms");
    expect(marked[0].group).toBe("feel");
  });

  it("prints nothing when the dev tool is absent", () => {
    expect(timelineLines(sample({ gpu: null }))).toEqual([]);
  });

  it("reports MiB and the texture count when it is present", () => {
    const lines = timelineLines(
      sample({ gpu: { textureBytes: 345_409_512, totalBytes: 442_222_014, textures: 268 } }),
    );
    expect(lines).toHaveLength(1);
    expect(lines[0].text).toBe("gpu 422 MiB · 329 MiB tex · 268 textures");
  });

  it("does not restate the pool terms the existing row already carries", () => {
    // `rttPoolLine` owns that row. Two spellings of one census is the duplication this module's
    // header refuses, and it would drift the moment either is edited.
    const lines = timelineLines(
      sample({ rttPooled: 99, renderable: 4999, gpu: { textureBytes: 1, totalBytes: 1, textures: 1 } }),
    );
    expect(lines.map((line) => line.text).join(" ")).not.toContain("4999");
  });
});

describe("emitDevToolsTrack — never breaks the page it profiles", () => {
  it("survives a console without timeStamp", () => {
    const original = (console as { timeStamp?: unknown }).timeStamp;
    (console as { timeStamp?: unknown }).timeStamp = undefined;
    expect(() => emitDevToolsTrack(sample())).not.toThrow();
    (console as { timeStamp?: unknown }).timeStamp = original;
  });

  it("survives a timeStamp that throws", () => {
    const original = (console as { timeStamp?: unknown }).timeStamp;
    (console as { timeStamp?: unknown }).timeStamp = () => {
      throw new Error("devtools said no");
    };
    expect(() => emitDevToolsTrack(sample())).not.toThrow();
    (console as { timeStamp?: unknown }).timeStamp = original;
  });
});
