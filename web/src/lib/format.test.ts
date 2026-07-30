// A one-line function with a real contract: every diagnostic line in the panel rounds the same
// way, because a panel that mixes `384 MB` and `383.9 MB` reads as broken rather than precise.

import { describe, expect, it } from "vitest";
import { megabytes } from "./format";

describe("megabytes", () => {
  it("counts MEBIbytes, not megabytes — the unit the GPU and the cache budget are written in", () => {
    // 384 MiB is TERRAIN_CACHE_BYTE_BUDGET's own spelling; dividing by 1e6 would print 403 here
    // and silently contradict the constant it is meant to render.
    expect(megabytes(384 * 1024 * 1024)).toBe("384");
    expect(megabytes(1024 * 1024)).toBe("1");
  });

  it("rounds to whole units, so no line ever grows a decimal place the others lack", () => {
    expect(megabytes(1.5 * 1024 * 1024)).toBe("2");
    expect(megabytes(1.4 * 1024 * 1024)).toBe("1");
  });

  it("renders a sub-megabyte reading as 0 rather than hiding it — a zero here is a real fact", () => {
    // Raster sources report 0 bytes against real slot counts (DEMData weighs nothing there), and
    // that must survive into the panel as "0", not as an empty string or a crash.
    expect(megabytes(0)).toBe("0");
    expect(megabytes(1024)).toBe("0");
  });
});
