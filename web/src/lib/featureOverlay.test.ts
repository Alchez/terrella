import { describe, expect, it } from "vitest";
import {
  FEATURES_SOURCE,
  featureFillLayer,
  featureHighlightLayers,
  featureLinearHitLayer,
  featureTilesSource,
  hoverStateTargets,
} from "./featureOverlay";
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

describe("the identity one hover writes against", () => {
  it("promotes the same field the pick rule returns", () => {
    // `pickFeature` returns a NAME, and `setFeatureState` addresses features by promoted id. If
    // these two ever name different fields the highlight silently does nothing — MapLibre answers
    // an unaddressable feature-state write by firing an ErrorEvent and returning.
    expect(featureTilesSource("/t/{z}/{x}/{y}.mvt", NOBODYS_ARCHIVE).promoteId).toBe("name");
  });

  it("writes to every source-layer that carries hover paint, and to nothing else", () => {
    // Feature state is keyed on (source, sourceLayer, id), so one write per source-layer is
    // required and a missing one leaves half the highlight dark. Derived from the layers that
    // actually paint rather than listed, so adding a highlight layer over a third source-layer
    // fails here instead of shipping a half-lit feature.
    const paintedLayers = new Set(
      featureHighlightLayers().map((layer) => layer["source-layer"]),
    );
    expect(new Set(hoverStateTargets().map((target) => target.sourceLayer))).toEqual(paintedLayers);
    expect(hoverStateTargets().every((target) => target.source === FEATURES_SOURCE)).toBe(true);
    // The fill is deliberately absent: it carries no hover paint, so a write there could only be
    // a mistake that looks like thoroughness.
    expect(paintedLayers.has(SOURCE_LAYERS.mars.fill!)).toBe(false);
  });
});

/** The widest stop of a zoom-interpolated `line-width` ramp. Throws rather than optional-chaining
 *  into `undefined`: a spec with no width is a broken layer, and a silent NaN comparison below
 *  would pass. */
function widestWidth(spec: { paint?: Record<string, unknown> }): number {
  const ramp = spec.paint?.["line-width"];
  if (!Array.isArray(ramp)) throw new Error("this layer spec carries no line-width ramp");
  return ramp.at(-1) as number;
}

describe("the linear features, which exist only as lines", () => {
  it("gets a hit surface over the layer that carries them", () => {
    // They have no polygon anywhere in the archive, so the fill cannot answer for them: without
    // this layer they are unreachable at every zoom, not merely hard to hit.
    expect(featureLinearHitLayer()["source-layer"]).toBe(SOURCE_LAYERS.mars.line);
    expect(featureLinearHitLayer().source).toBe(FEATURES_SOURCE);
  });

  it("stays invisible, because a hit surface that paints is a decision nobody made", () => {
    expect(featureLinearHitLayer().paint?.["line-opacity"]).toBe(0);
  });

  it("is wider than the hairline that highlights it, or it is not a tolerance", () => {
    // The stroke's width IS the pointing tolerance. If it ever narrowed to the drawn width, a
    // vallis would be exactly as unhittable as it is today and the layer would look present.
    const drawn = featureHighlightLayers().find((l) => l.id === "feature-linear-hl-line")!;
    expect(widestWidth(featureLinearHitLayer())).toBeGreaterThan(widestWidth(drawn) * 3);
  });
});

describe("the hover linework", () => {
  it("covers both kinds of geometry, since they are disjoint sets", () => {
    const bySourceLayer = new Map(
      featureHighlightLayers().map((layer) => [layer["source-layer"], layer.id]),
    );
    expect([...bySourceLayer.keys()].toSorted())
      .toEqual([SOURCE_LAYERS.mars.line, SOURCE_LAYERS.mars.outline].toSorted());
  });

  it("strokes the ring layer rather than the polygon", () => {
    // The stray-meridian fix countryHighlight.ts records: clipping a line trims it, clipping a
    // polygon closes the ring along the cut and a `line` layer strokes that phantom edge.
    const rings = featureHighlightLayers().filter((l) => l.id.startsWith("feature-hl-"));
    expect(rings).toHaveLength(2);
    expect(rings.every((l) => l["source-layer"] === SOURCE_LAYERS.mars.outline)).toBe(true);
  });

  it("is fully transparent until a feature's hover state is set", () => {
    // The property that makes this an ON-HOVER layer rather than paint. Every opacity is a `case`
    // whose default arm is a literal zero, so an un-hovered globe is untouched by all four.
    for (const layer of featureHighlightLayers()) {
      const opacity = layer.paint?.["line-opacity"] as unknown[];
      expect(opacity[0], `${layer.id} is not conditional on hover`).toBe("case");
      expect(opacity.at(-1), `${layer.id} paints without a hover`).toBe(0);
    }
  });

  it("puts each casing under its ink, or the separator becomes a second line", () => {
    const layers = featureHighlightLayers();
    for (const [casing, ink] of [
      ["feature-hl-casing", "feature-hl-line"],
      ["feature-linear-hl-casing", "feature-linear-hl-line"],
    ]) {
      expect(layers.findIndex((l) => l.id === casing))
        .toBeLessThan(layers.findIndex((l) => l.id === ink));
    }
  });
});
