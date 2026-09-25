/**
 * Which countries get a page and a gallery card: every one but a place listed on the globe alone.
 *
 * A listed-only place that slipped into either would ship a page reading "Not rendered yet", a
 * promise nothing will keep, and nothing about the build would fail.
 */

import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import CREDITS from "../data/attributions.json";
import { hasOwnPage, imageSources } from "./countryPages";
import type { Country } from "./manifest";

function country(overrides: Partial<Country> = {}): Country {
  return {
    slug: "bermuda",
    name: "Bermuda",
    admin: "Bermuda",
    continent: "North America",
    searchTerms: [],
    bbox: [-64.9, 32.2, -64.6, 32.5],
    aspect: 1.5,
    sizes: [],
    native: null,
    rendered: false,
    listedOnly: false,
    download: null,
    heroSources: [],
    hasSpotlight: false,
    spotlightSizes: [],
    ...overrides,
  };
}

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

describe("the globe matches shapes by Natural Earth's name and shows the config's", () => {
  // A country renamed in the config keeps its ADMIN, which is what every map feature carries. A
  // join on the display name would drop a renamed country from hover, highlight and click with no
  // error, and a chip reading the feature's ADMIN would show the name the config replaced.
  const globe = read("../components/Globe.astro").replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");

  it("filters the country layers to manifest ADMINs", () => {
    expect(globe).toContain("const inScope = manifest.countries.map((c) => c.admin);");
  });

  it("resolves a clicked feature through its ADMIN", () => {
    expect(globe).toContain("const byAdmin = new Map(manifest.countries.map((c) => [c.admin, c]));");
    expect(globe).toMatch(/map\.on\("click", \(event\) => goToCountry\(countryAtPoint\(event\.point\)\)\);/);
  });

  it("paints the chip with the display name", () => {
    expect(globe).toContain("countryChipName.textContent = byAdmin.get(admin)?.name ?? admin;");
  });

  it("resolves a search pick through the display name the row shows", () => {
    expect(globe).toContain("searchPick = (name) => goToCountry(byName.get(name));");
  });
});

const named = (key: keyof typeof CREDITS.sources) => CREDITS.sources[key].name;

describe("the datasets a country page credits under its image", () => {
  const rendered = { rendered: true, heroSources: ["glo30", "naturalearth", "globathy"] };

  it("are what its hero was recorded as rendered from, then the Focus layer's, once each", () => {
    expect(CREDITS.heroes.earth.focus).toEqual(["naturalearth"]);
    expect(imageSources(country({ ...rendered, hasSpotlight: true })).map((source) => source.name))
      .toEqual([named("glo30"), named("naturalearth"), named("globathy")]);
  });

  it("add the Focus layer's only where the page draws one", () => {
    const sources = imageSources(country({ rendered: true, heroSources: ["glo30"], hasSpotlight: true }));
    expect(sources.map((source) => source.name)).toEqual([named("glo30"), named("naturalearth")]);
    expect(imageSources(country({ rendered: true, heroSources: ["glo30"] })).map((source) => source.name))
      .toEqual([named("glo30")]);
  });

  it("are none for a country with no image", () => {
    expect(imageSources(country({ hasSpotlight: true }))).toEqual([]);
  });

  it("refuse a source the registry does not know rather than print nothing for it", () => {
    expect(() => imageSources(country({ rendered: true, heroSources: ["glo31"] }))).toThrow("glo31");
  });

  it("are the page's whole credit line", () => {
    const page = read("../pages/[slug].astro").replace(/\{\/\*[\s\S]*?\*\/\}/g, "");
    expect(page).toContain("const credited = imageSources(country);");
    expect(page).toMatch(/credited\.length > 0 && \(\s*<p class="meta">/);
  });
});

describe("a country's own page", () => {
  it("exists for a hero not yet rendered, and not for a place listed on the globe alone", () => {
    expect(hasOwnPage(country())).toBe(true);
    expect(hasOwnPage(country({ listedOnly: true }))).toBe(false);
  });

  it("is built only for those countries", () => {
    expect(read("../pages/[slug].astro")).toContain("data.countries.filter(hasOwnPage)");
  });

  it("is the gallery's whole population, so the grid, the index and the count agree", () => {
    const gallery = read("../components/Gallery.astro");
    expect(gallery).toContain("const pages = data.countries.filter(hasOwnPage);");
    const frontmatter = gallery.split(/^---$/m)[1] ?? "";
    expect(frontmatter, "a gallery list still reads the whole manifest").not.toMatch(
      /\[\.\.\.data\.countries\]/,
    );
    expect(gallery).not.toMatch(/\{data\.(rendered|count)\}/);
  });
});
