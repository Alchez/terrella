#!/usr/bin/env node
// Compute, from the bytes each published archive actually serves, the two facts about it that no
// other file can derive: its cache-busting TOKEN, and how many directory-cache entries it occupies.
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
// WHY THE LEAF COUNT IS HERE TOO. The tile Worker holds resolved PMTiles directories in one
// module-scope cache, and that cache must be big enough for every archive at once or a body switch
// evicts on alternating requests. Its size is now DERIVED from these counts rather than hand-tallied
// — which is worth doing because the hand tally was wrong: terrain was recorded as 21 leaves and has
// 22. Being one short costs a gunzip per tile and nothing else, so nothing would ever have said so.
//
// WHY IT READS THE TOKENS FILE INSTEAD OF IMPORTING THE REGISTRY. `node` strips types but does not
// resolve extensionless imports, and `tileAddress.ts` imports three contract modules that way. The
// binding that matters — that this file lists exactly the archives the registry publishes, with no
// placeholders left — is asserted in `tileAddress.test.ts`, where it runs on every suite.

import { createHash } from "node:crypto";
import { createReadStream, existsSync, readFileSync, writeFileSync } from "node:fs";
import { open } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";
import { bytesToHeader, readVarint } from "pmtiles";

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

/** What is recorded per archive. Both fields are read off the bytes; neither is a judgement. */
interface ArchiveFacts {
  token: string;
  /** Leaf directories in the archive — the third term in its directory-cache cost, after the
   *  header entry and the root entry. See `directoryCacheEntries` in worker/index.ts. */
  indexLeaves: number;
}

type TokenFile = Record<string, Record<string, ArchiveFacts>>;

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

/** Count an archive's leaf directories, which is how many entries past the first two it can occupy
 *  in the Worker's directory cache.
 *
 *  A PMTiles root directory holds one entry per child; an entry with `runLength === 0` is a POINTER
 *  to a leaf directory rather than to a tile, so counting those zeros counts the leaves. Read off
 *  the archive's own front rather than estimated from its size — the ratio of leaves to tiles is a
 *  property of how the cut clustered, not of how big it is.
 *
 *  The varint walk is hand-rolled because `pmtiles` does not export `deserializeIndex`, only the
 *  `readVarint` primitive it is built from. It reads the two arrays it needs and stops: the entry
 *  count, the tile-id deltas it skips, then the run lengths. Going through `PMTiles` instead would
 *  mean reaching into a `ResolvedValueCache`'s private Map to see what it happened to store. */
async function indexLeavesIn(archive: string): Promise<number> {
  const handle = await open(archive, "r");
  try {
    const front = Buffer.alloc(16_384);
    await handle.read(front, 0, front.length, 0);
    const header = bytesToHeader(front.buffer.slice(0, 127) as ArrayBuffer, undefined);
    const rootBytes = Buffer.alloc(header.rootDirectoryLength);
    await handle.read(rootBytes, 0, rootBytes.length, header.rootDirectoryOffset);
    // 1 = no compression, 2 = gzip. Anything else and the count would be silently wrong, which is
    // the one outcome this whole exercise exists to avoid.
    if (header.internalCompression !== 1 && header.internalCompression !== 2) {
      throw new Error(
        `${archive}: internalCompression ${header.internalCompression} is not one this script reads`,
      );
    }
    const plain =
      header.internalCompression === 2 ? gunzipSync(rootBytes) : new Uint8Array(rootBytes);
    const cursor = { buf: new Uint8Array(plain), pos: 0 };
    const entries = readVarint(cursor);
    for (let index = 0; index < entries; index++) readVarint(cursor); // tile-id deltas, unused
    let leaves = 0;
    for (let index = 0; index < entries; index++) if (readVarint(cursor) === 0) leaves++;
    return leaves;
  } finally {
    await handle.close();
  }
}

const write = process.argv.includes("--write");
const committed = JSON.parse(readFileSync(TOKENS_FILE, "utf8")) as TokenFile;
const dataRoot = resolveDataRoot(loadEnvironment(), REPO_ROOT);

const computed: TokenFile = {};
const drifted: string[] = [];
const missing: string[] = [];

for (const [body, layers] of Object.entries(committed)) {
  for (const [layer, recorded] of Object.entries(layers)) {
    const archive = archivePath(dataRoot, body as BodySlug, layer as LayerId);
    if (!existsSync(archive)) {
      missing.push(`${body}/${layer}: no archive at ${archive}`);
      // Carried through unchanged rather than dropped: a machine that holds one body's archives
      // must not silently delete another body's facts from the committed file.
      (computed[body] ??= {})[layer] = recorded;
      continue;
    }
    // Sequential ON PURPOSE, and the rule is right that this is usually a mistake. `tokenFor`
    // streams an entire PMTiles archive through SHA-256 — relief alone is gigabytes — so awaiting
    // one body/layer at a time is what keeps a single heavy read in flight. Running them
    // concurrently would put several GB-scale sequential reads on the same device to finish no
    // sooner, which is the pipeline's one-heavy-job-at-a-time rule stated in TypeScript.
    /* oxlint-disable no-await-in-loop */
    const facts: ArchiveFacts = {
      token: await tokenFor(archive),
      indexLeaves: await indexLeavesIn(archive),
    };
    /* oxlint-enable no-await-in-loop */
    (computed[body] ??= {})[layer] = facts;
    if (recorded.token !== facts.token) {
      drifted.push(`${body}/${layer}: committed ${recorded.token}, archive hashes to ${facts.token}`);
    }
    if (recorded.indexLeaves !== facts.indexLeaves) {
      // Its own line, because the consequence is different in kind: a stale TOKEN serves the wrong
      // bytes, a stale LEAF COUNT undersizes a cache and only costs time.
      drifted.push(
        `${body}/${layer}: committed ${recorded.indexLeaves} leaves, archive has ${facts.indexLeaves}`,
      );
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
  console.error(`✗ ${drifted.length} recorded fact(s) do not match the archive they name:`);
  for (const line of drifted) console.error(`  ${line}`);
  console.error("");
  console.error("  A stale token means production would serve new bytes at an old URL — and tiles");
  console.error("  are cached `immutable` for a year, so every browser holding the old ones keeps");
  console.error("  them. A stale leaf count undersizes the Worker's directory cache, which costs a");
  console.error("  gunzip per tile and reports nothing at all.");
  console.error("  Run `node scripts/gen_tile_tokens.ts --write` and commit the result.");
  process.exit(1);
}

const checked = Object.entries(committed).reduce(
  (count, [, layers]) => count + Object.keys(layers).length,
  0,
);
console.info(`✓ ${checked - missing.length} archive(s) match the token and leaf count recorded for them`);
