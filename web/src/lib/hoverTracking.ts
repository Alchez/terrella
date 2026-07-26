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
}

export interface HoverTracker<TPoint> {
  /** The pointer moved to a new screen point. Caches it for later re-resolution. */
  pointerMoved(point: TPoint): void;
  /** The pointer left the canvas: clears the hover AND the cached point. */
  pointerLeft(): void;
  /** The camera moved under a stationary pointer — re-resolve at the cached point. */
  viewChanged(): void;
  /** The currently hovered ADMIN, or null. */
  current(): string | null;
}

export function createHoverTracker<TPoint>({
  resolve,
  onChange,
}: HoverTrackerOptions<TPoint>): HoverTracker<TPoint> {
  let lastPointerPosition: TPoint | null = null;
  let hoveredAdmin: string | null = null;

  /** Every caller re-resolves far more often than the answer changes (once per pointer move, once
   *  per moveend), so the transition check lives here rather than in each of them. */
  function setHovered(admin: string | null) {
    if (admin === hoveredAdmin) return;
    const previousAdmin = hoveredAdmin;
    hoveredAdmin = admin;
    onChange(admin, previousAdmin);
  }

  return {
    pointerMoved(point) {
      lastPointerPosition = point;
      setHovered(resolve(point));
    },

    pointerLeft() {
      lastPointerPosition = null;
      setHovered(null);
    },

    viewChanged() {
      // No cached point means the pointer is not over the canvas at all. Re-resolving anyway would
      // need a stale position and could revive a hover the user already dismissed by leaving, so a
      // camera move with no pointer on the map is deliberately a no-op — resolve is not even called.
      if (lastPointerPosition === null) return;
      setHovered(resolve(lastPointerPosition));
    },

    current() {
      return hoveredAdmin;
    },
  };
}
