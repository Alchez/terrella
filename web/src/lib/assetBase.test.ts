// The asset-base seam. Every one of these cases is a way a deploy's env can be written by
// hand, and three of them produce a silently wrong URL under bare concatenation — which is
// what every call site did before this module existed (`${HERO_BASE}${slug}-1920.webp`).

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { TILE_URL_TEMPLATE, resolveAssetBase } from "./assetBase";

/** web/ — this file is web/src/lib/assetBase.test.ts. */
const WEB_ROOT = fileURLToPath(new URL("../../", import.meta.url));

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

// These read source rather than importing it, because the thing under test is the drift
// between two files that no type can relate: the bases this module READS from the build
// env, and the bases package.json's `build:deploy` SUPPLIES. They agree today; nothing but
// this test makes them keep agreeing. The failure is silent and total — an unsupplied base
// falls back to same-origin, so the deploy succeeds and every URL under it 404s in
// production. That is exactly how the site stood before this phase: 204 pages addressing
// /heroes/ on an origin that has never held a hero.
describe("the deploy build supplies every base the site reads", () => {
  const deployScript = (): string => {
    const packageJson = JSON.parse(readFileSync(`${WEB_ROOT}package.json`, "utf8"));
    return packageJson.scripts["build:deploy"];
  };

  const basesReadFromEnv = (): string[] => {
    const source = readFileSync(`${WEB_ROOT}src/lib/assetBase.ts`, "utf8");
    return [...source.matchAll(/import\.meta\.env\.(PUBLIC_\w+)/g)].map((match) => match[1]);
  };

  it("scans a module that actually declares bases", () => {
    // Without this the whole suite passes vacuously the day assetBase.ts is refactored to
    // read its env some other way — a guard that silently stops guarding.
    expect(basesReadFromEnv().length).toBeGreaterThan(0);
  });

  it("names every base in build:deploy, as an absolute URL", () => {
    const script = deployScript();
    // `=https://` and not merely the name: a base set to a relative path would satisfy a
    // presence check while shipping the same-origin URLs this is here to prevent.
    const missing = basesReadFromEnv().filter((name) => !script.includes(`${name}=https://`));
    expect(missing).toEqual([]);
  });
});
