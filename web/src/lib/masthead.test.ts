import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

/**
 * The source-level half of the masthead guard. `masthead.browser.test.ts` proves the layout holds
 * its height across every heading width — but it does that against a COPY of the CSS, so on its own
 * it would go on proving a layout the site had stopped shipping. These assertions pin the premises
 * that copy depends on, and the two decisions that removed the gallery's post-paint reflow.
 */

const source = (path: string) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const gallery = () => source("pages/index.astro");

describe("the gallery masthead has nothing that changes its width after paint", () => {
  it("does not link to the globe from the nav", () => {
    // Not a style choice — this link is what made the row overflow. The globe is reached from the
    // view bar's tier picker instead; `about.astro` keeps a crawlable route (asserted below).
    const nav = gallery().match(/<nav slot="actions" class="head-links">[\s\S]*?<\/nav>/)?.[0];
    expect(nav, "the head-links nav is no longer recognisable in index.astro").toBeDefined();
    expect(nav).not.toContain('href="/earth/"');
  });

  it("never removes a masthead link from script", () => {
    // The second of the two shifts was `.head-links a[href="/earth/"]` being removed after paint,
    // which took the nav from 219px to 162px and un-wrapped the row. Any post-paint mutation of
    // this nav re-arms that, whatever it is keyed to.
    const html = gallery();
    expect(html).not.toMatch(/\.head-links[^\n]*\.remove\(\)/);
    // The gallery has no capability concern left at all now that it offers no globe link. This
    // inherits from `capability.test.ts`, which used to require the OPPOSITE — that the page ask
    // `canRunGlobe` rather than re-derive the floor — and became a contradiction the day the link
    // went. Both halves are kept: don't consult the floor, and don't restate it either.
    expect(html).not.toContain("canRunGlobe");
    expect(html).not.toMatch(/webgl2\s*&&\s*!\w+\.softwareGpu/);
  });

  it("gives the source link an accessible name, since its only content is a decorative SVG", () => {
    // A link whose content is `aria-hidden` has NO accessible name at all — it announces as its
    // href. Same trap the globe's credit glyph hit when it stopped being a word.
    const link = gallery().match(/<a\s+class="head-source"[\s\S]*?>/)?.[0];
    expect(link, "the head-source link is no longer recognisable").toBeDefined();
    expect(link).toContain('aria-label="Source on GitHub"');
    expect(link).toContain('title="Source on GitHub"');
    expect(link).toContain('rel="noopener noreferrer"');
  });

  it("keeps a real, crawlable link to the globe somewhere a clone can follow", () => {
    // index.astro held the ONLY <a href="/earth/"> on the site, and `.no-js .view-bar` is
    // display:none — so dropping it with nothing else in place orphans /earth/ for crawlers and
    // for anyone without JavaScript. There is no sitemap integration to fall back on.
    expect(source("pages/about.astro")).toContain('href="/earth/"');
  });
});

describe("the layout facts masthead.browser.test.ts models", () => {
  it("declares the stack breakpoint, at the width the browser test sweeps against", () => {
    // The browser test builds its media query by interpolation, so it carries the bare number.
    const breakpoint = "359.98";
    expect(source("components/Masthead.astro")).toContain(`@media (max-width: ${breakpoint}px)`);
    expect(source("lib/masthead.browser.test.ts")).toContain(`STACK_MAX_PX = ${breakpoint}`);
  });

  it("keeps the stack rule in the component that owns the selector, not in a page", () => {
    // Astro scopes a component's selectors with a generated attribute, so `.masthead-row` inside
    // Masthead.astro is (0,2,0) while a page's `:global(.masthead-row)` is (0,1,0). The page loses
    // to `align-items: flex-end` and gets a column that is still right-aligned — which shipped for
    // one build, passed the browser test (it injects raw CSS, with no scoping to lose to), and was
    // caught only by looking at a screenshot.
    const stack = source("components/Masthead.astro").match(
      /@media \(max-width: 359\.98px\)[\s\S]*?\n  \}/,
    )?.[0];
    expect(stack, "the stack rule is no longer recognisable in Masthead.astro").toBeDefined();
    expect(stack).toContain("flex-direction: column");
    expect(stack).toContain("align-items: flex-start");
    for (const name of ["index.astro", "about.astro", "[slug].astro"]) {
      expect(source(`pages/${name}`), `${name} reaches .masthead-row through :global()`).not.toMatch(
        /:global\([^)]*\.masthead-row/,
      );
    }
  });

  it("still lays the row out the way the model does", () => {
    // If any of these move, the browser test is measuring a layout the site does not ship.
    const masthead = source("components/Masthead.astro");
    for (const declaration of ["display: flex", "flex-wrap: wrap", "gap: 1rem", "align-items: flex-end"]) {
      expect(masthead, `Masthead.astro no longer declares \`${declaration}\``).toContain(declaration);
    }
    expect(masthead).toContain("font-size: clamp(2rem, 5vw, 3.2rem)");
    expect(masthead).toContain("max-width: var(--masthead-max, 1240px)");
  });

  it("still sizes the nav and its icon the way the model does", () => {
    const html = gallery();
    expect(html).toMatch(/\.head-links \{[\s\S]*?gap: 1\.1rem;/);
    expect(html).toMatch(/\.head-source \{[\s\S]*?padding: 0\.25rem;/);
    expect(html).toMatch(/\.head-source svg \{[\s\S]*?width: 1\.05rem;/);
  });
});
