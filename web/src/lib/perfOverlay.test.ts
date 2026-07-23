import { describe, expect, it } from "vitest";
import { perfSummaryLines, type PerfSnapshot } from "./perfOverlay";

const BASE: PerfSnapshot = {
  bootMs: 1234.6,
  mapLoadMs: null,
  firstIdleMs: null,
  longTaskCount: 0,
  longTaskTotalMs: 0,
  longTaskMaxMs: 0,
  lastLongTaskEndMs: null,
  longTaskApiAvailable: true,
};

describe("perfSummaryLines", () => {
  it("renders pending timings as em-dashes and rounds real ones", () => {
    const lines = perfSummaryLines(BASE);
    expect(lines[0]).toBe("boot 1235 ms");
    expect(lines[1]).toBe("map load — · first idle —");
  });

  it("summarizes long tasks once they arrive", () => {
    const lines = perfSummaryLines({
      ...BASE,
      mapLoadMs: 2100,
      firstIdleMs: 3400.4,
      longTaskCount: 14,
      longTaskTotalMs: 2210.7,
      longTaskMaxMs: 480.2,
      lastLongTaskEndMs: 3200,
    });
    expect(lines[1]).toBe("map load 2100 ms · first idle 3400 ms");
    expect(lines[2]).toBe("long tasks 14 · 2211 ms total · 480 ms max");
    expect(lines[3]).toBe("last long task ended 3200 ms");
  });

  it("says so plainly when the long-task API is missing", () => {
    const lines = perfSummaryLines({ ...BASE, longTaskApiAvailable: false });
    expect(lines[2]).toBe("long-task API unavailable");
    expect(lines).toHaveLength(3);
  });
});
