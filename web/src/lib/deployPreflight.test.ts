import { describe, expect, it, vi } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  advertisedObjects,
  bundleProblems,
  downloadSizeMismatches,
} from "../../scripts/check_deploy_sync.ts";
import { ASSET_BUCKET, R2Unreachable, listBucket } from "../../scripts/r2.ts";
import type { Country, DownloadFiles, Manifest } from "./manifest";
import { TECTONICS_FILE } from "./tectonicBoundaries";

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

/**
 * Every file the site fetches from `BORDERS_BASE`, read off the `BORDERS_BASE + …` sites in the
 * source. An identifier is resolved through `NAMED`, and one it does not know fails, so a new fetch
 * spelled through a constant cannot pass unseen.
 */
function filesFetchedFromTheBordersStore(): string[] {
  const NAMED: Record<string, string> = { TECTONICS_FILE };
  const root = fileURLToPath(new URL("../", import.meta.url));
  const files: string[] = [];
  for (const path of readdirSync(root, { recursive: true, encoding: "utf8" })) {
    if (!/\.(ts|astro)$/.test(path) || path.endsWith(".test.ts")) continue;
    const source = readFileSync(root + path, "utf8");
    for (const [, literal, name] of source.matchAll(/BORDERS_BASE \+ (?:"([^"]+)"|(\w+))/g)) {
      if (literal !== undefined) files.push(literal);
      else if (name in NAMED) files.push(NAMED[name]);
      else throw new Error(`${path} fetches BORDERS_BASE + ${name}, which this test cannot resolve`);
    }
  }
  return files;
}

describe("the deploy preflight holds R2 to the GeoJSON the globe fetches", () => {
  it("advertises exactly the files fetched from the borders store, and none it no longer fetches", () => {
    const fetched = filesFetchedFromTheBordersStore();
    expect(fetched.length, "the source scan found no fetch at all").toBeGreaterThan(0);
    const advertised = [...advertisedObjects(MANIFEST)].filter((key) => key.startsWith("borders/"));
    expect(advertised.toSorted()).toEqual(fetched.map((file) => `borders/${file}`).toSorted());
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
    // A PATH carrying no `aws`, so the spawn fails before any binary runs; the closed local port
    // is belt and braces, since nothing reaches the network to use it.
    //
    // Do not put the real `aws` back. Running it made this pass only when the CLI happened to
    // start inside the timeout, which is not the claim: a cold one took 6.2 s against 5 s.
    vi.stubEnv("PATH", fileURLToPath(new URL(".", import.meta.url)));
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
