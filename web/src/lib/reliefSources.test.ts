// These two specs are the last place a per-body number can be replaced by Earth's, and the failure
// is invisible from the page: a Mars source declared to z8 asks for tiles the pyramid does not hold,
// every server refuses the address without a storage read, and the browser paints nothing — which
// looks exactly like a tile still in flight. The assertions below are on the objects MapLibre is
// handed, because the number MapLibre is handed is the thing that goes wrong.

import { describe, expect, it } from "vitest";
import type { BodySlug } from "./bodies";
import { DECLARED_TILE_SIZE, reliefBaseTilesSource, reliefTilesSource } from "./reliefSources";
import { RELIEF_BASE_MAX_ZOOM, RELIEF_MAX_ZOOM } from "./reliefTiles";
import { PUBLISHED, archiveFor } from "./tileAddress";

const TEMPLATE = "https://tiles.example/earth/relief/deadbeef/{z}/{x}/{y}.webp";
const ATTRIBUTION = '<a href="/about/">Data sources</a>';

/** Every body that publishes a relief pyramid, so a third planet joins these cases by existing. */
const RELIEF_BODIES = (Object.keys(PUBLISHED) as BodySlug[]).filter(
  (body) => PUBLISHED[body].relief,
);

describe("the relief source", () => {
  it("takes each body's own zoom range from the registry, never Earth's constants", () => {
    for (const body of RELIEF_BODIES) {
      const archive = archiveFor(body, "relief");
      const source = reliefTilesSource(body, TEMPLATE, ATTRIBUTION);
      expect(source.minzoom, `${body} floor`).toBe(archive.minZoom);
      expect(source.maxzoom, `${body} ceiling`).toBe(archive.maxZoom);
    }
  });

  it("is measuring bodies that actually DISAGREE, or the case above proves nothing", () => {
    // The loop passes against a hardcoded Earth constant the moment every body shares a ceiling, and
    // it would go on passing silently. This is the premise that keeps it honest, asserted rather
    // than assumed: the two bodies are cut to different ceilings, because a ceiling follows each
    // body's own source data. If a re-cut ever makes them agree, this fails and the case above needs
    // a different second instance — not a wider tolerance.
    expect(RELIEF_BODIES.length).toBeGreaterThan(1);
    const ceilings = new Set(RELIEF_BODIES.map((body) => archiveFor(body, "relief").maxZoom));
    expect(ceilings.size).toBeGreaterThan(1);
    expect(archiveFor("mars", "relief").maxZoom).not.toBe(RELIEF_MAX_ZOOM);
  });

  it("declares the 512px assets at 256, which serves them @2x", () => {
    expect(DECLARED_TILE_SIZE).toBe(256);
    expect(reliefTilesSource("earth", TEMPLATE, ATTRIBUTION).tileSize).toBe(DECLARED_TILE_SIZE);
  });

  it("draws the template it is given, and credits it", () => {
    const source = reliefTilesSource("earth", TEMPLATE, ATTRIBUTION);
    expect(source.tiles).toEqual([TEMPLATE]);
    expect(source.attribution).toBe(ATTRIBUTION);
  });
});

describe("the pinned base source — a floor that is a map, not a colour", () => {
  it("caps the base source at z0 for every body, because that is what makes it unmissable", () => {
    // The guarantee is arithmetic, not luck: a raster source's covering set is clamped to its own
    // maxzoom, so at 0 there is exactly ONE tile, ideal at every camera, therefore never absent
    // after first load. At z1 the set is still camera-dependent and a first visit to a cold quadrant
    // paints nothing — measured on production, so this is load-bearing.
    expect(RELIEF_BASE_MAX_ZOOM).toBe(0);
    for (const body of RELIEF_BODIES) {
      expect(reliefBaseTilesSource(body, TEMPLATE).maxzoom, `${body} base ceiling`).toBe(0);
    }
  });

  it("takes its FLOOR from the body even though its ceiling is pinned", () => {
    for (const body of RELIEF_BODIES) {
      expect(reliefBaseTilesSource(body, TEMPLATE).minzoom).toBe(archiveFor(body, "relief").minZoom);
    }
  });

  it("carries no attribution, so one archive does not credit itself twice", () => {
    // MapLibre renders the attribution of every source it draws and both of these draw the same
    // archive, so a credit here would put the same control on screen twice. Structural now — the
    // function takes no attribution at all — but asserted because a later edit could add one.
    expect(reliefBaseTilesSource("earth", TEMPLATE)).not.toHaveProperty("attribution");
  });

  it("draws the same archive as the relief source above it", () => {
    // Not a second pyramid: the floor is the SAME tiles, which is what makes it a map rather than a
    // colour, and what makes it free after the first fetch.
    expect(reliefBaseTilesSource("earth", TEMPLATE).tiles).toEqual(
      reliefTilesSource("earth", TEMPLATE, ATTRIBUTION).tiles,
    );
  });
});
