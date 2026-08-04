import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";

/**
 * The globe's first paint must not wait on MapLibre's widget stylesheet.
 *
 * WHY THIS IS A SOURCE GUARD AND NOT A BROWSER TEST
 * -------------------------------------------------
 * **Dev and prod disagree here, and dev is the more forgiving of the two.** In dev, Vite injects
 * every CSS module as a `<style>` — including one reached through `?url` — so MapLibre's sheet is
 * BOTH linked and injected, and it lands in the same relative position it always did. In the build
 * it is linked once, non-blocking, and promoted after our own CSS. So the cascade order differs
 * between the two, and a browser test driven against the dev server would confirm the old ordering
 * while the shipped one had changed. There is no arrangement of a dev-server test that catches a
 * regression here; reading the source is what catches it.
 *
 * WHAT IT IS PROTECTING, measured rather than assumed
 * ---------------------------------------------------
 * A bare `import "maplibre-gl/dist/maplibre-gl.css"` in the client script makes Vite hoist it into
 * a render-blocking `<link>`. That put **70 KB of widget CSS in front of first paint** on a page
 * where the first widget cannot exist until the 265 KB globe chunk has downloaded and executed —
 * measured at 1,209 ms for the stylesheet against 1,894 ms for the chunk, so it was blocking paint
 * for something ~700 ms away from needing it. Reverting the import costs FCP 629 → 1,264 ms.
 */
const WEB_ROOT = new URL("../../", import.meta.url).pathname;
// THE SUBJECT IS SPLIT ACROSS THREE FILES, and each half is checked against the one that can break
// it. The `<link>` and its promoter live in `MapStylesheet.astro`; the client script that must
// never side-effect-import the sheet is `Globe.astro`; and reaching `<head>` at all depends on the
// PAGE forwarding that component into `Base`'s named slot, because a `slot` attribute means nothing
// except on a direct child of a component invocation.
const mapStylesheet = readFileSync(`${WEB_ROOT}src/components/MapStylesheet.astro`, "utf8");
const globe = readFileSync(`${WEB_ROOT}src/components/Globe.astro`, "utf8");
const earthPage = readFileSync(`${WEB_ROOT}src/pages/earth.astro`, "utf8");
const astroConfig = readFileSync(`${WEB_ROOT}astro.config.ts`, "utf8");

// AND `MapStylesheet.astro` IS READ AS THREE THINGS, because a whole-file scan of this component is
// satisfied by its own explanation. Both `media="print"` and `<noscript>` appear in the comment that
// justifies them, so a positive `toMatch` kept passing with the element itself deleted — measured,
// not reasoned: the mutation swapping the real `<noscript>` for a `<template>` survived a full
// harness run. Splitting at the frontmatter fence is NOT enough and that was measured too, on the
// next run: the comment is a `{/* */}` block, so it sits in the template half beside the markup.
// Positive checks therefore read `markup`, the template with its comments removed.
const mapStylesheetHalves = mapStylesheet.split(/^---$/m);
const mapStylesheetFrontmatter = mapStylesheetHalves.at(1) ?? "";
const mapStylesheetTemplate = mapStylesheetHalves.at(-1) ?? "";
const mapStylesheetMarkup = mapStylesheetTemplate.replace(/\{\/\*[\s\S]*?\*\/\}/g, "");

describe("MapLibre's stylesheet must not block the globe's first paint", () => {
  it("reads the component's markup, and not the prose explaining it", () => {
    // Every positive check below is only as good as this. If the fence stops matching, the halves
    // collapse; if the comment syntax changes, the strip silently no-ops and the prose satisfies
    // the guards again. Both are proven here rather than assumed: the phrase exists only in the
    // comment, and `<link` only in the markup, so each failure direction has an assertion.
    expect(mapStylesheetHalves, "expected --- frontmatter --- then markup").toHaveLength(3);
    expect(mapStylesheetFrontmatter).toContain("import maplibreStylesheet");
    expect(mapStylesheetMarkup, "a comment survived the strip").not.toContain("twin is not");
    expect(mapStylesheetMarkup, "the strip ate the markup too").toContain("<link");
  });

  it("imports it for its URL, never for its side effect", () => {
    // The `?url` suffix is the whole mechanism: it yields the emitted asset's href and does NOT
    // register the sheet for injection, which is what a side-effect import does.
    expect(mapStylesheetFrontmatter).toMatch(
      /import\s+\w+\s+from\s+"maplibre-gl\/dist\/maplibre-gl\.css\?url"/,
    );
    // Checked against the CLIENT SCRIPT as well, and that half is the one that matters: the
    // measured regression was a bare import in the globe's script, which is a different file from
    // the one holding the link. Matched WITHOUT the `?url` suffix, and anchored on the quote so the
    // comments explaining this rule do not satisfy their own guard.
    for (const [name, source] of [
      ["MapStylesheet.astro", mapStylesheet],
      ["Globe.astro", globe],
    ] as const) {
      expect(source, `${name} side-effect-imports the sheet`).not.toMatch(
        /^\s*import\s+"maplibre-gl\/dist\/maplibre-gl\.css"/m,
      );
    }
  });

  it("links it non-blocking, with the noscript twin that makes that safe", () => {
    // `media="print"` matches no screen, so the parser does not wait; the onload swap promotes it.
    expect(mapStylesheetMarkup).toMatch(/media="print"/);
    // The handler body is a frontmatter constant, not an inline attribute: written inline, Astro
    // type-checks it as an expression and emits a hint about a variable that does not exist. So the
    // guard asserts the constant's VALUE and that the attribute is wired to it — checking only the
    // attribute would pass while it pointed at something else entirely.
    expect(mapStylesheetFrontmatter).toMatch(/const PROMOTE_STYLESHEET = "this\.media='all'";/);
    expect(mapStylesheetMarkup).toMatch(/onload=\{PROMOTE_STYLESHEET\}/);
    // Without this, a scripts-off visitor keeps `media="print"` forever and the controls render
    // unstyled — a different failure from "needs JS", and a silent one.
    expect(mapStylesheetMarkup).toMatch(/<noscript>/);
  });

  it("puts it in the head, where the preload scanner finds it during the first parse", () => {
    // The one line that cannot live in the component. Written inside `MapStylesheet.astro`,
    // `slot="head"` is an ordinary attribute on an ordinary element and the sheet renders in the
    // BODY — still found by the scanner, still working, and silently no longer where the layout
    // documented it. So the guard is on the page that forwards it.
    expect(earthPage).toMatch(/<Fragment slot="head">\s*<MapStylesheet\s*\/>\s*<\/Fragment>/);
    // Matched against the TEMPLATE half only. The frontmatter above it documents this very rule, so
    // a whole-file search fails on the explanation rather than on a regression — the same trap the
    // scoped-style guard next door records having fallen into.
    expect(
      mapStylesheetTemplate,
      "the component must not try to name the slot itself",
    ).not.toContain('slot="head"');
  });
});

describe("the page's own stylesheet must arrive with the document", () => {
  it("astro.config sets inlineStylesheets to always", () => {
    // Deferring MapLibre's sheet buys nothing on its own: the round trip is charged by whichever
    // stylesheet still blocks, and ours is 12 KB — just past Vite's 4 KB assetsInlineLimit, so the
    // default 'auto' left it linked. Both winning arms inlined THIS sheet; that is where the
    // 635 ms came from. Measured: inline ours + defer MapLibre's = 629 ms, inline BOTH = 689 ms.
    expect(astroConfig).toMatch(/inlineStylesheets:\s*['"]always['"]/);
  });
});
