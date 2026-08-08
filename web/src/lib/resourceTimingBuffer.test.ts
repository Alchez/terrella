import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { RESOURCE_TIMING_BUFFER_SIZE, raiseResourceTimingBuffer } from "./resourceTimingBuffer";

describe("raiseResourceTimingBuffer", () => {
  it("sets the size and returns it, so a report states it rather than assuming it", () => {
    const calls: number[] = [];
    const size = raiseResourceTimingBuffer(
      { setResourceTimingBufferSize: (value: number) => calls.push(value) },
      RESOURCE_TIMING_BUFFER_SIZE,
    );
    expect(calls).toEqual([RESOURCE_TIMING_BUFFER_SIZE]);
    expect(size).toBe(RESOURCE_TIMING_BUFFER_SIZE);
  });

  it("is large enough for a session that already measured 97 tiles in one viewport", () => {
    expect(RESOURCE_TIMING_BUFFER_SIZE).toBeGreaterThan(250);
  });
});

describe("the page raises the buffer, early, and pays nothing else for it", () => {
  const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");

  it("calls the raiser, which a test of the function alone does not check", () => {
    // Found by sabotage: replacing the call site with the bare constant broke nothing, because
    // every assertion was about the function rather than about anyone using it.
    expect(globe).toContain("raiseResourceTimingBuffer(performance, RESOURCE_TIMING_BUFFER_SIZE)");
  });

  it("raises it before the map is constructed, since dropped entries never come back", () => {
    // Order is the whole value: a raise after the first tiles have gone out leaves the totals a
    // floor with no way to know it.
    const raiseAt = globe.indexOf("raiseResourceTimingBuffer(performance");
    const mapAt = globe.indexOf("new maplibregl.Map(");
    expect(raiseAt).toBeGreaterThan(-1);
    expect(mapAt).toBeGreaterThan(-1);
    expect(raiseAt, "the buffer must be raised before the map starts requesting").toBeLessThan(
      mapAt,
    );
  });

  it("imports this module statically, which is the exemption the ordering needs", () => {
    // The defect this closes, measured: leaving the raiser inside `perfNetwork.ts` gave that module a
    // static import, Rollup put it in the main chunk, and 268 lines of instrument shipped to every
    // visitor — +2,362 bytes, gallery tier included. Splitting the import site does not split the
    // chunk; splitting the module does. The companion rule — that nothing in lib/perf/ is statically
    // imported — is guarded in lib/perf/lazyBoundary.test.ts.
    expect(globe).toMatch(/^\s*import \{[^;]*?from "\.\.\/lib\/resourceTimingBuffer";/m);
  });
});
