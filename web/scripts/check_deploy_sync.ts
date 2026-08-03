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
const ARCHIVE_BUCKET = "terrella-tiles";
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

function listBucket(endpoint: string, bucket: string = BUCKET): Set<string> {
  try {
    const stdout = execFileSync(
      "aws",
      [
        "s3api", "list-objects-v2",
        "--bucket", bucket,
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
      `could not list s3://${bucket}/.`,
      (stderr || detail).trim().split("\n").pop() ?? "",
      "Check the `r2` profile in ~/.aws/credentials and R2_ENDPOINT in web/.env.",
      "To deploy anyway (code-only change, or R2 unreachable): SKIP_ASSET_SYNC_CHECK=1",
    );
  }
}

/** Every archive object key the tile Worker will ask R2 for, read out of its own config so this
 *  cannot drift from what actually ships. Returns the KEYS, so the caller can say which is
 *  missing rather than merely that something is.
 *
 *  Parsed with a regex rather than by importing the config: wrangler.jsonc is JSONC (the file is
 *  more comment than setting), and a JSON parser would reject it. */
function workerArchiveKeys(workerConfig: string): { name: string; key: string }[] {
  const keys: { name: string; key: string }[] = [];
  for (const name of ["ARCHIVE_KEY", "TERRAIN_ARCHIVE_KEY"]) {
    const match = new RegExp(String.raw`"${name}"\s*:\s*"([^"]+)"`).exec(workerConfig);
    if (match) keys.push({ name, key: match[1] });
  }
  return keys;
}

/**
 * Refuse to deploy a globe that would request terrain nothing serves.
 *
 * Terrain rides on the `full` tier as of Tier 3 step 4, so a promoted visitor's map adds a
 * `raster-dem` source pointing at `/terrain/...`. Every DEM tile 404ing is invisible: the globe
 * still renders, just flat, and nothing reports it. It is also invisible to the object check
 * below, because the archives are not in the manifest — the manifest describes heroes and
 * borders, so "all advertised objects present" would report a clean deploy either way.
 *
 * TWO SEPARATE THINGS HAVE TO BE TRUE and each fails silently on its own: the Worker must ROUTE
 * `/terrain/`, and the bucket must HOLD the object that route names. Checking only the source
 * (which is all this could do before step 3) would pass on a Worker that routes perfectly at an
 * object nobody uploaded.
 */
function checkTerrainHasAnOrigin(endpoint: string): void {
  const globe = readFileSync(`${WEB_ROOT}src/pages/earth.astro`, "utf8");
  const ridesOnTier = /resolveTerrainExaggeration\([\s\S]{0,80}?currentTier\(\)\s*===\s*"full"/.test(
    globe,
  );
  if (!ridesOnTier) return;

  const worker = readFileSync(`${WEB_ROOT}worker/index.ts`, "utf8");
  const workerConfig = readFileSync(`${WEB_ROOT}worker/wrangler.jsonc`, "utf8");
  if (!worker.includes("parseTerrainTilePath")) {
    fail(
      "the globe would request terrain that production cannot serve.",
      "",
      "  earth.astro enables terrain on the `full` tier, so a promoted visitor adds a raster-dem",
      "  source at /terrain/{z}/{x}/{y}.webp — and worker/index.ts does not route that path, so",
      "  every DEM tile would 404 silently.",
      "",
      "  Route it in worker/index.ts, or gate terrain off the tier again before deploying.",
    );
  }

  // Both archives, not just terrain's: nothing has ever checked that the RELIEF archive the
  // Worker names is present either, and the failure is the same shape — a live site whose every
  // tile 404s, discovered by looking rather than by any check.
  const declared = workerArchiveKeys(workerConfig);
  if (!declared.some(({ name }) => name === "TERRAIN_ARCHIVE_KEY")) {
    fail(
      "worker/wrangler.jsonc names no TERRAIN_ARCHIVE_KEY.",
      "  The Worker falls back to a default key, which is a silent way to serve nothing.",
      "  Add it to the `vars` block, pointing at the uploaded terrain archive.",
    );
  }
  const present = listBucket(endpoint, ARCHIVE_BUCKET);
  const absent = declared.filter(({ key }) => !present.has(key));
  if (absent.length) {
    fail(
      `${absent.length} archive(s) the tile Worker names are not in s3://${ARCHIVE_BUCKET}/.`,
      ...absent.map(({ name, key }) => `  ${name} = ${key}`),
      "",
      "  Upload them before deploying — the Worker would answer every tile with a 404 and the",
      "  globe would render flat, with no error anywhere.",
    );
  }
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

  const endpoint = r2Endpoint();
  checkTerrainHasAnOrigin(endpoint);

  const manifest = JSON.parse(readFileSync(MANIFEST, "utf8")) as Manifest;
  const advertised = advertisedObjects(manifest);
  const present = listBucket(endpoint);

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
