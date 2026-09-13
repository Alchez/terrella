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
// Sizes, not contents: the listing reports each object's size at no extra cost, and a download
// file uploaded before its stamp is the same key at another size, which presence alone passes.

import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
// Type-only: erased at run time, so this does NOT pull in the gitignored countries.json that
// manifest.ts imports for its value export, nor the imports archiveIndex.ts makes.
import type { BundleRecord } from "../src/lib/archiveIndex";
import type { Manifest } from "../src/lib/manifest";
import {
  ARCHIVE_BUCKET,
  ASSET_BUCKET,
  HERO_PREFIX,
  R2Unreachable,
  listBucket,
  r2Endpoint,
  type Listing,
} from "./r2.ts";

const WEB_ROOT = fileURLToPath(new URL("../", import.meta.url));
const MANIFEST = `${WEB_ROOT}src/data/countries.json`;
const BUNDLES = `${WEB_ROOT}src/data/downloads.json`;
const GEOJSON = ["borders/countries.geojson", "borders/boundary_lines.geojson"];

/** Exits; typed `never` so callers are not treated as possibly falling through. */
function fail(...lines: string[]): never {
  console.error(`\n✗ deploy preflight: ${lines[0]}`);
  for (const line of lines.slice(1)) console.error(`  ${line}`);
  console.error("");
  process.exit(1);
}

/** Every object the built site will reference, derived from the same fields the pages use —
 *  which is what makes the shared `Manifest` type load-bearing rather than decorative. */
export function advertisedObjects(manifest: Manifest): Set<string> {
  const keys = new Set<string>(GEOJSON);
  for (const country of manifest.countries) {
    const { slug, sizes, spotlightSizes } = country;
    for (const size of sizes) keys.add(`${HERO_PREFIX}${slug}-${size}.webp`);
    for (const size of spotlightSizes) keys.add(`${HERO_PREFIX}${slug}-spotlight-${size}.webp`);
  }
  const { webp, png } = downloadFiles(manifest);
  for (const name of [...webp.keys(), ...png.keys()]) keys.add(`${HERO_PREFIX}${name}`);
  return keys;
}

/** Each rendered country's two download files, named as the store names them, with the bytes the
 *  manifest records for each. */
function downloadFiles(manifest: Manifest): { webp: Map<string, number>; png: Map<string, number> } {
  const webp = new Map<string, number>();
  const png = new Map<string, number>();
  for (const { slug, native, download } of manifest.countries) {
    if (!download) continue;
    webp.set(`${slug}-${native}.webp`, download.webpBytes);
    png.set(`${slug}-${native}.png`, download.pngBytes);
  }
  return { webp, png };
}

/** Every download file R2 holds at another size than the manifest records. One R2 lacks is the
 *  missing list's to report. */
export function downloadSizeMismatches(manifest: Manifest, present: Listing): string[] {
  const { webp, png } = downloadFiles(manifest);
  return [...webp, ...png].flatMap(([name, recorded]) => {
    const held = present.get(`${HERO_PREFIX}${name}`);
    return held === undefined || held === recorded
      ? []
      : [`${HERO_PREFIX}${name}: ${held} bytes in R2, ${recorded} in the manifest`];
  });
}

/** What keeps the bundle the Archives page offers from being what it says: absent from the
 *  archive bucket, uploaded at another size than its record, or holding other images than the
 *  pages offer, as a bundle not rebuilt after a render does. */
export function bundleProblems(bundle: BundleRecord, manifest: Manifest, archives: Listing): string[] {
  const problems: string[] = [];
  const held = archives.get(bundle.key);
  if (held === undefined) problems.push(`${bundle.key} is not in s3://${ARCHIVE_BUCKET}/`);
  else if (held !== bundle.bytes) {
    problems.push(`${bundle.key}: ${held} bytes in s3://${ARCHIVE_BUCKET}/, ${bundle.bytes} in its record`);
  }
  const offered = downloadFiles(manifest).webp;
  const bundled = new Map(Object.entries(bundle.images));
  for (const [name, recorded] of offered) {
    const size = bundled.get(name);
    if (size === undefined) problems.push(`the bundle lacks ${name}`);
    else if (size !== recorded) problems.push(`the bundle's ${name} is ${size} bytes, the page's ${recorded}`);
  }
  for (const name of bundled.keys()) {
    if (!offered.has(name)) problems.push(`the bundle holds ${name}, which no page offers`);
  }
  return problems;
}

/** Every archive object key the registry publishes, across all bodies and all layers.
 *
 *  THE REGISTRY, NOT THE WORKER'S CONFIG. This used to read `wrangler.jsonc` for two named
 *  variables, which meant the COUNTRY archive was never checked at all — a third pyramid arrived
 *  and the preflight kept reporting a clean deploy without ever asking whether its object existed.
 *  Enumerating instead of naming is what stops that recurring: a fourth archive is checked the day
 *  it is published, by a script nobody edited.
 *
 *  Read as SOURCE rather than imported, for the reason stated at the terrain check below: this is
 *  plain node, which strips types but does not resolve the extensionless imports the app's modules
 *  use. Presence is all this needs, so a flat list of quoted keys is enough — no part of the check
 *  depends on knowing which body or layer a key belongs to, which is what keeps a regex honest
 *  here. `tileAddress.test.ts` pins this parse against the real registry from the other side. */
function publishedArchiveKeys(registry: string): string[] {
  return [...registry.matchAll(/objectKey:\s*"([^"]+)"/g)].map((match) => match[1]);
}

/**
 * Refuse to deploy while any archive the site will address is missing from the bucket.
 *
 * Unconditional, unlike the terrain check below, and that is the point: relief and the country
 * pyramid are not gated on a tier, so a gap in either is a live site whose every tile 404s. The
 * globe still renders — grey sphere, or flat, or without borders — and nothing reports it.
 *
 * Superseded archives are deliberately NOT reported as dead objects here. The convention is that a
 * re-cut ships under a new key and the old object is deleted only once the new one is verified
 * live, so an "unreferenced archive" warning would fire on purpose during every rollout.
 */
function checkEveryPublishedArchiveIsUploaded(present: Listing): void {
  const registry = readFileSync(`${WEB_ROOT}src/lib/tileAddress.ts`, "utf8");
  const keys = publishedArchiveKeys(registry);
  if (keys.length === 0) {
    // A parse that finds nothing would otherwise report a perfect deploy. The registry is never
    // empty — a site that publishes no pyramid has no globe.
    fail(
      "found no published archives in src/lib/tileAddress.ts.",
      "  Either PUBLISHED is empty, or the shape this script parses has changed and it is now",
      "  checking nothing at all. It must not be possible to deploy on a vacuous check.",
    );
  }
  const absent = keys.filter((key) => !present.has(key));
  if (absent.length) {
    fail(
      `${absent.length} archive(s) the registry publishes are not in s3://${ARCHIVE_BUCKET}/.`,
      ...absent.map((key) => `  ${key}`),
      "",
      "  Upload them before deploying — the Worker would answer every tile from those pyramids",
      "  with a 404, and the globe would render without them rather than fail.",
    );
  }
}

/** Refuse to deploy while the bundle the Archives page offers is not the one its record describes
 *  or holds other images than the pages offer. The manifest's countries are Earth's, so the bundle
 *  held to them is Earth's. */
function checkTheBundle(manifest: Manifest, archives: Listing): void {
  const { earth } = JSON.parse(readFileSync(BUNDLES, "utf8")) as Partial<Record<string, BundleRecord>>;
  if (!earth) {
    fail(
      "src/data/downloads.json records no bundle for Earth.",
      "  Write it with `python -m pipeline.compose.downloads bundle`.",
    );
  }
  const problems = bundleProblems(earth, manifest, archives);
  if (problems.length) {
    fail(
      "the country maps bundle is not the one the Archives page describes.",
      ...problems.map((problem) => `  ${problem}`),
      "",
      "  Rebuild it with `python -m pipeline.compose.downloads bundle` if its images differ from",
      "  the pages', then upload it.",
    );
  }
}

/**
 * Refuse to deploy a globe that would request terrain nothing serves.
 *
 * Terrain rides on the `full` tier as of Tier 3 step 4, so a promoted visitor's map adds a
 * `raster-dem` source pointing at `/terrain/...`. Every DEM tile 404ing is invisible: the globe
 * still renders, just flat, and nothing reports it. It is also invisible to the object check
 * below, because the archives are not in the manifest: the manifest describes heroes, so "all
 * advertised objects present" would report a clean deploy either way.
 *
 * THE OBJECT HALF NOW LIVES ABOVE, in the unconditional archive check — it is not terrain-specific
 * and never was. What is left here is the half that genuinely is: whether the ROUTE exists at all,
 * which only matters while terrain rides a tier.
 */
function checkTerrainIsRoutable(): void {
  const globe = readFileSync(`${WEB_ROOT}src/components/Globe.astro`, "utf8");
  // THE `return` BELOW IS AN EARLY EXIT ON A GREP, so this check is only as alive as the file it
  // reads. Point it at the wrong source, as an extraction very nearly did when the globe's script
  // moved out of Earth's page into this component, and the regex finds nothing, the function
  // returns "nothing to check", and a deploy that 404s every DEM tile sails through reporting
  // clean. So the subject is asserted before the question is asked.
  if (!globe.includes("resolveTerrainExaggeration(")) {
    fail(
      "the deploy preflight cannot find the globe's terrain wiring.",
      "",
      "  This check reads src/components/Globe.astro and greps it for",
      "  `resolveTerrainExaggeration(`. That call is absent, so it has nothing to judge and",
      "  would otherwise pass by finding nothing — which is indistinguishable from terrain being",
      "  safely off.",
      "",
      "  If the globe's script moved again, point this check at its new home. If terrain was",
      "  removed outright, delete this check rather than leaving it looking at a ghost.",
    );
  }
  const ridesOnTier = /resolveTerrainExaggeration\([\s\S]{0,80}?currentTier\(\)\s*===\s*"full"/.test(
    globe,
  );
  if (!ridesOnTier) return;

  const worker = readFileSync(`${WEB_ROOT}worker/index.ts`, "utf8");
  const registry = readFileSync(`${WEB_ROOT}src/lib/tileAddress.ts`, "utf8");
  // TWO GREPS SINCE ROUTING MOVED TO THE REGISTRY: the Worker must dispatch through the shared
  // resolver, and that resolver must have a terrain archive to dispatch AT. Either half alone is
  // satisfiable while terrain 404s — a Worker that resolves nothing, or a registry entry no server
  // reads. Read as source rather than imported because this script is plain node, which does not
  // resolve the extensionless imports the app's modules use.
  const routesTerrain =
    worker.includes("resolveTileRequest") && /terrain:\s*\{[^}]*objectKey/.test(registry);
  if (!routesTerrain) {
    fail(
      "the globe would request terrain that production cannot serve.",
      "",
      "  src/components/Globe.astro enables terrain on the `full` tier, so a promoted visitor adds a",
      "  raster-dem source pointing at the terrain pyramid — and either worker/index.ts does not",
      "  route through resolveTileRequest, or src/lib/tileAddress.ts publishes no terrain archive",
      "  for it to find. Every DEM tile would 404 silently.",
      "",
      "  Fix whichever half is missing, or gate terrain off the tier again before deploying.",
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
  checkTerrainIsRoutable();
  const archives = listBucket(endpoint, ARCHIVE_BUCKET);
  checkEveryPublishedArchiveIsUploaded(archives);

  const manifest = JSON.parse(readFileSync(MANIFEST, "utf8")) as Manifest;
  checkTheBundle(manifest, archives);
  const advertised = advertisedObjects(manifest);
  const present = listBucket(endpoint, ASSET_BUCKET);

  const missing = [...advertised].filter((key) => !present.has(key)).toSorted();
  const dead = [...present.keys()]
    .filter((key) => !advertised.has(key) && !key.endsWith("/"))
    .toSorted();

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

  const resized = downloadSizeMismatches(manifest, present);
  if (resized.length) {
    fail(
      `${resized.length} download file(s) R2 holds at another size than the manifest records:`,
      ...resized.slice(0, 20).map((line) => `  ${line}`),
      ...(resized.length > 20 ? [`  …and ${resized.length - 20} more`] : []),
      "",
      "  Upload them from the render store the manifest was written from. A stamp keeps a file's",
      "  key, so only its size says whether R2 holds the stamped one.",
    );
  }

  console.log(
    `✓ deploy preflight: ${advertised.size} objects advertised, all present in R2, and the ` +
      "download files and the bundle at the sizes recorded",
  );
}

// Only when run, so a test can import the checks above without listing a bucket.
if (import.meta.main) {
  try {
    main();
  } catch (error) {
    if (!(error instanceof R2Unreachable)) throw error;
    fail(...error.lines, "To deploy anyway (code-only change, or R2 unreachable): SKIP_ASSET_SYNC_CHECK=1");
  }
}
