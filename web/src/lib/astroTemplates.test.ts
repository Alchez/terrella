import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/**
 * An Astro template must carry no HTML comment, because an HTML comment SHIPS.
 *
 * WHY THIS EXISTS: the globe's markup lived at the top level of a page for its whole life, and its
 * five `<!-- -->` comments never reached a visitor. Not because of a rule — because of POSITION.
 * Astro strips HTML comments out of slot children, and everything a page writes inside `<Base>` is
 * a slot child. Moving that markup into `components/Globe.astro` made it a component's own
 * template, where comments are markup like any other, and all five began shipping. Nothing failed:
 * the build succeeded, the page rendered identically, and only a byte-diff of `dist/` against the
 * parent commit said so.
 *
 * So the rule is not "prefer the JSX form". It is that the SAFE form is the only form whose safety
 * does not depend on where the file happens to sit, and this repo already writes `{/* *\/}`
 * everywhere else — the five that shipped were the only exceptions in the tree.
 *
 * THE SWEEP IS RECURSIVE ON PURPOSE. Its predecessor named `pages/` and `components/` explicitly
 * and therefore stopped covering `layouts/`, which is where a template most likely to be shared
 * actually lives. A guard that enumerates directories goes quiet the day the tree grows one, and it
 * goes quiet in the direction that looks green.
 */
const SOURCE_ROOT = new URL("../", import.meta.url);

const templates = readdirSync(SOURCE_ROOT, { recursive: true })
  .filter((name): name is string => typeof name === "string" && name.endsWith(".astro"))
  .map((name) => ({ name, text: readFileSync(new URL(name, SOURCE_ROOT), "utf8") }));

describe("every Astro template under src/", () => {
  it("is actually found by the sweep, across all three template directories", () => {
    // Three directories, so a walk that stops recursing fails here rather than passing on a subset.
    // Without this the rule below is satisfied by an empty list, which is the shape that reads green
    // while checking nothing.
    const found = templates.map((template) => template.name);
    for (const required of ["layouts/Base.astro", "components/Globe.astro", "pages/earth/index.astro"]) {
      expect(found, `the sweep missed ${required}`).toContain(required);
    }
  });

  it("writes its comments in the form that never reaches a visitor", () => {
    // Matched on the opening delimiter alone: `<!--` cannot appear in an Astro template for any
    // other reason, and a rule that tried to allow some of them would need to model where the file
    // sits — which is precisely the thing that failed silently the first time.
    const offenders = templates
      .filter((template) => template.text.includes("<!--"))
      .map((template) => template.name);
    expect(offenders, "an HTML comment ships to every visitor; write {/* … */} instead").toEqual([]);
  });
});
