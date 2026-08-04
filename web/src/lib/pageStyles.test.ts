import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";

/**
 * Invariants that live in the globe's CSS rather than in its behaviour.
 *
 * These are source scans, which is weaker than a rendered assertion and worth writing anyway: they
 * catch deletion and rewording, which is how these rules actually get lost.
 *
 * WHERE THE RULES LIVE, since it decides what could check them. The globe's GLOBAL styles are now a
 * file (`styles/globe.css`), so a browser test CAN import and render them — `railIcons.browser.test`
 * does exactly that, and any assertion here that graduates to a computed one belongs beside it. The
 * page's SCOPED block is the half that stays out of reach: it is compiled with a
 * `[data-astro-cid-…]` attribute the browser project never mounts, so reading the source is the only
 * check available for it.
 *
 * The `mask-image` vs `background-image` icon rule belongs here too and does not have a guard yet.
 */
const WEB_ROOT = new URL("../../", import.meta.url).pathname;
const globe = readFileSync(`${WEB_ROOT}src/styles/globe.css`, "utf8");

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

describe("the globe's stylesheets stay split the way the cascade needs", () => {
  // The component, not the page: markup and scoped style moved together into `Globe.astro`, and
  // they had to. Astro stamps ONE `data-astro-cid-…` on both halves of a component, so a scoped
  // block left behind in the page would compile against a cid nothing renders — every selector
  // matching nothing, with no error and no visual tell until someone looks at the globe.
  const globeAstro = readFileSync(`${WEB_ROOT}src/components/Globe.astro`, "utf8");

  it("keeps the SCOPED block beside its markup, where Astro can stamp both", () => {
    // This is the constraint that decided the split. Astro rewrites a scoped selector with a
    // `[data-astro-cid-…]` attribute at build time, worth one class of specificity. The identical
    // rules in a `.css` file compile WITHOUT it, so every one of them drops a level and starts
    // losing to things it currently beats — silently, and only in the build, since the rules
    // themselves are unchanged. There is no error and no visual tell until something overlaps.
    const scoped = globeAstro.match(/<style>([\s\S]*?)<\/style>/);
    expect(scoped, "Globe.astro must still carry its scoped <style> block").not.toBeNull();
    expect(scoped![1], "the scoped block must still hold the globe's own elements").toContain(
      ".starfield",
    );
    // Anchored to a tag at the start of a line: the phrase also appears in prose explaining why
    // the block moved, and a bare substring check would fail on the explanation rather than on a
    // regression — a guard that cannot survive its own documentation is a guard someone deletes.
    expect(
      globeAstro,
      "the global rules moved to a file; nothing should re-inline them",
    ).not.toMatch(/^<style is:global>/m);
  });

  it("imports the global stylesheet, or the globe ships with none of it", () => {
    // The file is only reachable because the component asks for it. Drop the import and every MapLibre
    // widget reverts to stock white boxes — while every test that reads `styles/globe.css`
    // directly goes on passing, because the rules still exist. Nothing else would notice.
    expect(globeAstro).toContain('import "../styles/globe.css"');
  });

  it("keeps the globe's own scoped elements out of the shared stylesheet", () => {
    // The half that cannot move must not be moved piecemeal either. A scoped rule relocated into
    // the shared file would lose its cid and its specificity level with it.
    for (const scopedOnly of [".starfield", ".hero-panel", ".globe-lost"]) {
      expect(globe, `${scopedOnly} belongs to the globe's scoped block`).not.toContain(scopedOnly);
    }
  });
});
