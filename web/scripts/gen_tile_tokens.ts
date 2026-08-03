#!/usr/bin/env node
// Compute each published archive's cache-busting token from the bytes it serves.
//
// The token is a prefix of the archive's SHA-256, and it is the segment of a tile URL that makes a
// re-cut visible to a browser holding a year-long `immutable` copy of the old tiles. It is
// COMMITTED rather than computed at build time, for two reasons: the site would otherwise refuse to
// build on a checkout without ~6 GB of archives, and the line that changes which bytes production
// serves deserves to be a line someone can see in a diff.
//
//   node scripts/gen_tile_tokens.ts             # check the committed tokens against the archives
//   node scripts/gen_tile_tokens.ts --write     # recompute and rewrite them
//
// WHY THE ARCHIVE AND NOT ITS RECIPE. Every cut writes a recipe sidecar beside its output, and
// hashing that was the first design. It fails on the case that matters most: `tile_params.json`
// records format, quality and zoom range, so a look change re-shades the composite and re-cuts every
// tile while leaving that file byte-identical. The token would hold still through exactly the re-cut
// it exists to announce. Bytes cannot misdescribe themselves.
//
// WHAT THIS DOES NOT PROVE. It proves the token names the local cut. That the R2 object holds those
// same bytes is a separate question, answered at upload time by reconstructing the multipart ETag.
//
// WHY IT READS THE TOKENS FILE INSTEAD OF IMPORTING THE REGISTRY. `node` strips types but does not
// resolve extensionless imports, and `tileAddress.ts` imports three contract modules that way. The
// binding that matters — that this file lists exactly the archives the registry publishes, with no
// placeholders left — is asserted in `tileAddress.test.ts`, where it runs on every suite.

import { createHash } from "node:crypto";
import { createReadStream, existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { archivePath, resolveDataRoot } from "../src/lib/devStores.ts";
import type { BodySlug } from "../src/lib/bodies.ts";
import type { LayerId } from "../src/lib/tileAddress.ts";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..");
// Beside the module that reads it, not in src/data/ — the repo's root `data/` ignore pattern is
// unanchored and matches any directory of that name, so a committed file cannot live there.
const TOKENS_FILE = path.join(WEB_ROOT, "src/lib/tileTokens.json");

/** Hex characters kept. Restated from `TOKEN_LENGTH` in tileAddress.ts, which cannot be imported
 *  here; `tileAddress.test.ts` asserts every committed token is that long, so a drift between the
 *  two is one red test rather than a URL the parser silently refuses. */
const TOKEN_LENGTH = 8;

type TokenFile = Record<string, Record<string, string>>;

/** Read `web/.env` the way the dev config does, so one machine resolves one data store. Node's own
 *  parser rather than Vite's `loadEnv`: this is a script, not a build. */
function loadEnvironment(): Record<string, string | undefined> {
  const envFile = path.join(WEB_ROOT, ".env");
  if (existsSync(envFile)) process.loadEnvFile(envFile);
  return process.env;
}

async function tokenFor(archive: string): Promise<string> {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(archive)) hash.update(chunk as Buffer);
  return hash.digest("hex").slice(0, TOKEN_LENGTH);
}

const write = process.argv.includes("--write");
const committed = JSON.parse(readFileSync(TOKENS_FILE, "utf8")) as TokenFile;
const dataRoot = resolveDataRoot(loadEnvironment(), REPO_ROOT);

const computed: TokenFile = {};
const drifted: string[] = [];
const missing: string[] = [];

for (const [body, layers] of Object.entries(committed)) {
  for (const layer of Object.keys(layers)) {
    const archive = archivePath(dataRoot, body as BodySlug, layer as LayerId);
    if (!existsSync(archive)) {
      missing.push(`${body}/${layer}: no archive at ${archive}`);
      // Carried through unchanged rather than dropped: a machine that holds one body's archives
      // must not silently delete another body's tokens from the committed file.
      (computed[body] ??= {})[layer] = layers[layer];
      continue;
    }
    const token = await tokenFor(archive);
    (computed[body] ??= {})[layer] = token;
    if (layers[layer] !== token) {
      drifted.push(`${body}/${layer}: committed ${layers[layer]}, archive hashes to ${token}`);
    }
  }
}

if (missing.length) {
  // Not a failure — a checkout may hold one body's archives and not another's. Said out loud
  // because silence would make an unchecked pair look checked.
  console.warn(`⚠ ${missing.length} archive(s) not on this machine, token left as committed:`);
  for (const line of missing) console.warn(`  ${line}`);
}

if (write) {
  writeFileSync(TOKENS_FILE, `${JSON.stringify(computed, null, 2)}\n`, "utf8");
  console.info(`✓ wrote ${path.relative(WEB_ROOT, TOKENS_FILE)}`);
  process.exit(0);
}

if (drifted.length) {
  console.error(`✗ ${drifted.length} token(s) do not name the archive they are committed against:`);
  for (const line of drifted) console.error(`  ${line}`);
  console.error("");
  console.error("  A stale token means production would serve new bytes at an old URL — and tiles");
  console.error("  are cached `immutable` for a year, so every browser holding the old ones keeps");
  console.error("  them. Run `node scripts/gen_tile_tokens.ts --write` and commit the result.");
  process.exit(1);
}

const checked = Object.entries(committed).reduce(
  (count, [, layers]) => count + Object.keys(layers).length,
  0,
);
console.info(`✓ ${checked - missing.length} tile token(s) match the archives they name`);
