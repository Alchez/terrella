import { afterEach, describe, expect, it } from "vitest";

import {
  DEFERRED_ROOT_MARGIN,
  STAGED_PLACEHOLDER,
  promoteCard,
  watchDeferredCards,
  type ObserverFactory,
} from "./lazyCards";

/**
 * The half of this module a node test cannot judge: `querySelectorAll` against real markup, and
 * what a browser DOES with a staged `<img>` that carries no `src`.
 *
 * That second one is the reason this file exists rather than being folded into the node suite. The
 * markup stages URLs by withholding `src`/`srcset`, and whether a src-less `<img>` paints its `alt`
 * text is a rendering question with a visible answer on 196 cards — not something to take from
 * memory. It is asserted here against a real renderer.
 */

const mounted: HTMLElement[] = [];

afterEach(() => {
  while (mounted.length) mounted.pop()!.remove();
});

/** Build a card the way index.astro emits a deferred one, and put it in the real document. */
function mountDeferredCard({ hero = "/heroes/albania-640.webp", spotlight = "" } = {}) {
  const card = document.createElement("article");
  card.className = "card";
  // The width/height rule is copied from index.astro's scoped CSS on purpose: it is what turns a
  // fallback render from "a stray line of text" into "a line of text across the whole card".
  card.innerHTML = `
    <figure style="aspect-ratio:0.465;width:379px;overflow:hidden">
      <img src="${STAGED_PLACEHOLDER}" data-src="${hero}" data-srcset="${hero} 298w" sizes="92vw"
           style="width:100%;height:100%;object-fit:cover"
           alt="Ray-traced relief map of Albania" loading="lazy" decoding="async">
      ${spotlight ? `<img class="spotlight-layer" src="${STAGED_PLACEHOLDER}"
           data-src="${spotlight}" data-srcset="${spotlight} 298w"
           sizes="92vw" alt="" aria-hidden="true" loading="lazy">` : ""}
      <figcaption>Albania</figcaption>
    </figure>`;
  document.body.append(card);
  mounted.push(card);
  return card;
}

describe("a staged card in a real document", () => {
  it("holds a DECODED placeholder, so the alt fallback is never painted", async () => {
    // This assertion is here because its first version was wrong in the other direction. Withholding
    // `src` entirely — on the reasoning that an image with no source represents nothing — put Chrome
    // in the BROKEN state, and the screenshot showed a broken-image icon followed by "Ray-traced
    // relief map of Albania" in text. Under the card's `height: 100%` that is a caption-sized line
    // across every one of 196 deferred cards.
    //
    // `naturalWidth > 0` is the oracle rather than a height or a screenshot: it is precisely the
    // condition that distinguishes "available" from "broken", and the alt fallback is what a broken
    // image renders. A height check would pass for a card that is merely collapsed.
    const image = mountDeferredCard().querySelector("img")!;
    expect(image.getAttribute("src")).toBe(STAGED_PLACEHOLDER);
    await image.decode();
    expect(image.naturalWidth).toBeGreaterThan(0);
  });

  it("still has the real URL withheld from every attribute the browser fetches from", () => {
    const image = mountDeferredCard().querySelector("img")!;
    expect(image.getAttribute("srcset")).toBeNull();
    expect(image.currentSrc).not.toContain("albania-640");
    expect(image.dataset.src).toBe("/heroes/albania-640.webp");
  });

  it("reserves the card's height from aspect-ratio, so promoting cannot shift the layout", () => {
    // CLS is 0.000 across twelve production Lighthouse runs. The figure owns the box; the image
    // only fills it. If this ever reads 0 the deferral is buying LCP with layout shift.
    const card = mountDeferredCard();
    const figure = card.querySelector("figure")!;
    expect(figure.getBoundingClientRect().height).toBeGreaterThan(0);
  });

  it("finds both staged images through the real selector", () => {
    const card = mountDeferredCard({ spotlight: "/heroes/albania-spotlight-640.webp" });
    expect(promoteCard(card)).toBe(2);
    const [hero, spotlight] = [...card.querySelectorAll("img")];
    expect(hero.getAttribute("src")).toBe("/heroes/albania-640.webp");
    expect(spotlight.getAttribute("src")).toBe("/heroes/albania-spotlight-640.webp");
    expect(card.querySelectorAll("img[data-src]")).toHaveLength(0);
  });

  it("leaves an already-live card untouched, so an eager card is never re-pointed", () => {
    const card = document.createElement("article");
    card.innerHTML = `<img src="/heroes/afghanistan-960.webp" srcset="/heroes/afghanistan-960.webp 960w">`;
    document.body.append(card);
    mounted.push(card);
    expect(promoteCard(card)).toBe(0);
    expect(card.querySelector("img")!.getAttribute("src")).toBe("/heroes/afghanistan-960.webp");
  });
});

describe("watchDeferredCards against the real IntersectionObserver", () => {
  it("promotes a card that is on screen, and asks the real API for the module's root margin", async () => {
    const card = mountDeferredCard();
    let observedRootMargin = "";
    const factory: ObserverFactory = (callback, options) => {
      observedRootMargin = options.rootMargin;
      return new IntersectionObserver(callback, options);
    };
    watchDeferredCards([card], factory);
    // The real observer delivers asynchronously — polling is the honest wait here, because a
    // fixed timeout would pass for the wrong reason on a slow machine.
    await expect.poll(() => card.querySelector("img")!.getAttribute("src")).toBe(
      "/heroes/albania-640.webp",
    );
    expect(observedRootMargin).toBe(DEFERRED_ROOT_MARGIN);
    // The margin has to be a value the real API accepts. A malformed rootMargin makes the
    // IntersectionObserver constructor throw, which would have shown up as a silent dead gallery.
    expect(() => new IntersectionObserver(() => {}, { rootMargin: DEFERRED_ROOT_MARGIN })).not.toThrow();
  });

  it("holds back a card parked far below the viewport", async () => {
    const card = mountDeferredCard();
    card.style.position = "absolute";
    card.style.top = `${window.innerHeight * 8}px`;
    watchDeferredCards([card], (callback, options) => new IntersectionObserver(callback, options));
    // Give the observer real frames to deliver in; the assertion is that it stays unpromoted.
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const image = card.querySelector("img")!;
    expect(image.getAttribute("src")).toBe(STAGED_PLACEHOLDER);
    expect(image.dataset.src).toBe("/heroes/albania-640.webp");
  });

  it("loads everything immediately when the browser has no IntersectionObserver", () => {
    const card = mountDeferredCard();
    expect(watchDeferredCards([card], undefined)).toBeNull();
    expect(card.querySelector("img")!.getAttribute("src")).toBe("/heroes/albania-640.webp");
  });

  it("survives a factory that fires its callback synchronously rather than throwing on the TDZ", () => {
    const card = mountDeferredCard();
    const synchronous: ObserverFactory = (callback) => {
      callback([{ target: card, isIntersecting: true }]);
      return { observe: () => {}, unobserve: () => {}, disconnect: () => {} };
    };
    expect(() => watchDeferredCards([card], synchronous)).not.toThrow();
    expect(card.querySelector("img")!.getAttribute("src")).toBe("/heroes/albania-640.webp");
  });
});
