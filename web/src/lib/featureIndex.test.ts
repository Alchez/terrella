import { describe, it, expect } from "vitest";
import { featureIndex, featureNamed, type NamedFeature } from "./featureIndex";
import { candidateFrom } from "./featureTargeting";

/**
 * The committed index, asserted against no data but itself.
 *
 * EVERYTHING HERE RUNS ON A CLEAN CHECKOUT, which is the whole reason the file is tracked. Its
 * sibling `tests/test_feature_index.py` asks the one question that needs the acquired gazetteer —
 * whether these bytes are still what the producer emits — and SKIPS without it, which reads exactly
 * like a pass. So the properties that would actually reach a visitor if they broke are pinned here
 * instead: the fold, the sort, the duplicate name, and the rule deciding what has a size.
 */

const TOTAL = 1919;

describe("the catalogue is whole", () => {
  it("carries every IAU name from both gazetteer layers", () => {
    // 1,717 areal + 203 linear, less the one record the gazetteer enters twice. A short count is a
    // producer that dropped a layer, which nothing about the file's shape would otherwise reveal.
    expect(featureIndex).toHaveLength(TOTAL);
  });

  it("populates every string field on every row", () => {
    // `origin` is the entire content of Mars's detail card, so a blank one is a panel that opens
    // saying nothing — the acquirer refuses that upstream and this refuses it in the shipped form.
    const empty = featureIndex.filter(
      (feature) => !feature.name || !feature.cleanName || !feature.type || !feature.origin,
    );
    expect(empty.map((feature) => feature.name)).toEqual([]);
  });
});

describe("the longitudes arrived folded", () => {
  it("puts every centre inside the window the tile grid addresses", () => {
    // THE 540-DEGREE TRAP, IN ITS LAST POSSIBLE PLACE. The gazetteer's centres are east-positive
    // 0-360 and its outlines span -180..+360.34; a row that skipped the fold would fly the camera
    // to a longitude the globe cannot show, and would look like nothing at all on disk.
    const outside = featureIndex.filter(
      (feature) => feature.longitude < -180 || feature.longitude > 180
        || feature.latitude < -90 || feature.latitude > 90,
    );
    expect(outside.map((feature) => [feature.name, feature.longitude])).toEqual([]);
  });

  it("keeps the features the fold is for, rather than dropping them", () => {
    // The cheap positive control: folding is only observable where something crossed the seam, so a
    // producer that silently discarded those rows would satisfy the assertion above perfectly.
    expect(featureIndex.filter((feature) => feature.longitude < -90).length).toBeGreaterThan(100);
  });
});

describe("the order is published, not incidental", () => {
  it("sorts by name and then by position", () => {
    // Byte-identity against a fresh run is what guards this file, and that is only checkable while
    // the order is a function of the data rather than of the order the gazetteer's layers were read.
    const sorted = featureIndex.toSorted((left, right) => {
      if (left.name !== right.name) return left.name < right.name ? -1 : 1;
      if (left.longitude !== right.longitude) return left.longitude - right.longitude;
      return left.latitude - right.latitude;
    });
    expect(featureIndex.map((feature) => feature.name)).toEqual(
      sorted.map((feature) => feature.name),
    );
  });
});

describe("a name identifies exactly one feature", () => {
  it("leaves no name on two rows", () => {
    // The gazetteer enters Bohar twice and the producer collapses the pair, so a name is a usable
    // key downstream — a search hit, a fly-to target, a card. THIS IS THE ASSERTION THAT MUST BE
    // ALLOWED TO FAIL: an edition publishing two genuinely different features under one name would
    // keep both rows (they differ, so nothing collapses), and the consequence is a search list
    // quietly showing one of them. Better a red test than a decision made by whichever sorts first.
    const seen = new Map<string, NamedFeature[]>();
    for (const feature of featureIndex) {
      seen.set(feature.name, [...(seen.get(feature.name) ?? []), feature]);
    }
    const repeated = [...seen.entries()].filter(([, rows]) => rows.length > 1);
    expect(repeated.map(([name]) => name)).toEqual([]);
    expect(seen.size).toBe(TOTAL);
  });

  it("kept the survivor of the collapsed pair rather than dropping both", () => {
    // The positive control the assertion above cannot supply: a producer that deleted every
    // duplicated name outright would satisfy it perfectly and lose Bohar entirely.
    const bohar = featureIndex.filter((feature) => feature.name === "Bohar");
    expect(bohar).toHaveLength(1);
    expect(bohar[0]!.diameterKm).toBe(11);
  });
});

describe("one catalogue, one answer about size", () => {
  it("reads a missing diameter the same way the tiles do", () => {
    // THE EXECUTABLE COPY OF A RULE THAT EXISTS TWICE. The producer writes null where the gazetteer
    // says zero; `candidateFrom` drops a falsy diameter off a tile. Those are two spellings of one
    // decision, in two languages, and a drift makes a feature pickable by search and unpickable by
    // pointer — or framed at zero kilometres. Feeding each row back through the tile's own reader
    // is what fails loudly instead.
    const disagreed = featureIndex.filter((feature) => {
      const asTileProperties = feature.diameterKm === null
        ? { name: feature.name }
        : { name: feature.name, diameter: feature.diameterKm };
      return candidateFrom(asTileProperties, false)?.diameterKm !== feature.diameterKm;
    });
    expect(disagreed.map((feature) => feature.name)).toEqual([]);
  });

  it("sizes all but the two features the gazetteer publishes at zero", () => {
    // Pinned as a count so an edition that sized them is a decision someone makes, not a silent
    // change of what the search index can fly to.
    const unsized = featureIndex.filter((feature) => feature.diameterKm === null);
    expect(unsized.map((feature) => feature.name)).toEqual(["Candor Chaos", "Xanthe Dorsa"]);
  });

  it("never carries a zero or a negative", () => {
    const bad = featureIndex.filter(
      (feature) => feature.diameterKm !== null && !(feature.diameterKm > 0),
    );
    expect(bad.map((feature) => feature.name)).toEqual([]);
  });
});

describe("a name resolves to the place it belongs to", () => {
  it("finds a feature the pointer could have picked", () => {
    const gale = featureNamed("Gale");
    expect(gale?.latitude).toBeCloseTo(-5.37, 1);
    expect(gale?.longitude).toBeCloseTo(137.85, 1);
  });

  it("resolves every name in the catalogue, since the pointer can produce any of them", () => {
    // The lookup is what turns a picked name into a camera target, so a row it cannot reach is a
    // feature that lights and names itself and then refuses to be flown to. Asserted over the whole
    // index rather than sampled: the Map is built from these rows, so a partial answer would mean
    // duplicate keys silently collapsing distinct features.
    const unreachable = featureIndex.filter((row) => featureNamed(row.name) === null);
    expect(unreachable.map((row) => row.name)).toEqual([]);
  });

  it("hands back the row itself, not a copy that could drift", () => {
    expect(featureNamed(featureIndex[0]!.name)).toBe(featureIndex[0]);
  });

  it("answers null for a name no edition published", () => {
    // The caller passes an arbitrary string — a stale search URL, a renamed feature. Null lets the
    // click do nothing; throwing here would take the globe down with it.
    expect(featureNamed("Barsoom")).toBeNull();
    expect(featureNamed("")).toBeNull();
  });

  it("is case- and space-exact, because the tiles' promoteId is", () => {
    // Not a matcher. Feature state, the hit test and this lookup are all keyed on the published
    // spelling, and a lenient lookup here would resolve a name that could never light anything.
    expect(featureNamed("gale")).toBeNull();
    expect(featureNamed(" Gale")).toBeNull();
  });
});
