import { describe, expect, it } from "vitest";

import { archiveIndex, humanSize } from "./archiveIndex";
import { BODIES, type BodySlug } from "./bodies";
import { terrainDecodeExpression } from "./terrainSource";
import { ARCHIVED, PUBLISHED } from "./tileAddress";

/** The index for a bucket that cannot list itself.
 *
 *  WHAT GOES WRONG HERE IS SILENT AND LOOKS FINE. A page built from `PUBLISHED` alone renders
 *  completely, links every archive the site serves, and omits every superseded object in the
 *  bucket. Nobody reading it can tell, because the thing missing is what they came to discover.
 *
 *  ASSERTED AGAINST THE RETURNED ROWS, not against the page source. The first version of this
 *  scanned `archives.astro` for the word `ARCHIVED`, which the import line satisfies on its own:
 *  emptying the superseded list left it green, and mutation is what said so.
 */
describe("archiveIndex", () => {
  const worlds = archiveIndex();

  it("lists every body the site publishes", () => {
    expect(worlds.map((world) => world.slug).toSorted()).toEqual(Object.keys(PUBLISHED).toSorted());
  });

  it("carries every superseded cut, so a re-cut cannot drop a row from the index", () => {
    const listed = worlds.flatMap((world) => world.superseded.map((cut) => cut.key)).toSorted();
    expect(listed).toEqual(ARCHIVED.map((cut) => cut.key).toSorted());
    expect(listed.length).toBeGreaterThan(0);
  });

  it("carries every published archive with a size, a credit and a download", () => {
    const rows = worlds.flatMap((world) => world.current);
    const published = Object.values(PUBLISHED).flatMap((byLayer) =>
      Object.values(byLayer).filter((archive) => archive !== null),
    );
    expect(rows).toHaveLength(published.length);
    for (const row of rows) {
      expect(row.credit, row.key).toContain("CC BY-SA 4.0");
      expect(row.size, row.key).toMatch(/^\d+(\.\d+)? (GB|MB)$/);
      expect(row.href, row.key).toContain(row.key);
    }
  });

  it("names every dataset an archive owes a credit to, with a licence and somewhere to read it", () => {
    // The list is what the card SHOWS; the paragraph beside it is what the file carries. A blank
    // name renders as an empty row rather than as a missing one, so the card goes on looking
    // complete while crediting nobody.
    for (const row of worlds.flatMap((world) => world.current)) {
      expect(row.sources.length, `${row.key} credits nothing`).toBeGreaterThan(0);
      for (const source of row.sources) {
        expect(source.name.trim(), `${row.key} source name`).not.toBe("");
        expect(source.license.trim(), `${row.key} ${source.name} licence`).not.toBe("");
        expect(source.href, `${row.key} ${source.name} href`).toMatch(/^https:\/\//);
      }
    }
  });

  it("tells a downloader how to read elevation, and nothing else needs telling", () => {
    // The archive a stranger can silently misread is the one whose pixels are a NUMBER. Both names
    // they would search for, Mapbox's Terrain-RGB and plain Terrarium, apply cleanly to these bytes
    // and return a plausible figure, so there is nothing for them to notice.
    for (const row of worlds.flatMap((world) => world.current)) {
      if (row.layer !== "terrain") {
        expect(row.decode, `${row.key} needs no decode`).toBeNull();
        continue;
      }
      expect(row.decode, row.key).toBe(terrainDecodeExpression());
      expect(row.decode, `${row.key} carries a channel that holds no elevation`).not.toContain(
        "blue",
      );
    }
  });

  it("composes that decode from the shipped step rather than spelling one", () => {
    // The half a literal would pass. A hardcoded expression is right today and stays right through
    // a re-cut at another `--step`, which is exactly when it becomes wrong metres on a public page.
    expect(terrainDecodeExpression(16)).toContain("4096");
    expect(terrainDecodeExpression(16)).toContain("green * 16");
    // At one metre the encoding IS standard Terrarium, which is the one case with a blue term.
    expect(terrainDecodeExpression(1)).toBe("red * 256 + green + blue / 256 - 32768");
  });

  it("names no format that would decode an archive wrongly", () => {
    // "Terrain-RGB" is Mapbox's, and this pyramid is not it. The page said so on both bodies.
    for (const row of worlds.flatMap((world) => world.current)) {
      expect(row.role, `${row.key} role`).not.toMatch(/terrain-rgb/i);
    }
  });

  it("describes each archive in its own body's words, naming no other body", () => {
    // `vector` is a ROLE rather than a content: it is countries on one planet and named features on
    // another. The card described the layer instead of the file and said both, so Earth's vector
    // archive advertised Mars on it, under a heading that had already said Earth.
    for (const world of worlds) {
      const others = (Object.keys(BODIES) as BodySlug[]).filter((slug) => slug !== world.slug);
      const vector = world.current.find((row) => row.layer === "vector");
      expect(vector?.role, `${world.slug} vector`).toContain(BODIES[world.slug].catalogue.plural);
      for (const row of world.current) {
        for (const other of others) {
          const where = `${world.slug}/${row.layer} names ${other}`;
          expect(row.role.toLowerCase(), where).not.toContain(BODIES[other].label.toLowerCase());
          expect(row.role, where).not.toContain(BODIES[other].catalogue.plural);
        }
      }
    }
  });

  it("sends downloads to the archive host and tiles to the tile host", () => {
    // One object read against one worker invocation. Linking a multi-GB download at the tile host
    // would 404, and the shapes that parse would bill a worker for it.
    for (const row of worlds.flatMap((world) => world.current)) {
      expect(row.href, row.key).not.toContain("/tiles/");
      expect(row.tiles, row.key).toContain("{z}/{x}/{y}");
    }
  });

  it("reports sizes in the units a download manager shows", () => {
    expect(humanSize(2_353_330_123)).toBe("2.35 GB");
    expect(humanSize(10_239_263)).toBe("10.2 MB");
  });
});
