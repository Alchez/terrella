import { afterEach, describe, expect, it } from "vitest";
import { page } from "vitest/browser";
import * as maplibregl from "maplibre-gl";
import globalCss from "../styles/global.css?raw";
import globeStyles from "../styles/globe.css?raw";
import maplibreCss from "maplibre-gl/dist/maplibre-gl.css?raw";
import { CREDITS } from "./mapCredit";
import { mountGlobe, type MountedGlobe } from "./testing/mountGlobe";

/**
 * The on-map credit draws its ⓘ once MapLibre's attribution control has handled it.
 *
 * MapLibre sanitises every source's `attribution` before inserting it, and what survives is its
 * call: an element it drops leaves an empty link and raises nothing. So the oracle is the pixels of
 * the link as the page's own stylesheets render it, which holds whichever way the glyph is drawn.
 */

/** Stands in for the chrome row's `--chrome-ink`, pinned so the rendered size has one right answer. */
const CHROME_INK_PX = 20;

/** Share of the ink box the ⓘ covers: a radius-6 disc in a 12-unit box, less the dot (radius 1)
 *  and the stem (2 by 3 with round ends), which is (36π − 2π − 6) / 144. */
const GLYPH_COVERAGE = (34 * Math.PI - 6) / 144;

let mounted: MountedGlobe | undefined;
const installed: HTMLElement[] = [];

afterEach(() => {
  mounted?.dispose();
  mounted = undefined;
  for (const element of installed.splice(0)) element.remove();
});

function inject(css: string): void {
  const element = document.createElement("style");
  element.textContent = css;
  document.head.appendChild(element);
  installed.push(element);
}

/** Mount the credit the way the page does: a real attribution control reading a source's
 *  `attribution`, moved into the chrome row with the class that styles it there. */
async function mountCredit(): Promise<HTMLAnchorElement> {
  expect(globeStyles, "globe.css must carry the credit's rules").toContain(".chrome-credit");
  inject(globalCss);
  inject(globeStyles);
  inject(maplibreCss);

  mounted = await mountGlobe();
  const { map } = mounted;
  map.addControl(new maplibregl.AttributionControl({ compact: false }), "bottom-left");
  map.addSource("credited", {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
    attribution: CREDITS,
  });
  map.addLayer({ id: "credited", type: "fill", source: "credited" });

  const chromeRow = document.createElement("div");
  chromeRow.style.setProperty("--chrome-ink", `${CHROME_INK_PX}px`);
  chromeRow.style.position = "fixed";
  chromeRow.style.top = "0";
  chromeRow.style.left = "0";
  document.body.appendChild(chromeRow);
  installed.push(chromeRow);
  const credit = mounted.container.querySelector<HTMLElement>(".maplibregl-ctrl-attrib");
  if (!credit) throw new Error("the attribution control did not mount");
  credit.classList.add("chrome-credit");
  chromeRow.append(credit);

  await expect.poll(() => credit.querySelector("a"), { timeout: 5000 }).not.toBeNull();
  return credit.querySelector("a") as HTMLAnchorElement;
}

function rgb(color: string): [number, number, number] {
  const channels = color.match(/\d+(\.\d+)?/g);
  if (!channels || channels.length < 3) throw new Error(`unparsed colour ${color}`);
  return [Number(channels[0]), Number(channels[1]), Number(channels[2])];
}

/** WCAG relative luminance of an sRGB colour. */
function luminance(color: readonly number[]): number {
  const [red, green, blue] = color.map((channel) => {
    const unit = channel / 255;
    return unit <= 0.04045 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

interface Ink {
  /** Painted ink as a share of the link's own box. */
  coverage: number;
  /** WCAG contrast ratio between the ink and the pill behind it. */
  contrast: number;
  /** Ink at a point given as fractions of the link's box, 0 for none and 1 for full. */
  at: (across: number, down: number) => number;
}

/** Read the link's ink from a screenshot of the pill around it. Each pixel is placed between the
 *  pill's colour, sampled in its padding, and the link's own text colour, so an antialiased edge
 *  counts by its share. */
async function readInk(link: HTMLAnchorElement): Promise<Ink> {
  const box = link.getBoundingClientRect();
  expect(box.width * box.height, "an empty link has no pixels to read").toBeGreaterThan(0);
  const pill = link.closest<HTMLElement>(".chrome-credit");
  if (!pill) throw new Error("the link is not inside the credit pill");
  const pillBox = pill.getBoundingClientRect();
  const base64 = await page.screenshot({ element: pill, save: false });
  const blob = await (await fetch(`data:image/png;base64,${base64}`)).blob();
  const bitmap = await createImageBitmap(blob);
  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("no 2d context for reading the screenshot");
  context.drawImage(bitmap, 0, 0);
  const scale = bitmap.width / pillBox.width;
  const pixelAt = (x: number, y: number) =>
    context.getImageData(Math.floor(x * scale), Math.floor(y * scale), 1, 1).data;

  const paddingMiddle = (box.left - pillBox.left) / 2;
  const background = Array.from(pixelAt(paddingMiddle, pillBox.height / 2).slice(0, 3));
  const ink = rgb(getComputedStyle(link).color);
  const span = ink.map((channel, index) => channel - background[index]);
  const spanSquared = span.reduce((sum, channel) => sum + channel * channel, 0);
  const inkOf = (pixel: ArrayLike<number>, offset = 0) => {
    let projection = 0;
    for (let index = 0; index < 3; index++) {
      projection += (pixel[offset + index] - background[index]) * span[index];
    }
    return Math.min(1, Math.max(0, projection / spanSquared));
  };

  // The link's box plus a pixel each side, since an edge on a fractional position spills into it.
  const left = Math.floor((box.left - pillBox.left) * scale) - 1;
  const top = Math.floor((box.top - pillBox.top) * scale) - 1;
  const width = Math.ceil(box.width * scale) + 2;
  const height = Math.ceil(box.height * scale) + 2;
  const pixels = context.getImageData(left, top, width, height).data;
  let covered = 0;
  for (let offset = 0; offset < pixels.length; offset += 4) covered += inkOf(pixels, offset);

  const [lighter, darker] = [luminance(ink), luminance(background)].toSorted((a, b) => b - a);
  return {
    coverage: covered / (box.width * box.height * scale ** 2),
    contrast: (lighter + 0.05) / (darker + 0.05),
    at: (across, down) =>
      inkOf(
        pixelAt(
          box.left - pillBox.left + across * box.width,
          box.top - pillBox.top + down * box.height,
        ),
      ),
  };
}

describe("the on-map credit", () => {
  it("keeps its link to the credits page and its name", async () => {
    const link = await mountCredit();
    expect(new URL(link.href).pathname).toBe("/about/");
    expect(link.getAttribute("aria-label")).toBe("Data sources");
  });

  it("renders its icon at the chrome row's ink size", async () => {
    const link = await mountCredit();
    const box = link.getBoundingClientRect();
    expect(box.width).toBeCloseTo(CHROME_INK_PX, 0);
    expect(box.height).toBeCloseTo(CHROME_INK_PX, 0);
  });

  it("paints the ⓘ's ink, neither an empty box nor a solid one", async () => {
    const link = await mountCredit();
    const { coverage, contrast } = await readInk(link);
    expect(contrast, "WCAG's 3:1 for a graphic that carries meaning").toBeGreaterThanOrEqual(3);
    expect(coverage).toBeGreaterThan(GLYPH_COVERAGE - 0.1);
    expect(coverage).toBeLessThan(GLYPH_COVERAGE + 0.1);
  });

  // Points in the 12-unit glyph box, as fractions of it: the dot's centre (6, 3), the stem's
  // centre (6, 7.5), and the ring either side of the stem (2.5, 6) and (9.5, 6).
  it("cuts the i out of the disc", async () => {
    const { at } = await readInk(await mountCredit());
    expect(at(0.5, 0.25), "the i's dot").toBeLessThan(0.1);
    expect(at(0.5, 0.625), "the i's stem").toBeLessThan(0.1);
    expect(at(0.208, 0.5), "the ring left of the stem").toBeGreaterThan(0.9);
    expect(at(0.792, 0.5), "the ring right of the stem").toBeGreaterThan(0.9);
  });
});
