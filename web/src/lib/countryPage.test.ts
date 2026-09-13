import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import CREDITS from "../data/attributions.json";

/**
 * A country page offers its full-size image as a link. The zoom swaps that file in as a CSS
 * background, which a right-click cannot save, so without a link the page source is the only route.
 */
const page = readFileSync(new URL("../pages/[slug].astro", import.meta.url), "utf8");
const frontmatter = page.split(/^---$/m)[1] ?? "";
const template = page.split(/^---$/m).at(-1) ?? "";
// Comments removed, so a sentence describing the link cannot stand in for it.
const withoutComments = (source: string) => source.replace(/\{\/\*[\s\S]*?\*\/\}/g, "");
const markup = withoutComments(template);
const about = withoutComments(readFileSync(new URL("../pages/about.astro", import.meta.url), "utf8"));

/** The text inside the link whose `href` is the frontmatter constant `name`, as source text. */
const linkText = (name: string) =>
  markup.match(new RegExp(`<a\\b[^>]*\\bhref=\\{${name}\\}[^>]*>([\\s\\S]*?)</a>`))?.[1] ?? "";
/** The template literal a frontmatter constant is declared as. */
const declared = (name: string) =>
  frontmatter.match(new RegExp(`const ${name} = \`([^\`]+)\`;`))?.[1];

/** Every word of every dataset name the site credits, as the registry spells it. */
const datasetWords = new Set(
  Object.values(CREDITS.bodies)
    .flatMap((body) => body.sources)
    .flatMap((source) => source.name.split(/[^A-Za-z0-9-]+/))
    .filter((word) => word.length >= 3),
);

describe("a country page credits its image from the registry", () => {
  const caption = markup.match(/<p class="meta">([\s\S]*?)<\/p>/)?.[1];

  it("finds the caption, so the checks below read something", () => {
    expect(caption, 'no `<p class="meta">` in the markup').toBeDefined();
    expect(datasetWords.size, "no dataset names came out of attributions.json").toBeGreaterThan(20);
  });

  it("types no dataset name into it", () => {
    const typed = (caption ?? "").match(/[A-Za-z0-9-]+/g) ?? [];
    expect(
      typed.filter((word) => datasetWords.has(word)),
      "the caption types a dataset's name; the list comes from attributions.json's `heroes`",
    ).toEqual([]);
  });

  it("lists the hero's sources, and Natural Earth only where a Focus layer draws it", () => {
    expect(frontmatter).toContain("CREDITS.heroes.earth.sources");
    expect(frontmatter).toMatch(/country\.hasSpotlight\s*\?\s*CREDITS\.heroes\.earth\.focus/);
  });
});

describe("a country page offers its full-size image", () => {
  it("reads the page's markup, and not the prose around it", () => {
    expect(markup, "the zoom's own use of the full-size URL is gone from the markup").toContain(
      "data-native-hero={nativeHero}",
    );
  });

  it("links it, rather than only swapping it in behind the zoom", () => {
    expect(markup, "the country page never links its full-size image").toMatch(
      /<a\b[^>]*\bhref=\{nativeHero\}/,
    );
  });

  it("links the PNG copy beside it, for print", () => {
    expect(declared("nativeHero"), "`nativeHero` is no longer a template literal").toBeDefined();
    expect(declared("nativePng"), "the PNG is not the full-size WebP's name as a .png").toBe(
      declared("nativeHero")?.replace(/\.webp$/, ".png"),
    );
    expect(markup, "the country page never links the PNG copy").toMatch(
      /<a\b[^>]*\bhref=\{nativePng\}/,
    );
  });

  it("states each file's pixels and bytes as the manifest records them", () => {
    expect(linkText("nativeHero")).toMatch(
      /\{country\.download\.width\}\s*×\s*\{country\.download\.height\}\s*px/,
    );
    expect(linkText("nativeHero")).toContain("{humanSize(country.download.webpBytes)}");
    expect(linkText("nativePng")).toContain("{humanSize(country.download.pngBytes)}");
  });

  it("links its licence to the section of About that states the terms", () => {
    const section = markup.match(/<a\b[^>]*\bhref="\/about\/#([\w-]+)"/)?.[1];
    expect(section, "the licence links no section of About").toBeDefined();
    expect(about, `about.astro has no element with id="${section}"`).toMatch(
      new RegExp(`<\\w+[^>]*\\sid="${section}"`),
    );
  });
});
