import { describe, expect, it } from "vitest";

import gallerySource from "../components/Gallery.astro?raw";
import {
  EAGER_CARD_COUNT,
  STAGED_PLACEHOLDER,
  promoteImage,
  promoteImages,
  type DeferredImage,
} from "./lazyCards";

/**
 * A stand-in for one `<img>`. It satisfies `DeferredImage` structurally, which is the point of that
 * interface existing — no `as unknown as HTMLImageElement` anywhere in this file.
 */
function stagedImage(staged: { src?: string; srcset?: string }) {
  const image = {
    dataset: { ...staged } as { src?: string; srcset?: string },
    src: "",
    srcset: "",
    removed: [] as string[],
    removeAttribute(name: string) {
      this.removed.push(name);
      if (name === "data-src") delete this.dataset.src;
      if (name === "data-srcset") delete this.dataset.srcset;
    },
  };
  return image satisfies DeferredImage;
}

describe("promoteImage", () => {
  it("moves both staged URLs onto the attributes the browser fetches from", () => {
    const image = stagedImage({ src: "/heroes/albania-640.webp", srcset: "/heroes/albania-640.webp 298w" });
    expect(promoteImage(image)).toBe(true);
    expect(image.src).toBe("/heroes/albania-640.webp");
    expect(image.srcset).toBe("/heroes/albania-640.webp 298w");
  });

  it("clears the staged attributes so the DOM stops carrying two copies of every URL", () => {
    const image = stagedImage({ src: "/heroes/albania-640.webp", srcset: "x 1w" });
    promoteImage(image);
    expect(image.removed).toEqual(["data-srcset", "data-src"]);
    expect(image.dataset).toEqual({});
  });

  it("reports nothing to do for an image that was never staged", () => {
    const image = stagedImage({});
    expect(promoteImage(image)).toBe(false);
    expect(image.src).toBe("");
  });

  it("is idempotent, so a second observer callback cannot re-fetch", () => {
    const image = stagedImage({ src: "a", srcset: "a 1w" });
    expect(promoteImage(image)).toBe(true);
    expect(promoteImage(image)).toBe(false);
  });

  it("assigns srcset BEFORE src, or the browser starts fetching the fallback rung and abandons it", () => {
    const order: string[] = [];
    const image = {
      dataset: { src: "fallback.webp", srcset: "wide.webp 892w" } as { src?: string; srcset?: string },
      set src(_value: string) { order.push("src"); },
      get src() { return ""; },
      set srcset(_value: string) { order.push("srcset"); },
      get srcset() { return ""; },
      removeAttribute() {},
    } satisfies DeferredImage;
    promoteImage(image);
    expect(order).toEqual(["srcset", "src"]);
  });
});

describe("promoteImages", () => {
  it("promotes BOTH images of a card, because a rendered card stacks a spotlight on its hero", () => {
    const hero = stagedImage({ src: "hero.webp" });
    const spotlight = stagedImage({ src: "spotlight.webp" });
    expect(promoteImages([hero, spotlight])).toBe(2);
    expect([hero.src, spotlight.src]).toEqual(["hero.webp", "spotlight.webp"]);
  });

  it("counts only what it actually moved", () => {
    expect(promoteImages([stagedImage({ src: "a" }), stagedImage({})])).toBe(1);
  });

  it("is a no-op on an empty card rather than throwing", () => {
    expect(promoteImages([])).toBe(0);
  });
});

/**
 * The gallery's own markup, read as source. These are the parts of the design that live in
 * `index.astro` rather than in this module, and each one fails silently if it is tidied away:
 * a page that still renders, still passes every other test, and quietly costs somebody something.
 */
describe("the gallery markup this module is wired into", () => {
  it("stages the deferred images behind a decodable placeholder, never a bare src", () => {
    // Withholding `src` puts Chrome in the BROKEN state and paints a broken-image icon plus the alt
    // text across the card — proven against a real renderer in lazyCards.browser.test.ts. The
    // placeholder is what keeps the element "available", so the page must actually emit it.
    expect(gallerySource).toContain("STAGED_PLACEHOLDER");
    expect(gallerySource).toMatch(/data-src=\{index < EAGER_CARD_COUNT \? undefined :/);
  });

  it("hides the staged image when script never runs, or the no-JS twin overflows the figure", () => {
    // Without this rule a no-JS visitor gets the placeholder <img> AND the <noscript> twin in the
    // same `overflow: hidden` figure, so the real image is pushed out of the box and the card looks
    // empty — the exact failure the twin exists to prevent.
    expect(gallerySource).toMatch(/:global\(html\.no-js\)\s*\.card figure img\[data-src\]/);
  });

  it("gives every deferred card a no-JS twin, because `/` must render without script", () => {
    // `/` is the pessimistic Tier-1 default that has to work for no-JS visitors, incapable devices
    // and crawlers — a settled decision, and the reason deferral may not simply drop the imagery.
    expect(gallerySource).toContain("<noscript>");
    expect(gallerySource).toMatch(/index >= EAGER_CARD_COUNT && \(/);
  });

  it("derives the watched set from the staged attribute rather than repeating the card index", () => {
    // An index repeated in the script and disagreeing with EAGER_CARD_COUNT in the markup would
    // leave cards unwatched: they would never promote, and the page would look fine until scrolled.
    expect(gallerySource).toContain('querySelectorAll<HTMLImageElement>("img[data-src]")');
    expect(gallerySource).not.toMatch(/querySelectorAll\([^)]*:has\(/);
  });

  it("keeps the placeholder out of the srcset, so it can never be a selectable rung", () => {
    const placeholderInSrcset = new RegExp(`srcset=\\{[^}]*${STAGED_PLACEHOLDER.slice(0, 24)}`);
    expect(gallerySource).not.toMatch(placeholderInSrcset);
  });
});

describe("the constants the markup depends on", () => {
  it("keeps enough cards eager for the LCP image to skip the observer entirely", () => {
    // One 92vw column shows about one and a half cards on a 412x823 phone, and the measured LCP
    // element is the SECOND card. One would put it behind script; this is why it is not one.
    expect(EAGER_CARD_COUNT).toBeGreaterThanOrEqual(2);
  });

  it("keeps the eager count small enough to be worth doing at all", () => {
    // A cold mobile load fetched seven cards for 1,130 KiB. An eager count that reaches the
    // below-fold cards would re-create exactly the contention this module removes.
    expect(EAGER_CARD_COUNT).toBeLessThan(4);
  });
});
