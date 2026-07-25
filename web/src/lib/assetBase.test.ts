// The asset-base seam. Every one of these cases is a way a deploy's env can be written by
// hand, and three of them produce a silently wrong URL under bare concatenation — which is
// what every call site did before this module existed (`${HERO_BASE}${slug}-1920.webp`).

import { describe, expect, it } from "vitest";
import { TILE_URL_TEMPLATE, resolveAssetBase } from "./assetBase";

describe("resolveAssetBase", () => {
  it("falls back to the same-origin path when nothing is configured", () => {
    expect(resolveAssetBase(undefined, "/heroes/")).toBe("/heroes/");
  });

  it("treats an empty or whitespace-only value as unset", () => {
    expect(resolveAssetBase("", "/heroes/")).toBe("/heroes/");
    expect(resolveAssetBase("   ", "/heroes/")).toBe("/heroes/");
  });

  it("appends the separator a hand-written host is likely to be missing", () => {
    expect(resolveAssetBase("https://assets.example.com/heroes", "/heroes/")).toBe(
      "https://assets.example.com/heroes/",
    );
  });

  it("leaves an already-terminated base alone", () => {
    expect(resolveAssetBase("https://assets.example.com/heroes/", "/heroes/")).toBe(
      "https://assets.example.com/heroes/",
    );
  });

  it("trims stray whitespace rather than baking it into the URL", () => {
    expect(resolveAssetBase("  https://assets.example.com/heroes/  ", "/heroes/")).toBe(
      "https://assets.example.com/heroes/",
    );
  });

  it("accepts a bare origin, where the trailing slash is the whole path", () => {
    expect(resolveAssetBase("https://tiles.example.com", "/tiles/")).toBe("https://tiles.example.com/");
  });
});

describe("TILE_URL_TEMPLATE", () => {
  it("carries MapLibre's placeholders and the archive's PNG tile type", () => {
    expect(TILE_URL_TEMPLATE.endsWith("{z}/{x}/{y}.png")).toBe(true);
  });
});
