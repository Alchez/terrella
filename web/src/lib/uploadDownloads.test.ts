import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";

import { ARCHIVE_BUCKET, ASSET_BUCKET, HERO_PREFIX } from "../../scripts/r2.ts";
import {
  copyArguments,
  deployBase,
  localProblems,
  modeOf,
  plannedUploads,
  run,
  servedProblems,
  type Upload,
} from "../../scripts/upload_downloads.ts";
import type { BundleRecord } from "./archiveIndex";
import type { Country, DownloadFiles, Manifest } from "./manifest";

/** One country as the manifest publishes it: rendered with these download files, or not at all. */
function country(slug: string, download: DownloadFiles | null): Country {
  return {
    slug,
    name: slug,
    admin: slug,
    continent: "Asia",
    searchTerms: [],
    bbox: [0, 0, 1, 1],
    aspect: 1.5,
    sizes: download ? [640, 7680] : [],
    native: download ? 7680 : null,
    rendered: download !== null,
    listedOnly: false,
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
const BUNDLE: BundleRecord = {
  key: "earth/country-maps-webp-v1.zip",
  bytes: 10_429_471,
  sha256: "0".repeat(64),
  images: { "nepal-7680.webp": NEPAL.webpBytes },
};
const BASES = { hero: "https://assets.example/heroes/", archive: "https://archives.example/" };
const STORE = { variants: "/store/variants", archives: "/store/archives" };

const planned = plannedUploads(MANIFEST, BUNDLE, BASES, STORE);
const named = (name: string): Upload => {
  const found = planned.find((upload) => upload.name === name);
  if (!found) throw new Error(`nothing planned is named ${name}`);
  return found;
};

describe("the uploader plans every download file the site offers", () => {
  it("plans both of a rendered country's files and the bundle, and nothing for an unrendered one", () => {
    expect(planned.map((upload) => upload.name)).toEqual([
      "nepal-7680.webp",
      "nepal-7680.png",
      "country-maps-webp-v1.zip",
    ]);
  });

  it("sends each file to the key the site links it at, from the store that wrote it", () => {
    expect(named("nepal-7680.png")).toMatchObject({
      local: "/store/variants/nepal-7680.png",
      bucket: ASSET_BUCKET,
      key: `${HERO_PREFIX}nepal-7680.png`,
      url: "https://assets.example/heroes/nepal-7680.png",
    });
    expect(named("country-maps-webp-v1.zip")).toMatchObject({
      local: `/store/archives/${BUNDLE.key}`,
      bucket: ARCHIVE_BUCKET,
      key: BUNDLE.key,
      url: `https://archives.example/${BUNDLE.key}`,
    });
  });

  it("marks every file to save under its own name, as its own type", () => {
    for (const upload of planned) {
      expect(upload.contentDisposition, upload.name).toBe(`attachment; filename="${upload.name}"`);
    }
    expect(planned.map((upload) => upload.contentType)).toEqual([
      "image/webp",
      "image/png",
      "application/zip",
    ]);
  });

  it("expects each file at the size the manifest or the bundle's record gives", () => {
    expect(planned.map((upload) => upload.bytes)).toEqual([NEPAL.webpBytes, NEPAL.pngBytes, BUNDLE.bytes]);
  });
});

/** A store holding these files at these sizes, as the uploader asks one. */
const onDisk = (entries: [string, number][]) => {
  const sizes = new Map(entries);
  return (local: string) => sizes.get(local);
};

/** One ranged response from a public host. */
const served = (status: number, headers: Record<string, string>) => ({
  status,
  headers: new Headers(headers),
});

describe("the uploader refuses a store other than the one the records describe", () => {
  it("passes a store holding every file at its recorded size", () => {
    const sizeOf = onDisk(planned.map((upload) => [upload.local, upload.bytes]));
    expect(localProblems(planned, sizeOf)).toEqual([]);
  });

  it("names a file the store lacks and one at another size", () => {
    const sizeOf = onDisk([
      [named("nepal-7680.webp").local, NEPAL.webpBytes - 2_952],
      [named("nepal-7680.png").local, NEPAL.pngBytes],
    ]);
    const problems = localProblems(planned, sizeOf);
    expect(problems).toHaveLength(2);
    expect(problems.join("\n")).toContain("nepal-7680.webp");
    expect(problems.join("\n")).toContain("country-maps-webp-v1.zip");
  });
});

describe("each upload", () => {
  it("copies the file to its key with its type and disposition, through R2's options", () => {
    const upload = named("nepal-7680.webp");
    const argv = copyArguments(upload, "https://r2.example");
    const value = (flag: string) => argv[argv.indexOf(flag) + 1];
    expect(argv.slice(0, 4)).toEqual(["s3", "cp", upload.local, `s3://${ASSET_BUCKET}/${upload.key}`]);
    expect(value("--content-type")).toBe("image/webp");
    expect(value("--content-disposition")).toBe('attachment; filename="nepal-7680.webp"');
    expect(value("--endpoint-url")).toBe("https://r2.example");
    expect(value("--profile")).toBe("r2");
  });
});

describe("the verifier judges what a visitor is served", () => {
  it("passes one byte of the file at its recorded size, marked to save under its name", () => {
    const upload = named("nepal-7680.webp");
    const response = served(206, {
      "content-range": `bytes 0-0/${upload.bytes}`,
      "content-type": "image/webp",
      "content-disposition": 'attachment; filename="nepal-7680.webp"',
    });
    expect(servedProblems(upload, response)).toEqual([]);
  });

  it("names the edge's copy from before the upload: no disposition, and another size", () => {
    const upload = named("nepal-7680.webp");
    const response = served(206, {
      "content-range": `bytes 0-0/${upload.bytes - 2_952}`,
      "content-type": "image/webp",
    });
    const problems = servedProblems(upload, response);
    expect(problems).toHaveLength(2);
    expect(problems.join("\n")).toContain(String(upload.bytes - 2_952));
    expect(problems.join("\n")).toContain("disposition");
  });

  it("names a file served as another type", () => {
    const upload = named("nepal-7680.webp");
    const response = served(206, {
      "content-range": `bytes 0-0/${upload.bytes}`,
      "content-type": "application/octet-stream",
      "content-disposition": 'attachment; filename="nepal-7680.webp"',
    });
    expect(servedProblems(upload, response)).toEqual([
      expect.stringContaining("application/octet-stream"),
    ]);
  });

  it("names a file the host does not serve", () => {
    const upload = named("nepal-7680.webp");
    expect(servedProblems(upload, served(404, {}))).toEqual([expect.stringContaining("404")]);
  });
});

describe("the public hosts come from the deploy build", () => {
  const script = "PUBLIC_HERO_BASE=https://a.example/heroes/ PUBLIC_ARCHIVE_BASE=https://b.example/ astro build";

  it("reads each base as build:deploy sets it", () => {
    expect(deployBase("PUBLIC_HERO_BASE", script)).toBe("https://a.example/heroes/");
    expect(deployBase("PUBLIC_ARCHIVE_BASE", script)).toBe("https://b.example/");
  });

  it("refuses a base the deploy build does not set", () => {
    expect(() => deployBase("PUBLIC_TILE_BASE", script)).toThrow(/PUBLIC_TILE_BASE/);
  });

  it("finds both in the real build:deploy", () => {
    const real = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8"))
      .scripts["build:deploy"] as string;
    expect(deployBase("PUBLIC_HERO_BASE", real)).toMatch(/^https:\/\/.+\/$/);
    expect(deployBase("PUBLIC_ARCHIVE_BASE", real)).toMatch(/^https:\/\/.+\/$/);
  });
});

const actions = () => ({ describe: vi.fn(), upload: vi.fn(), verify: vi.fn(async () => {}) });

describe("a run uploads only when told to", () => {
  it("reads a bare run as a dry run", () => {
    expect(modeOf([])).toBe("dry run");
    expect(modeOf(["--upload"])).toBe("upload");
    expect(modeOf(["--verify"])).toBe("verify");
  });

  it("refuses to upload and verify in one run", () => {
    expect(() => modeOf(["--upload", "--verify"])).toThrow();
  });

  it("describes and uploads nothing on a dry run", async () => {
    const spies = actions();
    await run("dry run", planned, [], spies);
    expect(spies.describe).toHaveBeenCalledWith(planned);
    expect(spies.upload).not.toHaveBeenCalled();
  });

  it("uploads nothing from a store the records do not describe", async () => {
    const spies = actions();
    await expect(run("upload", planned, ["nepal-7680.webp is missing"], spies)).rejects.toThrow(
      /nepal-7680\.webp is missing/,
    );
    expect(spies.upload).not.toHaveBeenCalled();
  });

  it("uploads every planned file when told to", async () => {
    const spies = actions();
    await run("upload", planned, [], spies);
    expect(spies.upload).toHaveBeenCalledWith(planned);
  });

  it("verifies without reading the store, which may be on another machine", async () => {
    const spies = actions();
    await run("verify", planned, ["nepal-7680.webp is missing"], spies);
    expect(spies.verify).toHaveBeenCalledWith(planned);
    expect(spies.upload).not.toHaveBeenCalled();
  });
});
