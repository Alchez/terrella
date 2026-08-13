// The asset-base seam. Every one of these cases is a way a deploy's env can be written by
// hand, and three of them produce a silently wrong URL under bare concatenation — which is
// what every call site did before this module existed (`${HERO_BASE}${slug}-1920.webp`).

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { TILE_BASE, capsManifestUrl, resolveAssetBase, tileUrlTemplate } from "./assetBase";
import { BODIES, type BodySlug } from "./bodies";
import { LAYERS, archiveFor, tilePathTemplate } from "./tileAddress";

const SLUGS = Object.keys(BODIES) as BodySlug[];

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

describe("tileUrlTemplate", () => {
  it("is the tile base and the address, with nothing invented in between", () => {
    // The whole function. It exists so the base — the one env-shaped thing here — is the ONLY
    // thing this module contributes to a tile URL; the address comes from the registry both
    // servers parse with, so what the browser ASKS for and what they ACCEPT cannot drift.
    expect(tileUrlTemplate("earth", "relief")).toBe(`${TILE_BASE}${tilePathTemplate("earth", "relief")}`);
  });

  it("names the body, the layer and the cut in every URL it builds", () => {
    const template = tileUrlTemplate("earth", "terrain");
    expect(template.startsWith(TILE_BASE)).toBe(true);
    expect(template).toContain("earth/terrain/");
    expect(template).toContain(archiveFor("earth", "terrain").token);
    expect(template.endsWith(`/{z}/{x}/{y}.${LAYERS.terrain.extension}`)).toBe(true);
  });

  it("rides the SAME base for every layer, because one Worker serves them all", () => {
    // Derived rather than given a PUBLIC_TERRAIN_BASE or PUBLIC_COUNTRIES_BASE of their own. If
    // any two of these resolve to different origins, one tile server has been addressed in
    // several places — and an unset PUBLIC_ base does not error, it silently becomes same-origin.
    const templates = (["relief", "terrain", "vector"] as const).map((layer) =>
      tileUrlTemplate("earth", layer),
    );
    for (const template of templates) expect(template.startsWith(TILE_BASE)).toBe(true);
    // And they are three DISTINCT addresses: the layer segment is what tells the Worker which
    // archive is meant, and relief and terrain agree on codec, zoom range and tiling scheme.
    expect(new Set(templates).size).toBe(3);
  });

  it("adds no fourth deploy variable — a base nobody supplies falls back to same-origin", () => {
    // The failure mode this closes is the one that shipped 204 pages at /heroes/ on an origin
    // with no heroes: an unset PUBLIC_ base does not error, it silently becomes same-origin.
    // Deriving means there is no new base to leave unset.
    //
    // Matched on the `import.meta.env` READ rather than on the bare name, because the docstring
    // above explains why there is no such variable — a guard that cannot tell code from prose
    // goes red on its own rationale.
    const source = readFileSync(`${WEB_ROOT}src/lib/assetBase.ts`, "utf8");
    const bases = [...source.matchAll(/import\.meta\.env\.(PUBLIC_\w+)/g)].map((m) => m[1]);
    expect(bases).toEqual(["PUBLIC_HERO_BASE", "PUBLIC_BORDERS_BASE", "PUBLIC_TILE_BASE"]);
  });
});

describe("capsManifestUrl", () => {
  it("keeps Earth's URL byte-for-byte the one every warm browser cache already holds", () => {
    // Spelled out rather than derived from the rule. `/caps/caps.json` has been fetched by this
    // site since before there was a second body, and the empty prefix exists precisely so adding
    // one did not move it. Asserting the rule instead would let the rule change and call it green.
    expect(capsManifestUrl("earth")).toBe("/caps/caps.json");
  });

  it("nests a second body one level in, where its pipeline actually wrote the file", () => {
    expect(capsManifestUrl("mars")).toBe("/caps/mars/caps.json");
  });

  it("gives every body a DIFFERENT manifest, which is the failure worth catching", () => {
    // The bug this replaces was a literal `/caps/caps.json` inside addPolarCaps. Note what it was
    // NOT: a 404. Earth's prefix is empty, so any body whose address collapsed toward Earth's gets
    // Earth's manifest with a 200, parses it, and draws Greenland and Arctic sea ice over another
    // planet's pole — correctly sized, correctly feathered, and silent. So a builder that ignored
    // its argument would satisfy both assertions above and still be the original defect.
    const urls = SLUGS.map(capsManifestUrl);
    expect(new Set(urls).size).toBe(urls.length);
  });

  it("does not ride a PUBLIC_ base, because the caps ship inside the build", () => {
    // The three pyramids move to object storage on deploy; ~17 MB of WebP does not. Were this to
    // acquire a base, an unsupplied one would fall back to same-origin and look fine in dev while
    // production served a capless globe — the exact shape the deploy-variable test above guards.
    for (const slug of SLUGS) expect(capsManifestUrl(slug).startsWith("/caps/")).toBe(true);
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
