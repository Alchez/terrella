// The caps.json contract mapping and the pure mesh math — the values the pipeline authors
// (edge_lat, feather ceiling, URLs) must flow through capOptionsFrom untouched, because the
// literals they replaced drifted silently by construction (the hero/tile constants lesson).

import { describe, expect, it } from "vitest";
import {
  MOBILE_CAP_BUDGET_PX,
  RINGS,
  SECTORS,
  buildMesh,
  capOptionsFrom,
  capTextureBudget,
  clampedTextureSize,
  type CapsManifest,
} from "./polarCaps";

const MANIFEST: CapsManifest = {
  north: { url: "/caps/cap_north.webp", edge_lat: 78, feather_hi: 84, px: 4096 },
  south: { url: "/caps/cap_south.webp", edge_lat: -78, feather_hi: -84, px: 4096 },
};

describe("capOptionsFrom", () => {
  it("maps the pipeline contract onto both caps without re-encoding it", () => {
    const [north, south] = capOptionsFrom(MANIFEST);
    expect(north.layerId).toBe("polar-cap-north");
    expect(north.textureUrl).toBe("/caps/cap_north.webp");
    expect(north.poleLat).toBe(90);
    expect(north.texEdgeLat).toBe(78);
    expect(south.poleLat).toBe(-90);
    expect(south.texEdgeLat).toBe(-78);
    expect(south.latBottom).toBeLessThan(0);
  });

  it("feathers on |lat| even though the south ships a signed ceiling", () => {
    const [north, south] = capOptionsFrom(MANIFEST);
    expect(north.featherHi).toBe(84);
    expect(south.featherHi).toBe(84); // Math.abs(−84): the shader compares against |lat|
  });

  it("keeps the feather ordered: fade starts below the ceiling", () => {
    for (const options of capOptionsFrom(MANIFEST)) {
      expect(options.featherLo).toBeLessThan(options.featherHi);
    }
  });
});

describe("buildMesh", () => {
  it("builds the full grid with in-range AEQD UVs", () => {
    const [north] = capOptionsFrom(MANIFEST);
    const { vertices, indices } = buildMesh(north);
    expect(vertices.length).toBe((RINGS + 1) * (SECTORS + 1) * 6);
    expect(indices.length).toBe(RINGS * SECTORS * 6);
    for (let vertex = 0; vertex < vertices.length; vertex += 6) {
      expect(vertices[vertex + 3]).toBeGreaterThanOrEqual(0); // u
      expect(vertices[vertex + 3]).toBeLessThanOrEqual(1);
      expect(vertices[vertex + 4]).toBeGreaterThanOrEqual(0); // v
      expect(vertices[vertex + 4]).toBeLessThanOrEqual(1);
    }
  });

  it("pins the pole ring to the texture centre (AEQD radius 0 at the pole)", () => {
    const [north] = capOptionsFrom(MANIFEST);
    const { vertices } = buildMesh(north);
    const poleRingStart = RINGS * (SECTORS + 1) * 6; // last ring = the pole
    for (let sector = 0; sector <= SECTORS; sector++) {
      const base = poleRingStart + sector * 6;
      expect(vertices[base + 3]).toBeCloseTo(0.5, 6); // u
      expect(vertices[base + 4]).toBeCloseTo(0.5, 6); // v
      expect(vertices[base + 5]).toBeCloseTo(90, 6); // lat
    }
  });
});

describe("clampedTextureSize", () => {
  it("passes a fitting texture through and clamps an oversized one", () => {
    expect(clampedTextureSize(4096, 16384)).toBe(4096);
    expect(clampedTextureSize(8192, 4096)).toBe(4096); // the weak-GPU case
  });

  it("applies the device budget even when the GPU could take the full texture", () => {
    // The OnePlus 11R case: Adreno 730 reports MAX_TEXTURE_SIZE 16384, so the GPU
    // clamp never fires — the budget is what spares the phone the 268 MB upload.
    expect(clampedTextureSize(8192, 16384, 4096)).toBe(4096);
  });

  it("leaves desktops at full size when the budget is Infinity", () => {
    expect(clampedTextureSize(8192, 16384, Infinity)).toBe(8192);
  });

  it("never upscales past the image itself", () => {
    expect(clampedTextureSize(4096, 16384, 8192)).toBe(4096);
  });
});

describe("capTextureBudget", () => {
  it("gives mobile-class devices the 4096 rung and desktops no budget", () => {
    expect(capTextureBudget(true)).toBe(MOBILE_CAP_BUDGET_PX);
    expect(capTextureBudget(false)).toBe(Infinity);
  });
});
