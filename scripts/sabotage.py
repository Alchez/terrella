#!/usr/bin/env python3
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

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
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
        needle=' *  suggests, which is worth knowing before anyone cuts a z9 that could never load. */',
        replacement=' *  suggests, which is worth knowing before anyone cuts a z9 that could never load.',
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
        path='web/src/pages/earth.astro',
        needle='      map.setTerrain({ source: TERRAIN_SOURCE, exaggeration: exaggerationFor(map.getZoom()) });\n      applyCacheCap();',
        replacement='      applyCacheCap();\n      map.setTerrain({ source: TERRAIN_SOURCE, exaggeration: exaggerationFor(map.getZoom()) });',
        guard='caps the DEM cache AFTER setTerrain, which is what builds the manager it lands on',
    ),
    Sabotage(
        suite='web',
        label='recovery watch no longer re-adds the polar caps',
        path='web/src/pages/earth.astro',
        needle='        reassertPolarCaps();\n',
        replacement='',
        guard='puts back what a restore silently drops, once the map reads healthy',
    ),
    Sabotage(
        suite='web',
        label='recovery watch no longer re-asserts the DEM bound',
        path='web/src/pages/earth.astro',
        needle='        reassertTerrainBound();\n',
        replacement='',
        guard='puts back what a restore silently drops, once the map reads healthy',
    ),
    Sabotage(
        suite='web',
        label='loss handler stops starting the watch (back to event-driven recovery)',
        path='web/src/pages/earth.astro',
        needle='    startRecoveryWatch(performance.now() + GL_RESTORE_GRACE_MS);',
        replacement='',
        guard='starts the recovery watch from the LOSS, because the restore event may never fire',
    ),
    Sabotage(
        suite='web',
        label='loss handler stops charging the recurrence budget',
        path='web/src/pages/earth.astro',
        needle='    if (recoveryVerdict(chargedLosses) === "give-up") {',
        replacement='    if (false) {',
        guard='bounds recovery by recurrence rather than trying to read a cause that does not exist',
    ),
    Sabotage(
        suite='web',
        label='cap re-assertion reports without repairing',
        path='web/src/pages/earth.astro',
        needle='        applyCacheCap();\n        console.info(`[terrain] DEM cache cap was not in force',
        replacement='        console.info(`[terrain] DEM cache cap was not in force',
        guard='REPAIRS a dropped cap before reporting it, and lets the next idle be the judge',
    ),
    Sabotage(
        suite='web',
        label='cap re-assertion verifies its own write synchronously (the stale-oracle bug)',
        path='web/src/pages/earth.astro',
        needle='        applyCacheCap();\n        console.info(',
        replacement='        applyCacheCap();\n        demCacheCapFault(map.style?.tileManagers?.[TERRAIN_SOURCE], intendedCacheSlots);\n        console.info(',
        guard='REPAIRS a dropped cap before reporting it, and lets the next idle be the judge',
    ),
    Sabotage(
        suite='web',
        label='polar cap re-add stops clearing the dead layers first',
        path='web/src/pages/earth.astro',
        needle='        if (map.getLayer(layerId)) map.removeLayer(layerId);',
        replacement='        void layerId;',
        guard='re-adds the caps on recovery, from OUTSIDE style.load, because that ordering is too early',
    ),
    Sabotage(
        suite='web',
        label='restore handler touches the notice again (the original bug)',
        path='web/src/pages/earth.astro',
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
        label='base source uncapped — maxzoom follows relief, losing the one-tile guarantee',
        path='web/src/pages/earth.astro',
        needle='    maxzoom: RELIEF_BASE_MAX_ZOOM,',
        replacement='    maxzoom: RELIEF_MAX_ZOOM,',
        guard='caps the base source at z0, because that is what makes it unmissable',
    ),
    Sabotage(
        suite='web',
        label='the constant itself drifts off 0',
        path='web/src/lib/reliefTiles.ts',
        needle='export const RELIEF_BASE_MAX_ZOOM = 0;',
        replacement='export const RELIEF_BASE_MAX_ZOOM = 1;',
        guard='caps the base source at z0, because that is what makes it unmissable',
    ),
    Sabotage(
        suite='web',
        label='base layer drawn OVER relief, hiding the real tiles',
        path='web/src/pages/earth.astro',
        needle='        { id: "relief", type: "raster", source: "relief", paint: { "raster-fade-duration": 0 } },\n      ],',
        replacement='      ],',
        guard='draws the base UNDER relief and OVER the background, or it is pointless',
    ),
    Sabotage(
        suite='web',
        label='base source registered but never added to the style',
        path='web/src/pages/earth.astro',
        needle='sources: { relief: reliefSource, "relief-base": reliefBaseSource },',
        replacement='sources: { relief: reliefSource },',
        guard='draws the base UNDER relief and OVER the background, or it is pointless',
    ),
    Sabotage(
        suite='web',
        label='base source grows a second attribution, doubling the credit',
        path='web/src/pages/earth.astro',
        needle='    maxzoom: RELIEF_BASE_MAX_ZOOM,\n    tileSize: 256,\n  };',
        replacement='    maxzoom: RELIEF_BASE_MAX_ZOOM,\n    tileSize: 256,\n    attribution: CREDITS,\n  };',
        guard='caps the base source at z0, because that is what makes it unmissable',
    ),
    # --- the terrain-retirement flag (2026-07-29) ----------------------------------------------------
    Sabotage(
        suite='web',
        label='re-assertion stops honouring the retirement flag',
        path='web/src/pages/earth.astro',
        needle='    reassertTerrainBound = () => {\n      if (terrainRetired) return;',
        replacement='    reassertTerrainBound = () => {\n      if (false) return;',
        guard='goes quiet when the FPS ladder retires terrain, instead of crying wolf about the cap',
    ),
    Sabotage(
        suite='web',
        label='applyCacheCap stops honouring the retirement flag',
        path='web/src/pages/earth.astro',
        needle='    const applyCacheCap = () => {\n      if (terrainRetired) return;',
        replacement='    const applyCacheCap = () => {\n      if (false) return;',
        guard='goes quiet when the FPS ladder retires terrain, instead of crying wolf about the cap',
    ),
    Sabotage(
        suite='web',
        label='flag raised AFTER the teardown, so an idle inside it still false-alarms',
        path='web/src/pages/earth.astro',
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
        path='web/src/pages/earth.astro',
        needle='          pixelRatioLowered,\n          devicePixelRatio: map.getPixelRatio(),',
        replacement='          pixelRatioLowered,\n          devicePixelRatio: window.devicePixelRatio || 1,',
        guard="feeds the ladder the MAP's ratio, never the display's",
    ),
    Sabotage(
        suite='web',
        label='the dead-globe notice sinks back under the perf panel',
        path='web/src/pages/earth.astro',
        needle='    z-index: 50;',
        replacement='    z-index: 20;',
        guard='keeps the dead-globe notice above the ?perf panel',
    ),
    Sabotage(
        suite='web',
        label="the perf report reads the DISPLAY ratio instead of the map's",
        path='web/src/pages/earth.astro',
        needle='              devicePixelRatio: map.getPixelRatio(),',
        replacement='              devicePixelRatio: window.devicePixelRatio || 1,',
        guard="reports the MAP's ratio in the perf snapshot too, not the display's",
    ),
    Sabotage(
        suite='web',
        label='the report probes capabilities per tick again — 13.3 WebGL contexts/second',
        path='web/src/pages/earth.astro',
        needle='            signals: probedSignals,',
        replacement='            signals: probeSignals(),',
        guard="is never called from the ?perf overlay's per-tick path",
    ),
    Sabotage(
        suite='web',
        label='the tier is cached, so a mid-session quality change goes unreported',
        path='web/src/pages/earth.astro',
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
        path='web/src/pages/earth.astro',
        needle='import maplibreStylesheet from "maplibre-gl/dist/maplibre-gl.css?url";',
        replacement='import "maplibre-gl/dist/maplibre-gl.css";\nconst maplibreStylesheet = "";',
        guard='imports it for its URL, never for its side effect',
    ),
    Sabotage(
        suite='web',
        # The scripts-off hole. `onload` is an inline handler, so without the noscript twin a
        # visitor with JS disabled keeps media="print" forever and the controls render unstyled.
        label='the deferred stylesheet loses its noscript fallback',
        path='web/src/pages/earth.astro',
        needle='  <noscript slot="head">',
        replacement='  <template slot="head">',
        guard='links it non-blocking, with the noscript twin that makes that safe',
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
        path='web/src/pages/earth.astro',
        needle='                  ...demCache().map((text) => ({ group: "ram" as const, text })),',
        replacement='',
        guard='surfaces the line through the perf overlay, so it is visible in Zen without devtools',
    ),
    # --- the four instrument fixes and the lazy boundary (2026-07-30) --------------------------------
    Sabotage(
        suite='web',
        label='helper stops rejecting an empty read',
        path='web/src/pages/earth.astro',
        needle='return snapshotHasContent(snapshot) ? snapshot : null;',
        replacement='return snapshot;',
        guard='rejects an empty read at the single place a routine sample is taken',
    ),
    Sabotage(
        suite='web',
        label='an empty idle read erases the healthy sample',
        path='web/src/pages/earth.astro',
        needle='lastHealthyGlState = sampledGlState() ?? lastHealthyGlState;',
        replacement='lastHealthyGlState = sampledGlState();',
        guard='never overwrites the healthy sample with an empty read',
    ),
    Sabotage(
        suite='web',
        label='export stops taking a fresh sample',
        path='web/src/pages/earth.astro',
        needle='{ sampleGlNow: true }',
        replacement='{ sampleGlNow: false }',
        guard='takes a FRESH sample on export and the stale one on the panel tick',
    ),
    Sabotage(
        suite='web',
        label='the 300 ms panel tick opts into per-tick sampling',
        path='web/src/pages/earth.astro',
        needle='perfReportLines(composeReport(timing, { expanded: true }))',
        replacement='perfReportLines(composeReport(timing, { expanded: true }, { sampleGlNow: true }))',
        guard='takes a FRESH sample on export and the stale one on the panel tick',
    ),
    Sabotage(
        suite='web',
        label='the fresh/stale switch is bypassed entirely',
        path='web/src/pages/earth.astro',
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
        path='web/src/pages/earth.astro',
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
        label='the terrain split matches the prefix anywhere in the path',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='path.startsWith(`${TERRAIN_PATH_PREFIX}/`)',
        replacement='path.includes(TERRAIN_PATH_PREFIX)',
        guard='does not mistake a relief tile at zoom level named like the prefix',
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
        path='web/src/pages/earth.astro',
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
        path='web/src/pages/earth.astro',
        needle='  import type { CameraFill } from "../lib/perf/perfNetwork";',
        replacement='  import { newCameraFill } from "../lib/perf/perfNetwork";',
        guard='is never statically VALUE-imported by a page',
    ),
    Sabotage(
        suite='web',
        label='an instrument module stops loading dynamically',
        path='web/src/pages/earth.astro',
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
        label='an instrument module re-exports the exempt raiser, dragging the chunk back',
        path='web/src/lib/perf/perfNetwork.ts',
        needle='export function wireBytes(',
        replacement='export { raiseResourceTimingBuffer } from "../resourceTimingBuffer";\nexport function wireBytes(',
        guard='does not re-export the always-shipped buffer raiser back into this directory',
    ),
    Sabotage(
        suite='web',
        label='the buffer raise moves AFTER the map, so early entries are lost in silence',
        path='web/src/pages/earth.astro',
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
        path='web/src/pages/earth.astro',
        needle=(
            '      addCountryHighlight(); // hover outline on top of everything, so the edge stays crisp\n'
        ),
        replacement=(
            '      addCountryHitTargets();\n'
            '      addCountryHighlight(); // hover outline on top of everything, so the edge stays crisp\n'
        ),
        guard='matches what earth.astro actually adds last',
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
    Sabotage(
        suite='web',
        label='the version-prefix regex loses its ^ anchor and strips a mid-path /vN/',
        path='web/worker/index.ts',
        needle='.replace(/^\\/v\\d+\\//, "/")',
        replacement='.replace(/\\/v\\d+\\//, "/")',
        guard='strips only the LEADING segment, not one buried mid-path',
    ),
    Sabotage(
        suite='web',
        label='the version-prefix regex widens to \\w and swallows /v3x/',
        path='web/worker/index.ts',
        needle='.replace(/^\\/v\\d+\\//, "/")',
        replacement='.replace(/^\\/v\\w+\\//, "/")',
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
        path='web/src/pages/earth.astro',
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
        path='web/src/pages/earth.astro',
        needle='    return locate.call(transform, new maplibregl.Point(x, y));',
        replacement='    return map.unproject([x, y]);',
        guard='measures through the transform, not through map.unproject',
    ),
    Sabotage(
        suite='web',
        label='terrain is handed to screenPointToLocation, which is the expensive overload',
        path='web/src/pages/earth.astro',
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
        path='web/src/pages/earth.astro',
        needle='  function updateRuler(): void {',
        replacement='  function refreshRulerReading(): void {',
        guard='keeps the per-frame path free of any unproject at all',
    ),
    Sabotage(
        suite='web',
        label='the locator function is renamed, the other half of the same vacuity risk',
        path='web/src/pages/earth.astro',
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
        path='web/src/pages/earth.astro',
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
        needle='  borders={true}',
        replacement='  borders={true}\n  spotlight={true}',
        guard='fits on one row at 320px on the globe',
    ),
    # The label direction: nothing about the markup changes shape, one word just gets longer. This is
    # the mutation a reviewer waves through.
    Sabotage(
        suite='web',
        label='a button label grows by a word, which no diff makes look like a layout change',
        path='web/src/layouts/Base.astro',
        needle='              Borders',
        replacement='              Country borders',
        guard='fits on one row at 320px on the globe',
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
        guard='fits on one row at 320px on the globe',
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
        needle='    mercator_radius_m=6378137.0,',
        replacement='    mercator_radius_m=6371000.0,',
        guard='test_earth_carries_web_mercator_s_defining_sphere',
    ),
    # The plausible edit: 6371000 IS a real earth radius, just not the projection's one. Nothing
    # crashes; the per-row z-factor is quietly wrong at every latitude. It used to be catchable only
    # as drift between two copies; now there is one home, so the guard pins the value itself.
    Sabotage(
        suite='python',
        label='a shading module regrows its own sphere radius beside the shared one',
        path='pipeline/render/snow.py',
        needle='    return mercator.latitude_at(merc_y, bodies.EARTH.mercator_radius_m)',
        replacement='    return mercator.latitude_at(merc_y, 6378137.0)',
        guard='test_the_render_package_no_longer_carries_its_own_earth_radius',
    ),
    # Identical output today, which is exactly why nothing else would notice: the module has quietly
    # stopped asking the body and gone back to knowing the answer.
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
        label='a Body field gains a default, so a new planet inherits Earth without being asked',
        path='pipeline/bodies.py',
        # THE LAST FIELD, deliberately. Defaulting any earlier one is followed by a field without a
        # default, so Python refuses the class at import and the module never loads — which reads as
        # "caught" while leaving the guard itself unexercised. Only a mutation the interpreter
        # accepts can prove the test does the work.
        needle='    path_prefix: str\n',
        replacement='    path_prefix: str = ""\n',
        guard='test_no_field_carries_a_default_so_a_new_one_must_be_decided_per_body',
    ),
    # --- The look seam ------------------------------------------------------------------------------
    # The ramps' kind-dispatch used to be transcribed in four functions; it is now one resolver over a
    # frozen Look. That is a refactor whose contract is "nothing changes", so its guard is a byte
    # hash rather than a property — every mutation below leaves ramps that are still monotonic, still
    # hit their stops, and still agree with gdaldem within 1 DN, which is all the property tests ask.
    Sabotage(
        suite='python',
        label='the look resolver swaps land and sea, repainting the whole planet inside out',
        path='pipeline/render/palette.py',
        needle='    if kind == "land":\n        return look.land\n    if kind == "sea":\n        return look.sea',
        replacement='    if kind == "land":\n        return look.sea\n    if kind == "sea":\n        return look.land',
        guard='test_gdaldem_ramp_text_is_unchanged',
    ),
    # The sea ramp's LUT starts at the abyss, not at 0 m. Dropping the offset leaves a table that is
    # the right length, the right dtype and the right shape, and wrong at every index.
    Sabotage(
        suite='python',
        label='the sea LUT loses its abyss offset, so every depth reads the wrong colour',
        path='pipeline/render/palette.py',
        needle='    base = min(0.0, ramp.extreme_m)\n    colors = ',
        replacement='    base = 0.0\n    colors = ',
        guard='test_relief_lut_bytes_are_unchanged',
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
        needle='    aeqd_radius_m=6371000.0,',
        replacement='    aeqd_radius_m=6378137.0,',
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
        path='pipeline/tile/cap_render.py',
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
        needle='<html lang="en" class="no-js" data-body={body}>',
        replacement='<html lang="en" class="no-js">',
        guard='renders data-body on <html>, server-side and unconditionally',
    ),
    # The attribute goes on the wrong element. `:root` IS <html>, so this compiles, renders, and
    # silently matches nothing — a mistake no type can catch, since both spellings are valid Astro.
    Sabotage(
        suite='web',
        label='data-body lands on <body>, where the token block cannot see it',
        path='web/src/layouts/Base.astro',
        needle='<html lang="en" class="no-js" data-body={body}>',
        replacement='<html lang="en" class="no-js">\n  <body data-body={body}>',
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
    # --- The route is the body's slug ------------------------------------------------------------
    # `/earth/` is a body route now, not a page name that happens to be there. The guard that admits
    # a capable visitor cannot import the registry (it runs before the bundle), so the route is
    # spelled in both places and only a test can hold them together.
    Sabotage(
        suite='web',
        label='the pre-paint guard sends capable visitors to a route that no longer exists',
        path='web/src/layouts/Base.astro',
        needle='          location.replace("/earth/");',
        replacement='          location.replace("/globe/");',
        guard='steers a capable first-time visitor from the gallery to the globe',
    ),
    # The other half of the same guard: it stops recognising that it is already on a globe route, so
    # a visitor who lands there is bounced or re-steered rather than left alone.
    Sabotage(
        suite='web',
        label='the guard stops recognising the globe route it is standing on',
        path='web/src/layouts/Base.astro',
        needle='          var atGlobe = path === "/earth" || path === "/earth/";',
        replacement='          var atGlobe = path === "/globe" || path === "/globe/";',
        guard='marks the session steered when the globe is reached by deep link',
    ),
    # --- The globe's two stylesheets -------------------------------------------------------------
    # The global rules are a file so a second body's page can import the same one; the SCOPED block
    # cannot follow, because Astro stamps it with `[data-astro-cid-…]` and that attribute is worth a
    # class of specificity. Both mutations below leave every rule intact and change only where it
    # lives, which is the entire failure mode: no error, no missing declaration, just a level lost.
    Sabotage(
        suite='web',
        label='the page stops importing its global stylesheet, shipping the widgets unstyled',
        path='web/src/pages/earth.astro',
        needle='import "../styles/globe.css";\n',
        replacement='',
        guard='imports the global stylesheet, or the page ships with none of it',
    ),
    # The scoped block is re-declared global, which strips the cid from every rule in it.
    Sabotage(
        suite='web',
        label='the scoped block goes global, dropping a specificity level off every page rule',
        path='web/src/pages/earth.astro',
        needle='\n<style>\n',
        replacement='\n<style is:global>\n',
        guard='keeps the SCOPED block in the page, where Astro can stamp it',
    ),
    # A scoped rule migrates into the shared file, where it compiles without its cid.
    Sabotage(
        suite='web',
        label='a page-scoped rule is moved into the shared stylesheet and loses its cid',
        path='web/src/styles/globe.css',
        needle='.chrome-credit.chrome-credit.maplibregl-ctrl.maplibregl-ctrl {',
        replacement='.starfield {\n  z-index: 0;\n}\n.chrome-credit.chrome-credit.maplibregl-ctrl.maplibregl-ctrl {',
        guard="keeps the page's own elements out of the shared stylesheet",
    ),
    # --- The globe's floor is a body fact --------------------------------------------------------
    # `space-floor` exists so a gap in the tiles reads as more of this planet rather than as a hole
    # to space. Every mutation below leaves a globe that renders perfectly for Earth and is wrong in
    # a way that looks like slow loading for anything else.
    Sabotage(
        suite='web',
        label='the space-floor goes back to a fixed colour, so every body gets Earth\'s ocean',
        path='web/src/pages/earth.astro',
        needle='paint: { "background-color": body.spaceFloor }',
        replacement='paint: { "background-color": "#47808F" }',
        guard='paints the background layer from the descriptor',
    ),
    # The runtime lookup stops being strict. A page whose layout forgot to declare its body then
    # draws Earth's sea under its missing tiles and reports nothing.
    Sabotage(
        suite='web',
        label='the page falls back to Earth when no body is declared instead of failing',
        path='web/src/lib/bodies.ts',
        needle='  if (slug === undefined) {\n    throw new Error(\n      "<html> carries no data-body: the page\'s layout must declare which body it draws",\n    );\n  }',
        replacement='  if (slug === undefined) {\n    return BODIES.earth;\n  }',
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
        needle='    MOBILE_EXEMPT_LADDERS = {\n        "border": (',
        replacement='    MOBILE_EXEMPT_LADDERS = {\n        "hero": ("no reason at all"),\n        "border": (',
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


def leftover_backups() -> list[Path]:
    """Backups a killed run left behind — the working tree is still sabotaged."""
    found: list[Path] = []
    for root in MUTABLE_ROOTS:
        found.extend((REPO_ROOT / root).rglob(f"*{BACKUP_SUFFIX}"))
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
