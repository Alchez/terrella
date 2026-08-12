// The arm label reaches this function straight off a query string, so most of what is asserted
// here is what it REFUSES to put in a path.

import { describe, expect, it } from "vitest";
import { PERF_CAPTURE_ARM_MAX, perfCaptureName, slugifyArm } from "./perfCaptureName";

const STAMP = "2026-08-12T14-20-00-000Z";

describe("slugifyArm", () => {
  it("keeps a label a reader would recognise", () => {
    expect(slugifyArm("refresh-true")).toBe("refresh-true");
    expect(slugifyArm("M11 pitch60")).toBe("m11-pitch60");
  });

  it("cannot emit a path separator or a dot, so traversal has nothing to work with", () => {
    // Allow-listed, not escaped: `..` and `/` need no special case because neither character is in
    // the output alphabet. Asserted on the OUTPUT rather than on a list of inputs, so the property
    // holds for attacks nobody wrote a case for.
    for (const hostile of ["../../etc/passwd", "..", "./.", "a/b\\c", "%2e%2e%2f"]) {
      const slug = slugifyArm(hostile);
      expect(slug === null || /^[a-z0-9-]+$/.test(slug), `${hostile} -> ${slug}`).toBe(true);
    }
    expect(slugifyArm("../../etc/passwd")).toBe("etc-passwd");
  });

  it("returns null when nothing survives, rather than inventing a name", () => {
    // A capture named for a label that was never usable is a false record, and the caller asked
    // for a name it did not get — which the absence of a suffix makes visible.
    expect(slugifyArm("")).toBeNull();
    expect(slugifyArm("...")).toBeNull();
    expect(slugifyArm("///")).toBeNull();
    expect(slugifyArm(null)).toBeNull();
    expect(slugifyArm(undefined)).toBeNull();
  });

  it("caps length without leaving a trailing separator the cut would otherwise show", () => {
    const long = slugifyArm(`${"a".repeat(38)}--${"b".repeat(20)}`);
    expect(long).not.toBeNull();
    expect(long!.length).toBeLessThanOrEqual(PERF_CAPTURE_ARM_MAX);
    expect(long!.endsWith("-")).toBe(false);
  });
});

describe("perfCaptureName", () => {
  it("puts the timestamp first, so one run's arms sort adjacent", () => {
    // The comparison that matters is between arms of the SAME run. Arm-first would interleave runs
    // and split the only grouping anyone reads.
    const names = [
      perfCaptureName(STAMP, "default"),
      perfCaptureName(STAMP, "refresh-true"),
      perfCaptureName("2026-08-12T15-00-00-000Z", "default"),
    ].toSorted();
    expect(names[0]).toContain(STAMP);
    expect(names[1]).toContain(STAMP);
    expect(names[2]).toContain("15-00-00");
  });

  it("is unchanged from the old scheme when no arm is given", () => {
    // Every existing capture in the directory is this shape, and an ad-hoc export still is.
    expect(perfCaptureName(STAMP, null)).toBe(`${STAMP}.json`);
    expect(perfCaptureName(STAMP, "   ")).toBe(`${STAMP}.json`);
  });

  it("appends the arm when there is one", () => {
    expect(perfCaptureName(STAMP, "refresh=true")).toBe(`${STAMP}-refresh-true.json`);
  });
});
