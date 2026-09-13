import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";

/**
 * The gutter between a page's content and the edge of its container has one owner.
 *
 * `Masthead.astro` pads itself and every page pads its own main, so a heading and the sections
 * under it line up only because both spell the same clamp. Seven copies of it were in the tree
 * when the archives page shipped with none: its heading sat 40 px right of every section below it
 * at 2560 px, and the page looked correct on its own, because nothing compares a page against its
 * own masthead.
 *
 * READ OUT OF THE DECLARATION, NEVER RETYPED. A guard that spells the clamp itself becomes an
 * eighth copy, and it would pass on the day the other seven changed together.
 */

const SRC = new URL("../", import.meta.url);
const GLOBAL_CSS = "styles/global.css";

const read = (name: string) => readFileSync(new URL(name, SRC), "utf8");

/** Everything Astro or CSS under `src/`, walked rather than listed: a page added to the tree is a
 *  page this guard covers, which is the half a hand-kept list loses first. */
const SOURCES: [string, string][] = readdirSync(SRC, { recursive: true })
  .filter((name): name is string => typeof name === "string" && /\.(astro|css)$/.test(name))
  .map((name) => [name, read(name)]);

const globalCss = read(GLOBAL_CSS);
const gutter = globalCss.match(/--page-gutter:\s*([^;]+);/)?.[1]?.trim();

/** The files that draw a `<Masthead>`, and therefore have a heading to line up with. Matched on the
 *  import rather than on the word, which global.css now mentions in a comment. */
const MASTHEAD_PAGES = SOURCES.filter(([, source]) =>
  /import Masthead from ["'][^"']*Masthead\.astro["']/.test(source),
);

describe("the page gutter", () => {
  it("is declared, once, in the stylesheet every page loads", () => {
    expect(gutter, "--page-gutter is not declared in global.css").toBeDefined();
    expect(gutter).toMatch(/^clamp\(/);
    expect(globalCss.match(/--page-gutter:/g)).toHaveLength(1);
  });

  it("is spelled nowhere else, so no two containers can disagree about it", () => {
    for (const [name, source] of SOURCES) {
      if (name === GLOBAL_CSS) continue;
      expect(source, `${name} spells the gutter instead of using var(--page-gutter)`).not.toContain(
        gutter,
      );
    }
  });

  it("pads the main of every page that draws a masthead", () => {
    // The archives page is why this is asserted over the set rather than over the one page that
    // was wrong: four of the five were already correct, and being in the majority is what made the
    // fifth invisible.
    expect(MASTHEAD_PAGES.length).toBeGreaterThan(1);
    for (const [name, source] of MASTHEAD_PAGES) {
      expect(source, `${name} draws a masthead but pads its content by something else`).toContain(
        "var(--page-gutter)",
      );
    }
  });
});
