/**
 * Deferred hero loading for the gallery grid.
 *
 * `loading="lazy"` already suppresses almost everything here — the gallery ships 406 `<img>`
 * elements and a cold mobile load fetches seven. The defect is only the THRESHOLD: Chrome widens
 * its fetch-ahead distance when it detects a slow connection, which is backwards for this page.
 * Seven heroes totalling 1,130 KiB share one throttled link while roughly 1.5 cards are on screen,
 * and because the pipe is the constraint the five below-fold cards are not "loaded early", they are
 * taking bandwidth from the one image the visitor is actually waiting on. Measured: raising the LCP
 * image's priority moved Load Delay -730 ms and Load Time +715 ms, a net -18 ms, while removing the
 * five below-fold requests moved LCP 8,828 -> 5,750 ms.
 *
 * So this module takes the threshold decision away from the browser. The page stages the deferred
 * URLs in `data-src` / `data-srcset` and promotes them when a card actually comes near.
 *
 * THE TYPES HERE ARE STRUCTURAL ON PURPOSE. `DeferredImage` and `ObserverLike` describe only what
 * this module touches, so a real `HTMLImageElement` and a plain test double both satisfy them
 * without a cast. A previous round of this codebase reached for `as unknown as HTMLImageElement` to
 * get a fake past the compiler, which is a way of telling the type checker to stop checking; naming
 * the small surface instead keeps it checking.
 */

/**
 * How many cards keep real `src`/`srcset` in the server-rendered HTML.
 *
 * These exist so the LCP image is discoverable by the preload scanner with no JavaScript in its
 * path — deferring the top of the page would trade bytes for discovery latency on the one request
 * that decides LCP. Two is set for the NARROWEST viewport, where a single 92vw column shows about
 * one and a half cards. A server-rendered count cannot be viewport-aware, so wider screens rely on
 * the observer promoting their above-fold cards on its first callback, which costs a frame on an
 * unthrottled link.
 */
export const EAGER_CARD_COUNT = 2;

/**
 * How far outside the viewport a card is promoted, as a fraction of the root's height.
 *
 * Half a viewport, not a guess dressed up as a constant: it is the smallest margin that still hides
 * the promotion behind a normal scroll gesture. Widening it re-creates the problem this module
 * exists to solve, since every extra card is a request competing for the same pipe. If scrolling
 * ever feels starved, the fix is two-phase (tight until `load`, generous after) rather than one
 * loose constant that pays the cost during the LCP window.
 */
export const DEFERRED_ROOT_MARGIN = "50%";

/**
 * What a staged `<img>` carries in `src` until it is promoted: a 1×1 fully transparent GIF.
 *
 * NOT decoration, and not a guess. The first version of this simply withheld `src`, on the
 * reasoning that an `<img>` with no source represents nothing. A browser test against a real
 * renderer said otherwise: Chrome puts the element in the BROKEN state and paints a broken-image
 * icon followed by the alt text — which, under the gallery's `width/height: 100%` rule, would have
 * been a line of grey text over the figure background on 196 cards. A decodable source keeps the
 * element "available", so the alt fallback never renders, and `object-fit: cover` stretches one
 * transparent pixel to reveal the figure's own background underneath.
 *
 * A data URI rather than a shared placeholder file, because a file would be one more request inside
 * the LCP window — the exact contention this module exists to remove. It repeats identically on
 * every deferred image, which is the cheapest thing there is for gzip to encode.
 */
export const STAGED_PLACEHOLDER =
  "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

/** The `<img>` surface this module touches — satisfied by HTMLImageElement and by a test double. */
export interface DeferredImage {
  readonly dataset: { src?: string; srcset?: string };
  src: string;
  srcset: string;
  removeAttribute(name: string): void;
}

/** The IntersectionObserver surface this module touches. */
export interface ObserverLike {
  observe(target: Element): void;
  unobserve(target: Element): void;
  disconnect(): void;
}

/** The entry surface this module reads — a real IntersectionObserverEntry satisfies it. */
export interface IntersectionLike {
  readonly target: Element;
  readonly isIntersecting: boolean;
}

export type ObserverFactory = (
  callback: (entries: IntersectionLike[]) => void,
  options: { rootMargin: string },
) => ObserverLike;

/**
 * Move one image's staged URLs onto the attributes the browser actually fetches from.
 *
 * Returns whether anything moved, so callers can tell "promoted" from "already live" rather than
 * inferring it. `srcset` is assigned BEFORE `src`: with both present the browser selects from the
 * srcset, but an image that briefly has only `src` would start fetching the fallback rung and then
 * abandon it. The `data-` attributes are removed so a second pass is a no-op and so the DOM stops
 * carrying two copies of every URL.
 */
export function promoteImage(image: DeferredImage): boolean {
  const stagedSrcset = image.dataset.srcset;
  const stagedSrc = image.dataset.src;
  if (stagedSrcset === undefined && stagedSrc === undefined) return false;
  if (stagedSrcset !== undefined) {
    image.srcset = stagedSrcset;
    image.removeAttribute("data-srcset");
  }
  if (stagedSrc !== undefined) {
    image.src = stagedSrc;
    image.removeAttribute("data-src");
  }
  return true;
}

/**
 * Promote every staged image inside one card, returning how many moved.
 *
 * A rendered card holds up to two images — the hero and the subject-spotlight overlay stacked on
 * top of it — so this cannot assume one. The overlay is `display: none` until the visitor turns
 * Focus on, and a lazy image with no layout box is never fetched, which is why 203 overlays cost
 * zero bytes today. Promoting it here only stages the URL; the browser still declines to fetch it
 * while it is hidden.
 */
export function promoteImages(images: Iterable<DeferredImage>): number {
  let promoted = 0;
  for (const image of images) {
    if (promoteImage(image)) promoted += 1;
  }
  return promoted;
}

/**
 * The DOM adapter over `promoteImages` — the one line that needs a real element.
 *
 * The split is deliberate rather than decorative. `promoteImages` is judged in the node project
 * with plain objects and no casts, while this function is judged in the browser project against
 * real markup. Collapsing them would force a `querySelectorAll`-shaped fake past the compiler with
 * `as unknown as Element`, which is not a test of anything except the cast.
 */
export function promoteCard(card: ParentNode): number {
  return promoteImages(card.querySelectorAll<HTMLImageElement>("img[data-src], img[data-srcset]"));
}

/**
 * Watch deferred cards and promote each as it approaches the viewport.
 *
 * Returns null when the environment has no IntersectionObserver, having promoted everything first:
 * a browser too old for the API must not be a browser that shows an empty gallery. That is the same
 * direction the rest of the site degrades in — `/` is the pessimistic Tier-1 default that has to
 * render for no-JS visitors, incapable devices and crawlers, so every failure here resolves toward
 * "load the images" rather than "load nothing".
 */
export function watchDeferredCards(
  cards: Iterable<ParentNode & Element>,
  createObserver: ObserverFactory | undefined,
  rootMargin: string = DEFERRED_ROOT_MARGIN,
): ObserverLike | null {
  const pending = [...cards];
  if (!createObserver) {
    for (const card of pending) promoteCard(card);
    return null;
  }
  // `observer` is declared before the factory runs and read through `?.` inside the callback,
  // because a factory that invokes its callback SYNCHRONOUSLY would otherwise hit the temporal
  // dead zone on a `const` and throw where a real IntersectionObserver never would. A test double
  // is exactly the thing that fires synchronously, so the hazard is real rather than theoretical —
  // and in that case there is nothing to unobserve yet anyway.
  let observer: ObserverLike | undefined;
  observer = createObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      promoteCard(entry.target);
      observer?.unobserve(entry.target);
    }
  }, { rootMargin });
  for (const card of pending) observer.observe(card);
  return observer;
}
