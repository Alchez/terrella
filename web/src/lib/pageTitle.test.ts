import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { SITE_NAME, TITLE_SEPARATOR, pageTitle } from "./pageTitle";

const PAGES_ROOT = new URL("../pages/", import.meta.url);
/** Every page, WALKED rather than listed, for the reason `siteLinks.test.ts` gives: a rule enforced
 *  against a hand-written list of pages is silent about the page someone adds next, and adding a
 *  page is exactly when a title gets hand-written. */
const ALL_PAGES: [string, string][] = readdirSync(PAGES_ROOT, { recursive: true })
  .filter((name): name is string => typeof name === "string" && name.endsWith(".astro"))
  .map((name) => [name, readFileSync(new URL(name, PAGES_ROOT), "utf8")]);

/** The `title=` value off a page's `<Base>` tag, which is the only title that reaches the browser.
 *  Taken from after `<Base` on purpose: a `title=` elsewhere in a page is a pointer tooltip, a
 *  different thing that happens to share an attribute name, and props precede children.
 *
 *  THE BRACES ARE COUNTED RATHER THAN MATCHED WITH A REGEX, and that is not fastidiousness — the
 *  first version of this used `\{[^}]*\}` and a mutation walked through it: `pageTitle(`${x} —
 *  Terrella`)` closes a brace at `${x}`, so the extracted value ended before the hand-written half
 *  and the rule below read a string that could not contain what it was looking for. */
function baseTitle(source: string): string | null {
  const afterTag = source.slice(source.indexOf("<Base"));
  const at = afterTag.search(/\btitle=/);
  if (source.indexOf("<Base") < 0 || at < 0) return null;
  const value = afterTag.slice(afterTag.indexOf("=", at) + 1);
  if (value.startsWith('"')) {
    const end = value.indexOf('"', 1);
    return end < 0 ? null : value.slice(0, end + 1);
  }
  if (!value.startsWith("{")) return null;
  let depth = 0;
  for (let index = 0; index < value.length; index++) {
    if (value[index] === "{") depth++;
    else if (value[index] === "}" && --depth === 0) return value.slice(0, index + 1);
  }
  return null;
}

describe("the page title format", () => {
  it("puts the page first, which is the half a truncated tab keeps", () => {
    expect(pageTitle("About")).toBe(`About ${TITLE_SEPARATOR} ${SITE_NAME}`);
  });

  it("uses a separator that is not a dash of any kind", () => {
    // The whole point of the sweep that introduced this module: three pages had drifted onto two
    // dash conventions and two orderings. Pinning the glyph is what stops a fourth appearing.
    expect(TITLE_SEPARATOR).not.toMatch(/[-–—]/);
  });
});

describe("every page composes its title rather than spelling one", () => {
  it("finds pages with titles at all, so the two rules below are not vacuous", () => {
    // Both halves, because they fail differently: no pages makes every rule below pass over an
    // empty list, and pages whose titles this cannot parse makes them pass over nulls.
    expect(ALL_PAGES.length, "no .astro pages were walked at all").toBeGreaterThan(0);
    const parsed = ALL_PAGES.filter(([, source]) => baseTitle(source) !== null);
    expect(
      parsed.length,
      `no page's <Base title=…> could be parsed, so this guard reads nothing. Walked: ${ALL_PAGES.map(([name]) => name).join(", ")}`,
    ).toBe(ALL_PAGES.length);
  });

  it("routes every page's title through pageTitle()", () => {
    for (const [name, source] of ALL_PAGES) {
      expect(
        baseTitle(source),
        `${name} writes its own <Base> title. Call pageTitle("<what this page is>") instead, or ` +
          "the site name and separator get a second spelling and the tab strip drifts again.",
      ).toContain("pageTitle(");
    }
  });

  it("never lets a page spell the site name into a title itself", () => {
    // The failure the rule above cannot see on its own: a page can call the helper and still
    // hand-write the format inside its argument. A page names what IT is and nothing else.
    for (const [name, source] of ALL_PAGES) {
      expect(
        baseTitle(source) ?? "",
        `${name} puts "${SITE_NAME}" inside its own title. pageTitle() adds it.`,
      ).not.toContain(SITE_NAME);
    }
  });
});
