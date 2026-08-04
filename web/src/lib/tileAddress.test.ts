import { describe, expect, it } from "vitest";

import { BODIES } from "./bodies";
import {
  LAYERS,
  PUBLISHED,
  TILE_PATH_SEGMENTS,
  TOKEN_LENGTH,
  archiveFor,
  parseTileAddress,
  resolveTileRequest,
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

describe("the legacy grammar, which both servers still accept", () => {
  const legacy: [string, LayerId][] = [
    ["5/17/11.webp", "relief"],
    ["terrain/5/17/11.webp", "terrain"],
    ["countries/1/0/0.mvt", "countries"],
  ];

  for (const [pathname, layer] of legacy) {
    it(`resolves ${pathname} to Earth's ${layer} pyramid, with no token`, () => {
      // A null token is the honest answer: the request named none. Filling in the current one
      // would erase the only signal that tells us when the legacy branch is safe to delete.
      expect(resolveTileRequest(pathname)).toMatchObject({ body: "earth", layer, token: null });
    });
  }

  it("still tolerates the version prefix production has always accepted", () => {
    // It exists so a re-cut could ship under a new base URL instead of a zone-wide purge. The dev
    // server used to 404 this exact shape while the Worker served it — one resolver, one answer.
    expect(resolveTileRequest("/v2/5/17/11.webp")).toMatchObject({ layer: "relief", token: null });
  });

  it("strips that prefix only at the front", () => {
    // Unanchored, `/5/v2/1/2.webp` becomes `/5/1/2.webp` — a perfectly valid tile served under an
    // address nobody ever minted.
    expect(resolveTileRequest("/5/v2/1/2.webp")).toBeNull();
  });

  it("cannot shadow an addressed path", () => {
    expect(resolveTileRequest(EARTH_RELIEF)).toMatchObject({ layer: "relief", token: expect.any(String) });
  });
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
    expect(Object.keys(PUBLISHED).toSorted()).toEqual(Object.keys(BODIES).toSorted());
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
    // No longer a hypothetical cast: Mars is a real body in the registry that publishes nothing.
    expect(() => archiveFor("mars", "relief")).toThrow(/publishes no/);
  });

  it("refuses a Mars tile address outright, rather than serving Earth's pyramid", () => {
    // The failure this prevents does not 404 and does not look broken: Earth relief served at a
    // Mars address is a complete, plausible, wrong planet. `null` in PUBLISHED is what makes the
    // parser reject it — before any storage is touched, so a probe costs no range read.
    const marsAddress = `mars/relief/${archiveFor("earth", "relief").token}/5/17/11.webp`;
    expect(parseTileAddress(marsAddress)).toBeNull();
    expect(resolveTileRequest(marsAddress)).toBeNull();
  });

  it("still lets Mars be a body, which is what a page and a work tree need", () => {
    // Publishing nothing is not the same as not existing. The slug has to resolve for the route,
    // the accent tokens and the dev server's work-tree prefix.
    expect(Object.keys(PUBLISHED)).toContain("mars");
  });
});

describe("the committed archive facts", () => {
  const committed = TOKENS as Record<string, Record<string, { token: string; indexLeaves: number }>>;

  it("lists exactly the archives the registry publishes", () => {
    const published = Object.entries(PUBLISHED).flatMap(([body, layers]) =>
      (Object.keys(LAYERS) as LayerId[]).filter((layer) => layers[layer]).map((l) => `${body}/${l}`),
    );
    const listed = Object.entries(committed).flatMap(([body, layers]) =>
      Object.keys(layers).map((layer) => `${body}/${layer}`),
    );
    expect(listed.toSorted()).toEqual(published.toSorted());
  });

  it("holds a real hash for every one, never the placeholder", () => {
    // A forgotten `gen_tile_tokens.ts --write` would otherwise ship a token that names nothing,
    // and every tile would still serve — under an address that can never be busted.
    for (const [body, layers] of Object.entries(committed)) {
      for (const [layer, facts] of Object.entries(layers)) {
        expect(facts.token, `${body}/${layer}`).toMatch(new RegExp(`^[0-9a-f]{${TOKEN_LENGTH}}$`));
        expect(facts.token, `${body}/${layer}`).not.toBe("0".repeat(TOKEN_LENGTH));
      }
    }
  });

  it("holds a real leaf count for every one, which the Worker's cache is sized from", () => {
    // Zero is the shape a placeholder takes here, and it is also a plausible-looking number — a
    // cache sized from zeros would be all headroom and would thrash on the first interleaved
    // request. Every PMTiles archive big enough to need leaves has at least one.
    for (const [body, layers] of Object.entries(committed)) {
      for (const [layer, facts] of Object.entries(layers)) {
        expect(facts.indexLeaves, `${body}/${layer}`).toBeGreaterThan(0);
        expect(Number.isInteger(facts.indexLeaves), `${body}/${layer}`).toBe(true);
      }
    }
  });

  it("is what the registry actually advertises", () => {
    expect(archiveFor("earth", "relief").token).toBe(committed.earth.relief.token);
    expect(archiveFor("earth", "relief").indexLeaves).toBe(committed.earth.relief.indexLeaves);
  });
});
