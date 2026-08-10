import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import {
  COUNTRY_PANEL_NOTE,
  countryPanelContent,
  heroSrcset,
  variantWidth,
  type PanelContent,
} from "./detailPanel";
import type { Country } from "./manifest";

const WEB_ROOT = new URL("../../", import.meta.url).pathname;
const GLOBE = readFileSync(`${WEB_ROOT}src/components/Globe.astro`, "utf8");

/** A rendered landscape country, with every field the builder reads populated. */
function country(overrides: Partial<Country> = {}): Country {
  return {
    slug: "chile",
    name: "Chile",
    continent: "South America",
    bbox: [-75.6, -55.9, -66.4, -17.5],
    aspect: 0.5,
    sizes: [640, 1920, 3840],
    native: 3840,
    rendered: true,
    hasBorder: true,
    borderSizes: [640, 1920],
    hasSpotlight: false,
    spotlightSizes: [],
    ...overrides,
  };
}

describe("srcset descriptors are widths, not long edges", () => {
  it("leaves a landscape variant at its key", () => {
    expect(variantWidth(1920, 1.5)).toBe(1920);
  });

  it("narrows a portrait variant to its real width", () => {
    // The trap this exists for: a portrait hero's key names its HEIGHT, so a descriptor taken from
    // the key alone overstates the width and the browser settles for a rung too small.
    expect(variantWidth(1920, 0.5)).toBe(960);
    expect(variantWidth(3840, 0.75)).toBe(2880);
  });

  it("names the webp variants for a hero and the png ones for a border", () => {
    const hero = heroSrcset("chile", [640, 1920], 0.5);
    expect(hero).toContain("chile-640.webp 320w");
    expect(hero).toContain("chile-1920.webp 960w");
    expect(hero).not.toContain("-border-");

    const border = heroSrcset("chile", [640], 0.5, true);
    expect(border).toContain("chile-border-640.png 320w");
    expect(border).not.toContain(".webp");
  });
});

describe("a country becomes card content", () => {
  it("puts the continent in the eyebrow and the render sentence in the note", () => {
    const content = countryPanelContent(country());
    expect(content.eyebrow).toBe("South America");
    expect(content.name).toBe("Chile");
    expect(content.note).toBe(COUNTRY_PANEL_NOTE);
    expect(content.link).toBe("/chile/");
  });

  it("empties the eyebrow rather than printing a missing continent", () => {
    expect(countryPanelContent(country({ continent: "" })).eyebrow).toBe("");
  });

  it("builds the figure from the smallest rung and describes it for a screen reader", () => {
    const { figure } = countryPanelContent(country());
    expect(figure).not.toBeNull();
    expect(figure!.aspect).toBe(0.5);
    expect(figure!.src).toContain("chile-640.webp");
    expect(figure!.srcset).toContain("chile-3840.webp 1920w");
    expect(figure!.alt).toBe("Ray-traced relief map of Chile");
  });

  it("drops the border when the country has none", () => {
    expect(countryPanelContent(country({ hasBorder: false })).figure!.border).toBeNull();
    expect(countryPanelContent(country({ borderSizes: [] })).figure!.border).toBeNull();
  });

  it("yields NO figure for an unrendered country rather than a broken image", () => {
    // The defect this pins: the old panel indexed `sizes[0]` unconditionally and asked for
    // `chile-undefined.webp`, which 404s behind a spinner. Unreachable on Earth today because only
    // in-scope countries are interactive — and the reason the figure has to be nullable at all is
    // the body that has no renders for ANY of its places.
    const content = countryPanelContent(country({ sizes: [], native: null, rendered: false }));
    expect(content.figure).toBeNull();
    expect(JSON.stringify(content)).not.toContain("undefined.webp");
  });
});

describe("the panel seam the module cannot check itself", () => {
  function panelMarkup(): string {
    const start = GLOBE.indexOf('<aside id="detail-panel"');
    expect(start, "the detail panel is gone from the markup").toBeGreaterThan(-1);
    return GLOBE.slice(start, GLOBE.indexOf("</aside>", start));
  }

  it("takes content rather than a country", () => {
    // The whole point of the refactor. `openPanel(country: Country)` is what a second body cannot
    // call, so the signature is the thing worth pinning rather than any of the fields.
    expect(GLOBE).toContain("function openPanel(content: PanelContent)");
    expect(GLOBE).toContain("openPanel(countryPanelContent(country))");
  });

  it("opens only for a body whose places have renders", () => {
    // THE GATE, PINNED AT ITS SITE. `globeSubsystems.test.ts` asserts that `subsystems.heroes`
    // appears SOMEWHERE in the globe, which is an existence scan — and it stopped being able to
    // catch a deleted gate here the moment a second reader arrived, because `chip-answers-taps`
    // reads the same flag and keeps the string present. Proved by mutation: removing this `if`
    // left that scan green.
    expect(GLOBE).toContain("if (subsystems.heroes) openPanel(countryPanelContent(country));");
  });

  it("leaves every slot in the markup empty, the note included", () => {
    // The note used to be a sentence in the markup claiming the card showed a ray-traced render.
    // A static string cannot be right on one body and wrong on another, so it must arrive written.
    expect(panelMarkup()).toContain('<p class="dp-note"></p>');
    expect(GLOBE).toContain('panel.querySelector(".dp-note")!.textContent = content.note;');
  });

  it("retires every spelling that named the panel after a hero", () => {
    // A half-finished rename is the failure mode here: the CSS block, the markup and the
    // querySelectors are three places, and a survivor in any one of them styles or selects nothing.
    for (const retired of ["hero-panel", "hero-close", "hp-"]) {
      expect(GLOBE, `${retired} survived the rename`).not.toContain(retired);
    }
  });

  it("selects only classes the markup actually carries", () => {
    // Catches the other half of a half-finished rename — a querySelector updated to a class the
    // markup never gained resolves to null and throws on the non-null assertion, but only when a
    // card is opened, which no test opens.
    const markup = panelMarkup();
    const selected = [...GLOBE.matchAll(/querySelector\("\.(dp-[a-z]+)"\)/g)].map((m) => m[1]);
    expect(selected.length).toBeGreaterThan(3);
    for (const cls of new Set(selected)) {
      expect(markup, `.${cls} is selected but not in the markup`).toContain(`class="${cls}"`);
    }
  });
});

describe("the content contract stays body-neutral", () => {
  it("names no country field", () => {
    // `PanelContent` exists so a second body can fill the card. A `slug`, a `continent` or a
    // `borderSizes` creeping back in would re-couple it to Earth's manifest without anything
    // failing, because Earth's builder would go on supplying them.
    const content: PanelContent = countryPanelContent(country());
    expect(Object.keys(content).toSorted()).toEqual(["eyebrow", "figure", "link", "name", "note"]);
  });
});
