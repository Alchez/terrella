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

Two suites, because the guards live in two languages. `suite='web'` runs `pnpm test`; `suite='python'`
runs `pytest`, and those cases exist to check `tests/test_sabotage_cases.py`, the table's own
freshness gate. That gate is a guard like any other and gets the same treatment.

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
    uv run scripts/sabotage.py                  # all cases (~5 min: 71 web at ~2 s, 10 python at ~11 s)
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
MUTABLE_ROOTS = ("web/src", "web/worker", "scripts", "PROCESS.md")

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
    fail_pattern: re.Pattern[str]


SUITES: dict[str, Suite] = {
    "web": Suite(
        command=["pnpm", "run", "test"],
        cwd="web",
        environment={},
        fail_pattern=re.compile(r"^\s*FAIL\s+\S+\s+>\s+(.+)$"),
    ),
    "python": Suite(
        command=["uv", "run", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=".",
        environment={"PYTHONDONTWRITEBYTECODE": "1"},
        fail_pattern=re.compile(r"^FAILED\s+\S+::([^\s\[]+)"),
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
    # --- GL context-loss recovery and the DEM cache cap (2026-07-29) ---------------------------------
    Sabotage(
        suite='web',
        label='cap ordering: put applyCacheCap back BEFORE setTerrain',
        path='web/src/pages/globe.astro',
        needle='      map.setTerrain({ source: TERRAIN_SOURCE, exaggeration: exaggerationFor(map.getZoom()) });\n      applyCacheCap();',
        replacement='      applyCacheCap();\n      map.setTerrain({ source: TERRAIN_SOURCE, exaggeration: exaggerationFor(map.getZoom()) });',
        guard='caps the DEM cache AFTER setTerrain, which is what builds the manager it lands on',
    ),
    Sabotage(
        suite='web',
        label='recovery watch no longer re-adds the polar caps',
        path='web/src/pages/globe.astro',
        needle='        reassertPolarCaps();\n',
        replacement='',
        guard='puts back what a restore silently drops, once the map reads healthy',
    ),
    Sabotage(
        suite='web',
        label='recovery watch no longer re-asserts the DEM bound',
        path='web/src/pages/globe.astro',
        needle='        reassertTerrainBound();\n',
        replacement='',
        guard='puts back what a restore silently drops, once the map reads healthy',
    ),
    Sabotage(
        suite='web',
        label='loss handler stops starting the watch (back to event-driven recovery)',
        path='web/src/pages/globe.astro',
        needle='    startRecoveryWatch(performance.now() + GL_RESTORE_GRACE_MS);',
        replacement='',
        guard='starts the recovery watch from the LOSS, because the restore event may never fire',
    ),
    Sabotage(
        suite='web',
        label='loss handler stops charging the recurrence budget',
        path='web/src/pages/globe.astro',
        needle='    if (recoveryVerdict(chargedLosses) === "give-up") {',
        replacement='    if (false) {',
        guard='bounds recovery by recurrence rather than trying to read a cause that does not exist',
    ),
    Sabotage(
        suite='web',
        label='cap re-assertion reports without repairing',
        path='web/src/pages/globe.astro',
        needle='        applyCacheCap();\n        console.info(`[terrain] DEM cache cap was not in force',
        replacement='        console.info(`[terrain] DEM cache cap was not in force',
        guard='REPAIRS a dropped cap before reporting it, and lets the next idle be the judge',
    ),
    Sabotage(
        suite='web',
        label='cap re-assertion verifies its own write synchronously (the stale-oracle bug)',
        path='web/src/pages/globe.astro',
        needle='        applyCacheCap();\n        console.info(',
        replacement='        applyCacheCap();\n        demCacheCapFault(map.style?.tileManagers?.[TERRAIN_SOURCE], intendedCacheSlots);\n        console.info(',
        guard='REPAIRS a dropped cap before reporting it, and lets the next idle be the judge',
    ),
    Sabotage(
        suite='web',
        label='polar cap re-add stops clearing the dead layers first',
        path='web/src/pages/globe.astro',
        needle='        if (map.getLayer(layerId)) map.removeLayer(layerId);',
        replacement='        void layerId;',
        guard='re-adds the caps on recovery, from OUTSIDE style.load, because that ordering is too early',
    ),
    Sabotage(
        suite='web',
        label='restore handler touches the notice again (the original bug)',
        path='web/src/pages/globe.astro',
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
        path='web/src/pages/globe.astro',
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
        path='web/src/pages/globe.astro',
        needle='        { id: "relief", type: "raster", source: "relief", paint: { "raster-fade-duration": 0 } },\n      ],',
        replacement='      ],',
        guard='draws the base UNDER relief and OVER the background, or it is pointless',
    ),
    Sabotage(
        suite='web',
        label='base source registered but never added to the style',
        path='web/src/pages/globe.astro',
        needle='sources: { relief: reliefSource, "relief-base": reliefBaseSource },',
        replacement='sources: { relief: reliefSource },',
        guard='draws the base UNDER relief and OVER the background, or it is pointless',
    ),
    Sabotage(
        suite='web',
        label='base source grows a second attribution, doubling the credit',
        path='web/src/pages/globe.astro',
        needle='    maxzoom: RELIEF_BASE_MAX_ZOOM,\n    tileSize: 256,\n  };',
        replacement='    maxzoom: RELIEF_BASE_MAX_ZOOM,\n    tileSize: 256,\n    attribution: CREDITS,\n  };',
        guard='caps the base source at z0, because that is what makes it unmissable',
    ),
    # --- the terrain-retirement flag (2026-07-29) ----------------------------------------------------
    Sabotage(
        suite='web',
        label='re-assertion stops honouring the retirement flag',
        path='web/src/pages/globe.astro',
        needle='    reassertTerrainBound = () => {\n      if (terrainRetired) return;',
        replacement='    reassertTerrainBound = () => {\n      if (false) return;',
        guard='goes quiet when the FPS ladder retires terrain, instead of crying wolf about the cap',
    ),
    Sabotage(
        suite='web',
        label='applyCacheCap stops honouring the retirement flag',
        path='web/src/pages/globe.astro',
        needle='    const applyCacheCap = () => {\n      if (terrainRetired) return;',
        replacement='    const applyCacheCap = () => {\n      if (false) return;',
        guard='goes quiet when the FPS ladder retires terrain, instead of crying wolf about the cap',
    ),
    Sabotage(
        suite='web',
        label='flag raised AFTER the teardown, so an idle inside it still false-alarms',
        path='web/src/pages/globe.astro',
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
        needle='` (${report.deviceClass.via}) · tier ${report.tier}`,',
        replacement='` · tier ${report.tier}`,',
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
        path='web/src/pages/globe.astro',
        needle='          pixelRatioLowered,\n          devicePixelRatio: map.getPixelRatio(),',
        replacement='          pixelRatioLowered,\n          devicePixelRatio: window.devicePixelRatio || 1,',
        guard="feeds the ladder the MAP's ratio, never the display's",
    ),
    Sabotage(
        suite='web',
        label='the dead-globe notice sinks back under the perf panel',
        path='web/src/pages/globe.astro',
        needle='    z-index: 50;',
        replacement='    z-index: 20;',
        guard='keeps the dead-globe notice above the ?perf panel',
    ),
    Sabotage(
        suite='web',
        label="the perf report reads the DISPLAY ratio instead of the map's",
        path='web/src/pages/globe.astro',
        needle='              devicePixelRatio: map.getPixelRatio(),',
        replacement='              devicePixelRatio: window.devicePixelRatio || 1,',
        guard="reports the MAP's ratio in the perf snapshot too, not the display's",
    ),
    Sabotage(
        suite='web',
        label='the report probes capabilities per tick again — 13.3 WebGL contexts/second',
        path='web/src/pages/globe.astro',
        needle='            signals: probedSignals,',
        replacement='            signals: probeSignals(),',
        guard="is never called from the ?perf overlay's per-tick path",
    ),
    Sabotage(
        suite='web',
        label='the tier is cached, so a mid-session quality change goes unreported',
        path='web/src/pages/globe.astro',
        needle='            tier: decideTier(probedSignals, getQuality()),',
        replacement='            tier: probedTier,',
        guard='still tracks a quality change the user makes mid-session',
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
        path='web/src/pages/globe.astro',
        needle='                  ...demCache().map((text) => ({ group: "ram" as const, text })),',
        replacement='',
        guard='surfaces the line through the perf overlay, so it is visible in Zen without devtools',
    ),
    # --- the four instrument fixes and the lazy boundary (2026-07-30) --------------------------------
    Sabotage(
        suite='web',
        label='helper stops rejecting an empty read',
        path='web/src/pages/globe.astro',
        needle='return snapshotHasContent(snapshot) ? snapshot : null;',
        replacement='return snapshot;',
        guard='rejects an empty read at the single place a routine sample is taken',
    ),
    Sabotage(
        suite='web',
        label='an empty idle read erases the healthy sample',
        path='web/src/pages/globe.astro',
        needle='lastHealthyGlState = sampledGlState() ?? lastHealthyGlState;',
        replacement='lastHealthyGlState = sampledGlState();',
        guard='never overwrites the healthy sample with an empty read',
    ),
    Sabotage(
        suite='web',
        label='export stops taking a fresh sample',
        path='web/src/pages/globe.astro',
        needle='{ sampleGlNow: true }',
        replacement='{ sampleGlNow: false }',
        guard='takes a FRESH sample on export and the stale one on the panel tick',
    ),
    Sabotage(
        suite='web',
        label='the 300 ms panel tick opts into per-tick sampling',
        path='web/src/pages/globe.astro',
        needle='perfReportLines(composeReport(timing, { expanded: true }))',
        replacement='perfReportLines(composeReport(timing, { expanded: true }, { sampleGlNow: true }))',
        guard='takes a FRESH sample on export and the stale one on the panel tick',
    ),
    Sabotage(
        suite='web',
        label='the fresh/stale switch is bypassed entirely',
        path='web/src/pages/globe.astro',
        needle='gl: (sampleGlNow ? sampledGlState() : null) ?? lastHealthyGlState,',
        replacement='gl: lastHealthyGlState,',
        guard='takes a FRESH sample on export and the stale one on the panel tick',
    ),
    Sabotage(
        suite='web',
        label='the seam is removed, so scripted A/Bs silently lose the camera',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='(window as unknown as { terrellaMap?: MaplibreMap }).terrellaMap = map;',
        replacement='// seam removed',
        guard='lives in the lazily-imported instrument, so an ordinary visit cannot reach it',
    ),
    Sabotage(
        suite='web',
        label='the page writes the seam itself, where nothing structural gates it',
        path='web/src/pages/globe.astro',
        needle='    const probedSignals = probeSignals();',
        replacement='    (window as unknown as { terrellaMap?: maplibregl.Map }).terrellaMap = map;\n    const probedSignals = probeSignals();',
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
        path='web/src/pages/globe.astro',
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
        path='web/src/pages/globe.astro',
        needle='  import type { CameraFill } from "../lib/perf/perfNetwork";',
        replacement='  import { newCameraFill } from "../lib/perf/perfNetwork";',
        guard='is never statically VALUE-imported by a page',
    ),
    Sabotage(
        suite='web',
        label='an instrument module stops loading dynamically',
        path='web/src/pages/globe.astro',
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
        path='web/src/pages/globe.astro',
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
        path='web/src/pages/globe.astro',
        needle=(
            '      addCountryHighlight(); // hover outline on top of everything, so the edge stays crisp\n'
        ),
        replacement=(
            '      addCountryHitTargets();\n'
            '      addCountryHighlight(); // hover outline on top of everything, so the edge stays crisp\n'
        ),
        guard='matches what globe.astro actually adds last',
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
