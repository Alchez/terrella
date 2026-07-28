#!/usr/bin/env node
// Deploy preflight: does R2 actually hold everything the manifest is about to promise?
//
// The gallery manifest (src/data/countries.json) is generated from the LOCAL render store —
// which hero variants exist on this disk, at which sizes. The heroes themselves are served
// from R2. Nothing else checks that those two agree, and they can diverge silently in both
// directions:
//
//   - rendered locally, never uploaded     -> pages promise files that 404
//   - uploaded, manifest never regenerated -> new variants exist and nothing references them
//
// The first is a broken site with no error anywhere in the build. This runs before the
// upload, because that is the moment the divergence becomes public.
//
// TypeScript rather than plain JS for one reason worth the extra ceremony: the `Manifest`
// type below is the SAME declaration the pages consume, so if the manifest contract changes
// under this script, `astro check` fails in CI instead of the deploy throwing later. Node
// strips the types at run time (24.x, no loader), and web/tsconfig.json already covers
// scripts/ — this file needs no build step and no config of its own.
//
// Presence only. Phase 2 verified integrity by reconstructing multipart ETags; re-checking
// bytes here would cost minutes to catch a failure mode that has never occurred.

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
// Type-only: erased at run time, so this does NOT pull in the gitignored countries.json that
// manifest.ts imports for its value export.
import type { Manifest } from "../src/lib/manifest";

const WEB_ROOT = fileURLToPath(new URL("../", import.meta.url));
const MANIFEST = `${WEB_ROOT}src/data/countries.json`;
const BUCKET = "terrella-assets";
const GEOJSON = ["borders/countries.geojson", "borders/boundary_lines.geojson"];

/** Exits; typed `never` so callers are not treated as possibly falling through. */
function fail(...lines: string[]): never {
  console.error(`\n✗ deploy preflight: ${lines[0]}`);
  for (const line of lines.slice(1)) console.error(`  ${line}`);
  console.error("");
  process.exit(1);
}

/** Machine-specific R2 coordinates live in web/.env, never in the repo — the account ID is
 *  part of the endpoint and this repo is going open-source. */
function r2Endpoint(): string {
  if (existsSync(`${WEB_ROOT}.env`)) process.loadEnvFile(`${WEB_ROOT}.env`);
  const endpoint = process.env.R2_ENDPOINT?.trim();
  if (!endpoint) {
    fail(
      "R2_ENDPOINT is not set.",
      "Add it to web/.env (see .env.example). It is machine-specific and gitignored,",
      "because the account ID is part of the URL.",
    );
  }
  return endpoint;
}

/** Every object the built site will reference, derived from the same fields the pages use —
 *  which is what makes the shared `Manifest` type load-bearing rather than decorative. */
function advertisedObjects(manifest: Manifest): Set<string> {
  const keys = new Set<string>(GEOJSON);
  for (const country of manifest.countries) {
    const { slug, sizes, borderSizes, spotlightSizes } = country;
    for (const size of sizes) keys.add(`heroes/${slug}-${size}.webp`);
    for (const size of borderSizes) keys.add(`heroes/${slug}-border-${size}.png`);
    for (const size of spotlightSizes) keys.add(`heroes/${slug}-spotlight-${size}.webp`);
  }
  return keys;
}

function listBucket(endpoint: string): Set<string> {
  try {
    const stdout = execFileSync(
      "aws",
      [
        "s3api", "list-objects-v2",
        "--bucket", BUCKET,
        "--endpoint-url", endpoint,
        "--profile", "r2",
        "--query", "Contents[].Key",
        "--output", "json",
      ],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
    );
    return new Set<string>(JSON.parse(stdout) ?? []);
  } catch (error) {
    // Deliberately not a silent skip: an unreachable bucket must not read as "all present".
    const detail = error instanceof Error ? error.message : String(error);
    const stderr = (error as { stderr?: Buffer | string }).stderr?.toString() ?? "";
    fail(
      `could not list s3://${BUCKET}/.`,
      (stderr || detail).trim().split("\n").pop() ?? "",
      "Check the `r2` profile in ~/.aws/credentials and R2_ENDPOINT in web/.env.",
      "To deploy anyway (code-only change, or R2 unreachable): SKIP_ASSET_SYNC_CHECK=1",
    );
  }
}

/**
 * Refuse to deploy a globe that would request terrain nothing serves.
 *
 * Terrain rides on the `full` tier as of Tier 3 step 4, so a promoted visitor's map adds a
 * `raster-dem` source pointing at `/terrain/...`. In DEV that path is answered by a Vite
 * middleware reading loose tiles off the render store. **In production nothing answers it** —
 * neither wrangler config routes it, and the tile Worker binds only the relief archive. Every DEM
 * tile would 404, forever, with the globe still rendering (flat) and no error surfaced to anyone.
 *
 * That is precisely the failure class this script exists for, and it is invisible to the object
 * check below because the terrain archive is not in the manifest — the manifest describes heroes
 * and borders, so "all advertised objects present" would report a clean deploy either way.
 *
 * The test is deliberately on the WORKER SOURCE rather than on R2: the archive existing in a
 * bucket is worth nothing until something routes `/terrain/` at it. When step 3 lands this stops
 * firing on its own.
 */
function checkTerrainHasAnOrigin(): void {
  const globe = readFileSync(`${WEB_ROOT}src/pages/globe.astro`, "utf8");
  const ridesOnTier = /resolveTerrainExaggeration\([\s\S]{0,80}?currentTier\(\)\s*===\s*"full"/.test(
    globe,
  );
  if (!ridesOnTier) return;

  const worker = readFileSync(`${WEB_ROOT}worker/index.ts`, "utf8");
  const workerConfig = readFileSync(`${WEB_ROOT}worker/wrangler.jsonc`, "utf8");
  const served = worker.includes("/terrain/") || workerConfig.includes("terrain.pmtiles");
  if (served) return;

  fail(
    "the globe would request terrain that production cannot serve.",
    "",
    "  globe.astro enables terrain on the `full` tier, so a promoted visitor adds a raster-dem",
    "  source at /terrain/<build>/{z}/{x}/{y}.webp. The dev server answers that from loose tiles;",
    "  the tile Worker does not route it at all, so every DEM tile would 404 silently — the globe",
    "  still renders, just flat, and nothing reports it.",
    "",
    "  Land Tier 3 step 3 (pack terrain.pmtiles, bind it in worker/wrangler.jsonc, route /terrain/",
    "  in worker/index.ts), or gate terrain off the tier again before deploying.",
  );
}

function main(): void {
  if (process.env.SKIP_ASSET_SYNC_CHECK === "1") {
    console.warn("⚠ deploy preflight SKIPPED via SKIP_ASSET_SYNC_CHECK=1 — assets unverified");
    return;
  }
  if (!existsSync(MANIFEST)) {
    fail(
      "src/data/countries.json is missing.",
      "It is generated from the render store and gitignored, so a fresh checkout has none.",
      "Regenerate with scripts/gen_manifest.py (see docs/pipeline.md) before deploying.",
    );
  }

  checkTerrainHasAnOrigin();

  const manifest = JSON.parse(readFileSync(MANIFEST, "utf8")) as Manifest;
  const advertised = advertisedObjects(manifest);
  const present = listBucket(r2Endpoint());

  const missing = [...advertised].filter((key) => !present.has(key)).sort();
  const dead = [...present].filter((key) => !advertised.has(key) && !key.endsWith("/")).sort();

  if (dead.length) {
    // Not fatal — stale bytes cost storage, not correctness. Loud anyway, because the usual
    // cause is a manifest that was never regenerated after a render, i.e. work that silently
    // did not ship.
    console.warn(`\n⚠ ${dead.length} object(s) in R2 that nothing references:`);
    for (const key of dead.slice(0, 10)) console.warn(`    ${key}`);
    if (dead.length > 10) console.warn(`    …and ${dead.length - 10} more`);
    console.warn("  Usually means the manifest was not regenerated after a render.\n");
  }

  if (missing.length) {
    console.error(`\n✗ deploy preflight: ${missing.length} object(s) the site would 404 on:`);
    for (const key of missing.slice(0, 20)) console.error(`    ${key}`);
    if (missing.length > 20) console.error(`    …and ${missing.length - 20} more`);
    console.error("\n  The manifest promises these; R2 does not have them. Upload the render");
    console.error("  store to R2, or regenerate the manifest to match what is uploaded.\n");
    process.exit(1);
  }

  console.log(`✓ deploy preflight: ${advertised.size} objects advertised, all present in R2`);
}

main();
