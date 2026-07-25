#!/usr/bin/env node
// Deploy preflight: does R2 actually hold everything the manifest is about to promise?
//
// The gallery manifest (src/data/countries.json) is generated from the LOCAL render store —
// which hero variants exist on this disk, at which sizes. The heroes themselves are served
// from R2. Nothing has ever checked that those two agree, and they can diverge silently in
// both directions:
//
//   - rendered locally, never uploaded  -> the site ships pages promising files that 404
//   - uploaded, manifest never regenerated -> new variants exist and nothing references them
//
// The first is a broken site with no error anywhere in the build. This runs before the
// upload, because that is the moment the divergence becomes public.
//
// Presence only. Phase 2 verified integrity by reconstructing multipart ETags; re-checking
// bytes here would cost minutes to catch a failure mode that has never occurred.

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const WEB_ROOT = fileURLToPath(new URL("../", import.meta.url));
const MANIFEST = `${WEB_ROOT}src/data/countries.json`;
const BUCKET = "terrella-assets";
const GEOJSON = ["borders/countries.geojson", "borders/boundary_lines.geojson"];

/** Machine-specific R2 coordinates live in web/.env, never in the repo — the account ID is
 *  part of the endpoint and this repo is going open-source. */
function r2Endpoint() {
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

function fail(...lines) {
  console.error(`\n✗ deploy preflight: ${lines[0]}`);
  for (const line of lines.slice(1)) console.error(`  ${line}`);
  console.error("");
  process.exit(1);
}

/** Every object the built site will reference, derived the same way the pages derive it. */
function advertisedObjects(manifest) {
  const keys = new Set(GEOJSON);
  for (const country of manifest.countries) {
    const { slug, sizes, borderSizes, spotlightSizes } = country;
    for (const size of sizes) keys.add(`heroes/${slug}-${size}.webp`);
    for (const size of borderSizes) keys.add(`heroes/${slug}-border-${size}.png`);
    for (const size of spotlightSizes) keys.add(`heroes/${slug}-spotlight-${size}.webp`);
  }
  return keys;
}

function listBucket(endpoint) {
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
    return new Set(JSON.parse(stdout) ?? []);
  } catch (error) {
    // Deliberately not a silent skip: an unreachable bucket must not read as "all present".
    fail(
      `could not list s3://${BUCKET}/.`,
      `${(error.stderr || error.message || "").toString().trim().split("\n").pop()}`,
      "Check the `r2` profile in ~/.aws/credentials and R2_ENDPOINT in web/.env.",
      "To deploy anyway (code-only change, or R2 unreachable): SKIP_ASSET_SYNC_CHECK=1",
    );
  }
}

function main() {
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

  const advertised = advertisedObjects(JSON.parse(readFileSync(MANIFEST, "utf8")));
  const present = listBucket(r2Endpoint());

  const missing = [...advertised].filter((key) => !present.has(key)).sort();
  const dead = [...present]
    .filter((key) => !advertised.has(key) && !key.endsWith("/"))
    .sort();

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
