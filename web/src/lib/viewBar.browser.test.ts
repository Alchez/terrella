import { afterEach, describe, expect, it } from "vitest";
import { page } from "vitest/browser";

import "../styles/global.css";
import baseLayout from "../layouts/Base.astro?raw";
import galleryPage from "../pages/index.astro?raw";
import globePage from "../pages/earth.astro?raw";

/**
 * The view bar has to hold one row at 320 px.
 *
 * `Base.astro` states that as fact — "the controls measure 229.7 px and the bar is allowed 281.6 px
 * at 320 px" — and nothing checked it. That number is now ambiguous enough to be worth replacing:
 * it matches neither page today (the gallery's bar measures 231 px, the globe's 244 px, because
 * "Borders" is a wider word than "Focus"), and there is no way to tell from the comment which
 * element it was measuring. A number in a comment ratchets nothing; this file ratchets.
 *
 * It matters more than it did. The gallery's masthead no longer carries a Globe link, so the tier
 * segment in this bar is the ONLY route from the gallery to the globe.
 *
 * Two things make this a different risk from the masthead's, and both are reasons the assertions
 * here are narrower:
 *
 *   - the bar is `position: fixed`, so it is out of flow and wrapping cannot move page content —
 *     a wrap here is a look regression, never a layout shift;
 *   - every label is set in `--sans`, a pure system stack, so nothing about this bar changes width
 *     after first paint. The masthead's cliff needed zero slack AND a post-paint change. This has
 *     slack and no trigger.
 *
 * What it does share is the shape that bites: a fixed set of controls sized against a fixed budget,
 * where the next control added is the one that does not fit. The union of every group `Base.astro`
 * can emit already does not fit at 320 px — see the control at the bottom of this file — so the
 * margin is one prop away from gone.
 *
 * The configurations are READ FROM THE PAGES, not listed here. Add `spotlight={true}` to the globe
 * and this file measures the globe's new bar without being edited.
 */

/** The narrowest width the site serves; `Base.astro` sizes this bar for it. */
const NARROWEST_PX = 320;

/**
 * Below this the buttons take tighter padding. Both sides are exercised: the tighter padding is
 * what buys the fit at 320, so a test that never crossed the breakpoint could not see it go.
 */
const TIGHT_MAX_PX = 420;

/** Room the bar must still have spare at 320 px once it has laid out on one row. */
const MIN_SLACK_PX = 16;

/**
 * Which control groups a page turns on. Parsed from its `<Base …>` tag so the set of measured
 * configurations cannot drift from the set the site ships.
 */
type BarFlags = { borders: boolean; spotlight: boolean; quality: boolean };

function barFlags(source: string): BarFlags {
  const attrs = source.match(/<Base\b([^>]*)>/)?.[1];
  if (attrs === undefined) throw new Error("page no longer opens with a recognisable <Base …> tag");
  const on = (flag: string) => new RegExp(`\\b${flag}=\\{true\\}`).test(attrs);
  return { borders: on("borders"), spotlight: on("spotlight"), quality: on("quality") };
}

/** Pages that render a bar at all. `about` and `[slug]` pass no flags and get none. */
const PAGE_BARS: { label: string; flags: BarFlags }[] = [
  { label: "gallery", flags: barFlags(galleryPage) },
  { label: "globe", flags: barFlags(globePage) },
];

/** Titles for `it.each`; strings because a sabotage guard has to be able to find one in source. */
const PAGE_LABELS = PAGE_BARS.map((entry) => entry.label);

/**
 * The bar's markup, lifted out of the layout with its Astro conditionals removed — so every group
 * is present and the test hides the ones a given page does not ask for. `display: none` generates
 * no box, which is exactly what the absent markup would have done.
 */
function unionBarMarkup(): string {
  const start = baseLayout.indexOf('<div class="view-bar">');
  if (start < 0) throw new Error("Base.astro no longer contains a recognisable view-bar");
  // Scan to the matching close rather than regex it — the bar nests a div inside a div.
  let depth = 0;
  let index = start;
  for (const match of baseLayout.slice(start).matchAll(/<div\b|<\/div>/g)) {
    depth += match[0] === "</div>" ? -1 : 1;
    if (depth === 0) {
      index = start + match.index! + match[0].length;
      break;
    }
  }
  return (
    baseLayout
      .slice(start, index)
      .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
      .replace(/\{[^{}]*&&\s*(<[^{}]*\/>)\}/g, "$1")
      .replace(/\{[^{}<]*&&\s*\(/g, "")
      .replace(/\)\}/g, "")
      // Astro accepts `<span … />`; HTML does not. The parser ignores that slash and treats the
      // tag as OPEN, so everything after it — the whole tier segment — becomes a CHILD of a 1 px
      // divider. It measured 150 px and read like a bar that comfortably fitted. Astro emits the
      // close itself, so this is the harness matching the browser, not a change to the markup.
      .replace(/<(span|div)\b([^>]*?)\s*\/>/g, "<$1$2></$1>")
  );
}

const mounted: HTMLElement[] = [];

afterEach(() => {
  for (const element of mounted.splice(0)) element.remove();
});

function mountBar(flags: BarFlags) {
  const host = document.createElement("div");
  host.innerHTML = unionBarMarkup();
  document.body.append(host);
  mounted.push(host);

  const bar = host.querySelector<HTMLElement>(".view-bar")!;
  const items = host.querySelector<HTMLElement>(".view-bar-items")!;
  const hide = (selector: string) => {
    const element = host.querySelector<HTMLElement>(selector);
    if (element) element.style.display = "none";
  };
  if (!flags.borders) hide("#border-toggle");
  if (!flags.spotlight) hide("#spotlight-toggle");
  if (!flags.quality) hide(".quality-fab");
  // Mirrors the layout's own condition for the divider.
  if (!((flags.borders || flags.spotlight) && flags.quality)) hide(".view-bar-divider");

  return {
    bar,
    /** Space the bar is allowed — `max-width: calc(100vw - 2.4rem)`, resolved by the browser. */
    allowed: () => Number.parseFloat(getComputedStyle(bar).maxWidth),
    /**
     * Width the controls need on ONE row. Read with the cap lifted, because a bar that has already
     * wrapped reports the wrapped width and would read as though it fitted.
     */
    required: () => {
      bar.style.maxWidth = "none";
      const width = bar.getBoundingClientRect().width;
      bar.style.maxWidth = "";
      return width;
    },
    /**
     * The observable outcome, not a derivation of the two numbers above.
     *
     * Clustered on each child's vertical CENTRE, not its top: the divider is `align-self: stretch`
     * with a 0.15rem margin while the buttons are centred, so on a single row their tops already
     * differ by 2.4 px. Counting distinct tops reported two rows for a bar that production serves
     * on one. The tolerance is derived from the shortest child rather than picked, because what
     * separates two rows is a row height and nothing smaller.
     */
    rows: () => {
      const boxes = [...items.children]
        .filter((child) => getComputedStyle(child).display !== "none")
        .map((child) => child.getBoundingClientRect());
      const tolerance = Math.min(...boxes.map((box) => box.height)) / 2;
      const centres = boxes.map((box) => box.y + box.height / 2).toSorted((a, b) => a - b);
      const rows: number[] = [];
      for (const centre of centres) {
        if (rows.length === 0 || centre - rows[rows.length - 1] > tolerance) rows.push(centre);
      }
      return rows.length;
    },
    labels: () =>
      [...host.querySelectorAll<HTMLElement>("button")]
        .filter((button) => getComputedStyle(button).display !== "none")
        .map((button) => button.textContent!.trim()),
  };
}

describe("the view bar holds one row at the narrowest width the site serves", () => {
  it("is measuring the shipped markup and stylesheet, not an empty string", () => {
    // Every assertion below is satisfied for free by a bar that failed to render or a sheet that
    // failed to load. Prove all four groups survived extraction and the breakpoint is in the CSS.
    const markup = unionBarMarkup();
    expect(markup).toContain("border-toggle");
    expect(markup).toContain("spotlight-toggle");
    expect(markup).toContain("view-bar-divider");
    expect(markup).toContain("quality-fab");
    expect(markup).not.toContain("&&");
    // And that the pages really do ask for different bars — the whole reason both are measured.
    expect(PAGE_BARS.map((entry) => entry.flags.borders)).toEqual([false, true]);
    expect(PAGE_BARS.map((entry) => entry.flags.spotlight)).toEqual([true, false]);

    // The string being right is not the DOM being right. The first version of this file parsed to
    // a tier segment nested INSIDE the 1 px divider, which every width assertion then passed —
    // a narrower bar fits more easily, so the harness's own bug read as a comfortable result.
    // Assert the shape the browser actually built: four groups, all siblings, in source order.
    const bar = mountBar({ borders: true, spotlight: true, quality: true });
    const children = [...bar.bar.querySelector(".view-bar-items")!.children];
    expect(children.map((child) => child.id || child.className)).toEqual([
      "border-toggle",
      "spotlight-toggle",
      "view-bar-divider",
      "quality-fab",
    ]);
  });

  it.each(PAGE_LABELS)("fits on one row at 320px on the %s", async (label) => {
    const flags = PAGE_BARS.find((entry) => entry.label === label)!.flags;
    await page.viewport(NARROWEST_PX, 823);
    const bar = mountBar(flags);

    const required = bar.required();
    const allowed = bar.allowed();
    const slack = Math.round(allowed - required);

    expect(bar.rows(), `the ${label} bar wrapped at ${NARROWEST_PX}px: ${bar.labels().join(" ")}`).toBe(1);
    expect(
      slack,
      `only ${slack}px spare on the ${label} bar at ${NARROWEST_PX}px ` +
        `(needs ${Math.round(required)}px of ${Math.round(allowed)}px)`,
    ).toBeGreaterThanOrEqual(MIN_SLACK_PX);
  });

  it("keeps the tighter phone padding, which is what buys the fit", async () => {
    // The 420 px breakpoint is load-bearing, not cosmetic. Measured either side of it so that
    // deleting the media query fails here rather than silently eating the slack above.
    await page.viewport(TIGHT_MAX_PX, 823);
    const tight = mountBar(PAGE_BARS[1].flags).required();
    mounted.splice(0).forEach((element) => element.remove());
    await page.viewport(TIGHT_MAX_PX + 1, 823);
    const roomy = mountBar(PAGE_BARS[1].flags).required();

    expect(tight).toBeLessThan(roomy);
  });

  it("can tell a bar that does not fit, so a passing measurement means something", async () => {
    // The positive control, and the record of a real limit: the union of every group Base.astro can
    // emit needs more than 320 px allows, so no page may turn all three on at once. Nothing does
    // today — and because the configurations above are read from the pages, the day one does it is
    // measured rather than assumed.
    await page.viewport(NARROWEST_PX, 823);
    const union = mountBar({ borders: true, spotlight: true, quality: true });
    expect(union.required()).toBeGreaterThan(union.allowed());
    expect(union.rows()).toBeGreaterThan(1);
  });
});
