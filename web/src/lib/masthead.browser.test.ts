import { afterEach, describe, expect, it } from "vitest";
// `vitest/browser`, not `@vitest/browser/context` — the latter still resolves but warns that it
// stops working next major. This is the first test here to need the viewport, so there was no
// existing import to copy.
import { page } from "vitest/browser";

import "../styles/global.css";
import galleryPage from "../pages/index.astro?raw";
import mastheadComponent from "../components/Masthead.astro?raw";

/**
 * The masthead's height must not depend on how WIDE its heading is.
 *
 * This is the invariant whose absence cost the gallery a CLS of 0.328. At 412 px the row measured
 * `title 117 + gap 16 + nav 219` against 352 px of space — full to the pixel — so the heading
 * growing 14 px when the webfont swapped in wrapped the nav onto a second line, grew the header by
 * 38 px, and moved all 203 cards. A second post-paint change (a nav link being removed) flipped it
 * back, and CLS charged us for both.
 *
 * Nothing in the suite could see that, because `getBoundingClientRect()` is zeroes without a
 * renderer. It is asserted here against real layout, by sweeping the heading through a width range
 * that brackets every font state rather than by loading a particular font — the fallback face is
 * the visitor's, not ours, so pinning one font would be pinning this machine.
 *
 * THE CSS IS THE SHIPPED CSS, read out of the two `.astro` files rather than copied. That is the
 * whole point: a copy would go on proving a layout the site had stopped shipping, and this defect
 * was born the day a rule left the row with no room. Add a nav item, grow the heading, widen a gap
 * or delete the stack breakpoint, and some width in the sweep wraps.
 */

/**
 * Viewports the site serves. 320 is the narrowest — `Base.astro` sizes the view bar for it.
 * Written as strings because they become test TITLES, and a sabotage guard has to name one.
 */
const SERVED_WIDTHS = ["320px", "360px", "390px", "412px", "430px", "768px", "1280px"];

/** Below this the row stacks deterministically rather than fitting by a few pixels. */
const STACK_MAX_PX = 359.98;

/**
 * The heading widths a metric change can produce. Measured here: 103 px in the fallback serif and
 * 117 px in Fraunces. The sweep is deliberately wider on both sides, because Astro's
 * metric-matched face is `src: local("Times New Roman")` — which resolves on neither Linux nor
 * Android — so the real spread is a property of the visitor's device.
 */
const HEADING_SWEEP_PX = { from: 88, to: 142, step: 2 };

/**
 * Astro scopes component styles with a generated attribute at BUILD time and rewrites `:global(x)`
 * to plain `x`. The raw source has neither, so the selectors already match anything — except
 * `:global(...)`, which a browser parses as an unknown pseudo-class and drops the whole rule for.
 * Unwrapping it is the one transform applied, and it is the reason the stack rule survives.
 */
function shippedStyles(...sources: string[]): string {
  const css = sources
    .flatMap((source) => [...source.matchAll(/<style>([\s\S]*?)<\/style>/g)].map((match) => match[1]))
    .join("\n");
  return css.replace(/:global\(([^)]*)\)/g, "$1");
}

const MASTHEAD_CSS = shippedStyles(mastheadComponent, galleryPage);

const mounted: HTMLElement[] = [];

afterEach(() => {
  for (const element of mounted.splice(0)) element.remove();
});

/**
 * The gallery's own masthead markup. Extracted from the page rather than retyped, so a nav item
 * added there is a nav item measured here — which is exactly the change that caused the defect.
 */
function galleryNavMarkup(): string {
  const nav = galleryPage.match(/<nav slot="actions" class="head-links">[\s\S]*?<\/nav>/)?.[0];
  if (!nav) throw new Error("index.astro no longer contains a recognisable head-links nav");
  // The page is a template: strip Astro expressions so the fragment is plain HTML. `href={REPO_URL}`
  // becomes a literal, and the comment braces go.
  return nav
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/href=\{[^}]*\}/g, 'href="https://github.com/"')
    .replace(/\{[^}]*\}/g, "");
}

function mountMasthead() {
  const style = document.createElement("style");
  style.textContent = MASTHEAD_CSS;
  const header = document.createElement("header");
  header.className = "masthead";
  header.style.setProperty("--masthead-max", "min(2200px, 94vw)");
  header.innerHTML = `
    <div class="masthead-row">
      <div class="masthead-title">
        <p class="eyebrow">Atlas</p>
        <h1>Terrella</h1>
      </div>
      ${galleryNavMarkup()}
    </div>
  `;
  document.body.append(style, header);
  mounted.push(style, header);

  const row = header.querySelector<HTMLElement>(".masthead-row")!;
  const title = header.querySelector<HTMLElement>(".masthead-title")!;
  const nav = header.querySelector<HTMLElement>(".head-links")!;
  const heading = header.querySelector<HTMLElement>("h1")!;
  return {
    row,
    nav,
    /** Model a metric change without needing the font: drive the heading's width directly. */
    setHeadingWidth(px: number) {
      heading.style.width = `${px}px`;
    },
    /** Two lines means the nav has dropped below the title — the 38 px the gallery paid for. */
    isStacked() {
      const titleBox = title.getBoundingClientRect();
      const navBox = nav.getBoundingClientRect();
      return Math.round(navBox.y) >= Math.round(titleBox.y + titleBox.height);
    },
    height() {
      return Math.round(row.getBoundingClientRect().height);
    },
  };
}

function sweep(masthead: ReturnType<typeof mountMasthead>) {
  const seen: { width: number; height: number; stacked: boolean }[] = [];
  for (let width = HEADING_SWEEP_PX.from; width <= HEADING_SWEEP_PX.to; width += HEADING_SWEEP_PX.step) {
    masthead.setHeadingWidth(width);
    seen.push({ width, height: masthead.height(), stacked: masthead.isStacked() });
  }
  return seen;
}

describe("the masthead's height does not depend on its heading's width", () => {
  it("is measuring the shipped stylesheet, not an empty string", () => {
    // Every assertion below is a "nothing changed" one, which a stylesheet that failed to load
    // satisfies for free. Prove the CSS arrived and carries the two rules that do the work.
    expect(MASTHEAD_CSS).toContain("flex-wrap: wrap");
    expect(MASTHEAD_CSS).toContain(`@media (max-width: ${STACK_MAX_PX}px)`);
    expect(galleryNavMarkup()).toContain("head-source");
  });

  // `it.each` with `%s` rather than a loop over a template literal, so the rendered titles are
  // reconstructable from source — `tests/test_sabotage_cases.py` matches a sabotage case's guard
  // against the test files as TEXT, and a title built by `${}` interpolation exists nowhere in them.
  it.each(SERVED_WIDTHS)(
    "holds one layout across every heading width at %s",
    async (label) => {
      const viewport = Number.parseInt(label, 10);
      await page.viewport(viewport, 823);
      const masthead = mountMasthead();
      const seen = sweep(masthead);

      expect(seen.length).toBeGreaterThan(20);

      const heights = [...new Set(seen.map((entry) => entry.height))];
      expect(
        heights,
        `masthead height changed with the heading width at ${viewport}px: ` +
          seen.map((entry) => `${entry.width}->${entry.height}`).join(" "),
      ).toHaveLength(1);

      // And the layout it holds is the one intended for that width, not merely a stable wrong one.
      const stacked = [...new Set(seen.map((entry) => entry.stacked))];
      expect(stacked).toHaveLength(1);
      expect(stacked[0]).toBe(viewport <= STACK_MAX_PX);
    },
  );

  it("stacks to the LEFT, aligned with everything else in the header", async () => {
    // Not a nicety. The first version of the stack rule lived in the page as `:global(.masthead-row)`
    // and lost on specificity to the component's own `align-items: flex-end`, so it got the column
    // and not the alignment — the title and nav shipped right-aligned against a left-aligned tagline
    // and legend. This file could not see that (it injects raw CSS, with no Astro scoping for the
    // page rule to lose to), so `masthead.test.ts` owns the cascade half. This owns the outcome.
    await page.viewport(320, 823);
    const masthead = mountMasthead();
    expect(masthead.isStacked()).toBe(true);
    const title = masthead.row.querySelector<HTMLElement>(".masthead-title")!.getBoundingClientRect();
    expect(Math.round(masthead.nav.getBoundingClientRect().x)).toBe(Math.round(title.x));
  });

  it("can tell the two layouts apart, so a passing sweep means something", async () => {
    // The positive control: proves the probe reports a wrap when there genuinely is one.
    await page.viewport(412, 823);
    const masthead = mountMasthead();
    expect(masthead.isStacked()).toBe(false);
    masthead.setHeadingWidth(320);
    expect(masthead.isStacked()).toBe(true);
  });

  it("gives the icon link a real touch target, not just its ink", async () => {
    // 16.8 px of octicon is not something a thumb can hit. WCAG 2.2 AA puts the floor at 24×24,
    // and the padding that reaches it is also what the nav-width arithmetic above is built on —
    // so this is here to stop the padding being 'tidied' away as decoration.
    await page.viewport(412, 823);
    const masthead = mountMasthead();
    const box = masthead.nav.querySelector<HTMLElement>(".head-source")!.getBoundingClientRect();
    expect(Math.round(box.width)).toBeGreaterThanOrEqual(24);
    expect(Math.round(box.height)).toBeGreaterThanOrEqual(24);
  });

  it("leaves the row real slack at the narrowest width it does not stack", async () => {
    // 360 px is the tightest one-line case. The margin has to survive a metric change bigger than
    // the 14 px measured here, because the fallback font is the visitor's, not ours.
    await page.viewport(360, 823);
    const masthead = mountMasthead();
    masthead.setHeadingWidth(117);
    const row = masthead.row.getBoundingClientRect();
    const nav = masthead.nav.getBoundingClientRect();
    const slack = Math.round(row.width) - 117 - 16 - Math.round(nav.width);
    expect(masthead.isStacked()).toBe(false);
    expect(slack, `only ${slack}px of slack at 360px`).toBeGreaterThanOrEqual(16);
  });
});
