/**
 * The two buttons the globe's camera rail needs and MapLibre does not ship — the idle-spin
 * toggle and the hide-controls toggle.
 *
 * DELIBERATELY NOT `IControl`s. MapLibre gives every control its OWN `.maplibregl-ctrl-group`
 * pill, so registering these the ordinary way renders four stacked pills in the top-right — nav,
 * spin, fullscreen, quiet — where the design calls for two. They are plain widgets instead, and
 * `earth.astro` appends each into the group it belongs to: spin joins zoom+compass (the camera),
 * quiet joins fullscreen (the frame), so the grouping states the concern.
 *
 * The markup mirrors MapLibre's own exactly — `<button class="…"><span
 * class="maplibregl-ctrl-icon"></span></button>` — so one CSS block styles every icon in the
 * rail, ours and theirs, instead of two that have to be kept in step.
 */

/** How a toggle is built. `onToggle` receives the state the button is moving TO. */
export interface RailToggleOptions {
  /** Class on the `<button>`. The CSS hangs the icon mask on it; the tests use it as the hook. */
  className: string;
  /** Accessible name while off. */
  label: string;
  /**
   * Accessible name while on. Defaults to `label`, for a control whose name does not flip —
   * Spin is always "Toggle globe auto-rotate", but the quiet toggle has to say which way it
   * goes, because a button that hid the controls cannot also be labelled "Hide controls".
   */
  pressedLabel?: string;
  /** Initial pressed state. */
  pressed?: boolean;
  onToggle: (next: boolean) => void;
}

/** A rail button, with the state writes its owner needs. */
export interface RailToggle {
  readonly button: HTMLButtonElement;
  isPressed(): boolean;
  /** Reflect state set elsewhere. The page stays the single writer; this only mirrors. */
  setPressed(pressed: boolean): void;
  /**
   * Grey out and disable, with a replacement name saying what would make it work again.
   * Passing `true` restores the name `pressed` currently implies.
   */
  setAvailable(available: boolean, unavailableLabel?: string): void;
}

/**
 * Build a rail toggle. The element is created HERE rather than on first mount, so its owner can
 * set state on it during setup without a null window to guard — the spin state is decided in one
 * place well after the button is registered.
 */
export function createRailToggle(options: RailToggleOptions): RailToggle {
  const { className, label, pressedLabel = label, pressed = false, onToggle } = options;

  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.setAttribute("aria-pressed", String(pressed));

  // The icon is a masked background on this span (see the rail block in earth.astro), so the
  // button's only content is decorative. Without BOTH of these it would have no accessible name
  // at all — the trap the credit's ⓘ hit when it stopped being words.
  const icon = document.createElement("span");
  icon.className = "maplibregl-ctrl-icon";
  icon.setAttribute("aria-hidden", "true");
  button.append(icon);

  let available = true;

  /** One writer for both names, so `title` and `aria-label` can never disagree. */
  function applyName(name: string): void {
    button.title = name;
    button.setAttribute("aria-label", name);
  }

  function currentName(): string {
    return button.getAttribute("aria-pressed") === "true" ? pressedLabel : label;
  }

  applyName(currentName());

  button.addEventListener("click", () => {
    // Read the DOM rather than a captured flag: `setPressed` is called from the page for reasons
    // that never touch this button (an interaction retiring the spin, the FPS watchdog), so the
    // attribute is the only value guaranteed to be current.
    onToggle(button.getAttribute("aria-pressed") !== "true");
  });

  return {
    button,
    isPressed: () => button.getAttribute("aria-pressed") === "true",
    setPressed(next: boolean): void {
      button.setAttribute("aria-pressed", String(next));
      if (available) applyName(currentName());
    },
    setAvailable(next: boolean, unavailableLabel?: string): void {
      available = next;
      button.disabled = !next;
      button.classList.toggle("is-unavailable", !next);
      applyName(next ? currentName() : (unavailableLabel ?? currentName()));
    },
  };
}

/**
 * Find the control group holding `buttonSelector`, so a widget can join the pill it belongs to.
 *
 * Semantic rather than positional on purpose: `:nth-child` would silently retarget the first time
 * a control is added or reordered, and the failure — a button landing in the wrong pill — looks
 * like a styling bug rather than a lookup one.
 */
export function findRailGroup(container: HTMLElement, buttonSelector: string): HTMLElement | null {
  return container.querySelector(buttonSelector)?.closest<HTMLElement>(".maplibregl-ctrl-group") ?? null;
}

/**
 * Where a joining button sits in its group's reading order.
 *
 * IT DECIDES TWO POSITIONS, NOT ONE, and that is the whole reason it is a parameter rather than a
 * `prepend` at the call site. `"start"` also means "and if the control you are joining never
 * rendered, put your new group at the TOP of the corner" — because the two cases have to agree.
 * `FullscreenControl` draws nothing where the Fullscreen API is absent, so on that device a
 * `"start"` button that only knew about its group would land in a pill appended below the camera:
 * a lone eye halfway down the right edge, which is the exact state this placement exists to stop.
 */
export type RailPlacement = "start" | "end";

/**
 * Put `button` in the group holding `buttonSelector`, or in a new group of its own if that
 * control never rendered — `FullscreenControl` draws nothing where the Fullscreen API is absent
 * (iPhone Safari), and the quiet toggle must not disappear with it.
 *
 * Returns the group it landed in, so a caller can tell which case it got.
 */
export function joinRailGroup(
  container: HTMLElement,
  buttonSelector: string,
  button: HTMLButtonElement,
  placement: RailPlacement = "end",
): HTMLElement {
  const existing = findRailGroup(container, buttonSelector);
  if (existing) {
    if (placement === "start") existing.prepend(button);
    else existing.append(button);
    return existing;
  }
  const group = document.createElement("div");
  group.className = "maplibregl-ctrl maplibregl-ctrl-group";
  group.append(button);
  if (placement === "start") container.prepend(group);
  else container.append(group);
  return group;
}
