import { describe, it, expect, afterEach } from "vitest";
import { createQuietMode, QUIET_CLASS, QUIET_KEY, type QuietMode } from "./quietMode";

/**
 * Real browser (the `browser` project). Key handling is the whole surface here, and a dispatched
 * KeyboardEvent against a stub proves nothing about modifier chords or `repeat` — those are
 * properties the browser sets, not ones a test hands over.
 */

const live: QuietMode[] = [];

function quietMode(onChange?: (quiet: boolean) => void): QuietMode {
  const mode = createQuietMode({ onChange });
  live.push(mode);
  return mode;
}

/** Send a keystroke the way the browser would, so `repeat` and the modifiers are real fields. */
function press(key: string, init: KeyboardEventInit = {}, target: EventTarget = document): void {
  target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, ...init }));
}

afterEach(() => {
  for (const mode of live.splice(0)) mode.destroy();
  document.body.classList.remove(QUIET_CLASS);
});

describe("quiet mode — the state", () => {
  it("starts inactive and reads nothing from storage", () => {
    // Not persisted, on purpose: a returning visitor must never land on a globe with no visible
    // controls. Writing the key first proves the absence is a decision, not an oversight.
    localStorage.setItem("rg:quiet", "1");
    const mode = quietMode();
    expect(mode.isQuiet()).toBe(false);
    expect(document.body.classList.contains(QUIET_CLASS)).toBe(false);
    localStorage.removeItem("rg:quiet");
  });

  it("puts the class on the body, which is what every stylesheet keys on", () => {
    const mode = quietMode();
    mode.enter();
    expect(document.body.classList.contains(QUIET_CLASS)).toBe(true);
    mode.exit();
    expect(document.body.classList.contains(QUIET_CLASS)).toBe(false);
  });

  it("announces every real change exactly once, and no non-changes", () => {
    // The rail button mirrors this. A repeated announcement is harmless; a missed one leaves the
    // button claiming the opposite of what the page is doing.
    const seen: boolean[] = [];
    const mode = quietMode((next) => seen.push(next));
    mode.enter();
    mode.enter(); // already there
    mode.toggle();
    mode.exit(); // already there
    expect(seen).toEqual([true, false]);
  });
});

describe("quiet mode — the keyboard shortcut", () => {
  it("toggles on the bare key", () => {
    const mode = quietMode();
    press(QUIET_KEY);
    expect(mode.isQuiet()).toBe(true);
    press(QUIET_KEY);
    expect(mode.isQuiet()).toBe(false);
  });

  it("accepts the shifted key, since Shift+Z is still just Z", () => {
    const mode = quietMode();
    press(QUIET_KEY.toUpperCase(), { shiftKey: true });
    expect(mode.isQuiet()).toBe(true);
  });

  it("leaves Ctrl/Cmd/Alt chords to the browser", () => {
    // Ctrl+Z is undo. Stealing it would be the most irritating thing this control could do.
    const mode = quietMode();
    press(QUIET_KEY, { ctrlKey: true });
    press(QUIET_KEY, { metaKey: true });
    press(QUIET_KEY, { altKey: true });
    expect(mode.isQuiet()).toBe(false);
  });

  it("does not strobe while the key is held down", () => {
    const seen: boolean[] = [];
    const mode = quietMode((next) => seen.push(next));
    press(QUIET_KEY);
    press(QUIET_KEY, { repeat: true });
    press(QUIET_KEY, { repeat: true });
    expect(mode.isQuiet()).toBe(true);
    expect(seen).toEqual([true]);
  });

  it("ignores every other key", () => {
    const mode = quietMode();
    for (const key of ["q", "Escape", "ArrowLeft", "+", " "]) press(key);
    expect(mode.isQuiet()).toBe(false);
  });

  it("yields to a field being typed into", () => {
    // Guards a future search box rather than a present bug — but a bare single-letter shortcut is
    // exactly the kind that starts eating keystrokes the moment one lands, and by then the cause
    // is not obvious.
    const input = document.createElement("input");
    document.body.append(input);
    const mode = quietMode();
    press(QUIET_KEY, {}, input);
    expect(mode.isQuiet()).toBe(false);
    input.remove();
  });

  it("still fires when focus is on a rail button, which is not typing", () => {
    const button = document.createElement("button");
    document.body.append(button);
    const mode = quietMode();
    press(QUIET_KEY, {}, button);
    expect(mode.isQuiet()).toBe(true);
    button.remove();
  });
});

describe("quiet mode — Escape is the page's to order, not this module's", () => {
  it("does not act on Escape at all", () => {
    // The globe's Escape must close the country card FIRST and only then leave quiet. This module
    // cannot see that card, so it exposes exit() and stays out of the ordering. If it ever grabs
    // Escape, the card becomes uncloseable while quiet.
    const mode = quietMode();
    mode.enter();
    press("Escape");
    expect(mode.isQuiet()).toBe(true);
  });
});

describe("quiet mode — teardown", () => {
  it("stops listening and restores the chrome", () => {
    // A destroyed mode that left the class on would strand the controls hidden with nothing
    // listening for the key that brings them back.
    const mode = createQuietMode();
    mode.enter();
    mode.destroy();
    expect(document.body.classList.contains(QUIET_CLASS)).toBe(false);
    press(QUIET_KEY);
    expect(mode.isQuiet()).toBe(false);
  });
});
