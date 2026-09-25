import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import globeSource from "../components/Globe.astro?raw";
import { functionBody } from "./testing/sourceScan";

/**
 * The gate itself is exercised against a real globe in the browser project; what these can see and
 * that cannot is whether the page's two pickers ASK, and whether the symbol the gate reaches for is
 * still in MapLibre.
 */
describe("the globe's pickers ask whether the pointer is on the planet", () => {
  const pickers = [
    ["countryAt", "function countryAt(point: Point): string | null {"],
    ["featureAt", "function featureAt(point: Point): string | null {"],
  ] as const;

  it.each(pickers)("%s gates before it queries anything", (_name, signature) => {
    const body = functionBody(globeSource, signature);
    const gate = body.indexOf("pointIsOnPlanet(map, point)");
    expect(gate, "the picker no longer asks whether the point is on the planet").toBeGreaterThan(-1);
    // Before the query, not merely present: a gate that runs after the answer is computed leaves
    // the name chip and the hover outline lighting up off the disc, which is the whole defect.
    expect(gate).toBeLessThan(body.indexOf("queryRenderedFeatures"));
    // And the answer is acted on: the gate reading false has to end the call, not be computed and
    // dropped.
    expect(body.slice(gate, gate + 60)).toContain("return null");
  });

  it("covers every rendered-feature query the page makes", () => {
    // The set, enumerated rather than assumed: a third picker added later must join the two above
    // or this fails, which is the only way source can catch one.
    const queries = globeSource.match(/map\.queryRenderedFeatures\(/g) ?? [];
    const inside = pickers.flatMap(
      ([, signature]) => functionBody(globeSource, signature).match(/map\.queryRenderedFeatures\(/g) ?? [],
    );
    expect(queries.length).toBe(inside.length);
  });

  it("canary — MapLibre still exposes the surface test the gate reaches for", () => {
    // The shipped bundle, where property names survive minification, because `transform` is untyped
    // on `Map`: a rename upstream would otherwise surface as a silent fall back to the slow path.
    const bundle = readFileSync(
      new URL("../../node_modules/maplibre-gl/dist/maplibre-gl.mjs", import.meta.url),
      "utf8",
    );
    expect(bundle).toMatch(/isPointOnMapSurface\(\w+(,\s*\w+)?\)\{/);
  });
});
