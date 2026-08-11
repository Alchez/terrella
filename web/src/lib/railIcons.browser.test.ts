import { describe, it, expect, afterEach } from "vitest";
import globeSource from "../components/Globe.astro?raw";
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

/** One rail button in MapLibre's own markup, which is what the shared icon rule keys on. */
function railButton(controlClass: string): string {
  const pressed = controlClass === "rg-ctrl-quiet" ? ' aria-pressed="true"' : "";
  return `<button class="${controlClass}"${pressed}><span class="maplibregl-ctrl-icon" aria-hidden="true"></span></button>`;
}

/**
 * The rail as quiet mode leaves it — the frame group, the camera group, and `is-quiet` on the body.
 *
 * `frameButtons` is the order INSIDE the frame group, and it is the whole subject: that order is
 * the only difference between a lone eye and an eye wearing a clipped hairline, and it is decided
 * in `Globe.astro` where no stylesheet can see it.
 */
function mountQuietRail(frameButtons: readonly string[]) {
  inject(globalCss);
  inject(globalStyleBlock());
  inject(maplibreCss);

  document.body.className = "is-quiet";
  document.body.innerHTML = `
    <div class="maplibregl-ctrl-top-right">
      <div class="maplibregl-ctrl maplibregl-ctrl-group">${frameButtons.map(railButton).join("")}</div>
      <div class="maplibregl-ctrl maplibregl-ctrl-group">${["maplibregl-ctrl-zoom-in", "maplibregl-ctrl-zoom-out", "rg-ctrl-spin"].map(railButton).join("")}</div>
    </div>`;

  const quiet = document.querySelector(".rg-ctrl-quiet");
  const camera = document.querySelector(".maplibregl-ctrl-zoom-in")?.closest(".maplibregl-ctrl-group");
  if (!(quiet instanceof HTMLElement) || !(camera instanceof HTMLElement)) {
    throw new Error("the quiet rail did not mount");
  }
  return { quiet, camera };
}

afterEach(() => {
  for (const element of installed.splice(0)) element.remove();
  document.body.innerHTML = "";
  document.body.className = "";
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

describe("quiet mode leaves ONE ghost, and it is in the corner", () => {
  it("gives the surviving eye no hairline, because it leads its group", () => {
    // The defect this replaces: with the group ordered [fullscreen, quiet], quiet mode set
    // fullscreen to `display: none` and the eye went on matching `button + button` — DOM order,
    // not visibility — so it kept a 1px top border that the group's 999px radius clipped into a
    // dark chord across the top of the circle. Reported from a phone as a nick out of the icon,
    // and cured at the time with a `border-top-width: 0` cancel. Ordering the group [quiet,
    // fullscreen] makes the eye the first child, so no `+` selector reaches it and the cancel is
    // gone. Computed, not scanned: this is the state the phone showed.
    const { quiet } = mountQuietRail(["rg-ctrl-quiet", "maplibregl-ctrl-fullscreen"]);
    expect(getComputedStyle(quiet).borderTopWidth).toBe("0px");
  });

  it("grows the chord straight back if the group is reordered — the positive control", () => {
    // Without this the assertion above would pass just as happily against a stylesheet with no
    // divider rule at all, i.e. while measuring nothing. Same sheets, same body class, only the
    // order changed, and the hairline must return.
    const { quiet } = mountQuietRail(["maplibregl-ctrl-fullscreen", "rg-ctrl-quiet"]);
    expect(
      getComputedStyle(quiet).borderTopWidth,
      "the divider must still be live, or the no-hairline assertion is vacuous",
    ).not.toBe("0px");
  });

  it("hides the camera group while keeping the frame group visible", () => {
    // The `:not(:has(.rg-ctrl-quiet))` split, rendered. It is `visibility` rather than `display` on
    // purpose — the box stays, which is exactly why the frame group has to come FIRST rather than
    // be re-anchored from here.
    const { quiet, camera } = mountQuietRail(["rg-ctrl-quiet", "maplibregl-ctrl-fullscreen"]);
    expect(getComputedStyle(camera).visibility).toBe("hidden");
    expect(getComputedStyle(quiet).visibility).toBe("visible");
  });

  it("keeps the page building that order, which no stylesheet can state", () => {
    // Both halves, because either one alone leaves the eye adrift. `addControl` APPENDS at every
    // `top-*` position, so the two calls' order IS the column's order; and the quiet button joins
    // at `"start"`, which is also what puts its fallback group at the top of the corner on a
    // browser where `FullscreenControl` renders nothing at all.
    const fullscreen = globeSource.indexOf("map.addControl(new maplibregl.FullscreenControl");
    const navigation = globeSource.indexOf("map.addControl(new maplibregl.NavigationControl");
    expect(fullscreen, "the page must still add a FullscreenControl").toBeGreaterThan(-1);
    expect(navigation, "the page must still add a NavigationControl").toBeGreaterThan(-1);
    expect(fullscreen, "the frame group must be added before the camera group").toBeLessThan(
      navigation,
    );
    expect(globeSource).toContain(
      'joinRailGroup(map.getContainer(), ".maplibregl-ctrl-fullscreen", quietToggle.button, "start")',
    );
  });
});

/**
 * `--page-inset` in px, resolved by the browser rather than restated as a number here.
 *
 * THE PROBE MEASURES A MARGIN BECAUSE THE SUBJECT IS A MARGIN. Read off `width` instead it comes
 * back 19.1875px against the margin's 19.2px — a used width is snapped to the layout grid and a
 * computed margin is not, so the two disagree by a 64th of a pixel and the assertion fails on the
 * instrument rather than on the rule.
 */
function resolvedPageInset(): string {
  const probe = document.createElement("div");
  probe.style.position = "absolute";
  probe.style.marginTop = "var(--page-inset)";
  document.body.append(probe);
  const inset = getComputedStyle(probe).marginTop;
  probe.remove();
  expect(inset, "--page-inset must resolve, or both assertions below compare nothing").not.toBe(
    "0px",
  );
  return inset;
}
describe("the rail sits the same distance off the edge as the row opposite it", () => {

  it("takes both offsets from the one token the top-left row uses", () => {
    // MapLibre hardcodes `margin: 10px 10px 0 0` here, so the rail sat 9.2px above and 9.2px
    // outside a row written at 1.2rem. Reported from a phone as the two rows not being level.
    // Computed, because the failure is a cascade one: our rule and theirs are both valid CSS.
    const { icon } = mountRail("maplibregl-ctrl-zoom-in");
    const group = icon.closest(".maplibregl-ctrl-group");
    if (!(group instanceof HTMLElement)) throw new Error("the group did not mount");

    const inset = resolvedPageInset();
    const style = getComputedStyle(group);
    expect(style.marginTop, "level with the top-left row").toBe(inset);
    expect(style.marginRight, "and the same distance in from its own edge").toBe(inset);
  });

  it("loses to MapLibre's own margin without the doubled class — the positive control", () => {
    // Their rule is (0,2,0) and injected at RUNTIME, so it lands after ours wherever ours sits.
    // Drop one class from our selector and the override must stop applying, which is what makes
    // the assertion above a measurement of the cascade rather than of a literal.
    const weakened = globalStyleBlock().replace(
      ".maplibregl-ctrl-top-right .maplibregl-ctrl.maplibregl-ctrl {",
      ".maplibregl-ctrl-top-right .maplibregl-ctrl {",
    );
    const { icon } = mountRail("maplibregl-ctrl-zoom-in", weakened);
    const group = icon.closest(".maplibregl-ctrl-group");
    if (!(group instanceof HTMLElement)) throw new Error("the group did not mount");

    expect(
      getComputedStyle(group).marginTop,
      "MapLibre's rule must be live, or the override assertion is vacuous",
    ).toBe("10px");
  });
});
