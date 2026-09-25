// R2 as the deploy scripts reach it: the S3 endpoint in web/.env, the `r2` profile in
// ~/.aws/credentials, and the two buckets the site is served from.
//
// A failure is thrown rather than printed, so each script names itself in the message and says
// what its own way round it is.

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const WEB_ROOT = fileURLToPath(new URL("../", import.meta.url));

/** Hero renders, the country pages' download files and the border GeoJSON. */
export const ASSET_BUCKET = "terrella-assets";
/** The tile archives, which the tile Worker reads, and the country maps bundle. The archive host
 *  serves each whole. */
export const ARCHIVE_BUCKET = "terrella-tiles";
/** Where the hero renders sit in the asset bucket, and so under the hero host. */
export const HERO_PREFIX = "heroes/";
/** Where the link-preview card sits, the same pair of spellings one prefix down. */
export const SOCIAL_PREFIX = "social/";

/** What a bucket holds: each object's key, with its size in bytes. */
export type Listing = Map<string, number>;

/** R2 could not be reached, with the lines that say why and what to check. */
export class R2Unreachable extends Error {
  readonly lines: string[];

  constructor(lines: string[]) {
    super(lines.join("\n"));
    this.lines = lines;
  }
}

/** The S3 endpoint, from web/.env. The account ID is part of it, so it never lives in the repo. */
export function r2Endpoint(): string {
  if (existsSync(`${WEB_ROOT}.env`)) process.loadEnvFile(`${WEB_ROOT}.env`);
  const endpoint = process.env.R2_ENDPOINT?.trim();
  if (!endpoint) {
    throw new R2Unreachable([
      "R2_ENDPOINT is not set.",
      "Add it to web/.env (see .env.example). It is machine-specific and gitignored,",
      "because the account ID is part of the URL.",
    ]);
  }
  return endpoint;
}

/** The options every `aws` call to R2 takes. */
export function r2Options(endpoint: string): string[] {
  return ["--endpoint-url", endpoint, "--profile", "r2"];
}

/** Every object in `bucket`, with its size. A bucket that cannot be listed throws, so it can never
 *  read as an empty one. */
export function listBucket(endpoint: string, bucket: string): Listing {
  try {
    const stdout = execFileSync(
      "aws",
      [
        "s3api", "list-objects-v2",
        "--bucket", bucket,
        ...r2Options(endpoint),
        "--query", "Contents[].[Key, Size]",
        "--output", "json",
      ],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
    );
    return new Map<string, number>(JSON.parse(stdout) ?? []);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    const stderr = (error as { stderr?: Buffer | string }).stderr?.toString() ?? "";
    throw new R2Unreachable([
      `could not list s3://${bucket}/.`,
      (stderr || detail).trim().split("\n").pop() ?? "",
      "Check the `r2` profile in ~/.aws/credentials and R2_ENDPOINT in web/.env.",
    ]);
  }
}
