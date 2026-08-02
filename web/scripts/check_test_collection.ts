#!/usr/bin/env node
// Does every test file on disk actually get run?
//
// vitest.config.ts splits the suite into a `node` project and a `browser` project. A project
// whose `include` matches nothing is not an error to vitest — it is simply absent. Pointing the
// browser glob at a non-matching pattern reports `Test Files 28 passed (28)` and exits 0: not a
// discrepancy, not a warning, a clean green run with two files silently uncollected. There is no
// config option to fix this — `passWithNoTests` is listed in vitest's `NonProjectOptions`, so it
// cannot be set per project.
//
// So this compares two independent sources for the same set:
//
//   ground truth  the filesystem, walked here
//   measurement   `vitest list`, i.e. vitest's own resolver applied to the real config
//
// A guard for this CANNOT live inside the suite it guards. A vitest test that checked the same
// thing would be collected by the `node` project — and a broken `node` glob would drop the guard
// along with everything else, leaving it green. It runs as its own CI step for the same reason.
//
// TypeScript for consistency with check_deploy_sync.ts, and because web/tsconfig.json already
// covers scripts/: node 24 strips the types at run time, so there is no build step.

import { execFileSync } from "node:child_process";
import { readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";

const WEB_ROOT = fileURLToPath(new URL("../", import.meta.url));

/** The roots vitest.config.ts globs. Both projects' includes live under one of these. */
const TEST_ROOTS = ["src", "worker"];

/** One `vitest list --filesOnly --json` entry. */
interface CollectedFile {
  file: string;
  projectName: string;
}

/**
 * Exits non-zero, naming the check that failed on its own line.
 *
 * The name is the contract with `scripts/sabotage.py`, which reads it back out of this output the
 * way it reads a failing test's name out of vitest or pytest — so "the script went red" is not
 * accepted as proof that the intended check is what fired.
 */
function fail(check: string, ...lines: string[]): never {
  console.error(`\n✗ test collection: ${check}`);
  for (const line of lines) console.error(`  ${line}`);
  console.error("");
  process.exit(1);
}

/** Every `*.test.ts` under the roots, repo-relative, sorted. Ground truth. */
function testFilesOnDisk(): string[] {
  const found: string[] = [];
  for (const root of TEST_ROOTS) {
    let entries: unknown[];
    try {
      entries = readdirSync(`${WEB_ROOT}${root}`, { recursive: true });
    } catch (error) {
      // A missing root would otherwise throw ENOENT with no indication that the *walk* is what
      // broke — and a silently shortened walk is the one way this script reports a false pass.
      fail("tree-is-not-empty", `cannot walk ${root}/: ${String(error)}`);
    }
    for (const entry of entries) {
      const relative = `${root}/${String(entry)}`;
      if (!relative.endsWith(".test.ts")) continue;
      // A name ending `.test.ts` is not necessarily a FILE. When a browser test fails, vitest
      // writes `__screenshots__/<spec>.browser.test.ts/` — a directory named exactly like the spec
      // — and counting it here reported two uncollected tests that do not exist.
      if (!statSync(`${WEB_ROOT}${relative}`).isFile()) continue;
      // Defensive: neither root should contain these, but a stray build output here would look
      // like an uncollected test rather than the packaging mistake it is.
      if (relative.split("/").includes("node_modules")) continue;
      if (relative.split("/").includes("dist")) continue;
      found.push(relative);
    }
  }
  return found.sort();
}

/** What vitest's own resolver collects, from the real config. The measurement. */
function collectedByVitest(): CollectedFile[] {
  let output: string;
  try {
    // The binary directly rather than through `pnpm exec`, so no package-manager banner can land
    // in front of the JSON.
    output = execFileSync("./node_modules/.bin/vitest", ["list", "--filesOnly", "--json"], {
      cwd: WEB_ROOT,
      encoding: "utf8",
      maxBuffer: 32 * 1024 * 1024,
    });
  } catch (error) {
    fail("vitest-list-runs", `\`vitest list\` failed: ${String(error)}`);
  }
  const start = output.indexOf("[");
  if (start === -1) fail("vitest-list-runs", "`vitest list` printed no JSON array", output.trim());
  try {
    return JSON.parse(output.slice(start)) as CollectedFile[];
  } catch (error) {
    fail("vitest-list-runs", `could not parse \`vitest list\` output: ${String(error)}`);
  }
}

const onDisk = testFilesOnDisk();

// Anti-vacuity, and it comes first: every check below compares against this set, so an empty walk
// would agree with an empty collection and report success having verified nothing.
if (onDisk.length === 0) {
  fail(
    "tree-is-not-empty",
    `no *.test.ts found under ${TEST_ROOTS.join(", ")} — the walk is broken, not the config`,
  );
}

const collected = collectedByVitest();
const collectedPaths = collected.map((entry) => entry.file.replace(WEB_ROOT, ""));
const collectedSet = new Set(collectedPaths);

const uncollected = onDisk.filter((path) => !collectedSet.has(path));
if (uncollected.length > 0) {
  fail(
    "every-test-file-is-collected",
    "these exist on disk and no vitest project collects them:",
    ...uncollected.map((path) => `  ${path}`),
    "a project's `include` has stopped matching, and vitest reports that as a pass",
  );
}

const onDiskSet = new Set(onDisk);
const phantom = collectedPaths.filter((path) => !onDiskSet.has(path));
if (phantom.length > 0) {
  fail(
    "collected-files-exist-on-disk",
    "vitest collected paths this walk did not find:",
    ...phantom.map((path) => `  ${path}`),
    `either TEST_ROOTS is short a directory, or the naming convention has moved past *.test.ts`,
  );
}

const seen = new Map<string, string[]>();
for (const entry of collected) {
  const path = entry.file.replace(WEB_ROOT, "");
  seen.set(path, [...(seen.get(path) ?? []), entry.projectName]);
}
const doubled = [...seen].filter(([, projects]) => projects.length > 1);
if (doubled.length > 0) {
  fail(
    "no-file-is-collected-twice",
    "these run under more than one project, so the same test is paying twice:",
    ...doubled.map(([path, projects]) => `  ${path} — ${projects.join(", ")}`),
  );
}

const projects = [...new Set(collected.map((entry) => entry.projectName))].sort();
console.log(
  `✓ test collection: ${onDisk.length} files, all collected exactly once, across ${projects.join(" + ")}`,
);
