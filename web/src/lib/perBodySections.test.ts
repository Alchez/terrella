import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";

/**
 * A page about more than one body wears none of their colours, and its sections wear one each.
 *
 * `Base.astro` stamps `data-body` on `<html>` from a required `BodySlug`, which is right on every
 * page that draws one planet and cannot be right on a page that lists two: the root names one of
 * them truthfully and the whole document takes its accent. The archives page shipped that way and
 * drew Mars's three archives in Earth's teal, under a heading saying Mars.
 *
 * TWO HALVES, NEITHER SUFFICIENT. `bodies.browser.test.ts` proves the stylesheet can scope an
 * accent to a subtree; this proves the pages ask it to. Both colours are the site's own, so there
 * is no invalid value to catch downstream and no rendering that looks broken.
 */

const PAGES_ROOT = new URL("../pages/", import.meta.url);
const PAGES: [string, string][] = readdirSync(PAGES_ROOT, { recursive: true })
  .filter((name): name is string => typeof name === "string" && name.endsWith(".astro"))
  .map((name) => [name, readFileSync(new URL(name, PAGES_ROOT), "utf8")]);

const page = (name: string) => PAGES.find(([file]) => file === name)?.[1] ?? "";

/** The class ON AN ELEMENT, never the word anywhere in the file. Both of these pages explain the
 *  arrangement in a comment that names it, and a plain `includes` reads that comment as the markup:
 *  deleting the class outright left this file green. */
const NEUTRAL_CHROME = /class="[^"]*\ball-bodies\b[^"]*"/;
const SECTION_BODY = /data-body=\{\w+\.slug\}/;

describe("a page that lists every body", () => {
  it("stamps the body on each section, on both pages that have them", () => {
    // Asserted per page rather than over a set: there are two, they are structurally different,
    // and the loop variable each one maps over is the half a set-shaped assertion would drop.
    expect(page("archives.astro")).toMatch(/<section class="world" data-body=\{world\.slug\}/);
    expect(page("about.astro")).toMatch(/<section class="panel" data-body=\{world\.slug\}/);
    expect(page("about.astro")).toMatch(/class="world-chip" data-body=\{world\.slug\}/);
  });

  it("neutralises its own chrome wherever it stamps a section", () => {
    for (const [name, source] of PAGES) {
      if (!SECTION_BODY.test(source)) continue;
      expect(source, `${name} colours sections per body but keeps one body's chrome`).toMatch(
        NEUTRAL_CHROME,
      );
    }
  });

  it("stamps sections wherever it neutralises, so the accent is not simply gone", () => {
    // The other direction, and the one a half-finished fix lands on: `all-bodies` alone leaves the
    // page grey throughout, which reads as a deliberate look rather than as a missing attribute.
    for (const [name, source] of PAGES) {
      if (!NEUTRAL_CHROME.test(source)) continue;
      expect(source, `${name} neutralises its chrome and gives no section a body`).toMatch(
        SECTION_BODY,
      );
    }
  });
});
