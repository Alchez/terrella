/**
 * Which countries get a page and a gallery card: every one but a place listed on the globe alone.
 *
 * A listed-only place that slipped into either would ship a page reading "This hero is still
 * rendering", a promise nothing will keep, and nothing about the build would fail.
 */

import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { hasOwnPage } from "./countryPages";
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
