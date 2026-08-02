import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";

/**
 * Invariants that live in `globe.astro`'s PAGE-SCOPED CSS, which no browser test can reach.
 *
 * The browser project mounts elements in isolation, so it never loads the page's `<style>` blocks —
 * a rule in there can be deleted and every browser test stays green. Reading the source is the only
 * check available, which makes these guards weaker than a rendered assertion and worth writing
 * anyway: they catch deletion and rewording, which is how these rules actually get lost.
 *
 * This file is the home for that category. The `mask-image` vs `background-image` icon rule belongs
 * here too and does not have a guard yet.
 */
const WEB_ROOT = new URL("../../", import.meta.url).pathname;
const globe = readFileSync(`${WEB_ROOT}src/pages/globe.astro`, "utf8");

describe("quiet mode leaves no orphaned divider on the rail", () => {
  it("cancels the hairline on the button after the hidden fullscreen control", () => {
    // `+` matches DOM ORDER, not visibility. The rail's second group is [fullscreen, quiet]; quiet
    // mode sets fullscreen to `display:none`, and the quiet button below it went on matching
    // `button + button` while becoming the group's first VISIBLE child. It kept a 1px hairline that
    // the group's 999px radius clipped into a dark chord across the top of the circle — reported
    // from a phone as "a tiny black part of the icon".
    expect(globe).toMatch(/\.maplibregl-ctrl-fullscreen\s*\n?\s*\+\s*button\s*\{[^}]*border-top-width:\s*0/);
  });

  it("keeps the cancel more specific than the divider it has to beat", () => {
    // The divider is (0,4,2) — two classes doubled. Any cancel written the obvious way, as
    // `body.is-quiet .rg-ctrl-quiet` (0,3,1), silently loses and the chord comes back. Asserting
    // the doubled group class is asserting the specificity, which is the part that is easy to
    // "tidy" away without noticing it was load-bearing.
    const cancel = globe.match(
      /body\.is-quiet\s*\n?\s*\.maplibregl-ctrl-top-right\s*\n?\s*\.maplibregl-ctrl-group\.maplibregl-ctrl-group\s*\n?\s*\.maplibregl-ctrl-fullscreen/,
    );
    expect(cancel, "the cancel must carry the doubled group class").not.toBeNull();
  });

  it("still draws the divider between two buttons that are both visible", () => {
    // A cancel that killed the hairline outright would fix the chord and flatten the rail. The
    // divider rule has to survive.
    expect(globe).toMatch(/button\s*\+\s*button\s*\{\s*border-top:\s*1px solid var\(--line\)/);
  });
});

describe("the pressed quiet toggle is a bare glyph, not a filled button", () => {
  it("cancels BOTH the accent fill and the accent text colour, at a specificity that wins", () => {
    // Measured on the live page before this guard existed: the cancel shipped as
    // `body.is-quiet .rg-ctrl-quiet[aria-pressed="true"]` — (0,3,1) against the "filled = on" rule's
    // (0,4,1) — so it never applied once, and BOTH its declarations were dead. The button read
    // `background: rgb(124,184,184)` and `color: rgb(27,26,22)`, i.e. accent on bg, identical to the
    // pressed spin button. Matching the doubled group class here asserts the specificity; capturing
    // the block asserts neither declaration gets dropped on the way past.
    const cancel = globe.match(
      /body\.is-quiet\s*\n?\s*\.maplibregl-ctrl-top-right\s*\n?\s*\.maplibregl-ctrl-group\.maplibregl-ctrl-group\s*\n?\s*\.rg-ctrl-quiet\[aria-pressed="true"\]\s*\{([^}]*)\}/,
    );
    expect(cancel, "the pressed-quiet cancel must carry the doubled group class").not.toBeNull();
    expect(cancel![1], "the fill must be cancelled").toMatch(/background:\s*none/);
    expect(cancel![1], "the glyph colour must be cancelled too").toMatch(/color:\s*var\(--muted\)/);
  });

  it("never reverts to the un-doubled form that silently loses", () => {
    // The exact shape that shipped and did nothing. Asserting its ABSENCE is what catches someone
    // "tidying" the selector above back into the obvious one.
    expect(globe).not.toMatch(/body\.is-quiet\s+\.rg-ctrl-quiet\[aria-pressed="true"\]\s*\{/);
  });

  it("leaves every OTHER pressed rail button filled", () => {
    // The cancel is an exception, not a repeal — "filled = on" is the grammar the view bar shares,
    // and the spin toggle still depends on it.
    expect(globe).toMatch(
      /\.maplibregl-ctrl-group\.maplibregl-ctrl-group\s*\n?\s*button\[aria-pressed="true"\]\s*\{[^}]*background:\s*var\(--accent\)/,
    );
  });
});
