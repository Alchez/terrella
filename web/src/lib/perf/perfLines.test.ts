import { describe, expect, it } from "vitest";
import {
  PERF_GROUP_HEADINGS,
  PERF_GROUP_ORDER,
  groupPerfLines,
  type PerfGroup,
  type PerfLine,
} from "./perfLines";

/** A line in every group, in a deliberately scrambled order, so nothing passes by accident. */
const ONE_PER_GROUP: PerfLine[] = [
  { group: "config", text: "terrain 15.0x" },
  { group: "origin", text: "origin static build" },
  { group: "cpu", text: "long tasks 13" },
  { group: "alarm", text: "FAULT dem cache uncapped" },
  { group: "device", text: "device mobile-class" },
  { group: "feel", text: "fps 58" },
  { group: "gpu", text: "caps 68 MB" },
  { group: "ram", text: "dem 0/384 MB" },
  { group: "network", text: "tiles relief 78" },
];

describe("the group table", () => {
  it("orders every group exactly once — a group missing here renders NO lines at all", () => {
    // The one failure this shape cannot catch at compile time. `PERF_GROUP_HEADINGS` being a
    // Record over the union means a new group must declare a heading, but nothing forces it into
    // the order array — and a group absent from the order array is skipped by the render loop, so
    // its lines disappear from the panel without a heading, a gap, or an error to notice.
    const headingKeys = Object.keys(PERF_GROUP_HEADINGS) as PerfGroup[];
    expect([...PERF_GROUP_ORDER].sort()).toEqual([...headingKeys].sort());
    expect(new Set(PERF_GROUP_ORDER).size).toBe(PERF_GROUP_ORDER.length);
  });

  it("keeps the two positional promises: alarms first, origin last", () => {
    // Not merely "somewhere in the order". Faults are the one row that must never be skipped, and
    // the origin line is what stops a cropped screenshot being unattributable to an arm.
    expect(PERF_GROUP_ORDER[0]).toBe("alarm");
    expect(PERF_GROUP_ORDER.at(-1)).toBe("origin");
  });

  it("renders alarms and origin without a heading, and every subsystem with one", () => {
    expect(PERF_GROUP_HEADINGS.alarm).toBeNull();
    expect(PERF_GROUP_HEADINGS.origin).toBeNull();
    for (const group of PERF_GROUP_ORDER) {
      if (group === "alarm" || group === "origin") continue;
      expect(PERF_GROUP_HEADINGS[group]).toBeTruthy();
    }
  });
});

describe("groupPerfLines", () => {
  it("renders the groups in PERF_GROUP_ORDER regardless of composition order", () => {
    expect(groupPerfLines(ONE_PER_GROUP)).toEqual([
      "FAULT dem cache uncapped",
      "",
      "FEEL",
      "fps 58",
      "",
      "CPU · MAIN THREAD",
      "long tasks 13",
      "",
      "NETWORK",
      "tiles relief 78",
      "",
      "GPU · VRAM",
      "caps 68 MB",
      "",
      "RAM",
      "dem 0/384 MB",
      "",
      "DEVICE",
      "device mobile-class",
      "",
      "CONFIG",
      "terrain 15.0x",
      "",
      "origin static build",
    ]);
  });

  it("omits a group with no lines entirely — no orphan heading, no double blank", () => {
    // The ordinary case, not an edge one: `caps` is absent without polar caps, `fill` before the
    // first gesture, and the alarm block on every healthy run.
    const rendered = groupPerfLines([
      { group: "feel", text: "fps 58" },
      { group: "config", text: "sky 0.42" },
    ]);
    expect(rendered).toEqual(["FEEL", "fps 58", "", "CONFIG", "sky 0.42"]);
    expect(rendered).not.toContain("NETWORK");
    expect(rendered.join("\n")).not.toContain("\n\n\n");
  });

  it("separates groups rather than introducing them — never leads or trails with a blank", () => {
    const rendered = groupPerfLines(ONE_PER_GROUP);
    expect(rendered[0]).not.toBe("");
    expect(rendered.at(-1)).not.toBe("");
  });

  it("keeps composition order within a group", () => {
    // The DEM cache line and the caps line are both GPU memory and come from different modules;
    // which reads first is decided where they are composed, not by a second sort in here.
    expect(
      groupPerfLines([
        { group: "gpu", text: "dem cache 381/1155 slots" },
        { group: "gpu", text: "caps 68 MB" },
      ]),
    ).toEqual(["GPU · VRAM", "dem cache 381/1155 slots", "caps 68 MB"]);
  });

  it("renders nothing at all for no lines", () => {
    expect(groupPerfLines([])).toEqual([]);
  });
});
