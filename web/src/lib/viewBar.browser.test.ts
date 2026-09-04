import { afterEach, describe, expect, it } from "vitest";
import { page } from "vitest/browser";

import "../styles/global.css";
import { BODIES, type BodySlug } from "./bodies";
import { hasHoverHighlight } from "./globeSubsystems";
import { PUBLISHED } from "./tileAddress";
import type { Country } from "./manifest";
import baseLayout from "../layouts/Base.astro?raw";

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
 * THE SAME SYSTEM STACK IS WHY THE MEASUREMENT IS PINNED TO ONE FACE. `system-ui` is not a font, it
 * is whatever the machine calls its UI font — Noto Sans on the dev box, DejaVu Sans on the CI
 * runner — and the same commit measured 265.4 px on one and 271.6 px on the other, which is a
 * guard that passes or fails on where it runs. Across the faces a real visitor can land on, the
 * spread is 248.3 px (Carlito) to 271.6 px (DejaVu): 24 px, wider than MIN_SLACK_PX itself, so the
 * floor was never checkable from a single machine. Pinning makes the number reproducible AND
 * pessimistic — DejaVu is at the wide end, and the faces that actually ship as `system-ui` on
 * macOS, Windows and Android are all narrower than it.
 *
 * What it does share is the shape that bites: a fixed set of controls sized against a fixed budget,
 * where the next control added is the one that does not fit. The union of every group `Base.astro`
 * can emit already does not fit at 320 px — see the control at the bottom of this file — so the
 * margin is one prop away from gone.
 *
 * BOTH HALVES OF THE CONFIGURATION ARE FOUND, NOT LISTED — which pages ship a bar, and what each
 * one turns on. The second half was always read from the source; the first was a list of two, and a
 * list of two stopped being every globe the day Mars got one. Nothing would have reported that: an
 * unmeasured page cannot fail to fit, so narrowing this sweep looks exactly like passing it.
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
 * The face every width here is measured in — see the header for why it is pinned rather than
 * inherited. Named without a fallback ON PURPOSE: if the box has no DejaVu the text falls back to
 * the default face and the bar measures narrower, which is a guard quietly grading itself easier.
 * `fontsResolve` below is what turns that into a failure.
 */
const MEASUREMENT_FONT = '"DejaVu Sans"';

/** Width of a fixed string in one family, for deciding whether a face resolved at all. */
function inkWidth(family: string): number {
  const ruler = document.createElement("span");
  ruler.textContent = "Borders Lite Globe Full";
  ruler.style.cssText = `font-family:${family};font-size:16px;position:absolute;white-space:pre`;
  document.body.append(ruler);
  const width = ruler.getBoundingClientRect().width;
  ruler.remove();
  return width;
}

/**
 * Which control groups a page turns on. Parsed from its `<Base …>` tag so the set of measured
 * configurations cannot drift from the set the site ships.
 */
type BarFlags = {
  highlight: boolean;
  borders: boolean;
  spotlight: boolean;
  quality: boolean;
};

/**
 * A flag's answer: fixed at build time, or `"varies"` for one template that renders both ways.
 *
 * `"varies"` is not "unknown". It is the honest reading of `[slug].astro`, which is ONE page source
 * and 203 rendered documents, some of which ship the spotlight control and some of which do not.
 * Collapsing that to a single boolean would pick an arm and stop measuring the other; both are
 * expanded below instead, so whichever is the wider bar is the one that has to fit.
 */
type FlagAnswer = boolean | "varies";

/**
 * Per-country fields a flag may be written from, checked against `Country` by the compiler.
 *
 * A TYPE-ONLY import, which is erased before this file reaches a browser — `manifest.ts` value-
 * imports a gitignored, data-derived JSON that does not exist on a clean checkout, and pulling it
 * in here would make this suite fail on CI for a reason that has nothing to do with the view bar.
 */
const COUNTRY_FLAG_FIELDS = ["hasSpotlight"] as const satisfies readonly (keyof Country)[];

/**
 * Resolve one flag EXPRESSION to the answer(s) the page ships with.
 *
 * A page may write the answer (`{true}`), take it from the body registry (`{body.hasBorders}`), or
 * take it per country (`{country.hasSpotlight}`) — but the important half is what it does with a
 * FOURTH spelling. The version that only knew `{true}` reported anything else as `false`, i.e. as a
 * control group the site does not ship, and a group that is not measured cannot fail to fit. So an
 * unrecognised expression is an ERROR here, not an absence: this guard's whole claim is that it
 * measures the configurations the site actually ships, and quietly measuring fewer is how that
 * claim goes hollow.
 */
function resolveFlag(
  pageName: string,
  flag: string,
  expression: string,
  source: string,
): FlagAnswer {
  if (expression === "true") return true;
  if (expression === "false") return false;
  const field = /^body\.(\w+)$/.exec(expression)?.[1];
  if (field !== undefined) {
    // The page names its body once, in frontmatter, and passes `body.slug` to the layout — so the
    // slug is read from the same declaration the flag is read from rather than from the attribute.
    const slug = /\bBODIES\.(\w+)\b/.exec(source)?.[1];
    const descriptor = slug === undefined ? undefined : BODIES[slug as BodySlug];
    const value = descriptor?.[field as keyof typeof descriptor];
    if (typeof value !== "boolean") {
      throw new Error(`${pageName}: ${flag}={${expression}} does not resolve to a boolean in BODIES`);
    }
    return value;
  }
  // A registry PREDICATE rather than a registry field, because what it asks — does this body
  // publish a vector overlay — is already answered by `PUBLISHED` and copying it onto the body
  // descriptor would be that answer written twice. Evaluated here for real, against the same
  // function the page calls, so this cannot drift from what ships.
  if (/^hasHoverHighlight\(PUBLISHED\[body\.slug\]\)$/.test(expression)) {
    const slug = /\bBODIES\.(\w+)\b/.exec(source)?.[1];
    if (slug === undefined || !(slug in BODIES)) {
      throw new Error(`${pageName}: ${flag}={${expression}} on a page that names no body`);
    }
    return hasHoverHighlight(PUBLISHED[slug as BodySlug]);
  }
  const countryField = /^country\.(\w+)$/.exec(expression)?.[1];
  if (countryField !== undefined) {
    if (!(COUNTRY_FLAG_FIELDS as readonly string[]).includes(countryField)) {
      throw new Error(
        `${pageName}: ${flag}={${expression}} — add ${countryField} to COUNTRY_FLAG_FIELDS if it ` +
          `is a real boolean on Country, so the compiler can say when it is renamed away.`,
      );
    }
    return "varies";
  }
  throw new Error(
    `${pageName}: cannot resolve ${flag}={${expression}}. Teach resolveFlag about it — reading ` +
      `it as "off" would drop a shipped control group out of the measurement without failing.`,
  );
}

/** The values one flag can take across the documents a page source renders to. */
const arms = (answer: FlagAnswer) => (answer === "varies" ? [true, false] : [answer]);

/** Every bar one page source can ship: one configuration, doubled per `"varies"` flag. */
function barFlags(source: string, pageName: string): BarFlags[] {
  const attrs = source.match(/<Base\b([^>]*)>/)?.[1];
  if (attrs === undefined) throw new Error("page no longer opens with a recognisable <Base …> tag");
  const on = (flag: string): FlagAnswer => {
    const written = new RegExp(`\\b${flag}=\\{([^}]*)\\}`).exec(attrs)?.[1];
    return written === undefined ? false : resolveFlag(pageName, flag, written.trim(), source);
  };
  const configurations: BarFlags[] = [];
  for (const highlight of arms(on("highlight")))
    for (const borders of arms(on("borders")))
      for (const spotlight of arms(on("spotlight")))
        for (const quality of arms(on("quality")))
          configurations.push({ highlight, borders, spotlight, quality });
  return configurations;
}

/**
 * Every page under `src/pages/`, keyed by the path Astro routes it from.
 *
 * `import.meta.glob` rather than `readdirSync`, because this file runs in a real browser: Vite
 * resolves the pattern at build time and inlines each page's source, so there is no filesystem to
 * read. Recursive, since a body's Lite page is nested (`mars/lite.astro`) and a non-recursive
 * pattern would silently exclude a whole tier of the site.
 */
const PAGE_SOURCES = import.meta.glob("../pages/**/*.astro", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** The groups a configuration turns on, so each measured bar names itself in its own title. */
const describeFlags = (flags: BarFlags) =>
  (["highlight", "borders", "spotlight", "quality"] as const)
    .filter((flag) => flags[flag])
    .join("+");

/**
 * Every bar the site ships, one entry per configuration rather than one per page.
 *
 * A page turning nothing on renders no bar and drops out here — `about.astro` passes no flags at
 * all, and the arm of `[slug].astro` for a country with no spotlight has nothing left to show.
 */
const PAGE_BARS = Object.entries(PAGE_SOURCES)
  .map(([path, source]) => ({ page: path.replace("../pages/", ""), source }))
  .flatMap(({ page: name, source }) =>
    barFlags(source, name).map((flags) => ({
      page: name,
      flags,
      label: `${name} [${describeFlags(flags)}]`,
    })),
  )
  .filter(({ flags }) => flags.borders || flags.spotlight || flags.quality)
  .toSorted((a, b) => a.label.localeCompare(b.label));

/**
 * The bar carrying the most control groups, for the one assertion that needs a single subject.
 *
 * Derived rather than named, and by group COUNT rather than by width: padding is charged per
 * button, so the fullest bar is the one whose width moves most across the phone breakpoint, which
 * is what makes that measurement sensitive enough to fail. Naming a page here would be a second
 * hand-maintained list — the thing the sweep above exists to remove.
 */
const groupCount = ({ borders, spotlight, quality }: BarFlags) =>
  Number(borders) + Number(spotlight) + Number(quality);
const FULLEST_BAR = PAGE_BARS.toSorted((a, b) => groupCount(b.flags) - groupCount(a.flags))[0];

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

/** One sheet's rules. A sheet the runner injected from another origin throws rather than
 *  reporting empty, and an unreadable sheet is not a missing rule. */
function rulesOf(sheet: CSSStyleSheet): CSSRule[] {
  try {
    return Array.from(sheet.cssRules);
  } catch {
    return [];
  }
}

const mounted: HTMLElement[] = [];

afterEach(() => {
  for (const element of mounted.splice(0)) element.remove();
});

function mountBar(flags: BarFlags) {
  const host = document.createElement("div");
  host.innerHTML = unionBarMarkup();
  // On the host rather than in the stylesheet: `.view-bar button` takes `font: inherit`, so the
  // whole subtree resolves from here and the shipped `--sans` is left exactly as it ships.
  host.style.fontFamily = MEASUREMENT_FONT;
  document.body.append(host);
  mounted.push(host);

  const bar = host.querySelector<HTMLElement>(".view-bar")!;
  const items = host.querySelector<HTMLElement>(".view-bar-items")!;
  const hide = (selector: string) => {
    const element = host.querySelector<HTMLElement>(selector);
    if (element) element.style.display = "none";
  };
  if (!flags.highlight) hide("#highlight-toggle");
  if (!flags.borders) hide("#border-toggle");
  if (!flags.spotlight) hide("#spotlight-toggle");
  if (!flags.quality) hide(".quality-fab");
  // Mirrors the layout's own condition for the divider.
  if (!((flags.highlight || flags.borders || flags.spotlight) && flags.quality)) {
    hide(".view-bar-divider");
  }

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
    expect(markup).toContain("highlight-toggle");
    expect(markup).toContain("border-toggle");
    expect(markup).toContain("spotlight-toggle");
    expect(markup).toContain("view-bar-divider");
    expect(markup).toContain("quality-fab");
    expect(markup).not.toContain("&&");
    // And that the sweep found the bars, since a walk that matched nothing satisfies every width
    // assertion below by having no bar to wrap. Derived from the registry rather than listed: a
    // body's globe is where a new control group lands, so every body's page has to be measured.
    const measured = PAGE_BARS.map((entry) => entry.page);
    expect(measured, "the sweep missed the gallery").toContain("index.astro");
    // The country page is the one whose bar VARIES per rendered document, and the one a list of
    // named pages had been leaving out entirely — so its presence is what proves the expansion ran.
    expect(measured, "the sweep missed the country page").toContain("[slug].astro");
    for (const slug of Object.keys(BODIES)) {
      expect(measured, `${slug}'s globe ships a bar nothing measures`).toContain(
        `${slug}/index.astro`,
      );
    }
    // And that they are not all the SAME bar — three copies of one configuration would pass
    // everything below while measuring one thing three times.
    for (const flag of ["highlight", "borders", "spotlight"] as const) {
      const answers = [...new Set(PAGE_BARS.map((entry) => entry.flags[flag]))].toSorted();
      expect(answers, `every measured page answers ${flag} the same way`).toEqual([false, true]);
    }

    // The string being right is not the DOM being right. The first version of this file parsed to
    // a tier segment nested INSIDE the 1 px divider, which every width assertion then passed —
    // a narrower bar fits more easily, so the harness's own bug read as a comfortable result.
    // Assert the shape the browser actually built: four groups, all siblings, in source order.
    const bar = mountBar({ highlight: true, borders: true, spotlight: true, quality: true });
    const children = [...bar.bar.querySelector(".view-bar-items")!.children];
    expect(children.map((child) => child.id || child.className)).toEqual([
      "highlight-toggle",
      "border-toggle",
      "spotlight-toggle",
      "view-bar-divider",
      "quality-fab",
    ]);
  });

  /**
   * The pointer control is not offered where the primary input cannot hover.
   *
   * SPLIT IN TWO, because only half of the claim is reachable from here: the browser context fixes
   * its own hover capability for the whole run, so the CONDITION is read off the shipped sheet
   * while the DECLARATION is put through the real cascade. The second half is the one with a live
   * opponent — `.view-bar button.icon-btn` sets `display: inline-flex`, so a hide written as a
   * class would lose and the control would ship to touch devices regardless, with every other
   * assertion in this file still green.
   */
  it("does not offer the pointer control where the pointer cannot hover", () => {
    const hides = [...document.styleSheets]
      .flatMap(rulesOf)
      .filter((rule) => rule instanceof CSSMediaRule)
      .filter((rule) => /\(\s*hover\s*:\s*none\s*\)/.test(rule.conditionText))
      .flatMap((rule) => Array.from(rule.cssRules))
      .filter((rule) => rule instanceof CSSStyleRule)
      .filter((rule) => rule.selectorText.includes("highlight-toggle"));
    expect(hides, "no `hover: none` block hides the highlight toggle").toHaveLength(1);
    expect(hides[0].style.display).toBe("none");

    const bar = mountBar({ highlight: true, borders: true, spotlight: false, quality: true });
    const button = bar.bar.querySelector<HTMLElement>("#highlight-toggle")!;
    // `flex`, not the `inline-flex` the sheet declares: a flex item's display is blockified.
    expect(getComputedStyle(button).display).toBe("flex");
    const unconditional = document.createElement("style");
    unconditional.textContent = hides[0].cssText;
    document.head.append(unconditional);
    try {
      expect(getComputedStyle(button).display, "the hide loses the cascade to .icon-btn").toBe(
        "none",
      );
    } finally {
      unconditional.remove();
    }
  });

  it("is measuring in the face it pins, not in whatever the box fell back to", () => {
    // `document.fonts.check` is NOT the oracle: asked about a family that does not exist it
    // answered true, so it cannot tell a resolved face from a fallback. Widths can — an absent
    // DejaVu renders in the default face, which is what an unresolvable name renders in too.
    // The one false alarm this cannot distinguish is a box whose DEFAULT face is DejaVu Sans, and
    // that direction is the safe one: it fails loudly rather than measuring the wrong thing.
    expect(
      inkWidth(MEASUREMENT_FONT),
      `${MEASUREMENT_FONT} did not resolve — every width in this file is a fallback's`,
    ).not.toBe(inkWidth('"NoSuchFaceZZ"'));
  });

  // ONE CASE OVER EVERY CONFIGURATION, not `it.each` over them, and the reason is the harness that
  // proves this guard is not vacuous: it finds a guard by its title in the source, and an `it.each`
  // title built from a derived label is a string that exists only at runtime. The configurations
  // are found rather than listed, so their names cannot be literals — which makes a static title
  // the only kind this file can have. Each configuration still names itself in the failure.
  it("fits on one row at 320px, on every bar the site ships", async () => {
    await page.viewport(NARROWEST_PX, 823);
    for (const { label, flags } of PAGE_BARS) {
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
    }
  });

  it("keeps the tighter phone padding, which is what buys the fit", async () => {
    // The 420 px breakpoint is load-bearing, not cosmetic. Measured either side of it so that
    // deleting the media query fails here rather than silently eating the slack above.
    await page.viewport(TIGHT_MAX_PX, 823);
    const tight = mountBar(FULLEST_BAR.flags).required();
    mounted.splice(0).forEach((element) => element.remove());
    await page.viewport(TIGHT_MAX_PX + 1, 823);
    const roomy = mountBar(FULLEST_BAR.flags).required();

    expect(tight).toBeLessThan(roomy);
  });

  it("can tell a bar that does not fit, so a passing measurement means something", async () => {
    // The positive control, and the record of a real limit: the union of every group Base.astro can
    // emit needs more than 320 px allows, so no page may turn all four on at once. Nothing does
    // today — and because the configurations above are read from the pages, the day one does it is
    // measured rather than assumed.
    await page.viewport(NARROWEST_PX, 823);
    const union = mountBar({ highlight: true, borders: true, spotlight: true, quality: true });
    expect(union.required()).toBeGreaterThan(union.allowed());
    expect(union.rows()).toBeGreaterThan(1);
  });
});
