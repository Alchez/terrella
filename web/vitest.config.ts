import { defineConfig, configDefaults } from "vitest/config";
import { playwright } from "@vitest/browser-playwright";

/**
 * Two test projects, split by what each one can actually observe.
 *
 * `node` is everything the suite already had: pure logic, and the source-text assertions that
 * read a `.astro` file and pin a structure. It needs no DOM and must not pay for one.
 *
 * `browser` is for the handful of things node cannot judge at all — real layout geometry
 * (`getBoundingClientRect` is zeroes without a renderer) and the real CSS cascade, including
 * `mask-image`, `color-mix`, `backdrop-filter` and `:has()`. The globe's chrome has had its
 * clearance constants re-derived by hand three times because there was no way to assert them;
 * this is that gap closed.
 *
 * THE SPLIT ITSELF IS THE HAZARD, and vitest does not flag it. A project whose `include` matches
 * nothing is simply absent from the run — pointing the browser glob at a non-matching pattern
 * reports `Test Files 28 passed (28)` and exits 0. Not a discrepancy, not a warning: a clean green
 * run with two files silently uncollected, which is the failure mode that looks exactly like
 * success. A green suite is therefore not evidence that both projects ran.
 *
 * `scripts/check_test_collection.ts` is the guard: it walks the tree and diffs it against what
 * `vitest list` resolves, so every `*.test.ts` under `src/` and `worker/` must be collected exactly
 * once. It runs as its own CI step and deliberately is not a test in here — a vitest test would be
 * dropped by the same broken glob it exists to catch. Do not put an expected count back in this
 * comment instead: a number in a docstring ratchets nothing, and the one that was here went stale.
 */
export default defineConfig({
  test: {
    projects: [
      {
        test: {
          name: "node",
          include: ["src/**/*.test.ts", "worker/**/*.test.ts"],
          // Spread the defaults rather than replacing them — a bare array here would drop
          // node_modules and dist from the exclusions and start collecting third-party specs.
          exclude: [...configDefaults.exclude, "**/*.browser.test.ts"],
          environment: "node",
        },
      },
      {
        test: {
          name: "browser",
          include: ["src/**/*.browser.test.ts"],
          browser: {
            enabled: true,
            // CI installs `--only-shell`, which is the binary this flag selects. Going headed
            // needs that narrowing dropped in .github/workflows/ci.yml first.
            headless: true,
            provider: playwright(),
            instances: [{ browser: "chromium" }],
          },
        },
      },
    ],
  },
});
