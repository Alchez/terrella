// `webgl-memory` is a 50 KB diagnostic that must never reach a visitor.
//
// It is the second tool with this shape — `jsProfilingPolicy` was the first — and the first one is
// safe because a Vite plugin's `configureServer` simply never runs for a static build. This one
// needs a second guarantee, because unlike a response header it is LOADED BY A TAG IN THE PAGE, and
// a tag is ordinary markup that any edit could unguard without failing anything.
//
// So the property is checked where it is decided rather than in the built output. A test that
// inspects `dist/` would have to run a full `astro build` to be meaningful, and one that inspects it
// only WHEN PRESENT is worse than nothing: it would pass vacuously on a clean checkout, which is
// exactly the shape of check this project has been bitten by. The four assertions below hold the
// same line and run in milliseconds.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const CONFIG = new URL("../../astro.config.ts", import.meta.url);
const BASE_LAYOUT = new URL("../layouts/Base.astro", import.meta.url);
const PACKAGE_JSON = new URL("../../package.json", import.meta.url);

const read = (url: URL) => readFileSync(url, "utf8");

describe("webgl-memory is a dev tool and cannot ship", () => {
  it("is a devDependency, never a runtime one", () => {
    const manifest = JSON.parse(read(PACKAGE_JSON)) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };
    expect(
      manifest.dependencies?.["webgl-memory"],
      "a runtime dependency is a promise to ship it",
    ).toBeUndefined();
    expect(manifest.devDependencies?.["webgl-memory"]).toBeDefined();
  });

  it("is never imported by any source file", () => {
    // An import would place it in a chunk regardless of how the tag is guarded — the same failure
    // `lib/perf/lazyBoundary.test.ts` exists for, one directory over.
    const config = read(CONFIG);
    expect(config).not.toMatch(/^\s*import .*['"]webgl-memory['"]/m);
    expect(read(BASE_LAYOUT)).not.toMatch(/import .*['"]webgl-memory['"]/);
  });

  it("is served only by a plugin that cannot run at build time", () => {
    const config = read(CONFIG);
    const plugin = config.slice(config.indexOf("function webglMemoryDevTool"));
    expect(plugin, "the plugin must exist for this sweep to mean anything").toContain(
      "webgl-memory",
    );
    // `apply: 'serve'` is the load-bearing line. Without it the plugin is merely *usually* inert.
    //
    // COMMENTS ARE STRIPPED FIRST, and that is not tidiness. The first version of this used
    // `toContain`, and a mutation that deleted the real property still passed — because the
    // function's own comment explains what `apply: 'serve'` does, so the test was satisfied by
    // PROSE ABOUT the property rather than by the property. Requiring a whole line that parses as
    // a property assignment is what makes it check the code.
    const body = plugin.slice(0, plugin.indexOf("\n}\n")).replaceAll(/^\s*\/\/.*$/gm, "");
    expect(body).toMatch(/^\s*apply: 'serve',$/m);
  });

  it("is loaded by a tag the production build evaluates away", () => {
    const layout = read(BASE_LAYOUT);
    const tagLine = layout
      .split("\n")
      .find((line) => line.includes("__webgl-memory.js"));
    expect(tagLine, "the layout must carry the tag for this to be checking anything").toBeDefined();
    // The guard and the tag on ONE line, so no edit can separate them without this noticing.
    expect(tagLine).toContain("import.meta.env.DEV &&");
  });
});
