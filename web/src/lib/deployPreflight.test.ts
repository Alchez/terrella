import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";

import {
  advertisedObjects,
  bundleProblems,
  downloadSizeMismatches,
} from "../../scripts/check_deploy_sync.ts";
import { ASSET_BUCKET, R2Unreachable, listBucket } from "../../scripts/r2.ts";
import type { Country, DownloadFiles, Manifest } from "./manifest";

/** One country as the manifest publishes it: rendered with these download files, or not at all. */
function country(slug: string, download: DownloadFiles | null): Country {
  return {
    slug,
    name: slug,
    continent: "Asia",
    searchTerms: [],
    bbox: [0, 0, 1, 1],
    aspect: 1.5,
    sizes: download ? [640, 7680] : [],
    native: download ? 7680 : null,
    rendered: download !== null,
    download,
    hasSpotlight: false,
    spotlightSizes: [],
  };
}

const NEPAL: DownloadFiles = { width: 7680, height: 4787, webpBytes: 10_427_982, pngBytes: 59_115_316 };
const MANIFEST: Manifest = {
  count: 2,
  rendered: 1,
  countries: [country("nepal", NEPAL), country("kiribati", null)],
};
/** The full-size WebP as it was uploaded before a stamp put its credit inside it. */
const UNSTAMPED_WEBP_BYTES = NEPAL.webpBytes - 2_952;
const BUNDLE = {
  key: "earth/country-maps-webp-v1.zip",
  bytes: 10_429_471,
  sha256: "0".repeat(64),
  images: { "nepal-7680.webp": NEPAL.webpBytes },
};

describe("the deploy preflight holds R2 to the download files the pages offer", () => {
  it("advertises both of a rendered country's download files, and nothing for an unrendered one", () => {
    const advertised = advertisedObjects(MANIFEST);
    expect(advertised).toContain("heroes/nepal-7680.webp");
    expect(advertised).toContain("heroes/nepal-7680.png");
    expect([...advertised].filter((key) => key.includes("kiribati"))).toEqual([]);
  });

  it("passes download files R2 holds at the sizes the manifest records", () => {
    const listing = new Map([
      ["heroes/nepal-7680.webp", NEPAL.webpBytes],
      ["heroes/nepal-7680.png", NEPAL.pngBytes],
    ]);
    expect(downloadSizeMismatches(MANIFEST, listing)).toEqual([]);
  });

  it("names a download file R2 holds without its credit, which presence alone cannot see", () => {
    const listing = new Map([
      ["heroes/nepal-7680.webp", UNSTAMPED_WEBP_BYTES],
      ["heroes/nepal-7680.png", NEPAL.pngBytes],
    ]);
    const [mismatch, ...rest] = downloadSizeMismatches(MANIFEST, listing);
    expect(rest).toEqual([]);
    expect(mismatch).toContain("heroes/nepal-7680.webp");
    expect(mismatch).toContain(String(UNSTAMPED_WEBP_BYTES));
    expect(mismatch).toContain(String(NEPAL.webpBytes));
  });

  it("names a PNG copy R2 holds from an earlier render of its master", () => {
    const listing = new Map([
      ["heroes/nepal-7680.webp", NEPAL.webpBytes],
      ["heroes/nepal-7680.png", NEPAL.pngBytes + 81_207],
    ]);
    const [mismatch, ...rest] = downloadSizeMismatches(MANIFEST, listing);
    expect(rest).toEqual([]);
    expect(mismatch).toContain("heroes/nepal-7680.png");
  });

  it("leaves a file R2 lacks to the missing list rather than calling it resized", () => {
    const listing = new Map([["heroes/nepal-7680.webp", NEPAL.webpBytes]]);
    expect(downloadSizeMismatches(MANIFEST, listing)).toEqual([]);
  });
});

describe("the deploy preflight holds the bundle to its record and to the pages", () => {
  const uploaded = new Map([[BUNDLE.key, BUNDLE.bytes]]);

  it("passes a bundle uploaded at its recorded size, holding the images the pages offer", () => {
    expect(bundleProblems(BUNDLE, MANIFEST, uploaded)).toEqual([]);
  });

  it("names a bundle that was never uploaded", () => {
    const [problem, ...rest] = bundleProblems(BUNDLE, MANIFEST, new Map());
    expect(rest).toEqual([]);
    expect(problem).toContain(BUNDLE.key);
  });

  it("names a bundle uploaded at another size than its record", () => {
    const [problem, ...rest] = bundleProblems(BUNDLE, MANIFEST, new Map([[BUNDLE.key, 1]]));
    expect(rest).toEqual([]);
    expect(problem).toContain(BUNDLE.key);
    expect(problem).toContain(String(BUNDLE.bytes));
  });

  it("names an image the bundle holds from before a re-render", () => {
    const earlier = { ...BUNDLE, images: { "nepal-7680.webp": NEPAL.webpBytes - 40_000 } };
    const [problem, ...rest] = bundleProblems(earlier, MANIFEST, uploaded);
    expect(rest).toEqual([]);
    expect(problem).toContain("nepal-7680.webp");
  });

  it("names an image the pages offer that the bundle lacks, and one it holds that no page offers", () => {
    const shifted = { ...BUNDLE, images: { "atlantis-7680.webp": NEPAL.webpBytes } };
    const problems = bundleProblems(shifted, MANIFEST, uploaded);
    expect(problems).toHaveLength(2);
    expect(problems.join("\n")).toContain("nepal-7680.webp");
    expect(problems.join("\n")).toContain("atlantis-7680.webp");
  });
});

describe("a bucket R2 cannot list", () => {
  it("throws rather than reading as an empty one", () => {
    // A closed local port, so nothing leaves the machine, and one attempt, so it fails at once.
    // Where `aws` is not installed the spawn fails instead, which must throw the same way.
    vi.stubEnv("AWS_MAX_ATTEMPTS", "1");
    try {
      expect(() => listBucket("http://127.0.0.1:9", ASSET_BUCKET)).toThrow(R2Unreachable);
    } finally {
      vi.unstubAllEnvs();
    }
  });
});

/** The preflight's source with comments removed, from `name`'s declaration to the next one. */
function declaration(name: string): string {
  const script = readFileSync(new URL("../../scripts/check_deploy_sync.ts", import.meta.url), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");
  const start = script.indexOf(`function ${name}(`);
  const end = script.indexOf("\nfunction ", start + 1);
  return start === -1 ? "" : script.slice(start, end === -1 ? undefined : end);
}

describe("the deploy preflight refuses on both checks, which need R2 and so run only in main()", () => {
  it("holds the bundle to its record and the pages against the archive bucket's listing", () => {
    expect(declaration("main")).toMatch(/\n\s*checkTheBundle\(manifest, archives\);/);
    expect(declaration("checkTheBundle")).toMatch(
      /const problems = bundleProblems\(earth, manifest, archives\);\s*if \(problems\.length\) \{\s*fail\(/,
    );
  });

  it("refuses a download file R2 holds at another size", () => {
    expect(declaration("main")).toMatch(
      /const resized = downloadSizeMismatches\(manifest, present\);\s*if \(resized\.length\) \{\s*fail\(/,
    );
  });
});
