"""Mutation harness — break each guard's subject and confirm the guard fails.

A guard that passes whether or not its subject is present is decoration, and this repo has shipped
several: a regex anchored `^import` that never matched Astro's indented imports (three vacuous
guards in one day), a duplicate in `capability.test.ts` that had been vacuous its whole life, and a
sweep over a directory listing that would have passed by finding nothing. None of them failed. The
only way to learn that is to break the thing each one claims to watch and see whether anything
notices.

Each case rewrites ONE string in ONE file, runs that file's suite, and restores the file whatever
happens. A case names the test that should catch it, so "the suite went red" is not accepted as
proof — red for the wrong reason is a different guard doing someone else's job, and it will stop
covering this case the moment that other guard changes.

Three suites, because not every guard is a test. `suite='web'` runs `pnpm test`; `suite='python'` runs
`pytest`, and those cases check `tests/test_sabotage_cases.py`, the table's own freshness gate, along
with the repo-integrity guards over the docs. That gate is a guard like any other and gets the same
treatment.

`suite='collection'` runs `web/scripts/check_test_collection.ts`, which is a script and not a test on
purpose: it asserts that every test file on disk is collected by some vitest project, and a vitest
test that checked the same thing would be dropped by the very broken glob it exists to catch. A guard
that can be disabled by its own subject has to live outside the suite, so the harness reads a named
check out of its output the way it reads a test name out of the other two.

Four lessons are baked into the control flow because each cost a full run to learn:

  * THE BASELINE IS ASSERTED GREEN FIRST, per suite. A harness that only asks "did the suite fail?"
    reports every case as caught when the suite was already red. One broken regex produced 19 false
    positives that way.
  * FILES ARE TOUCHED AFTER RESTORE. `shutil.copy2` preserves mtime, so a running Vite dev server
    keeps serving the sabotaged module after the file on disk is correct again.
  * THE PYTHON SUITE RUNS WITH BYTECODE WRITING OFF. A `.pyc` is validated on source mtime at
    one-second granularity plus size, so a sabotage-then-restore inside one second can leave pytest
    reading stale bytecode — which made one case report CAUGHT and WRONG on consecutive passes. A
    verdict that flips between passes is this, not flakiness.
  * A MUTATION OF THIS FILE MUST STAY SYNTACTICALLY VALID. Ten cases sabotage the harness itself, and
    `--restore` lives here too: a mutation that breaks the parse would take the recovery path with it.

What this does NOT do: it does not find missing guards, only vacuous ones — a behaviour with no test
at all has no case here and never will, because cases are written from the guard side.

Usage:
    uv run scripts/sabotage.py                  # all cases; each runs its whole suite once
    uv run scripts/sabotage.py --filter cap     # only cases whose label or path matches
    uv run scripts/sabotage.py --suite python   # only one suite
    uv run scripts/sabotage.py --list           # print the table, run nothing
    uv run scripts/sabotage.py --harvest        # print which tests catch each case, judge nothing
    uv run scripts/sabotage.py --restore        # undo leftover backups from a killed run

`tests/test_sabotage_cases.py` checks the table against the tree without running anything, so a
needle that a refactor moved is a 0.1 s pytest failure rather than a shrugged-off SKIP 5 min in.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKUP_SUFFIX = ".sabotage-backup"

# The only directories a case may write to. Paths are repo-root-relative, and this list is what keeps
# "relative path" from meaning "anywhere in the repo" now that cases reach outside `web/`. Widen it
# when a case genuinely needs to — deliberately, since `tests/test_sabotage_cases.py` enforces it.
# PROCESS.md joins the roots because the structural-integrity guard covers repo docs, and a case
# it cannot write to is a case that cannot prove anything.
MUTABLE_ROOTS = (
    "web/src",
    "web/worker",
    # Joined when the deploy preflight started ENUMERATING the archive registry rather than naming
    # two keys out of the Worker's config. That check is the only thing between a re-cut and a site
    # whose every tile 404s, and it cannot run in CI (it needs R2) — so its shape is what gets
    # mutation-tested, and the mutations have to be able to reach it.
    "web/scripts",
    "scripts",
    "PROCESS.md",
    "web/vitest.config.ts",
    # Joined when `build.inlineStylesheets` became load-bearing: the globe's own 12 KB sheet sits
    # just past Vite's 4 KB inline limit, so the default 'auto' left it blocking first paint.
    "web/astro.config.ts",
    # Joined for the portrait fill rung: the srcset ladder is decided in the PIPELINE and consumed by
    # the page, so the mutations that matter (a rung that stops being produced, an overlay that
    # stops sharing the ladder) can only be made here.
    "pipeline/compose",
    # A single test file, on the same principle as PROCESS.md above. The mobile ladder contract
    # carries an exemption list, and a skip-list nobody can mutate is a skip-list nobody can prove
    # is still doing anything — which is the failure mode it exists to prevent.
    "tests/test_hero_variants.py",
    # The bulk-edit guard, which is a PARSER and therefore both guard and subject. Its checks read
    # every tracked text file, so it is the one place where a wrong answer is spread across the whole
    # repo and blamed on whichever file happens to expose it — the reason it earns mutation coverage
    # is that its failures name the wrong line by construction.
    "tests/test_repo_integrity.py",
    # Joined for the body registry. Its whole safety story is a set of bridge tests holding the
    # duplicated constants (`EARTH_RADIUS` twice, `EXAGGERATION` once) to the registry's copy until
    # each original is deleted — and a bridge nobody can mutate is a bridge nobody can prove is
    # load-bearing. The look package as a whole, because the parameterisation touches all of it.
    "pipeline/bodies.py",
    "pipeline/render",
    # Joined with the required `--body`. The planet entry points are where a silent Earth assumption
    # would be reintroduced, and it is invisible while Earth is the only body — so the guards against
    # it are worth exactly as much as the proof that they still fire.
    "pipeline/tile",
    # Joined with the Mars DEM recipe, and for the sharpest version of the same argument: an
    # acquisition guard runs ONCE, against a server, before ~10.6 GiB lands. It cannot be exercised
    # by any pipeline run, it has no output to inspect, and by the time it would have mattered the
    # wrong edition is already on disk. Mutation is the only proof available that it still fires.
    "pipeline/acquire",
    # Joined with the HTTP identity, whose failure mode is the least visible in the package: every
    # acquisition test mocks the network, so a missing header is invisible to the suite, and every
    # host WITHOUT bot protection serves us anyway, so it is invisible to a run. It surfaced as a
    # 403 on a 10.6 GiB download and could only have surfaced that way.
    "pipeline/fetch.py",
    # Joined with the planet seam, the one contract two different tiers write and two more read. Its
    # whole job is to keep three situations apart — no mask, no producer, a crashed producer — and
    # every way of collapsing them leaves a module that imports and answers. There is no output to
    # inspect either: the failure is a planet that shades from half a fusion and reports DONE.
    "pipeline/planet_seam.py",
    "pipeline/fuse",
    # Joined with the one home for Natural Earth, and for a reason particular to this seam: every
    # way of breaking it is invisible on a developer box, where `MAPS_DATA` is unset and the two
    # roots resolve to the same directory. Its guards therefore never fire during ordinary work,
    # and a guard that never fires is one nobody can tell apart from a guard that cannot.
    "pipeline/naturalearth.py",
    # Joined with the hero pipeline's paths. This is the one tier whose stages talk to each other in
    # SHELL STRINGS rather than in Python values, so its wiring is invisible to both the type
    # checker and the import probe — the only proof that anything watches it is breaking it.
    "pipeline/frame",
    "pipeline/batch.py",
    # A second single test file, on `tests/test_hero_variants.py`'s principle. The store probe's
    # PREDICATE lives in the test module, so the predicate is both guard and subject, and there is
    # nowhere else to break it. It has now been wrong in both directions — blind to a spelling
    # three times, then reporting sixteen correct constants as offenders because CI checks out
    # under a directory named `work` — and neither direction is visible from this machine.
    "tests/test_paths.py",
    # Same principle as the two test files above: the import scan IS the guard, so the
    # only way to prove it still sees anything is to narrow it and watch something fail.
    "tests/test_fetch.py",
    # Joined with the look seam, on the principle the test files above share: the ramp-bypass sweep
    # IS the guard, so the only way to prove it still reads the shading path is to narrow its walk
    # and watch something fail. Narrowing is also the realistic mistake — the scan sits in a
    # palette test, and scoping it to the render package reads as tidying rather than gutting.
    "tests/test_palette.py",
    # Joined with the output licence, which is stated in four files and was checked in none. Two
    # roots, for two different reasons. `LICENSE` because it is a mutation TARGET no other root
    # reaches — it has no extension, sits outside every package, and is the copy a reader treats as
    # authoritative. `tests/test_attributions.py` because its sweep is guard and subject both: the
    # suffix set decides which files are read at all, so narrowing it silences the check from the
    # inside while every assertion still passes.
    "LICENSE",
    "tests/test_attributions.py",
    # The fourth on that principle, and the sharpest: the cross-language parity guard has to PARSE
    # `web/src/lib/bodies.ts` to compare it, so its brace counter is both guard and subject. A
    # counter that stops counting still returns blocks, still finds a body, and reads the wrong
    # planet's answer — a failure with no error and no output to inspect.
    "tests/test_bodies.py",
    # Joined when the pass's memory cap stopped being one number. The harness is a SHELL SCRIPT, so
    # neither pyright nor ruff reads it, and every way of reverting it leaves a script that runs and
    # prints a plausible preflight line — the cap is simply the wrong planet's. Its two failure
    # directions are also both expensive and neither is a crash at the edit: too high refuses a pass
    # the box could have run, too low OOM-kills hours in.
    "pipeline/profile",
)

# Set for the duration of one case, so the backup THIS run is holding does not trip the leftover
# canary in tests/test_sabotage_cases.py. Narrow on purpose: any other stray backup still fires.
IN_FLIGHT_ENV = "TERRELLA_SABOTAGE_IN_FLIGHT"


class Suite(NamedTuple):
    """How to run one suite, and how to read a failing test's name back out of its output."""

    command: list[str]
    cwd: str
    environment: dict[str, str]
    # Vitest prints ` FAIL  <file> > <describe> > <title>`; pytest prints `FAILED <file>::<name>`.
    # `guard` is matched against the whole output, so it may be any substring of the name.
    #
    # The vitest form gains a `|browser (chromium)|` segment for the browser project and NOT for
    # node, so the project label has to be optional. Judging never noticed, because it greps the
    # whole output — but `--harvest` reads this pattern, and without the optional segment it
    # reported "(nothing failed)" for a case three browser tests were in fact catching. Harvest is
    # exactly the tool you reach for when you do not yet know which test catches a case, so a blind
    # spot there reads as "nothing guards this".
    fail_pattern: re.Pattern[str]


SUITES: dict[str, Suite] = {
    "web": Suite(
        command=["pnpm", "run", "test"],
        cwd="web",
        environment={},
        fail_pattern=re.compile(r"^\s*FAIL\s+(?:\|[^|]*\|\s+)?\S+\s+>\s+(.+)$"),
    ),
    "python": Suite(
        command=["uv", "run", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=".",
        environment={"PYTHONDONTWRITEBYTECODE": "1"},
        fail_pattern=re.compile(r"^FAILED\s+\S+::([^\s\[]+)"),
    ),
    # Not a test framework: a script that names its own failing check, so a case here is held to
    # the same standard as one naming a vitest title or a pytest function.
    "collection": Suite(
        command=["node", "scripts/check_test_collection.ts"],
        cwd="web",
        environment={},
        fail_pattern=re.compile(r"^✗ test collection: (\S+)$"),
    ),
}


class Sabotage(NamedTuple):
    """One mutation: replace `needle` with `replacement` in `path`, expect `guard` to fail.

    `guard` is the failing test's name — a vitest title or a pytest function — and it is mandatory.
    It was optional for one draft, on the theory that the forty cases imported from earlier one-off
    runs had no recorded intent; but `--harvest` recovers the name in two seconds a case, so the
    optional tier bought nothing and would have left two standards of proof looking like one.

    An empty `needle` means a CREATION case: `path` must not exist, and the mutation is to write
    `replacement` there and delete it afterwards. Some subjects are the presence of a file, not a
    line in one.
    """

    suite: str
    label: str
    path: str
    needle: str
    replacement: str
    guard: str


SABOTAGES: list[Sabotage] = [
    # --- repo structural integrity: the bulk-edit corruption guard -------------------------------
    # Every case below is a REAL corruption a repo-wide regex produced, not an invented one. The
    # first two are the wound that mattered: a deleted `*/` does NOT leave a comment open at EOF
    # (the next comment's terminator closes it), so an end-of-file check reports clean while real
    # exports sit commented out. That check was written, shipped, and found vacuous by this table.
    Sabotage(
        suite='python',
        label='delete a closing */ so a doc comment swallows an export',
        path='web/src/lib/terrainSource.ts',
        # Re-anchored: this block gained a closing paragraph, so the `*/` moved off the line the
        # needle named. The case is about the LAST line of the comment above an export, which is a
        # position rather than a sentence — so it re-anchors whenever that block is edited.
        needle=' *  made to fail. Threading the archive is what makes it checkable before a second body has one. */',
        replacement=' *  made to fail. Threading the archive is what makes it checkable before a second body has one.',
        guard='test_no_block_comment_swallows_a_declaration',
    ),
    Sabotage(
        suite='python',
        label='delete the second closing */ (TERRAIN_TILE_SIZE this time)',
        path='web/src/lib/terrainSource.ts',
        needle=' *  DEM\'s. `terrainZoomsFor` has the arithmetic right and its tests pin it against two live reads. */',
        replacement=' *  DEM\'s. `terrainZoomsFor` has the arithmetic right and its tests pin it against two live reads.',
        guard='test_no_block_comment_swallows_a_declaration',
    ),
    Sabotage(
        suite='python',
        label='clip the closing pipe off a markdown table row',
        path='PROCESS.md',
        needle='| 1 | warp height → 3857 | **6:49** | ~0 s | `height_3857.tif` 44 GB | `is_stale` |',
        replacement='| 1 | warp height → 3857 | **6:49** | ~0 s | `height_3857.tif` 44 GB | `is_stale`',
        guard='test_markdown_table_rows_are_terminated',
    ),
    Sabotage(
        suite='python',
        label='leave a code fence unclosed',
        path='PROCESS.md',
        needle='```mermaid',
        replacement='```mermaid\n```extra',
        guard='test_code_fences_are_balanced',
    ),
    Sabotage(
        suite='python',
        label='cite a working document from a file that ships',
        path='web/src/lib/assetBase.ts',
        needle='// The tile base is the one',
        replacement='// See ' + 'HISTORY' + ' \u00a7 something.\n// The tile base is the one',
        guard='test_no_reference_to_a_file_a_clone_will_not_have',
    ),
    # --- span attribution: the three ways it could quietly start lying -------------------------------
    # All three mutations leave a report that still RENDERS and still reads plausible, which is the
    # only reason they are worth a case: a broken attribution does not throw, it just blames the
    # wrong subsystem.
    Sabotage(
        suite='web',
        label='attribution reverts to naive subtraction instead of interval intersection',
        path='web/src/lib/perf/perfTrace.ts',
        needle='  const attributedMs = Math.min(overlapMs(entries.map(toInterval), longTasks), blockedTotal);',
        replacement='  const attributedMs = Math.min(entries.reduce((sum, entry) => sum + entry.duration, 0), blockedTotal);',
        guard='does not go negative when a span runs across SHORT tasks',
    ),
    Sabotage(
        suite='web',
        label='dropped long-task windows stop being counted, so a partial reading reads as whole',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='    tally.longTaskIntervalsDropped += 1;',
        replacement='',
        guard='stops retaining windows at the ceiling and COUNTS what it dropped',
    ),
    Sabotage(
        suite='web',
        label='an unarmed instrument reports as an empty one',
        path='web/src/lib/perf/perfSnapshot.ts',
        needle='  if (!report.traceArmed) {',
        replacement='  if (report.traceArmed) {',
        guard='distinguishes an instrument that never armed from one that found nothing',
    ),

    # --- GL context-loss recovery and the DEM cache cap (2026-07-29) ---------------------------------
    Sabotage(
        suite='web',
        label='cap ordering: put applyCacheCap back BEFORE setTerrain',
        path='web/src/components/Globe.astro',
        needle='      map.setTerrain({ source: TERRAIN_SOURCE, exaggeration: exaggerationFor(map.getZoom()) });\n      applyCacheCap();',
        replacement='      applyCacheCap();\n      map.setTerrain({ source: TERRAIN_SOURCE, exaggeration: exaggerationFor(map.getZoom()) });',
        guard='caps the DEM cache AFTER setTerrain, which is what builds the manager it lands on',
    ),
    Sabotage(
        suite='web',
        label='recovery watch no longer re-adds the polar caps',
        path='web/src/components/Globe.astro',
        needle='        reassertPolarCaps();\n',
        replacement='',
        guard='puts back what a restore silently drops, once the map reads healthy',
    ),
    Sabotage(
        suite='web',
        label='recovery watch no longer re-asserts the DEM bound',
        path='web/src/components/Globe.astro',
        needle='        reassertTerrainBound();\n',
        replacement='',
        guard='puts back what a restore silently drops, once the map reads healthy',
    ),
    Sabotage(
        suite='web',
        label='loss handler stops starting the watch (back to event-driven recovery)',
        path='web/src/components/Globe.astro',
        needle='    startRecoveryWatch(performance.now() + GL_RESTORE_GRACE_MS);',
        replacement='',
        guard='starts the recovery watch from the LOSS, because the restore event may never fire',
    ),
    Sabotage(
        suite='web',
        label='loss handler stops charging the recurrence budget',
        path='web/src/components/Globe.astro',
        needle='    if (recoveryVerdict(chargedLosses) === "give-up") {',
        replacement='    if (false) {',
        guard='bounds recovery by recurrence rather than trying to read a cause that does not exist',
    ),
    Sabotage(
        suite='web',
        label='cap re-assertion reports without repairing',
        path='web/src/components/Globe.astro',
        needle='        applyCacheCap();\n        console.info(`[terrain] DEM cache cap was not in force',
        replacement='        console.info(`[terrain] DEM cache cap was not in force',
        guard='REPAIRS a dropped cap before reporting it, and lets the next idle be the judge',
    ),
    Sabotage(
        suite='web',
        label='cap re-assertion verifies its own write synchronously (the stale-oracle bug)',
        path='web/src/components/Globe.astro',
        needle='        applyCacheCap();\n        console.info(',
        replacement='        applyCacheCap();\n        demCacheCapFault(map.style?.tileManagers?.[TERRAIN_SOURCE], intendedCacheSlots);\n        console.info(',
        guard='REPAIRS a dropped cap before reporting it, and lets the next idle be the judge',
    ),
    Sabotage(
        suite='web',
        label='polar cap re-add stops clearing the dead layers first',
        path='web/src/components/Globe.astro',
        needle='        if (map.getLayer(layerId)) map.removeLayer(layerId);',
        replacement='        void layerId;',
        guard='re-adds the caps on recovery, from OUTSIDE style.load, because that ordering is too early',
    ),
    Sabotage(
        suite='web',
        label='restore handler touches the notice again (the original bug)',
        path='web/src/components/Globe.astro',
        needle='    window.clearTimeout(restoreWatchdog);\n    startRecoveryWatch(performance.now());',
        replacement='    window.clearTimeout(restoreWatchdog);\n    glLostNotice?.setAttribute("hidden", "");\n    startRecoveryWatch(performance.now());',
        guard='NEVER hides the notice on the restore event alone — this is the whole bug',
    ),
    Sabotage(
        suite='web',
        label='amnesty window stops expiring old losses',
        path='web/src/lib/glDiagnostics.ts',
        needle='    (previous) => lostAtMs - previous <= GL_LOSS_AMNESTY_MS,',
        replacement='    () => true,',
        guard='forgives losses older than the amnesty, so a long-lived tab is not sentenced by its morning',
    ),
    Sabotage(
        suite='web',
        label='budget stops ever giving up',
        path='web/src/lib/glDiagnostics.ts',
        needle='  return chargedLosses.length > GL_RECOVERY_ATTEMPT_LIMIT ? "give-up" : "recover";',
        replacement='  return chargedLosses.length > 9999 ? "give-up" : "recover";',
        guard='stops at the third loss in the window — the incident logged four',
    ),
    # --- the z0 relief base pin (2026-07-29) ---------------------------------------------------------
    Sabotage(
        suite='web',
        # Re-anchored when both source specs left the page for a module that a test can import. The
        # mutation is the same one and it got MORE plausible in the move: the body's ceiling is now
        # two lines above, so writing it here reads as removing an inconsistency.
        label='base source uncapped — maxzoom follows relief, losing the one-tile guarantee',
        path='web/src/lib/reliefSources.ts',
        needle='    maxzoom: RELIEF_BASE_MAX_ZOOM,',
        replacement='    maxzoom: archive.maxZoom,',
        guard='caps the base source at z0 for every body, because that is what makes it unmissable',
    ),
    Sabotage(
        suite='web',
        # The defect this whole split exists to make impossible. Earth's pyramid is cut to z8 and
        # Mars's to z6, so Earth's numbers written out here — which is what the page held until the
        # registry became the source of truth — make a Mars globe request two levels that were never
        # cut. Nothing errors: the address is refused without a storage read, so the tiles simply
        # never arrive and the globe looks slow rather than wrong.
        label='the relief source takes Earth\'s zoom range instead of the body\'s',
        path='web/src/lib/reliefSources.ts',
        needle='    minzoom: archive.minZoom,\n    maxzoom: archive.maxZoom,',
        replacement='    minzoom: 0,\n    maxzoom: 8,',
        guard='takes each body\'s own zoom range from the registry, never Earth\'s constants',
    ),
    Sabotage(
        suite='web',
        label='the constant itself drifts off 0',
        path='web/src/lib/reliefTiles.ts',
        needle='export const RELIEF_BASE_MAX_ZOOM = 0;',
        replacement='export const RELIEF_BASE_MAX_ZOOM = 1;',
        guard='caps the base source at z0 for every body, because that is what makes it unmissable',
    ),
    Sabotage(
        suite='web',
        label='base layer drawn OVER relief, hiding the real tiles',
        path='web/src/components/Globe.astro',
        needle='        { id: "relief", type: "raster", source: "relief", paint: { "raster-fade-duration": 0 } },\n      ],',
        replacement='      ],',
        guard='draws the base UNDER relief and OVER the background, or it is pointless',
    ),
    Sabotage(
        suite='web',
        label='base source registered but never added to the style',
        path='web/src/components/Globe.astro',
        needle='sources: { relief: reliefSource, "relief-base": reliefBaseSource },',
        replacement='sources: { relief: reliefSource },',
        guard='draws the base UNDER relief and OVER the background, or it is pointless',
    ),
    Sabotage(
        suite='web',
        label='base source grows a second attribution, doubling the credit',
        path='web/src/lib/reliefSources.ts',
        needle='    maxzoom: RELIEF_BASE_MAX_ZOOM,\n    tileSize: DECLARED_TILE_SIZE,\n  };',
        replacement=(
            '    maxzoom: RELIEF_BASE_MAX_ZOOM,\n    tileSize: DECLARED_TILE_SIZE,\n'
            '    attribution: "one archive, credited twice",\n  };'
        ),
        guard='carries no attribution, so one archive does not credit itself twice',
    ),
    # --- the terrain-retirement flag (2026-07-29) ----------------------------------------------------
    Sabotage(
        suite='web',
        label='re-assertion stops honouring the retirement flag',
        path='web/src/components/Globe.astro',
        needle='    reassertTerrainBound = () => {\n      if (terrainRetired) return;',
        replacement='    reassertTerrainBound = () => {\n      if (false) return;',
        guard='goes quiet when the FPS ladder retires terrain, instead of crying wolf about the cap',
    ),
    Sabotage(
        suite='web',
        label='applyCacheCap stops honouring the retirement flag',
        path='web/src/components/Globe.astro',
        needle='    const applyCacheCap = () => {\n      if (terrainRetired) return;',
        replacement='    const applyCacheCap = () => {\n      if (false) return;',
        guard='goes quiet when the FPS ladder retires terrain, instead of crying wolf about the cap',
    ),
    Sabotage(
        suite='web',
        label='flag raised AFTER the teardown, so an idle inside it still false-alarms',
        path='web/src/components/Globe.astro',
        needle='          terrainRetired = true;\n          map.setTerrain(null);',
        replacement='          map.setTerrain(null);\n          terrainRetired = true;',
        guard='goes quiet when the FPS ladder retires terrain, instead of crying wolf about the cap',
    ),
    # --- the ?perf instrument, Phase 1 and 2 (2026-07-29/30) -----------------------------------------
    Sabotage(
        suite='web',
        label='the origin stops distinguishing dev from a real build',
        path='web/src/lib/perf/perfSnapshot.ts',
        needle='const server = origin.devServer ? "DEV SERVER — absolutes not comparable to prod" : "static build";',
        replacement='const server = "static build";',
        guard='shouts when the numbers came from the dev server',
    ),
    Sabotage(
        suite='web',
        label='an unmeasured device class renders as a plain desktop verdict',
        path='web/src/lib/perf/perfSnapshot.ts',
        needle='` (${report.deviceClass.via}) · tier ${report.tier}` +',
        replacement='` · tier ${report.tier}` +',
        guard='never renders an unmeasured device class as a desktop reading',
    ),
    Sabotage(
        suite='web',
        label='cap bytes bill the rung being FETCHED as if it were uploaded',
        path='web/src/lib/glDiagnostics.ts',
        needle='(total, state) => total + (state.loadedRungPx ? capTextureBytes(state.loadedRungPx) : 0),',
        replacement='(total, state) => total + capTextureBytes(state.loadedRungPx ?? state.rungLoading ?? 0),',
        guard='bills nothing for a cap whose FIRST fetch is still in flight',
    ),
    Sabotage(
        suite='web',
        label='a wrong-typed elevation flag is coerced to a reading',
        path='web/src/lib/glDiagnostics.ts',
        needle='typeof implementation.elevLoaded === "boolean" ? implementation.elevLoaded : null,',
        replacement='Boolean(implementation.elevLoaded),',
        guard='reports null, not a fabricated reading, when the fields are no longer the types we read',
    ),
    Sabotage(
        suite='web',
        label='no-signal is folded into the boolean and its provenance lost',
        path='web/src/lib/polarCaps.ts',
        needle='return { mobileClass: false, via: "no-signal" };',
        replacement='return { mobileClass: false, via: "pointer-coarse" };',
        guard='reports NO SIGNAL as its own state, instead of a desktop verdict from no evidence',
    ),
    Sabotage(
        suite='web',
        # The fallback only runs where `createImageBitmap` rejects, which is no machine we own, so
        # for its whole life the branch was covered by nothing. It is also the shape a tidy-up
        # reverses without a thought — the assignment form is two lines shorter and looks equivalent.
        label='the cap Image fallback goes back to assigning onload',
        path='web/src/lib/polarCaps.ts',
        needle='      image.addEventListener("load", () => resolve(image), { once: true });',
        replacement='      image.onload = () => resolve(image);',
        guard='still uploads when the engine has no createImageBitmap and the Image path takes over',
    ),
    # --- a body fetches its OWN polar-cap manifest, and Earth's URL is not the universal one ---
    Sabotage(
        suite='web',
        # The literal this restores is not a typo — it is what shipped, correctly, for as long as
        # one planet had caps. It is also the tidy a reader makes when a derived URL looks like
        # ceremony around a constant. What makes it the worst case in this file is that it does not
        # 404: Earth's prefix is empty, so the wrong body gets a 200, a valid manifest, and Earth's
        # Arctic textures drawn over its pole at the right size.
        label='the cap manifest goes back to the literal that is really Earth-only',
        path='web/src/lib/polarCaps.ts',
        needle='const response = await fetch(manifestUrl, { cache: "no-cache" });',
        replacement='const response = await fetch("/caps/caps.json", { cache: "no-cache" });',
        guard="fetches Mars's manifest for Mars, not the one Earth has always used",
    ),
    Sabotage(
        suite='web',
        # The prefix and the slug are the same word on every body that nests, so `slug` reads as
        # the obvious simplification — and it is wrong on exactly one body, the one whose prefix is
        # deliberately empty. Every Mars URL keeps working; every Earth URL moves.
        label='the served prefix is replaced by the slug it happens to equal',
        path='web/src/lib/assetBase.ts',
        needle='["caps", BODIES[body].pathPrefix, "caps.json"]',
        replacement='["caps", body, "caps.json"]',
        guard="keeps Earth's URL byte-for-byte the one every warm browser cache already holds",
    ),
    Sabotage(
        suite='web',
        # Reverses the collapse, which is the half a reader trims when the filter looks redundant.
        # Only Earth can see it: `/caps//caps.json` is a path no server was told to write.
        label='the empty prefix stops collapsing and doubles the separator',
        path='web/src/lib/assetBase.ts',
        needle='.filter(Boolean).join("/")}`;',
        replacement='.join("/")}`;',
        guard="keeps Earth's URL byte-for-byte the one every warm browser cache already holds",
    ),
    Sabotage(
        suite='python',
        # The cross-language half, and a PYTHON case over a web file for the reason the cap-flag
        # case above gives: the pipeline is what WRITES the files, so the browser's prefix is only
        # ever the second half of that fact. A drift here cannot be seen by any type, any linter, or
        # any page that only ever loads Earth.
        label="a body's served prefix drifts to Earth's empty one",
        path='web/src/lib/bodies.ts',
        needle='    pathPrefix: "mars",',
        replacement='    pathPrefix: "",',
        guard='test_the_two_registries_agree_on_where_a_body_nests_its_served_assets',
    ),
    Sabotage(
        suite='web',
        label='the collapsed view grows past a phone corner',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='    `${tasks} · z${snapshot.zoom.toFixed(2)}`,\n  ];',
        replacement='    `${tasks}`,\n    `z${snapshot.zoom.toFixed(2)}`,\n  ];',
        guard='stays two lines, which is the bound that actually protects a phone screen',
    ),
    Sabotage(
        suite='web',
        label='a missing clipboard reports success instead of failure',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='return options.writeClipboard ? "copied" : "failed";',
        replacement='return "copied";',
        guard='reports FAILED rather than a silent success when neither path exists',
    ),
    Sabotage(
        suite='web',
        label='the collapsed view prints a measured zero in a browser with no Long Tasks API',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='  const tasks = snapshot.longTaskApiAvailable\n    ? `blocked ${ms(snapshot.longTaskTotalMs)} in ${snapshot.longTaskCount}`\n    : "blocked n/a";',
        replacement='  const tasks = `blocked ${ms(snapshot.longTaskTotalMs)} in ${snapshot.longTaskCount}`;',
        guard='carries the missing-API honesty into the collapsed view too',
    ),
    Sabotage(
        suite='web',
        label='a recovered context loss leaves no trace on the panel',
        path='web/src/lib/perf/perfSnapshot.ts',
        needle='  if (report.glLossCount > 0) {',
        replacement='  if (false) {',
        guard='names a context-loss loop, which nothing else on the panel can',
    ),
    Sabotage(
        suite='web',
        label='restoreFault asserts a cause it never checked',
        path='web/src/lib/glDiagnostics.ts',
        needle='return "MapLibre never rebuilt the style — nothing can render";',
        replacement='return "the context came back but MapLibre never rebuilt the style";',
        guard='reports the most fundamental failure first',
    ),
    Sabotage(
        suite='web',
        label='the loss line drops when the timestamp is missing',
        path='web/src/lib/perf/perfSnapshot.ts',
        needle='    lines.push({\n      group: "alarm",\n      text: `GPU CONTEXT LOST ${report.glLossCount}x this page${since}`,\n    });',
        replacement='    if (report.lastGlLossMs !== null) {\n      lines.push({ group: "alarm", text: `GPU CONTEXT LOST ${report.glLossCount}x this page` });\n    }',
        guard='still reports the count when the timestamp is missing, rather than dropping the line',
    ),
    Sabotage(
        suite='web',
        label='the requested ratio is reported as if the canvas got it',
        path='web/src/lib/perf/perfSnapshot.ts',
        needle='      : ` (realised ${origin.realisedPixelRatio.toFixed(2)} — clamped by maxCanvasSize)`;',
        replacement='      : ``;',
        guard='flags a ratio the canvas did NOT get, and stays quiet when it did',
    ),
    Sabotage(
        suite='web',
        label="the ladder reads the DISPLAY ratio again, not the map's",
        path='web/src/components/Globe.astro',
        needle='          pixelRatioLowered,\n          devicePixelRatio: map.getPixelRatio(),',
        replacement='          pixelRatioLowered,\n          devicePixelRatio: window.devicePixelRatio || 1,',
        guard="feeds the ladder the MAP's ratio, never the display's",
    ),
    Sabotage(
        suite='web',
        label='the dead-globe notice sinks back under the perf panel',
        path='web/src/components/Globe.astro',
        needle='    z-index: 50;',
        replacement='    z-index: 20;',
        guard='keeps the dead-globe notice above the ?perf panel',
    ),
    Sabotage(
        suite='web',
        label="the perf report reads the DISPLAY ratio instead of the map's",
        path='web/src/components/Globe.astro',
        needle='              devicePixelRatio: map.getPixelRatio(),',
        replacement='              devicePixelRatio: window.devicePixelRatio || 1,',
        guard="reports the MAP's ratio in the perf snapshot too, not the display's",
    ),
    Sabotage(
        suite='web',
        label='the report probes capabilities per tick again — 13.3 WebGL contexts/second',
        path='web/src/components/Globe.astro',
        needle='            signals: probedSignals,',
        replacement='            signals: probeSignals(),',
        guard="is never called from the ?perf overlay's per-tick path",
    ),
    Sabotage(
        suite='web',
        label='the tier is cached, so a mid-session quality change goes unreported',
        path='web/src/components/Globe.astro',
        needle='            tier: decideGlobeTier(probedSignals, getQuality()),',
        replacement='            tier: bootTier,',
        guard='still tracks a quality change the user makes mid-session',
    ),
    Sabotage(
        suite='web',
        # The chord comes back. `+` matches DOM order, so hiding fullscreen leaves its divider on
        # the quiet button below, and the group's 999px radius clips it into a dark arc.
        label='quiet mode keeps the divider of the button it hid',
        path='web/src/styles/globe.css',
        needle='  border-top-width: 0;',
        replacement='  border-top-width: 1px;',
        guard='cancels the hairline on the button after the hidden fullscreen control',
    ),
    Sabotage(
        suite='web',
        # The specificity, tidied away. `body.is-quiet .rg-ctrl-quiet` is the obvious way to write
        # this cancel and it is (0,3,1) against a (0,4,2) divider — it loses, silently.
        label="the divider cancel is rewritten without the specificity that makes it win",
        path='web/src/styles/globe.css',
        needle='  .maplibregl-ctrl-group.maplibregl-ctrl-group\n  .maplibregl-ctrl-fullscreen\n  + button {',
        replacement='  .maplibregl-ctrl-group\n  .maplibregl-ctrl-fullscreen\n  + button {',
        guard='keeps the cancel more specific than the divider it has to beat',
    ),
    Sabotage(
        suite='web',
        # The original defect restored: a side-effect import makes Vite hoist MapLibre's 70 KB
        # widget sheet into a render-blocking <link>, in front of a paint that needs none of it.
        label="MapLibre's stylesheet goes back to blocking first paint",
        path='web/src/components/MapStylesheet.astro',
        needle='import maplibreStylesheet from "maplibre-gl/dist/maplibre-gl.css?url";',
        replacement='import "maplibre-gl/dist/maplibre-gl.css";\nconst maplibreStylesheet = "";',
        guard='imports it for its URL, never for its side effect',
    ),
    Sabotage(
        suite='web',
        # The scripts-off hole. `onload` is an inline handler, so without the noscript twin a
        # visitor with JS disabled keeps media="print" forever and the controls render unstyled.
        label='the deferred stylesheet loses its noscript fallback',
        # Re-anchored when the link moved into its own component: the element no longer carries
        # `slot="head"` (a page forwards the whole component into that slot instead), so the old
        # needle named an attribute that no longer exists. Anchored at line start, because
        # `</noscript>` contains the opening tag as a substring.
        #
        # THIS CASE SURVIVED ONCE, and the survival is why the guard now reads only the template
        # half: the same move that gave the element its own file gave it the comment explaining it,
        # and a whole-file `toMatch(/<noscript>/)` was satisfied by that comment.
        path='web/src/components/MapStylesheet.astro',
        needle='\n<noscript>\n',
        replacement='\n<template>\n',
        guard='links it non-blocking, with the noscript twin that makes that safe',
    ),
    Sabotage(
        suite='web',
        # The other half of the same element, and vacuous by the same mechanism until now: the
        # comment above the <link> quotes `media="print"` while explaining it. Without the attribute
        # the sheet is render-blocking again, which is the 635 ms this whole block exists to hold.
        label='the deferred stylesheet starts blocking again, losing its print media',
        path='web/src/components/MapStylesheet.astro',
        needle='<link rel="stylesheet" href={maplibreStylesheet} media="print"',
        replacement='<link rel="stylesheet" href={maplibreStylesheet}',
        guard='links it non-blocking, with the noscript twin that makes that safe',
    ),
    Sabotage(
        suite='web',
        # THE SECOND GLOBE PAGE, which is the whole reason this guard sweeps instead of reading one
        # file. `slot` reaches the layout's head only from a direct child of the component call, so
        # a page that omits this line links MapLibre's sheet nowhere and every widget on that
        # planet renders unstyled — while Earth, the page the guard used to read, stays perfect.
        label="Mars's globe stops forwarding MapLibre's stylesheet into the head",
        path='web/src/pages/mars.astro',
        needle='  <Fragment slot="head"><MapStylesheet /></Fragment>\n',
        replacement='',
        guard='puts it in the head, where the preload scanner finds it during the first parse',
    ),
    Sabotage(
        suite='web',
        # And the narrowing itself, restored: the sweep is pointed back at the one page it read
        # before there were two. Every remaining globe page passes for free, which is exactly what
        # the old version did — so this is caught by the anti-vacuity check or by nothing.
        label='the globe-page sweep is narrowed back to Earth, and the rest pass by not being read',
        path='web/src/lib/criticalCss.test.ts',
        needle='const globePages = pages.filter((page) => /<Globe\\s*\\/>/.test(page.text));',
        replacement='const globePages = pages.filter((page) => page.name === "earth.astro");',
        guard='knows which pages draw a globe, in both directions',
    ),
    Sabotage(
        suite='web',
        # Deferring MapLibre's sheet buys nothing while OUR 12 KB one still blocks — and at Vite's
        # default 4 KB inline limit, 'auto' leaves it linked. This is the half that carries the win.
        label="the page's own stylesheet goes back to a blocking request",
        path='web/astro.config.ts',
        needle="    inlineStylesheets: 'always',",
        replacement="    inlineStylesheets: 'auto',",
        guard='astro.config sets inlineStylesheets to always',
    ),
    Sabotage(
        suite='web',
        # The clamp disarmed. Without it the report, and before it the view bar, can say `gallery`
        # about a page that is demonstrably running the globe — which is exactly the contradiction
        # that hid the downlink defect, because the chip renders `gallery` and `globe` identically.
        # Two leading spaces are load-bearing: the other `return "globe";` in this file sits after
        # a `)` on the soft-signal line and must not be the one that gets rewritten.
        label='the globe page stops clamping a soft gallery verdict',
        path='web/src/lib/capability.ts',
        needle='  return "globe";',
        replacement='  return "gallery";',
        guard='clamps a soft demotion to globe, where plain decideTier says gallery',
    ),
    Sabotage(
        suite='web',
        label='probeSignals leaks the context it created',
        path='web/src/lib/capability.ts',
        needle='      gl.getExtension("WEBGL_lose_context")?.loseContext();',
        replacement='',
        guard='releases the context it creates, not just the canvas',
    ),
    Sabotage(
        suite='web',
        # The shipped defect, restored exactly: `downlink` is 0 until the browser has observed
        # enough traffic to estimate, so a cold load read as slower than 1.5 Mbps and decideTier
        # sent it to `gallery` — measured live at `tier gallery` on a globe running at 243 fps.
        label='an unmeasured downlink counts as a slow link again',
        path='web/src/lib/capability.ts',
        needle='  if (downlinkMbps === undefined || downlinkMbps === 0) return false;',
        replacement='  if (downlinkMbps === undefined) return false;',
        guard='does NOT treat zero as slow',
    ),
    Sabotage(
        suite='web',
        label='the export stops recording whether the instrument was displaying',
        path='web/src/lib/perf/perfSnapshot.ts',
        needle='    ` · panel ${origin.panelExpanded ? "expanded" : "collapsed"}`',
        replacement='    ``',
        guard='records whether the INSTRUMENT was displaying — the variable that invalidated two nights',
    ),
    Sabotage(
        suite='web',
        label='the megabyte formatter switches to SI units',
        path='web/src/lib/format.ts',
        needle='(bytes / (1024 * 1024)).toFixed(0)',
        replacement='(bytes / (1000 * 1000)).toFixed(0)',
        guard='counts MEBIbytes, not megabytes — the unit the GPU and the cache budget are written in',
    ),
    Sabotage(
        suite='web',
        label='the perf overlay stops receiving the DEM cache line',
        path='web/src/components/Globe.astro',
        needle='                  ...demCache().map((text) => ({ group: "ram" as const, text })),',
        replacement='',
        guard='surfaces the line through the perf overlay, so it is visible in Zen without devtools',
    ),
    # --- the four instrument fixes and the lazy boundary (2026-07-30) --------------------------------
    Sabotage(
        suite='web',
        label='helper stops rejecting an empty read',
        path='web/src/components/Globe.astro',
        needle='return snapshotHasContent(snapshot) ? snapshot : null;',
        replacement='return snapshot;',
        guard='rejects an empty read at the single place a routine sample is taken',
    ),
    Sabotage(
        suite='web',
        label='an empty idle read erases the healthy sample',
        path='web/src/components/Globe.astro',
        needle='lastHealthyGlState = sampledGlState() ?? lastHealthyGlState;',
        replacement='lastHealthyGlState = sampledGlState();',
        guard='never overwrites the healthy sample with an empty read',
    ),
    Sabotage(
        suite='web',
        label='export stops taking a fresh sample',
        path='web/src/components/Globe.astro',
        needle='{ sampleGlNow: true }',
        replacement='{ sampleGlNow: false }',
        guard='takes a FRESH sample on export and the stale one on the panel tick',
    ),
    Sabotage(
        suite='web',
        label='the 300 ms panel tick opts into per-tick sampling',
        path='web/src/components/Globe.astro',
        needle='perfReportLines(composeReport(timing, { expanded: true }))',
        replacement='perfReportLines(composeReport(timing, { expanded: true }, { sampleGlNow: true }))',
        guard='takes a FRESH sample on export and the stale one on the panel tick',
    ),
    Sabotage(
        suite='web',
        label='the fresh/stale switch is bypassed entirely',
        path='web/src/components/Globe.astro',
        needle='gl: (sampleGlNow ? sampledGlState() : null) ?? lastHealthyGlState,',
        replacement='gl: lastHealthyGlState,',
        guard='takes a FRESH sample on export and the stale one on the panel tick',
    ),
    Sabotage(
        suite='web',
        label='the seam is removed, so scripted A/Bs silently lose the camera',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='  window.terrellaMap = map;',
        replacement='  // seam removed',
        guard='lives in the lazily-imported instrument, so an ordinary visit cannot reach it',
    ),
    Sabotage(
        suite='web',
        label='the page writes the seam itself, where nothing structural gates it',
        path='web/src/components/Globe.astro',
        needle='    const probedSignals = probeSignals();',
        replacement='    window.terrellaMap = map;\n    const probedSignals = probeSignals();',
        guard='is not also written from the page, where nothing structural would gate it',
    ),
    Sabotage(
        suite='web',
        label='a retained rate is presented as a live one',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='  const rate = snapshot.fps === null ? "fps — (idle)" : `fps ${snapshot.fps}`;',
        replacement='  const rate = `fps ${snapshot.fps ?? snapshot.lastActiveFps}`;',
        guard='still says idle, and still dates the retained rate',
    ),
    Sabotage(
        suite='web',
        label='the retained rate loses its age',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='      text: `last drew ${snapshot.lastActiveFps} fps, ${seconds(snapshot.lastActiveFpsAgeMs)} ago`,',
        replacement='      text: `last drew ${snapshot.lastActiveFps} fps`,',
        guard='reports the rate an idle map last drew at, because settling is what erases it',
    ),
    Sabotage(
        suite='web',
        label='retention drops the reading instead of carrying it',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='return liveFps === null ? retained : { fps: liveFps, measuredAtMs: nowMs };',
        replacement='return { fps: liveFps, measuredAtMs: nowMs };',
        guard='carries the last active rate across an idle map, and dates it',
    ),
    Sabotage(
        suite='web',
        label='retention re-stamps the time on every idle tick, so the age never grows',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='return liveFps === null ? retained : { fps: liveFps, measuredAtMs: nowMs };',
        replacement='return { fps: liveFps ?? retained.fps, measuredAtMs: nowMs };',
        guard='carries the last active rate across an idle map, and dates it',
    ),
    Sabotage(
        suite='web',
        label='a live rate is shown alongside a stale one',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='  if (snapshot.fps === null && snapshot.lastActiveFps !== null && snapshot.lastActiveFpsAgeMs !== null) {',
        replacement='  if (snapshot.lastActiveFps !== null && snapshot.lastActiveFpsAgeMs !== null) {',
        guard='does not show a retained rate while a live one exists',
    ),
    Sabotage(
        suite='web',
        label='the retained rate bloats the collapsed phone view',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='export function perfCollapsedLines(snapshot: PerfSnapshot): string[] {',
        replacement="export function perfCollapsedLines(snapshot: PerfSnapshot): string[] {\n  if (snapshot.lastActiveFps !== null) return ['was ' + snapshot.lastActiveFps, 'x', 'y'];",
        guard='keeps the retained rate out of the collapsed view, which has a two-line budget',
    ),
    Sabotage(
        suite='web',
        label='the tile base is compared unresolved, silently matching nothing on dev',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='const base = new URL(tileBase, pageUrl).href;',
        replacement='const base = tileBase;',
        guard='resolves a RELATIVE tile base, which is what the dev server actually has',
    ),
    Sabotage(
        suite='web',
        label="matching compares PATHS on both sides, so another origin's tiles count as ours",
        path='web/src/lib/perf/perfNetwork.ts',
        needle='const tiles = entries.filter((entry) => entry.name.startsWith(base));',
        replacement='const tiles = entries.filter((entry) => new URL(entry.name).pathname.startsWith(new URL(base).pathname));',
        guard='does not match another origin that happens to share the path',
    ),
    Sabotage(
        suite='web',
        label='the header allowance is treated as payload',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='return Math.max(0, entry.transferSize - TRANSFER_SIZE_HEADER_ALLOWANCE);',
        replacement='return entry.transferSize;',
        guard='subtracts the mandated header allowance, so a byte count means payload',
    ),
    Sabotage(
        suite='web',
        label='an opaque reading is counted as a cache hit',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='return wireBytes(entry) === 0 && entry.encodedBodySize > 0;',
        replacement='return wireBytes(entry) === 0;',
        guard="separates 'had it already' from 'learned nothing about it'",
    ),
    Sabotage(
        suite='web',
        label='cache hits enter the median, so caching reads as a faster network',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='    if (servedFromBrowserCache(entry)) slice.fromBrowserCache++;\n    else networkDurations.push(entry.duration);',
        replacement='    if (servedFromBrowserCache(entry)) slice.fromBrowserCache++;\n    networkDurations.push(entry.duration);',
        guard='keeps cache hits out of the median, so caching cannot look like a faster network',
    ),
    Sabotage(
        suite='web',
        label='a full buffer stops announcing that the totals are a floor',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='bufferFull: entries.length >= bufferSize,',
        replacement='bufferFull: false,',
        guard='says the totals are a floor once the buffer is full',
    ),
    Sabotage(
        suite='web',
        label='an r2-derived cache verdict is revived',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='  traffic.medianNetworkDurationMs = median(networkDurations);',
        replacement='  const edgeHit = false;\n  void edgeHit;\n  traffic.medianNetworkDurationMs = median(networkDurations);',
        guard='derives no cache verdict from serverTiming anywhere in this module',
    ),
    Sabotage(
        suite='web',
        label='the buffer is never raised, so totals silently truncate at 250',
        path='web/src/components/Globe.astro',
        needle='? raiseResourceTimingBuffer(performance, RESOURCE_TIMING_BUFFER_SIZE)',
        replacement='? RESOURCE_TIMING_BUFFER_SIZE',
        guard='calls the raiser, which a test of the function alone does not check',
    ),
    Sabotage(
        suite='web',
        label='an idle with no preceding move records a fill anyway',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='  if (fill.movingSinceMs === null || fill.tilesAtMoveStart === null) return fill;',
        replacement='  if (false) return fill;',
        guard='records nothing for an idle that no move preceded',
    ),
    Sabotage(
        suite='web',
        label='a second gesture restarts the clock, reporting a long wait as a short one',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='  if (fill.movingSinceMs !== null) return fill;',
        replacement='  if (false) return fill;',
        guard='treats a second gesture inside an unsettled move as the same fill',
    ),
    Sabotage(
        suite='web',
        label='a mid-window eviction reports negative tiles',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='      tilesFetched: Math.max(0, tileCount - fill.tilesAtMoveStart),',
        replacement='      tilesFetched: tileCount - fill.tilesAtMoveStart,',
        guard='never reports negative tiles when the entry buffer evicts mid-window',
    ),
    Sabotage(
        suite='web',
        label='a stale duration is shown mid-gesture instead of saying it is moving',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='  if (fill.movingSinceMs !== null) return { group: "feel", text: "fill · moving…" };',
        replacement='  if (false) return null;',
        guard='says it is moving rather than showing a stale duration mid-gesture',
    ),
    Sabotage(
        suite='web',
        label='a page statically VALUE-imports the instrument, shipping it to every visitor',
        path='web/src/components/Globe.astro',
        needle='  import type { CameraFill } from "../lib/perf/perfNetwork";',
        replacement='  import { newCameraFill } from "../lib/perf/perfNetwork";',
        guard='is never statically VALUE-imported by a page',
    ),
    Sabotage(
        suite='web',
        label='an instrument module stops loading dynamically',
        path='web/src/components/Globe.astro',
        needle='import("../lib/perf/perfNetwork"),',
        replacement='import("../lib/perf/perfNetworkX"),',
        guard='is reached only through a dynamic import, or through a sibling that is',
    ),
    Sabotage(
        suite='web',
        label='the directory sweep is emptied, so it would pass by finding nothing',
        path='web/src/lib/perf/lazyBoundary.test.ts',
        needle='.filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts"))',
        replacement='.filter((name) => name.endsWith(".nope"))',
        guard='has modules to check, so the sweep below cannot pass by finding nothing',
    ),
    Sabotage(
        suite='web',
        # The OTHER way this sweep empties, and the one it actually suffered: not a filter that
        # matches nothing, but a walk that never descends. `src/` has no .astro at its top level, so
        # dropping the recursion silently reduces the subject to zero while the filter still looks
        # right. The rule this protects — no page value-imports the perf instrument — would then be
        # asserted over nothing, which is how it passed with the globe's script outside its scope.
        label='the template walk stops descending, so it sweeps a directory with no templates in it',
        path='web/src/lib/perf/lazyBoundary.test.ts',
        needle='readdirSync(SOURCE_ROOT, { recursive: true })',
        replacement='readdirSync(SOURCE_ROOT)',
        guard='has modules to check, so the sweep below cannot pass by finding nothing',
    ),
    Sabotage(
        suite='web',
        # Same mutation, other sweep. Both walk src/ for templates and both are worth their own case:
        # they are separate copies of one shape, and a copy that stops recursing takes only its own
        # rule down with it.
        label='the comment sweep stops descending, and its rule is asserted over nothing',
        path='web/src/lib/astroTemplates.test.ts',
        needle='readdirSync(SOURCE_ROOT, { recursive: true })',
        replacement='readdirSync(SOURCE_ROOT)',
        guard='is actually found by the sweep, across all three template directories',
    ),
    Sabotage(
        suite='web',
        # The regression itself. Astro strips an HTML comment out of slot children and NOT out of a
        # component's own template, so these shipped to every visitor the moment the globe's markup
        # became a component — build green, page identical, only a byte-diff of dist/ saying so.
        # The needle swaps the opening delimiter alone because that is what the rule keys on; a
        # reader tidying the comment converts both ends, and this catches that identically.
        label='an HTML comment returns to a template, and ships to every visitor',
        path='web/src/components/Globe.astro',
        needle='{/* Names whatever the pointer is on',
        replacement='<!-- Names whatever the pointer is on',
        guard='writes its comments in the form that never reaches a visitor',
    ),
    Sabotage(
        suite='web',
        label='an instrument module re-exports the exempt raiser, dragging the chunk back',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='export function wireBytes(',
        replacement='export { raiseResourceTimingBuffer } from "../resourceTimingBuffer";\nexport function wireBytes(',
        guard='does not re-export the always-shipped buffer raiser back into this directory',
    ),
    Sabotage(
        suite='web',
        label='the buffer raise moves AFTER the map, so early entries are lost in silence',
        path='web/src/components/Globe.astro',
        needle='  const resourceTimingBufferSize = urlFlags.has("perf")\n    ? raiseResourceTimingBuffer(performance, RESOURCE_TIMING_BUFFER_SIZE)\n    : null;',
        replacement='  const resourceTimingBufferSize: number | null = null;',
        guard='calls the raiser, which a test of the function alone does not check',
    ),
    # --- the panel's subsystem grouping, web/src/lib/perf/perfLines.ts (2026-07-30) ---------------
    # Every case here breaks a placement rather than a number, because that is what this layer is:
    # the numbers were already correct and unreadable. A grouping defect is silent by nature — the
    # panel still renders, still holds every reading, and simply says the wrong thing about which
    # subsystem owns one.
    Sabotage(
        suite='web',
        label='the group order is scrambled, so the panel reads in an arbitrary sequence',
        path='web/src/lib/perf/perfLines.ts',
        needle='  "alarm",\n  "feel",\n  "cpu",\n  "network",\n  "gpu",\n  "ram",\n  "device",\n  "config",\n  "origin",\n];',
        replacement='  "cpu",\n  "feel",\n  "alarm",\n  "network",\n  "gpu",\n  "ram",\n  "device",\n  "config",\n  "origin",\n];',
        guard='keeps the two positional promises: alarms first, origin last',
    ),
    Sabotage(
        suite='web',
        label='a group is dropped from the order, so its lines vanish without a trace',
        path='web/src/lib/perf/perfLines.ts',
        needle='  "ram",\n  "device",\n  "config",\n  "origin",\n];',
        replacement='  "device",\n  "config",\n  "origin",\n];',
        guard='orders every group exactly once — a group missing here renders NO lines at all',
    ),
    Sabotage(
        suite='web',
        label='the empty-group skip is deleted, so headings render over nothing',
        path='web/src/lib/perf/perfLines.ts',
        needle='    if (inGroup.length === 0) continue;',
        replacement='    if (inGroup.length < 0) continue;',
        guard='omits a group with no lines entirely — no orphan heading, no double blank',
    ),
    Sabotage(
        suite='web',
        label='the blank separator leads the panel, so it opens on an empty row',
        path='web/src/lib/perf/perfLines.ts',
        needle='    if (rendered.length > 0) rendered.push("");',
        replacement='    rendered.push("");',
        guard='separates groups rather than introducing them — never leads or trails with a blank',
    ),
    Sabotage(
        suite='web',
        label='the alarm block gets a heading, demoting the one row that must not be skipped',
        path='web/src/lib/perf/perfLines.ts',
        needle='  alarm: null,',
        replacement='  alarm: "ALARM",',
        guard='renders alarms and origin without a heading, and every subsystem with one',
    ),
    Sabotage(
        suite='web',
        label='the frame line claims a subsystem the panel cannot attribute it to',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='  lines.push({\n    group: "feel",',
        replacement='  lines.push({\n    group: "cpu",',
        guard='stays four lines, and files the load timeline apart from the frame outcome',
    ),
    Sabotage(
        suite='web',
        label='a GPU context loss is filed under GPU, where a heading demotes it',
        path='web/src/lib/perf/perfSnapshot.ts',
        needle='      group: "alarm",\n      text: `GPU CONTEXT LOST',
        replacement='      group: "gpu",\n      text: `GPU CONTEXT LOST',
        guard='files the two alarm rows OUTSIDE any subsystem, so no heading can demote them',
    ),
    Sabotage(
        suite='web',
        label='the fill line is filed as network, which is the reading already got wrong once',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='  return { group: "feel", text: `fill ${seconds}s · ${fill.last.tilesFetched} tiles` };',
        replacement='  return { group: "network", text: `fill ${seconds}s · ${fill.last.tilesFetched} tiles` };',
        guard='times one move and counts the tiles it caused',
    ),
    # --- the table's own freshness gate, tests/test_sabotage_cases.py (2026-07-30) ----------------
    Sabotage(
        suite='python',
        label='the table is emptied, so every parametrised check sweeps nothing',
        path='scripts/sabotage.py',
        needle="\n\ndef run_suite(",
        replacement="\n\nSABOTAGES = SABOTAGES[:0]\n\n\ndef run_suite(",
        guard='test_table_is_not_empty',
    ),
    Sabotage(
        suite='python',
        label='a refactor moves a needle out from under its case',
        path='web/src/lib/reliefTiles.ts',
        needle="export const RELIEF_BASE_MAX_ZOOM = 0;",
        replacement="export const RELIEF_BASE_MAX_ZOOM: number = 0;",
        guard='test_needle_matches_exactly_once',
    ),
    # The next three mutate a case in THIS file, so their needles span two lines on purpose. A
    # single-line needle quoting a line of this file matches twice — once at the real site, once
    # inside the needle literal itself — and `replace(…, 1)` would then pick by position. A needle
    # literal renders its newline as an escape, never a real one, so a two-line needle is unique.
    Sabotage(
        suite='python',
        label='a case points at a file that no longer exists',
        path='scripts/sabotage.py',
        needle="        label='the constant itself drifts off 0',\n        path='web/src/lib/reliefTiles.ts',",
        replacement="        label='the constant itself drifts off 0',\n        path='web/src/lib/reliefTilesRenamed.ts',",
        guard='test_case_path_is_inside_a_mutable_root',
    ),
    Sabotage(
        suite='python',
        label='a case escapes the mutable roots and would write to the repo root',
        path='scripts/sabotage.py',
        needle="        label='the constant itself drifts off 0',\n        path='web/src/lib/reliefTiles.ts',",
        replacement="        label='the constant itself drifts off 0',\n        path='../pyproject.toml',",
        guard='test_case_path_is_inside_a_mutable_root',
    ),
    Sabotage(
        suite='python',
        label='two cases share a label, so the harness report becomes ambiguous',
        path='scripts/sabotage.py',
        needle="        label='the constant itself drifts off 0',\n        path='web/src/lib/reliefTiles.ts',",
        replacement="        label='budget stops ever giving up',\n        path='web/src/lib/reliefTiles.ts',",
        guard='test_labels_are_unique',
    ),
    Sabotage(
        suite='python',
        label='a case names a suite that does not exist',
        path='scripts/sabotage.py',
        needle="        suite='python',\n        label='a killed run leaves the tree sabotaged',",
        replacement="        suite='vitest',\n        label='a killed run leaves the tree sabotaged',",
        guard='test_suite_is_known',
    ),
    Sabotage(
        suite='python',
        label="a guard's vitest test is renamed",
        path='web/src/lib/fpsDegradation.test.ts',
        needle="keeps the dead-globe notice above the ?perf panel",
        replacement="keeps the dead-globe notice on top",
        guard='test_guard_is_a_real_test_name',
    ),
    Sabotage(
        suite='python',
        label='a test.each PARAMETER is renamed, which no verbatim check would see',
        path='web/src/lib/glDiagnostics.test.ts',
        needle="the fields are no longer the types we read",
        replacement="the fields changed type",
        guard='test_guard_is_a_real_test_name',
    ),
    Sabotage(
        suite='python',
        label='a replacement is made a no-op, which would always report as MISSED',
        path='scripts/sabotage.py',
        needle="        needle='export const RELIEF_BASE_MAX_ZOOM = 0;',\n        replacement='export const RELIEF_BASE_MAX_ZOOM = 1;',",
        replacement="        needle='export const RELIEF_BASE_MAX_ZOOM = 0;',\n        replacement='export const RELIEF_BASE_MAX_ZOOM = 0;',",
        guard='test_replacement_changes_something',
    ),
    Sabotage(
        suite='python',
        label='a killed run leaves the tree sabotaged',
        path='web/src/lib/reliefTiles.ts' + BACKUP_SUFFIX,
        needle="",
        replacement="# left behind by a killed sabotage run\n",
        guard='test_no_sabotage_backups_are_left_in_the_tree',
    ),

    # --- terrain drape stacks (2026-07-30) --------------------------------------------------------
    # `country-hit` is a `circle` that draws nothing, and while it sat mid-order it split one drape
    # run into two — a third of the RTT pool spent on an invisible layer. The move is only durable
    # if putting it back fails something.
    Sabotage(
        suite='web',
        label='country-hit moves back above the highlight layers, costing a third drape stack',
        path='web/src/components/Globe.astro',
        needle=(
            '      if (subsystems.countries) addCountryHighlight(); // hover outline, on top so the edge is crisp\n'
        ),
        replacement=(
            '      if (subsystems.countries) addCountryHitTargets();\n'
            '      if (subsystems.countries) addCountryHighlight(); // hover outline, on top so the edge is crisp\n'
        ),
        guard='matches what the globe actually adds last',
    ),
    Sabotage(
        suite='web',
        label='the drape-type list gains circle, which would make the whole precaution pointless',
        path='web/src/lib/drapeStacks.ts',
        needle='  "color-relief",\n];',
        replacement='  "color-relief",\n  "circle",\n];',
        guard='agrees with LAYERS_TO_TEXTURES in the shipped bundle',
    ),
    Sabotage(
        suite='web',
        label='a trailing non-drapeable layer starts charging for a stack',
        path='web/src/lib/drapeStacks.ts',
        needle='    if (draped && !previousWasDraped) stacks += 1;',
        replacement='    if (draped !== previousWasDraped) stacks += 1;',
        guard='charges nothing for a non-drapeable layer at the END',
    ),

    # --- the tile Worker's fetch handler (2026-07-30) --------------------------------------------
    # Every production tile takes this path and nothing reached it until now. Each case below was
    # run by hand against the real suite before being written down, so none of them is a guess
    # about what a test would catch.
    Sabotage(
        suite='web',
        label='a cache hit stops going through respond(), freezing one origin into the cached body',
        path='web/worker/index.ts',
        needle='    if (hit) return respond(tagCache(hit, "hit"));',
        replacement='    if (hit) return tagCache(hit, "hit");',
        guard='gives two different origins two different answers off the SAME cached body',
    ),
    # The two version-prefix cases that used to sit here are GONE, and how they died is the lesson.
    # The Worker stripped the prefix itself on the way into `resolveRoute`, duplicating a rule the
    # resolver already applies; that line was deleted and a comment put in its place explaining why.
    # The comment QUOTED the deleted regex — so both needles went on matching, exactly once, in
    # prose. The freshness gate was satisfied, the harness mutated a sentence, and two guards
    # reported intact while guarding nothing. Only the MISSED verdict from running them said so.
    #
    # The rule lives in tileAddress.ts now, and so do its cases: the anchor one directly below, and
    # the character-class one beside it.
    Sabotage(
        suite='web',
        label='the legacy version prefix widens to \\w and swallows /v3x/',
        path='web/src/lib/tileAddress.ts',
        needle='const LEGACY_VERSION_PREFIX = /^\\/v\\d+\\//;',
        replacement='const LEGACY_VERSION_PREFIX = /^\\/v\\w+\\//;',
        guard='does NOT strip a segment that merely looks like one',
    ),
    # Reordered rather than deleted, on purpose. Dropping the `try {` leaves a dangling `} catch`
    # — a SYNTAX error, which the compiler catches and no test ever sees, so the case reported
    # WRONG/(unparsed) rather than naming a guard. A mutation has to compile to prove anything.
    Sabotage(
        suite='web',
        label='the index load moves back outside the try, so a missing archive 500s instead of 404ing',
        path='web/worker/index.ts',
        needle=(
            '    try {\n'
            '      // The index is fetched whole, once, and then reused three ways: within this request, across\n'
            '      // requests in this isolate (DIRECTORY_CACHE), and across isolates (the Cache API entry below,\n'
            '      // which is colo-local and long-lived — live tiles come back with `age` in the tens of\n'
            '      // thousands of seconds, far longer than any isolate survives).\n'
            '      const index = await loadArchiveIndex(env.ARCHIVE, archiveKey, r2Source, cache, ctx, request);\n'
            '      const archive = new PMTiles(\n'
            '        index ? new PrefetchedIndexSource(r2Source, index) : r2Source,\n'
            '        DIRECTORY_CACHE,\n'
            '        nativeDecompress,\n'
            '      );\n'
        ),
        replacement=(
            '    const index = await loadArchiveIndex(env.ARCHIVE, archiveKey, r2Source, cache, ctx, request);\n'
            '    const archive = new PMTiles(\n'
            '      index ? new PrefetchedIndexSource(r2Source, index) : r2Source,\n'
            '      DIRECTORY_CACHE,\n'
            '      nativeDecompress,\n'
            '    );\n'
            '    try {\n'
        ),
        guard='answers 404 when the bucket has no such object',
    ),
    Sabotage(
        suite='web',
        label='ALLOWED_ORIGIN unset starts meaning "allow anyone"',
        path='web/worker/index.ts',
        needle='  if (allowed && (allowed === "*" || allowed === requestOrigin)) {',
        replacement='  if (!allowed || allowed === "*" || allowed === requestOrigin) {',
        guard='sends no allow-origin at all when ALLOWED_ORIGIN is unset',
    ),
    Sabotage(
        suite='web',
        label='Timing-Allow-Origin narrows to the allowlist, blinding Resource Timing off-origin',
        path='web/worker/index.ts',
        needle='  headers.set("Timing-Allow-Origin", "*");',
        replacement='  if (allowed === requestOrigin) headers.set("Timing-Allow-Origin", "*");',
        guard='keeps Timing-Allow-Origin wide open even when ACAO is narrowed',
    ),
    Sabotage(
        suite='web',
        label='the method gate lets a write through to the archive',
        path='web/worker/index.ts',
        needle='    if (request.method !== "GET" && request.method !== "HEAD") {',
        replacement='    if (request.method === "NEVER") {',
        guard='refuses a write method with 405 and never looks at the bucket',
    ),
    Sabotage(
        suite='web',
        label='the method gate rejects HEAD along with the writes',
        path='web/worker/index.ts',
        needle='    if (request.method !== "GET" && request.method !== "HEAD") {',
        replacement='    if (request.method !== "GET") {',
        guard='serves HEAD, which is not a write and must not be lumped in with one',
    ),
    # Escape belongs to the PAGE, not to this module: the globe's Escape closes the country card
    # first and only then leaves quiet. A module that swallowed it would make the card uncloseable
    # while quiet — a bug with no error, so only a guard sees it.
    Sabotage(
        suite='web',
        label='quiet mode starts acting on Escape, stealing it from the page',
        path='web/src/lib/quietMode.ts',
        needle='if (event.key.toLowerCase() !== QUIET_KEY) return;',
        replacement='if (event.key.toLowerCase() !== QUIET_KEY && event.key !== "Escape") return;',
        guard='does not act on Escape at all',
    ),
    # `title` and `aria-label` come from one writer so they cannot disagree. The button's only
    # content is a decorative masked span, so a wrong `aria-label` leaves it with no accessible
    # name at all — and nothing renders differently.
    Sabotage(
        suite='web',
        label='the rail button\'s aria-label drifts from its title',
        path='web/src/lib/railControls.ts',
        needle='button.setAttribute("aria-label", name);',
        replacement='button.setAttribute("aria-label", name.toLowerCase());',
        guard='carries title AND aria-label, in agreement',
    ),
    # Both of these SHIPPED, in the first form, and neither changed a test. A losing selector is
    # valid CSS that parses, cascades and does nothing, so the only thing that can catch it is a
    # guard that asserts the specificity itself.
    Sabotage(
        suite='web',
        label='the pressed-quiet cancel is tidied back to the selector that loses',
        path='web/src/styles/globe.css',
        needle=(
            'body.is-quiet\n'
            '  .maplibregl-ctrl-top-right\n'
            '  .maplibregl-ctrl-group.maplibregl-ctrl-group\n'
            '  .rg-ctrl-quiet[aria-pressed="true"] {'
        ),
        replacement='body.is-quiet .rg-ctrl-quiet[aria-pressed="true"] {',
        guard='never reverts to the un-doubled form that silently loses',
    ),
    Sabotage(
        suite='web',
        label='only the fill is cancelled, leaving the glyph painted in the background colour',
        path='web/src/styles/globe.css',
        needle=(
            '  .rg-ctrl-quiet[aria-pressed="true"] {\n'
            '  color: var(--muted);\n'
            '  background: none;\n'
            '}'
        ),
        replacement=(
            '  .rg-ctrl-quiet[aria-pressed="true"] {\n'
            '  background: none;\n'
            '}'
        ),
        guard='cancels BOTH the accent fill and the accent text colour, at a specificity that wins',
    ),
    # The rail's icons are masks, and every one of these mutations leaves VALID CSS that renders a
    # solid slab instead of a glyph. Nothing throws, nothing logs, and no node test can see it —
    # which is why the guards live in the browser project against the page's real stylesheet.
    # Both prefixed and unprefixed go together: Chromium honours `-webkit-mask-image` on its own,
    # so removing only one of the pair mutates nothing.
    Sabotage(
        suite='web',
        label='the icon stencil is deleted, so currentColor paints the whole button box',
        path='web/src/styles/globe.css',
        needle=(
            '  -webkit-mask-image: var(--rail-icon);\n'
            '  mask-image: var(--rail-icon);\n'
        ),
        replacement='',
        guard='gives every masked control a real stencil painted in currentColor',
    ),
    Sabotage(
        suite='web',
        label='an icon payload is truncated, which CSS accepts and SVG does not',
        path='web/src/styles/globe.css',
        needle="1.5-.75 1.5-1.5S19.75 13 19 13z'/%3E%3C/svg%3E\");",
        replacement="1.5-.75 1.5-1.5S19.75 13 19 13z'/%3E\");",
        guard='parses each data URI the page authors, and proves it found them',
    ),
    Sabotage(
        suite='web',
        label='a rail toggle is renamed past the rule that gives it an icon',
        path='web/src/components/Globe.astro',
        needle='    className: "rg-ctrl-spin",',
        replacement='    className: "rg-ctrl-orbit",',
        guard='gives every rail toggle the page builds an icon to draw',
    ),
    # The subject here is the SUITE ITSELF, which is why the guard is a script. Under this
    # mutation `pnpm test` reports `28 passed (28)` and exits 0 — measured, not assumed — so a
    # case with suite='web' would record CAUGHT for a run that noticed nothing.
    Sabotage(
        suite='collection',
        label='a vitest project glob stops matching, and the run stays green',
        path='web/vitest.config.ts',
        needle='include: ["src/**/*.browser.test.ts"],',
        replacement='include: ["src/**/*.nomatch.test.ts"],',
        guard='every-test-file-is-collected',
    ),

    # --- the scale ruler's terrain readback ---------------------------------------------------------
    # These mutations are INVISIBLE to every other signal: the page renders identically, the ruler
    # shows the same label, nothing throws, and no other test's output changes. They only cost two
    # synchronous GPU readbacks on every frame of every drag, measured at 9.8% of the main thread.
    # A guard nobody can mutate-test is a guard nobody should trust, which is why all three are here.
    # The FIRST version of this case passed vacuously and the table is why it was found: the guard
    # asserted only that `unproject` appeared after the symbol check, which the degraded path
    # satisfies whatever the primary branch does. The guard now counts them.
    Sabotage(
        suite='web',
        label='the ruler goes back to map.unproject, paying a GPU readback twice per frame',
        path='web/src/components/Globe.astro',
        needle='    return locate.call(transform, new maplibregl.Point(x, y));',
        replacement='    return map.unproject([x, y]);',
        guard='measures through the transform, not through map.unproject',
    ),
    Sabotage(
        suite='web',
        label='terrain is handed to screenPointToLocation, which is the expensive overload',
        path='web/src/components/Globe.astro',
        needle='locate.call(transform, new maplibregl.Point(x, y))',
        replacement='locate.call(transform, new maplibregl.Point(x, y), map.terrain)',
        guard='names no terrain, which is the only way to make that call read back the GPU',
    ),
    # The guard reads functions BY NAME out of the page source, so a rename is how it could go
    # vacuous — passing by finding nothing rather than by finding something correct. It must fail
    # loudly instead, and these two cases are what prove it does, one per anchored name.
    Sabotage(
        suite='web',
        label='the measured function is renamed, so a name-anchored guard could silently find nothing',
        path='web/src/components/Globe.astro',
        needle='  function updateRuler(): void {',
        replacement='  function refreshRulerReading(): void {',
        guard='keeps the per-frame path free of any unproject at all',
    ),
    Sabotage(
        suite='web',
        label='the locator function is renamed, the other half of the same vacuity risk',
        path='web/src/components/Globe.astro',
        needle='  function locateOnDatum([x, y]: [number, number]): maplibregl.LngLat {',
        replacement='  function pickLocator([x, y]: [number, number]): maplibregl.LngLat {',
        guard='measures through the transform, not through map.unproject',
    ),
    # THE ONE THAT ACTUALLY SHIPPED. Hoisting the transform lookup out of the per-call function
    # freezes the ruler at whatever camera existed when the script ran, because MapLibre replaces
    # `painter.transform` afterwards. It throws nothing, the readback stays correctly gone, and the
    # number it prints is plausible — it simply never changes again. Nothing but the label catches it.
    Sabotage(
        suite='web',
        label='the transform lookup is hoisted out of the per-call path, freezing the reading',
        path='web/src/components/Globe.astro',
        needle='    const transform = (map.painter as unknown as { transform?: Record<string, unknown> } | undefined)\n      ?.transform;',
        replacement='    const transform = hoistedTransform;',
        guard='measures through the transform, not through map.unproject',
    ),
    # --- Gallery deferral -------------------------------------------------------------------
    # Every one of these leaves a page that renders correctly on a fast link. They cost bytes, or
    # they cost a no-JS visitor the imagery — neither of which shows up as an error anywhere.
    Sabotage(
        suite='web',
        label='the eager count creeps back past the fold, re-creating the contention it removed',
        path='web/src/lib/lazyCards.ts',
        needle='export const EAGER_CARD_COUNT = 2;',
        replacement='export const EAGER_CARD_COUNT = 8;',
        guard='keeps the eager count small enough to be worth doing at all',
    ),
    # One eager card is the subtle direction: the page still works, but the measured LCP element is
    # the SECOND card, so this puts the one image that decides LCP behind script.
    Sabotage(
        suite='web',
        label='the eager count drops to one, putting the LCP image behind the observer',
        path='web/src/lib/lazyCards.ts',
        needle='export const EAGER_CARD_COUNT = 2;',
        replacement='export const EAGER_CARD_COUNT = 1;',
        guard='keeps enough cards eager for the LCP image to skip the observer entirely',
    ),
    # `src` before `srcset` starts a fetch of the fallback rung and abandons it — a wasted request
    # per card, on the one connection this whole module exists to keep clear.
    Sabotage(
        suite='web',
        label='src is assigned before srcset, so the fallback rung is fetched and abandoned',
        path='web/src/lib/lazyCards.ts',
        needle=(
            '  if (stagedSrcset !== undefined) {\n'
            '    image.srcset = stagedSrcset;\n'
            '    image.removeAttribute("data-srcset");\n'
            '  }\n'
            '  if (stagedSrc !== undefined) {\n'
            '    image.src = stagedSrc;\n'
            '    image.removeAttribute("data-src");\n'
            '  }'
        ),
        replacement=(
            '  if (stagedSrc !== undefined) {\n'
            '    image.src = stagedSrc;\n'
            '    image.removeAttribute("data-src");\n'
            '  }\n'
            '  if (stagedSrcset !== undefined) {\n'
            '    image.srcset = stagedSrcset;\n'
            '    image.removeAttribute("data-srcset");\n'
            '  }'
        ),
        guard='assigns srcset BEFORE src',
    ),
    # THE ONE I ACTUALLY SHIPPED, for one test run. Withholding `src` reads as the obviously correct
    # way to stage a URL, and it puts Chrome in the BROKEN state: a broken-image icon and the alt
    # text painted across every deferred card. Only a real renderer can see it.
    Sabotage(
        suite='web',
        label='the staged placeholder is emptied, so the alt fallback paints on every deferred card',
        path='web/src/lib/lazyCards.ts',
        needle='export const STAGED_PLACEHOLDER =\n  "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";',
        replacement='export const STAGED_PLACEHOLDER = "";',
        guard='holds a DECODED placeholder, so the alt fallback is never painted',
    ),
    # A browser too old for IntersectionObserver must still get its images. This mutation is the
    # quiet version of that bug: the function returns cleanly, and the gallery is simply blank.
    Sabotage(
        suite='web',
        label='the no-IntersectionObserver fallback stops promoting, blanking the whole gallery',
        path='web/src/lib/lazyCards.ts',
        needle='    for (const card of pending) promoteCard(card);\n    return null;',
        replacement='    return null;',
        guard='loads everything immediately when the browser has no IntersectionObserver',
    ),
    Sabotage(
        suite='web',
        label='the intersection check is dropped, so every card promotes on the first callback',
        path='web/src/lib/lazyCards.ts',
        needle='      if (!entry.isIntersecting) continue;',
        replacement='',
        guard='holds back a card parked far below the viewport',
    ),
    # The no-JS twin and the rule that hides its stand-in are one mechanism; removing either leaves
    # a scripted visitor perfectly happy and a scriptless one looking at empty cards.
    Sabotage(
        suite='web',
        label='the no-js rule goes, so the staged image pushes the twin out of the figure',
        path='web/src/pages/index.astro',
        needle='  :global(html.no-js) .card figure img[data-src] {\n    display: none;\n  }',
        replacement='',
        guard='hides the staged image when script never runs',
    ),
    Sabotage(
        suite='web',
        label='the watched set is taken with :has(), which the fallback browsers do not support',
        path='web/src/pages/index.astro',
        needle='  for (const image of document.querySelectorAll<HTMLImageElement>("img[data-src]")) {\n    const card = image.closest(".card");\n    if (card) deferredCards.add(card);\n  }',
        replacement='  for (const card of document.querySelectorAll(".card:has(img[data-src])")) {\n    deferredCards.add(card);\n  }',
        guard='derives the watched set from the staged attribute rather than repeating the card index',
    ),
    # --- The masthead's slack ------------------------------------------------------------------
    # The gallery's CLS of 0.328 was a masthead row that measured 352px inside 352px, so a 14px
    # metric change wrapped the nav and moved 203 cards. Every mutation here puts the row back
    # within a few pixels of that threshold — which is invisible in a screenshot, invisible in a
    # node test, and only shows up as content moving under a thumb on a phone.
    Sabotage(
        suite='web',
        label='the Globe link returns to the nav, refilling the row it was removed from',
        path='web/src/pages/index.astro',
        needle='      <a href="/about/">About</a>',
        replacement='      <a href="/earth/">Globe</a>\n      <a href="/about/">About</a>',
        guard='holds one layout across every heading width at 412px',
    ),
    # The subtle direction: the row still fits on THIS machine's fallback font, and stops fitting
    # on a visitor whose serif is wider. The sweep is what makes that reachable from a test.
    Sabotage(
        suite='web',
        label='the source link becomes a word again, spending the slack the icon bought',
        path='web/src/pages/index.astro',
        needle='    width: 1.05rem;\n    height: 1.05rem;',
        replacement='    width: 4rem;\n    height: 1.05rem;',
        guard='leaves the row real slack at the narrowest width it does not stack',
    ),
    Sabotage(
        suite='web',
        label='the 320px stack goes, so the narrowest phone fits by two pixels or not at all',
        path='web/src/components/Masthead.astro',
        needle=(
            '  @media (max-width: 359.98px) {\n'
            '    .masthead-row {\n'
            '      flex-direction: column;\n'
            '      align-items: flex-start;\n'
            '      gap: 0.6rem;\n'
            '    }\n'
            '  }'
        ),
        replacement='',
        guard='holds one layout across every heading width at 320px',
    ),
    # The stacked row inherits `align-items: flex-end` unless the rule overrides it, which is how
    # the first version of this shipped right-aligned against a left-aligned tagline.
    Sabotage(
        suite='web',
        label='the stacked row keeps flex-end, so the title and nav align right against everything else',
        path='web/src/components/Masthead.astro',
        needle='      flex-direction: column;\n      align-items: flex-start;',
        replacement='      flex-direction: column;',
        guard='stacks to the LEFT, aligned with everything else in the header',
    ),
    # Padding on an icon link reads as decoration and gets tidied. It is the touch target.
    Sabotage(
        suite='web',
        label='the icon link loses its padding, leaving 16.8px of ink as the whole touch target',
        path='web/src/pages/index.astro',
        needle='    padding: 0.25rem;',
        replacement='',
        guard='gives the icon link a real touch target, not just its ink',
    ),
    Sabotage(
        suite='web',
        label='the source link loses its accessible name, announcing as a bare URL',
        path='web/src/pages/index.astro',
        needle='        aria-label="Source on GitHub"\n',
        replacement='',
        guard='gives the source link an accessible name, since its only content is a decorative SVG',
    ),
    # The second of the two shifts, restored: a post-paint DOM change to the nav.
    Sabotage(
        suite='web',
        label='a script removes a masthead link again, re-arming the un-wrap half of the shift',
        path='web/src/pages/index.astro',
        needle='  import { watchDeferredCards } from "../lib/lazyCards";',
        replacement=(
            '  import { watchDeferredCards } from "../lib/lazyCards";\n'
            '  import { canRunGlobe, probeSignals } from "../lib/capability";\n'
            '  if (!canRunGlobe(probeSignals())) {\n'
            '    document.querySelector<HTMLAnchorElement>(\'.head-links a[href="/about/"]\')?.remove();\n'
            '  }'
        ),
        guard='never removes a masthead link from script',
    ),
    # Dropping the nav link orphaned /earth/ — it held the only <a> to it on the site, and the view
    # bar is display:none without JS. The About link is the replacement route, and nothing about a
    # build can see that it has gone.
    Sabotage(
        suite='web',
        label='the About page stops linking the globe, orphaning it from crawlers and no-JS',
        path='web/src/pages/about.astro',
        needle='<a href="/earth/">an interactive globe</a>',
        replacement='an interactive globe',
        guard='keeps a real, crawlable link to the globe somewhere a clone can follow',
    ),
    # --- The view bar's one row ------------------------------------------------------------------
    # The bar is `position: fixed`, so a wrap here can never move page content — this is a LOOK
    # regression, not a layout shift, and that is why it went unguarded for so long. What makes it
    # worth catching is that the tier segment in this bar is now the gallery's only route to the
    # globe, and that the union of every group Base.astro can emit already needs 293 px where 320 px
    # allows 282. The margin is one control wide.
    Sabotage(
        suite='web',
        label='the globe gains a second toggle, spending the row it had left at 320px',
        path='web/src/pages/earth.astro',
        needle='  borders={body.hasBorders}',
        replacement='  borders={body.hasBorders}\n  spotlight={true}',
        guard='fits on one row at 320px, on every bar the site ships',
    ),
    # The label direction: nothing about the markup changes shape, one word just gets longer. This is
    # the mutation a reviewer waves through.
    Sabotage(
        suite='web',
        label='a button label grows by a word, which no diff makes look like a layout change',
        path='web/src/layouts/Base.astro',
        needle='              Borders',
        replacement='              Country borders',
        guard='fits on one row at 320px, on every bar the site ships',
    ),
    # The tighter phone padding is what buys the fit; reverting it to the desktop values is the kind
    # of tidy-up that looks like removing a redundant override.
    Sabotage(
        suite='web',
        label='the phone padding is tidied back to the desktop values it deliberately overrides',
        path='web/src/styles/global.css',
        needle='    padding: 0.35rem 0.7rem;\n    font-size: 0.78rem;',
        replacement='    padding: 0.4rem 0.85rem;\n    font-size: 0.82rem;',
        guard='keeps the tighter phone padding, which is what buys the fit',
    ),
    Sabotage(
        suite='web',
        label='the segment gap is opened up, spending the slack on air between the buttons',
        path='web/src/styles/global.css',
        needle='  justify-content: center;\n  gap: 0.2rem;\n}',
        replacement='  justify-content: center;\n  gap: 1.2rem;\n}',
        guard='fits on one row at 320px, on every bar the site ships',
    ),
    # --- The globe fixture ------------------------------------------------------------------------
    # The fixture is the first thing here that instantiates a real map, so everything later built on
    # it inherits its correctness. Both mutations below produce a fixture that still mounts, still
    # reaches `load`, and still passes anything that only asks whether a map exists — which is the
    # shape of failure this whole file exists to make visible.
    Sabotage(
        suite='web',
        label='the fixture container loses its height, so every geometry assertion passes by collapsing',
        path='web/src/lib/testing/mountGlobe.ts',
        needle='  container.style.height = `${options.height ?? FIXTURE_HEIGHT_PX}px`;\n',
        replacement='',
        guard='builds the map at the size the fixture asked for, not merely a non-zero one',
    ),
    # The height mutation was MISSED on its first run, and the miss is the point. The guard asked
    # only for a non-zero box, and deleting the height still gave one: with no MapLibre stylesheet
    # injected the canvas flows normally and hands the div a height back. Measured 800x158 where the
    # fixture declares 800x600 — not a collapse, a silent reframe, which every geometric assertion
    # built on the fixture would then have been measuring. The guard now pins the declared size.
    Sabotage(
        suite='web',
        label='the fixture quietly mounts mercator, so the globe transform is never the one under test',
        path='web/src/lib/testing/mountGlobe.ts',
        needle='projection: { type: "globe" }',
        replacement='projection: { type: "mercator" }',
        guard='carries the globe projection the page ships, not the default mercator',
    ),
    # --- The ruler's reading, against a real transform ---------------------------------------------
    # The source guards beside these pin the MECHANISM (per-call transform lookup, one unproject, no
    # terrain). These pin the OUTCOME, which no source assertion can reach: a reading that is true
    # and that moves. Every mutation below leaves a ruler that renders a plausible number.
    Sabotage(
        suite='web',
        label='the measured span drifts from the drawn one, so every reading is scaled wrong',
        path='web/src/lib/scaleRuler.ts',
        needle='rulerSamplePoints(width, height, spanPx)',
        replacement='rulerSamplePoints(width, height, spanPx * 2)',
        guard='agrees with the ground-resolution identity, which the ruler never computes',
    ),
    # Both sample points collapse onto one: distance 0, label the em dash. The ruler still renders,
    # still updates, still never throws — it just stops being a distance.
    Sabotage(
        suite='web',
        label='the two sample points collapse onto one, so the ruler measures nothing at all',
        path='web/src/lib/scaleRuler.ts',
        needle='    [midX - spanPx / 2, midY],\n    [midX + spanPx / 2, midY],',
        replacement='    [midX, midY],\n    [midX, midY],',
        guard='reports a finite, positive distance at every zoom the globe serves',
    ),
    # The span is re-anchored at the viewport edge, which is what MapLibre's own control does and
    # what this module's header explains it must not: on a globe the left edge is frequently off the
    # sphere, where unprojecting answers on the plane behind it.
    Sabotage(
        suite='web',
        label='the span is anchored at the viewport edge, off the sphere, like the control we replaced',
        path='web/src/lib/scaleRuler.ts',
        needle='  const midX = width / 2;',
        replacement='  const midX = spanPx / 2;',
        guard='agrees with the ground-resolution identity, which the ruler never computes',
    ),
    # --- Hover against a real map ------------------------------------------------------------------
    # `hoverTracking.test.ts` drives these paths with a FAKE resolve, so it proves the state machine
    # and cannot see whether the answer is true. These three run the same machine over
    # queryRenderedFeatures on a rendered globe, which is where "the chip names the wrong country"
    # actually lives.
    Sabotage(
        suite='web',
        label='viewChanged stops resolving, so a parked pointer keeps naming the country that moved away',
        path='web/src/lib/hoverTracking.ts',
        needle='      if (lastPointerPosition === null) return;\n      scheduleResolve();\n    },',
        replacement='      if (lastPointerPosition === null) return;\n    },',
        guard='FOLLOWS THE CAMERA under a parked pointer, which is the bug viewChanged exists for',
    ),
    # The original defect, restored exactly: hover recomputed on pointer movement alone. It was
    # invisible for as long as the highlight was an anonymous outline, and became a chip stating a
    # wrong country by name the moment one was added.
    Sabotage(
        suite='web',
        label='leaving stops clearing the cached point, so the next camera move revives a dead hover',
        path='web/src/lib/hoverTracking.ts',
        needle='    pointerLeft() {\n      lastPointerPosition = null;',
        replacement='    pointerLeft() {',
        guard='does not revive a hover when the camera moves after the pointer has left',
    ),
    Sabotage(
        suite='web',
        label='leaving is deferred to a frame, so the chip lingers over empty canvas',
        path='web/src/lib/hoverTracking.ts',
        needle='      lastPointerPosition = null;\n      setHovered(null);\n    },',
        replacement='      lastPointerPosition = null;\n      scheduleFrame(() => setHovered(null));\n    },',
        guard='clears synchronously when the pointer leaves, with no frame of lingering chip',
    ),
    # --- The body registry -------------------------------------------------------------------------
    # The registry is a pure addition that nothing reads yet, so the only thing it can be wrong about
    # is its own contract. All three mutations below leave a pipeline that runs and a planet that
    # renders — which is the entire reason a second body needs this module before it needs data.
    Sabotage(
        suite='python',
        label='the registry radius is "corrected" to the spherical mean, tilting every latitude',
        path='pipeline/bodies.py',
        # ANCHORED ON EARTH'S OWN COMMENT, because the bare field line stopped being unique the
        # moment Mars joined the registry carrying the SAME number on purpose. The freshness gate
        # caught that within a second of Mars landing, which is the whole reason it exists.
        needle=("    # Web Mercator's sphere. Duplicated today in render/hillshade.py and "
                "render/snow.py.\n    mercator_radius_m=6378137.0,"),
        replacement=("    # Web Mercator's sphere. Duplicated today in render/hillshade.py and "
                     "render/snow.py.\n    mercator_radius_m=6371000.0,"),
        guard='test_earth_carries_web_mercator_s_defining_sphere',
    ),
    # The plausible edit: 6371000 IS a real earth radius, just not the projection's one. Nothing
    # crashes; the per-row z-factor is quietly wrong at every latitude. It used to be catchable only
    # as drift between two copies; now there is one home, so the guard pins the value itself.
    Sabotage(
        suite='python',
        label='a shading module regrows its own sphere radius beside the shared one',
        path='pipeline/render/snow.py',
        needle='    return mercator.latitude_at(merc_y, mercator.WEB_MERCATOR_RADIUS_M)',
        replacement='    return mercator.latitude_at(merc_y, 6378137.0)',
        guard='test_the_render_package_no_longer_carries_its_own_earth_radius',
    ),
    # Identical output today, which is exactly why nothing else would notice: the module has quietly
    # stopped asking the projection module and gone back to knowing the answer. The needle moved off
    # `bodies.EARTH` when the sphere did: a grid row's latitude is a property of the GRID, and every
    # grid here is EPSG:3857 for every planet, so reading it from a body was the misleading half.
    Sabotage(
        suite='python',
        label='an unknown body silently falls back to Earth instead of raising',
        path='pipeline/bodies.py',
        needle='    try:\n        return BODIES[name]',
        replacement='    if name not in BODIES:\n        return EARTH\n    try:\n        return BODIES[name]',
        guard='test_an_unknown_body_raises_and_names_the_ones_that_exist',
    ),
    # A misspelt body name then produces a complete, plausible, entirely wrong pyramid.
    Sabotage(
        suite='python',
        label='the ground ratio is inverted, which Earth cannot notice because its ratio is 1.0',
        path='pipeline/bodies.py',
        needle='    return body.ground_radius_m / body.mercator_radius_m',
        replacement='    return body.mercator_radius_m / body.ground_radius_m',
        guard='test_a_body_on_a_smaller_sphere_reports_a_ratio_below_one',
    ),
    # THE CASE THIS WHOLE MODULE EXISTS FOR, and the reason its guard uses a synthetic body rather
    # than Earth. Inverted, the helper still returns exactly 1.0 for Earth — the division is
    # symmetric when both radii are the same number — so every Earth-only assertion passes, every
    # Earth pixel is byte-identical, and the error is a 3.5x wrong exaggeration on the first planet
    # whose sphere is not Earth's. A guard written against the registered body would be vacuous.
    Sabotage(
        suite='python',
        label='the body sphere is "corrected" to the spherical mean, tilting the ratio off 1.0',
        path='pipeline/bodies.py',
        needle='    ground_radius_m=6378137.0,',
        replacement='    ground_radius_m=6371000.0,',
        guard='test_earths_ground_sphere_is_its_mercator_sphere_so_the_ratio_is_exactly_one',
    ),
    # The tidying edit that looks like a fix: 6371000 is a real Earth radius and reads as the more
    # "correct" one. It takes Earth's ratio to 0.99888, so every hillshade z-factor on the live
    # planet shifts by a tenth of a percent — visible nowhere, byte-identical nothing.
    Sabotage(
        suite='python',
        label='the grid resolution is rounded to its exact value, orphaning the raster on disk',
        path='pipeline/bodies.py',
        needle='    map_units_per_pixel=305.7483,',
        replacement='    map_units_per_pixel=305.748113,',
        guard='test_earth_s_grid_resolution_is_the_one_its_live_raster_was_built_at',
    ),
    # The most tempting edit in the file, because the exact figure IS more correct. It restages
    # nothing today — height_3857 is gated on its sources' mtimes and every sibling compares against
    # height's actual grid — so it sits inert until an unrelated re-fuse re-warps height at the new
    # resolution, moves the grid under all six siblings at once and restages the planet under
    # someone else's change. `test_every_body_s_grid_resolution_agrees_with_its_own_tile_ceiling`
    # has no case of its own yet: on Earth alone it is redundant with the bridge above, and it earns
    # its keep at the first body that has no module constant to be bridged to.
    Sabotage(
        suite='python',
        label='a Body field gains a default, so a new planet inherits Earth without being asked',
        path='pipeline/bodies.py',
        # THE LAST FIELD, deliberately. Defaulting any earlier one is followed by a field without a
        # default, so Python refuses the class at import and the module never loads — which reads as
        # "caught" while leaving the guard itself unexercised. Only a mutation the interpreter
        # accepts can prove the test does the work.
        #
        # WHICH FIELD IS LAST IS NOT THIS FILE'S TO KNOW, and it has drifted twice: naming
        # `path_prefix` here quietly stopped being valid the moment `surface_layers` was appended to
        # `Body`, and the needle still matched exactly once, so the table's own freshness gate stayed
        # green. `test_the_defaulted_field_case_still_names_the_last_field_of_body` is what makes the
        # next append a red test instead of a silently hollow case.
        needle='    renders_polar_caps: bool\n',
        replacement='    renders_polar_caps: bool = True\n',
        guard='test_no_field_carries_a_default_so_a_new_one_must_be_decided_per_body',
    ),
    # --- Polar caps as a per-body decision ----------------------------------------------------------
    # The dangerous property of all three: a body publishing no caps would RENDER them perfectly well.
    # Declaring no surface layers leaves the cap needing only the heightfield, so there is no missing
    # file to stop it and no error to read — just ~14 GB a pole spent shipping a look nobody ratified.
    Sabotage(
        suite='python',
        label='the shade pass shells out to the cap render for every body again',
        path='pipeline/tile/shade_planet.py',
        needle='    return body.renders_polar_caps\n',
        replacement='    return True\n',
        guard='test_the_shade_pass_skips_the_cap_subprocess_for_a_body_that_publishes_none',
    ),
    Sabotage(
        suite='python',
        # The tidy-looking version: an operator running the module directly "obviously" wants a
        # render, so the second gate reads as belt-and-braces. It is the only gate on that path.
        label='cap_render trusts its caller and drops its own body check',
        path='pipeline/tile/cap_render.py',
        needle='    if not body.renders_polar_caps:\n',
        replacement='    if False:\n',
        guard='test_a_body_publishing_no_caps_is_refused_by_the_cap_pass_itself',
    ),
    Sabotage(
        suite='python',
        # Not cosmetic: the refusal names the field an operator must change to turn caps ON. Without
        # it the message says a body publishes no caps and gives no way to disagree with that.
        label='the cap refusal stops naming the field that would enable them',
        path='pipeline/tile/cap_render.py',
        needle='                 f"renders_polar_caps on the body in pipeline/bodies.py once they are ratified.")',
        replacement='                 f"the body in pipeline/bodies.py once they are ratified.")',
        guard='test_a_body_publishing_no_caps_is_refused_by_the_cap_pass_itself',
    ),
    # --- The second body ---------------------------------------------------------------------------
    # Mars publishes no pyramid yet, so none of these can be caught by looking at a rendered planet.
    # Each one leaves a registry that imports, type-checks and reads perfectly sensibly.
    Sabotage(
        suite='python',
        label="Mars is given its own sphere to project on, which cannot be tiled at all",
        path='pipeline/bodies.py',
        # ANCHORED ON MARS'S OWN COMMENT, not on the two radii being adjacent — which is what this
        # needle used to rely on, and a comment inserted between them broke it one commit later.
        # Adjacency is not a property of the code; it is a property of nobody having explained it yet.
        # Only the AEQD radius moves, which makes this the HALF-fix: the guard asserts both spheres,
        # so a case that changed both would pass even against a test that had lost one assertion.
        needle=('    # proj4 string names no celestial body: it does not escape the check either. '
                'See the field note.\n    aeqd_radius_m=6371000.0,'),
        replacement=('    # proj4 string names no celestial body: it does not escape the check either. '
                     'See the field note.\n    aeqd_radius_m=3396190.0,'),
        guard='test_mars_projects_on_earths_spheres_and_that_is_deliberate',
    ),
    # THE MOST TEMPTING EDIT IN THE REGISTRY, and the reason that guard is written as a deliberate
    # sameness rather than left implicit: a planet whose radius is 3,396,190 m carrying Earth's
    # 6,378,137 reads as a copy-paste slip, and correcting it is the obvious next commit. PROJ then
    # refuses to reproject between two celestial bodies and `gdal raster tile` cannot cut the raster
    # — but nothing says so until a run has already spent an hour warping.
    Sabotage(
        suite='python',
        label="Mars's ground sphere is set to the grid's, silently flattening its exaggeration",
        path='pipeline/bodies.py',
        needle='    ground_radius_m=3396190.0,',
        replacement='    ground_radius_m=6378137.0,',
        guard='test_mars_is_the_first_body_whose_ground_sphere_is_not_its_grid',
    ),
    # The inverse of the case above and far quieter: the registry now says a Mars map unit is a Mars
    # ground metre, the ratio comes out 1.0, and every hillshade is drawn at 0.53x the exaggeration
    # it was meant to have. Nothing raises, and the planet renders.
    Sabotage(
        suite='python',
        label='the Mars ceiling moves without its grid resolution, cutting at a zoom it was not built for',
        path='pipeline/bodies.py',
        needle='    tile_max_zoom=6,',
        replacement='    tile_max_zoom=7,',
        guard='test_every_body_s_grid_resolution_agrees_with_its_own_tile_ceiling',
    ),
    # THE CASE THE RELATIONAL PIN WAS WAITING FOR. It shipped with the previous commit and had no
    # mutation of its own, because on Earth alone any single-site edit trips the bridge to Z8_RES
    # instead — the guard only becomes reachable at a body with no module constant to be bridged to,
    # which is exactly what Mars is. Moving the ceiling is the FIRST thing the look loop does.
    Sabotage(
        suite='python',
        label='the browser forgets a body the pipeline still publishes for',
        path='web/src/lib/bodies.ts',
        needle='export type BodySlug = "earth" | "mars";',
        replacement='export type BodySlug = "earth";',
        guard='test_the_two_registries_agree_on_how_a_body_is_spelled',
    ),
    # Two registries, no import between them: the pipeline writes a pyramid under one name and the
    # browser requests it under another, which surfaces as a 404 at the edge long after the run that
    # produced it. Mutating the WEB file against a PYTHON guard on purpose — the drift is the gap
    # between the two languages, so a case that stayed inside one of them would not be testing it.
    Sabotage(
        suite='python',
        label='the warp regrows Earth\'s grid resolution, putting every body on the z8 lattice',
        path='pipeline/tile/shade_planet.py',
        needle='        resolution = body.map_units_per_pixel',
        replacement='        resolution = 305.7483',
        guard='test_the_shade_pass_no_longer_carries_its_own_grid_or_ceiling',
    ),
    # Identical output for Earth — which is exactly why nothing else can see it. The module has
    # quietly stopped asking the body and gone back to knowing the answer, and the next planet gets
    # a raster warped to a lattice its pyramid was never going to be cut on. The scan is the only
    # oracle available: a regrown constant type-checks and tests green.
    Sabotage(
        suite='python',
        label='the cut ceiling is hardcoded again, so every planet stops at Earth\'s depth',
        path='pipeline/tile/shade_planet.py',
        needle='                   max_zoom=body.tile_max_zoom,',
        replacement='                   max_zoom=8,',
        guard='test_the_cut_differs_between_bodies_in_exactly_one_setting',
    ),
    Sabotage(
        suite='python',
        label='the encoder quality is parameterised by body, duplicating a fact that is not one',
        path='pipeline/tile/shade_planet.py',
        needle='    return TileCut(format="WEBP", quality=95, tile_size=512, min_zoom=0,',
        replacement=('    return TileCut(format="WEBP", quality=95 if body.name == "earth" else 90,\n'
                     '                   tile_size=512, min_zoom=0,'),
        guard='test_the_cut_differs_between_bodies_in_exactly_one_setting',
    ),
    # The OVER-parameterisation direction, and the quieter one. Under-parameterising is loud — Mars
    # cuts to z8 and the disk says so. Moving an encoder setting onto the body reads as thoroughness
    # and silently lets two planets' encodings drift, with every other test still green.
    Sabotage(
        suite='python',
        label='the planet hillshade is driven at a literal, so the recipe records a relief nobody drew',
        path='pipeline/tile/shade_planet.py',
        needle='            height, hs, body.exaggeration, ALT, AZ,',
        replacement='            height, hs, 15.0, ALT, AZ,',
        guard='test_the_hillshade_is_driven_at_the_body_s_exaggeration',
    ),
    # The WORST available shape and the reason a scan is not enough here. The sidecar still records
    # the body's exaggeration, so it reports fresh; the pixels are drawn at Earth's; and re-running
    # changes nothing, because the recipe it compares against never moved. Only driving the real
    # entry point with a body that is not Earth can see the gap between the record and the shader.
    Sabotage(
        suite='python',
        label="the caps' fill sun keeps Earth's relief while the main sun takes the body's",
        path='pipeline/tile/cap_render.py',
        needle='    fill = hillshade.hillshade_array(haloed, cell, zfactor, hillshade.FILL_ALTITUDE, fill_az)',
        replacement='    fill = hillshade.hillshade_array(haloed, cell, 15.0, hillshade.FILL_ALTITUDE, fill_az)',
        guard='test_the_caps_are_shaded_at_the_body_s_exaggeration',
    ),
    # ONE of the two suns, deliberately: a fix applied to the line someone happened to be reading is
    # how a pair drifts, and a guard that checks only the main call would pass this cleanly.
    Sabotage(
        suite='python',
        label='the hillshade recipe hardcodes the exaggeration, so re-tuning relief restages nothing',
        path='pipeline/tile/shade_planet.py',
        needle='    params: dict[str, Any] = {"exag": body.exaggeration, "alt": ALT, "az": AZ}',
        replacement='    params: dict[str, Any] = {"exag": 15.0, "alt": ALT, "az": AZ}',
        guard='test_the_hillshade_recipe_records_the_body_s_own_exaggeration',
    ),
    Sabotage(
        suite='python',
        label='the cap recipe hardcodes the exaggeration, so a re-tuned cap reports fresh forever',
        path='pipeline/tile/cap_render.py',
        needle='                       "light": {"az": AZ, "alt": ALT, "exag": grid.body.exaggeration,',
        replacement='                       "light": {"az": AZ, "alt": ALT, "exag": 15.0,',
        guard='test_the_cap_recipe_records_the_body_s_own_exaggeration',
    ),
    # The mirror of the two above: the shader takes the body and the RECORD forgets it. Each body
    # writes into its own work tree, so this is not a collision between planets — it is the quieter
    # one WITHIN a planet. Re-tune its relief and the sidecar never moves, so a 53.8 min composite and
    # a ~14 GB cap render both find a matching recipe and skip, forever.
    Sabotage(
        suite='python',
        label='a dormant Earth exaggeration reappears at module scope in the cap renderer',
        path='pipeline/tile/cap_render.py',
        # Re-anchored when `ROOT = paths.ROOT` was deleted here: `COAST_SHP` was its only reader and
        # it moved to `paths.DATA`. Any module-scope constant line serves — what the mutation needs
        # is a place to define one, not this particular neighbour.
        needle='COAST_RGB = (96, 122, 142)  # muted steel-blue',
        replacement='COAST_RGB = (96, 122, 142)  # muted steel-blue\nEXAG = 15.0',
        guard='test_neither_shading_module_carries_its_own_exaggeration',
    ),
    # Unused, so every behavioural guard above stays green and the diff reads as a tidy local. This
    # is the case that isolates what the SCAN is for: the constant is how the wiring comes back, and
    # it is at its most invisible in the commit that merely defines it.
    Sabotage(
        suite='python',
        label='the region preview regrows its own exaggeration and stops predicting the planet',
        path='pipeline/tile/shade.py',
        needle='EXAG = palette.EXAGGERATION  # the region path exists to PREDICT the planet',
        replacement='EXAG = 15.0  # the region path exists to PREDICT the planet',
        guard='test_exaggeration_is_shared',
    ),
    # Byte-identical output TODAY, which is the whole hazard: the region path is where every look
    # A/B is judged, so a private copy only diverges once someone re-tunes the shared constant — and
    # then the previews that ratified the change were rendered at the value it replaced.
    Sabotage(
        suite='python',
        label='the ground scale is multiplied into the z-factor instead of divided out',
        path='pipeline/render/hillshade.py',
        needle='                zfactor = (exaggeration\n                           / (ground_scale * np.cos(np.radians(latitude)))).reshape(-1, 1)',
        replacement='                zfactor = (exaggeration * ground_scale\n                           / np.cos(np.radians(latitude))).reshape(-1, 1)',
        guard='test_the_scale_divides_exactly_as_an_equal_exaggeration_change_would',
    ),
    # THE SABOTAGE EARTH CANNOT FAIL, which is the only kind worth writing here: at a scale of
    # exactly 1.0 multiply and divide are the same operation, so every Earth pixel and every Earth
    # test stays green while the first non-Earth body is shaded 3.5x wrong in the flattening
    # direction. Only a synthetic body driven through the real shader can see it.
    Sabotage(
        suite='python',
        label='the hillshade forgets the ground scale, shading a small planet at Earth\'s relief',
        path='pipeline/tile/shade_planet.py',
        needle='            ground_scale=bodies.ground_metres_per_mercator_unit(body))',
        replacement='            ground_scale=1.0)',
        guard='test_the_hillshade_is_driven_at_the_body_s_exaggeration',
    ),
    Sabotage(
        suite='python',
        label='the ground scale reaches the recipe but never the pixels it claims to describe',
        path='pipeline/tile/shade_planet.py',
        needle='    ground_res = body.map_units_per_pixel * ground',
        replacement='    ground_res = body.map_units_per_pixel',
        guard='test_the_sky_view_is_sized_and_searched_in_ground_metres',
    ),
    # The sky-view half, and it fails silently in the flattest possible way: a body whose map units
    # overstate distance searches a horizon 1.878x too long, so its valleys read as open ground and
    # the global renormalisation spreads the error over the whole planet rather than localising it.
    Sabotage(
        suite='python',
        label='Earth\'s hillshade recipe records a scale of 1.0, restaging the live pyramid for nothing',
        path='pipeline/tile/shade_planet.py',
        needle='    if ground_scale != 1.0:\n        params["ground_scale"] = ground_scale',
        replacement='    params["ground_scale"] = ground_scale',
        guard='test_the_hillshade_recipe_records_the_ground_scale_only_when_it_is_not_the_identity',
    ),
    # The over-recording direction, which no pixel test can see because no pixel changes. Adding the
    # key marks the live 46 GB chain stale and buys an 8:28 hillshade, a 53.8 min composite and a
    # 3:44 cut, all to write the bytes already on disk.
    Sabotage(
        suite='python',
        label='the layer gate asks the filesystem before it asks the body',
        path='pipeline/tile/shade_planet.py',
        needle='    if layer not in body.surface_layers:',
        replacement='    if layer not in body.surface_layers and not source.exists():',
        guard='test_a_layer_is_refused_for_a_body_that_does_not_declare_it_even_though_the_source_is_there',
    ),
    # THE ORIGINAL BUG, as the tidy-looking refactor that reintroduces it: two branches that both
    # print and both return False, collapsed into one condition. It reads as a simplification and it
    # is a different function — refusing only when the body lacks the layer AND the file is missing,
    # so on a box that has Earth's data every planet passes. Mars then warps Earth's northern-
    # hemisphere snow onto its own grid at the same latitudes and paints it: no exception, no
    # missing file, and a Martian pyramid with a plausible snow line.
    #
    # THE FIRST ATTEMPT AT THIS CASE WAS VACUOUS AND THE HARNESS SAID SO. It reordered the two
    # checks, which changes nothing: both still refuse, so the mutation reproduced no bug and the
    # guard correctly did not fire. A mutation has to make the subject WRONG, not merely different.
    Sabotage(
        suite='python',
        label='the Antarctic land-ice patch is applied to every body again',
        path='pipeline/tile/shade_planet.py',
        needle='    if "snow" in inputs.body.surface_layers:',
        replacement='    if True:',
        guard='test_a_body_without_the_snow_layer_composites_no_snow_at_all',
    ),
    # A latitude-and-land rule with no dataset behind it, so no file on disk could ever switch it
    # off. On a body with no sea every pixel below 60 south is land, and the southern third of the
    # planet renders solid white — while the raster layers all correctly sat out.
    Sabotage(
        suite='python',
        label='the snow read loses the guard its three sibling layers have always had',
        path='pipeline/tile/shade_planet.py',
        needle='            persistence_raw=read1_window(persistence_p, win) if persistence_p.exists() else None,',
        replacement='            persistence_raw=read1_window(persistence_p, win),',
        guard='test_a_body_with_no_snow_layer_composites_without_the_raster',
    ),
    # Caught only end-to-end: the guard lives in a closure inside `composite_planet`, and the
    # synthetic planet fixture WRITES a persistence raster, so every other test in the suite
    # exercises the present-file branch and passes with this reverted.
    Sabotage(
        suite='python',
        label="Earth's composite recipe records an empty layers-off list, restaging the pyramid",
        path='pipeline/tile/shade_planet.py',
        needle='    if absent_layers:\n        missing["layers_off"] = absent_layers',
        replacement='    missing["layers_off"] = absent_layers',
        guard='test_the_composite_recipe_records_only_the_layers_that_are_off',
    ),
    Sabotage(
        suite='python',
        label='Earth quietly loses a surface layer it has always composited',
        path='pipeline/bodies.py',
        needle='    surface_layers=frozenset({"lake_depth", "snow", "glaciers", "sea_ice", "coastline"}),',
        replacement='    surface_layers=frozenset({"lake_depth", "snow", "glaciers", "coastline"}),',
        guard='test_earth_has_every_surface_layer_and_the_second_body_has_none',
    ),
    # The under-declaring direction: Earth stops painting a product it has, which is a look change
    # nothing else asserts — the sea ice would simply not be there, and the pass would say so once
    # in a line of output nobody reads back.
    # --- The cap pass's layer gates -----------------------------------------------------------------
    # Every source below is one global path to an Earth dataset that IS on this box, so each mutation
    # here leaves a cap that renders cleanly, at plausible latitudes, describing another planet.
    Sabotage(
        suite='python',
        label="the north cap asks the disk before the body, so Earth's snow reaches every planet",
        path='pipeline/tile/cap_render.py',
        needle='    if layer_is_buildable(grid.body, "snow", Path(snow.SP_NC), "the north cap paints no snow"):',
        replacement='    if Path(snow.SP_NC).exists():',
        guard='test_a_body_with_no_layers_opens_none_of_earths_files',
    ),
    Sabotage(
        suite='python',
        label="the cap's sea ice asks the disk before the body, painting an Arctic on any planet",
        path='pipeline/tile/cap_render.py',
        needle='    if not layer_is_buildable(grid.body, "sea_ice", Path(seaice.SEAICE_SRC), consequence):',
        replacement='    if not Path(seaice.SEAICE_SRC).exists():',
        guard='test_a_body_with_no_layers_opens_none_of_earths_files',
    ),
    # Both of the above are the tidy-looking collapse rather than a typo: the body check reads as
    # redundant once you have seen the file sitting there, and dropping it is silent on the only
    # body anyone builds.
    Sabotage(
        suite='python',
        label="the south's forced Antarctic ice loses its gate and whitens a sea-less planet's pole",
        path='pipeline/tile/cap_render.py',
        needle='    if body_declares_layer(grid.body, "snow", "polar land stays on the relief ramp"):',
        replacement='    if True:',
        guard='test_the_forced_antarctic_patch_is_refused_for_a_body_with_no_snow_layer',
    ),
    # The one rule with no file behind it, so nothing on disk could ever have switched it off.
    Sabotage(
        suite='python',
        label='the coastline gate keeps only its look half, burning Natural Earth onto any body',
        path='pipeline/tile/cap_render.py',
        needle='    if grid.coast_opacity <= 0.0:\n        return False\n    return layer_is_buildable(grid.body, "coastline", COAST_SHP,\n                              "the cap ships with no land/sea line")',
        replacement='    return grid.coast_opacity > 0.0',
        guard='test_a_body_without_the_layer_declines_it_though_earths_file_is_right_there',
    ),
    Sabotage(
        suite='python',
        label='a cap depends on a climatology it never opens, so it can never read fresh',
        path='pipeline/tile/cap_render.py',
        needle='    if "sea_ice" in grid.body.surface_layers:\n        sources.append(Path(seaice.SEAICE_SRC))',
        replacement='    sources.append(Path(seaice.SEAICE_SRC))',
        guard='test_a_source_for_an_absent_layer_is_not_a_dependency',
    ),
    Sabotage(
        suite='python',
        label='the cap recipe stops recording which layers are off, so switching one restages nothing',
        path='pipeline/tile/cap_render.py',
        needle='    absent = bodies.layers_off(grid.body, bodies.CAP_LAYERS)\n    layers = {"layers_off": absent} if absent else {}',
        replacement='    layers = {}',
        guard='test_turning_a_layer_off_restages_although_its_source_stops_being_a_dependency',
    ),
    # Load-bearing rather than tidy: turning a layer off also REMOVES its file from cap_sources, so
    # the mtime that would have noticed disappears along with the layer. The recipe is what is left.
    Sabotage(
        suite='python',
        label='the composite recipe enumerates every layer, so a cap-only decision restages 46 GB',
        path='pipeline/tile/shade_planet.py',
        needle='    absent_layers = bodies.layers_off(body, bodies.COMPOSITE_LAYERS)',
        replacement='    absent_layers = bodies.layers_off(body, bodies.SURFACE_LAYERS)',
        guard='test_the_composite_recipe_records_only_the_layers_that_are_off',
    ),
    # Over-tracking is exactly as silent as under-tracking, and this is its direction: the tile
    # composite cannot contain a coastline, so recording one restages the planet for a texture's sake.
    # --- The cap's ground metres --------------------------------------------------------------------
    Sabotage(
        suite='python',
        label="the cap converts through the tile grid's sphere, which is not the one it is drawn on",
        path='pipeline/tile/cap_render.py',
        needle='    zfactor = grid.body.exaggeration / bodies.ground_metres_per_aeqd_unit(grid.body)',
        replacement='    zfactor = grid.body.exaggeration / bodies.ground_metres_per_mercator_unit(grid.body)',
        guard='test_a_body_whose_spheres_coincide_is_driven_at_its_bare_exaggeration',
    ),
    # THE MOST PLAUSIBLE MUTATION IN THIS FILE. The helper next door has almost the same name, is
    # already imported, and is wrong by 0.11% on Earth — invisible — and by 1.88x on Mars.
    Sabotage(
        suite='python',
        label='the cap ground scale is applied the wrong way round, flattening the smaller body',
        path='pipeline/tile/cap_render.py',
        needle='    zfactor = grid.body.exaggeration / bodies.ground_metres_per_aeqd_unit(grid.body)',
        replacement='    zfactor = grid.body.exaggeration * bodies.ground_metres_per_aeqd_unit(grid.body)',
        guard='test_a_smaller_body_is_shaded_more_steeply_for_the_same_exaggeration',
    ),
    Sabotage(
        suite='python',
        label='the cap recipe drops the ground scale, so a body change leaves the cap falsely fresh',
        path='pipeline/tile/cap_render.py',
        needle='                                 "ground_scale": bodies.ground_metres_per_aeqd_unit(grid.body),\n',
        replacement='',
        guard='test_the_ground_scale_rides_in_the_recipe_that_gates_the_render',
    ),
    # --- The Mars acquisition recipe ----------------------------------------------------------------
    # Nothing here can be caught by looking at output: the file is not on disk, and every one of these
    # mutations leaves a module that imports, type-checks and reads perfectly sensibly.
    Sabotage(
        suite='python',
        label='the edition preflight checks only the size, so a re-upload passes as the pinned one',
        path='pipeline/acquire/download_mars_dem.py',
        needle='    for field, served, expected in (("size", served_bytes, EXPECTED_BYTES),\n                                    ("Last-Modified", served_date, EXPECTED_LAST_MODIFIED)):',
        replacement='    for field, served, expected in (("size", served_bytes, EXPECTED_BYTES),):',
        guard='test_a_re_upload_of_the_SAME_bytes_still_aborts',
    ),
    Sabotage(
        suite='python',
        label='the sphere is read as PROJ `a`, which an unflattened body does not have at all',
        path='pipeline/acquire/download_mars_dem.py',
        needle='        ellipsoid = pyproj.CRS.from_user_input(crs.to_wkt()).ellipsoid\n        semi_major = ellipsoid.semi_major_metre if ellipsoid is not None else None',
        replacement='        semi_major = crs.to_dict().get("a")',
        guard='test_the_published_grid_passes',
    ),
    # NOT INVENTED — this is the spelling I reached for first, and the test above refused it. PROJ
    # serialises a sphere as `+R=`, so `to_dict()["a"]` is None for exactly the products this checks.
    Sabotage(
        suite='python',
        label='the sphere tolerance widens enough to admit the 3,389,500 m spherical mean',
        path='pipeline/acquire/download_mars_dem.py',
        needle='        if semi_major is None or abs(semi_major - bodies.MARS.ground_radius_m) > 1.0:',
        replacement='        if semi_major is None or abs(semi_major - bodies.MARS.ground_radius_m) > 10000.0:',
        guard='test_a_source_on_the_MEAN_sphere_is_refused_though_it_is_only_0_2_percent_out',
    ),
    Sabotage(
        suite='python',
        label='--check falls through and starts a 10.6 GiB download nobody authorised',
        path='pipeline/acquire/download_mars_dem.py',
        needle='    if args.check:\n        return 0',
        replacement='    if False:\n        return 0',
        guard='test_check_stops_after_the_preflight',
    ),
    # --- The HTTP identity --------------------------------------------------------------------------
    # These are the hardest mutations in the file to catch by any other means. Every acquisition test
    # mocks the network, so the suite cannot see a missing header; every host without bot protection
    # serves an anonymous client happily, so a real run cannot see it either. The defect they encode
    # shipped in ten call sites and was found by a download returning 403.
    Sabotage(
        suite='python',
        label='the request goes out anonymous, which is what every bot-protection edge refuses',
        path='pipeline/fetch.py',
        needle='    return urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})',
        replacement='    return urllib.request.Request(url, method=method)',
        guard='test_build_request_carries_the_pipeline_user_agent',
    ),
    Sabotage(
        suite='python',
        # Not a stylistic mutation: `preflight` HEADs the Mars mosaic precisely so the edition can be
        # checked WITHOUT moving 10.6 GiB. Silently downgrading it to GET makes the free check the
        # expensive one, and it still passes every assertion about what the headers said.
        label='the method is dropped, so every HEAD becomes a GET that pulls the body',
        path='pipeline/fetch.py',
        needle='    return urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})',
        replacement='    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})',
        guard='test_build_request_passes_the_method_through',
    ),
    Sabotage(
        suite='python',
        # The tidy-looking version of this change: a default that "matches what the callers pass".
        # It matches them today and silently covers the one that forgets tomorrow, and a stalled host
        # then hangs a stage forever rather than failing it.
        label='the timeout gains a default, so the next call site can omit it without noticing',
        path='pipeline/fetch.py',
        needle='def open_url(url: str, *, method: str = "GET", timeout: float) -> Any:',
        replacement='def open_url(url: str, *, method: str = "GET", timeout: float = 60) -> Any:',
        guard='test_open_url_requires_a_timeout_and_will_not_take_it_positionally',
    ),
    Sabotage(
        suite='python',
        # The exact blindness the guard was written against, reintroduced one level up: the scan that
        # replaced a hand-grep for `urlopen` must not itself become a scan for one import spelling.
        label='the import scan sees only `import urllib.request`, never the `from` form',
        path='tests/test_fetch.py',
        needle='        elif isinstance(node, ast.ImportFrom) and node.module == "urllib.request":\n            return True\n',
        replacement='',
        guard='test_the_scan_would_catch_a_module_that_went_around_fetch',
    ),
    Sabotage(
        suite='python',
        # Where the defect actually lived. A scan that skips the acquisition package is a scan that
        # reports clean forever while every module that talks to a server does as it likes.
        label='the import scan skips the acquire package, which is where every fetcher is',
        path='tests/test_fetch.py',
        needle='        if source != FETCH_MODULE and "__pycache__" not in source.parts',
        replacement='        if source != FETCH_MODULE and "__pycache__" not in source.parts\n        and "acquire" not in source.parts',
        guard='test_the_scan_reaches_the_whole_package_rather_than_a_handful_of_files',
    ),
    # --- The planet seam ----------------------------------------------------------------------------
    # Every mutation below leaves a module that imports, type-checks, and answers every question it is
    # asked. What they change is which of THREE situations collapse into one answer: "this planet has
    # no ocean mask", "the producer never ran", and "the producer died partway". A pipeline that cannot
    # tell those apart shades a half-built planet and reports success, so the guards are the only place
    # the distinction is enforced.
    Sabotage(
        suite='python',
        label='a body whose producer never ran reads as a planet with no masks',
        path='pipeline/planet_seam.py',
        needle='    if not path.exists():\n        raise FileNotFoundError(',
        replacement='    if not path.exists():\n        return frozenset()\n    if False:\n        raise FileNotFoundError(',
        guard='test_a_body_that_never_ran_raises_rather_than_reading_as_a_planet_with_no_masks',
    ),
    Sabotage(
        suite='python',
        label='the declaration is trusted to name rasters nobody checked onto disk',
        path='pipeline/planet_seam.py',
        needle='    if absent:\n        raise FileNotFoundError(',
        replacement='    if False:\n        raise FileNotFoundError(',
        guard='test_declaring_a_raster_that_is_not_on_disk_is_refused',
    ),
    Sabotage(
        suite='python',
        label='coherence is checked only where it is written, never where it is read',
        path='pipeline/planet_seam.py',
        needle='    _require_coherent(body, rasters)\n    return rasters',
        replacement='    return rasters',
        guard='test_coherence_is_rechecked_on_READ_not_only_on_write',
    ),
    # The tidy that motivates it: the write side already checks, so the read side looks redundant. It
    # is not — the registry can gain a layer long after the declaration was written.
    Sabotage(
        suite='python',
        label='only lake depth is coupled to its mask, so sea ice can be on and paint nothing',
        path='pipeline/planet_seam.py',
        needle='LAYER_REQUIRES_RASTER: dict[str, str] = {"lake_depth": "watermask", "sea_ice": "oceanmask"}',
        replacement='LAYER_REQUIRES_RASTER: dict[str, str] = {"lake_depth": "watermask"}',
        guard='test_sea_ice_without_an_ocean_mask_is_refused',
    ),
    Sabotage(
        suite='python',
        label='the freshness record names the rasters that are ON, which puts a key in Earth\'s recipe',
        path='pipeline/planet_seam.py',
        needle='    return sorted(KNOWN_RASTERS - rasters)',
        replacement='    return sorted(rasters)',
        guard='test_a_full_planet_records_nothing',
    ),
    Sabotage(
        suite='python',
        label='rebuilding the VRTs always replaces them, restaging the whole 46 GB planet',
        path='pipeline/planet_seam.py',
        needle='    if vrt.exists() and vrt.read_bytes() == scratch.read_bytes():',
        replacement='    if False:',
        guard='test_an_unchanged_source_set_leaves_the_file_untouched',
    ),
    Sabotage(
        suite='python',
        label='the scratch VRT is built outside the directory, so its relative paths never match',
        path='pipeline/planet_seam.py',
        needle='    scratch = vrt.with_suffix(".vrt.new")',
        replacement='    scratch = vrt.parent.parent / (vrt.name + ".new")',
        guard='test_an_unchanged_source_set_leaves_the_file_untouched',
    ),
    # The consumer side of the same seam. Each of these leaves a pass that runs to completion and
    # produces a whole planet; what changes is whether that planet's sea was declared or assumed.
    Sabotage(
        suite='python',
        label='the composite records the missing rasters unconditionally, restaging Earth',
        path='pipeline/tile/shade_planet.py',
        needle='    if absent_rasters:\n        missing["rasters_off"] = absent_rasters',
        replacement='    missing["rasters_off"] = absent_rasters',
        guard='test_a_whole_planet_records_nothing',
    ),
    Sabotage(
        suite='python',
        label='the mask warps run for every planet, so a sea-less body gets Earth\'s coastlines',
        path='pipeline/tile/shade_planet.py',
        needle='        if raster not in rasters:',
        replacement='        if False:',
        guard='test_an_undeclared_mask_never_reaches_gdalwarp',
    ),
    Sabotage(
        suite='python',
        label='the composite reads the masks if the FILE is there, not if the planet declared one',
        path='pipeline/tile/shade_planet.py',
        needle='            ocean_raw=read1_window(ocean_p, win) if "oceanmask" in rasters else None,',
        replacement='            ocean_raw=read1_window(ocean_p, win) if ocean_p.exists() else None,',
        guard='test_the_masks_are_never_opened',
    ),
    # The one that reads as a tidy: every other optional input in that struct is gated on `.exists()`,
    # so matching them looks like consistency. It is the opposite — those four ask "did we download
    # Earth's data", and this one asks "does this planet have a sea".
    Sabotage(
        suite='python',
        label='the cap warps its masks whatever the planet emitted',
        path='pipeline/tile/cap_render.py',
        needle='    if "oceanmask" in rasters:',
        replacement='    if True:',
        guard='test_an_undeclared_mask_is_never_warped',
    ),
    Sabotage(
        suite='python',
        label='the cap depends on mask VRTs a body never built, so it can never read fresh',
        path='pipeline/tile/cap_render.py',
        needle='               for raster in planet_seam.PLANET_RASTERS if raster in rasters]',
        replacement='               for raster in planet_seam.PLANET_RASTERS]',
        guard='test_cap_sources_drops_a_mask_the_planet_never_emitted',
    ),
    # The tidy that unifies the two dependency lists. It looks like removing an inconsistency; it is
    # making the composite's list exact, which is the direction that can under-track silently.
    Sabotage(
        suite='python',
        label='the composite dependency list drops the masks to match cap_sources',
        path='pipeline/tile/shade_planet.py',
        needle='    return (work / "height_3857.tif", hs, work / "ocean_3857.tif", work / "water_3857.tif",',
        replacement='    return (work / "height_3857.tif", hs,',
        guard='test_the_composite_names_the_masks_whatever_the_planet_declared',
    ),
    # --- Mars's planet producer ------------------------------------------------------------------
    # The relabel is metadata only, so every mutation here produces a Mars that projects perfectly,
    # tiles cleanly, and is somewhere it does not belong — or one that quietly acquires an ocean.
    Sabotage(
        suite='python',
        label='the relabel REPROJECTS instead of assigning, which PROJ refuses across bodies',
        path='pipeline/fuse/relabel_mars.py',
        needle='        subprocess.run(["gdal_translate", "-q", "-of", "VRT", "-a_srs", "EPSG:4326",',
        replacement='        subprocess.run(["gdal_translate", "-q", "-of", "VRT", "-a_ullr", "-180", "90", "180", "-89",',
        guard='test_not_one_angle_moves',
    ),
    Sabotage(
        suite='python',
        label='the published grid is verified AFTER the VRT is written, so a shifted source lands first',
        path='pipeline/fuse/relabel_mars.py',
        needle='    download_mars_dem.assert_grid(blend)\n    relabel(blend)',
        replacement='    relabel(blend)\n    download_mars_dem.assert_grid(blend)',
        guard='test_the_published_grid_is_verified_before_the_vrt_is_written',
    ),
    Sabotage(
        suite='python',
        label='Mars declares masks it never produced, which is how a fabricated ocean gets in',
        path='pipeline/fuse/relabel_mars.py',
        needle="    print(f\"declared {planet_seam.declare(bodies.MARS, ['heightfield'])}\", flush=True)",
        replacement='    print(f"declared {planet_seam.declare(bodies.MARS, planet_seam.PLANET_RASTERS)}", flush=True)',
        guard='test_it_declares_a_heightfield_and_nothing_else',
    ),
    # --- The look seam ------------------------------------------------------------------------------
    # The ramps' kind-dispatch used to be transcribed in four functions; it is now one resolver over a
    # frozen Look. That is a refactor whose contract is "nothing changes", so its guard is a byte
    # hash rather than a property — every mutation below leaves ramps that are still monotonic, still
    # hit their stops, and still agree with gdaldem within 1 DN, which is all the property tests ask.
    Sabotage(
        suite='python',
        # Re-anchored when the sea branch grew its no-sea refusal, so the two returns stopped being
        # adjacent lines. The claim is unchanged: land resolves to the sea's ramp, and every
        # continent is painted in the abyss's colours while the ramp stays monotonic.
        label='the look resolver hands back the sea ramp when land was asked for',
        path='pipeline/render/palette.py',
        needle='    if kind == "land":\n        return look.land',
        replacement='    if kind == "land":\n        return look.sea',
        guard='test_gdaldem_ramp_text_is_unchanged',
    ),
    Sabotage(
        suite='python',
        # The refusal deleted, which is the tidy it invites: `look.sea` is typed optional, so
        # returning it directly looks like the simplification the type checker was asking for.
        # What it actually does is hand `None` to a body with no sea and crash somewhere else --
        # or, worse, reach a caller that treats the absence as a ramp.
        label='the no-sea look stops refusing and returns its missing ramp instead',
        path='pipeline/render/palette.py',
        needle='        if look.sea is None:\n            raise ValueError(\n                "this look draws no sea',
        replacement='        if False:\n            raise ValueError(\n                "this look draws no sea',
        guard='test_a_look_with_no_sea_refuses_to_resolve_one',
    ),
    Sabotage(
        suite='python',
        # A body with no look inherits Earth's rather than raising -- the one-line "friendlier"
        # change that turns a hard stop into a whole plausible pyramid in another planet's colours.
        label='an unregistered body falls back to Earth\'s ramp instead of raising',
        path='pipeline/render/palette.py',
        needle='        return LOOK_BY_BODY[body]',
        replacement='        return LOOK_BY_BODY.get(body, EARTH_LOOK)',
        guard='test_an_unregistered_body_gets_no_look_at_all',
    ),
    Sabotage(
        suite='python',
        # The anti-regrowth sweep narrowed to the package that happens to hold the palette, which
        # is the tidy it invites -- "ramps are a render concern". It drops `pipeline/tile/`, where
        # BOTH of the modules that actually carried this bug live, and the scan goes on passing.
        label='the ramp-bypass sweep stops reading the package the shading path lives in',
        path='tests/test_palette.py',
        needle='for path in sorted((REPO_ROOT / "pipeline").rglob("*.py")):',
        replacement='for path in sorted((REPO_ROOT / "pipeline/render").rglob("*.py")):',
        guard='test_no_module_reaches_around_the_look_to_the_ramp_globals',
    ),
    Sabotage(
        suite='python',
        # The composite draws a sea for a planet that declares none. All-False ocean means the
        # pixels are identical, so nothing on screen moves -- but the freshness recipe and the
        # allocation both come back, and the look's `sea=None` stops meaning anything.
        label='the composite paints a sea on a body whose look has none',
        path='pipeline/tile/shade.py',
        needle='    if look.sea is None:\n        # A body that draws no sea.',
        replacement='    if False:\n        # A body that draws no sea.',
        guard='test_a_body_with_no_sea_ramp_composites_from_land_alone',
    ),
    # The sea ramp's LUT starts at the abyss, not at 0 m. Dropping the offset leaves a table that is
    # the right length, the right dtype and the right shape, and wrong at every index.
    Sabotage(
        suite='python',
        # Re-anchored when the ramp gained an origin: the offset used to be `min(0.0, extreme_m)`
        # and is now `Surface.lowest_m`. The mutation is the same defect and now reaches further —
        # it breaks Earth's sea AND every land ramp that starts below its body's datum.
        label='the sea LUT loses its abyss offset, so every depth reads the wrong colour',
        path='pipeline/render/palette.py',
        needle='    colors = [_srgb8(ramp_color((ramp.lowest_m + index * step',
        replacement='    colors = [_srgb8(ramp_color((0.0 + index * step',
        guard='test_relief_lut_bytes_are_unchanged',
    ),
    # --- Mars draws its own colours, and the page says what they are not ------------------------------
    # The borrowing was a PLACEHOLDER held in place by a guard asserting it, so the day it ended the
    # guard had to invert. These three cover the ways it comes back or quietly stops being honest.
    Sabotage(
        suite='python',
        # The tidy: two ramps in one module, one of them referenced through the other, and someone
        # collapses the "duplication". Every Earth pixel is unchanged, every gate stays green, and
        # Mars silently goes back to wearing a shoreline hinge on a planet with no shore.
        label="Mars's ramp is pointed back at Earth's stops as a de-duplication",
        path='pipeline/render/palette.py',
        needle='    land=Surface(stops=MARS_LAND_STOPS, origin_m=-6000.0, extreme_m=6100.0),',
        replacement='    land=Surface(stops=EARTH_LOOK.land.stops, origin_m=-6000.0, extreme_m=6100.0),',
        guard='test_mars_draws_its_own_colours_and_no_longer_borrows_earths',
    ),
    Sabotage(
        suite='python',
        # A re-tune that darkens the top stop past its neighbour. It reads as a taste change and is
        # a CORRECTNESS one: the ramp stops being readable as elevation, which is the single
        # property chosen over fidelity to the planet. Nothing renders wrong; two heights just
        # become one colour again, which is the defect the whole authored ramp exists to remove.
        label="a re-tune leaves Mars's ramp brighter in the middle than at the top",
        path='pipeline/render/palette.py',
        needle='    (1.000, (0.658375, 0.520996, 0.337164)),',
        replacement='    (1.000, (0.458375, 0.320996, 0.237164)),',
        guard='test_mars_land_rises_monotonically_so_height_can_be_read',
    ),
    Sabotage(
        suite='web',
        # The disclosure goes vague. Nobody deletes it — it is softened during a copy pass, which is
        # what happens to a caveat that names something specific. "Certain dark markings" commits to
        # nothing a reader can check, where Syrtis Major tells them exactly what is missing and lets
        # them go and look. The paragraph still reads as an honest limitation while disclosing none.
        label='the Mars colour note stops naming the feature the ramp cannot show',
        path='web/src/pages/about.astro',
        needle='<strong>Syrtis Major</strong> and <strong>Acidalia</strong>',
        replacement='certain dark markings',
        guard='names a real albedo feature the map does not reproduce',
    ),

    # --- The ramp runs between two ends, and neither of them is assumed ------------------------------
    # Every case here puts the datum back at one end of the ramp. All five are invisible on Earth BY
    # CONSTRUCTION — both its ramps hinge on 0 m, so the mutated and correct expressions agree to the
    # byte — and each is wrong only on a body whose ramp starts somewhere else. That is the reason
    # they exist rather than a caveat: this is the shape that stayed green for as long as there was
    # one planet, and the second planet is the entire oracle.
    Sabotage(
        suite='python',
        label='the ramp hinges on the datum again, so a body below it loses half its colours',
        path='pipeline/render/palette.py',
        needle='        return min(self.origin_m, self.extreme_m)',
        replacement='        return min(0.0, self.extreme_m)',
        guard='test_mars_land_spans_its_own_measured_elevations',
    ),
    # The conditional record, in both directions. Over-recording is the tidy-looking one — it reads
    # as "just always track it" and silently restages a 46 GB planet to emit identical pixels.
    Sabotage(
        suite='python',
        label='the ramp origin is recorded unconditionally, restaging Earth for no pixel change',
        path='pipeline/tile/shade_planet.py',
        needle='    return {} if ramp.origin_m == 0.0 else {f"{kind}_origin_m": ramp.origin_m}',
        replacement='    return {f"{kind}_origin_m": ramp.origin_m}',
        guard='test_earths_ramps_add_no_key_because_both_hinge_on_the_datum',
    ),
    Sabotage(
        suite='python',
        label='the ramp origin reaches no freshness record, so a re-tune leaves a stale composite',
        path='pipeline/tile/shade_planet.py',
        needle='    return {} if ramp.origin_m == 0.0 else {f"{kind}_origin_m": ramp.origin_m}\n',
        replacement='    return {}\n',
        guard='test_a_ramp_off_the_datum_is_recorded',
    ),
    # The one with no symptom at all: a zero-width ramp divides by zero, nan survives `rint`, and the
    # cast to int32 picks an arbitrary index. One wrong colour, no exception, every gate green.
    Sabotage(
        suite='python',
        label='a zero-width ramp is admitted, so a planet renders from an arbitrary LUT index',
        path='pipeline/render/palette.py',
        needle='        if self.origin_m == self.extreme_m:',
        replacement='        if False:',
        guard='test_a_zero_width_ramp_is_refused_at_declaration',
    ),
    # The third copy of the assumption, in the module a type checker cannot connect to the other two.
    # Its own guard could not see this until it stopped comparing against a literal zero.
    Sabotage(
        suite='python',
        label="the hero rig restates the datum instead of reading the ramp's own origin",
        path='pipeline/render/scene_build.py',
        needle='LAND_RANGE = (_HERO_LOOK.land.origin_m, _HERO_LOOK.land.extreme_m)',
        replacement='LAND_RANGE = (0.0, _HERO_LOOK.land.extreme_m)',
        guard='test_the_origin_is_READ_and_not_coincidentally_zero',
    ),
    # --- Where a body's intermediates live -----------------------------------------------------------
    # The body is carried by the PATH, deliberately not by the freshness recipes: adding a body key to
    # composite_params.json would restage a 21:37 composite and a 4:19 cut to emit identical pixels.
    # That makes the path resolver load-bearing, and both mutations below are silent — Earth keeps
    # running, and only a second planet discovers it has been writing into Earth's directories.
    Sabotage(
        suite='python',
        label='the work prefix is dropped, so every body writes into Earth\'s own directories',
        path='pipeline/bodies.py',
        needle='    return paths.DATA / "work" / body.path_prefix / stage',
        replacement='    return paths.DATA / "work" / stage',
        guard='test_another_body_nests_under_its_own_name',
    ),
    # A stage name assembled by concatenation then walks out of the body's tree — and lands in
    # another planet's intermediates, which is where a mistake here stops being recoverable.
    Sabotage(
        suite='python',
        label='the stage-name check is relaxed, letting a path expression escape the body tree',
        path='pipeline/bodies.py',
        needle='    if not stage or "/" in stage or "\\\\" in stage or stage in {".", ".."}:',
        replacement='    if False:',
        guard='test_a_stage_name_cannot_escape_the_body_s_own_directory',
    ),
    # --- The caps' two roots -------------------------------------------------------------------------
    # Intermediates follow the data store, served assets follow the checkout. Collapsing them is
    # silent in every local run, because on an unrelocated checkout the two roots coincide.
    Sabotage(
        suite='python',
        label='served assets are resolved against the data store, so a relocated store publishes nothing',
        path='pipeline/bodies.py',
        needle='    return PUBLIC_ROOT / stage / body.path_prefix',
        replacement='    return paths.DATA / "web/public" / stage / body.path_prefix',
        guard='test_served_assets_follow_the_checkout_not_the_data_store',
    ),
    # The prefix moves to the wrong side of the stage: Earth is unaffected (its prefix is empty), so
    # this ships green and only a second body finds its caps published at the wrong URL.
    Sabotage(
        suite='python',
        label='the caps prefix is applied above the stage, publishing a second body at the wrong URL',
        path='pipeline/bodies.py',
        needle='    return PUBLIC_ROOT / stage / body.path_prefix',
        replacement='    return PUBLIC_ROOT / body.path_prefix / stage',
        guard='test_a_second_body_publishes_under_its_own_segment',
    ),
    # --- The body is required --------------------------------------------------------------------
    # Both mutations restore a silent Earth assumption. Neither raises, neither changes a pixel today,
    # and both mean a Mars pass would quietly shade with Earth's geometry into Earth's directories —
    # the one failure this whole workstream exists to make impossible.
    Sabotage(
        suite='python',
        label='--body regains a default, so a pass with no planet named silently means Earth',
        path='pipeline/tile/shade_planet.py',
        needle='    ap.add_argument("--body", required=True,',
        replacement='    ap.add_argument("--body", default="earth",',
        guard='test_omitting_the_body_is_an_error_rather_than_an_assumption',
    ),
    # The override stops being honoured, so a look A/B silently writes over the production tree.
    Sabotage(
        suite='python',
        label='--out stops overriding the body default, so an A/B overwrites the live pyramid',
        path='pipeline/tile/shade_planet.py',
        needle='    return args.out if args.out is not None else bodies.work_dir(resolve_body(args), "planet_tiles")',
        replacement='    return bodies.work_dir(resolve_body(args), "planet_tiles")',
        guard='test_an_explicit_out_still_wins_over_the_body_s_default',
    ),
    # --- The caps' body facts ------------------------------------------------------------------------
    # The AEQD sphere moved onto the body. Both mutations below leave caps that render, project and
    # blend — one records a radius nothing checks, the other gates a ~14 GB render on fields that
    # cannot move a pixel. Neither is visible in any output.
    Sabotage(
        suite='python',
        label='the whole Body is inlined in the cap recipe, gating a 14 GB render on tile_max_zoom',
        path='pipeline/tile/cap_render.py',
        needle='    fields = {key: value for key, value in asdict(grid).items() if key != "body"}',
        replacement='    fields = dict(asdict(grid))',
        guard='test_the_whole_body_is_not_inlined',
    ),
    # And the other direction: the radius drops out of the recipe, which is the state it was in
    # before this change — a module constant that reached no sidecar, so moving it left caps fresh.
    Sabotage(
        suite='python',
        label='the AEQD radius drops out of the recipe, so moving it leaves both caps falsely fresh',
        path='pipeline/tile/cap_render.py',
        needle='    fields["aeqd_radius_m"] = grid.body.aeqd_radius_m\n',
        replacement='',
        guard='test_the_projection_radius_is_recorded',
    ),
    # The two spheres collapse into one. 7 km apart, so the cap still projects and still blends —
    # it simply lands on a different parallel than the tiles it feathers into.
    Sabotage(
        suite='python',
        label='the AEQD sphere is collapsed onto the Mercator one, moving the cap off its parallel',
        path='pipeline/bodies.py',
        # Earth's copy, disambiguated from Mars's by the comment above it — see the note on the
        # Mercator case for why the bare line is no longer unique.
        needle=("    # The caps' AEQD sphere. NOT the Mercator one above, and not MapLibre's globe "
                "radius.\n    aeqd_radius_m=6371000.0,"),
        replacement=("    # The caps' AEQD sphere. NOT the Mercator one above, and not MapLibre's "
                     "globe radius.\n    aeqd_radius_m=6378137.0,"),
        guard='test_a_body_carries_two_distinct_radii_and_they_are_not_interchangeable',
    ),
    # --- Where a cap reads and writes ----------------------------------------------------------
    # Each of these leaves a cap that renders and blends perfectly; only its LOCATION is wrong, and
    # a location is exactly what no rendered pixel can report on.
    Sabotage(
        suite='python',
        label='the served cap directory ignores the body, so a Mars cap overwrites Earth\'s texture',
        path='pipeline/tile/cap_render.py',
        needle='    return bodies.public_dir(body, "caps")',
        replacement='    return bodies.public_dir(bodies.EARTH, "caps")',
        guard='test_a_second_body_cannot_land_its_caps_on_earths',
    ),
    # The reading half, which is worse: it does not overwrite anything, it renders a clean Arctic
    # from Earth's fused heightfield and publishes it as another planet's pole.
    Sabotage(
        suite='python',
        label="a second body's caps source Earth's fused planet rasters",
        path='pipeline/planet_seam.py',
        needle='    return bodies.work_dir(body, "planet")',
        replacement='    return bodies.work_dir(bodies.EARTH, "planet")',
        guard='test_a_second_body_cannot_land_its_caps_on_earths',
    ),
    # The two roots collapse. Served assets would follow the relocatable data store instead of the
    # checkout, so a run with MAPS_DATA set publishes nothing and reports success.
    Sabotage(
        suite='python',
        label='served cap textures follow the data store rather than the checkout',
        path='pipeline/tile/cap_render.py',
        needle='    return bodies.public_dir(body, "caps")',
        replacement='    return bodies.work_dir(body, "caps")',
        guard='test_earth_reads_and_writes_exactly_where_it_always_has',
    ),
    # --- The web body descriptor -----------------------------------------------------------------
    # `--accent` has no bare `:root` declaration by design: a page that reaches the stylesheet
    # without `data-body` must lose its accent visibly rather than wear Earth's silently. That makes
    # the attribute load-bearing for every link, button and heading rule on the site.
    Sabotage(
        suite='web',
        label='the layout stops writing data-body, so every page loads with no accent at all',
        path='web/src/layouts/Base.astro',
        needle='<html\n  lang="en"\n  class="no-js"\n  data-body={body}\n  data-globe-route={routes.globe}\n  data-lite-route={routes.lite}\n>',
        replacement='<html\n  lang="en"\n  class="no-js"\n  data-globe-route={routes.globe}\n  data-lite-route={routes.lite}\n>',
        guard='renders data-body on <html>, server-side and unconditionally',
    ),
    # The attribute goes on the wrong element. `:root` IS <html>, so this compiles, renders, and
    # silently matches nothing — a mistake no type can catch, since both spellings are valid Astro.
    Sabotage(
        suite='web',
        label='data-body lands on <body>, where the token block cannot see it',
        path='web/src/layouts/Base.astro',
        needle='<html\n  lang="en"\n  class="no-js"\n  data-body={body}\n  data-globe-route={routes.globe}\n  data-lite-route={routes.lite}\n>',
        replacement='<html\n  lang="en"\n  class="no-js"\n  data-globe-route={routes.globe}\n  data-lite-route={routes.lite}\n>\n  <body data-body={body}>',
        guard='renders data-body on <html>, server-side and unconditionally',
    ),
    # A bare fallback creeps back in. Earth looks perfect and the attribute becomes decorative, so
    # the second body inherits Earth's teal at exactly the moment nobody is checking Earth.
    Sabotage(
        suite='web',
        label='a bare :root accent returns, making a page that declares no body silently Earth',
        path='web/src/styles/global.css',
        needle=':root[data-body="earth"] {\n  --accent: #3a6e7d;',
        replacement=':root {\n  --accent: #3a6e7d;',
        guard='leaves the accent undefined when no body is declared, rather than defaulting to Earth',
    ),
    # The copied colour drifts. This is the WATER_RGB failure one layer up: the stylesheet and the
    # descriptor both state the accent, and only a test comparing them can notice they stopped agreeing.
    Sabotage(
        suite='web',
        label="the stylesheet's accent drifts from the descriptor that is supposed to own it",
        path='web/src/styles/global.css',
        needle='  --accent: #3a6e7d; /* deep-sea teal, from the hero ramp */',
        replacement='  --accent: #3a6f7d; /* deep-sea teal, from the hero ramp */',
        guard="computes the descriptor's colour for every body the site knows",
    ),
    # The prop gains a default, which is what makes `astro check` stop asking. The page that forgets
    # to name its body then renders in Earth's chrome and passes every gate.
    Sabotage(
        suite='web',
        label='the body prop gains a default, so a page that names no planet quietly gets Earth',
        path='web/src/layouts/Base.astro',
        needle='  body,\n} = Astro.props;',
        replacement='  body = "earth",\n} = Astro.props;',
        guard='takes the body as a required prop with no default',
    ),
    # --- What a body declares it SHIPS -----------------------------------------------------------
    # Three booleans naming subsystems built for Earth. Each type-checks at either value and each is
    # invisible when wrong: the symptom is a subsystem that quietly never runs, or one that runs
    # against nothing. The plausible mutation is always the same — a body "completed" to match the
    # reference one, which is how a second planet inherits an answer nobody gave.
    Sabotage(
        suite='python',
        # Deliberately a PYTHON case over a web file: the pipeline decides whether ~14 GB per pole
        # gets rendered, so the browser flag is only ever the second half of that fact. Flipping it
        # here makes the globe fetch a caps.json for a body whose caps were never rendered, and the
        # 404 lands in a `.catch` that logs and moves on.
        label="Mars claims polar caps the pipeline never renders",
        path='web/src/lib/bodies.ts',
        needle='    rendersPolarCaps: false,',
        replacement='    rendersPolarCaps: true,',
        guard='test_the_two_registries_agree_on_which_bodies_render_polar_caps',
    ),
    Sabotage(
        suite='python',
        # The guard on the guard. Its scan must decide ENCLOSURE, not match a text span: every
        # descriptor nests an `accent` object, so a counter that stops counting ends each body's
        # block at the wrong brace and reads the wrong planet's answer — or, as here, no answer.
        label="the descriptor scan stops counting braces, so a nested object ends the block",
        path='tests/test_bodies.py',
        needle='        if character == "{":\n            depth += 1',
        replacement='        if character == "{":\n            pass',
        guard='test_the_two_registries_agree_on_which_bodies_render_polar_caps',
    ),
    Sabotage(
        suite='web',
        # Heroes with no countries pyramid is a panel with no route into it: on the globe the only
        # way one opens is a map click hit-tested against the countries MVT.
        label='Mars claims heroes, which nothing on its globe could ever open',
        path='web/src/lib/bodies.ts',
        needle='    hasHeroes: false,',
        replacement='    hasHeroes: true,',
        guard='gives heroes only to a body that publishes a countries pyramid',
    ),
    Sabotage(
        suite='web',
        # Borders have no coherence partner, so nothing structural can refuse this one. What catches
        # it is the flag having both answers somewhere in the record — which is the check that stops
        # a per-body switch quietly becoming a constant.
        label='Mars claims political borders, and the flag stops varying at all',
        path='web/src/lib/bodies.ts',
        needle='    hasBorders: false,',
        replacement='    hasBorders: true,',
        guard='holds both answers to every flag, so none of them is a constant in disguise',
    ),
    # --- What a body's globe actually draws -------------------------------------------------------
    # The three flags above answer nothing until something reads them. These cases cover the module
    # that does, plus the two sites in the page where a gate can quietly go missing. The whole point
    # of the module is that "show me only the raster" and "this planet only HAS a raster" stopped
    # being two conditions maintained apart.
    Sabotage(
        suite='web',
        # The registry stops being consulted and only the flags decide, so every body draws Earth's
        # caps — a cap in another planet's palette, silently, since a texture that renders is a
        # texture that looks deliberate.
        label='the caps forget to ask the body, and every planet gets a polar texture',
        path='web/src/lib/globeSubsystems.ts',
        needle='    polarCaps: descriptor.rendersPolarCaps && !bare && !flags.has("nocaps"),',
        replacement='    polarCaps: !bare && !flags.has("nocaps"),',
        guard='gives a relief-only body its raster and nothing else',
    ),
    Sabotage(
        suite='web',
        # The tidy that reads as a simplification: a field that is `true` for the only body anyone
        # has looked at becomes `true`. It survives every Earth test by construction.
        label='terrain is declared for every body, including the ones with no DEM pyramid',
        path='web/src/lib/globeSubsystems.ts',
        needle='    terrain: published.terrain !== null,',
        replacement='    terrain: true,',
        guard='never advertises a pyramid the body does not publish, whatever the URL says',
    ),
    Sabotage(
        suite='web',
        # One flag stops taking one thing away. Nothing about Earth's default globe changes, and the
        # only reader who notices is someone using ?bare to isolate the raster — i.e. someone already
        # hunting something else.
        label='?bare stops stripping the borders overlay, so the isolation is partial',
        path='web/src/lib/globeSubsystems.ts',
        needle='    borders: descriptor.hasBorders && !bare,',
        replacement='    borders: descriptor.hasBorders,',
        guard='strips every body down to the same floor, whatever that body publishes',
    ),
    Sabotage(
        suite='web',
        # THE DEFECT THE COMMIT EXISTS FOR, restored. Building an address for an unpublished layer
        # throws, and this runs at module scope — so the globe is blank before a map is constructed.
        # Earth notices nothing, because Earth publishes all three.
        label='a tile address is built for a layer the body does not publish, and the globe dies',
        path='web/src/lib/globeSubsystems.ts',
        needle='    terrain: drawn.terrain ? tileUrlTemplate(body, "terrain") : null,',
        replacement='    terrain: tileUrlTemplate(body, "terrain"),',
        guard='resolves for a body that publishes only relief, instead of throwing at page load',
    ),
    Sabotage(
        suite='web',
        # A gate deleted in the page rather than in the module. This is the shape a source scan is
        # the only available guard for: the gates live in a client script nothing can import.
        label='the hero panel opens for a body with no heroes rendered',
        path='web/src/components/Globe.astro',
        needle='    if (subsystems.heroes) openPanel(country);',
        replacement='    openPanel(country);',
        guard='is READ by the globe for every answer it gives, so none of them is decoration',
    ),
    Sabotage(
        suite='web',
        # The regression back to two readers. Caps would go on working for Earth and would be asked
        # for on a body that publishes none — a `caps.json` 404 the console swallows.
        label='the page reads the caps flag itself again instead of asking the registry',
        path='web/src/components/Globe.astro',
        needle='  if (subsystems.polarCaps) {',
        replacement='  if (!urlFlags.has("nocaps")) {',
        guard='is the only thing reading the flags it owns, so one place decides',
    ),
    Sabotage(
        suite='python',
        # The parser goes back to letting a bad guess outlive its line. A quote character inside a
        # regex literal then runs until the next one anywhere in the file, so every `/*` in between
        # is invisible — and the check reports an unclosed comment against whichever innocent line it
        # could finally see. The repo stays green until some unrelated file grows an apostrophe.
        label='a phantom string outlives its line, and the comment check blames the wrong file',
        path='tests/test_repo_integrity.py',
        needle="""            if quote in ('"', "'"):\n                quote = None\n""",
        replacement='',
        guard='test_a_quote_inside_a_regex_literal_does_not_swallow_the_rest_of_the_file',
    ),
    Sabotage(
        suite='python',
        # The harness's own blind spot, restored: four MUTABLE_ROOTS are single FILES, and
        # `rglob` on a file matches nothing. `--restore` then reports a sabotaged tree clean,
        # which is how a mutation survives into a commit. Found by a killed run, not by a check.
        #
        # Two lines, with the newline written as an ESCAPE, for the reason the cases above give:
        # a needle quoting one line of this file matches twice, once at the real site and once
        # inside the literal here.
        label='the backup finder goes back to globbing file roots, and reports a dirty tree clean',
        path='scripts/sabotage.py',
        needle="        if path.is_dir():\n            found.extend(path.rglob(",
        replacement="        if True:\n            found.extend(path.rglob(",
        guard='test_a_backup_beside_a_single_file_root_is_found',
    ),
    # --- A ground metre is worth what the body says -----------------------------------------------
    # The ruler is the only readout on the page that claims to be MEASURED. Every mutation here
    # leaves it rendering a plausible number at every zoom, which is the whole reason the original
    # defect survived a body registry, a required `--body` and two rounds of parameterisation.
    Sabotage(
        suite='web',
        # The radius argument stops being used and the arc is Earth's again — the state this commit
        # left. Earth notices nothing; Mars reads 1.876x long.
        label='the arc is scaled by a fixed radius, so every planet reports Earth distances',
        path='web/src/lib/scaleRuler.ts',
        needle='  return groundRadiusM * Math.acos(Math.min(cosineOfArc, 1));',
        replacement='  return 6371008.8 * Math.acos(Math.min(cosineOfArc, 1));',
        guard='reports a second body\'s distances on that body, through the same live camera',
    ),
    Sabotage(
        suite='web',
        # The clamp goes, which is invisible until two samples land on one point: `Math.acos` of a
        # cosine a hair above 1 is NaN, and the formatter renders NaN as the em-dash it keeps for
        # "not a distance". A parked globe would blank its own ruler.
        label='the cosine clamp goes, and a stationary camera blanks the ruler',
        path='web/src/lib/scaleRuler.ts',
        needle='  return groundRadiusM * Math.acos(Math.min(cosineOfArc, 1));',
        replacement='  return groundRadiusM * Math.acos(cosineOfArc);',
        guard='survives two samples landing on the same point, where the cosine can exceed 1',
    ),
    Sabotage(
        suite='web',
        # Earth's radius is "corrected" to the equatorial figure the pipeline carries. Every label
        # is unchanged at two significant figures, and the ruler quietly stops measuring the sphere
        # MapLibre draws.
        label='Earth takes the pipeline\'s equatorial radius, and the ruler leaves the geometry',
        path='web/src/lib/bodies.ts',
        needle='    groundRadiusM: 6371008.8,',
        replacement='    groundRadiusM: 6378137.0,',
        guard='measures Earth on the sphere MapLibre draws Earth on',
    ),
    Sabotage(
        suite='python',
        # The second body's radius drifts to the OTHER Mars figure — 3,389,500 m is the IAU mean,
        # and it is 0.2% out from the sphere this DEM is actually published on.
        label='a body\'s radius drifts to a different published figure for the same planet',
        path='web/src/lib/bodies.ts',
        needle='    groundRadiusM: 3396190,',
        replacement='    groundRadiusM: 3389500,',
        guard='test_the_two_registries_hold_one_radius_for_a_body_that_is_really_a_sphere',
    ),
    Sabotage(
        suite='web',
        # The page stops passing its own body and hands the ruler Earth's radius directly. The
        # module stays correct and every call site is what decides — which is why the argument is
        # required rather than defaulted, and why this case reads the PAGE.
        label='the page hands the ruler a literal radius instead of the body it is drawing',
        path='web/src/components/Globe.astro',
        needle='        body.groundRadiusM,',
        replacement='        6371008.8,',
        guard='takes the radius from the body it is drawing, not from a number',
    ),
    # --- Which body's pages the routing sends you to ----------------------------------------------
    # Every case below is the code as it was written for one globe, restored. None of them changes
    # anything a visitor to Earth would see, because on Earth the literal and the registry agree —
    # which is exactly why the wrong version survived until a second body had a page.
    Sabotage(
        suite='web',
        # The bounce goes back to Earth's gallery, so a device that cannot draw Mars is answered by
        # being shown a different planet, before paint, with nothing on screen to say so.
        label='a visitor bounced off a globe lands on Earth, whichever body they were looking at',
        path='web/src/layouts/Base.astro',
        needle='            if (quality === "lite" || !capable()) location.replace(liteRoute);',
        replacement='            if (quality === "lite" || !capable()) location.replace("/");',
        guard="bounces a Lite visitor off Mars's globe to MARS's fallback, not Earth's",
    ),
    Sabotage(
        suite='web',
        # And the steer, which is the same defect pointing the other way: a capable visitor on any
        # body's lite page is carried to Earth's globe.
        label='the auto-steer carries every body to Earth',
        path='web/src/layouts/Base.astro',
        needle='          location.replace(globeRoute);',
        replacement='          location.replace("/earth/");',
        guard="steers a capable visitor from Mars's fallback onto Mars's globe",
    ),
    Sabotage(
        suite='web',
        # The tidy that looks like removing a pointless normalisation. Astro serves both spellings,
        # so the guard would simply stop firing for anyone who arrived by the other one — and the
        # site's own links all use the spelling that keeps working.
        label='the guard compares paths exactly, so the other trailing-slash spelling is unguarded',
        path='web/src/layouts/Base.astro',
        needle=r'            return String(a).replace(/\/+$/, "") === String(b).replace(/\/+$/, "");',
        replacement='            return String(a) === String(b);',
        guard="reads both trailing-slash spellings of a body's globe",
    ),
    Sabotage(
        suite='web',
        # The view bar half. Nothing can import this script, so its only guard is a scan — and the
        # mutation is the code that shipped: Globe and Full on Mars navigating to Earth.
        label="the tier picker's buttons navigate to Earth from every body",
        path='web/src/layouts/Base.astro',
        needle='        const target = choice === "lite" ? routes.lite : routes.globe;',
        replacement='        const target = choice === "lite" ? "/" : "/earth/";',
        guard="takes both tier destinations from the body's own routes",
    ),
    Sabotage(
        suite='web',
        # The stamp goes missing. This is the silent one: the guard is wrapped in try/catch so it can
        # never break a page, so a missing attribute takes every branch of it out of service without
        # a console line anywhere.
        label='the layout stops stamping the fallback route the pre-paint guard reads',
        path='web/src/layouts/Base.astro',
        needle='  data-lite-route={routes.lite}\n',
        replacement='',
        guard='puts the body and both of its routes on that element',
    ),
    Sabotage(
        suite='web',
        # The derivation that justifies not storing a globe route at all becomes a literal. Earth is
        # unchanged by construction, and every other body's globe address is now Earth's.
        label="a body's globe route stops being derived from its own slug",
        path='web/src/lib/bodyRoutes.ts',
        needle='  return { globe: `/${slug}/`, lite: BODIES[slug].liteRoute };',
        replacement='  return { globe: "/earth/", lite: BODIES[slug].liteRoute };',
        guard="puts every body's globe at its own slug",
    ),
    Sabotage(
        suite='web',
        # THE MISTAKE THE SECOND GLOBE PAGE MAKES POSSIBLE, and it is one word. `mars.astro` is
        # `earth.astro` with the descriptor changed; leave the descriptor and the page still builds,
        # still routes at /mars/, still draws Mars's relief — in Earth's accent, with a Lite button
        # aimed at Earth's gallery and a pre-paint guard that steers an incapable visitor there.
        label="a body's page keeps the descriptor of the page it was copied from",
        path='web/src/pages/mars.astro',
        needle='const body = BODIES.mars;',
        replacement='const body = BODIES.earth;',
        guard='dresses every page a body owns in that body, and not in the one next door',
    ),
    Sabotage(
        suite='web',
        # The copy-paste slip the per-body split exists to prevent, and the one that reads as a
        # tidy: Mars's source is filed under Earth's heading. Nothing is lost from the page — the
        # card still renders, the citation is still there — but the reader is now told that the
        # planet's data sits under the group whose terms are Copernicus's, which is the exact
        # inference the two groups exist to stop.
        label="a body's data sources are filed under the planet next door",
        path='web/src/pages/about.astro',
        needle='    body: "Mars",',
        replacement='    body: "Earth",',
        guard='gives every registered body a group of its own',
    ),
    Sabotage(
        suite='python',
        # The licence change reaches the three files a reader browses and misses the one nobody
        # opens. LICENSE has no extension, sorts away from the docs, and is the copy a court would
        # read first — so it is exactly the copy a sweep-by-eye skips.
        label='the LICENSE file keeps the superseded output licence after the other three move',
        path='LICENSE',
        needle='under CC BY-SA 4.0; see ATTRIBUTIONS.md',
        replacement='under CC BY-NC 4.0; see ATTRIBUTIONS.md',
        guard='test_every_site_states_the_output_license',
    ),
    Sabotage(
        suite='python',
        # A live link to the withdrawn licence, left behind on the page that grants the rights. It
        # renders, it resolves, and it reads as deliberate — the visitor is simply told the wrong
        # terms. Prose naming the old licence is allowed on purpose, so only the URL can catch it.
        label='the About page still LINKS the superseded licence beside the current name',
        path='web/src/pages/about.astro',
        needle="          <p set:html={licenceHtml} />\n",
        replacement=(
            "          <p set:html={licenceHtml} />\n"
            '          <p><a href="https://creativecommons.org/licenses/by-nc/4.0/">terms</a></p>\n'
        ),
        guard='test_no_tracked_file_links_the_superseded_output_license',
    ),
    Sabotage(
        suite='python',
        # The tidy that guts the sweep: .astro looks like markup rather than a place a licence is
        # declared, so dropping it reads as narrowing the scan to documents. It takes the About
        # page — the only page that states the licence to a visitor — out of scope, and only the
        # anti-vacuity NAMING that file rather than counting files can tell.
        label='the licence sweep stops reading the file type the About page is written in',
        path='tests/test_attributions.py',
        needle='LICENSE_BEARING_SUFFIXES = {".md", ".py", ".ts", ".astro", ".html"}',
        replacement='LICENSE_BEARING_SUFFIXES = {".md", ".py", ".ts", ".html"}',
        guard='test_no_tracked_file_links_the_superseded_output_license',
    ),
    Sabotage(
        suite='python',
        # The requested citation drops off the user-facing page while staying in the source of
        # truth — the exact drift `test_attributions.py` was written for, now covering a string
        # the publisher asks for in its Use Constraints rather than one a licence compels.
        label="the Mars blend's requested citation is trimmed off the About page",
        path='web/src/pages/about.astro',
        needle='Fergason, R. L, Hare, T. M., & Laura, J. (2018). HRSC and MOLA Blended Digital Elevation Model at 200m v2. Astrogeology PDS Annex, U.S. Geological Survey. ',
        replacement='',
        guard='test_about_page_carries_the_required_string',
    ),
    Sabotage(
        suite='web',
        # The repo URL inlined on a page that did not exist when the no-literals rule was written.
        # That rule read a hand-written list of four names, so a fifth page was outside it — and a
        # page nobody checks cannot fail. Caught only because the list became a walk.
        label='a new page inlines the repository URL the shared constant exists to own',
        path='web/src/pages/mars.astro',
        needle='  <Globe />\n',
        replacement='  <Globe />\n  <a href="https://github.com/Alchez/terrella">source</a>\n',
        guard='is never inlined as a literal, which is the drift this constant exists to stop',
    ),
    Sabotage(
        suite='web',
        # A per-country flag collapsed to one arm, which is the tidy reading of an expression the
        # parser cannot resolve statically. `[slug].astro` then turns nothing on, drops out of the
        # measured set entirely, and 203 rendered documents ship a bar nothing has ever sized.
        label='a bar flag that varies per country is read as simply off',
        path='web/src/lib/viewBar.browser.test.ts',
        needle='    return "varies";',
        replacement='    return false;',
        guard='is measuring the shipped markup and stylesheet, not an empty string',
    ),
    Sabotage(
        suite='web',
        # The registry edit that reads as reuse rather than as a decision: Mars falls back to the
        # page Earth falls back to. It is one string, and it undoes the whole commit. Named against
        # the ANTI-VACUITY assertion rather than the one below, because sharing a fallback is not
        # landing on another body's globe — it is the two bodies ceasing to have separate answers,
        # which is the property that check exists to state. The harness is what settled which: the
        # first version of this case named the wrong guard and was reported WRONG rather than caught.
        label='a second body borrows the first body\'s fallback page',
        path='web/src/lib/bodies.ts',
        needle='    liteRoute: "/mars/lite/",',
        replacement='    liteRoute: "/",',
        guard='has the bodies actually disagree, on both routes',
    ),
    Sabotage(
        suite='web',
        # The other shortcut on the same line, and the one the check below is really for: rather
        # than write a page, point the fallback at the globe that already exists. It answers "your
        # device cannot draw Mars" by drawing Earth — on hardware that, by construction, cannot draw
        # either, so the visitor gets bounced twice and lands where they started.
        label='a body with no lite page points its fallback at another body\'s globe',
        path='web/src/lib/bodies.ts',
        needle='    liteRoute: "/mars/lite/",',
        replacement='    liteRoute: "/earth/",',
        guard='never sends a visitor off this body when they cannot run its globe',
    ),
    # --- The globe's two stylesheets -------------------------------------------------------------
    # The global rules are a file so a second body's page can import the same one; the SCOPED block
    # cannot follow, because Astro stamps it with `[data-astro-cid-…]` and that attribute is worth a
    # class of specificity. Both mutations below leave every rule intact and change only where it
    # lives, which is the entire failure mode: no error, no missing declaration, just a level lost.
    Sabotage(
        suite='web',
        label='the page stops importing its global stylesheet, shipping the widgets unstyled',
        path='web/src/components/Globe.astro',
        needle='import "../styles/globe.css";\n',
        replacement='',
        guard='imports the global stylesheet, or the globe ships with none of it',
    ),
    # The scoped block is re-declared global, which strips the cid from every rule in it.
    Sabotage(
        suite='web',
        label='the scoped block goes global, dropping a specificity level off every page rule',
        path='web/src/components/Globe.astro',
        needle='\n<style>\n',
        replacement='\n<style is:global>\n',
        guard='keeps the SCOPED block beside its markup, where Astro can stamp both',
    ),
    # A scoped rule migrates into the shared file, where it compiles without its cid.
    Sabotage(
        suite='web',
        label='a page-scoped rule is moved into the shared stylesheet and loses its cid',
        path='web/src/styles/globe.css',
        needle='.chrome-credit.chrome-credit.maplibregl-ctrl.maplibregl-ctrl {',
        replacement='.starfield {\n  z-index: 0;\n}\n.chrome-credit.chrome-credit.maplibregl-ctrl.maplibregl-ctrl {',
        guard="keeps the globe's own scoped elements out of the shared stylesheet",
    ),
    # --- The globe's floor is a body fact --------------------------------------------------------
    # `space-floor` exists so a gap in the tiles reads as more of this planet rather than as a hole
    # to space. Every mutation below leaves a globe that renders perfectly for Earth and is wrong in
    # a way that looks like slow loading for anything else.
    Sabotage(
        suite='web',
        label='the space-floor goes back to a fixed colour, so every body gets Earth\'s ocean',
        path='web/src/components/Globe.astro',
        needle='paint: { "background-color": body.spaceFloor }',
        replacement='paint: { "background-color": "#47808F" }',
        guard='paints the background layer from the descriptor',
    ),
    # The runtime lookup stops being strict. A page whose layout forgot to declare its body then
    # draws Earth's sea under its missing tiles and reports nothing.
    Sabotage(
        suite='web',
        label='the page falls back to Earth when no body is declared instead of failing',
        # Moved out of bodies.ts: the registry is compiled by the tile Worker, which has no DOM.
        path='web/src/lib/currentBody.ts',
        needle='  if (slug === undefined) {\n    throw new Error(\n      "<html> carries no data-body: the page\'s layout must declare which body it draws",\n    );\n  }',
        replacement='  if (slug === undefined) {\n    return bodyFor("earth");\n  }',
        guard='throws when the layout declared nothing, rather than assuming Earth',
    ),
    # The imported stop becomes a third hand-typed copy of the hex, with nothing comparing it back
    # to the sea surface it is supposed to match — the WATER_RGB failure, repeated.
    Sabotage(
        suite='web',
        label="the body's floor colour is retyped instead of imported, and drifts off the ramp",
        path='web/src/lib/bodies.ts',
        needle='    spaceFloor: DEEP_SEA,',
        replacement='    spaceFloor: "#478090",',
        guard="takes Earth's floor from the pipeline's own stop rather than a third copy of the hex",
    ),
    # --- The cap pass takes its own body ---------------------------------------------------------
    # The same argument the shade pass requires, on the entry point that renders the caps. A default
    # here is worse than one there: the caps are invoked automatically at the shade pass's tail, so
    # a defaulted body means a Mars pass ends by re-rendering Earth's poles and reporting success.
    Sabotage(
        suite='python',
        label='the cap pass defaults its body, so a Mars pass ends by re-rendering Earth\'s poles',
        path='pipeline/tile/cap_render.py',
        needle='    parser.add_argument("--body", required=True,',
        replacement='    parser.add_argument("--body", default="earth",',
        guard='test_omitting_the_body_is_an_error_rather_than_an_assumption',
    ),
    # The handoff itself. Dropping the flag is loud (the cap pass refuses to start); hardcoding the
    # name is silent, and stays silent until the day a second body exists.
    Sabotage(
        suite='python',
        label='the shade pass hands the cap pass a hardcoded earth instead of its own body',
        path='pipeline/tile/shade_planet.py',
        needle='    return [sys.executable, "-m", "pipeline.tile.cap_render", "--body", body.name]',
        replacement='    return [sys.executable, "-m", "pipeline.tile.cap_render", "--body", "earth"]',
        guard='test_the_shade_pass_hands_its_own_body_down_to_the_cap_pass',
    ),
    Sabotage(
        suite='python',
        label='the shade pass stops passing --body to the cap pass at all',
        path='pipeline/tile/shade_planet.py',
        needle='    return [sys.executable, "-m", "pipeline.tile.cap_render", "--body", body.name]',
        replacement='    return [sys.executable, "-m", "pipeline.tile.cap_render"]',
        guard='test_the_shade_pass_hands_its_own_body_down_to_the_cap_pass',
    ),
    # --- The grids are built per body ----------------------------------------------------------
    # A factory that ignores its argument is the exact failure the module constants were deleted to
    # remove, and it is invisible: the cap projects, blends and publishes — on Earth's sphere, from
    # Earth's heightfield, over Earth's shipped textures.
    Sabotage(
        suite='python',
        label='the north grid factory pins Earth, so every body inherits Earth by construction',
        path='pipeline/tile/cap_render.py',
        needle='    return CapGrid(lat_0=90.0, edge_lat=78.0, px=CAP_PX, name="north", az_sign=-1.0, body=body)',
        replacement='    return CapGrid(lat_0=90.0, edge_lat=78.0, px=CAP_PX, name="north", az_sign=-1.0,\n                   body=bodies.EARTH)',
        guard='test_a_factory_carries_the_body_it_was_given_all_the_way_through',
    ),
    # The URL is rebuilt from the basename, which is what it used to be. Correct for Earth, whose
    # segment is empty; every nesting body advertises its whole texture set one directory up.
    Sabotage(
        suite='python',
        label="a cap's served URL is rebuilt from its basename, 404ing every body that nests",
        path='pipeline/tile/cap_render.py',
        needle='    return "/" + asset.relative_to(bodies.PUBLIC_ROOT).as_posix()',
        replacement='    return f"/caps/{asset.name}"',
        guard='test_the_served_url_matches_where_the_texture_is_actually_written',
    ),
    # The pole prefix stops being derived. Both renderers then share one set of AEQD warps, so
    # whichever ran last decides what the other one shaded.
    Sabotage(
        suite='python',
        label='the cap warp prefix is hardcoded north, so both poles share one set of warps',
        path='pipeline/tile/cap_render.py',
        needle='    return cap_work_dir(grid.body) / f"cap{grid.name[0].upper()}_{layer}.tif"',
        replacement='    return cap_work_dir(grid.body) / f"capN_{layer}.tif"',
        guard='test_earth_reads_and_writes_exactly_where_it_always_has',
    ),
    # --- The portrait fill rung ----------------------------------------------------------------
    # A rung names the LONG EDGE while `srcset` selects on WIDTH, so these mutations all produce a
    # ladder that is correct for landscape and silently two rungs short for portrait — which is the
    # original defect, and it shipped under a guard that modelled every country as landscape.
    Sabotage(
        suite='python',
        label='mobile demand is priced off the Lighthouse preset, so no portrait fill rung is made',
        path='pipeline/compose/hero_variants.py',
        needle='MOBILE_DEMAND_PX = 1187',
        replacement='MOBILE_DEMAND_PX = 663',
        guard='test_every_ladder_serves_a_PORTRAIT_country_on_a_real_phone',
    ),
    Sabotage(
        suite='python',
        label='the fill rung is dropped from the ladder, leaving the gap it was added to close',
        path='pipeline/compose/hero_variants.py',
        needle='    fill = fill_rung(width, height)\n    if fill is not None:\n        targets.add(fill)',
        replacement='',
        guard='test_every_ladder_serves_a_PORTRAIT_country_on_a_real_phone',
    ),
    # The overlay is layered on the hero under ONE `sizes`, so a ladder it does not share makes the
    # browser fetch a bigger file for the top layer than for the one underneath. This is the exact
    # revert the tuple-only version of the guard could not see.
    Sabotage(
        suite='python',
        label='gen_spotlight restates the ladder instead of importing it, and misses the fill rung',
        path='pipeline/compose/gen_spotlight.py',
        needle='    sizes = rungs_for(full_w, full_h)',
        replacement='    sizes = sorted(set(list(TARGETS) + [max(full_w, full_h)]))',
        guard='test_the_ladder_matches_the_spotlight_overlay',
    ),
    # An exemption list is where coverage goes to die quietly. If the border ladder is ever fixed,
    # this entry must fail rather than keep exempting nothing.
    Sabotage(
        suite='python',
        label='a ladder is exempted from the mobile contract without actually having a gap',
        path='tests/test_hero_variants.py',
        needle='ClassVar[dict[str, str]] = {\n        "border": (',
        replacement='ClassVar[dict[str, str]] = {\n        "hero": ("no reason at all"),\n        "border": (',
        guard='test_every_exemption_is_load_bearing',
    ),
    # --- the cap ladder: a sweep must not leave a shipped constant swapped -----------------------
    # These three reproduce, exactly, what the two scripts this module replaced actually did. None
    # of them is invented: the first is how a ladder that no longer ended on the default left
    # damp-0.0 pixels under a sidecar the freshness gate called current, and neither predecessor was
    # visible to any gate because they lived in the one directory pyright was told to skip.
    Sabotage(
        suite='python',
        label='the knob sweep restores on the happy path only, so a failed rung leaks its value',
        path='pipeline/tile/cap_ladder.py',
        needle='    previous_knob = knobs[axis]\n    knobs[axis] = value\n    try:\n        yield\n    finally:\n        knobs[axis] = previous_knob',
        replacement='    previous_knob = knobs[axis]\n    knobs[axis] = value\n    yield\n    knobs[axis] = previous_knob',
        guard='test_a_knob_is_restored_when_the_rung_raises',
    ),
    Sabotage(
        suite='python',
        label='a typo\'d axis CREATES a knob instead of being refused, sweeping something unread',
        path='pipeline/tile/cap_ladder.py',
        needle='    if axis not in knobs:\n        raise KeyError(f"unknown axis {axis!r}; sweepable: {\', \'.join(sweepable_axes())}")\n',
        replacement='',
        guard='test_an_unknown_axis_is_refused_rather_than_silently_added',
    ),
    # The label and the picture must agree: a rounded rung renders one size and files it under
    # another, which is the one thing a judging harness may never do.
    Sabotage(
        suite='python',
        label='a fractional px rung is rounded into the ladder instead of refused',
        path='pipeline/tile/cap_ladder.py',
        needle='        fractional = [value for value in parsed if not value.is_integer()]',
        replacement='        fractional = []',
        guard='test_a_fractional_pixel_rung_is_refused_rather_than_rounded',
    ),

    # --- the derived dev store: a wrong path must never be a served pixel ----------------------------
    # The dev server stopped being TOLD where each archive is and now computes it. The value of that
    # is that a second body costs no configuration; the risk it takes on is that a bad derivation is
    # a plausible path rather than an obvious blank, so these break the two rules the paths rest on.
    Sabotage(
        suite='web',
        label='a blank MAPS_DATA stops counting as unset and resolves to a path made of spaces',
        path='web/src/lib/devStores.ts',
        needle='  const configured = env.MAPS_DATA?.trim();',
        replacement='  const configured = env.MAPS_DATA;',
        guard='treats a blank MAPS_DATA as unset, not as the filesystem root',
    ),
    # The copy-paste that would matter: two archives pointing into one stage directory. The terrain
    # request would then open the relief pyramid, whose header check rejects it — but only because
    # the two encodings differ, which is luck rather than a guarantee for the next pyramid.
    Sabotage(
        suite='web',
        label='the terrain archive resolves into the relief stage directory',
        path='web/src/lib/devStores.ts',
        needle='    stage: "planet_terrain",',
        replacement='    stage: "planet_tiles",',
        guard="puts Earth's archives where the pipeline has always written them",
    ),
    Sabotage(
        suite='web',
        label='a blank retired store variable warns anyway, so the warning stops meaning anything',
        path='web/src/lib/devStores.ts',
        needle='  const stillSet = RETIRED_STORE_VARS.filter((name) => env[name]?.trim());',
        replacement='  const stillSet = RETIRED_STORE_VARS.filter((name) => env[name] !== undefined);',
        guard='ignores a blank one, the same way the resolver does',
    ),

    # --- the tile address grammar: every rejection has to be free ------------------------------------
    # A tile server that reaches storage before refusing a typo pays a range read on a multi-gigabyte
    # object for a URL nobody minted. Each of these turns a free refusal into a paid one, or into a
    # served tile — and none of them changes how a CORRECT address behaves, which is why they need a
    # guard rather than a glance.
    Sabotage(
        suite='web',
        label='the extension stops being checked against the layer it names',
        path='web/src/lib/tileAddress.ts',
        needle='  if (extension !== LAYERS[layer].extension) return null;',
        replacement='',
        guard='refuses the wrong extension for the layer',
    ),
    Sabotage(
        suite='web',
        label='a zoom outside the cut is accepted and handed to the archive',
        path='web/src/lib/tileAddress.ts',
        needle='  if (z < published.minZoom || z > published.maxZoom) return null;',
        replacement='',
        guard='refuses a zoom past the cut',
    ),
    # The rule the whole scheme rests on: two raster pyramids in one archive is not a tight packing,
    # it is an address collision — and it would serve terrain bytes where relief was asked for.
    Sabotage(
        suite='web',
        label='terrain is published out of the relief archive',
        path='web/src/lib/tileAddress.ts',
        needle='      objectKey: "terrain-v1.pmtiles",',
        replacement='      objectKey: "planet-v2.pmtiles",',
        guard='never puts two raster pyramids in one archive',
    ),
    # The compatibility half, which is temporary and therefore exactly the half nobody re-reads.
    Sabotage(
        suite='web',
        label='the version-prefix strip loses its anchor and eats a segment mid-path',
        path='web/src/lib/tileAddress.ts',
        needle='const LEGACY_VERSION_PREFIX = /^\\/v\\d+\\//;',
        replacement='const LEGACY_VERSION_PREFIX = /\\/v\\d+\\//;',
        guard='strips that prefix only at the front',
    ),
    Sabotage(
        suite='web',
        label='a legacy terrain URL is mapped to the relief layer',
        path='web/src/lib/tileAddress.ts',
        needle='  if (terrain) return { body: LEGACY_BODY, layer: "terrain", token: null, ...terrain };',
        replacement='  if (terrain) return { body: LEGACY_BODY, layer: "relief", token: null, ...terrain };',
        guard='resolves the SAME tile address to two different archives, which is the whole risk',
    ),

    # --- the client asks the addressed shape, and the instrument reads it -----------------------------
    # The address only matters if the browser uses it, and the panel that reports on it only means
    # anything if it reads the same grammar. Both failures are silent by construction: a template built
    # from the wrong half still renders a globe, and a misclassified tile still shows a plausible count.
    Sabotage(
        suite='web',
        label='the tile template stops carrying the body and the cut',
        path='web/src/lib/assetBase.ts',
        needle='  return `${TILE_BASE}${tilePathTemplate(body, layer)}`;',
        replacement='  return `${TILE_BASE}{z}/{x}/{y}.webp`;',
        guard='names the body, the layer and the cut in every URL it builds',
    ),
    Sabotage(
        suite='web',
        label='every layer is addressed at the relief pyramid',
        path='web/src/lib/assetBase.ts',
        needle='  return `${TILE_BASE}${tilePathTemplate(body, layer)}`;',
        replacement='  return `${TILE_BASE}${tilePathTemplate(body, "relief")}`;',
        guard='rides the SAME base for every layer, because one Worker serves them all',
    ),
    # The regression this pass actually found, re-armed. It was live: a `startsWith("terrain/")` test
    # survived the move to `{body}/{layer}/{token}/…` untouched, so every terrain tile counted as relief
    # on the one panel whose job is telling those two apart.
    Sabotage(
        suite='web',
        label='the traffic split reads a path prefix instead of the servers\' own parser',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='    const slice = traffic[address.layer];',
        replacement='    const slice = path.startsWith("terrain/") ? traffic.terrain : traffic.relief;',
        guard='reads the ADDRESSED grammar, which is what the browser now asks for',
    ),
    Sabotage(
        suite='web',
        label='an entry that parses as no tile is dropped instead of counted',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='      traffic.unaddressedCount++;',
        replacement='',
        guard='does not mistake a path merely CONTAINING a layer word for that layer',
    ),

    # --- one home for the archive keys, and a preflight that enumerates it -----------------------------
    # The preflight is the only thing standing between a re-cut and a live site whose tiles all 404,
    # and it cannot be exercised in CI (it needs R2). So what IS pinned is its shape: that it
    # enumerates rather than naming, and that it refuses to run on an enumeration that found nothing.
    Sabotage(
        suite='web',
        label='the preflight goes back to naming archive keys instead of enumerating them',
        path='web/scripts/check_deploy_sync.ts',
        needle='  checkEveryPublishedArchiveIsUploaded(endpoint);',
        replacement='',
        guard='checks BOTH halves — that the route exists and that the bytes do',
    ),
    Sabotage(
        suite='web',
        label='a parse that finds no archives reports a clean deploy instead of refusing',
        path='web/scripts/check_deploy_sync.ts',
        needle='  if (keys.length === 0) {',
        replacement='  if (false) {',
        guard='checks BOTH halves — that the route exists and that the bytes do',
    ),
    # The vars are gone; what stops them growing back is that nothing in the Worker's config may name
    # an object at all. A fourth key under a new name would slip past a check written on the old names.
    Sabotage(
        suite='web',
        label='an archive key reappears in the Worker config, as a new spelling',
        path='web/worker/wrangler.jsonc',
        needle='  "vars": {',
        replacement='  "vars": {\n    "RELIEF_OBJECT": "planet-v2.pmtiles",',
        guard='names no archive object in the Worker\'s config at all',
    ),

    # --- a second body, and a cache sized for every pyramid at once -----------------------------------
    # Both failures here are silent by construction. A Mars address resolving to Earth's archive draws a
    # complete, plausible, wrong planet; a directory cache one entry short costs a gunzip per tile and
    # reports nothing at all — which is exactly how the hand tally got terrain's leaf count wrong.
    Sabotage(
        suite='web',
        # The one check that replaced three per-layer `assert*ZoomRange` functions. Half of it is
        # easy to lose: a re-cut that moves only the FLOOR is the rarest case and the one a reader
        # trims when tidying the condition, and nothing downstream notices — the server just opens
        # an archive whose first level is not the one the registry promised.
        label='the archive header check stops comparing the zoom FLOOR',
        path='web/src/lib/tileAddress.ts',
        needle=(
            '  if (header.minZoom === published.minZoom && header.maxZoom === published.maxZoom)'
            ' return null;'
        ),
        replacement='  if (header.maxZoom === published.maxZoom) return null;',
        guard='catches drift in BOTH directions, because neither shows up as an error',
    ),
    Sabotage(
        suite='web',
        # Re-anchored when Mars started publishing. The old case made Mars's `null` into Earth's
        # archive; there is no `null` to mutate now, and the live failure moved with it. What is
        # left is the tidy-looking one: Mars's ceiling written as the module constants that sit
        # three lines above it in the same file. It compiles, it reads as removing a magic number,
        # and it makes a z7 and z8 Mars address parse against a pyramid cut to z6.
        label='Mars relief takes Earth\'s zoom ceiling instead of its own',
        path='web/src/lib/tileAddress.ts',
        needle='      minZoom: 0,\n      maxZoom: 6,',
        replacement='      minZoom: RELIEF_MIN_ZOOM,\n      maxZoom: RELIEF_MAX_ZOOM,',
        guard='bounds a Mars relief address by MARS\'s ceiling, not Earth\'s',
    ),
    Sabotage(
        suite='web',
        label='the directory cache goes back to a hand-typed capacity',
        path='web/worker/index.ts',
        needle='const DIRECTORY_CACHE = new ResolvedValueCache(directoryCacheEntries(), undefined, nativeDecompress);',
        replacement='const DIRECTORY_CACHE = new ResolvedValueCache(64, undefined, nativeDecompress);',
        guard='sizes the directory cache by SUMMING the registry, not by a literal',
    ),
    Sabotage(
        suite='web',
        label='the cache sum counts archives but not their leaf directories',
        path='web/worker/index.ts',
        needle='      if (archive) entries += CACHE_ENTRIES_BEFORE_LEAVES + archive.indexLeaves;',
        replacement='      if (archive) entries += CACHE_ENTRIES_BEFORE_LEAVES;',
        guard='covers every published archive at once, with room above the worst case',
    ),
    Sabotage(
        suite='web',
        # REPLACES 'a leaf count is committed as a placeholder zero', which mutated Earth's 21 to 0.
        # That rule was deliberately dropped when Mars arrived: a z0-6 index spills to no leaf
        # directories at all, so 0 is a real answer and `> 0` was Earth's scale written as a law.
        # The case outlived the rule it named for several commits, invisible because every harness
        # run in between was filtered to the module being worked on. What survives the relaxation is
        # the token, where the placeholder is a shape no real hash takes.
        #
        # A hand-edited leaf count now has no oracle inside the suite — only `check:tile-tokens`,
        # which reads the archives themselves and so cannot run on a checkout without a data store.
        label='a token is committed as its placeholder, addressing an archive nothing can bust',
        path='web/src/lib/tileTokens.json',
        needle='"token": "4d04db58"',
        replacement='"token": "00000000"',
        guard='holds a real hash for every one, never the placeholder',
    ),
    # --- the packer learns which planet it is packing --------------------------------------------
    # This stage is the last one before an archive exists, and it has no output a reader can check:
    # a wrong-tree pack produces a complete, valid MBTiles that only announces itself when a globe
    # draws the other planet. Every case below is a way of making the body decorative.
    Sabotage(
        suite='python',
        label='the packer takes a body and then ignores it, packing every planet from one tree',
        path='pipeline/tile/pack_pmtiles.py',
        needle='    return bodies.work_dir(body, "planet_tiles") / "tiles"',
        replacement='    return bodies.work_dir(bodies.EARTH, "planet_tiles") / "tiles"',
        guard='test_mars_nests_under_its_own_prefix',
    ),
    # The quieter half of the pair: reading the right pyramid and writing the archive into Earth's
    # tree. It packs the correct tiles, so every count and every checksum inside the file is right.
    Sabotage(
        suite='python',
        label='a second planet writes its archive beside Earth\'s',
        path='pipeline/tile/pack_pmtiles.py',
        needle='    return bodies.work_dir(body, "planet_tiles") / "planet.mbtiles"',
        replacement='    return bodies.work_dir(bodies.EARTH, "planet_tiles") / "planet.mbtiles"',
        guard='test_mars_nests_under_its_own_prefix',
    ),
    # The default nobody would notice, because on this box it is right. Earth is the only body whose
    # prefix is empty, so an Earth fallback is invisible until the run that needed the other one.
    Sabotage(
        suite='python',
        label='the packer\'s body acquires a default and a Mars run silently packs Earth',
        path='pipeline/tile/pack_pmtiles.py',
        needle='    parser.add_argument("--body", required=True,',
        replacement='    parser.add_argument("--body", default="earth",',
        guard='test_the_body_is_required_with_no_default',
    ),
    # The tidy that looks like the parameterisation finishing and is the one change here that costs
    # real money: the name reaches the archive header, the header is inside the SHA that becomes the
    # tile token, and the token is in every served URL.
    Sabotage(
        suite='python',
        label='the archive name is derived from the body, changing every tile URL the site serves',
        path='pipeline/tile/pack_pmtiles.py',
        needle='    pack_directory(tiles, out, name=args.name)',
        replacement='    pack_directory(tiles, out, name=f"terrella-{body.name}-relief")',
        guard='test_the_default_name_does_not_vary_with_the_body',
    ),
    # `default_tiles` and `default_out` could both be exactly right while `main` called neither —
    # which is what the module did before it had a body at all.
    Sabotage(
        suite='python',
        label='the resolved defaults are computed and then not used',
        path='pipeline/tile/pack_pmtiles.py',
        needle='    tiles = args.tiles if args.tiles is not None else default_tiles(body)',
        replacement='    tiles = args.tiles if args.tiles is not None else default_tiles(bodies.EARTH)',
        guard='test_the_body_selects_the_paths_main_actually_packs',
    ),
    # --- the shared-dataset seam ------------------------------------------------------------
    # Everything here is invisible on a developer box, because `MAPS_DATA` is unset and the two
    # roots resolve to the same directory. That is precisely how eight spellings of one path
    # accumulated: every one of them was right, on this machine, every time anyone looked.
    Sabotage(
        suite='python',
        label='the vectors go back to being read out of the checkout',
        path='pipeline/naturalearth.py',
        needle='DIR = paths.DATA / "raw/naturalearth"',
        replacement='DIR = paths.ROOT / "data/raw/naturalearth"',
        guard='test_no_module_path_stays_behind_when_the_store_moves',
    ),
    # The probe itself, reverted to reading the ABSOLUTE path's segments. That version answers a
    # question about the machine as well as the repo, and CI's checkout sits two levels under a
    # directory the runner names `work` — so it reported all sixteen checkout-resident constants,
    # `config/` and `web/public` and `blender/renders` among them, as data paths left behind.
    #
    # THE CASE IS ONLY REACHABLE FROM A DIFFERENTLY-NAMED CHECKOUT, which is the whole difficulty:
    # the mutation is invisible from this one, so `test_no_module_path_stays_behind_when_the_store
    # _moves` stays green through it and only the test that builds its own `work/` checkout fires.
    Sabotage(
        suite='python',
        label='the store probe reads the machine\'s path segments as well as the repo\'s',
        path='tests/test_paths.py',
        needle=('        below = (value.relative_to(paths.ROOT).parts\n'
                '                 if value.is_relative_to(paths.ROOT) else value.parts)'),
        replacement='        below = value.parts',
        guard='test_the_probe_reads_the_repos_own_segments_and_not_the_machines',
    ),
    # The other half of the same seam, in the other language. The writer moving alone is worse than
    # neither moving: the acquirer fills one tree and seven readers look in the other.
    Sabotage(
        suite='python',
        label='the acquirer writes into the checkout while every reader looks in the store',
        path='pipeline/acquire/download_naturalearth.sh',
        needle='DATA="${MAPS_DATA:-$(cd "$(dirname "$0")/../.." && pwd)/data}"',
        replacement='DATA="$(cd "$(dirname "$0")/../.." && pwd)/data"',
        guard='test_maps_data_moves_the_acquirers_destination',
    ),
    # Natural Earth repeats each layer name as its directory AND its stem. Dropping one half is the
    # single likeliest typo in this module, and it fails as a missing file, which reads like a
    # download that never completed rather than like a path that was assembled wrong.
    Sabotage(
        suite='python',
        label='the layer join loses the directory level',
        path='pipeline/naturalearth.py',
        needle='    return (DIR if directory is None else directory) / name / f"{name}.shp"',
        replacement='    return (DIR if directory is None else directory) / f"{name}.shp"',
        guard='test_the_name_appears_as_both_directory_and_stem',
    ),
    # The tidy that looks like a redundant check being removed. Without it a typo resolves to a
    # plausible path and the error arrives frames later, from shapefile, about a missing file.
    Sabotage(
        suite='python',
        label='the layer vocabulary stops being checked, so a typo becomes a missing file',
        path='pipeline/naturalearth.py',
        needle='    if name not in LAYERS:',
        replacement='    if False:',
        guard='test_an_unknown_layer_names_the_ones_that_exist',
    ),
    # The vocabulary is spelled in two languages that cannot import each other, so the only thing
    # holding them together is the parity test — and a list nobody can mutate proves nothing.
    Sabotage(
        suite='python',
        label='a layer the acquirer fetches drops out of the Python vocabulary',
        path='pipeline/naturalearth.py',
        needle='    "ne_10m_rivers_lake_centerlines",',
        replacement='',
        guard='test_every_downloaded_layer_is_addressable',
    ),
    # The three modules around `work/borders` are a write-write-read chain. A literal in any one of
    # them resolves identically today, so nothing behavioural can see it — only the scan can.
    Sabotage(
        suite='python',
        label='the borders reader spells its own path again, and the chain can now drift',
        path='pipeline/compose/countries_pmtiles.py',
        needle='BORDERS = bodies.work_dir(bodies.EARTH, "borders")',
        replacement='BORDERS = paths.DATA / "work/borders"',
        guard='test_the_borders_work_dir_is_spelled_once',
    ),
    # A reader re-deriving the shapefile longhand: the exact shape that reached five call sites.
    Sabotage(
        suite='python',
        label='a reader hand-writes the layer path again instead of asking for it',
        path='pipeline/tile/cap_render.py',
        needle='COAST_SHP = naturalearth.layer("ne_10m_coastline")',
        replacement='COAST_SHP = naturalearth.DIR / "ne_10m_coastline/ne_10m_coastline.shp"',
        guard='test_the_layer_name_is_never_doubled_by_hand',
    ),
    # --- the hero pipeline's own paths ------------------------------------------------------
    # The shape here is the one no scan can see: a RELATIVE data path in a command string, resolved
    # against whatever directory the runner happens to be in. There is no join operator to match and
    # no import-time value to read — only running it tells you where it went.
    Sabotage(
        suite='python',
        label='the stage list goes back to relative work paths, resolved against the runner\'s cwd',
        path='pipeline/frame/country_config.py',
        needle='    work = country_work_dir(resolved["slug"])',
        replacement='    work = f"data/work/{resolved[\'slug\']}"',
        guard='test_every_work_path_is_absolute_and_in_the_store',
    ),
    # The half that made this dangerous rather than merely wrong: the fusion stage READ through the
    # store and WROTE beside the source tree, in one command, with no error either way.
    Sabotage(
        suite='python',
        label='the render dir drifts from the work dir the fusion was told to fill',
        path='pipeline/frame/country_config.py',
        needle='    return country_work_dir(slug) / "render"',
        replacement='    return paths.ROOT / "data/work" / slug / "render"',
        guard='test_it_follows_a_relocated_store',
    ),
    # A pin written into a tree the render never reads. Both sides exist, both look right, and the
    # frame the hero is built from is simply the older one.
    Sabotage(
        suite='python',
        label='the emitted pin lands in a different tree from the render dir',
        path='pipeline/frame/country_config.py',
        needle='    dest = country_render_dir(slug) / "frame.json"',
        replacement='    dest = ROOT / "data/work" / slug / "render" / "frame.json"',
        guard='test_no_data_path_is_built_by_joining_onto_a_checkout_root',
    ),
    # The reclaim path. Pointed at the checkout with the store elsewhere, `--clean` deletes nothing
    # and reports success, which is how a near-global sweep runs the disk out.
    Sabotage(
        suite='python',
        label='the pruner reclaims a country from the checkout instead of the store',
        path='pipeline/batch.py',
        needle='    work = country_work_dir(slug)',
        replacement='    work = ROOT / f"data/work/{slug}"',
        guard='test_no_data_path_is_built_by_joining_onto_a_checkout_root',
    ),
    # The scan's own reach, asserted where it is cheapest to break: shell is a separate pattern from
    # the Python one, so a case that only ever mutates .py leaves half the guard unproven.
    Sabotage(
        suite='python',
        label='a shell acquirer joins the checkout root straight into data/',
        path='pipeline/acquire/download_naturalearth.sh',
        needle='DEST="$DATA/raw/naturalearth"',
        replacement='DEST="$(cd "$(dirname "$0")/../.." && pwd)/data/raw/naturalearth"',
        guard='test_no_data_path_is_built_by_joining_onto_a_checkout_root',
    ),
    # --- the globe's atmosphere becomes the body's -------------------------------------------------
    # Every case here is a way the change reverts to "one sky for every planet" while the site still
    # builds, renders and passes a type-check. That is the whole failure mode: it is only visible on
    # the body nobody has loaded.
    Sabotage(
        suite='web',
        label='Mars inherits an atmosphere instead of declaring none',
        path='web/src/lib/bodies.ts',
        needle='    atmosphere: null,\n    // Matches',
        replacement='    atmosphere: { sky: "#8fb8d6", horizon: "#cbd8dd", fog: "#dfe7ea" },\n    // Matches',
        guard='is a state the registry actually holds, in both arms',
    ),
    Sabotage(
        suite='web',
        label='the moveend rebuild drops its no-atmosphere gate',
        path='web/src/components/Globe.astro',
        needle='  map.on("moveend", () => {\n    if (bodyAtmosphere === null) return;\n',
        replacement='  map.on("moveend", () => {\n',
        guard='skips the sky entirely for a body that declares none, at every call site',
    ),
    Sabotage(
        suite='web',
        label='style.load sets a sky for a body that declares none',
        path='web/src/components/Globe.astro',
        needle='    if (bodyAtmosphere === null) return;\n    skyPitch = map.getPitch();',
        replacement='    skyPitch = map.getPitch();',
        guard='skips the sky entirely for a body that declares none, at every call site',
    ),
    # The regrowth shape, and the one the type checker cannot see: a module that never calls skySpec
    # and simply states a hex of its own. Planted in a module with no business holding one.
    Sabotage(
        suite='web',
        label='a third module grows its own copy of the sky colour',
        path='web/src/lib/reliefSources.ts',
        needle='import { archiveFor',
        replacement='const SKY_COLOR = "#8fb8d6";\nimport { archiveFor',
        guard="finds none of the body's atmosphere colours outside the registry",
    ),
    # The sweep's own reach. Narrowing it to the page repairs the instance and keeps the shape —
    # which is exactly how the pipeline's ramp globals stayed reachable from two modules for months.
    Sabotage(
        suite='web',
        label='the sky sweep stops recursing, so its subject silently empties',
        path='web/src/lib/skyAtmosphere.test.ts',
        needle='  const swept = readdirSync(SOURCE_ROOT, { recursive: true })',
        replacement='  const swept = readdirSync(SOURCE_ROOT)',
        guard='sweeps the files that could plausibly hold one, so the rule is not vacuous',
    ),
    Sabotage(
        suite='web',
        label='the read-out reports a ramp for a body that has no air',
        path='web/src/lib/skyAtmosphere.ts',
        needle='  if (atmosphere === null) return "sky none · this body declares no atmosphere";\n',
        replacement='',
        guard='says so in the read-out rather than going quiet',
    ),
    # --- the pass's memory cap becomes the body's --------------------------------------------------
    # Every case here restores "one cap for every planet" while the harness still starts, still caps,
    # and still prints a preflight line. The damage is asymmetric and that is why they are worth
    # having: too HIGH refuses a pass the box could have run, which is loud but wastes an afternoon
    # of look iteration; too LOW OOM-kills hours in, after every finished stage has been paid for.
    Sabotage(
        suite='python',
        label='the shell resolves the cap and then ignores it for a constant',
        path='pipeline/profile/run_pass.sh',
        needle='MEMORY_CAP=${MEMORY_CAP_GIB}G',
        replacement='MEMORY_CAP=16G',
        guard='test_the_cgroup_argument_carries_the_bodys_cap_not_a_constant',
    ),
    Sabotage(
        suite='python',
        label='the resolver stops reading the body and answers Earth for every planet',
        path='pipeline/profile/pass_cap.py',
        needle='    return CAP_RENDERING_GIB if body.renders_polar_caps else STANDING_GIB',
        replacement='    return CAP_RENDERING_GIB',
        guard='test_a_capless_body_gets_the_standing_cap',
    ),
    # The tidiest-looking of the four: two constants that agree are one constant, and collapsing them
    # leaves a resolver that still branches, still reads the body, and still answers.
    Sabotage(
        suite='python',
        label='the standing cap creeps up to match Earth so the split is a no-op',
        path='pipeline/profile/pass_cap.py',
        needle='STANDING_GIB = 12',
        replacement='STANDING_GIB = 16',
        guard='test_the_two_numbers_actually_differ',
    ),
    # `set -u` does NOT catch this: a failed command substitution assigns the EMPTY STRING rather
    # than leaving the name unset, so the cap becomes `G`, the arithmetic compares against zero, and
    # a run with no body sails through the preflight into a cgroup scope.
    Sabotage(
        suite='python',
        label="the resolver's refusal goes unchecked, so a bad argv reaches the scope",
        path='pipeline/profile/run_pass.sh',
        needle='pipeline.profile.pass_cap "$@") || exit 1',
        replacement='pipeline.profile.pass_cap "$@")',
        guard='test_an_omitted_body_is_refused_before_the_scope_opens',
    ),
]


def run_suite(name: str, in_flight: str | None = None) -> tuple[bool, str]:
    """Run one suite. Returns (green, combined output)."""
    suite = SUITES[name]
    environment = {**os.environ, **suite.environment}
    if in_flight is not None:
        environment[IN_FLIGHT_ENV] = in_flight
    result = subprocess.run(
        suite.command,
        cwd=REPO_ROOT / suite.cwd,
        capture_output=True,
        text=True,
        timeout=900,
        env=environment,
        check=False,  # a RED suite is the expected outcome here — raising would invert the harness
    )
    return result.returncode == 0, result.stdout + result.stderr


def failing_tests(name: str, output: str) -> list[str]:
    """The tests the suite reported as failing, in the order printed."""
    seen: list[str] = []
    for line in output.splitlines():
        match = SUITES[name].fail_pattern.match(line)
        if match is None:
            continue
        reported = match.group(1).split(" > ")[-1].strip()
        if reported and reported not in seen:
            seen.append(reported)
    return seen


def leftover_backups(
    roots: Sequence[str] = MUTABLE_ROOTS, base: Path | None = None
) -> list[Path]:
    """Backups a killed run left behind — the working tree is still sabotaged.

    A MUTABLE ROOT MAY BE A SINGLE FILE, and `rglob` on a file matches nothing at all. Four of the
    roots are files, so for years this reported "the tree is clean" over a tree that was not: a run
    killed mid-case on `pipeline/bodies.py` left the mutation in place, `--restore` said there was
    nothing to restore, and the next run refused to start because the baseline it found was red —
    the one outcome that made it visible, and only by luck. The failure it risks is the one this
    project has already had once: a commit taken over a mutated file.

    Measured before fixing: 4 file roots, 0 of them reachable by the old glob.

    `roots` and `base` are arguments so a test can hand it a tree that is not this one. Reading them
    off the module would make the file-root case untestable without planting a backup in the real
    repo — which every other check here would then fire on, so the guard for this would have to be
    disarmed to run at all.
    """
    base = REPO_ROOT if base is None else base
    found: list[Path] = []
    for root in roots:
        path = base / root
        if path.is_dir():
            found.extend(path.rglob(f"*{BACKUP_SUFFIX}"))
        else:
            beside = path.with_name(path.name + BACKUP_SUFFIX)
            if beside.exists():
                found.append(beside)
    return sorted(found)


def restore_backups(backups: list[Path]) -> None:
    for backup in backups:
        target = backup.with_suffix("")
        shutil.move(str(backup), str(target))
        target.touch()
        print(f"restored {target.relative_to(REPO_ROOT)}")


def selected(pattern: str | None, suite: str | None) -> list[Sabotage]:
    cases = SABOTAGES if suite is None else [case for case in SABOTAGES if case.suite == suite]
    if pattern is None:
        return cases
    needle = pattern.lower()
    return [case for case in cases if needle in case.label.lower() or needle in case.path.lower()]


def run_case(case: Sabotage) -> tuple[bool, str]:
    """Apply one sabotage, run its suite, restore. Returns (green, output)."""
    target = REPO_ROOT / case.path
    if not case.needle:
        target.write_text(case.replacement, encoding="utf-8")
        try:
            return run_suite(case.suite, in_flight=case.path)
        finally:
            target.unlink()

    backup = target.with_suffix(target.suffix + BACKUP_SUFFIX)
    source = target.read_text(encoding="utf-8")
    shutil.copy2(target, backup)
    try:
        target.write_text(source.replace(case.needle, case.replacement, 1), encoding="utf-8")
        target.touch()  # mtime, or a running Vite serves the sabotaged module after restore
        return run_suite(case.suite, in_flight=case.path)
    finally:
        shutil.move(str(backup), str(target))
        target.touch()


def stale_reason(case: Sabotage) -> str | None:
    """Why this case can no longer be applied, or None when it can."""
    target = REPO_ROOT / case.path
    if not case.needle:
        return f"{case.path} already exists; a creation case needs it absent" if target.exists() else None
    if not target.is_file():
        return f"{case.path} does not exist"
    if case.needle not in target.read_text(encoding="utf-8"):
        return f"needle absent from {case.path}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--filter", help="only cases whose label or path contains this substring")
    parser.add_argument("--suite", choices=sorted(SUITES), help="only cases for this suite")
    parser.add_argument("--list", action="store_true", help="print the table and exit")
    parser.add_argument("--restore", action="store_true", help="undo leftover backups and exit")
    parser.add_argument(
        "--harvest",
        action="store_true",
        help="report which tests catch each case instead of judging it — for assigning `guard`",
    )
    arguments = parser.parse_args()

    if arguments.restore:
        backups = leftover_backups()
        if not backups:
            print("no leftover backups — the tree is clean")
            return 0
        restore_backups(backups)
        return 0

    cases = selected(arguments.filter, arguments.suite)
    if not cases:
        print(f"no case matches filter={arguments.filter!r} suite={arguments.suite!r}")
        return 2

    if arguments.list:
        for case in cases:
            print(f"[{case.suite}] {case.path}\n    {case.label}\n    -> {case.guard}")
        print(f"\n{len(cases)} case(s)")
        return 0

    backups = leftover_backups()
    if backups:
        print("REFUSING TO RUN — a previous run left the tree sabotaged:")
        for backup in backups:
            print(f"  {backup.relative_to(REPO_ROOT)}")
        print("Run with --restore first.")
        return 2

    suites = sorted({case.suite for case in cases})
    print(f"{len(cases)} case(s) across {', '.join(suites)}; each edits a file and restores it.")
    print("If this is killed mid-run, `uv run scripts/sabotage.py --restore` puts the tree back.\n")

    for name in suites:
        print(f"baseline ({name}): must be GREEN before any result means anything")
        green, output = run_suite(name)
        if not green:
            print(f"REFUSING TO RUN — the {name} baseline is already red; every case would report caught:")
            print(output[-2500:])
            return 2
    print("baselines green\n")

    caught: list[Sabotage] = []
    problems: list[tuple[str, str]] = []

    for case in cases:
        stale = stale_reason(case)
        if stale is not None:
            print(f"STALE   {case.label}\n        {stale}")
            problems.append((case.label, stale))
            continue

        green, output = run_case(case)

        if arguments.harvest:
            print(f"HARVEST {case.label}")
            for reported in failing_tests(case.suite, output) or ["(nothing failed)"]:
                print(f"        {reported}")
            continue

        if green:
            print(f"MISSED  {case.label}\n        nothing failed; expected: {case.guard}")
            problems.append((case.label, f"not caught; expected {case.guard}"))
        elif case.guard in output:
            print(f"CAUGHT  {case.label}")
            caught.append(case)
        else:
            actual = ", ".join(failing_tests(case.suite, output)) or "(unparsed)"
            print(f"WRONG   {case.label}\n        expected: {case.guard}\n        got: {actual}")
            problems.append((case.label, f"caught by {actual}, not by {case.guard}"))

    if arguments.harvest:
        print("\nharvest only — nothing judged")
        return 0

    print(f"\n{len(caught)}/{len(cases)} caught by the named guard")
    for label, why in problems:
        print(f"  - {label}: {why}")

    restored = True
    for name in suites:
        green, _ = run_suite(name)
        print(f"restored baseline ({name}): " + ("green" if green else "RED — restore failed"))
        restored = restored and green
    return 0 if not problems and restored else 1


if __name__ == "__main__":
    sys.exit(main())
