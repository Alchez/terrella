import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  DRAPED_LAYER_TYPES,
  GLOBE_LAYER_TYPES,
  drapeStackCount,
  isDraped,
} from "./drapeStacks";

describe("drapeStackCount", () => {
  it("counts one stack for an unbroken run", () => {
    expect(drapeStackCount(["background", "raster", "fill", "line"])).toBe(1);
  });

  it("counts zero when nothing drapes at all", () => {
    // A style with no drapeable layers allocates no RTT objects — the pool stays empty rather
    // than holding one stack's worth of nothing.
    expect(drapeStackCount(["circle", "symbol", "custom"])).toBe(0);
  });

  it("splits a run in two when a non-drapeable layer lands in the MIDDLE", () => {
    // This is exactly what `country-hit` used to do between the fill and the border lines.
    expect(drapeStackCount(["fill", "circle", "line"])).toBe(2);
  });

  it("charges nothing for a non-drapeable layer at the END", () => {
    // The asymmetry the move relies on: a trailing circle terminates the run it follows.
    expect(drapeStackCount(["fill", "line", "circle"])).toBe(1);
  });

  it("charges nothing for a non-drapeable layer at the START", () => {
    expect(drapeStackCount(["circle", "fill", "line"])).toBe(1);
  });

  it("counts consecutive non-drapeable layers as ONE break, not two", () => {
    // The two polar caps are adjacent `custom` layers. If this counted per-layer the model would
    // over-report and the pool arithmetic in HISTORY would not have matched to 0.4%.
    expect(drapeStackCount(["raster", "custom", "custom", "fill"])).toBe(2);
  });

  it("treats an unknown layer type as non-drapeable", () => {
    // Fail toward the expensive reading: a type we do not recognise is one MapLibre may not
    // drape, and under-counting would hide a regression rather than surface it.
    expect(drapeStackCount(["fill", "fill-extrusion", "line"])).toBe(2);
    expect(isDraped("fill-extrusion")).toBe(false);
  });
});

describe("the globe's own layer order", () => {
  it("costs two stacks, which is the point of putting country-hit last", () => {
    expect(drapeStackCount(GLOBE_LAYER_TYPES)).toBe(2);
  });

  it("would cost three with country-hit back in its old slot", () => {
    // The regression this file exists to catch, stated as the diff rather than asserted in the
    // abstract: a test that only pins "2" passes just as well if someone deletes a layer.
    const fillAt = GLOBE_LAYER_TYPES.indexOf("fill");
    const oldOrder = [
      ...GLOBE_LAYER_TYPES.slice(0, fillAt + 1),
      "circle", // country-hit, where it used to sit
      ...GLOBE_LAYER_TYPES.slice(fillAt + 1).filter((type) => type !== "circle"),
    ];
    expect(drapeStackCount(oldOrder)).toBe(3);
  });

  it("ends on the only non-drapeable layer after the caps", () => {
    // Anything appended after `country-hit` pays the third stack back. Pin the tail so that
    // shows up here rather than as a card that fills faster.
    expect(GLOBE_LAYER_TYPES.at(-1)).toBe("circle");
    expect(GLOBE_LAYER_TYPES.filter((type) => !DRAPED_LAYER_TYPES.includes(type))).toEqual([
      "custom",
      "custom",
      "circle",
    ]);
  });

  it("matches what earth.astro actually adds last", () => {
    // The array above is a MODEL of the page. Pin it to the page, or it becomes a description of
    // a layer order that used to exist — the exact rot this module was written after finding.
    const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");
    const hitAt = globe.indexOf("addCountryHitTargets();");
    const highlightAt = globe.indexOf("addCountryHighlight();");
    const countriesAt = globe.indexOf("addCountryTiles();");
    // ANTI-VACUITY, and it is not hypothetical: this used to look for `addCountries(countries);`,
    // and when that call was deleted with the GeoJSON arm `indexOf` returned -1 — so the ordering
    // assertions compared against -1 and passed while checking nothing. Every anchor must be
    // PRESENT before its position means anything.
    for (const [label, at] of [
      ["addCountryTiles();", countriesAt],
      ["addCountryHighlight();", highlightAt],
      ["addCountryHitTargets();", hitAt],
    ] as const) {
      expect(at, `${label} is missing from earth.astro — the order below would be vacuous`).toBeGreaterThan(-1);
    }
    expect(hitAt).toBeGreaterThan(highlightAt);
    expect(highlightAt).toBeGreaterThan(countriesAt);
    // And the layer itself must not have crept back into the source-and-fill run.
    const addCountryTilesBody = globe.slice(
      globe.indexOf("function addCountryTiles("),
      globe.indexOf("function addCountryHitTargets("),
    );
    expect(addCountryTilesBody).not.toContain('id: "country-hit"');
  });
});

describe("canary — MapLibre still drapes exactly these types", () => {
  it("agrees with LAYERS_TO_TEXTURES in the shipped bundle", () => {
    // Our copy of a private constant. If MapLibre adds `circle` here the move above becomes
    // pointless and this module should be deleted; if it REMOVES a type we drape today, the
    // stack count silently rises. Either way this is where it surfaces.
    const bundle = readFileSync(
      new URL("../../node_modules/maplibre-gl/dist/maplibre-gl-dev.mjs", import.meta.url),
      "utf8",
    );
    const declaration = /const LAYERS_TO_TEXTURES = \{([^}]*)\}/.exec(bundle);
    expect(declaration, "LAYERS_TO_TEXTURES is gone or renamed in MapLibre").not.toBeNull();
    // Keys are bare identifiers except `"color-relief"`, which only carries quotes because of the
    // hyphen — so match both forms rather than the quoted one, which finds exactly that one key
    // and would have reported five missing types as a MapLibre change.
    const types = [...(declaration?.[1] ?? "").matchAll(/"?([a-z-]+)"?\s*:/g)].map(
      (match) => match[1],
    );
    expect(types.toSorted()).toEqual([...DRAPED_LAYER_TYPES].toSorted());
  });

  it("still allocates one RTT object per tile per stack", () => {
    // The arithmetic that makes a stack count a memory figure at all: acquireRTT is called from
    // the per-stack loop, keyed by stack index on the tile.
    const bundle = readFileSync(
      new URL("../../node_modules/maplibre-gl/dist/maplibre-gl-dev.mjs", import.meta.url),
      "utf8",
    );
    expect(bundle).toMatch(/acquireRTT\(painter, stack, size\)\s*\{\s*return this\.rttObjects\[stack\] = painter\.acquireRTT\(size\)/);
  });
});
