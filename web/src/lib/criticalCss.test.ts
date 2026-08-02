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
const globe = readFileSync(`${WEB_ROOT}src/pages/globe.astro`, "utf8");
const astroConfig = readFileSync(`${WEB_ROOT}astro.config.ts`, "utf8");

describe("MapLibre's stylesheet must not block the globe's first paint", () => {
  it("imports it for its URL, never for its side effect", () => {
    // The `?url` suffix is the whole mechanism: it yields the emitted asset's href and does NOT
    // register the sheet for injection, which is what a side-effect import does.
    expect(globe).toMatch(/import\s+\w+\s+from\s+"maplibre-gl\/dist\/maplibre-gl\.css\?url"/);
    // A side-effect import anywhere in the file undoes it. Matched WITHOUT the `?url` suffix, and
    // anchored on the quote so the comments explaining this rule do not satisfy their own guard.
    expect(globe).not.toMatch(/^\s*import\s+"maplibre-gl\/dist\/maplibre-gl\.css"/m);
  });

  it("links it non-blocking, with the noscript twin that makes that safe", () => {
    // `media="print"` matches no screen, so the parser does not wait; the onload swap promotes it.
    expect(globe).toMatch(/media="print"/);
    // The handler body is a frontmatter constant, not an inline attribute: written inline, Astro
    // type-checks it as an expression and emits a hint about a variable that does not exist. So the
    // guard asserts the constant's VALUE and that the attribute is wired to it — checking only the
    // attribute would pass while it pointed at something else entirely.
    expect(globe).toMatch(/const PROMOTE_STYLESHEET = "this\.media='all'";/);
    expect(globe).toMatch(/onload=\{PROMOTE_STYLESHEET\}/);
    // Without this, a scripts-off visitor keeps `media="print"` forever and the controls render
    // unstyled — a different failure from "needs JS", and a silent one.
    expect(globe).toMatch(/<noscript slot="head">/);
  });

  it("puts it in the head, where the preload scanner finds it during the first parse", () => {
    expect(globe).toMatch(/<link\s+slot="head"/);
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
