import { afterEach, describe, expect, it } from "vitest";
import { page } from "vitest/browser";
import "../styles/global.css";
import aboutPage from "../pages/about.astro?raw";

/**
 * About's own stylesheet, applied unscoped. Scoping adds one attribute to every selector in it
 * alike, so it moves no contest between the rules measured here.
 */
const ABOUT_STYLE = aboutPage.match(/<style>([\s\S]*?)<\/style>/)?.[1] ?? "";

const mounted: Element[] = [];
afterEach(() => {
  for (const element of mounted.splice(0)) element.remove();
});

function siteWideGrid(notes: number): HTMLElement {
  const style = document.createElement("style");
  style.textContent = ABOUT_STYLE;
  const main = document.createElement("main");
  main.className = "about";
  main.innerHTML = `<div class="shared"><div class="note-grid">${Array.from(
    { length: notes },
    (_, index) => `<section class="note-block"><h2>Note ${index}</h2><div class="note"><p>Text.</p></div></section>`,
  ).join("")}</div></div>`;
  document.head.append(style);
  document.body.append(main);
  mounted.push(style, main);
  return main.querySelector<HTMLElement>(".note-grid")!;
}

const columns = (grid: HTMLElement) => getComputedStyle(grid).gridTemplateColumns.split(" ").length;

async function columnsAt(width: number): Promise<number> {
  await page.viewport(width, 900);
  const count = columns(siteWideGrid(4));
  mounted.splice(0).forEach((element) => element.remove());
  return count;
}

describe("About's site-wide notes", () => {
  it("is measuring About's stylesheet, not an empty one", () => {
    expect(ABOUT_STYLE).toContain(".note-grid");
  });

  it("lay out at most two across, so four make two rows rather than three and a lone fourth", async () => {
    expect(await columnsAt(412), "columns on a phone").toBe(1);
    expect(await columnsAt(820), "columns on a tablet").toBe(2);
    expect(await columnsAt(1400), "columns on a desktop").toBe(2);
    expect(await columnsAt(2560), "columns on a wide screen").toBe(2);
  });
});
