import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  archiveFileName,
  archivePath,
  describeMissingArchive,
  describeRetiredStoreVars,
  resolveDataRoot,
} from "./devStores";
import type { LayerId } from "./tileAddress";

const REPO = "/checkout/maps";
const LAYERS_UNDER_TEST: LayerId[] = ["relief", "terrain", "vector"];

describe("resolveDataRoot", () => {
  it("defaults to <repo>/data, the same fallback pipeline/paths.py takes", () => {
    expect(resolveDataRoot({}, REPO)).toBe("/checkout/maps/data");
  });

  it("takes MAPS_DATA when it is set, so a relocated store moves both halves together", () => {
    expect(resolveDataRoot({ MAPS_DATA: "/mnt/big/terrella-data" }, REPO)).toBe(
      "/mnt/big/terrella-data",
    );
  });

  it("resolves a relative MAPS_DATA rather than passing it through", () => {
    // A path that depends on the server's cwd would resolve differently for the middleware than
    // for anything else reading the same variable.
    expect(path.isAbsolute(resolveDataRoot({ MAPS_DATA: "../store" }, REPO))).toBe(true);
  });

  it("treats a blank MAPS_DATA as unset, not as the filesystem root", () => {
    expect(resolveDataRoot({ MAPS_DATA: "   " }, REPO)).toBe("/checkout/maps/data");
  });
});

describe("archivePath", () => {
  // THE CHARACTERISATION: these three paths are exactly what web/.env.example used to spell out by
  // hand, one variable each. Written as literals rather than assembled from the module, so a change
  // to the convention has to be made here too — which is the point of pinning it.
  it("puts Earth's archives where the pipeline has always written them", () => {
    const data = resolveDataRoot({}, REPO);
    expect(archivePath(data, "earth", "relief")).toBe(
      "/checkout/maps/data/work/planet_tiles/planet.pmtiles",
    );
    expect(archivePath(data, "earth", "terrain")).toBe(
      "/checkout/maps/data/work/planet_terrain/terrain.pmtiles",
    );
    expect(archivePath(data, "earth", "vector")).toBe(
      "/checkout/maps/data/work/planet_vector/vector.pmtiles",
    );
  });

  it("collapses Earth's empty prefix instead of leaving a doubled separator", () => {
    // path.join swallows an empty segment; asserted because the whole "Earth does not move"
    // decision rests on it, and a `//` would be a different path to a stricter reader.
    expect(archivePath("/data", "earth", "relief")).not.toContain("//");
  });

  it("keeps the three archives in three directories", () => {
    const paths = LAYERS_UNDER_TEST.map((layer) => archivePath("/data", "earth", layer));
    expect(new Set(paths).size).toBe(LAYERS_UNDER_TEST.length);
  });

  it("follows the data root, so MAPS_DATA moves every archive at once", () => {
    const relocated = resolveDataRoot({ MAPS_DATA: "/mnt/store" }, REPO);
    for (const layer of LAYERS_UNDER_TEST) {
      expect(archivePath(relocated, "earth", layer).startsWith("/mnt/store/work/")).toBe(true);
    }
  });
});

describe("archiveFileName", () => {
  it("names each archive the way the pipeline does", () => {
    expect(archiveFileName("relief")).toBe("planet.pmtiles");
    expect(archiveFileName("terrain")).toBe("terrain.pmtiles");
    expect(archiveFileName("vector")).toBe("vector.pmtiles");
  });
});

describe("describeMissingArchive", () => {
  const message = describeMissingArchive(
    "earth",
    "terrain",
    "/checkout/maps/data/work/planet_terrain/terrain.pmtiles",
    "/checkout/maps/data",
  );

  it("names the path it looked at", () => {
    expect(message).toContain("/checkout/maps/data/work/planet_terrain/terrain.pmtiles");
  });

  it("names the stage that would have written it", () => {
    expect(message).toContain("pipeline/tile/terrain_rgb.py");
  });

  it("names the one variable that relocates the store", () => {
    expect(message).toContain("MAPS_DATA");
  });
});

describe("describeRetiredStoreVars", () => {
  it("stays quiet when no retired variable is set", () => {
    expect(describeRetiredStoreVars({ HERO_STORE: "/renders" })).toBeNull();
  });

  it("names every retired variable a checkout still sets", () => {
    const warning = describeRetiredStoreVars({
      PMTILES_STORE: "/old/planet_tiles",
      COUNTRIES_PMTILES_STORE: "/old/planet_countries",
    });
    expect(warning).toContain("PMTILES_STORE");
    expect(warning).toContain("COUNTRIES_PMTILES_STORE");
  });

  it("ignores a blank one, the same way the resolver does", () => {
    expect(describeRetiredStoreVars({ PMTILES_STORE: "  " })).toBeNull();
  });
});
