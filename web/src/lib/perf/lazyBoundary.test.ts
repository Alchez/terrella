// The one rule this directory exists to make enforceable.
//
// Everything in `lib/perf/` is instrument: it runs only when `?perf` is in the URL, and a visitor
// without the flag must not download it. That was previously guarded per-file, for `perfOverlay`
// alone — and it is exactly why a regression walked straight through. `perfNetwork` was given a
// static import so its Resource Timing buffer raiser could run before `new maplibregl.Map`, Rollup
// therefore placed the whole module in the main chunk, and **268 lines of instrument shipped to
// every visitor for +2,362 bytes**, gallery tier included. Nothing failed, because nothing was
// looking at anything but one filename.
//
// Splitting the import SITE does not split the chunk — a module lands wherever it is statically
// imported, and a later dynamic import of the same module just references the copy already there.
// Splitting the MODULE does. So the raiser now lives in `lib/resourceTimingBuffer.ts`, fifteen
// lines, outside this directory and deliberately exempt.
//
// A directory rule catches the next one by default, which a per-file rule cannot.

import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const PAGES = new URL("../../pages/", import.meta.url);
const PERF_DIR = new URL("./", import.meta.url);

/** Every instrument module in this directory, by import specifier stem. */
const instrumentModules = readdirSync(PERF_DIR)
  .filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts"))
  .map((name) => name.replace(/\.ts$/, ""))
  .sort();

const pageSources = readdirSync(PAGES)
  .filter((name) => name.endsWith(".astro"))
  .map((name) => ({ name, text: readFileSync(new URL(name, PAGES), "utf8") }));

describe("lib/perf is a lazy boundary", () => {
  it("has modules to check, so the sweep below cannot pass by finding nothing", () => {
    // A directory rule over an empty list is a test that always passes. Assert the subject exists,
    // and name it, so a rename that empties this list fails here rather than going quiet.
    expect(instrumentModules).toEqual(["perfNetwork", "perfOverlay", "perfSnapshot"]);
    expect(pageSources.length).toBeGreaterThan(0);
  });

  it("is never statically VALUE-imported by a page", () => {
    // Type imports are fine and the globe has three: they are erased at build, so they create no
    // dependency and cannot pull a module into an ordinary visit. `[^;]*?` rather than `[\s\S]*?`
    // so a match cannot run from one import statement into a later one and misattribute it.
    const offenders: string[] = [];
    for (const page of pageSources) {
      for (const module of instrumentModules) {
        const pattern = new RegExp(
          String.raw`^[ \t]*import\s+(?!type\b)[^;]*?from "\.\./lib/perf/${module}";`,
          "m",
        );
        if (pattern.test(page.text)) offenders.push(`${page.name} -> ${module}`);
      }
    }
    expect(offenders, "a value import ships the instrument to every visitor").toEqual([]);
  });

  it("is reached only through a dynamic import, inside the ?perf branch", () => {
    const globe = pageSources.find((page) => page.name === "globe.astro");
    expect(globe, "globe.astro must exist").toBeTruthy();
    for (const module of instrumentModules) {
      expect(globe!.text, `${module} must load dynamically`).toContain(
        `import("../lib/perf/${module}")`,
      );
    }
    expect(globe!.text).toMatch(/if \(urlFlags\.has\("perf"\)\)/);
  });

  it("does not re-export the always-shipped buffer raiser back into this directory", () => {
    // The failure mode that would quietly undo all of the above: re-exporting the exempt module from
    // here would give a page a legitimate-looking `lib/perf/…` import that drags the chunk back in.
    for (const module of instrumentModules) {
      const source = readFileSync(new URL(`./${module}.ts`, PERF_DIR), "utf8");
      expect(source, `${module} must not re-export the raiser`).not.toMatch(
        /export .*(raiseResourceTimingBuffer|RESOURCE_TIMING_BUFFER_SIZE)/,
      );
    }
  });
});
