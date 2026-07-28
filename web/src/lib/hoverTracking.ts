// Hover resolution for the globe: WHICH country the pointer is on, kept true as the globe moves.
//
// Factored out of globe.astro for the same reason countryHighlight.ts was — the wiring is
// load-bearing and a future edit would break it silently. The non-obvious member is viewChanged().
//
// Hover used to be recomputed on pointer movement alone, so any camera move under a parked pointer
// left the highlight on the country that USED to be there: unbounded after a drag or a zoom, 2.2 s
// after the fly-to, one step during auto-spin. That was invisible while the highlight was an
// anonymous gold outline, and stops being invisible the moment a chip states the name — so the
// caller MUST also drive viewChanged() from `moveend`.
//
// The tracker never inspects a point, it only caches one and replays it, hence the type parameter:
// globe.astro passes MapLibre's Point, tests pass a plain object, and this module imports neither.
//
// RESOLUTION IS COALESCED TO ONE PER FRAME, and that is a performance fix with a measured cause.
// `resolve` is globe.astro's countryAt, i.e. queryRenderedFeatures — and with terrain enabled that
// routes through terrain.pointCoordinate, which renders tile coordinates into a 1024x1024 offscreen
// framebuffer and readPixels it back. That is a synchronous GPU stall: measured 2.2-2.4 ms with
// terrain against 0.2 ms without, and the camera invalidates the framebuffer every frame so it
// cannot be cached. Meanwhile `mousemove` was bound straight through to a synchronous resolve, and
// a 500-1000 Hz mouse delivers several moves per frame — so a 165 Hz budget of 6.06 ms was being
// oversubscribed 2-4x by hover alone. At 0.2 ms the missing coalesce never mattered; terrain did
// not create this bug, it made it affordable to notice.

export interface HoverTrackerOptions<TPoint> {
  /** Which country (Natural Earth ADMIN) is under this screen point, or null for sea. */
  resolve: (point: TPoint) => string | null;
  /**
   * Called ONLY when the answer actually changes — never once per pointer move.
   *
   * `previousAdmin` is what the hover is LEAVING. Feature-state highlighting has to clear the old
   * country as well as set the new one, and handing both over here is what lets the caller keep
   * no hover state of its own — the tracker is the single owner.
   */
  onChange: (admin: string | null, previousAdmin: string | null) => void;
  /**
   * Defers a coalesced resolve to the next frame. Defaults to the browser's
   * `requestAnimationFrame`, which is the only correct choice in production: it is the clock the
   * cost is measured against, and it stops resolving entirely while the tab is hidden.
   *
   * Injectable so tests can drive the clock by hand. They must: an auto-flushing fake would make
   * "queued" and "ran" indistinguishable, and the coalesce is precisely the difference.
   */
  scheduleFrame?: (callback: () => void) => void;
}

export interface HoverTracker<TPoint> {
  /**
   * The pointer moved to a new screen point. Caches it immediately; resolves at most once on the
   * next frame however many times this is called before then.
   */
  pointerMoved(point: TPoint): void;
  /**
   * The pointer left the canvas: clears the hover AND the cached point, SYNCHRONOUSLY.
   *
   * Deliberately not deferred. Leaving is the one event a frame of latency is visible on — the
   * chip and the gold outline would linger over empty canvas — and nulling the cached point is
   * also what makes a queued resolve stand down, so no cancellation handle is needed.
   */
  pointerLeft(): void;
  /** The camera moved under a stationary pointer — re-resolve at the cached point. */
  viewChanged(): void;
  /** The currently hovered ADMIN, or null. */
  current(): string | null;
}

/** Production's frame clock. Referenced through `globalThis` rather than imported, so the module
 *  keeps its one dependency-free property — and throws loudly off the browser instead of silently
 *  falling back to a synchronous resolve, which would look like it worked and coalesce nothing. */
const browserFrame = (callback: () => void): void => {
  globalThis.requestAnimationFrame(callback);
};

export function createHoverTracker<TPoint>({
  resolve,
  onChange,
  scheduleFrame = browserFrame,
}: HoverTrackerOptions<TPoint>): HoverTracker<TPoint> {
  let lastPointerPosition: TPoint | null = null;
  let hoveredAdmin: string | null = null;
  let resolveScheduled = false;

  /** Every caller re-resolves far more often than the answer changes (once per pointer move, once
   *  per moveend), so the transition check lives here rather than in each of them. */
  function setHovered(admin: string | null) {
    if (admin === hoveredAdmin) return;
    const previousAdmin = hoveredAdmin;
    hoveredAdmin = admin;
    onChange(admin, previousAdmin);
  }

  /** Queue one resolve for the next frame, or join the one already queued.
   *
   *  Both callers land here, so a pointer move and a `moveend` arriving in the same frame cost one
   *  resolve between them rather than two — they would resolve the same cached point anyway.
   *  Whatever position is cached WHEN THE FRAME RUNS is the one used, so a burst of moves resolves
   *  where the pointer ended up, never where it passed through. */
  function scheduleResolve() {
    if (resolveScheduled) return;
    resolveScheduled = true;
    scheduleFrame(() => {
      resolveScheduled = false;
      // The pointer left between the schedule and the frame: pointerLeft already announced null,
      // and resolving a position it no longer occupies is exactly the revival that must not happen.
      if (lastPointerPosition === null) return;
      setHovered(resolve(lastPointerPosition));
    });
  }

  return {
    pointerMoved(point) {
      lastPointerPosition = point;
      scheduleResolve();
    },

    pointerLeft() {
      lastPointerPosition = null;
      setHovered(null);
    },

    viewChanged() {
      // No cached point means the pointer is not over the canvas at all. Re-resolving anyway would
      // need a stale position and could revive a hover the user already dismissed by leaving, so a
      // camera move with no pointer on the map is deliberately a no-op — nothing is even queued.
      if (lastPointerPosition === null) return;
      scheduleResolve();
    },

    current() {
      return hoveredAdmin;
    },
  };
}
