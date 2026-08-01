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
 * THE SPLIT ITSELF IS THE HAZARD. Before this file existed the whole suite ran on vitest's
 * defaults, so a `projects` block that mis-globs would report a green run having executed
 * nothing — the failure mode that looks exactly like success. The control is the count: the
 * node project ran 698 tests across 24 files immediately before this file was added, and any
 * change here that drops below that has lost tests rather than fixed them.
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
