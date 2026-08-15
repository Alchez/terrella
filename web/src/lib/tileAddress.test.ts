import { describe, expect, it } from "vitest";

import { BODIES, type BodySlug } from "./bodies";
import {
  LAYERS,
  PUBLISHED,
  TILE_PATH_SEGMENTS,
  TOKEN_LENGTH,
  addressedLayerWord,
  archiveFor,
  describeArchiveHeaderMismatch,
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
    // The legacy PREFIX keeps its spelling; the layer it resolves to does not. A URL production
    // already served is a fact, not a name we get to revise.
    ["countries/1/0/0.mvt", "vector"],
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

describe("the renamed layer word, which is temporary and separate from the legacy grammar", () => {
  // These carry a TOKEN — they are current-shape URLs with a stale word, which is what the site
  // minted before `countries` became `vector`. They must keep working across the window between
  // the Worker deploy and the site deploy, and for every page a visitor already has open, whose
  // tile URLs are `immutable` for a year.
  const current = tilePathTemplate("earth", "vector")
    .replace("{z}", "3").replace("{x}", "4").replace("{y}", "3");
  const renamed = current.replace("earth/vector/", "earth/countries/");

  it("resolves the old word to exactly the tile the new word resolves to", () => {
    // Byte-for-byte the same address, so an aliased request cannot reach a different archive, a
    // different zoom range or a different token than the current spelling would.
    expect(resolveTileRequest(renamed)).toEqual(resolveTileRequest(current));
    expect(resolveTileRequest(renamed)).toMatchObject({ layer: "vector", token: expect.any(String) });
  });

  it("is a distinct path from the legacy one, so the two can be deleted separately", () => {
    // The legacy shape has no token; this one does. A single latch over both would go quiet as
    // soon as either stopped, and delete the other branch while clients still used it.
    expect(resolveTileRequest(renamed)?.token).not.toBeNull();
  });

  it("reports the word a path SPELLED, which is the only signal for when the alias can go", () => {
    expect(addressedLayerWord(renamed)).toBe("countries");
    expect(addressedLayerWord(current)).toBe("vector");
    // Null for anything that is not an addressed path, so a legacy URL cannot be mistaken for a
    // stale word and keep the alias alive forever.
    expect(addressedLayerWord("countries/1/0/0.mvt")).toBeNull();
  });

  it("does not invent a layer that never existed", () => {
    expect(resolveTileRequest(current.replace("earth/vector/", "earth/borders/"))).toBeNull();
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

  it("never puts two pyramids in one archive", () => {
    // A PMTiles archive holds one tile per address, so two of a body's pyramids in one object is
    // not a tight packing — it is an address collision.
    //
    // EVERY LAYER, where this once excluded the vector one. `PublishedArchives` gives a body one
    // archive slot per layer, so there is no layer for which sharing a key is legitimate and the
    // exclusion could never fire. What it was reaching for — MVT carrying several named layers per
    // tile — is real, but it lives on the PRODUCT axis, which this registry does not index and
    // `sourceLayers.ts` owns.
    for (const layers of Object.values(PUBLISHED)) {
      const keys = (Object.keys(LAYERS) as LayerId[])
        .map((layer) => layers[layer]?.objectKey)
        .filter((key): key is string => key !== undefined);
      expect(new Set(keys).size).toBe(keys.length);
    }
  });

  it("refuses to hand back a cut a body does not publish", () => {
    // CONSTRUCTED, BECAUSE NO REAL PAIR IS LEFT TO BORROW. This read `archiveFor("mars", "terrain")`
    // while that entry was null, and publishing Mars's DEM took the last unpublished pair in the
    // registry with it. The casts are not hypotheticals: `archiveFor` is defensive precisely because
    // its arguments arrive as URL segments and `data-body`, neither of which the type system has
    // ever seen — an unknown word IS the shape this guard exists for, on both axes.
    expect(() => archiveFor("mars", "heightfield" as LayerId)).toThrow(/publishes no/);
    expect(() => archiveFor("venus" as BodySlug, "relief")).toThrow(/publishes no/);
    // The control, so the throws above are about the lookup rather than `archiveFor` being broken
    // for everything. Skips nulls rather than forbidding them: a body is allowed to stop publishing
    // a layer, and this case should not be the thing that argues against it.
    for (const [body, layers] of Object.entries(PUBLISHED)) {
      for (const [layer, entry] of Object.entries(layers)) {
        if (entry === null) continue;
        expect(() => archiveFor(body as BodySlug, layer as LayerId), `${body}/${layer}`)
          .not.toThrow();
      }
    }
  });

  it("bounds Mars's terrain by MARS's ceiling, so a z8 request is refused", () => {
    // WHAT THIS CASE USED TO BE, AND WHY IT COULD NOT SURVIVE. It asserted that a `mars/terrain`
    // address parsed to null while Mars published no DEM — but it spelled the tile `.png`, and
    // terrain tiles are `.webp`, so the parser rejected it on EXTENSION several lines above the
    // publication check it named. It would have gone on passing with Mars's terrain published,
    // still asserting nothing it claimed to: a test can be green, load-bearing-looking, and about
    // a different branch than its comment says.
    //
    // The reachable form of the same worry is the ceiling. Earth is cut to z8 and Mars to z7, and
    // the failure never 404s in the obvious place — Earth terrain answered at a Mars address is a
    // complete, plausible, wrong planet.
    const token = archiveFor("mars", "terrain").token;
    expect(parseTileAddress(`mars/terrain/${token}/7/64/64.webp`)).not.toBeNull();
    expect(parseTileAddress(`mars/terrain/${token}/8/128/128.webp`)).toBeNull();
    expect(resolveTileRequest(`mars/terrain/${token}/8/128/128.webp`)).toBeNull();
    // The control: z8 is not refused everywhere, only above Mars's own ceiling.
    const earth = archiveFor("earth", "terrain").token;
    expect(parseTileAddress(`earth/terrain/${earth}/8/128/128.webp`)).not.toBeNull();
  });

  it("bounds a Mars relief address by MARS's ceiling, not Earth's", () => {
    // The reason the zoom range is a registry field rather than a module constant. Earth is cut to
    // z8 and Mars to z7; checked against Earth's constants a legitimate Mars pyramid answers a zoom
    // level it does not contain, and a range read would look for tiles that were never cut.
    const token = archiveFor("mars", "relief").token;
    expect(parseTileAddress(`mars/relief/${token}/7/64/64.webp`)).not.toBeNull();
    expect(parseTileAddress(`mars/relief/${token}/8/128/128.webp`)).toBeNull();
    expect(parseTileAddress(`earth/relief/${archiveFor("earth", "relief").token}/8/128/128.webp`))
      .not.toBeNull();
  });

  it("still lets Mars be a body, which is what a page and a work tree need", () => {
    // Publishing nothing is not the same as not existing. The slug has to resolve for the route,
    // the accent tokens and the dev server's work-tree prefix.
    expect(Object.keys(PUBLISHED)).toContain("mars");
  });
});

describe("describeArchiveHeaderMismatch", () => {
  // This one check replaced three `assert*ZoomRange` functions, one per layer module, each of
  // which compared an archive against ITS OWN module constants. That shape could not survive a
  // second body cut to a different ceiling, which makes a per-layer constant Earth's answer to a
  // per-planet question. These cases are the three it inherited, plus the one that could not be
  // written before — a correct archive for a body with a different ceiling.

  it("passes an archive that covers exactly what the registry advertises", () => {
    for (const [body, layers] of Object.entries(PUBLISHED)) {
      for (const [layer, archive] of Object.entries(layers)) {
        if (!archive) continue;
        const header = { minZoom: archive.minZoom, maxZoom: archive.maxZoom };
        expect(
          describeArchiveHeaderMismatch(body as keyof typeof PUBLISHED, layer as LayerId, header),
          `${body}/${layer}`,
        ).toBeNull();
      }
    }
  });

  it("accepts Mars at its own ceiling and refuses it at Earth's, which is the whole point", () => {
    expect(describeArchiveHeaderMismatch("mars", "relief", { minZoom: 0, maxZoom: 7 })).toBeNull();
    expect(describeArchiveHeaderMismatch("mars", "relief", { minZoom: 0, maxZoom: 8 }))
      .toMatch(/covers z0-z8/);
    // And the rung it just left, which is the direction a re-cut actually drifts.
    expect(describeArchiveHeaderMismatch("mars", "relief", { minZoom: 0, maxZoom: 6 }))
      .toMatch(/covers z0-z6/);
  });

  it("catches drift in BOTH directions, because neither shows up as an error", () => {
    // Shallower: tiles past the depth stop arriving and the globe keeps drawing what it has.
    expect(describeArchiveHeaderMismatch("earth", "relief", { minZoom: 0, maxZoom: 6 }))
      .toMatch(/PUBLISHED\.earth\.relief/);
    // Deeper: the extra levels are simply never requested.
    expect(describeArchiveHeaderMismatch("earth", "relief", { minZoom: 0, maxZoom: 10 }))
      .toMatch(/PUBLISHED\.earth\.relief/);
    // And a min that moved, which nothing else in the chain would notice.
    expect(describeArchiveHeaderMismatch("earth", "vector", { minZoom: 1, maxZoom: 8 }))
      .toMatch(/PUBLISHED\.earth\.vector/);
  });

  it("names the file to edit, so the message is actionable without reading this test", () => {
    const message = describeArchiveHeaderMismatch("earth", "terrain", { minZoom: 0, maxZoom: 6 });
    expect(message).toMatch(/src\/lib\/tileAddress\.ts/);
  });

  it("throws rather than passing for a layer the body does not publish", () => {
    // Inherited from `archiveFor`, and worth pinning here: silently returning null would let a
    // server open an archive for a cut that is not supposed to exist.
    // Constructed for the same reason as the registry case above: Mars's terrain was the live
    // example until Mars published it, and a borrowed negative instance ends without saying so.
    expect(() => describeArchiveHeaderMismatch("mars", "heightfield" as LayerId,
                                               { minZoom: 0, maxZoom: 8 }))
      .toThrow(/publishes no/);
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
    // ZERO IS A REAL ANSWER, AND MARS IS WHY THIS NO LONGER DEMANDS ONE. A PMTiles root directory
    // spills to leaf directories only when it outgrows what fits in the header's root slot; Mars's
    // z0-6 cut is 5,461 tiles whose whole index is 13 KB, so it has no leaves at all and its
    // directory is resident from the first prefetch. Requiring `> 0` here was Earth's scale written
    // as a rule, and it refused a correct archive.
    //
    // The placeholder this test was reaching for is caught next door, by the token check: a
    // forgotten `--write` leaves BOTH fields at their placeholder, and `00000000` is a shape no
    // real hash takes, where `0` is a shape a real leaf count does.
    for (const [body, layers] of Object.entries(committed)) {
      for (const [layer, facts] of Object.entries(layers)) {
        expect(facts.indexLeaves, `${body}/${layer}`).toBeGreaterThanOrEqual(0);
        expect(Number.isInteger(facts.indexLeaves), `${body}/${layer}`).toBe(true);
      }
    }
  });

  it("is what the registry actually advertises", () => {
    expect(archiveFor("earth", "relief").token).toBe(committed.earth.relief.token);
    expect(archiveFor("earth", "relief").indexLeaves).toBe(committed.earth.relief.indexLeaves);
  });
});
