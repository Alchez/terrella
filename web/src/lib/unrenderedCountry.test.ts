import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

/** What a country with no rendered image tells a visitor, on its gallery card and on its page. */
const SOURCES = {
  "gallery card": "../components/Gallery.astro",
  "country page": "../pages/[slug].astro",
};

const withoutComments = (source: string) =>
  source.replace(/\{\/\*[\s\S]*?\*\/\}/g, "").replace(/<!--[\s\S]*?-->/g, "");

describe.each(Object.entries(SOURCES))("the %s placeholder", (_where, path) => {
  const template = readFileSync(new URL(path, import.meta.url), "utf8").split(/^---$/m).at(-1) ?? "";
  const placeholder = withoutComments(template).match(/<div class="placeholder"[^>]*>([\s\S]*?)<\/div>/)?.[1];

  it("is found, so the check below reads something", () => {
    expect(placeholder, 'no `<div class="placeholder">` in the markup').toBeDefined();
  });

  it("says the map is not rendered yet, and promises no render in progress", () => {
    expect(placeholder?.match(/<small>([\s\S]*?)<\/small>/)?.[1]?.trim()).toBe("Not rendered yet");
  });
});
