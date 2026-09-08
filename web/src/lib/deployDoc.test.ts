import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { LAYERS, PUBLISHED, type LayerId } from "./tileAddress";
import { DECLARED_TILE_SIZE } from "./reliefSources";
import { TERRAIN_TILE_SIZE } from "./terrainSource";

/** `web/DEPLOY.md` restates values that live in this directory, because a deploy runbook has to be
 *  readable without the source open. Each restatement is a second copy nothing could make go red,
 *  and every one of them had drifted: the archive count was written before Mars, the layer segment
 *  named the object's product where the URL takes its role, and one declared tile size stood in for
 *  two that differ. A reader building a URL from the wrong one gets a 404 with nothing to explain it. */
const deployDoc = readFileSync(new URL("../../DEPLOY.md", import.meta.url), "utf8");
/** The doc is hard-wrapped, so every claim below can be split across a line break at any time by an
 *  edit that changes nothing. Matching the wrapped form would make these guards fail on reflow and
 *  pass on a rewritten value, which is backwards. */
const prose = deployDoc.replace(/\s+/g, " ");

const publishedArchives = Object.values(PUBLISHED).flatMap((body) =>
  Object.values(body).filter((archive) => archive !== null),
);

const NUMBER_WORDS: Record<number, string> = {
  3: "three",
  4: "four",
  5: "five",
  6: "six",
  9: "nine",
  12: "twelve",
};

describe("the deploy runbook's copies of values this directory owns", () => {
  it("counts the archives the tile Worker serves, rather than a body's worth of them", () => {
    const counted = prose.match(/serves \*\*(\w+)\*\* archives out of one bucket/);
    expect(counted, "DEPLOY.md no longer says how many archives one bucket holds").not.toBeNull();
    expect(counted?.[1]).toBe(NUMBER_WORDS[publishedArchives.length]);
  });

  it("spells the layer segment with the names a tile URL takes, not the ones the object keys take", () => {
    const listed = prose.match(/where the layer segment is ([^.]+)\./);
    expect(listed, "DEPLOY.md no longer names the layer segment").not.toBeNull();
    const named = [...(listed?.[1] ?? "").matchAll(/`([^`]+)`/g)].map((match) => match[1]);
    expect(named).toEqual(Object.keys(LAYERS) as LayerId[]);
  });

  it("keeps the two declared tile sizes apart, since only one of them doubles the request count", () => {
    expect(prose).toContain(`relief declares \`tileSize: ${DECLARED_TILE_SIZE}\``);
    expect(prose).toContain(`terrain declares \`tileSize: ${TERRAIN_TILE_SIZE}\``);
  });

  it("names every origin the built site addresses, so a deploy cannot leave one unaccounted for", () => {
    // The bases are the build script's own enumeration of what is NOT on the site's origin, so the
    // table below them has to have grown when a new HOST appeared. Counting bases would say five:
    // heroes and borders are two variables addressing one bucket, and an origin is a host.
    const packageJson = readFileSync(new URL("../../package.json", import.meta.url), "utf8");
    const hosts = [...packageJson.matchAll(/PUBLIC_\w+_BASE=(https:\/\/[^/]+)/g)].map(
      (match) => match[1],
    );
    expect(hosts.length).toBeGreaterThan(0);
    const origins = new Set(hosts).size + 1;
    expect(prose).toContain(`production is ${NUMBER_WORDS[origins]} origins`);
  });
});
