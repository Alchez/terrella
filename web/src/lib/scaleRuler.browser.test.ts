import { afterEach, describe, expect, it } from "vitest";
import { FIXTURE_HEIGHT_PX, FIXTURE_WIDTH_PX, mountGlobe, type MountedGlobe } from "./testing/mountGlobe";
import { RULER_WIDTH_PX, formatGroundDistance, rulerGroundDistance } from "./scaleRuler";

/**
 * The ruler measured against a REAL globe transform, at real zooms.
 *
 * WHY THIS EXISTS, AND WHAT IT DELIBERATELY DOES NOT COVER. The ruler once shipped frozen — one
 * label at every zoom — and everything was green: the unit tests (which feed a fake `locate`, so
 * they cannot tell a live camera from a dead one), the source guards, the bundle canary, and the
 * readPixels metric the fix targeted. The cause was a captured transform reference, and
 * `scaleRuler.test.ts` now pins that mechanism by reading the page's own text: the lookup must be
 * inside the per-call function, there must be exactly one `unproject`, and no terrain may be named.
 * That guard is the right shape for the mechanism and this file does not duplicate it.
 *
 * What no source assertion can reach is the OUTCOME: whether the arithmetic, driven by a real
 * spherical transform, produces values that are correct and that move. That is this file, and the
 * split is deliberate — the source test proves the page uses the contracted locator, this one
 * proves the contracted locator produces a true reading.
 *
 * THE ORACLE IS INDEPENDENT, which is the only reason the numbers here mean anything. A ruler
 * checked against another call to the same transform would agree with itself no matter how wrong
 * it was. Instead the expectation is computed from the Web-Mercator ground-resolution identity —
 * `circumference / (tilePx * 2^zoom)` — using MapLibre's own globe radius, arithmetic the ruler
 * never performs. Measured agreement at z6-z8 is within 0.03%.
 */

/** MapLibre's globe radius, from its `_projection.vertex.glsl`: `#define GLOBE_RADIUS 6371008.8`. */
const GLOBE_RADIUS_M = 6371008.8;
/** MapLibre's internal tile size in CSS px — the unit `2^zoom` scales, independent of our assets. */
const MERCATOR_TILE_PX = 512;

/** Ground metres one CSS pixel spans at the equator, at `zoom`. Independent of anything under test. */
function expectedMetresPerPixel(zoom: number): number {
  return (2 * Math.PI * GLOBE_RADIUS_M) / (MERCATOR_TILE_PX * 2 ** zoom);
}

let mounted: MountedGlobe | null = null;

afterEach(() => {
  mounted?.dispose();
  mounted = null;
});

/**
 * Read the ruler the way the page does: the transform's own datum conversion, looked up PER CALL.
 *
 * A plain `{x, y}` is accepted — verified against the live object rather than assumed, which is
 * why this needs no `maplibregl.Point` import.
 */
function readRuler(globe: MountedGlobe): number {
  const painter = globe.map as unknown as { painter: { transform: Record<string, unknown> } };
  const locate = ([x, y]: [number, number]) => {
    const transform = painter.painter.transform;
    const convert = transform.screenPointToLocation as (point: { x: number; y: number }) => {
      distanceTo(other: unknown): number;
    };
    return convert.call(transform, { x, y });
  };
  return rulerGroundDistance(locate, FIXTURE_WIDTH_PX, FIXTURE_HEIGHT_PX);
}

/** Zooms swept for the tracking assertions. Spans the range the globe actually serves. */
const SWEEP = [0, 1, 2, 3, 4, 5, 6, 7, 8];
/** Zooms the oracle is checked at. Below z6 the 96 px span subtends enough arc that the flat
 *  ground-resolution identity is no longer the right model — measured 0.12% out at z4 against
 *  0.03% at z6, so the tolerance would have to be loosened past the point of saying anything. */
const ORACLE_ZOOMS = [6, 7, 8];

describe("the ruler tracks a real camera", () => {
  it("reports a finite, positive distance at every zoom the globe serves", async () => {
    mounted = await mountGlobe({ zoom: 0 });
    for (const zoom of SWEEP) {
      mounted.map.jumpTo({ zoom, center: [0, 0] });
      const metres = readRuler(mounted);
      expect(Number.isFinite(metres), `z${zoom} produced ${metres}`).toBe(true);
      expect(metres, `z${zoom} produced ${metres}`).toBeGreaterThan(0);
      // The label must never be the em-dash placeholder for a camera that is simply parked.
      expect(formatGroundDistance(metres)).not.toBe("—");
    }
  });

  it("takes a DISTINCT label at every zoom, which is the assertion the frozen ruler failed", async () => {
    mounted = await mountGlobe({ zoom: 0 });
    const labels: string[] = [];
    for (const zoom of SWEEP) {
      mounted.map.jumpTo({ zoom, center: [0, 0] });
      labels.push(formatGroundDistance(readRuler(mounted)));
    }
    // The whole class this file exists for — stale reference, dead listener, thrown handler — ends
    // as a label that renders plausibly and never changes. One assertion covers all of them.
    expect(new Set(labels).size, `labels were ${labels.join(", ")}`).toBe(SWEEP.length);
  });

  it("shrinks monotonically as the camera closes in", async () => {
    mounted = await mountGlobe({ zoom: 0 });
    const readings: number[] = [];
    for (const zoom of SWEEP) {
      mounted.map.jumpTo({ zoom, center: [0, 0] });
      readings.push(readRuler(mounted));
    }
    for (let index = 1; index < readings.length; index += 1) {
      // Direction, not magnitude: an inverted conversion still produces distinct labels and would
      // sail through the test above.
      expect(readings[index], `z${SWEEP[index]} did not shrink from z${SWEEP[index - 1]}`).toBeLessThan(
        readings[index - 1],
      );
    }
  });

  it("agrees with the ground-resolution identity, which the ruler never computes", async () => {
    mounted = await mountGlobe({ zoom: ORACLE_ZOOMS[0] });
    for (const zoom of ORACLE_ZOOMS) {
      mounted.map.jumpTo({ zoom, center: [0, 0] });
      const expected = expectedMetresPerPixel(zoom) * RULER_WIDTH_PX;
      const actual = readRuler(mounted);
      const error = Math.abs(actual - expected) / expected;
      // 1% is loose against the 0.03% measured, and deliberately so: it is sized to catch the
      // failures that matter — a wrong body radius (Mars differs from Earth by 47%), a metre/km
      // unit slip, a 256-vs-512 tile-size confusion — without pinning the residual curvature term.
      expect(error, `z${zoom}: ruler ${Math.round(actual)} m vs oracle ${Math.round(expected)} m`).toBeLessThan(
        0.01,
      );
    }
  });

  it("halves per zoom level once curvature over the span stops mattering", async () => {
    mounted = await mountGlobe({ zoom: 4 });
    const readings: number[] = [];
    for (const zoom of [4, 5, 6, 7, 8]) {
      mounted.map.jumpTo({ zoom, center: [0, 0] });
      readings.push(readRuler(mounted));
    }
    for (let index = 1; index < readings.length; index += 1) {
      // A zoom level is a factor of two by definition. Pinning the RATIO rather than the values
      // catches a scale error that happens to preserve ordering, which monotonicity cannot see.
      expect(readings[index - 1] / readings[index]).toBeCloseTo(2, 1);
    }
  });
});
