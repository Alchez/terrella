import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { createFeatureSearch, foldForSearch, queryTerms } from "./featureSearch";
import { featureIndex, type NamedFeature } from "./featureIndex";

const SOURCE = readFileSync(new URL("./featureSearch.ts", import.meta.url).pathname, "utf8");

/** A catalogue row with only the fields a search reads spelled out. */
function feature(fields: Partial<NamedFeature> & { name: string }): NamedFeature {
  return {
    cleanName: fields.name,
    type: "Crater, craters",
    origin: "",
    gazetteer: "https://planetarynames.wr.usgs.gov/Feature/1",
    diameterKm: null,
    longitude: 0,
    latitude: 0,
    ...fields,
  };
}

/** The shipped catalogue, which is what a visitor actually types at. */
const REAL = createFeatureSearch(featureIndex);
const names = (results: { matches: NamedFeature[] }) => results.matches.map((match) => match.name);

/** What a visitor types is the name without its punctuation — NOT without its spaces, which is a
 *  different string and one nobody types. `E. Mareotis Tholus` is "e mareotis tholus". */
const asTyped = (name: string) => foldForSearch(name).replace(/[^a-z0-9 ]+/g, "");

/** The shipped diameter for a name, so a size claim reads off the data rather than a literal. */
const sizeOf = (name: string) => featureIndex.find((row) => row.name === name)!.diameterKm!;

describe("the fold sees what a keyboard can type", () => {
  it("drops case and diacritics", () => {
    expect(foldForSearch("Belén")).toBe("belen");
    expect(foldForSearch("Baetis Labēs")).toBe("baetis labes");
  });

  it("folds the letter NFD cannot decompose, and the naive rule is shown to miss it", () => {
    // THE CONTROL IS THE POINT. `ł` is its own letter rather than an `l` wearing a combining mark,
    // so decomposition has nothing to take off it and the obvious one-line fold leaves it standing
    // — a visitor typing the ASCII spelling then matches nothing while every other name still
    // works. Without this control the special case reads as superstition and gets deleted.
    const naive = "Puławy".normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
    expect(naive).not.toBe("pulawy");
    expect(foldForSearch("Puławy")).toBe("pulawy");
  });

  it("leaves nothing in the real catalogue a keyboard cannot reach", () => {
    // Asserted over the shipped index rather than a fixture, because what introduces another
    // undecomposable letter is an edition the IAU publishes, not an edit anyone makes here. The
    // survivors are the punctuation the tokeniser is built to handle.
    const unreachable = featureIndex.filter((row) => /[^a-z0-9 .'-]/.test(foldForSearch(row.name)));
    expect(unreachable.map((row) => row.name)).toEqual([]);
  });
});

describe("a punctuated name is reachable the way it is typed", () => {
  it("splits a query on punctuation as well as spaces", () => {
    expect(queryTerms("Koval'sky")).toEqual(["koval", "sky"]);
    expect(queryTerms("olympus mons")).toEqual(["olympus", "mons"]);
    expect(queryTerms("  ")).toEqual([]);
  });

  it("keeps both readings of a punctuated word, because different queries want different ones", () => {
    const search = createFeatureSearch([
      feature({ name: "Koval'sky" }),
      feature({ name: "Al-Qahira Vallis" }),
      feature({ name: "Airy-0" }),
    ]);
    // Joining reaches the name typed without its punctuation…
    expect(names(search.search("kovalsky", 5))).toEqual(["Koval'sky"]);
    expect(names(search.search("airy0", 5))).toEqual(["Airy-0"]);
    // …and splitting reaches the part after it, which joining alone never would.
    expect(names(search.search("qahira", 5))).toEqual(["Al-Qahira Vallis"]);
    expect(names(search.search("sky", 5))).toEqual(["Koval'sky"]);
  });

  it("finds every punctuated name in the real catalogue from its punctuation-free spelling", () => {
    const missed = featureIndex
      .filter((row) => /[^A-Za-z0-9 ]/.test(row.name))
      .filter((row) => !names(REAL.search(asTyped(row.name), 50)).includes(row.name));
    expect(missed.map((row) => row.name)).toEqual([]);
  });

  it("reaches names that NEITHER published spelling contains, which is why cleanName is not the rule", () => {
    // THE PREMISE THIS MODULE WAS BUILT ON, PINNED. `cleanName` is not the diacritic-free name — it
    // is the IAU's punctuation-flattened form, which turns an apostrophe into a SPACE. So the
    // spelling a visitor actually types sits in neither published field, and a matcher written
    // against the two of them would answer nothing while looking entirely reasonable.
    const beyondBothFields = featureIndex.filter((row) => {
      const typed = asTyped(row.name);
      return !foldForSearch(row.name).includes(typed) && !foldForSearch(row.cleanName).includes(typed);
    });
    expect(beyondBothFields.length).toBeGreaterThan(0);
    expect(beyondBothFields.map((row) => row.name)).toContain("Koval'sky");
    expect(names(REAL.search("kovalsky", 5))).toContain("Koval'sky");
  });
});

describe("the kind answers for the queries the names cannot", () => {
  it("is the only way to reach a crater, because no crater name says so", () => {
    const craters = featureIndex.filter((row) => row.type.startsWith("Crater"));
    expect(craters.length).toBeGreaterThan(0);
    expect(craters.filter((row) => foldForSearch(row.name).includes("crater"))).toEqual([]);
    const found = REAL.search("crater", 5);
    expect(found.total).toBe(craters.length);
    expect(found.matches.every((match) => match.type.startsWith("Crater"))).toBe(true);
  });

  it("takes the gazetteer's plural as well as its singular", () => {
    const search = createFeatureSearch([feature({ name: "Zed", type: "Mons, montes" })]);
    expect(names(search.search("mons", 5))).toEqual(["Zed"]);
    expect(names(search.search("montes", 5))).toEqual(["Zed"]);
  });

  it("ranks a name below nothing — a kind match never outranks a name match", () => {
    // THE QUERY IS ON THE SECOND WORD ON PURPOSE, and the first fixture written here did not do
    // that: with the query leading the name, deleting the tier column entirely changed nothing,
    // because the position column ordered the pair the same way and masked it. A guard has to put
    // the column it names in the only seat that decides.
    const search = createFeatureSearch([
      feature({ name: "Zed", type: "Mons, montes", diameterKm: 900 }),
      feature({ name: "Nili Mons", type: "Crater, craters", diameterKm: 1 }),
    ]);
    // Zed is 900× larger and its kind matches, but the query is IN the other name, so size never
    // gets consulted: the tier is decided first.
    expect(names(search.search("mons", 5))).toEqual(["Nili Mons", "Zed"]);
  });

  it("still needs every term, whichever half answers each one", () => {
    const search = createFeatureSearch([
      feature({ name: "Gale", type: "Crater, craters" }),
      feature({ name: "Gale", type: "Mons, montes" }),
    ]);
    expect(search.search("gale crater", 5).total).toBe(1);
    expect(search.search("gale planitia", 5).total).toBe(0);
  });
});

describe("relevance decides which matches survive the cap", () => {
  it("puts the whole name first, then the names that start with the query", () => {
    const search = createFeatureSearch([
      feature({ name: "Galena Mensa", diameterKm: 500 }),
      feature({ name: "Gale", diameterKm: 1 }),
      feature({ name: "Nili Gale", diameterKm: 900 }),
    ]);
    // Both size and alphabet would order these differently; neither is consulted until the query's
    // position in the name is settled.
    expect(names(search.search("gale", 5))).toEqual(["Gale", "Galena Mensa", "Nili Gale"]);
  });

  it("breaks a tie on size, largest first, with the unsized last", () => {
    const search = createFeatureSearch([
      feature({ name: "Ab", diameterKm: 10 }),
      feature({ name: "Ac", diameterKm: null }),
      feature({ name: "Ad", diameterKm: 400 }),
    ]);
    expect(names(search.search("a", 5))).toEqual(["Ad", "Ab", "Ac"]);
  });

  it("orders the last tie by name, so a list never reshuffles under an identical query", () => {
    const search = createFeatureSearch([
      feature({ name: "Ares", diameterKm: 7 }),
      feature({ name: "Alpha", diameterKm: 7 }),
    ]);
    expect(names(search.search("a", 5))).toEqual(["Alpha", "Ares"]);
  });

  it("answers a whole name with that name, whatever else shares its first word", () => {
    expect(names(REAL.search("olympus mons", 5))[0]).toBe("Olympus Mons");
  });

  it("leads a PARTIAL name with the largest thing it could be, which is not always the famous one", () => {
    // THE ONE PLACE THE SIZE RULE IS VISIBLY ARGUABLE, recorded here rather than left to be
    // rediscovered. "oly" is Olympus Mons to a reader and Olympus Rupes to this ranking, because
    // the escarpment around the volcano is the larger feature and size is the only prominence the
    // index carries. Both are on the first page either way; only a jump-to-top-hit UI would feel
    // it. Asserted as a relationship rather than as two numbers, so an IAU revision moves the
    // expectation with the data instead of going red on a value nobody reads.
    const found = names(REAL.search("oly", 5));
    expect(found).toContain("Olympus Mons");
    expect(sizeOf("Olympus Rupes")).toBeGreaterThan(sizeOf("Olympus Mons"));
    expect(found.indexOf("Olympus Rupes")).toBeLessThan(found.indexOf("Olympus Mons"));
  });
});

describe("the cap states what it left out", () => {
  it("counts every match and returns only the page asked for", () => {
    const broad = REAL.search("a", 10);
    expect(broad.matches).toHaveLength(10);
    expect(broad.total).toBeGreaterThan(10);
    // The total is what lets a UI say "10 of N" instead of implying the list is the answer.
    expect(REAL.search("a", 10_000).matches).toHaveLength(broad.total);
  });

  it("never returns one feature twice", () => {
    const wide = REAL.search("a", 10_000).matches.map((match) => match.name);
    expect(new Set(wide).size).toBe(wide.length);
  });

  it("matches nothing on a query with no letters in it", () => {
    for (const empty of ["", "   ", "''-.", "\t"]) {
      expect(REAL.search(empty, 10)).toEqual({ matches: [], total: 0 });
    }
  });
});

describe("the catalogue stays out of Earth's download", () => {
  it("names the row type without fetching the rows", () => {
    // `Globe.astro` splits `featureIndex` onto its own chunk so Earth never downloads Martian place
    // names, and both bodies mount that one component. A VALUE import here would be reached
    // statically from it and would undo the split — silently, with every other gate green.
    expect(SOURCE).toContain('import type { NamedFeature } from "./featureIndex"');
    expect(SOURCE).not.toMatch(/^import\s+(?!type\b)[^;]*from "\.\/featureIndex"/m);
  });
});
