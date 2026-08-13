/**
 * Quiet mode — the globe with its chrome put away, so the render is the whole frame.
 *
 * CALLED `quiet`, NEVER `zen`. "Zen" already means the Zen Browser in this project's notes and
 * perf captures; a second meaning would make every future grep ambiguous. The button says
 * what it does — "Hide controls" / "Show controls" — and this module says what the state is.
 *
 * AN EXPLICIT MODE, NOT AN IDLE TIMER. The video-player idiom (fade the chrome when nothing
 * happens) is inverted for a map: idle means you are reading a label, and dragging means you are
 * exploring. Auto-hide would clear the chrome exactly when it is wanted and restore it exactly
 * when it is not.
 *
 * NOT PERSISTED — the only toggle on the site that isn't. Borders, Focus, the tier and the phone
 * collapse all survive a reload because they are preferences; this is a presentation state you
 * enter for a moment. Persisting it would land a returning visitor on a globe with no visible
 * controls and no memory of having asked for that.
 *
 * ESCAPE IS DELIBERATELY NOT HANDLED HERE. The globe's Escape has to close the country card
 * first and only then leave quiet, and this module cannot see that card. It exposes `exit()` and
 * lets the page own the ordering.
 */

/** The body class the stylesheets hang the hidden state on. */
export const QUIET_CLASS = "is-quiet";

/** The keyboard shortcut. Free: MapLibre's KeyboardHandler claims the arrows, +, - and Shift. */
export const QUIET_KEY = "z";

export interface QuietModeOptions {
  /** Mirrors the state onto whatever else shows it — the rail button's pressed state. */
  onChange?: (quiet: boolean) => void;
  /** The document to drive. Defaults to the ambient one; injectable so a test can isolate. */
  doc?: Document;
}

export interface QuietMode {
  isQuiet(): boolean;
  enter(): void;
  exit(): void;
  toggle(): void;
  /** Remove the key listener and restore the chrome. */
  destroy(): void;
}

/**
 * True when a keystroke belongs to whatever the user is typing into rather than to the page.
 *
 * EXPORTED BECAUSE THE SEARCH FIELD ARRIVED, which is the future this was written for. It now has
 * two readers — quiet mode's `Z` and the search field's `/` — and the list of what counts as a
 * typing target is exactly the kind of thing a second reader copies and then drifts. One owner, so
 * a shortcut that starts eating keystrokes is fixed once.
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/** Wire up quiet mode. Starts inactive; nothing is read from storage. */
export function createQuietMode(options: QuietModeOptions = {}): QuietMode {
  const { onChange, doc = document } = options;
  let quiet = false;

  function apply(next: boolean): void {
    if (next === quiet) return; // idempotent: no redundant class writes, no repeated onChange
    quiet = next;
    doc.body.classList.toggle(QUIET_CLASS, next);
    onChange?.(next);
  }

  function onKeyDown(event: KeyboardEvent): void {
    // A modifier means the chord belongs to the browser or the OS — Ctrl/Cmd+Z is undo, and
    // stealing it would be the single most irritating thing this control could do.
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.repeat) return; // holding the key must not strobe the chrome
    if (isTypingTarget(event.target)) return;
    if (event.key.toLowerCase() !== QUIET_KEY) return;
    apply(!quiet);
  }

  doc.addEventListener("keydown", onKeyDown);

  return {
    isQuiet: () => quiet,
    enter: () => apply(true),
    exit: () => apply(false),
    toggle: () => apply(!quiet),
    destroy(): void {
      doc.removeEventListener("keydown", onKeyDown);
      apply(false); // never leave a torn-down page with its controls hidden
    },
  };
}
