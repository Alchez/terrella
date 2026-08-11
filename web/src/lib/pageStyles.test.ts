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

describe("the rail's hairline stays a divider and not a cure", () => {
  it("still draws it between two buttons that are both visible", () => {
    // This used to sit beside a `border-top-width: 0` cancel keyed on the hidden fullscreen
    // control, because with the group ordered [fullscreen, quiet] the surviving eye kept a hairline
    // the 999px radius clipped into a dark chord. The group is [quiet, fullscreen] now, so the eye
    // is the first child and no `+` selector reaches it — the cancel went with the reorder and this
    // is what must NOT go with it. A "tidy-up" that deletes the divider outright fixes nothing and
    // flattens the rail; `railIcons.browser.test` is what proves the chord itself stays gone.
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

describe("one distance sets every floating element off the viewport edge", () => {
  const globeAstro = readFileSync(`${WEB_ROOT}src/components/Globe.astro`, "utf8");
  const scoped = globeAstro.match(/<style>([\s\S]*?)<\/style>/)?.[1] ?? "";

  it("owns the inset once, where the rail can read it too", () => {
    expect(scoped, "the scoped block must be readable, or the scan below proves nothing").toContain(
      ".globe-chrome",
    );
    expect(globe).toMatch(/:root\s*\{[^}]*--page-inset:/);
  });

  it("leaves no edge offset written as its own literal", () => {
    // Derived rather than listed, so a rule added later is covered the day it is added. The row was
    // at a literal `1.2rem` in six places while MapLibre's corners carried their own hardcoded
    // 10px, which is exactly how the two rows ended up 9.2px apart with nothing disagreeing.
    // `padding: 1rem 1.2rem` is untouched on purpose — a padding is not an inset.
    expect(scoped).not.toMatch(/^\s*(top|left|right|bottom|inset):[^;]*\b1\.2rem/m);
  });

  it("takes MapLibre's own control margin over rather than living beside it", () => {
    // Its rule is `.maplibregl-ctrl-top-right .maplibregl-ctrl { margin: 10px 10px 0 0 }` at (0,2,0)
    // and is injected at RUNTIME, so an equal-specificity override loses on source order and the
    // rail silently keeps the old offset. `railIcons.browser.test` measures the result.
    expect(globe).toMatch(
      /\.maplibregl-ctrl-top-right\s+\.maplibregl-ctrl\.maplibregl-ctrl\s*\{[^}]*margin:\s*var\(--page-inset\)\s+var\(--page-inset\)/,
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
    //
    // EACH SELECTOR IS ASSERTED PRESENT BEFORE IT IS ASSERTED ABSENT, because "absent from the
    // shared file" is true of every string that does not exist at all. Renaming `.hero-panel` to
    // `.detail-panel` and forgetting this list would have left the loop passing over a selector no
    // stylesheet contained — a guard that reports on nothing reads exactly like a guard that passed.
    for (const scopedOnly of [".starfield", ".detail-panel", ".globe-lost"]) {
      expect(globeAstro, `${scopedOnly} is not in the globe's scoped block`).toContain(scopedOnly);
      expect(globe, `${scopedOnly} belongs to the globe's scoped block`).not.toContain(scopedOnly);
    }
  });
});
