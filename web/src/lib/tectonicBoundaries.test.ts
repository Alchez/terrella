/**
 * The plate boundary overlay: the vocabulary it deliberately does not hold, its layers, the toggle,
 * and the two gates that decide who sees it.
 *
 * Every failure here is silent on a globe. A second copy of the boundary vocabulary brings filters
 * back, and MapLibre paints a filter that matches nothing as an empty layer, reporting nothing; and a
 * body gate that stops being read paints an overlay onto a planet that has no plate boundaries.
 */

import { readFileSync } from "node:fs";

import {
  expression,
  latest,
  type StylePropertySpecification,
} from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";

import { BODIES } from "./bodies";
import {
  CASING_INK,
  MINOR_FADE_END_ZOOM,
  MINOR_FADE_START_ZOOM,
  MINOR_LEVEL,
  TECTONIC_INK,
  TECTONIC_LAYERS,
  TECTONICS_FILE,
  TECTONICS_SOURCE,
  tectonicLayers,
  tectonicsOn,
  tectonicsSource,
  tectonicsStorageValue,
} from "./tectonicBoundaries";

/** The three widths out of one `interpolate` spec: every second entry after `["zoom"]`. */
function stopWidths(id: string): number[] {
  const layer = tectonicLayers().find((candidate) => candidate.id === id);
  if (layer === undefined) throw new Error(`no layer ${id}`);
  const spec = layer.paint?.["line-width"];
  if (!Array.isArray(spec)) throw new Error(`${id} has no interpolated line-width`);
  return spec.slice(3).filter((_, index) => index % 2 === 1) as number[];
}

/** The same three, read out of the border overlay's own literals in `Globe.astro`. Source text
 *  rather than an import, because those widths are declared inside the component. */
function borderStopWidths(name: string): number[] {
  const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");
  const found = new RegExp(`const ${name}[^;]*?1,\\s*([\\d.]+),\\s*4,\\s*([\\d.]+),\\s*8,\\s*([\\d.]+)`).exec(globe);
  return found === null ? [] : found.slice(1).map(Number);
}

/**
 * One layer's `line-opacity` for one feature at one zoom, run through MapLibre's own evaluator
 * rather than a reading of the array, so a spec MapLibre would reject or read differently fails here.
 */
function opacityAt(id: string, zoom: number, properties: Record<string, unknown>): number {
  const layer = tectonicLayers().find((candidate) => candidate.id === id);
  if (layer === undefined) throw new Error(`no layer ${id}`);
  const compiled = expression.createPropertyExpression(
    layer.paint?.["line-opacity"],
    "line-opacity",
    // The spec is typed from its JSON, which is wider than the union the parser declares.
    latest.paint_line["line-opacity"] as StylePropertySpecification,
  );
  if (compiled.result !== "success") {
    throw new Error(`${id}: ${compiled.value.map((error) => error.message).join("; ")}`);
  }
  return compiled.value.evaluate({ zoom }, { type: 2, properties });
}

/** The opening camera's zoom, read out of the map constructor in `Globe.astro`. */
function openingZoom(): number {
  const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");
  const found = /\bzoom: ([\d.]+),\s*minZoom: ([\d.]+),/.exec(globe);
  if (found === null) throw new Error("the map constructor's zoom is no longer readable");
  return Number(found[1]);
}

describe("the vocabulary this file deliberately does not hold", () => {
  const source = readFileSync(new URL("./tectonicBoundaries.ts", import.meta.url), "utf8");

  it("carries no filter, so no segment can be dropped by the style", () => {
    for (const layer of tectonicLayers()) expect(layer).not.toHaveProperty("filter");
  });

  it("names no boundary type, the compose stage owning that list alone", () => {
    const code = source.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    for (const type of ["spreading center", "subduction zone", "inferred", "dextral transform"]) {
      expect(code, `a second copy of the vocabulary has come back: ${type}`).not.toContain(type);
    }
  });
});

/** A storage stand-in, so the real one is never touched and the absent case is expressible. */
const storageOf = (value: string | null) => ({ getItem: () => value });

describe("the toggle's persisted state", () => {
  const base = readFileSync(new URL("../layouts/Base.astro", import.meta.url), "utf8");
  const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");

  it("is off for a visitor who has never pressed it, so no plate geometry is fetched", () => {
    expect(tectonicsOn(storageOf(null))).toBe(false);
  });

  it("turns on only for the value the layout writes", () => {
    expect(tectonicsOn(storageOf("1"))).toBe(true);
    for (const stray of ["0", "", "on", "true"]) {
      expect(tectonicsOn(storageOf(stray)), `${stray} turned the overlay on`).toBe(false);
    }
  });

  it("round-trips whatever it writes", () => {
    for (const on of [true, false]) {
      expect(tectonicsOn(storageOf(tectonicsStorageValue(on)))).toBe(on);
    }
  });

  it("is written by the layout and never by the globe, which only listens", () => {
    expect(base, "the layout no longer writes the key").toContain("localStorage.setItem(TECTONICS_KEY");
    expect(globe, "the globe writes state the layout owns").not.toContain("localStorage.setItem");
  });

  it("carries no URL flag beside the button, which would be a second answer to one question", () => {
    for (const [name, source] of [
      ["Globe.astro", globe],
      ["the module", readFileSync(new URL("./tectonicBoundaries.ts", import.meta.url), "utf8")],
    ]) {
      expect(source.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, ""), `${name} still parses a flag`).not.toMatch(
        /parseTectonicsFlag|urlFlags\.(has|get)\("tectonics"\)/,
      );
    }
  });
});

describe("the source", () => {
  it("declares no attribution, which would make the on-map credit change width as it toggles", () => {
    expect(tectonicsSource()).not.toHaveProperty("attribution");
  });

  it("fetches the file the compose stage writes", () => {
    expect(tectonicsSource().data).toContain(TECTONICS_FILE);
  });
});

describe("the layers", () => {
  it("are every id the visibility list names, in the same order", () => {
    expect(tectonicLayers().map((layer) => layer.id)).toEqual([...TECTONIC_LAYERS]);
  });

  it("all read the one source", () => {
    for (const layer of tectonicLayers()) expect(layer.source).toBe(TECTONICS_SOURCE);
  });

  it("are all `line`, so they join the drape run rather than splitting it", () => {
    for (const layer of tectonicLayers()) expect(layer.type).toBe("line");
  });

  it("keep the ink narrower than the casing at every stop, or the rim shows on one side only", () => {
    const ink = stopWidths("tectonic-ink");
    const casing = stopWidths("tectonic-casing");
    expect(ink).toHaveLength(3);
    expect(casing).toHaveLength(3);
    for (const [index, value] of ink.entries()) expect(value).toBeLessThan(casing[index]);
  });

  it("stay finer than the border overlay, which is the only thing telling the two apart", () => {
    for (const [ours, theirs] of [
      ["tectonic-ink", "inkWidth"],
      ["tectonic-casing", "casingWidth"],
    ]) {
      const border = borderStopWidths(theirs);
      expect(border, `${theirs} is no longer readable from Globe.astro`).toHaveLength(3);
      for (const [index, value] of stopWidths(ours).entries()) {
        expect(value, `${ours} is not finer than ${theirs} at stop ${index}`).toBeLessThan(
          border[index],
        );
      }
    }
  });

  describe("fade the minor boundaries in on zoom", () => {
    const major = { level: MINOR_LEVEL - 1 };
    const minor = { level: MINOR_LEVEL };

    it("show only the major boundaries at the opening view", () => {
      expect(openingZoom()).toBeLessThanOrEqual(MINOR_FADE_START_ZOOM);
      for (const id of TECTONIC_LAYERS) {
        expect(opacityAt(id, openingZoom(), minor), `${id} draws a minor segment`).toBe(0);
        expect(opacityAt(id, openingZoom(), major), `${id} hides a major segment`).toBeGreaterThan(0);
      }
    });

    it("draw a minor boundary exactly as a major one once the fade is done", () => {
      for (const id of TECTONIC_LAYERS) {
        for (const zoom of [MINOR_FADE_END_ZOOM, 8]) {
          expect(opacityAt(id, zoom, minor), `${id} at z${zoom}`).toBe(opacityAt(id, zoom, major));
        }
      }
    });

    it("are partway through between the two stops, so it is a fade and not a switch", () => {
      const midway = (MINOR_FADE_START_ZOOM + MINOR_FADE_END_ZOOM) / 2;
      for (const id of TECTONIC_LAYERS) {
        const value = opacityAt(id, midway, minor);
        expect(value).toBeGreaterThan(0);
        expect(value).toBeLessThan(opacityAt(id, midway, major));
      }
    });

    it("leave a major boundary at one opacity from the widest zoom out to the deepest", () => {
      for (const id of TECTONIC_LAYERS) {
        const values = [0.4, MINOR_FADE_START_ZOOM, MINOR_FADE_END_ZOOM, 8].map((zoom) =>
          opacityAt(id, zoom, major),
        );
        expect(new Set(values), `${id} varies with zoom: ${values.join(", ")}`).toHaveLength(1);
      }
    });

    it("draw a level they do not know as a major boundary, so a respelt attribute shows more rather than less", () => {
      for (const id of TECTONIC_LAYERS) {
        for (const stray of [{}, { level: String(MINOR_LEVEL) }, { level: MINOR_LEVEL + 1 }]) {
          expect(opacityAt(id, openingZoom(), stray), `${id} ${JSON.stringify(stray)}`).toBe(
            opacityAt(id, openingZoom(), major),
          );
        }
      }
    });
  });

  it("draw a dark ink over a dark rim, neither of them the hover gold", () => {
    expect(TECTONIC_INK).not.toBe(CASING_INK);
    for (const colour of [TECTONIC_INK, CASING_INK]) expect(colour).not.toBe("#eca834");
  });
});

describe("the two gates the overlay hangs on", () => {
  /**
   * A pin at its own site, which the subsystem source-scan says a gate like this needs.
   *
   * That scan asks only whether a field is read somewhere, so it cannot see one gate going missing
   * when another reads the same field. Both gates here read `subsystems.tectonics`, and dropping
   * the one at the add site would leave the overlay painting on any body whose outer gate passes
   * for another reason, which is every body publishing vectors.
   */
  const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");

  it("adds the layers only where the body has plate boundaries AND the visitor asked", () => {
    expect(globe, "the add site no longer checks both gates").toContain(
      "if (subsystems.tectonics && tectonicsOn()) addTectonicBoundaries();",
    );
  });

  it("offers the button only on a body that has plate boundaries", () => {
    const page = readFileSync(new URL("../pages/earth/index.astro", import.meta.url), "utf8");
    expect(page, "the control is hard-wired on rather than asked of the registry").toContain(
      "tectonics={body.hasTectonics}",
    );
  });

  it("mounts a late turn-on under the borders, where a style.load mount already sits", () => {
    // Appending is the position at style.load because nothing else exists yet, and it stops being
    // the position the moment a visitor turns borders on first: a bare `addLayer` then puts geology
    // over politics, on exactly the segments where a plate boundary follows a national one.
    expect(globe).toContain("const beforeBorders = BORDER_LAYERS.find((id) => map.getLayer(id));");
    expect(globe).toContain("for (const layer of tectonicLayers()) map.addLayer(layer, beforeBorders);");
  });

  it("is a body fact, and the two registered bodies disagree about it", () => {
    expect(BODIES.earth.hasTectonics).toBe(true);
    expect(BODIES.mars.hasTectonics).toBe(false);
  });
});
