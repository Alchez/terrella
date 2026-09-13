#!/usr/bin/env node
// Upload the files the site offers for download, each marked to save under its own name, and
// check what a visitor is then served.
//
//   node scripts/upload_downloads.ts            # check the store and say what would go up
//   node scripts/upload_downloads.ts --upload   # upload them
//   node scripts/upload_downloads.ts --verify   # read one byte of each public URL
//
// Those are each rendered country's full-size WebP and the PNG copy beside it, and the country
// maps bundle. A plain `s3 sync` uploads a changed one without the header that makes a link save
// it rather than open it, so this runs after any sync of the hero store.
//
// Verify reads one byte through the public host rather than asking R2, because the edge answers
// from its cache: until a purge, it serves the copy from before the upload.

import { execFileSync } from "node:child_process";
import { readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
// Type-only, and so erased at run time, like the preflight's.
import type { BundleRecord } from "../src/lib/archiveIndex";
import type { Manifest } from "../src/lib/manifest";
import {
  ARCHIVE_BUCKET,
  ASSET_BUCKET,
  HERO_PREFIX,
  R2Unreachable,
  r2Endpoint,
  r2Options,
} from "./r2.ts";

const WEB_ROOT = fileURLToPath(new URL("../", import.meta.url));
const RENDERS = fileURLToPath(new URL("../../blender/renders/", import.meta.url));
/** Where `pipeline/compose/downloads.py` writes each kind of file. */
const STORE = { variants: `${RENDERS}variants/`, archives: `${RENDERS}archives/` };

const CONTENT_TYPES: Record<string, string> = {
  webp: "image/webp",
  png: "image/png",
  zip: "application/zip",
};

/** One file to upload: where it is, where it goes, and how it is to be served. */
export interface Upload {
  name: string;
  local: string;
  bucket: string;
  key: string;
  /** The size the manifest or the bundle's record gives, which the file on disk must have. */
  bytes: number;
  contentType: string;
  contentDisposition: string;
  /** Where a visitor downloads it from. */
  url: string;
}

export type Mode = "dry run" | "upload" | "verify";

/** What a run does with the planned files, passed in so a test can see which it reached. */
export interface Actions {
  describe(planned: Upload[]): void;
  upload(planned: Upload[]): void;
  verify(planned: Upload[]): Promise<void>;
}

/** The store's files disagree with the records the site was built from. */
export class StoreMismatch extends Error {}

function uploadOf(name: string, local: string, bucket: string, key: string, bytes: number, url: string): Upload {
  const extension = name.slice(name.lastIndexOf(".") + 1);
  const contentType = CONTENT_TYPES[extension];
  if (!contentType) throw new Error(`${name}: no content type for .${extension}`);
  return {
    name,
    local,
    bucket,
    key,
    bytes,
    contentType,
    contentDisposition: `attachment; filename="${name}"`,
    url,
  };
}

/** Each rendered country's full-size WebP and PNG copy, then the bundle. */
export function plannedUploads(
  manifest: Manifest,
  bundle: BundleRecord,
  bases: { hero: string; archive: string },
  store: { variants: string; archives: string },
): Upload[] {
  const countries = manifest.countries.flatMap(({ slug, native, download }) => {
    if (!download) return [];
    return (
      [
        [`${slug}-${native}.webp`, download.webpBytes],
        [`${slug}-${native}.png`, download.pngBytes],
      ] as const
    ).map(([name, bytes]) =>
      uploadOf(name, `${store.variants.replace(/\/?$/, "/")}${name}`, ASSET_BUCKET,
        `${HERO_PREFIX}${name}`, bytes, `${bases.hero}${name}`),
    );
  });
  const bundleName = bundle.key.slice(bundle.key.lastIndexOf("/") + 1);
  return [
    ...countries,
    uploadOf(bundleName, `${store.archives.replace(/\/?$/, "/")}${bundle.key}`, ARCHIVE_BUCKET,
      bundle.key, bundle.bytes, `${bases.archive}${bundle.key}`),
  ];
}

/** Every planned file the store lacks or holds at another size than its record gives. */
export function localProblems(planned: Upload[], sizeOf: (local: string) => number | undefined): string[] {
  return planned.flatMap((item) => {
    const size = sizeOf(item.local);
    if (size === undefined) return [`${item.name}: not in the store at ${item.local}`];
    return size === item.bytes ? [] : [`${item.name}: ${size} bytes in the store, ${item.bytes} recorded`];
  });
}

/** The `aws` arguments that upload one file with its type and disposition. */
export function copyArguments(item: Upload, endpoint: string): string[] {
  return [
    "s3", "cp", item.local, `s3://${item.bucket}/${item.key}`,
    "--content-type", item.contentType,
    "--content-disposition", item.contentDisposition,
    "--no-progress",
    ...r2Options(endpoint),
  ];
}

/** What is wrong with one byte of a file as the public host served it. */
export function servedProblems(item: Upload, response: { status: number; headers: Headers }): string[] {
  if (response.status !== 206) return [`${item.url}: ${response.status} where one byte was asked for`];
  const problems: string[] = [];
  const total = response.headers.get("content-range")?.split("/")[1];
  if (total !== String(item.bytes)) problems.push(`${item.url}: ${total ?? "no"} bytes, ${item.bytes} recorded`);
  const type = response.headers.get("content-type");
  if (type !== item.contentType) problems.push(`${item.url}: served as ${type}, not ${item.contentType}`);
  const disposition = response.headers.get("content-disposition");
  if (disposition !== item.contentDisposition) {
    problems.push(`${item.url}: disposition ${disposition ?? "missing"}, not ${item.contentDisposition}`);
  }
  return problems;
}

/** A public base as `build:deploy` in package.json sets it for the deployed site. */
export function deployBase(name: string, deployScript: string): string {
  const value = deployScript.match(new RegExp(`\\b${name}=(\\S+)`))?.[1];
  if (!value) throw new Error(`build:deploy sets no ${name}`);
  return value;
}

export function modeOf(argv: string[]): Mode {
  const uploading = argv.includes("--upload");
  const verifying = argv.includes("--verify");
  if (uploading && verifying) throw new Error("--upload and --verify are separate runs: verify after the purge");
  return uploading ? "upload" : verifying ? "verify" : "dry run";
}

/** Verify reads the public side alone; the others hold the store to the records first. */
export async function run(mode: Mode, planned: Upload[], problems: string[], actions: Actions): Promise<void> {
  if (mode === "verify") return actions.verify(planned);
  if (problems.length) {
    throw new StoreMismatch(
      [`${problems.length} file(s) differ from the records the site was built from:`, ...problems].join("\n"),
    );
  }
  if (mode === "upload") actions.upload(planned);
  else actions.describe(planned);
}

function sizeOnDisk(local: string): number | undefined {
  try {
    return statSync(local).size;
  } catch {
    return undefined;
  }
}

/** One byte of `item` through its public host, judged. */
async function servedTo(item: Upload): Promise<string[]> {
  const response = await fetch(item.url, { headers: { Range: "bytes=0-0" } });
  await response.body?.cancel();
  return servedProblems(item, response);
}

function gigabytes(planned: Upload[]): string {
  return `${(planned.reduce((sum, item) => sum + item.bytes, 0) / 1e9).toFixed(2)} GB`;
}

const actions: Actions = {
  describe(planned) {
    for (const [type, group] of Object.entries(Object.groupBy(planned, (item) => item.contentType))) {
      console.log(`  ${group?.length} ${type}, ${gigabytes(group ?? [])}, e.g. ${group?.[0].key}`);
    }
    console.log(`Would upload ${planned.length} files, ${gigabytes(planned)}. Run with --upload.`);
  },
  upload(planned) {
    const endpoint = r2Endpoint();
    planned.forEach((item, index) => {
      console.log(`  [${index + 1}/${planned.length}] s3://${item.bucket}/${item.key}`);
      execFileSync("aws", copyArguments(item, endpoint), { stdio: ["ignore", "inherit", "inherit"] });
    });
    console.log(`Uploaded ${planned.length} files. Purge the hero prefix, then run with --verify.`);
  },
  async verify(planned) {
    const problems: string[] = [];
    for (const item of planned) {
      // oxlint-disable-next-line no-await-in-loop -- one at a time: after a purge, one byte of a file makes the edge fetch all of it from R2, so a burst would pull every file through at once
      problems.push(...(await servedTo(item)));
    }
    if (problems.length) {
      console.error(`✗ ${problems.length} problem(s) across ${planned.length} files:`);
      for (const problem of problems.slice(0, 20)) console.error(`    ${problem}`);
      if (problems.length > 20) console.error(`    …and ${problems.length - 20} more`);
      console.error("  After an upload, the edge serves each file as it was before until the hero prefix is purged.");
      process.exitCode = 1;
      return;
    }
    console.log(`✓ ${planned.length} files served at their recorded sizes, as their types, marked to save under their names`);
  },
};

async function main(): Promise<void> {
  const mode = modeOf(process.argv.slice(2));
  const manifest = JSON.parse(readFileSync(`${WEB_ROOT}src/data/countries.json`, "utf8")) as Manifest;
  const { earth } = JSON.parse(readFileSync(`${WEB_ROOT}src/data/downloads.json`, "utf8")) as Partial<
    Record<string, BundleRecord>
  >;
  if (!earth) throw new Error("src/data/downloads.json records no bundle for Earth");
  const deployScript = JSON.parse(readFileSync(`${WEB_ROOT}package.json`, "utf8")).scripts["build:deploy"];
  const bases = {
    hero: deployBase("PUBLIC_HERO_BASE", deployScript),
    archive: deployBase("PUBLIC_ARCHIVE_BASE", deployScript),
  };
  const planned = plannedUploads(manifest, earth, bases, STORE);
  await run(mode, planned, mode === "verify" ? [] : localProblems(planned, sizeOnDisk), actions);
}

if (import.meta.main) {
  try {
    await main();
  } catch (error) {
    const lines = error instanceof R2Unreachable ? error.lines : [String((error as Error).message ?? error)];
    console.error(`\n✗ upload downloads: ${lines.join("\n  ")}\n`);
    process.exitCode = 1;
  }
}
