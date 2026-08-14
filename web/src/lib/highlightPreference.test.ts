import { describe, it, expect } from "vitest";
import baseLayout from "../layouts/Base.astro?raw";
import globeComponent from "../components/Globe.astro?raw";
import {
  HIGHLIGHT_EVENT,
  HIGHLIGHT_KEY,
  highlightEnabled,
  highlightStorageValue,
} from "./highlightPreference";

/** A storage stand-in, so the real one is never touched and the absent case is expressible. */
const storageOf = (value: string | null) => ({ getItem: () => value });

describe("the default is ON, which inverts how the key is read", () => {
  it("is on for a visitor who has never touched it", () => {
    // THE WHOLE REASON THIS MODULE EXISTS. Borders and Focus are opt-in overlays, so absent means
    // off and `=== "1"` is right for them. Copying that spelling here would ship the highlight
    // switched off to everyone who had not already turned it on — with the button, the markup and
    // the globe all agreeing, and nothing to suggest it had ever been on.
    expect(highlightEnabled(storageOf(null))).toBe(true);
  });

  it("is off only for an explicit refusal", () => {
    expect(highlightEnabled(storageOf("0"))).toBe(false);
    expect(highlightEnabled(storageOf("1"))).toBe(true);
  });

  it("treats a value it does not recognise as on, rather than as off", () => {
    // A key left behind by another version, or hand-edited, must not silently disable a default-on
    // control. Only the value this module writes for "off" turns it off.
    expect(highlightEnabled(storageOf(""))).toBe(true);
    expect(highlightEnabled(storageOf("true"))).toBe(true);
  });

  it("round-trips whatever it writes", () => {
    // The writer and the reader are in different files; this is the one assertion that fails if
    // either changes its mind about which string means off.
    for (const on of [true, false]) {
      expect(highlightEnabled(storageOf(highlightStorageValue(on)))).toBe(on);
    }
  });
});

describe("the layout and the globe are wired to the same three strings", () => {
  it("ships the button already pressed, because the default is on", () => {
    // A CROSS-FILE CLAIM WITH NO OTHER WITNESS. The markup renders before any script runs, so a
    // button written `aria-pressed="false"` would show "off" on first paint while the globe was
    // already highlighting — and on a page where the visitor never clicks it, that mismatch is the
    // permanent state. Pinned against the module rather than against the literal `true`, so the
    // two move together if the default is ever reversed.
    const button = /<button[^>]*id="highlight-toggle"[\s\S]*?>/.exec(baseLayout)?.[0];
    expect(button, "the layout no longer renders a highlight toggle").toBeTruthy();
    expect(button).toContain(`aria-pressed="${String(highlightEnabled(storageOf(null)))}"`);
  });

  it("gives the button an accessible name, since its only content is a glyph", () => {
    const button = /<button[^>]*id="highlight-toggle"[\s\S]*?>/.exec(baseLayout)!;
    expect(button[0]).toContain("aria-label=");
    // The glyph must not be announced as content of its own; the label is the whole name.
    const markup = baseLayout.slice(button.index);
    expect(markup.slice(0, markup.indexOf("</button>"))).toContain('aria-hidden="true"');
  });

  it("spells the key and the event nowhere but this module", () => {
    // The shape this avoids is Borders', which writes "rg:borders" in the layout AND in the globe:
    // two spellings of one name with nothing comparing them, so a rename in either is silent.
    for (const [name, source] of [
      ["Base.astro", baseLayout],
      ["Globe.astro", globeComponent],
    ] as const) {
      expect(source, `${name} spells the highlight key literally`).not.toContain(
        `"${HIGHLIGHT_KEY}"`,
      );
      expect(source, `${name} spells the highlight event literally`).not.toContain(
        `"${HIGHLIGHT_EVENT}"`,
      );
    }
    expect(baseLayout).toContain("HIGHLIGHT_KEY");
    expect(globeComponent).toContain("HIGHLIGHT_EVENT");
  });

  it("has the globe read the stored preference rather than assume the default", () => {
    // A globe that started `enabled: true` would light everything for one pointer move on a page
    // whose visitor had switched it off, and only settle once they touched the button again.
    expect(globeComponent).toContain("enabled: highlightEnabled()");
  });
});
