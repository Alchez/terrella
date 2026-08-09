import { describe, it, expect } from "vitest";
import { BODIES } from "./bodies";
import { SOURCE_LAYERS, namedLayers, requireSourceLayer, sourceLayer } from "./sourceLayers";

describe("SOURCE_LAYERS", () => {
  it("pins the names each cutter writes, for both bodies", () => {
    // The other end is Python, which no type system here reaches, and a disagreement paints
    // nothing rather than erroring. tests/test_source_layers.py reads THIS FILE against both
    // producers; these literals are what makes an accidental edit here visible on its own.
    expect(SOURCE_LAYERS.earth).toEqual({
      fill: "country_fill",
      outline: "country_outline",
      hit: "country_hit",
      line: null,
      label: null,
    });
    expect(SOURCE_LAYERS.mars).toEqual({
      fill: "feature_fill",
      outline: "feature_outline",
      hit: null,
      line: "feature_line",
      label: "feature_label",
    });
  });

  it("makes every body answer for every role, so a new role cannot be silently inherited", () => {
    // The `PUBLISHED` rule, one tier down: a Partial here would let a role added for one planet
    // read as absent on the others without anyone deciding that.
    const roles = Object.keys(SOURCE_LAYERS.earth).toSorted();
    for (const slug of Object.keys(BODIES)) {
      expect(
        Object.keys(SOURCE_LAYERS[slug as keyof typeof SOURCE_LAYERS]).toSorted(),
        slug,
      ).toEqual(roles);
    }
  });

  it("covers every body the site knows about", () => {
    // Without this, a third planet could be added to BODIES and reach a globe with no entry here —
    // an `undefined` record, and `undefined["fill"]` throws only if something asks.
    expect(Object.keys(SOURCE_LAYERS).toSorted()).toEqual(Object.keys(BODIES).toSorted());
  });

  it("gives the two bodies genuinely different shapes, which is why this is per body", () => {
    // The guard against a descriptor that looks parameterised and holds one answer twice. Earth
    // carries a hit target and no linework; Mars carries linework and labels and no hit target.
    expect(sourceLayer("earth", "hit")).not.toBeNull();
    expect(sourceLayer("mars", "hit")).toBeNull();
    expect(sourceLayer("earth", "line")).toBeNull();
    expect(sourceLayer("mars", "line")).not.toBeNull();
  });

  it("shares no layer name between bodies", () => {
    // Two archives naming one layer the same is not a collision on its own — they are different
    // objects — but it would mean a style built for one planet silently half-works on the other,
    // which is harder to see than nothing working at all.
    const shared = namedLayers("earth").filter((name) => namedLayers("mars").includes(name));
    expect(shared).toEqual([]);
  });
});

describe("requireSourceLayer", () => {
  it("returns the name where the archive has one", () => {
    expect(requireSourceLayer("earth", "fill")).toBe("country_fill");
  });

  it("THROWS rather than handing undefined to a style spec", () => {
    // The whole reason it exists. A null reaching `source-layer` becomes undefined, and MapLibre
    // answers an unaddressable source-layer with an ErrorEvent and a return — no throw, no paint.
    expect(() => requireSourceLayer("mars", "hit")).toThrow(/publishes no hit source-layer/);
  });
});

describe("namedLayers", () => {
  it("drops the nulls and keeps the rest", () => {
    expect(namedLayers("earth")).toEqual(["country_fill", "country_outline", "country_hit"]);
    expect(namedLayers("mars")).toEqual([
      "feature_fill",
      "feature_outline",
      "feature_line",
      "feature_label",
    ]);
  });
});
