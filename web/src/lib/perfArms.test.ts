// An arm flag that is silently ignored produces a globe indistinguishable from the default, so
// most of what is asserted here is that "ignored" is never quiet.

import { describe, expect, it } from "vitest";
import {
  LOD_MAX_ZOOM_LEVELS_RANGE,
  REFRESH_MODES,
  armFlagComplaint,
  parseLodMaxZoomLevelsOnScreen,
  parseRefreshExpiredTiles,
} from "./perfArms";

const lod = (search: string) => parseLodMaxZoomLevelsOnScreen(new URLSearchParams(search));
const refresh = (search: string) => parseRefreshExpiredTiles(new URLSearchParams(search));
const complain = (search: string, flag: string, honoured = false) =>
  armFlagComplaint(new URLSearchParams(search), flag, honoured);

describe("arm flags are inert without ?perf", () => {
  it("changes nothing on a production URL, so a pasted link cannot reconfigure a stranger", () => {
    // The gate, and the whole reason these two share a module: stated once, not once per flag.
    expect(lod("?lod=11")).toBeNull();
    expect(refresh("?refresh=on")).toBeNull();
    expect(lod("?perf&lod=11")).toBe(11);
    expect(refresh("?perf&refresh=on")).toBe(true);
  });

  it("says so rather than ignoring the flag in silence", () => {
    // A typo and a missing ?perf both render as "the default", which is why neither may be quiet.
    expect(complain("?lod=11", "lod")).toContain("need ?perf");
    expect(complain("?lod=11", "lod")).toContain("11");
    expect(complain("?perf&lod=banana", "lod")).toContain("not a value this flag takes");
    expect(complain("?perf&lod=banana", "lod")).toContain("banana");
  });

  it("STAYS QUIET when the flag was honoured, which is the case that shipped broken", () => {
    // The first version complained on presence alone, so a working `?lod=11` logged "not a value
    // this flag takes" beside the line reporting it applied to three sources. The tests covered a
    // typo and a missing ?perf and never the success path, so nothing went red. A complaint cannot
    // infer what happened from presence — it has to be told.
    expect(complain("?perf&lod=11", "lod", true)).toBeNull();
    expect(complain("?perf&refresh=on", "refresh", true)).toBeNull();
  });

  it("has nothing to say about a flag nobody wrote", () => {
    expect(complain("?perf", "lod")).toBeNull();
    expect(complain("", "refresh")).toBeNull();
  });
});

describe("parseLodMaxZoomLevelsOnScreen", () => {
  it("accepts a float, so the default itself is expressible as an arm", () => {
    // An arm that cannot state the baseline it is compared against is half an experiment, and
    // MapLibre's own default is 9.314.
    expect(lod("?perf&lod=9.314")).toBe(9.314);
  });

  it("still reaches the regime where the falloff inverts, because that is a real arm", () => {
    // Below ~5.4 at our fov 15 the horizon falloff reverses. Deliberately reachable — a
    // measurement may want to enter that regime on purpose rather than be protected from it.
    expect(lod("?perf&lod=4")).toBe(4);
  });

  it("is null on anything doubtful rather than falling back to the default", () => {
    // A run that believes it measured M=11 while running at the default is worse than no run.
    expect(lod("?perf&lod=")).toBeNull();
    expect(lod("?perf&lod=banana")).toBeNull();
    expect(lod("?perf&lod=NaN")).toBeNull();
    expect(lod("?perf&lod=Infinity")).toBeNull();
    expect(lod(`?perf&lod=${LOD_MAX_ZOOM_LEVELS_RANGE.max + 1}`)).toBeNull();
    expect(lod(`?perf&lod=${LOD_MAX_ZOOM_LEVELS_RANGE.min - 1}`)).toBeNull();
  });

  it("takes the ends of its own range", () => {
    expect(lod(`?perf&lod=${LOD_MAX_ZOOM_LEVELS_RANGE.min}`)).toBe(LOD_MAX_ZOOM_LEVELS_RANGE.min);
    expect(lod(`?perf&lod=${LOD_MAX_ZOOM_LEVELS_RANGE.max}`)).toBe(LOD_MAX_ZOOM_LEVELS_RANGE.max);
  });
});

describe("parseRefreshExpiredTiles", () => {
  it("distinguishes an explicit control arm from an absent flag", () => {
    // Both leave the shipped default in place, but `refresh=off` appears in origin.flags, so the
    // control arm of a sweep is identifiable by what it SAYS rather than by what it lacks.
    expect(refresh("?perf&refresh=off")).toBe(false);
    expect(refresh("?perf")).toBeNull();
  });

  it("takes named modes only, so a number cannot round into a silent arm", () => {
    expect(refresh("?perf&refresh=1")).toBeNull();
    expect(refresh("?perf&refresh=true")).toBeNull();
    expect(refresh("?perf&refresh=")).toBeNull();
    expect([...REFRESH_MODES]).toEqual(["on", "off"]);
  });

  it("is not case- or whitespace-sensitive, since a hand-typed arm is a hand-typed arm", () => {
    expect(refresh("?perf&refresh=ON")).toBe(true);
    expect(refresh("?perf&refresh=%20off%20")).toBe(false);
  });
});
