import { afterEach, describe, expect, it } from "vitest";
import { page } from "vitest/browser";

import "../styles/global.css";
import baseLayout from "../layouts/Base.astro?raw";
import { BODIES, type BodySlug } from "./bodies";
import { bodyRoutes } from "./bodyRoutes";

/**
 * The body switcher: one entry per body, the current one marked, and nothing else deciding either.
 *
 * TWO HALVES, AND THE SPLIT IS THE SAME ONE `bodies.browser.test.ts` DRAWS. What `Base.astro` emits
 * can only be read as source — it is an Astro expression over the registry, and no renderer in this
 * suite runs it. What the cascade does with the result can only be read from a browser: the marked
 * entry is filled with `var(--accent)`, and whether that token resolves to this body's colour is a
 * property of several rules in three blocks rather than of the one line that names it.
 *
 * SO THE MOUNTED MARKUP IS BUILT HERE RATHER THAN EXTRACTED, and the honest reading of that is: the
 * computed half proves the STYLESHEET, not the template. What ties the two together is the source
 * half below, which pins the three things the built markup assumes — the class, the element, and
 * that the current body is marked with `aria-current`. A hand-built fixture that drifted from any
 * of those would go on passing while the shipped control lost its fill, so those assertions are the
 * load-bearing ones rather than the decoration.
 */

/** The narrowest width the site serves — the same floor the view bar is sized against. */
const NARROWEST_PX = 320;

/** Room the pill must still have spare at that width once it has laid out on one row. */
const MIN_SLACK_PX = 16;

/** The switcher's markup, as `Base.astro` composes it from the registry. */
function switcherMarkup(current: BodySlug): string {
  const entries = Object.values(BODIES).map((entry) => {
    const mark = entry.slug === current ? ' aria-current="true"' : "";
    return `<a href="${bodyRoutes(entry.slug).globe}"${mark}>${entry.label}</a>`;
  });
  return `<nav class="body-switcher" aria-label="Which body">${entries.join("")}</nav>`;
}

const mounted: HTMLElement[] = [];
const root = document.documentElement;
const originalBody = root.getAttribute("data-body");

afterEach(() => {
  for (const element of mounted.splice(0)) element.remove();
  if (originalBody === null) root.removeAttribute("data-body");
  else root.setAttribute("data-body", originalBody);
});

/** Mount the switcher as the given body's page would, with that body's tokens in force. */
function mountSwitcher(current: BodySlug) {
  root.setAttribute("data-body", current);
  const host = document.createElement("div");
  host.innerHTML = switcherMarkup(current);
  document.body.append(host);
  mounted.push(host);
  const nav = host.querySelector<HTMLElement>(".body-switcher")!;
  return {
    host,
    nav,
    links: [...nav.querySelectorAll("a")],
    marked: nav.querySelector<HTMLElement>("a[aria-current]")!,
    /** Space the pill is allowed — `max-width`, resolved by the browser rather than restated. */
    allowed: () => Number.parseFloat(getComputedStyle(nav).maxWidth),
    /** Width it needs on one row, with the cap lifted so a wrapped pill cannot read as fitting. */
    required: () => {
      nav.style.maxWidth = "none";
      const width = nav.getBoundingClientRect().width;
      nav.style.maxWidth = "";
      return width;
    },
  };
}

describe("the switcher marks the body you are on, in that body's own colour", () => {
  it("fills the current entry with the accent and leaves the others plain", async () => {
    await page.viewport(1280, 823);
    for (const slug of Object.keys(BODIES) as BodySlug[]) {
      const { host, links, marked } = mountSwitcher(slug);
      const accent = getComputedStyle(root).getPropertyValue("--accent").trim();
      // The negative control the assertion below needs: a token that failed to resolve is the empty
      // string, and `background-color` would then be the transparent both entries already have —
      // so "filled" and "not filled" would be one measurement and this would pass blind.
      expect(accent, `--accent must resolve for ${slug}`).not.toBe("");
      const filled = links.filter(
        (link) => getComputedStyle(link).backgroundColor !== "rgba(0, 0, 0, 0)",
      );
      expect(filled.length, `exactly one entry is current on ${slug}`).toBe(1);
      expect(filled[0], `the filled entry is the marked one on ${slug}`).toBe(marked);
      expect(marked.textContent).toBe(BODIES[slug].label);
      host.remove();
    }
  });

  it("holds one row at the narrowest width the site serves", async () => {
    // The pill is `position: fixed`, so a wrap here is a look regression rather than a layout
    // shift — but it is also the control that grows by a whole entry every time a body is added,
    // which is the one direction this page's chrome is guaranteed to move in.
    await page.viewport(NARROWEST_PX, 823);
    const { allowed, required, links } = mountSwitcher("earth");
    expect(links.length, "a switcher of one has nothing to measure").toBeGreaterThan(1);
    expect(required()).toBeLessThanOrEqual(allowed() - MIN_SLACK_PX);
  });
});

describe("nothing but the registry decides what the switcher contains", () => {
  /** The `<nav>` block as `Base.astro` writes it. */
  const start = baseLayout.indexOf('<nav class="body-switcher"');
  if (start < 0) throw new Error("Base.astro no longer contains a recognisable body switcher");
  const markup = baseLayout.slice(start, baseLayout.indexOf("</nav>", start));

  it("emits one entry per body, from the registry rather than from a list", () => {
    expect(markup).toContain("Object.values(BODIES).map");
    expect(markup).toContain("{entry.label}");
    expect(markup).toContain("bodyRoutes(entry.slug).globe");
  });

  it("names no body in the markup, so a third planet is a registry row and nothing else", () => {
    // The failure this catches is the obvious first draft — two hand-written links. It reads
    // identically on screen today and stops being the whole set the moment a body is added, with
    // every other gate green: the new planet has a page, an accent and a lite route, and no way to
    // reach it. `slug` as well as `label`, since the href is the half a copy would hard-code.
    for (const { slug, label } of Object.values(BODIES)) {
      expect(markup, `${slug} is written into the switcher by hand`).not.toContain(`"${slug}"`);
      expect(markup, `${label} is written into the switcher by hand`).not.toContain(`>${label}<`);
    }
  });

  it("marks the current body with aria-current, which is what the fill is keyed on", () => {
    // The two are one decision. `global.css` paints `a[aria-current]`, so a mark moved to a class
    // would take the fill with it and leave a screen reader with an unmarked set — and the mounted
    // fixture above, which writes the attribute itself, would go on measuring a fill the shipped
    // control no longer gets.
    expect(markup).toMatch(/aria-current=\{entry\.slug === body \? "true" : undefined\}/);
  });

  it("goes on every page that belongs to a body, and derives that from the role", () => {
    // NOT A PROP. `pageRole` already separates a body's two pages from the pages that belong to no
    // body, so a `switcher` boolean would be that same set written a second time on five pages —
    // and the copy that falls out of step is silent, because a page missing the control still
    // renders perfectly.
    expect(baseLayout).toMatch(/pageRole !== "plain" && \(\s*<nav class="body-switcher"/);
    expect(baseLayout, "the switcher gained a prop that duplicates the role").not.toMatch(
      /\n {2}switcher\??:/,
    );
  });
});

describe("the pill and the space it is given ship together", () => {
  it("is displayed, and drops whatever else centres in that band by a real distance", () => {
    // BOTH HALVES IN ONE ASSERTION, because either alone is worse than neither: the drop with no
    // pill is a country chip hanging under nothing, and the pill with no drop is two boxes on one
    // line. They are two declarations in two components, so nothing but this couples them — and
    // both failures render, which is what makes them the pair worth pinning rather than the pair
    // the next reader would notice.
    const { nav } = mountSwitcher("earth");
    expect(getComputedStyle(nav).display).toBe("flex");
    expect(
      Number.parseFloat(getComputedStyle(root).getPropertyValue("--switcher-drop")),
      "the drop must be a real distance, or the chip clears nothing",
    ).toBeGreaterThan(0);
  });
});
