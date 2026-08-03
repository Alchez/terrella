import { describe, it, expect, afterEach } from "vitest";
import globeSource from "../pages/earth.astro?raw";
import globalCss from "../styles/global.css?raw";
import globeStyles from "../styles/globe.css?raw";
import maplibreCss from "maplibre-gl/dist/maplibre-gl.css?raw";

/**
 * The rail's icons are ALPHA STENCILS, not images, and nothing else in the suite can see it.
 *
 * Every MapLibre control icon ships as a `background-image` data-URI with its fill baked in, so
 * recolouring meant re-authoring an image per state. `earth.astro` retires that: the icon span gets
 * `background-image: none`, `background-color: currentColor` and `mask-image: var(--rail-icon)`, so
 * the glyph takes the button's `color` and every state falls out of the existing tokens.
 *
 * WHEN IT BREAKS THERE IS NO ERROR. `mask-image: none` is a perfectly valid computed value, so a
 * malformed data URI, an unset `--rail-icon`, or an override at losing specificity all leave the
 * span with `background-color: currentColor` and nothing shaping it — and it paints the WHOLE box
 * as a solid slab. Measured on the live page, all three routes. It has shipped twice already: once
 * through specificity (the compass rendered as a grey block) and once through `encodeURIComponent`
 * not escaping apostrophes. `pyright`, `astro check` and the node suite were green both times,
 * because none of them reads CSS.
 *
 * These run in the `browser` project because they need a real cascade. The page's CSS is reachable
 * after all — the rail lives in `<style is:global>`, which ships unscoped, so injecting the raw
 * text reproduces what the browser actually gets. MapLibre's sheet is injected LAST because in
 * production its ES-module import lands after the page's block wherever that block sits, which is
 * the whole reason every selector in there doubles a class.
 */

/** The globe's global stylesheet — the one the rail lives in.
 *
 *  A file now, where this used to dig the `<style is:global>` block out of the page. The
 *  non-vacuity check moved with it and is the point: read from the wrong path this returns nothing,
 *  every assertion below runs against an empty stylesheet, and the whole file passes silently. */
function globalStyleBlock(): string {
  expect(
    globeStyles,
    "src/styles/globe.css must carry the rail's rules — an empty read makes this file vacuous",
  ).toContain(".maplibregl-ctrl-top-right");
  return globeStyles;
}

const installed: HTMLStyleElement[] = [];

function inject(css: string): HTMLStyleElement {
  const element = document.createElement("style");
  element.textContent = css;
  document.head.appendChild(element);
  installed.push(element);
  return element;
}

/**
 * Install the three sheets in PRODUCTION ORDER and mount one control.
 * Returns the icon span plus the page's own <style>, so a test can mutate or drop it.
 */
function mountRail(controlClass: string, pageCss = globalStyleBlock()) {
  inject(globalCss);
  const page = inject(pageCss);
  inject(maplibreCss);

  document.body.innerHTML = `
    <div class="maplibregl-ctrl-top-right">
      <div class="maplibregl-ctrl maplibregl-ctrl-group">
        <button class="${controlClass}"><span class="maplibregl-ctrl-icon" aria-hidden="true"></span></button>
      </div>
    </div>`;

  const icon = document.querySelector(".maplibregl-ctrl-icon");
  if (!(icon instanceof HTMLElement)) throw new Error("icon span did not mount");
  return { icon, page };
}

/**
 * Every control the CSS gives a `--rail-icon`, read out of the browser's own parsed rules rather
 * than by regex — so `@media` nesting and re-serialisation cannot produce a phantom selector.
 */
function maskedControlClasses(): string[] {
  const page = inject(globalStyleBlock());
  const found = new Set<string>();

  const walk = (rules: CSSRuleList) => {
    for (const rule of rules) {
      if (rule instanceof CSSMediaRule) walk(rule.cssRules);
      if (!(rule instanceof CSSStyleRule)) continue;
      if (!rule.style.getPropertyValue("--rail-icon").trim()) continue;
      // `.maplibregl-ctrl-top-right .rg-ctrl-quiet[aria-pressed="true"] .maplibregl-ctrl-icon`
      // → the control is the class immediately before the icon span.
      const control = rule.selectorText.match(
        /\.([\w-]+)(?:\[[^\]]*\])?\s+\.maplibregl-ctrl-icon\s*$/,
      );
      if (control) found.add(control[1]);
    }
  };
  walk(page.sheet!.cssRules);

  expect(found.size, "no control declares a --rail-icon, so this file proves nothing").toBeGreaterThan(0);
  return [...found];
}

afterEach(() => {
  for (const element of installed.splice(0)) element.remove();
  document.body.innerHTML = "";
});

describe("the rail's icons are masks, not images", () => {
  it("gives every masked control a real stencil painted in currentColor", () => {
    for (const control of maskedControlClasses()) {
      const { icon } = mountRail(control);
      const style = getComputedStyle(icon);

      expect(style.maskImage, `${control}: the stencil must resolve`).not.toBe("none");
      expect(style.backgroundImage, `${control}: MapLibre's baked glyph must be suppressed`).toBe(
        "none",
      );
      // The identity the whole technique rests on: the paint IS the text colour. Asserted as an
      // identity rather than a hex value because the tokens sit behind `prefers-color-scheme`, and
      // a literal would only hold in whichever theme the runner happens to report.
      expect(style.backgroundColor, `${control}: the fill must be currentColor`).toBe(style.color);
    }
  });

  it("proves MapLibre's sheet is actually competing, not merely present", () => {
    // Without this, `backgroundImage === "none"` above would pass just as happily if MapLibre's CSS
    // had never loaded — the assertion would be measuring nothing. Dropping OUR block must let
    // MapLibre's baked data-URI glyph come back.
    const { icon, page } = mountRail("maplibregl-ctrl-zoom-in");
    expect(getComputedStyle(icon).backgroundImage).toBe("none");

    page.remove();
    expect(
      getComputedStyle(icon).backgroundImage,
      "MapLibre's own icon rule must be live, or the suppression assertion is vacuous",
    ).not.toBe("none");
  });

  it("falls back to a painted slab when the stencil goes — the failure this file exists for", () => {
    // The positive control. Strip the one declaration and the same element must land in exactly the
    // state that shipped twice: no mask at all, and a background still painted.
    const stripped = globalStyleBlock().replace(/(-webkit-)?mask-image: var\(--rail-icon\);/g, "");
    const { icon } = mountRail("maplibregl-ctrl-zoom-in", stripped);
    const style = getComputedStyle(icon);

    expect(style.maskImage, "no mask survives").toBe("none");
    expect(style.backgroundColor, "and the whole box is still painted").not.toBe("rgba(0, 0, 0, 0)");
  });

  it("keeps the compass authored rather than masked, which is a deliberate exception", () => {
    // Its icon is two triangles of different colours; one mask flattens them into a bowtie. If a
    // later tidy-up makes the compass "consistent" with the others, this fails.
    const { icon } = mountRail("maplibregl-ctrl-compass");
    const style = getComputedStyle(icon);

    expect(style.maskImage, "the compass must NOT take the shared stencil").toBe("none");
    expect(style.backgroundColor, "and must not paint its box either").toBe("rgba(0, 0, 0, 0)");
  });

  it("gives every rail toggle the page builds an icon to draw", () => {
    // The likeliest future break: a third control added beside spin and quiet with no `--rail-icon`
    // rule, which renders as a solid slab. Both sides are derived from source, so a new toggle is
    // covered the day it is added and no count here can go stale.
    const built = [...globeSource.matchAll(/className:\s*"(rg-ctrl-[\w-]+)"/g)].map(
      (match) => match[1],
    );
    expect(built.length, "the page must still build its rail toggles this way").toBeGreaterThan(0);

    const masked = maskedControlClasses();
    for (const toggle of built) {
      expect(masked, `${toggle} is built but has no --rail-icon rule`).toContain(toggle);
    }
  });
});

describe("every icon payload is a decodable SVG", () => {
  it("parses each data URI the page authors, and proves it found them", () => {
    // Read from the RAW text, not the CSSOM: `url("data:image/svg+xml,<garbage>")` is valid CSS, so
    // the parser accepts a payload that is not an SVG at all — and a payload malformed enough to be
    // rejected would simply VANISH from the CSSOM rather than show up as broken.
    const block = globalStyleBlock();
    const uris = [...block.matchAll(/url\("(data:image\/svg\+xml[^"]*)"\)/g)].map((m) => m[1]);

    // Cross-checked against an independent derivation instead of a hardcoded count, which would
    // rot: there is at least one payload per masked control, and if this regex ever stops matching
    // the comparison fails instead of reporting a cheerful zero.
    expect(
      uris.length,
      "found fewer icon payloads than masked controls — the extraction has stopped matching",
    ).toBeGreaterThanOrEqual(maskedControlClasses().length);

    const parser = new DOMParser();
    for (const uri of uris) {
      const payload = decodeURIComponent(uri.slice(uri.indexOf(",") + 1));
      const document_ = parser.parseFromString(payload, "image/svg+xml");

      expect(
        document_.querySelector("parsererror"),
        `payload does not parse as SVG: ${payload.slice(0, 90)}`,
      ).toBeNull();
      expect(document_.documentElement.tagName.toLowerCase(), "payload must be an <svg>").toBe(
        "svg",
      );
      expect(
        document_.documentElement.getAttribute("viewBox"),
        "every icon is sized by mask-size against its viewBox, so it must declare one",
      ).not.toBeNull();
    }
  });
});
