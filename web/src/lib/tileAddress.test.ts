import { describe, expect, it } from "vitest";

import { BODIES } from "./bodies";
import {
  LAYERS,
  PUBLISHED,
  TILE_PATH_SEGMENTS,
  TOKEN_LENGTH,
  archiveFor,
  parseTileAddress,
  tilePathTemplate,
  type LayerId,
} from "./tileAddress";
import TOKENS from "./tileTokens.json";

const EARTH_RELIEF = tilePathTemplate("earth", "relief")
  .replace("{z}", "5")
  .replace("{x}", "17")
  .replace("{y}", "11");

describe("the grammar", () => {
  it("parses an address into its six parts", () => {
    const address = parseTileAddress(EARTH_RELIEF);
    expect(address).toEqual({
      body: "earth",
      layer: "relief",
      token: archiveFor("earth", "relief").token,
      z: 5,
      x: 17,
      y: 11,
    });
  });

  it("is fixed-arity — every tile path is TILE_PATH_SEGMENTS segments", () => {
    // The property the whole scheme rests on: additions change the vocabulary, never the shape,
    // so two archives can never share an address and exclusivity needs no argument.
    for (const body of Object.keys(PUBLISHED)) {
      for (const layer of Object.keys(LAYERS) as LayerId[]) {
        if (!PUBLISHED[body as keyof typeof PUBLISHED][layer]) continue;
        const template = tilePathTemplate(body as keyof typeof PUBLISHED, layer);
        expect(template.split("/")).toHaveLength(TILE_PATH_SEGMENTS);
      }
    }
  });

  it("accepts a leading slash, because the two servers strip their mounts differently", () => {
    expect(parseTileAddress(`/${EARTH_RELIEF}`)).not.toBeNull();
  });

  it("keeps MapLibre's placeholders as the last three segments", () => {
    const template = tilePathTemplate("earth", "terrain");
    expect(template.endsWith("/{z}/{x}/{y}.webp")).toBe(true);
  });
});

describe("what it refuses, all without touching storage", () => {
  // SPELLED OUT RATHER THAN LOOPED, because both are named by a case in scripts/sabotage.py and
  // that table's freshness gate greps this file for the guard it names. A test whose title is
  // assembled from a template exists at runtime and is invisible to a source scan — which is
  // exactly how a mutation case goes stale without anything noticing.
  it("refuses the wrong extension for the layer", () => {
    expect(parseTileAddress(EARTH_RELIEF.replace(".webp", ".mvt"))).toBeNull();
  });

  it("refuses a zoom past the cut", () => {
    expect(parseTileAddress(EARTH_RELIEF.replace("/5/17/11.", "/9/17/11."))).toBeNull();
  });

  const rejected: [string, string][] = [
    ["an unknown body", EARTH_RELIEF.replace("earth", "venus")],
    ["an unknown layer", EARTH_RELIEF.replace("relief", "bathymetry")],
    ["a token that is too short", EARTH_RELIEF.replace(/\/[0-9a-f]{8}\//, "/4d04db5/")],
    ["a token that is not lowercase hex", EARTH_RELIEF.replace(/\/[0-9a-f]{8}\//, "/4D04DB58/")],
    ["an address outside the 2^z grid", EARTH_RELIEF.replace("/5/17/11.", "/5/32/11.")],
    ["a negative-looking address", EARTH_RELIEF.replace("/5/17/11.", "/5/-1/11.")],
    ["the whole path missing its token", EARTH_RELIEF.replace(/\/[0-9a-f]{8}\//, "/")],
  ];

  for (const [what, pathname] of rejected) {
    it(`refuses ${what}`, () => {
      expect(parseTileAddress(pathname)).toBeNull();
    });
  }

  // The shapes production serves TODAY. They must not resolve under the new grammar, or a client
  // that failed to update would look like it was working while addressing an unversioned URL.
  const legacy = ["5/17/11.webp", "terrain/5/17/11.webp", "countries/1/0/0.mvt"];
  for (const pathname of legacy) {
    it(`refuses the legacy shape ${pathname}`, () => {
      expect(parseTileAddress(pathname)).toBeNull();
    });
  }
});

describe("the registry", () => {
  it("has no word that is both a body and a layer", () => {
    // Position already disambiguates. This is so no reader ever has to count segments to know
    // which noun they are looking at.
    const bodies = new Set(Object.keys(BODIES));
    const shared = Object.keys(LAYERS).filter((layer) => bodies.has(layer));
    expect(shared).toEqual([]);
  });

  it("publishes a cut for every body the site can draw", () => {
    expect(Object.keys(PUBLISHED).sort()).toEqual(Object.keys(BODIES).sort());
  });

  it("never puts two raster pyramids in one archive", () => {
    // A PMTiles archive holds one tile per address, so two raster products in one object is not a
    // tight packing — it is an address collision. Vector layers are the exception and travel
    // together inside one MVT tile, which is why `multiLayer` is a layer fact.
    for (const layers of Object.values(PUBLISHED)) {
      const rasterKeys = (Object.keys(LAYERS) as LayerId[])
        .filter((layer) => !LAYERS[layer].multiLayer)
        .map((layer) => layers[layer]?.objectKey)
        .filter((key): key is string => key !== undefined);
      expect(new Set(rasterKeys).size).toBe(rasterKeys.length);
    }
  });

  it("refuses to hand back a cut a body does not publish", () => {
    expect(() => archiveFor("mars" as keyof typeof PUBLISHED, "relief")).toThrow(/publishes no/);
  });
});

describe("the committed tokens", () => {
  const committed = TOKENS as Record<string, Record<string, string>>;

  it("lists exactly the archives the registry publishes", () => {
    const published = Object.entries(PUBLISHED).flatMap(([body, layers]) =>
      (Object.keys(LAYERS) as LayerId[]).filter((layer) => layers[layer]).map((l) => `${body}/${l}`),
    );
    const listed = Object.entries(committed).flatMap(([body, layers]) =>
      Object.keys(layers).map((layer) => `${body}/${layer}`),
    );
    expect(listed.sort()).toEqual(published.sort());
  });

  it("holds a real hash for every one, never the placeholder", () => {
    // A forgotten `gen_tile_tokens.ts --write` would otherwise ship a token that names nothing,
    // and every tile would still serve — under an address that can never be busted.
    for (const [body, layers] of Object.entries(committed)) {
      for (const [layer, token] of Object.entries(layers)) {
        expect(token, `${body}/${layer}`).toMatch(new RegExp(`^[0-9a-f]{${TOKEN_LENGTH}}$`));
        expect(token, `${body}/${layer}`).not.toBe("0".repeat(TOKEN_LENGTH));
      }
    }
  });

  it("is what the registry actually advertises", () => {
    expect(archiveFor("earth", "relief").token).toBe(committed.earth.relief);
  });
});
