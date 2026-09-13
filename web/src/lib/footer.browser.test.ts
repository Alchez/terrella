import { afterEach, describe, expect, it } from "vitest";

import "../styles/global.css";
import globalCss from "../styles/global.css?raw";
import footerComponent from "../components/Footer.astro?raw";
import { GITHUB_MARK } from "./siteLinks";

/**
 * The site's footer, and the fixed pill that floats over the bottom of the page it sits on.
 *
 * WHAT GOES WRONG IS NOT VISIBLE IN A STYLESHEET. The view bar is `position: fixed`, so it is
 * outside the footer's flow entirely: the footer renders, its links render, and on a page with a
 * bar the last row is simply underneath it. Nothing errors, nothing looks broken, and the link is
 * unclickable in the exact place a mouse lands.
 *
 * The clearance constant is deliberately NOT what this asserts. `--view-bar-clear` is a measured
 * number in a stylesheet and a measured number cannot notice the pill growing; the overlap
 * predicate can, so the number is free to be wrong and this is what says so.
 */

/** Astro scopes component selectors at build time and rewrites `:global(x)` to plain `x`; the raw
 *  source has neither, so the rules already match. Same transform `masthead.browser.test.ts` makes,
 *  for the same reason: this must be the shipped CSS and not a copy of it. */
function shippedStyles(...sources: string[]): string {
  return sources
    .flatMap((source) => [...source.matchAll(/<style>([\s\S]*?)<\/style>/g)].map((m) => m[1]))
    .join("\n")
    .replace(/:global\(([^)]*)\)/g, "$1");
}

/** The footer's own scoped block. The bar is styled in `global.css`, which the import above puts
 *  into the document for real rather than as a copy. */
const CSS = shippedStyles(footerComponent);

/** The widths the site serves, narrowest first. 320 is the floor `Base.astro` sizes the bar for. */
const SERVED_WIDTHS = [320, 360, 390, 412, 430, 768, 1280];

const mounted: HTMLElement[] = [];
afterEach(() => {
  for (const element of mounted.splice(0)) element.remove();
  document.documentElement.style.removeProperty("width");
});

/** The real pill and the real footer, both from the shipped sources, in a page tall enough that the
 *  footer is at the bottom of a scrolled document rather than in the middle of an empty one. */
function mount() {
  const style = document.createElement("style");
  style.textContent = CSS;
  const filler = document.createElement("div");
  filler.style.height = "1600px";
  const footer = document.createElement("footer");
  footer.className = "site-footer clears-bar";
  // The last link is the mark, not a word, because that is what the row has to fit and clear: a
  // padded icon is a different height and width from the text beside it.
  footer.innerHTML = `<nav aria-label="Site">
    <a href="/">Gallery</a><a href="/about/">About</a><a href="/archives/">Archives</a>
    <a class="source" href="#" aria-label="Source on GitHub"><svg viewBox="${GITHUB_MARK.viewBox}" aria-hidden="true"><path d="${GITHUB_MARK.path}"></path></svg></a>
  </nav>`;
  const bar = document.createElement("div");
  bar.className = "view-bar";
  bar.innerHTML = `<div class="view-bar-items" role="group">
    <button type="button">Borders</button><button type="button">Focus</button>
    <span class="view-bar-divider"></span>
    <div class="quality-fab" role="radiogroup">
      <button type="button">Lite</button><button type="button">Globe</button><button type="button">Full</button>
    </div>
  </div>`;
  document.body.append(style, filler, footer, bar);
  mounted.push(style, filler, footer, bar);
  return { footer, bar };
}

/** The predicate written out, over real rects, rather than a clearance compared against a constant. */
function overlaps(a: DOMRect, b: DOMRect): boolean {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

describe("the site footer clears the pill that floats over it", () => {
  it("is measuring the shipped stylesheet, not an empty string", () => {
    // Every assertion below is a "nothing collides" one, which no CSS at all satisfies for free:
    // with the rules missing the bar is not fixed, falls into flow below the footer, and can never
    // overlap it. So prove the footer's block arrived, the stylesheet still floats the bar, and the
    // bar in THIS document is actually taken out of flow.
    expect(CSS).toContain("--view-bar-clear");
    expect(globalCss).toMatch(/\.view-bar\s*\{\s*position:\s*fixed/);
    const { bar } = mount();
    expect(getComputedStyle(bar).position).toBe("fixed");
  });

  it("keeps every link out from under the view bar, at every width the site serves", () => {
    const { footer, bar } = mount();
    for (const width of SERVED_WIDTHS) {
      document.documentElement.style.width = `${width}px`;
      window.scrollTo(0, document.body.scrollHeight);
      const barBox = bar.getBoundingClientRect();
      for (const link of footer.querySelectorAll("a")) {
        expect(
          overlaps(link.getBoundingClientRect(), barBox),
          `${link.textContent} sits under the view bar at ${width}px`,
        ).toBe(false);
      }
    }
  });

  it("asks for that clearance only where a bar is drawn", () => {
    // A page with no bar must not carry the gap: it is a strip of nothing under the last row, and
    // the country pages, the gallery and the archives page do not all have one.
    const { footer } = mount();
    const withBar = getComputedStyle(footer).paddingBottom;
    footer.classList.remove("clears-bar");
    expect(getComputedStyle(footer).paddingBottom).not.toBe(withBar);
  });
});
