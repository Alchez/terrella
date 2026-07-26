import { describe, it, expect, vi } from "vitest";
import { readFileSync } from "node:fs";
import { createHoverTracker } from "./hoverTracking";

// --- fixture ---------------------------------------------------------------------------------
// A fake globe: `land` maps a pixel column to the country under it, and rotate() rewrites that map
// WITHOUT any pointer event — which is exactly the situation the tracker exists to survive (a drag,
// a zoom, the fly-to, a spin step, all moving the world under a pointer that never moved).

interface ScreenPoint {
  x: number;
}

function fakeGlobe(land: Record<number, string>) {
  let currentLand = land;
  const resolve = vi.fn((point: ScreenPoint) => currentLand[point.x] ?? null);
  return {
    resolve,
    rotate(next: Record<number, string>) {
      currentLand = next;
    },
  };
}

function trackerOver(land: Record<number, string>) {
  const globe = fakeGlobe(land);
  const onChange = vi.fn<(admin: string | null, previousAdmin: string | null) => void>();
  const tracker = createHoverTracker<ScreenPoint>({ resolve: globe.resolve, onChange });
  return { tracker, globe, onChange };
}

describe("createHoverTracker", () => {
  describe("pointer movement", () => {
    it("resolves the country under the pointer", () => {
      const { tracker, onChange } = trackerOver({ 10: "Nepal" });

      tracker.pointerMoved({ x: 10 });

      expect(tracker.current()).toBe("Nepal");
      expect(onChange).toHaveBeenCalledExactlyOnceWith("Nepal", null);
    });

    it("reports sea as null", () => {
      const { tracker, onChange } = trackerOver({ 10: "Nepal" });

      tracker.pointerMoved({ x: 10 });
      tracker.pointerMoved({ x: 99 }); // open ocean

      expect(tracker.current()).toBeNull();
      expect(onChange).toHaveBeenLastCalledWith(null, "Nepal");
    });

    it("does not re-announce a country the pointer is still on", () => {
      // The real handler fires on every mousemove; a country spans thousands of them, and each
      // redundant onChange would be a setFeatureState pair plus a chip write.
      const { tracker, onChange } = trackerOver({ 10: "Nepal", 11: "Nepal", 12: "Nepal" });

      tracker.pointerMoved({ x: 10 });
      tracker.pointerMoved({ x: 11 });
      tracker.pointerMoved({ x: 12 });

      expect(onChange).toHaveBeenCalledExactlyOnceWith("Nepal", null);
    });
  });

  describe("camera movement under a stationary pointer", () => {
    it("announces the new country after a drag, with no pointer event", () => {
      // THE STALENESS FIX. Before it, hover only ever recomputed on mousemove, so this sequence
      // left the highlight — and would leave the name chip — reading "Nepal" over India.
      const { tracker, globe, onChange } = trackerOver({ 10: "Nepal" });
      tracker.pointerMoved({ x: 10 });
      onChange.mockClear();

      globe.rotate({ 10: "India" }); // the drag: same pixel, different country
      tracker.viewChanged();

      expect(tracker.current()).toBe("India");
      expect(onChange).toHaveBeenCalledExactlyOnceWith("India", "Nepal");
    });

    it("stays quiet when the camera moves but the country under the pointer does not", () => {
      // A spin step drifts the surface ~5 px; most steps land inside the same country, and those
      // must not repaint the highlight or rewrite the chip.
      const { tracker, globe, onChange } = trackerOver({ 10: "Nepal" });
      tracker.pointerMoved({ x: 10 });
      onChange.mockClear();

      globe.rotate({ 10: "Nepal" });
      tracker.viewChanged();

      expect(onChange).not.toHaveBeenCalled();
    });

    it("clears the hover when the globe turns the land out from under the pointer", () => {
      const { tracker, globe, onChange } = trackerOver({ 10: "Nepal" });
      tracker.pointerMoved({ x: 10 });
      onChange.mockClear();

      globe.rotate({}); // all sea now
      tracker.viewChanged();

      expect(tracker.current()).toBeNull();
      expect(onChange).toHaveBeenCalledExactlyOnceWith(null, "Nepal");
    });
  });

  describe("no pointer on the map", () => {
    it("resolves nothing when the camera moves before the pointer ever arrives", () => {
      // moveend fires during load and during the opening fly-to, long before any mousemove.
      const { tracker, globe, onChange } = trackerOver({ 10: "Nepal" });

      tracker.viewChanged();

      expect(globe.resolve).not.toHaveBeenCalled();
      expect(onChange).not.toHaveBeenCalled();
      expect(tracker.current()).toBeNull();
    });

    it("resolves nothing when the camera moves after the pointer leaves", () => {
      // Leaving the canvas dismisses the hover; a later camera move must not revive it from a
      // position the pointer no longer occupies.
      const { tracker, globe, onChange } = trackerOver({ 10: "Nepal" });
      tracker.pointerMoved({ x: 10 });
      tracker.pointerLeft();
      globe.resolve.mockClear();
      onChange.mockClear();

      globe.rotate({ 10: "India" });
      tracker.viewChanged();

      expect(globe.resolve).not.toHaveBeenCalled();
      expect(onChange).not.toHaveBeenCalled();
      expect(tracker.current()).toBeNull();
    });

    it("clears the hover when the pointer leaves over land", () => {
      const { tracker, onChange } = trackerOver({ 10: "Nepal" });
      tracker.pointerMoved({ x: 10 });
      onChange.mockClear();

      tracker.pointerLeft();

      expect(tracker.current()).toBeNull();
      expect(onChange).toHaveBeenCalledExactlyOnceWith(null, "Nepal");
    });

    it("says nothing when the pointer leaves over sea", () => {
      const { tracker, onChange } = trackerOver({ 10: "Nepal" });

      tracker.pointerLeft();

      expect(onChange).not.toHaveBeenCalled();
    });
  });
});

describe("the staleness contract", () => {
  it("globe.astro re-resolves the hover on moveend", () => {
    const source = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");
    const boundToMoveEnd = /map\.on\(\s*["']moveend["'][\s\S]{0,200}?viewChanged/.test(source);
    expect(
      boundToMoveEnd,
      "globe.astro must call hoverTracker.viewChanged() from a `moveend` handler. Hover is " +
        "otherwise only ever recomputed on mousemove, so a drag, a zoom, the country fly-to and " +
        "every spin step leave the outline, the cursor AND the name chip describing the country " +
        "that used to be under the pointer — unbounded until the next mouse jiggle. Every unit " +
        "test above stays green without this line; nothing else catches its removal.",
    ).toBe(true);
  });
});
