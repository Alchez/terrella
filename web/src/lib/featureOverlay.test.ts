import { describe, expect, it } from "vitest";
import { FEATURES_SOURCE, featureFillLayer, featureTilesSource } from "./featureOverlay";
import { PUBLISHED } from "./tileAddress";
import { SOURCE_LAYERS } from "./sourceLayers";

/**
 * Mars's overlay, which draws nothing — so a test is the only thing that says it is there.
 *
 * THAT IS THE REASON THIS FILE EXISTS AND NOT A JUSTIFICATION FOR IT. An invisible layer cannot be
 * judged on a globe: a screenshot of a working `feature-fill` and a screenshot of a deleted one are
 * the same image. What makes it real is that `queryRenderedFeatures` reads an opacity-0 fill, which
 * is how Earth's `countryAt` resolves a country, and that is a property only a test can hold until
 * the hit-testing commit gives it a caller.
 */

/** A range that belongs to no archive in the registry, which is the point — see the zoom case. */
const NOBODYS_ARCHIVE = {
  objectKey: "nobody/nothing-v9.pmtiles",
  token: "00000000",
  indexLeaves: 1,
  zoomConstants: "nowhere — this archive exists only in this test",
  minZoom: 3,
  maxZoom: 5,
};

describe("the source Mars's features arrive through", () => {
  it("takes its zoom range from the archive it is handed, not from a module constant", () => {
    // THE GENERALISATION'S SECOND INSTANCE, and the reason the function takes an archive rather than
    // a body slug. Handed the real registry entry it would agree with a hardcoded 0..7 forever, and
    // a guard that cannot tell those apart is decoration. This range is nobody's, so a constant
    // anywhere in the path fails here.
    const source = featureTilesSource("/tiles/x/{z}/{x}/{y}.mvt", NOBODYS_ARCHIVE);
    expect(source.minzoom).toBe(3);
    expect(source.maxzoom).toBe(5);
  });

  it("advertises exactly the zooms Mars's archive was cut to", () => {
    // The live instance, which the case above deliberately cannot cover: it proves the wiring is
    // parameterised, this proves the parameter arriving is the right one.
    const archive = PUBLISHED.mars.vector;
    expect(archive, "Mars publishes no vector archive — this whole module is unreachable").not
      .toBeNull();
    const source = featureTilesSource("/tiles/x/{z}/{x}/{y}.mvt", archive!);
    expect([source.minzoom, source.maxzoom]).toEqual([archive!.minZoom, archive!.maxZoom]);
  });

  it("addresses the tiles by URL, so the parse happens in MapLibre's worker", () => {
    // Not a style preference. An object source is deep-rebuilt by `serialize()` and structured-
    // cloned on the MAIN thread; a URL is a worker request. countryTiles.ts carries the measurement
    // that decided it — a 358 ms long task that disappeared entirely.
    const source = featureTilesSource("/tiles/mars/vector/tok/{z}/{x}/{y}.mvt", NOBODYS_ARCHIVE);
    expect(source.type).toBe("vector");
    expect(source.tiles).toEqual(["/tiles/mars/vector/tok/{z}/{x}/{y}.mvt"]);
  });
});

describe("the fill, which is the whole overlay until hit-testing lands", () => {
  it("names the layer Mars's archive actually declares", () => {
    // The silent failure this whole seam exists for: MapLibre paints an unmatched `source-layer` as
    // EMPTY, with no error and no network difference. Read from the descriptor rather than typed
    // here, so this cannot pass by agreeing with a literal that drifted alongside it.
    expect(featureFillLayer()["source-layer"]).toBe(SOURCE_LAYERS.mars.fill);
  });

  it("draws over the source the same call adds, or it is a layer with no data", () => {
    expect(featureFillLayer().source).toBe(FEATURES_SOURCE);
  });

  it("paints nothing, and that is the ratified decision rather than an unfinished edit", () => {
    // PINNED SO A FUTURE EDIT IS A DECISION. Mars's features were permanently painted for one
    // commit, and it was reverted on two grounds: a vector pyramid is interaction data on this
    // globe, and the outlines traced crater rims the RELIEF already renders in shadow. Anything
    // that makes this visible has to come through here and say why.
    expect(featureFillLayer().paint?.["fill-opacity"]).toBe(0);
  });
});
