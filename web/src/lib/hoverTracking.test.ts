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

// The frame clock is driven BY HAND, never auto-flushed. Coalescing is the whole point of the
// scheduler, so a fake that ran the callback immediately would make "queued" and "ran"
// indistinguishable and every assertion below would pass without a coalesce existing at all.
function trackerOver(land: Record<number, string>) {
  const globe = fakeGlobe(land);
  const onChange = vi.fn<(admin: string | null, previousAdmin: string | null) => void>();
  let queued: (() => void)[] = [];
  const tracker = createHoverTracker<ScreenPoint>({
    resolve: globe.resolve,
    onChange,
    scheduleFrame: (callback) => queued.push(callback),
  });
  return {
    tracker,
    globe,
    onChange,
    /** Run the frame the tracker asked for, as the browser would. */
    flushFrame() {
      const running = queued;
      queued = [];
      for (const callback of running) callback();
    },
    framesQueued: () => queued.length,
  };
}

describe("createHoverTracker", () => {
  describe("pointer movement", () => {
    it("resolves the country under the pointer", () => {
      const { tracker, onChange, flushFrame } = trackerOver({ 10: "Nepal" });

      tracker.pointerMoved({ x: 10 });
      flushFrame();

      expect(tracker.current()).toBe("Nepal");
      expect(onChange).toHaveBeenCalledExactlyOnceWith("Nepal", null);
    });

    it("reports sea as null", () => {
      const { tracker, onChange, flushFrame } = trackerOver({ 10: "Nepal" });

      tracker.pointerMoved({ x: 10 });
      flushFrame();
      tracker.pointerMoved({ x: 99 }); // open ocean
      flushFrame();

      expect(tracker.current()).toBeNull();
      expect(onChange).toHaveBeenLastCalledWith(null, "Nepal");
    });

    it("does not re-announce a country the pointer is still on", () => {
      // The real handler fires on every mousemove; a country spans thousands of them, and each
      // redundant onChange would be a setFeatureState pair plus a chip write.
      // A frame between each move on purpose: coalescing would collapse them anyway, and then
      // this test would be proving the coalesce rather than setHovered's equality check.
      const { tracker, onChange, flushFrame } = trackerOver({ 10: "Nepal", 11: "Nepal", 12: "Nepal" });

      for (const x of [10, 11, 12]) {
        tracker.pointerMoved({ x });
        flushFrame();
      }

      expect(onChange).toHaveBeenCalledExactlyOnceWith("Nepal", null);
    });
  });

  describe("camera movement under a stationary pointer", () => {
    it("announces the new country after a drag, with no pointer event", () => {
      // THE STALENESS FIX. Before it, hover only ever recomputed on mousemove, so this sequence
      // left the highlight — and would leave the name chip — reading "Nepal" over India.
      const { tracker, globe, onChange, flushFrame } = trackerOver({ 10: "Nepal" });
      tracker.pointerMoved({ x: 10 });
      flushFrame();
      onChange.mockClear();

      globe.rotate({ 10: "India" }); // the drag: same pixel, different country
      tracker.viewChanged();
      flushFrame();

      expect(tracker.current()).toBe("India");
      expect(onChange).toHaveBeenCalledExactlyOnceWith("India", "Nepal");
    });

    it("stays quiet when the camera moves but the country under the pointer does not", () => {
      // A spin step drifts the surface ~5 px; most steps land inside the same country, and those
      // must not repaint the highlight or rewrite the chip.
      const { tracker, globe, onChange, flushFrame } = trackerOver({ 10: "Nepal" });
      tracker.pointerMoved({ x: 10 });
      flushFrame();
      onChange.mockClear();

      globe.rotate({ 10: "Nepal" });
      tracker.viewChanged();
      flushFrame();

      expect(onChange).not.toHaveBeenCalled();
    });

    it("clears the hover when the globe turns the land out from under the pointer", () => {
      const { tracker, globe, onChange, flushFrame } = trackerOver({ 10: "Nepal" });
      tracker.pointerMoved({ x: 10 });
      flushFrame();
      onChange.mockClear();

      globe.rotate({}); // all sea now
      tracker.viewChanged();
      flushFrame();

      expect(tracker.current()).toBeNull();
      expect(onChange).toHaveBeenCalledExactlyOnceWith(null, "Nepal");
    });
  });

  describe("no pointer on the map", () => {
    it("resolves nothing when the camera moves before the pointer ever arrives", () => {
      // moveend fires during load and during the opening fly-to, long before any mousemove.
      const { tracker, globe, onChange, flushFrame, framesQueued } = trackerOver({ 10: "Nepal" });

      tracker.viewChanged();
      expect(framesQueued(), "a pointerless camera move must not even queue a frame").toBe(0);
      flushFrame();

      expect(globe.resolve).not.toHaveBeenCalled();
      expect(onChange).not.toHaveBeenCalled();
      expect(tracker.current()).toBeNull();
    });

    it("resolves nothing when the camera moves after the pointer leaves", () => {
      // Leaving the canvas dismisses the hover; a later camera move must not revive it from a
      // position the pointer no longer occupies.
      const { tracker, globe, onChange, flushFrame } = trackerOver({ 10: "Nepal" });
      tracker.pointerMoved({ x: 10 });
      flushFrame();
      tracker.pointerLeft();
      globe.resolve.mockClear();
      onChange.mockClear();

      globe.rotate({ 10: "India" });
      tracker.viewChanged();
      flushFrame();

      expect(globe.resolve).not.toHaveBeenCalled();
      expect(onChange).not.toHaveBeenCalled();
      expect(tracker.current()).toBeNull();
    });

    it("clears the hover when the pointer leaves over land", () => {
      const { tracker, onChange, flushFrame } = trackerOver({ 10: "Nepal" });
      tracker.pointerMoved({ x: 10 });
      flushFrame();
      onChange.mockClear();

      tracker.pointerLeft(); // no flush: leaving must not wait for a frame

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

// Every test above would pass with the resolve left synchronous, because they all flush before
// asserting. These are the ones that fail if the coalesce is removed.
describe("coalescing to one resolve per frame", () => {
  it("resolves ONCE however many moves arrive in a frame", () => {
    // The measured cause: with terrain on, one resolve is a queryRenderedFeatures through
    // terrain.pointCoordinate — a 1024x1024 readPixels GPU stall at 2.2-2.4 ms, against a 6.06 ms
    // budget at 165 Hz. A 500-1000 Hz mouse delivers several of these per frame.
    const { tracker, globe, flushFrame, framesQueued } = trackerOver({ 10: "Nepal", 40: "India" });

    for (let x = 10; x <= 40; x += 1) tracker.pointerMoved({ x });
    expect(framesQueued(), "31 moves must queue one frame, not 31").toBe(1);
    expect(globe.resolve, "nothing may resolve before the frame runs").not.toHaveBeenCalled();
    flushFrame();

    expect(globe.resolve).toHaveBeenCalledTimes(1);
  });

  it("resolves where the pointer ENDED UP, not where it entered the frame", () => {
    // Coalescing is only correct if it keeps the last point. Keeping the first would lag the chip
    // behind the cursor by a frame during every fast sweep.
    const { tracker, globe, onChange, flushFrame } = trackerOver({ 10: "Nepal", 40: "India" });

    tracker.pointerMoved({ x: 10 });
    tracker.pointerMoved({ x: 40 });
    flushFrame();

    expect(globe.resolve).toHaveBeenCalledExactlyOnceWith({ x: 40 });
    expect(onChange).toHaveBeenCalledExactlyOnceWith("India", null);
  });

  it("charges a move and a moveend in the same frame one resolve between them", () => {
    // Both resolve the same cached point, so the second would be pure duplicated cost — and a drag
    // produces exactly this pairing, which is the case the fix is aimed at.
    const { tracker, globe, flushFrame, framesQueued } = trackerOver({ 10: "Nepal" });

    tracker.pointerMoved({ x: 10 });
    tracker.viewChanged();
    expect(framesQueued()).toBe(1);
    flushFrame();

    expect(globe.resolve).toHaveBeenCalledTimes(1);
  });

  it("stands a queued resolve down when the pointer leaves first", () => {
    // THE correctness case, not a performance one. The frame was queued while the pointer was over
    // Nepal; by the time it runs the pointer has left and the hover has been dismissed. Resolving
    // anyway would re-announce Nepal over an empty canvas, with no event left to clear it.
    const { tracker, globe, onChange, flushFrame } = trackerOver({ 10: "Nepal" });

    tracker.pointerMoved({ x: 10 });
    tracker.pointerLeft();
    onChange.mockClear();
    globe.resolve.mockClear();
    flushFrame();

    expect(globe.resolve).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
    expect(tracker.current()).toBeNull();
  });

  it("keeps resolving after a frame has run, rather than latching shut", () => {
    // The scheduled flag has to be cleared INSIDE the frame. Leaving it set would coalesce the
    // whole session into one resolve — every test above still passes, and hover dies after the
    // first frame.
    const { tracker, globe, flushFrame } = trackerOver({ 10: "Nepal", 20: "India" });

    tracker.pointerMoved({ x: 10 });
    flushFrame();
    tracker.pointerMoved({ x: 20 });
    flushFrame();

    expect(globe.resolve).toHaveBeenCalledTimes(2);
    expect(tracker.current()).toBe("India");
  });

  it("defaults to the browser's requestAnimationFrame when no clock is injected", () => {
    // earth.astro injects nothing, so the default is what ships. A silent synchronous fallback
    // would coalesce nothing while every test here stayed green.
    const requestAnimationFrame = vi.fn<(callback: () => void) => number>();
    vi.stubGlobal("requestAnimationFrame", requestAnimationFrame);
    try {
      const tracker = createHoverTracker<ScreenPoint>({ resolve: () => "Nepal", onChange: vi.fn() });
      tracker.pointerMoved({ x: 10 });
      expect(requestAnimationFrame).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("the staleness contract", () => {
  it("earth.astro re-resolves the hover on moveend", () => {
    const source = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");
    const boundToMoveEnd = /map\.on\(\s*["']moveend["'][\s\S]{0,200}?viewChanged/.test(source);
    expect(
      boundToMoveEnd,
      "earth.astro must call hoverTracker.viewChanged() from a `moveend` handler. Hover is " +
        "otherwise only ever recomputed on mousemove, so a drag, a zoom, the country fly-to and " +
        "every spin step leave the outline, the cursor AND the name chip describing the country " +
        "that used to be under the pointer — unbounded until the next mouse jiggle. Every unit " +
        "test above stays green without this line; nothing else catches its removal.",
    ).toBe(true);
  });
});
