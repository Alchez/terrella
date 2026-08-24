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
from collections.abc import Callable, Sequence
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
    "pipeline/look",
    "pipeline/render",
    # Joined with `also`, the authored search aliases. Both guards over it read the SHIPPED config
    # rather than a fixture, on purpose — the claim is "what this repo publishes is well-formed",
    # and a fixture can only say the checker works on data nobody ships. So the only way to make
    # either guard fire is to write to the real file, and a guard that cannot be made to fire is
    # the thing this harness exists to catch.
    "config",
    # Joined with the render block plan, whose every wrong answer is a PLAUSIBLE image. A margin
    # sized too small does not fail: the block renders, the tile crops, and the shadows reaching it
    # from outside are simply absent, on both sides of a seam that has no edge to notice. Earth
    # cannot expose the body half at all — its map-unit-to-ground ratio is exactly 1.0, which is why
    # all four probe copies of this arithmetic dropped that term and none of them ever looked wrong.
    "pipeline/block_plan.py",
    # Joined with the layer table, which took the body-half gate and the stage split out of the
    # planet shader. Both of its guards are invisible while Earth is the only body that declares a
    # layer: "ask the body before the disk" passes either way on a box holding Earth's files, and a
    # wrong stage column just moves a key in a recipe nobody re-reads. Neither has an output to
    # inspect, so mutation is the only proof they still fire.
    "pipeline/layers.py",
    # Joined with the reproject-then-burn owner, whose whole subject is a GDAL command that succeeds
    # while producing nothing. Earth's one caller draws a coastline that is obviously there, so every
    # guard over it passes on this box whether it fires or not; the body it protects is the one that
    # burns a mapped unit, and that body has no output to inspect yet.
    "pipeline/vector_raster.py",
    # Joined when a stale `.done` marker was found vouching for bytes it never saw. Every stage in
    # the pipeline asks this module whether to run, so a weakened answer here is silent everywhere
    # at once and shows up as a rebuilt planet that quietly kept one empty layer. There is no output
    # to inspect for a stage that DIDN'T run, which is the whole reason mutation is the only proof.
    "pipeline/freshness.py",
    # Joined on PROCESS.md's reasoning, one document over: this file's sentence enumerating the
    # stages that take a required `--body` is a CLAIM ABOUT FOUR ENTRY POINTS, and a guard drives
    # every one of them to check it. A doc nobody can mutate is a doc whose guard cannot be shown to
    # fire, and this sentence carried a module that had stopped having a CLI for a whole arc.
    "docs/pipeline.md",
    # Joined with the stage sentinel, whose subject is a PRINT: the pass runs correctly whichever
    # way this module is broken, and what changes is only what a reader learns about a night that
    # takes 22 hours. Dropping the marker leaves every call site printing what it printed before,
    # so there is nothing to inspect and no other gate is about a log line.
    "pipeline/progress.py",
    # Joined with the antimeridian fill, whose every wrong answer is a PLAUSIBLE one. Copying a
    # neighbour instead of interpolating across the seam is within noise of correct on real terrain
    # (the two differ by a median of 2.2 m), and the refusal that keeps it from smoothing genuine
    # source gaps produces no output at all while it is working. Neither has an artifact to inspect.
    "pipeline/wrap_seam.py",
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
    # Joined with the output licence, which every site below restates and none checked. The sweep in
    # `tests/test_attributions.py` is guard and subject both: its suffix set decides which files are
    # read at all, so narrowing it silences the check from the inside while every assertion still
    # passes. `LICENSE` was a root here too until it went back to pure MIT; it states no licence but
    # its own now, so mutating it would prove nothing.
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
    #: The same suite narrowed to ONE named guard, or None where it cannot be narrowed.
    #:
    #: None FOR THE WEB SUITE ON PURPOSE. Some vitest guards are a describe and a title run
    #: together — `guard_is_findable` has to split them to match — so `-t` would silently select
    #: nothing. Making it fast means first making those guards selectable titles.
    narrow: Callable[[str], list[str]] | None


SUITES: dict[str, Suite] = {
    "web": Suite(
        command=["pnpm", "run", "test"],
        cwd="web",
        environment={},
        fail_pattern=re.compile(r"^\s*FAIL\s+(?:\|[^|]*\|\s+)?\S+\s+>\s+(.+)$"),
        narrow=None,
    ),
    "python": Suite(
        command=["uv", "run", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=".",
        environment={"PYTHONDONTWRITEBYTECODE": "1"},
        fail_pattern=re.compile(r"^FAILED\s+\S+::([^\s\[]+)"),
        # A python guard is a function name, so always a legal `-k` term. Matching none exits 5,
        # which reads as not-green with the guard absent, so `run_case` escalates rather than judges.
        narrow=lambda guard: ["uv", "run", "pytest", "-q", "-p", "no:cacheprovider", "-k", guard],
    ),
    # Not a test framework: a script that names its own failing check, so a case here is held to
    # the same standard as one naming a vitest title or a pytest function. It runs one script and
    # has nothing to narrow to.
    "collection": Suite(
        command=["node", "scripts/check_test_collection.ts"],
        cwd="web",
        environment={},
        fail_pattern=re.compile(r"^✗ test collection: (\S+)$"),
        narrow=None,
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
    # The scratch-directory half of the same guard, and it needs its own case because it is a
    # separate alternation with a separate way of being wrong: the pattern requires a TRAILING SLASH
    # so a bare directory name can still be passed as an argument, and a needle without one would
    # pass while the real citation form went uncaught.
    Sabotage(
        suite='python',
        label='cite a prototype script from the module whose constants it owns',
        path='pipeline/look/mars_ice.py',
        needle='FEATHER_KM = 5.0',
        replacement='#: Reproduced by ' + '_ice_ab' + '/scripts/feather.py\nFEATHER_KM = 5.0',
        guard='test_no_reference_to_a_file_a_clone_will_not_have',
    ),
    # --- The ice white becomes the layer's own ------------------------------------------------------
    # Every one of these leaves a cap that opens, a recipe that parses and a pass that exits 0. Two
    # of them are only wrong on a planet nobody looks at, and one is only wrong in a branch no
    # shipping body reaches — which is precisely why they are mutations rather than review comments.
    Sabotage(
        suite='python',
        label="the union stops following the winner, so one layer's colour paints another's pixels",
        path='pipeline/tile/shade_planet.py',
        needle='    wins = (incoming_alpha > current_alpha)[None]',
        replacement='    wins = np.ones(incoming_alpha.shape, dtype=bool)[None]',
        guard='test_the_layer_with_the_HIGHER_alpha_supplies_each_pixels_colour',
    ),
    Sabotage(
        suite='python',
        label='Mars paints both poles in its northern white, losing the measurement entirely',
        path='pipeline/look/layer_producers.py',
        needle='    northern = np.asarray(window.latitude) >= 0.0',
        replacement='    northern = np.ones(np.asarray(window.latitude).shape, dtype=bool)',
        guard='test_mars_paints_its_two_poles_in_DIFFERENT_whites',
    ),
    Sabotage(
        suite='python',
        label="a body's whites paint pixels and reach no recipe, so a re-tune looks fresh",
        path='pipeline/look/layer_producers.py',
        needle='def _mars_ice_paint_recipe() -> dict[str, Any]:\n',
        replacement='def _mars_ice_paint_recipe() -> dict[str, Any]:\n    return {}\n',
        guard='test_every_declared_white_reaches_that_bodys_recipe',
    ),
    Sabotage(
        suite='python',
        label='the cap and the tiles disagree about one ice colour across the crossfade',
        path='pipeline/look/perennial_ice.py',
        needle='                              paint=lambda: palette.MARS_ICE_WHITE["north"],',
        replacement='                              paint=lambda: palette.MARS_ICE_WHITE["south"],',
        guard='test_each_body_paints_one_pole_the_same_in_both_tiers',
    ),
    Sabotage(
        suite='python',
        label="Earth's two union layers declare different whites, so one wins by table order",
        path='pipeline/look/layer_producers.py',
        needle='        build=_build_glaciers, contribution=_earth_glaciers, paint=_earth_white,',
        replacement='        build=_build_glaciers, contribution=_earth_glaciers,\n'
                    '        paint=lambda _window: ((9, 9, 9), (1, 1, 1)),',
        guard='test_earths_two_union_layers_declare_the_SAME_white',
    ),
    # --- The interpolated pole: corrections that look fine in every artifact -------------------------
    # Each of these still renders a cap that opens, feathers and ships. The failure is either an edit
    # to ground the altimeter DID measure, or a correction quietly not applied — neither of which
    # announces itself in a WebP.
    Sabotage(
        suite='python',
        label='Earth is smoothed too, as though every pole had a data gap',
        path='pipeline/tile/cap_render.py',
        needle='    smooth = POLE_SMOOTH_BY_BODY.get(grid.body.name)\n    if smooth is None:\n'
               '        return heights',
        replacement='    smooth = POLE_SMOOTH_BY_BODY.get(grid.body.name,\n'
                    '                                     PoleSmooth(87.1, 30.0, 4.0, 40.0))',
        guard='test_a_body_whose_altimeter_reached_its_pole_is_left_alone',
    ),
    Sabotage(
        suite='python',
        label='the boundary is pinned to the disc instead of to the parallel',
        path='pipeline/tile/cap_render.py',
        needle='    knee_px = (90.0 - smooth.interpolated_lat) / (90.0 - abs(grid.edge_lat)) '
               '* (grid.px / 2.0)',
        replacement='    knee_px = 0.29 * (grid.px / 2.0)',
        guard='test_the_boundary_follows_the_edge_latitude',
    ),
    Sabotage(
        suite='python',
        label='the correction runs everywhere rather than only over the gap',
        path='pipeline/tile/cap_render.py',
        needle='    t = np.clip((knee_px + taper_px / 2.0 - radius) / taper_px, 0.0, 1.0)',
        replacement='    t = np.ones_like(radius)',
        guard='test_nothing_beyond_the_boundary_is_touched',
    ),
    Sabotage(
        suite='python',
        label='the smoothing stops reaching the freshness recipe',
        path='pipeline/tile/cap_render.py',
        needle='        fields["pole_smooth"] = asdict(smooth)',
        replacement='        pass',
        guard='test_only_a_body_with_a_gap_records_one',
    ),
    Sabotage(
        suite='python',
        label='the elevation texture re-spells the nodata rule and skips the correction',
        path='pipeline/tile/cap_render.py',
        needle='    heights = cap_heights(grid, raw)\n\n    factor = CAP_PX // CAP_ELEV_PX',
        replacement='    heights = np.where(raw < -1e4, 0.0, raw).astype(np.float32)\n\n'
                    '    factor = CAP_PX // CAP_ELEV_PX',
        guard='test_the_nodata_convention_has_exactly_one_owner',
    ),

    # --- Mars's ice registration: the guards with no output to inspect -------------------------------
    # None of these five has an artifact a reader could check. Mars's ice is a band of a few degrees
    # at one pole, and every one of these mutations leaves a raster that opens, a recipe that parses
    # and a pass that exits 0 — which is exactly the shape mutation exists for.
    Sabotage(
        suite='python',
        label='a build-time constant stops reaching the freshness gate',
        path='pipeline/tile/shade_planet.py',
        needle='        tunables = producer.build_recipe()',
        replacement='        tunables = {}',
        guard='test_a_changed_build_constant_rebuilds_the_raster',
    ),
    Sabotage(
        suite='python',
        label='the two poles are graded against each other\'s levels',
        path='pipeline/look/mars_ice.py',
        needle='                    albedo_alpha(field, ALPHA_LEVELS["north"], nodata),\n'
               '                    albedo_alpha(field, ALPHA_LEVELS["south"], nodata))',
        replacement='                    albedo_alpha(field, ALPHA_LEVELS["south"], nodata),\n'
                    '                    albedo_alpha(field, ALPHA_LEVELS["north"], nodata))',
        guard='test_each_pole_is_graded_against_its_own_levels',
    ),
    Sabotage(
        suite='python',
        label='a unit span stops being taken per hemisphere, so one band swallows the planet',
        path='pipeline/look/mars_ice.py',
        needle='              if (value >= 0.0) == northern]',
        replacement='              if True]',
        guard='test_a_span_is_taken_PER_HEMISPHERE',
    ),
    Sabotage(
        suite='python',
        label='the ice band loses its pad, clipping the feather at the band edge',
        path='pipeline/look/mars_ice.py',
        needle='        row0, row1 = max(0, min(rows) - pad_rows), min(height, max(rows) + pad_rows)',
        replacement='        row0, row1 = max(0, min(rows)), min(height, max(rows))',
        guard='test_the_pad_widens_the_band_on_both_sides',
    ),
    Sabotage(
        suite='python',
        label="Mars's cap grades both poles against the north's levels",
        path='pipeline/look/perennial_ice.py',
        needle='    graded = mars_ice.albedo_alpha(field, mars_ice.ALPHA_LEVELS[pole], '
               'viking_luma.NODATA)',
        replacement='    graded = mars_ice.albedo_alpha(field, mars_ice.ALPHA_LEVELS["north"], '
                    'viking_luma.NODATA)',
        guard='test_each_pole_grades_against_its_OWN_levels',
    ),
    Sabotage(
        suite='python',
        label='the alpha levels drop out of the build recipe, so a re-tune leaves a stale raster',
        path='pipeline/look/layer_producers.py',
        needle='            "mars_alpha_levels": {pole: list(levels)',
        replacement='            "mars_alpha_levels_unread": {pole: list(levels)',
        guard='test_mars_declares_the_two_constants_its_build_bakes_in',
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
        # The defect this whole split exists to make impossible. The two bodies are cut to different
        # ceilings, so Earth's numbers written out here — which is what the page held until the
        # registry became the source of truth — make the shallower globe request levels that were
        # never cut. Nothing errors: the address is refused without a storage read, so the tiles
        # simply never arrive and the globe looks slow rather than wrong.
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
        needle='      terrainRetired = true;\n      map.setTerrain(null);',
        replacement='      map.setTerrain(null);\n      terrainRetired = true;',
        guard='goes quiet when the FPS ladder retires terrain, instead of crying wolf about the cap',
    ),
    # --- the watchdog's reach: what gets judged at all ------------------------------------------
    Sabotage(
        suite='web',
        label='the watchdog goes back to a motion gate, so a parked page is never judged',
        path='web/src/components/Globe.astro',
        needle='map.on("render", judgeFrame);',
        replacement='map.on("move", judgeFrame);',
        guard='DRIVES THE WATCHDOG FROM `render`, AND NEVER FROM A MOTION GATE',
    ),
    Sabotage(
        suite='web',
        label='the window stops resetting on idle, so a recovered device stays convicted',
        path='web/src/components/Globe.astro',
        needle='map.on("idle", forgetJudgedFrames);',
        replacement='map.on("movestart", forgetJudgedFrames);',
        guard='resets the window on the map\'s own `idle`, which is the only honest reset',
    ),
    Sabotage(
        suite='web',
        label='the catastrophic trigger is dropped, leaving only the 45-sample median',
        path='web/src/lib/fpsDegradation.ts',
        needle='return isSustainedSlow(frames.intervalsMs) || frames.slowRun >= CATASTROPHIC_RUN_LENGTH;',
        replacement='return isSustainedSlow(frames.intervalsMs);',
        guard='fires on a run of stalls long before the sustained rule could',
    ),
    Sabotage(
        suite='web',
        label='a stall run survives a fast frame, so scattered hitches accumulate into a rung',
        path='web/src/lib/fpsDegradation.ts',
        needle='slowRun: intervalMs > CATASTROPHIC_FRAME_MS ? frames.slowRun + 1 : 0,',
        replacement='slowRun: intervalMs > CATASTROPHIC_FRAME_MS ? frames.slowRun + 1 : frames.slowRun,',
        guard='counts a stall run and breaks it on ONE fast frame',
    ),
    Sabotage(
        suite='web',
        label='the first render after a reset books the whole quiet spell as one frame',
        path='web/src/lib/fpsDegradation.ts',
        needle='if (frames.previousStampMs === null) return { ...frames, previousStampMs: stampMs };',
        replacement='if (frames.previousStampMs === null) frames = { ...frames, previousStampMs: 0 };',
        guard='FORGETS THE STAMP ON RESET, so a quiet spell is not booked as one enormous frame',
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

    # --- the arm a capture belongs to, and the seam that drives it ----------------------------------
    # Every case here defends the same property: a capture must be able to say which ARM produced it.
    # The instrument was already strict about provenance and a measurement went around it anyway, so
    # what these protect is the path that makes going around it unnecessary.
    Sabotage(
        suite='web',
        label='the origin records flag keys again, so two arms of one sweep read identically',
        path='web/src/lib/perf/perfSnapshot.ts',
        needle='    else for (const value of values) described.push(`${key}=${value}`);',
        replacement='    else described.push(key);',
        guard='separates two arms that differ only in what a flag is SET TO',
    ),
    Sabotage(
        suite='web',
        label='a blank arm becomes a name, so two unnamed captures collide',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='  return arm === null || arm.trim() === "" ? undefined : arm;',
        replacement='  return arm === null ? undefined : arm;',
        guard='treats a blank arm as unnamed rather than as a name',
    ),
    Sabotage(
        suite='web',
        label='the export stops carrying the arm, so every capture is a bare timestamp',
        path='web/src/lib/perf/perfOverlay.ts',
        needle='    options.arm === undefined ? path : `${path}?arm=${encodeURIComponent(options.arm)}`;',
        replacement='    path;',
        guard='names the capture when an arm is given',
    ),
    Sabotage(
        suite='web',
        label='the arm slug admits a path separator, so a label can escape the capture directory',
        path='web/src/lib/perfCaptureName.ts',
        needle='    .replace(/[^a-z0-9]+/g, "-")',
        replacement='    .replace(/[^a-z0-9./]+/g, "-")',
        guard='cannot emit a path separator or a dot, so traversal has nothing to work with',
    ),
    Sabotage(
        suite='web',
        label='the capture is named arm-first, splitting the one run whose arms get compared',
        path='web/src/lib/perfCaptureName.ts',
        needle='  return slug === null ? `${stamp}.json` : `${stamp}-${slug}.json`;',
        replacement='  return slug === null ? `${stamp}.json` : `${slug}-${stamp}.json`;',
        guard="puts the timestamp first, so one run's arms sort adjacent",
    ),
    # The seam duplicate that actually shipped, replayed under a name the guard has never seen. The
    # previous version of that guard named ONE handle and so could not have caught this at all.
    Sabotage(
        suite='web',
        label='the page hands the live map to a global again, under a brand-new name',
        path='web/src/components/Globe.astro',
        needle='  // The scripted-diagnosis seam is NOT here.',
        replacement='  window.debugMap = map;\n  // The scripted-diagnosis seam is NOT here.',
        guard='is not also written from the page, where nothing structural would gate it',
    ),

    # --- the arm flags, whose whole failure mode is being ignored quietly ---------------------------
    Sabotage(
        suite='web',
        label='arm flags stop needing ?perf, so a pasted link reconfigures a stranger',
        path='web/src/lib/perfArms.ts',
        needle='  return params.has("perf");',
        replacement='  return true;',
        guard='changes nothing on a production URL, so a pasted link cannot reconfigure a stranger',
    ),
    Sabotage(
        suite='web',
        label='?lod falls back to a default instead of refusing, so a run measures the wrong arm',
        path='web/src/lib/perfArms.ts',
        needle='  if (!Number.isFinite(value)) return null;',
        replacement='  if (!Number.isFinite(value)) return 9.314;',
        guard='is null on anything doubtful rather than falling back to the default',
    ),
    Sabotage(
        suite='web',
        label='?refresh takes a number, so refresh=2 rounds into a silent arm',
        path='web/src/lib/perfArms.ts',
        needle='  return mode === "on" ? true : mode === "off" ? false : null;',
        replacement='  return mode === "on" || mode === "1" ? true : mode === "off" || mode === "0" ? false : null;',
        guard='takes named modes only, so a number cannot round into a silent arm',
    ),
    Sabotage(
        suite='web',
        label='an ignored arm flag stops complaining, so a typo reads as the default',
        path='web/src/lib/perfArms.ts',
        needle='  if (!params.has(flag) || honoured) return null;',
        replacement='  if (true) return null;',
        guard='says so rather than ignoring the flag in silence',
    ),
    # The defect that actually shipped: the complaint fired on PRESENCE, so a working ?lod=11 warned
    # "not a value this flag takes" next to the line saying it applied. Every test covered a failure
    # path and none covered success, so nothing was red.
    Sabotage(
        suite='web',
        label='the complaint fires on presence again, crying wolf over every valid arm',
        path='web/src/lib/perfArms.ts',
        needle='  if (!params.has(flag) || honoured) return null;',
        replacement='  if (!params.has(flag)) return null;',
        guard='STAYS QUIET when the flag was honoured, which is the case that shipped broken',
    ),
    # The renderable count is the only term in the census that is a CAUSE, and both of its failure
    # modes are silent: a missing count reads as "no terrain", and a present one crowds the row.
    Sabotage(
        suite='web',
        label='an absent renderable count reads as terrain drawing nothing',
        path='web/src/lib/rttPoolTrim.ts',
        needle='  return Array.isArray(keys) ? keys.length : null;',
        replacement='  return Array.isArray(keys) ? keys.length : 0;',
        guard='is null, not 0, when there is nothing to read',
    ),
    Sabotage(
        suite='web',
        label='the renderable count is put back on the panel row, over the phone budget',
        path='web/src/lib/rttPoolTrim.ts',
        needle='  return `rtt ${stats.pooled} idle · ${stats.held} held · peak ${stats.peakTotal}`;',
        replacement='  return `rtt ${stats.pooled} idle · ${stats.held} held · peak ${stats.peakTotal} · drawn ${stats.renderable}`;',
        guard='leaves the renderable count off the row, whatever it reads',
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
        # ANCHORED ON `const action =`, NOT ON INDENTATION. The ladder's call and the ?perf report's
        # call are otherwise identical, and this needle used to tell them apart only by nesting
        # depth — the ladder's was two levels deeper. When the watchdog stopped nesting inside a
        # motion gate the two collapsed to the same indent and the needle matched twice, which
        # `test_needle_matches_exactly_once` caught. This is the same pair that once bit the other
        # way round, the shallower needle silently corrupting the report instead of the ladder.
        needle=(
            'const action = nextDegradationAction({\n'
            '      spinning,\n'
            '      pixelRatioLowered,\n'
            '      devicePixelRatio: map.getPixelRatio(),'
        ),
        replacement=(
            'const action = nextDegradationAction({\n'
            '      spinning,\n'
            '      pixelRatioLowered,\n'
            '      devicePixelRatio: window.devicePixelRatio || 1,'
        ),
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
        # The chord comes back, by the route that replaced the old `border-top-width: 0` cancel:
        # `+` matches DOM order, so a quiet button placed AFTER fullscreen keeps the divider of the
        # button quiet mode hid, and the group's 999px radius clips it into a dark arc.
        label='the quiet toggle stops leading its pill',
        path='web/src/components/Globe.astro',
        needle='joinRailGroup(map.getContainer(), ".maplibregl-ctrl-fullscreen", quietToggle.button, "start");',
        replacement='joinRailGroup(map.getContainer(), ".maplibregl-ctrl-fullscreen", quietToggle.button);',
        # The SOURCE scan, not the rendered one — and the split is structural rather than an
        # attribution slip. `railIcons.browser.test` mounts its own markup, so no edit to the page
        # can ever reach it; what proves that rendered assertion non-vacuous is its own positive
        # control, which the divider-deletion case below exercises. Both halves of the page's
        # ordering land on the one guard that reads the page.
        guard='keeps the page building that order, which no stylesheet can state',
    ),
    Sabotage(
        suite='web',
        # The other half of the same defect, and the one no stylesheet can see. `addControl` appends,
        # so adding the camera group first puts the frame group under a five-button pill that quiet
        # mode hides with `visibility` — leaving the eye floating partway down an empty right edge.
        label='the camera group goes back above the frame group',
        path='web/src/components/Globe.astro',
        needle=(
            '  map.addControl(new maplibregl.FullscreenControl({ container: document.body }), "top-right");\n'
            '  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");'
        ),
        replacement=(
            '  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");\n'
            '  map.addControl(new maplibregl.FullscreenControl({ container: document.body }), "top-right");'
        ),
        guard='keeps the page building that order, which no stylesheet can state',
    ),
    Sabotage(
        suite='web',
        # The cure that flattens the rail. Deleting the divider outright also removes the chord, so
        # the no-hairline assertion alone would pass — its positive control is what refuses this.
        label='the rail loses the divider between its buttons',
        path='web/src/styles/globe.css',
        needle='  border-top: 1px solid var(--line);',
        replacement='  border-top: 0;',
        guard='grows the chord straight back if the group is reordered — the positive control',
    ),
    Sabotage(
        suite='web',
        # The iPhone-Safari half. `FullscreenControl` renders nothing where the Fullscreen API is
        # absent, so "start" has to decide where the FALLBACK pill goes as well; appending it parks
        # the eye below the camera group on exactly the devices this reorder was reported from.
        label='a "start" placement stops reaching the group it had to create',
        path='web/src/lib/railControls.ts',
        needle='  if (placement === "start") container.prepend(group);\n  else container.append(group);',
        replacement='  container.append(group);',
        guard='carries "start" to the fallback GROUP too, not just to the button',
    ),
    Sabotage(
        suite='web',
        # The rail goes back to MapLibre's own hardcoded margin, 9.2px above and outside the
        # top-left row it is meant to line up with. Their rule is injected at RUNTIME, so an
        # equal-specificity override loses on source order and nothing anywhere reports it.
        label="the rail's inset loses to MapLibre's own control margin",
        path='web/src/styles/globe.css',
        needle='.maplibregl-ctrl-top-right .maplibregl-ctrl.maplibregl-ctrl {',
        replacement='.maplibregl-ctrl-top-right .maplibregl-ctrl {',
        # The RENDERED assertion, not its positive control — the control cannot catch this by
        # construction. It weakens the selector itself, so against an already-weak source its
        # `replace` matches nothing and it goes on measuring MapLibre's 10px and passing.
        guard='takes both offsets from the one token the top-left row uses',
    ),
    Sabotage(
        suite='web',
        # The band state read from one occupant instead of both. Every open runs the other's close
        # first, so this leaves the class stuck off after a search hit opens a card — a phone whose
        # gallery link is gone with nothing on screen to explain it.
        label='the narrow cap goes back to a selector the base rule outranks',
        path='web/src/components/Globe.astro',
        needle='    .dp-figure img {\n      object-fit: contain;\n    }',
        replacement='    .dp-hero,\n    .dp-border {\n      object-fit: contain;\n    }',
        guard='overrides the fit through the SAME selector the base rule uses, or it silently loses',
    ),
    Sabotage(
        suite='web',
        label='the card is capped at no width, so a tall hero is unbounded on a phone',
        path='web/src/components/Globe.astro',
        needle='      max-height: 40vh;',
        replacement='      max-height: none;',
        guard='caps the figure by HEIGHT, which is the only lever an inline aspect yields to',
    ),
    Sabotage(
        suite='web',
        label='the chip yields to the card again, so it vanishes whenever one opens',
        path='web/src/components/Globe.astro',
        needle='    countryChip.hidden = admin === null;',
        replacement='    countryChip.hidden = admin === null || !panel.hidden;',
        guard='shows the chip whenever the pointer resolves, and never yields it to a box',
    ),
    Sabotage(
        suite='web',
        label='the open-panel class is written from the card alone',
        path='web/src/components/Globe.astro',
        needle='const occupied = !panel.hidden || (searchPanel?.isOpen() ?? false);',
        replacement='const occupied = !panel.hidden;',
        guard="writes the class from BOTH occupants' state, not from whoever moved last",
    ),
    Sabotage(
        suite='web',
        # Renamed on the side that can be renamed. A stylesheet cannot import a constant, so the
        # class exists twice — and a selector matching nothing is valid CSS that cascades quietly.
        label='the open-panel class is renamed in the page but not the stylesheet',
        path='web/src/components/Globe.astro',
        needle='const PANEL_OPEN_CLASS = "panel-open";',
        replacement='const PANEL_OPEN_CLASS = "band-occupied";',
        guard='spells the class the same on both sides of a seam nothing can close',
    ),
    Sabotage(
        suite='web',
        # The credit "restored" while a panel covers its corner — the tidy-up that looks like a
        # licence fix and leaves a 326px panel sitting on top of the ⓘ instead.
        label='the credit is exempted from the band that yields to an open panel',
        path='web/src/styles/globe.css',
        needle='  body.panel-open .body-switcher,\n  body.panel-open .chrome-credit.chrome-credit.maplibregl-ctrl {',
        replacement='  body.panel-open .body-switcher {',
        guard='hides the credit with everything else in its band, and says why in the same breath',
    ),
    Sabotage(
        suite='web',
        # An edge offset written as its own literal again, which is how the rail and the row drifted
        # 9.2px apart with every rule individually correct.
        label='a floating element goes back to its own copy of the inset',
        path='web/src/components/Globe.astro',
        needle='  .globe-chrome {\n    position: fixed;\n    top: var(--page-inset);',
        replacement='  .globe-chrome {\n    position: fixed;\n    top: 1.2rem;',
        guard='leaves no edge offset written as its own literal',
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
        path='web/src/pages/mars/index.astro',
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
        needle='perfReportLines(composeReport(timing, { expanded: true, timeline: [], markMs: null }))',
        replacement=(
            'perfReportLines(composeReport(timing, { expanded: true, timeline: [], markMs: null }, '
            '{ sampleGlNow: true }))'
        ),
        guard='takes a FRESH sample on export and the stale one on the panel tick',
    ),
    Sabotage(
        suite='web',
        label='the perf timeline ring grows without bound',
        path='web/src/lib/perf/perfTimeline.ts',
        needle='    if (this.ring.length < this.capacity) this.ring.push(sample);\n    else {',
        replacement='    if (true) this.ring.push(sample);\n    else {',
        guard='cannot grow past its capacity',
    ),
    Sabotage(
        suite='web',
        label='the GPU accounting asks for an extension name nothing registers',
        path='web/src/lib/perf/perfTimeline.ts',
        needle='gl.getExtension("GMAN_webgl_memory")',
        replacement='gl.getExtension("WEBGL_memory")',
        guard='asks for the extension by the name the library registers',
    ),
    Sabotage(
        suite='web',
        label='the mark swallows a hitch that happened before it',
        path='web/src/lib/perf/perfTimeline.ts',
        needle='    if (sample.atMs < markMs) continue;',
        replacement='    if (false) continue;',
        guard='EXCLUDES an earlier hitch, which is the entire point of marking',
    ),
    Sabotage(
        suite='web',
        label='the timeline invents zeros where the census is absent',
        path='web/src/lib/perf/perfTimeline.ts',
        needle='    rttPooled: input.stats?.pooled ?? null,',
        replacement='    rttPooled: input.stats?.pooled ?? 0,',
        guard='keeps a null census null rather than inventing zeros',
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
        needle='  window.terrella = {',
        replacement='  const seamRemoved = {',
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
            '      if (countries) addCountryHighlight(); // hover outline, on top so the edge is crisp\n'
        ),
        replacement=(
            '      if (countries) addCountryHitTargets();\n'
            '      if (countries) addCountryHighlight(); // hover outline, on top so the edge is crisp\n'
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
    # The spin step is the one place a constant-in-degrees can creep back. Every failure below is
    # silent on a desktop at low zoom — the globe still turns, at a speed nobody would call wrong
    # until they zoom in — which is exactly how the old ceiling came to exist instead of a fix.
    Sabotage(
        suite='web',
        label='the spin step goes back to a constant in degrees, the shape the ceiling existed to contain',
        path='web/src/lib/spinRate.ts',
        needle='return SPIN_REFERENCE_DEGREES * 2 ** (SPIN_REFERENCE_ZOOM - zoom);',
        replacement='return SPIN_REFERENCE_DEGREES;',
        guard='holds the screen speed constant across the camera\'s whole range',
    ),
    Sabotage(
        suite='web',
        label='the zoom term inverts, so the deep end crawls and the overview blurs',
        path='web/src/lib/spinRate.ts',
        needle='return SPIN_REFERENCE_DEGREES * 2 ** (SPIN_REFERENCE_ZOOM - zoom);',
        replacement='return SPIN_REFERENCE_DEGREES * 2 ** (zoom - SPIN_REFERENCE_ZOOM);',
        guard='halves for every zoom level gained',
    ),
    # The two constants are only pinned TOGETHER by the absolute-speed assertion; every other test
    # in that file is a ratio and passes happily while the globe turns at twice the ratified rate.
    Sabotage(
        suite='web',
        label='the ratified rate doubles while every relative property still holds',
        path='web/src/lib/spinRate.ts',
        needle='export const SPIN_REFERENCE_DEGREES = 2;',
        replacement='export const SPIN_REFERENCE_DEGREES = 4;',
        guard='holds the speed that was actually ratified on screen',
    ),
    Sabotage(
        suite='web',
        label='the reference zoom moves, which rescales the whole ladder invisibly',
        path='web/src/lib/spinRate.ts',
        needle='export const SPIN_REFERENCE_ZOOM = 3;',
        replacement='export const SPIN_REFERENCE_ZOOM = 4;',
        guard='holds the speed that was actually ratified on screen',
    ),
    # The wash's zoom fade. The first case is the one the browser test exists for: the object is
    # still well-formed, every unit assertion could be satisfied by re-deriving it from the
    # constants, and MapLibre rejects it with an ErrorEvent and no throw — so the layer never
    # enters the style and country picking dies with it.
    Sabotage(
        suite='web',
        label='the zoom curve is nested inside the hover case, which MapLibre silently rejects',
        path='web/src/lib/countryHighlight.ts',
        needle=(
            '      "fill-opacity": [\n'
            '        "interpolate",\n'
            '        ["linear"],\n'
            '        ["zoom"],\n'
            '        WASH_FULL_ZOOM,\n'
            '        ["case", whenHovered, WASH_OPACITY, 0],\n'
            '        WASH_CLEAR_ZOOM,\n'
            '        0,\n'
            '      ],'
        ),
        replacement=(
            '      "fill-opacity": [\n'
            '        "case",\n'
            '        whenHovered,\n'
            '        ["interpolate", ["linear"], ["zoom"], WASH_FULL_ZOOM, WASH_OPACITY,'
            ' WASH_CLEAR_ZOOM, 0],\n'
            '        0,\n'
            '      ],'
        ),
        guard='is a spec MapLibre accepts',
    ),
    Sabotage(
        suite='web',
        label='the ratified wash strength doubles while the curve stays self-consistent',
        path='web/src/lib/countryHighlight.ts',
        needle='export const WASH_OPACITY = 0.16;',
        replacement='export const WASH_OPACITY = 0.32;',
        guard='holds the ratified strength at every zoom',
    ),
    Sabotage(
        suite='web',
        label='the fade finishes before the fly-to lands, so a clicked country arrives unlit',
        path='web/src/lib/countryHighlight.ts',
        needle='export const WASH_CLEAR_ZOOM = 7;',
        replacement='export const WASH_CLEAR_ZOOM = 5;',
        guard='still paints in the frame a clicked country lands in',
    ),
    Sabotage(
        suite='web',
        label='the fade\'s far stop stops falling, so the wash survives at every zoom',
        path='web/src/lib/countryHighlight.ts',
        needle='        WASH_CLEAR_ZOOM,\n        0,\n      ],',
        replacement='        WASH_CLEAR_ZOOM,\n        WASH_OPACITY,\n      ],',
        guard='is gone once the viewport is inside one country',
    ),
    # The highlight toggle. Its default is ON, which is the opposite of every other view-bar
    # toggle, so the first two cases are the same mistake reached from two files — read the key
    # Borders' way, or ship the markup in Borders' state — and each is invisible on its own.
    Sabotage(
        suite='web',
        label='the highlight key is read the way an opt-in overlay is, so the default flips off',
        path='web/src/lib/highlightPreference.ts',
        needle='return storage.getItem(HIGHLIGHT_KEY) !== "0";',
        replacement='return storage.getItem(HIGHLIGHT_KEY) === "1";',
        guard='is on for a visitor who has never touched it',
    ),
    Sabotage(
        suite='web',
        label='the button renders unpressed while the globe is already highlighting',
        path='web/src/layouts/Base.astro',
        needle=(
            '              id="highlight-toggle"\n'
            '              class="icon-btn"\n'
            '              aria-pressed="true"'
        ),
        replacement=(
            '              id="highlight-toggle"\n'
            '              class="icon-btn"\n'
            '              aria-pressed="false"'
        ),
        guard='ships the button already pressed',
    ),
    # The two transitions no pointer event produces. Both leave the globe looking like the button
    # did nothing, and both are green under every test that only drives the pointer.
    Sabotage(
        suite='web',
        label='the switch stops repainting the feature the pointer is parked on',
        path='web/src/lib/hoverHighlight.ts',
        needle='      if (litId !== null) writeAll(litId, next);',
        replacement='      if (false && litId !== null) writeAll(litId, next);',
        guard='clears the parked feature the moment it goes off',
    ),
    Sabotage(
        suite='web',
        label='the chip stops answering the switch, leaving a name over unlit ground',
        path='web/src/lib/hoverHighlight.ts',
        needle='  const relabel = () => label(enabled ? litId : null);',
        replacement='  const relabel = () => label(litId);',
        guard='writes nothing at all and names nothing',
    ),
    # Mars wires its own highlight late. Handing over the tracker and not the highlight leaves the
    # second body re-resolving correctly and then relabelling through Earth's, which holds nothing.
    Sabotage(
        suite='web',
        label='the second body keeps the first body\'s highlight',
        path='web/src/components/Globe.astro',
        needle='    activeHighlight = featureHighlight;',
        replacement='    void featureHighlight;',
        guard='hands the pointer\'s chrome to the resolver that answers on this body',
    ),
    # The 8px the fourth control needed. A margin looks like spacing taste until it is the
    # difference between one row and two at the narrowest width the site serves.
    Sabotage(
        suite='web',
        label='the divider takes its side margins back, and the globe bar runs out of room',
        path='web/src/styles/global.css',
        needle='  .view-bar-divider {\n    margin-inline: 0;\n  }',
        replacement='  .view-bar-divider {\n    margin-inline: 0.25rem;\n  }',
        guard='fits on one row at 320px, on every bar the site ships',
    ),
    # The pills give back 1.6px a side at phone widths, and that is the half of the tightening the
    # floor actually rests on — the gap beside it is headroom and clears 320px without this.
    Sabotage(
        suite='web',
        label='the phone pills take their padding back, and the globe bar runs out of room',
        path='web/src/styles/global.css',
        needle='    padding: 0.35rem 0.6rem;\n    font-size: 0.78rem;',
        replacement='    padding: 0.35rem 0.7rem;\n    font-size: 0.78rem;',
        guard='fits on one row at 320px, on every bar the site ships',
    ),
    # Two ways the touch hide dies, and they fail in different halves of one guard: the rule can
    # stop naming the control, or it can keep naming it and lose the cascade. Neither renders
    # differently on a hover-capable box, which is every box the suite runs on.
    Sabotage(
        suite='web',
        label='the touch hide is written as a class and loses to the icon button',
        path='web/src/styles/global.css',
        needle='@media (hover: none) {\n  #highlight-toggle {',
        replacement='@media (hover: none) {\n  .icon-btn {',
        guard='does not offer the pointer control where the pointer cannot hover',
    ),
    Sabotage(
        suite='web',
        label='a later !important puts the pointer control back on touch devices',
        path='web/src/styles/global.css',
        needle='@media (hover: none) {\n  #highlight-toggle {\n    display: none;\n  }\n}\n',
        replacement=(
            '@media (hover: none) {\n  #highlight-toggle {\n    display: none;\n  }\n}\n'
            '.view-bar button.icon-btn {\n  display: inline-flex !important;\n}\n'
        ),
        guard='does not offer the pointer control where the pointer cannot hover',
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
        path='web/src/components/Gallery.astro',
        needle='  :global(html.no-js) .card figure img[data-src] {\n    display: none;\n  }',
        replacement='',
        guard='hides the staged image when script never runs',
    ),
    Sabotage(
        suite='web',
        label='the watched set is taken with :has(), which the fallback browsers do not support',
        path='web/src/components/Gallery.astro',
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
        path='web/src/components/Gallery.astro',
        needle='    <a href="/about/">About</a>',
        replacement='      <a href="/earth/">Globe</a>\n      <a href="/about/">About</a>',
        guard='holds one layout across every heading width at 412px',
    ),
    # The subtle direction: the row still fits on THIS machine's fallback font, and stops fitting
    # on a visitor whose serif is wider. The sweep is what makes that reachable from a test.
    Sabotage(
        suite='web',
        label='the source link becomes a word again, spending the slack the icon bought',
        path='web/src/components/Gallery.astro',
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
        path='web/src/components/Gallery.astro',
        needle='    padding: 0.25rem;',
        replacement='',
        guard='gives the icon link a real touch target, not just its ink',
    ),
    Sabotage(
        suite='web',
        label='the source link loses its accessible name, announcing as a bare URL',
        path='web/src/components/Gallery.astro',
        needle='      aria-label="Source on GitHub"\n',
        replacement='',
        guard='gives the source link an accessible name, since its only content is a decorative SVG',
    ),
    # The second of the two shifts, restored: a post-paint DOM change to the nav.
    Sabotage(
        suite='web',
        label='a script removes a masthead link again, re-arming the un-wrap half of the shift',
        path='web/src/components/Gallery.astro',
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
        # Re-anchored when the page grew a tab per planet: the link used to be one hand-written
        # `/earth/`, and is now derived per body from `bodyRoutes`. Breaking the href alone leaves
        # the derivation in place, so this falsifies the half that actually reaches a crawler.
        needle='href={world.globe}',
        replacement='href="#"',
        guard="keeps a real, crawlable link to EVERY body's globe somewhere a clone can follow",
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
        path='web/src/pages/earth/index.astro',
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
        # Qualified by the selector: the body switcher takes the same tightening, so the two
        # declarations alone stopped naming one rule the day it arrived.
        needle='  .view-bar button {\n    padding: 0.35rem 0.6rem;\n    font-size: 0.78rem;',
        replacement='  .view-bar button {\n    padding: 0.4rem 0.85rem;\n    font-size: 0.82rem;',
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
    # --- The body switcher --------------------------------------------------------------------------
    # Every mutation below leaves a control that renders, reads correctly on the body it was written
    # for, and is wrong somewhere the author is not looking — another planet, another page, or the
    # accessibility tree.
    Sabotage(
        suite='web',
        # The switcher stops appearing on the pages a visitor is sent to when their device cannot
        # run a globe — which is to say, on the pages where being able to change planet matters most
        # and where nobody develops.
        label='the switcher is narrowed to globes, and the lite pages lose their way across',
        path='web/src/layouts/Base.astro',
        needle='      pageRole !== "plain" && (',
        replacement='      pageRole === "globe" && (',
        guard='goes on every page that belongs to a body, and derives that from the role',
    ),
    Sabotage(
        suite='web',
        # The fill and the announcement come apart: the pill still paints if a class rule is added,
        # and a screen reader is handed a set with nothing current in it.
        label='the current body is marked with a class instead of aria-current',
        path='web/src/layouts/Base.astro',
        needle='aria-current={entry.slug === body ? "true" : undefined}',
        replacement='class={entry.slug === body ? "is-current" : undefined}',
        guard='marks the current body with aria-current, which is what the fill is keyed on',
    ),
    Sabotage(
        suite='web',
        # The pill keeps its place and the country chip comes back up into it. Both elements render,
        # the collision is one line of overlap on the two widths where the chip exists at all, and
        # no other rule in either component is wrong.
        label='the space above the country chip is closed back up to nothing',
        path='web/src/styles/global.css',
        needle='  --switcher-drop: 3rem;',
        replacement='  --switcher-drop: 0rem;',
        guard='is displayed, and drops whatever else centres in that band by a real distance',
    ),
    Sabotage(
        suite='web',
        # Two declarations of one distance, which is exactly how the rail and the top-left row ended
        # up 9.2px apart with every rule individually correct.
        label='the page inset is declared a second time, in the sheet it moved out of',
        path='web/src/styles/globe.css',
        needle=':root {\n  --rail-button-size: 2.15rem;',
        replacement=':root {\n  --page-inset: 1.2rem;\n  --rail-button-size: 2.15rem;',
        guard='owns the inset once, in the sheet every page gets',
    ),
    Sabotage(
        suite='web',
        # The same drift in the other file, and the instance that was sitting there unseen while the
        # literal scan read only the globe's scoped block.
        label='the view bar goes back to its own copy of the edge inset',
        path='web/src/styles/global.css',
        needle='  bottom: var(--page-inset);',
        replacement='  bottom: 1.2rem;',
        guard='leaves no edge offset written as its own literal',
    ),
    Sabotage(
        suite='web',
        # Two planets wearing one name in the control whose entire job is to tell them apart.
        label='a second body is given a label that already belongs to another',
        path='web/src/lib/bodies.ts',
        needle='    label: "Mars",',
        replacement='    label: "Earth",',
        guard='names every body distinctly, which is all a label can be checked for here',
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
        needle=("    # test, not one value read twice.\n"
                "    mercator_radius_m=6378137.0,"),
        replacement=("    # test, not one value read twice.\n"
                     "    mercator_radius_m=6371000.0,"),
        guard='test_earth_carries_web_mercator_s_defining_sphere',
    ),
    # The plausible edit: 6371000 IS a real earth radius, just not the projection's one. Nothing
    # crashes; the per-row z-factor is quietly wrong at every latitude. It used to be catchable only
    # as drift between two copies; now there is one home, so the guard pins the value itself.
    Sabotage(
        suite='python',
        label='a shading module regrows its own sphere radius beside the shared one',
        path='pipeline/look/snow.py',
        needle='    return mercator.latitude_at(merc_y, mercator.WEB_MERCATOR_RADIUS_M)',
        replacement='    return mercator.latitude_at(merc_y, 6378137.0)',
        guard='test_no_module_regrows_web_mercators_sphere',
    ),
    # THE SAME REGROWTH IN A PACKAGE THE OLD GUARD COULD NOT SEE. That guard named `hillshade` and
    # `snow`, which described where the constant had been found rather than where it could appear.
    # This case is what proves the sweep replaced a list of nouns, so it must keep a live anchor in
    # `pipeline/tile/` — it had one in `terrain_rgb.row_latitudes` until the polar feather that
    # helper existed for was deleted, and an orphaned needle would have retired the demonstration
    # silently. Re-anchored on the cap's projection string, where collapsing the body's AEQD sphere
    # into Web Mercator's is both plausible and the exact three-radii confusion `bodies.py` warns of.
    Sabotage(
        suite='python',
        label='a tile module regrows the sphere radius the render package was guarded against',
        path='pipeline/tile/cap_render.py',
        needle='        radius = self.body.aeqd_radius_m',
        replacement='        radius = 6378137.0',
        guard='test_no_module_regrows_web_mercators_sphere',
    ),
    # Identical output today, which is exactly why nothing else would notice: the module has quietly
    # stopped asking the projection module and gone back to knowing the answer. The needle moved off
    # `bodies.EARTH` when the sphere did: a grid row's latitude is a property of the GRID, and every
    # grid here is EPSG:3857 for every planet, so reading it from a body was the misleading half.
    # --- A pointer into a doc still lands where it says --------------------------------------------
    # ALL THREE OF THESE ALREADY SHIPPED, which is why the guard exists rather than the reverse.
    # `tile/shade.py` cited ART.md:56 and ART.md:90, both of which had become blank lines, and
    # `look/hillshade.py` cited ART.md:63 for the sun's locked azimuth while that line had become a
    # table row about the sea colour ramp. The mutations are planted in `gen_borders.py` because it
    # is the pointer under a MUTABLE_ROOT; the defect has no preferred site.
    Sabotage(
        suite='python',
        label='a doc pointer goes back to naming a line number, which is what rotted three times',
        path='pipeline/compose/gen_borders.py',
        needle='(ART.md\n§ Borders',
        replacement='(ART.md:56\n§ Borders',
        guard='test_no_pointer_cites_a_line_number',
    ),
    # The document is renamed or leaves version control. Existence on the author's disk is NOT the
    # test — an untracked file passes that locally and is absent from every clone and from CI.
    Sabotage(
        suite='python',
        label='a doc pointer names a document no clone receives',
        path='pipeline/compose/gen_borders.py',
        needle='downscaling (ART.md',
        replacement='downscaling (ARTDIRECTION.md',
        guard='test_every_document_a_pointer_names_reaches_a_clone',
    ),
    # The heading moves out from under a pointer that still names a real file. This is the live case
    # rather than a hypothetical: ART.md took 42 commits in three months carrying 95 heading
    # changes, and the `look/` split renamed two of them the same day it landed.
    Sabotage(
        suite='python',
        label='the cited section is renamed, leaving a pointer at a file that no longer explains it',
        path='pipeline/compose/gen_borders.py',
        needle='§ Borders, with overlay_borders',
        replacement='§ Boundaries, with overlay_borders',
        guard='test_every_section_citation_lands_on_a_heading',
    ),
    # The defect that shipped: the block frame's payload stopped answering the whole vocabulary,
    # and nothing ran the shipping path until a real prep crashed on it.
    Sabotage(
        suite='python',
        label="the block frame stops answering the frame vocabulary's geo keys",
        path='pipeline/render/prep_block.py',
        needle='                   frame_lonlat=None, dst_crs="EPSG:3857",\n'
               '                   xres_m=extent_w_m / window.width, extent_w_m=extent_w_m,\n'
               '                   extent_h_m=extent_w_m * window.height / window.width)',
        replacement='                   frame_lonlat=None, dst_crs="EPSG:3857")',
        guard='test_the_payload_round_trips_the_validating_serialiser',
    ),
    # The ocean gate on the block's sea-ice cut. Dropping it leaks alpha onto shoreline land, and
    # the same alpha damps displacement in the rig — coastal collapse at full exaggeration, while
    # every open-ocean pixel still renders correctly.
    Sabotage(
        suite='python',
        label='the sea-ice alpha stops being gated to the ocean',
        path='pipeline/render/prep_block.py',
        needle='    gated = np.where(ocean, contribution, 0.0)',
        replacement='    gated = np.asarray(contribution, dtype=float)',
        guard='test_ice_that_reaches_land_is_refused',
    ),
    # The column quietly flips back to the pre-ice answer. The literal pins in test_bodies catch
    # the table; this guard catches the BEHAVIOUR — the gather stops handing the rig its ice.
    Sabotage(
        suite='python',
        label="the block column drops sea ice again, starving the rig's ice arm",
        path='pipeline/layers.py',
        needle='SEA_ICE = Layer("sea_ice", in_composite=True, in_cap=True, in_block=True,',
        replacement='SEA_ICE = Layer("sea_ice", in_composite=True, in_cap=True, in_block=False,',
        guard='test_the_block_gathers_sea_ice_like_the_composite',
    ),
    # THE DEFECT THAT ALREADY HAPPENED, four times, in the render probe. Every copy of the margin
    # arithmetic there divided by nothing, because each was written and checked on Earth where the
    # ratio is 1.0 — and the same edit here undersizes 93% of Mars's blocks while every Earth case
    # in the suite still passes. There is no artifact to inspect: the shadow simply stops.
    Sabotage(
        suite='python',
        label='the block margin drops the map-unit-to-ground ratio, as all four probe copies did',
        path='pipeline/block_plan.py',
        needle='zfactor = exaggeration / (ground_scale * math.cos(math.radians(latitude_deg)))',
        replacement='zfactor = exaggeration / (1.0 * math.cos(math.radians(latitude_deg)))',
        guard='test_dropping_ground_scale_undersizes_mars_rather_than_erroring',
    ),
    # A margin that rounds to NEAREST is right for most blocks and one quantum short for the ones
    # sitting just above a boundary — i.e. it fails on precisely the blocks whose shadows are
    # longest. Two of the ten pinned cases sit within 0.2% of a boundary and exist for this.
    Sabotage(
        suite='python',
        label='the context quantum rounds to nearest, truncating the blocks with the longest shadows',
        path='pipeline/block_plan.py',
        needle='    quantised = math.ceil(CONTEXT_RATIO * per_axis_px / CONTEXT_QUANTUM_PX) * CONTEXT_QUANTUM_PX',
        replacement='    quantised = round(CONTEXT_RATIO * per_axis_px / CONTEXT_QUANTUM_PX) * CONTEXT_QUANTUM_PX',
        guard='test_context_rounds_up_rather_than_to_nearest',
    ),
    # The two halo axes are not symmetric and the probe's copies had them both wrapping, which lets
    # the north pole's relief size a block at the south pole. On a planet where both poles carry
    # tall ice that produces a bigger margin than needed rather than a smaller one, so it costs GPU
    # time silently instead of truncating anything — invisible in the output either way.
    Sabotage(
        suite='python',
        label='the block halo wraps in latitude, so the north pole sizes the south',
        path='pipeline/block_plan.py',
        needle='    padded = np.pad(relief, ((1, 1), (0, 0)), mode="edge")',
        replacement='    padded = np.pad(relief, ((1, 1), (0, 0)), mode="wrap")',
        guard='test_halo_clamps_in_latitude',
    ),
    # The one geometric term this module contributes on top of the shared law. Dropping it makes
    # every margin 1.41x larger than needed: nothing looks wrong, every seam is still covered, and
    # the planet render simply costs about a fifth more GPU-hours than it should.
    Sabotage(
        suite='python',
        label='the diagonal shadow loses its per-axis component, oversizing every frame',
        path='pipeline/block_plan.py',
        needle='    per_axis_px = reach_px * math.cos(math.radians(45.0))',
        replacement='    per_axis_px = reach_px',
        guard='test_earth_reproduces_the_reach_of_blocks_that_were_actually_rendered',
    ),
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
        needle='    planet_producer: PlanetProducer\n',
        replacement='    planet_producer: PlanetProducer = "composite"\n',
        guard='test_no_field_carries_a_default_so_a_new_one_must_be_decided_per_body',
    ),
    # --- The producer vocabulary, whose two failures are opposite shapes ------------------------
    # The typo case. It is a plausible one — "raytraced" is how the arc's prose spells the adjective
    # — and pyright would refuse it, but a `str` annotation reaching here in some future edit would
    # not, so the runtime membership test is what has to hold.
    Sabotage(
        suite='python',
        label='a body names a producer nothing can dispatch, and pyright is the only thing refusing it',
        path='pipeline/bodies.py',
        # The comment line disambiguates: the field's VALUE line is identical on both bodies, and a
        # needle matching twice is refused by the harness rather than mutating an arbitrary one.
        needle='    # production run is a full night of GPU, and the pixels it ships are a look decision.\n'
               '    planet_producer="composite",\n',
        replacement='    # production run is a full night of GPU, and the pixels it ships are a look decision.\n'
                    '    planet_producer="raytraced",\n',
        guard='test_every_body_names_a_producer_the_vocabulary_knows',
    ),
    # The opposite shape, and the one that reads as a simplification: dropping the Literal for a
    # plain `str` empties `PLANET_PRODUCERS` through `get_args`, which turns every downstream
    # membership test into a check against nothing rather than into an error anyone would see.
    Sabotage(
        suite='python',
        label='the producer vocabulary widens to a bare str, so it can no longer refuse anything',
        path='pipeline/bodies.py',
        needle='PlanetProducer = Literal["composite", "raytrace"]\n',
        replacement='PlanetProducer = str\n',
        guard='test_every_body_names_a_producer_the_vocabulary_knows',
    ),
    # --- Polar caps as a per-body decision ----------------------------------------------------------
    # The dangerous property of all three: a body publishing no caps would RENDER them perfectly well.
    # Declaring no surface layers leaves the cap needing only the heightfield, so there is no missing
    # file to stop it and no error to read — just ~14 GB a pole spent shipping a look nobody ratified.
    Sabotage(
        suite='python',
        label='the pass shells out to the cap render for every body again',
        path='pipeline/tile/planet_pass.py',
        needle='    return body.renders_polar_caps\n',
        replacement='    return True\n',
        guard='test_the_pass_skips_the_cap_subprocess_for_a_body_that_publishes_none',
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
        needle=('    # celestial body — which does not escape the check either. See the module '
                'note.\n    aeqd_radius_m=6371000.0,'),
        replacement=('    # celestial body — which does not escape the check either. See the module '
                     'note.\n    aeqd_radius_m=3396190.0,'),
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
        needle='    tile_max_zoom=7,',
        replacement='    tile_max_zoom=8,',
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
        needle='    resolution = body.map_units_per_pixel',
        replacement='    resolution = 305.7483',
        guard='test_the_shade_pass_no_longer_carries_its_own_grid_or_ceiling',
    ),
    # Identical output for Earth — which is exactly why nothing else can see it. The module has
    # quietly stopped asking the body and gone back to knowing the answer, and the next planet gets
    # a raster warped to a lattice its pyramid was never going to be cut on. The scan is the only
    # oracle available: a regrown constant type-checks and tests green.
    #
    # THE CASE ABOVE ASKS WHETHER THE RESOLUTION IS THE BODY'S; THIS ONE ASKS WHETHER ANYTHING EVER
    # RE-READS IT. Registered because the reverted form is what actually shipped: the reference
    # raster's inputs are a VRT and a chunk directory, neither of which moves when a ceiling does,
    # so raising Mars z6 -> z7 left a 32768 square grid reading FRESH and a real pass composited it
    # and began cutting a z7 pyramid out of z6 pixels. Every raster BELOW height was protected the
    # whole time; the one they take their grid from was not. Mutating to the exact prior expression,
    # which still type-checks and still passes every test that does not open the raster.
    # THE ONE THAT ACTUALLY SHIPPED AN EMPTY LAYER. A marker from an earlier successful run keeps
    # vouching after a later run overwrites the output and dies mid-write; the next pass then skips
    # it, because the marker exists and `grid_matches` passes precisely BECAUSE the crash created a
    # full-size target on the new grid. Mars's ice alpha came out 0 non-zero of 4.29 billion pixels
    # with every gate green, and only an eye on the globe caught it.
    Sabotage(
        suite='python',
        label='a done marker stops having to be newer than the bytes it vouches for',
        path='pipeline/freshness.py',
        needle='    if output.stat().st_mtime > stamped:\n        return True',
        replacement='    pass  # a crashed rewrite now keeps the previous run\'s promise',
        guard='test_an_output_rewritten_after_its_marker_is_stale',
    ),
    Sabotage(
        suite='python',
        label='the height warp goes back to mtimes alone, so a moved ceiling reuses the old grid',
        path='pipeline/tile/shade_planet.py',
        needle='    if reference_needs_rebuild(height, resolution, planet / "planet_heightfield.vrt", chunks):',
        replacement='    if is_stale(height, planet / "planet_heightfield.vrt", chunks):',
        guard='test_the_reference_raster_is_not_gated_on_mtimes_alone',
    ),
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
    # --- the browser's zoom range against the cut that produced it --------------------------------
    # The cut deciding a ceiling is only half of it: the browser holds its own copy, and until this
    # guard the two were bridged ONLY by the runtime header check, which needs archives on disk. On a
    # checkout without them the copies could disagree freely. The three cases below are the three
    # shapes that disagreement takes — a body's literal, a shared constant, and a layer going quiet.
    Sabotage(
        suite='python',
        label="the browser's zoom range: Mars's relief ceiling drifts past what was cut",
        path='web/src/lib/tileAddress.ts',
        # ANCHORED ON THE ENTRY'S OWN COMMENT, because `minZoom: 0, maxZoom: 7` stopped identifying
        # a single entry the day Mars published a terrain pyramid at the same ceiling. A bare
        # coordinate pair is not a location once a second thing legitimately holds it.
        needle="      // runtime by the dev server reading the archive's own header.\n"
               "      minZoom: 0,\n      maxZoom: 7,",
        replacement="      // runtime by the dev server reading the archive's own header.\n"
                    "      minZoom: 0,\n      maxZoom: 8,",
        guard='test_the_browser_publishes_every_pyramid_at_the_zoom_the_pipeline_cut_it_to',
    ),
    Sabotage(
        suite='python',
        label="the browser's zoom range: Mars's TERRAIN ceiling takes Earth's z8",
        path='web/src/lib/tileAddress.ts',
        # The sibling the case above needed once a second Mars pyramid existed: the same drift, on
        # the entry whose ceiling comes from the elevation cut's own master rather than the relief
        # cut's. Earth's z8 here asks for a level the descent never wrote.
        needle='      // arrives as a 404 and paints exactly like a tile still in flight.\n'
               '      minZoom: 0,\n      maxZoom: 7,',
        replacement='      // arrives as a 404 and paints exactly like a tile still in flight.\n'
                    '      minZoom: 0,\n      maxZoom: 8,',
        guard='test_the_browser_publishes_every_pyramid_at_the_zoom_the_pipeline_cut_it_to',
    ),
    # Through a NAMED CONSTANT rather than a literal, which is the case the guard nearly missed:
    # Earth's registry entry reads `RELIEF_MAX_ZOOM` where Mars's is a number, so a digits-only read
    # would have covered one planet while reading as though it covered both.
    Sabotage(
        suite='python',
        label="the browser's zoom range: Earth's ceiling drifts, via the constant its entry reads",
        path='web/src/lib/reliefTiles.ts',
        needle='export const RELIEF_MAX_ZOOM = 8;',
        replacement='export const RELIEF_MAX_ZOOM = 9;',
        guard='test_the_browser_publishes_every_pyramid_at_the_zoom_the_pipeline_cut_it_to',
    ),
    Sabotage(
        suite='python',
        label="the browser's zoom range: the vector pyramid stops matching the raster it overlays",
        path='web/src/lib/countryTiles.ts',
        needle='export const COUNTRIES_MAX_ZOOM = 8;',
        replacement='export const COUNTRIES_MAX_ZOOM = 7;',
        guard='test_the_browser_publishes_every_pyramid_at_the_zoom_the_pipeline_cut_it_to',
    ),
    # The OVER-parameterisation direction, and the quieter one. Under-parameterising is loud — Mars
    # cuts to Earth's ceiling and the disk says so. Moving an encoder setting onto the body reads as
    # thoroughness and silently lets two planets' encodings drift, with every other test still green.
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
        path='pipeline/look/hillshade.py',
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
        path='pipeline/layers.py',
        needle='    if layer.name not in body.surface_layers:',
        replacement='    if layer.name not in body.surface_layers and not source.exists():',
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
    # WAS "the Antarctic patch applies to every body again", mutating a gate that no longer exists.
    # Dropping the declaration question outright now RAISES out of `producer_for` instead of
    # painting, so that bug has no silent form left. This is the one that survives: ask the disk
    # rather than the body, which reads as the obvious tidy because the slice is right there, and is
    # correct for every layer except the one whose southern half has no file behind it at all.
    Sabotage(
        suite='python',
        label='the producer is gated on its raster rather than on the body declaring the layer',
        path='pipeline/look/layer_producers.py',
        needle=('    for layer, producer in producers_for(body, vocabulary):\n'
                '        seen = dataclasses.replace(window, raw=layer_raw[layer.name])'),
        replacement=('    for layer, producer in producers_for(body, vocabulary):\n'
                     '        if layer_raw[layer.name] is None:\n'
                     '            continue\n'
                     '        seen = dataclasses.replace(window, raw=layer_raw[layer.name])'),
        guard='test_earths_antarctic_patch_survives_a_missing_persistence_raster',
    ),
    Sabotage(
        suite='python',
        label='the built-layer reads lose the guard snow persistence once lacked',
        path='pipeline/tile/shade_planet.py',
        needle=('            layer_raw={name: read1_window(path, win) if path.exists() else None\n'
                '                       for name, path in layer_paths.items()},'),
        replacement=('            layer_raw={name: read1_window(path, win)\n'
                     '                       for name, path in layer_paths.items()},'),
        guard='test_a_body_with_no_perennial_ice_layer_composites_without_the_raster',
    ),
    # One expression now, where it used to be four fields and only three of them guarded. The
    # mutation can no longer single snow out — which is the point, and why the case reads as a
    # whole-set check rather than as the specific regression it descends from.
    # --- The composite tier's producers -------------------------------------------------------------
    # Every source here is one global path to an Earth dataset that IS on this box, so each mutation
    # below leaves a composite that renders cleanly, at plausible latitudes, describing another
    # planet. The cap tier's twins of these sit above.
    Sabotage(
        suite='python',
        label="the warp asks the disk before the body, so Earth's datasets reach every planet",
        path='pipeline/tile/shade_planet.py',
        needle=('        if not layers.body_declares_layer(body, layer, consequence):\n'
                '            continue\n'
                '        producer = layer_producers.producer_for(body, layer)'),
        replacement='        producer = layer_producers.PRODUCER_BY_BODY_LAYER[("earth", layer.name)]',
        guard='test_a_body_with_no_layers_opens_none_of_earths_files',
    ),
    Sabotage(
        suite='python',
        label='an unregistered body inherits Earth composite producers instead of the registry refusing',
        path='pipeline/look/layer_producers.py',
        needle='        return PRODUCER_BY_BODY_LAYER[(body.name, layer.name)]',
        replacement=('        return PRODUCER_BY_BODY_LAYER.get(\n'
                     '            (body.name, layer.name), PRODUCER_BY_BODY_LAYER[("earth", layer.name)])'),
        guard='test_a_body_declaring_a_layer_it_cannot_produce_opens_none_of_earths_files',
    ),
    # Both render Earth perfectly, because Earth's answer IS Earth's producer. They are wrong only
    # on the planet nobody has built, which is why neither has an output anyone could inspect.
    Sabotage(
        suite='python',
        label='a producer freezes its composite sources at import, so a moved data store never reaches it',
        path='pipeline/look/layer_producers.py',
        needle='        sources=lambda: (snow.SP_NC,),',
        replacement='        sources=lambda frozen=(snow.SP_NC,): frozen,',
        guard='test_the_composite_sources_are_read_at_CALL_time_so_a_redirect_reaches_them',
    ),
    # --- the vector->raster stage: four ways to draw nothing, or the wrong thing, in silence ------
    # Every one of these leaves both GDAL commands exiting 0 and a well-formed raster on disk. That
    # is the whole reason they are cases: there is no output to inspect and no error to read, and
    # three of the four are invisible on Earth, which never burns a mapped unit at all.
    Sabotage(
        suite='python',
        label='the vector is LABELLED with the target CRS instead of reprojected into it',
        path='pipeline/vector_raster.py',
        needle='    return ["ogr2ogr", "-t_srs", target_srs, str(out), str(source)]',
        replacement='    return ["ogr2ogr", "-a_srs", target_srs, str(out), str(source)]',
        guard='test_the_reprojection_uses_t_srs_and_never_a_srs',
    ),
    # NOT ONE OF THE FOUR ABOVE: this one is loud, and it is registered because it SHIPPED. The
    # reprojection cannot write over an existing GeoJSON by any flag, so the stage succeeded once
    # and raised on every re-run — invisible until something asked for the intermediate a second
    # time, which needs a grid to change, which needs a body's ceiling to move. Mars z6 -> z7 was
    # the first in this project's life, and it died four minutes into a real pass.
    Sabotage(
        suite='python',
        label='the reprojection stops removing its target, so the stage works once and never again',
        path='pipeline/vector_raster.py',
        needle='    projected.unlink(missing_ok=True)',
        replacement='    pass  # no unlink: the second run now dies on the first run\'s leftovers',
        guard='test_a_second_identical_run_succeeds',
    ),
    Sabotage(
        suite='python',
        label='the empty-burn guard stops firing, so a missed projection reads as a body with no ice',
        path='pipeline/vector_raster.py',
        needle='    if must_draw is not None and drew_nothing(out):',
        replacement='    if False and must_draw is not None and drew_nothing(out):',
        guard='test_the_guard_refuses_an_empty_burn_and_names_the_subject',
    ),
    # THE ROCK BURN'S OWN EMPTINESS GUARD, and it is a sharper case than the one above rather than a
    # copy of it. A missed ice burn shows: the cap loses its white. A rock mask of zeros subtracts
    # nothing from a rule that already covers the whole continent, so it renders as exactly the look
    # that shipped before the layer existed — every file present, every consumer working.
    Sabotage(
        suite='python',
        label='the rock burn accepts an empty result, so Antarctica silently keeps its old white',
        path='pipeline/look/snow.py',
        needle='    if vector_raster.drew_nothing(out_path):',
        replacement='    if False and vector_raster.drew_nothing(out_path):',
        guard='test_geometry_that_misses_the_grid_raises',
    ),
    # A GeoPackage is many layers in one file and `gdal_rasterize` will burn one of them regardless.
    Sabotage(
        suite='python',
        label='the burn stops naming its layer, so a GeoPackage answers by position instead',
        path='pipeline/vector_raster.py',
        needle='            *(["-l", layer] if layer is not None else []),',
        replacement='',
        guard='test_a_second_layer_in_the_same_file_contributes_nothing',
    ),
    # The inversion this layer exists to avoid: fold the rock into the union and the outcrop is
    # painted the very white it was measured to remove, as a perfectly plausible ice sheet.
    Sabotage(
        suite='python',
        label='the rock layer starts contributing, so the union paints the outcrop white',
        path='pipeline/look/layer_producers.py',
        needle='''    inversion that renders as a perfectly plausible ice sheet.
    """
    return None''',
        replacement='''    inversion that renders as a perfectly plausible ice sheet.
    """
    return None if _window.raw is None else np.asarray(_window.raw, dtype=float)''',
        guard='test_gather_returns_no_entry_for_it_however_much_rock_there_is',
    ),
    # THE DEFECT THAT SHIPPED, WRITTEN OUT AS A MUTATION. Moving the negative back inside a union
    # member is the placement the outcrop spent a release under: every plumbing guard passes, the
    # subtraction genuinely runs, and `persistence_alpha` re-claims 63% of the rock in the very next
    # operation. Only an OUTCOME guard can see it, which is what this case exists to prove.
    Sabotage(
        suite='python',
        label='the exclusion moves back inside the union, so any other white source re-covers the rock',
        path='pipeline/look/layer_producers.py',
        needle='''    alpha = np.zeros(shape, dtype=float)
    carried = None
    for layer in WHITE_UNION:
        contribution = contributions.get(layer.name)
        if contribution is None:
            continue
        if merge is not None:
            carried = merge(carried, alpha, layer.name, contribution)
        alpha = np.maximum(alpha, contribution)
    for layer in WHITE_EXCLUSIONS:
        removed = exclusions.get(layer.name)
        if removed is None:
            continue
        alpha = np.where(np.asarray(removed).astype(bool), 0.0, alpha)
    return alpha, carried''',
        replacement='''    alpha = np.zeros(shape, dtype=float)
    carried = None
    contributions = dict(contributions)
    for layer in WHITE_EXCLUSIONS:
        removed = exclusions.get(layer.name)
        if removed is None or WHITE_UNION[0].name not in contributions:
            continue
        contributions[WHITE_UNION[0].name] = np.where(
            np.asarray(removed).astype(bool), 0.0, contributions[WHITE_UNION[0].name])
    for layer in WHITE_UNION:
        contribution = contributions.get(layer.name)
        if contribution is None:
            continue
        if merge is not None:
            carried = merge(carried, alpha, layer.name, contribution)
        alpha = np.maximum(alpha, contribution)
    return alpha, carried''',
        guard='test_a_glacier_over_the_outcrop_does_not_rescue_it_either',
    ),
    # The fold stops excluding at all. The tell it must NOT have is a crash: every raster is still
    # built, warped and read, and the only symptom is Antarctica back under solid white.
    Sabotage(
        suite='python',
        label='the fold takes the exclusions and applies none of them',
        path='pipeline/look/layer_producers.py',
        needle='    for layer in WHITE_EXCLUSIONS:',
        replacement='    for layer in ():',
        guard='test_saturated_persistence_does_not_rescue_the_white_on_rock',
    ),
    # `shade_planet` keys `layer_raw` on `path.exists()` alone, so this gate is the only thing
    # standing between a body that declares no rock layer and an exclusion on its fold.
    Sabotage(
        suite='python',
        label='the exclusion is read off the raster rather than off the declaration',
        path='pipeline/look/layer_producers.py',
        needle='''    exclusions = {layer.name: raw for layer in WHITE_EXCLUSIONS
                  if layer.name in vocabulary and layer.name in body.surface_layers
                  and (raw := layer_raw.get(layer.name)) is not None}''',
        replacement='''    exclusions = {layer.name: raw for layer in WHITE_EXCLUSIONS
                  if (raw := layer_raw.get(layer.name)) is not None}''',
        guard='test_a_body_that_declares_no_rock_layer_excludes_nothing',
    ),
    # The stage half of that same gate: a vocabulary the caller narrowed must narrow the negatives
    # with it, or a stage takes an exclusion for a layer it never gathered.
    Sabotage(
        suite='python',
        label='the exclusions ignore the caller vocabulary, so a stage excludes a layer it never reads',
        path='pipeline/look/layer_producers.py',
        needle='                  if layer.name in vocabulary and layer.name in body.surface_layers',
        replacement='                  if layer.name in body.surface_layers',
        guard='test_a_stage_that_does_not_read_the_layer_excludes_nothing',
    ),
    # THE PLANNED STEP 6, WRITTEN OUT AS A MUTATION. Declaring the rock among the ice producer's
    # sources looks like the obvious symmetry with `_earth_north`'s NetCDF, and it hands an
    # undownloaded GeoPackage the power to render Antarctica on the tan LAND ramp.
    Sabotage(
        suite='python',
        label="the south declares the rock as a source, so a missing file switches off the white",
        path='pipeline/look/perennial_ice.py',
        needle='    ("earth", "south"): CapIce(sources=lambda: (), alpha=_earth_south,',
        replacement=('    ("earth", "south"): CapIce('
                     'sources=lambda: (__import__("pipeline.acquire.download_add_rock", '
                     'fromlist=["GPKG"]).GPKG,), alpha=_earth_south,'),
        guard='test_an_absent_rock_file_leaves_the_forced_white_untouched',
    ),
    # The south stops declaring the exclusion. Every raster is still built, warped and burnt, the
    # producer still answers, and the only symptom is Antarctica back under solid white.
    Sabotage(
        suite='python',
        label='the south cap stops declaring the outcrop, so the -84 seam quietly re-covers it',
        path='pipeline/look/perennial_ice.py',
        needle='                               exclusions=lambda: (layers.ANTARCTIC_ROCK,)),',
        replacement='                               exclusions=lambda: ()),',
        guard='test_only_earths_south_declares_an_exclusion',
    ),
    # An eager burn on every pole reads as a harmless simplification and puts a pole test outside
    # the registry: the north would reproject the whole ADD GeoPackage for a disc it cannot
    # intersect, where the burn's own emptiness guard raises on a shipping pass.
    Sabotage(
        suite='python',
        label='the north cap declares the outcrop too, so a disc that cannot hold it burns anyway',
        path='pipeline/look/perennial_ice.py',
        needle='                               paint=_earth_cap_white, exclusions=lambda: ()),',
        replacement=('                               paint=_earth_cap_white, '
                     'exclusions=lambda: (layers.ANTARCTIC_ROCK,)),'),
        guard='test_only_earths_south_declares_an_exclusion',
    ),
    # THE CAP STOPS SHARING THE TILE TIER'S LAW. Returning the producer's answer straight out is
    # what shipped, and it is invisible while the cap has exactly one white producer -- which is
    # what RGI region 19, now carried, stops being safe to assume.
    Sabotage(
        suite='python',
        label='the cap returns its producer alpha unfolded, so no exclusion reaches the disc',
        path='pipeline/tile/cap_render.py',
        needle='''    alpha, _ = layer_producers.fold_white(
        {layers.PERENNIAL_ICE.name: answer}, answer.shape,
        exclusions={layer.name: mask for layer in producer.exclusions()
                    if (mask := _cap_exclusion(grid, layer)) is not None})
    return alpha, producer.paint()''',
        replacement='    return answer, producer.paint()',
        guard='test_a_producer_claiming_every_pixel_still_loses_the_outcrop',
    ),
    # A layer the renderer has no burn for must be a hard error: the silent answer means "nothing to
    # exclude", which renders as white over ground the declaration says is bare.
    Sabotage(
        suite='python',
        label='an undeclared cap exclusion is ignored rather than refused',
        path='pipeline/tile/cap_render.py',
        needle='''    if layer is not layers.ANTARCTIC_ROCK:
        raise KeyError(''',
        replacement='''    if layer is not layers.ANTARCTIC_ROCK:
        return None
    if False:
        raise KeyError(''',
        guard='test_an_undeclared_exclusion_is_refused_rather_than_ignored',
    ),
    Sabotage(
        suite='python',
        label='the rock stops being a cap dependency, so a re-burn leaves both caps looking fresh',
        path='pipeline/tile/cap_render.py',
        needle='        sources.append(download_add_rock.GPKG)',
        replacement='        pass  # no rock dependency: a re-burn now moves no mtime the cap sees',
        guard='test_the_rock_is_a_cap_source_by_DECLARATION_and_drops_with_the_layer',
    ),
    Sabotage(
        suite='python',
        label='the feather pad becomes a constant, so every band seam is quietly wrong',
        path='pipeline/look/mars_ice.py',
        needle='    pad = int(np.ceil(feather_m / float(scale.min()))) + 1',
        replacement='    pad = 3',
        guard='test_banding_does_not_change_the_alpha_at_all',
    ),
    Sabotage(
        suite='python',
        label="Apu is drawn in the south too, whitening two thirds of that disc on no evidence",
        path='pipeline/look/mars_ice.py',
        needle='SOUTH_UNITS: tuple[str, ...] = ("lApc",)',
        replacement='SOUTH_UNITS: tuple[str, ...] = ("lApc", "Apu")',
        guard='test_apu_is_northern_only',
    ),
    # Rec. 601 is the OTHER luma every codebase carries, it sums to one as well, and it grades every
    # pixel against levels measured through Rec. 709. Nothing about the result looks wrong.
    Sabotage(
        suite='python',
        label='the luma moves to Rec. 601, re-grading Mars against levels measured in Rec. 709',
        path='pipeline/look/mars_ice.py',
        needle='LUMA_WEIGHTS: tuple[float, float, float] = (0.2126, 0.7152, 0.0722)',
        replacement='LUMA_WEIGHTS: tuple[float, float, float] = (0.299, 0.587, 0.114)',
        guard='test_it_is_rec_709_and_the_weights_are_a_partition_of_one',
    ),
    # --- The Viking brightness stage --------------------------------------------------------------
    # Every one of these leaves a module that imports, type-checks and builds a correct-looking
    # raster; what they break is the gate that decides whether to build it again.
    Sabotage(
        suite='python',
        label='the brightness recipe stops recording its weights, so a re-graded field reads fresh',
        path='pipeline/look/viking_luma.py',
        needle='        "luma_weights": list(mars_ice.LUMA_WEIGHTS),\n',
        replacement='',
        guard='test_changed_weights_are_STALE',
    ),
    Sabotage(
        suite='python',
        label='the recipe drops the source edition, so a republished mosaic never restages',
        path='pipeline/look/viking_luma.py',
        needle='        "source_md5": download_viking_mosaic.EXPECTED_MD5,\n',
        replacement='',
        guard='test_a_republished_source_edition_is_STALE',
    ),
    # The natural simplification, and it inverts the gate: `valid_fraction` is produced BY the build,
    # so comparing it asks the stage to predict its own result and rebuilds 215 MB on every run.
    Sabotage(
        suite='python',
        label='freshness compares the measured share too, so the stage rebuilds forever',
        path='pipeline/look/viking_luma.py',
        needle='    return {key: value for key, value in recorded.items() if key != "valid_fraction"} == \\\n        {key: value for key, value in expected.items() if key != "valid_fraction"}',
        replacement='    return recorded == expected',
        guard='test_a_different_measured_share_is_STILL_fresh',
    ),
    # An integer luma is the natural spelling for an 8-bit source and it destroys the dark end: a
    # pixel of (1, 0, 0) rounds to 0, which is the nodata fill, so the darkest measured ground
    # arrives at the grader as never measured.
    Sabotage(
        suite='python',
        label='the luma rounds to integers, turning the darkest measured ground into nodata',
        path='pipeline/look/mars_ice.py',
        needle='    return (stack * weights).sum(axis=0)',
        replacement='    return np.rint((stack * weights).sum(axis=0))',
        guard='test_the_dimmest_measurable_pixel_survives_as_measured',
    ),
    Sabotage(
        suite='python',
        label='a layer stops naming its built raster, so it silently leaves the composite entirely',
        path='pipeline/layers.py',
        needle='                      requires_raster=None, warped_basename="snow_persistence_3857.tif")',
        replacement='                      requires_raster=None, warped_basename=None)',
        guard='test_every_built_layer_names_the_raster_the_composite_reads',
    ),
    # The quietest of the set: dropping the basename takes the layer out of the warp, out of the
    # window reads AND out of `composite_deps` at once, so Earth stops painting its ice and the
    # composite reads fresh forever — the raster it lost is no longer a dependency to be newer than.
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
        needle='''    surface_layers=frozenset({"lake_depth", "perennial_ice", "glaciers", "sea_ice", "coastline",
                              "antarctic_rock"}),''',
        replacement='''    surface_layers=frozenset({"lake_depth", "perennial_ice", "glaciers", "coastline",
                              "antarctic_rock"}),''',
        guard='test_earth_has_every_surface_layer_and_mars_declares_only_what_it_can_produce',
    ),
    # The under-declaring direction: Earth stops painting a product it has, which is a look change
    # nothing else asserts — the sea ice would simply not be there, and the pass would say so once
    # in a line of output nobody reads back.
    # --- The cap pass's layer gates -----------------------------------------------------------------
    # Every source below is one global path to an Earth dataset that IS on this box, so each mutation
    # here leaves a cap that renders cleanly, at plausible latitudes, describing another planet.
    Sabotage(
        suite='python',
        label="the cap's ice asks the disk before the body, so Earth's snow reaches every planet",
        path='pipeline/tile/cap_render.py',
        needle=('    if not (layers.body_declares_layer(grid.body, layers.PERENNIAL_ICE, consequence)\n'
                '            and all(layers.layer_is_buildable(grid.body, layers.PERENNIAL_ICE, '
                'source, consequence)'),
        replacement='    if not (all(Path(source).exists()',
        guard='test_a_body_with_no_layers_opens_none_of_earths_files',
    ),
    Sabotage(
        suite='python',
        label="the cap's sea ice asks the disk before the body, painting an Arctic on any planet",
        path='pipeline/tile/cap_render.py',
        needle=('    if not layers.layer_is_buildable(grid.body, layers.SEA_ICE, '
                'Path(seaice.SEAICE_SRC),\n                                     consequence):'),
        replacement='    if not Path(seaice.SEAICE_SRC).exists():',
        guard='test_a_body_with_no_layers_opens_none_of_earths_files',
    ),
    # Both of the above are the tidy-looking collapse rather than a typo: the body check reads as
    # redundant once you have seen the file sitting there, and dropping it is silent on the only
    # body anyone builds.
    Sabotage(
        suite='python',
        label="the forced Antarctic ice loses its gate and whitens a sea-less planet's pole",
        path='pipeline/tile/cap_render.py',
        needle='        return np.zeros((grid.px, grid.px), dtype=np.float32), None\n    inputs = perennial_ice.CapIceInputs(',
        replacement='        pass\n    inputs = perennial_ice.CapIceInputs(',
        guard='test_the_forced_antarctic_patch_is_refused_for_a_body_with_no_ice_layer',
    ),
    # The one rule with no file behind it, so nothing on disk could ever have switched it off. Both
    # poles run through the one gate above now, so these two cases mutate the same lines in the two
    # directions that matter: the body question dropped, and the whole refusal dropped.
    Sabotage(
        suite='python',
        label="a cap's sources come from Earth's producer rather than from the body's own",
        path='pipeline/tile/cap_render.py',
        needle='        sources.extend(perennial_ice.cap_ice(grid.body, grid.name).sources())',
        replacement='        sources.extend(perennial_ice.CAP_ICE_BY_BODY[("earth", grid.name)].sources())',
        guard='test_a_caps_sources_are_exactly_what_its_own_producer_declares',
    ),
    # Straight back to the shape this seam replaced, and it renders Earth perfectly: Earth's answer
    # IS Earth's producer. It is wrong only on the planet nobody has built.
    Sabotage(
        suite='python',
        label='an unregistered body inherits Earth ice instead of the registry refusing',
        path='pipeline/look/perennial_ice.py',
        needle='        return CAP_ICE_BY_BODY[(body.name, pole)]',
        replacement='        return CAP_ICE_BY_BODY.get((body.name, pole), CAP_ICE_BY_BODY[("earth", pole)])',
        guard='test_a_body_with_no_producer_raises_and_names_itself',
    ),
    Sabotage(
        suite='python',
        label='the pole leaves the key, so both caps of a body get one producer',
        path='pipeline/look/perennial_ice.py',
        needle='    ("earth", "south"): CapIce(sources=lambda: (), alpha=_earth_south, paint=_earth_cap_white,',
        replacement='    ("earth", "south"): CapIce(sources=lambda: (Path(snow.SP_NC),), alpha=_earth_north, paint=_earth_cap_white,',
        guard='test_earths_two_poles_get_DIFFERENT_producers',
    ),
    Sabotage(
        suite='python',
        label='a producer freezes its source list at import, so a moved data store never reaches it',
        path='pipeline/look/perennial_ice.py',
        needle='    ("earth", "north"): CapIce(sources=lambda: (Path(snow.SP_NC),), alpha=_earth_north,',
        replacement='    ("earth", "north"): CapIce(sources=lambda frozen=(Path(snow.SP_NC),): frozen, alpha=_earth_north,',
        guard='test_the_sources_are_read_at_CALL_time_so_a_redirect_reaches_them',
    ),
    # Still a callable, still typed, still correct on a box that never moves its store — the default
    # argument is evaluated once at import, which is precisely the bug the suite caught here first.
    Sabotage(
        suite='python',
        label='the coastline gate keeps only its look half, burning Natural Earth onto any body',
        path='pipeline/tile/cap_render.py',
        needle=('    if grid.coast_opacity <= 0.0:\n        return False\n'
                '    return layers.layer_is_buildable(grid.body, layers.COASTLINE, COAST_SHP,\n'
                '                                     "the cap ships with no land/sea line")'),
        replacement='    return grid.coast_opacity > 0.0',
        guard='test_a_body_without_the_layer_declines_it_though_earths_file_is_right_there',
    ),
    Sabotage(
        suite='python',
        label='a cap depends on a climatology it never opens, so it can never read fresh',
        path='pipeline/tile/cap_render.py',
        needle=('    if layers.SEA_ICE.name in grid.body.surface_layers:\n'
                '        sources.append(Path(seaice.SEAICE_SRC))'),
        replacement='    sources.append(Path(seaice.SEAICE_SRC))',
        guard='test_a_source_for_an_absent_layer_is_not_a_dependency',
    ),
    Sabotage(
        suite='python',
        label='the cap recipe stops recording which layers are off, so switching one restages nothing',
        path='pipeline/tile/cap_render.py',
        needle=('    absent = layers.layers_off(grid.body, layers.CAP_LAYERS)\n'
                '    missing = {"layers_off": absent} if absent else {}'),
        replacement='    missing = {}',
        guard='test_turning_a_layer_off_restages_although_its_source_stops_being_a_dependency',
    ),
    # Load-bearing rather than tidy: turning a layer off also REMOVES its file from cap_sources, so
    # the mtime that would have noticed disappears along with the layer. The recipe is what is left.
    Sabotage(
        suite='python',
        label='the composite recipe enumerates every layer, so a cap-only decision restages 46 GB',
        path='pipeline/tile/shade_planet.py',
        needle='    absent_layers = layers.layers_off(body, layers.COMPOSITE_LAYERS)',
        replacement='    absent_layers = layers.layers_off(body, layers.SURFACE_LAYERS)',
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
    # The same confusion one function further down, and the one that stayed uncaught longest: this
    # returns metres either way, scales with the disc either way, and on an Earth-only pipeline is
    # wrong by a thousandth. Every ground distance drawn on a cap divides by it.
    Sabotage(
        suite='python',
        label='the cap pixel is measured in AEQD map metres, so a ground distance draws at the wrong width',
        path='pipeline/tile/cap_render.py',
        needle='    return (2.0 * grid.edge_m / grid.px) * bodies.ground_metres_per_aeqd_unit(grid.body)',
        replacement='    return 2.0 * grid.edge_m / grid.px',
        guard='test_every_shipped_cap_grid_spans_its_own_bodys_ground',
    ),
    # --- the two ice instruments' caches ---------------------------------------------------------
    # Both scripts reproduce a ratified look constant and nothing else can, so an oracle that reuses
    # the previous disc's pixels reports agreement about ice it never looked at. The gate is what
    # makes the cached name mean the grid rather than just the pole.
    Sabotage(
        suite='python',
        label="the ice-white warp is cached on its filename, so a moved cap disc is measured stale",
        path='scripts/measure_mars_ice_white.py',
        needle='    if freshness.warp_needs_rebuild(warped, cap_render.cap_reference_grid(grid), mosaic):',
        replacement='    if not warped.exists():',
        guard='test_an_artifact_from_another_disc_is_rebuilt',
    ),
    Sabotage(
        suite='python',
        label="the levels script's unit burn is cached on its filename, so a moved cap disc is stale",
        path='scripts/measure_viking_levels.py',
        needle='        if freshness.warp_needs_rebuild(out, cap_render.cap_reference_grid(grid),\n'
               '                                        download_sim3292.unit_path(unit)):',
        replacement='        if not out.exists():',
        guard='test_an_artifact_from_another_disc_is_rebuilt',
    ),
    # --- a freshness predicate must ANSWER, never raise ------------------------------------------
    # `download_sim3292.is_fresh` guarded the parse and not the shape, so a two-byte `{}` — valid
    # JSON — reached `document["features"]` and raised `KeyError`, killing the re-fetch that was
    # supposed to heal it. Six siblings guarded less; four compared a recipe with no `try` at all.
    # The first case reverts `recorded_json` to that narrow form. The second is the shape half on
    # its own, because the call site checks `features` independently of the helper and both are
    # load-bearing: one owner can be fixed while the other rots.
    Sabotage(
        suite='python',
        label='the JSON reader guards the parse but not the shape, so a non-object reaches the caller',
        path='pipeline/freshness.py',
        needle='    return parsed if isinstance(parsed, dict) else None',
        replacement='    return parsed',
        guard='test_valid_json_that_is_not_an_OBJECT_is_None',
    ),
    Sabotage(
        suite='python',
        label="the unit's freshness stops checking `features`, so a parseable stub raises KeyError",
        path='pipeline/acquire/download_sim3292.py',
        needle='    if document is None or "features" not in document:',
        replacement='    if document is None:',
        guard='test_a_document_that_PARSES_but_carries_no_features_is_not_fresh',
    ),
    # --- The shared atomic download ------------------------------------------------------------
    # Eight of ten callers test `status.startswith("failed")`. Defaulting the 404 branch ON turns a
    # missing file into a silent success for all of them, and nothing downstream raises.
    Sabotage(
        suite='python',
        label='the atomic download calls a 404 absent by default, so a missing file reads as success',
        path='pipeline/fetch.py',
        needle='                 absent_on_404: bool = False) -> str:',
        replacement='                 absent_on_404: bool = True) -> str:',
        guard='test_a_404_is_a_FAILURE_by_default',
    ),
    # --- The composite recipe's per-body scope ---------------------------------------------------
    # Recording every constant on every body is the natural spelling and produces a recipe that is
    # strictly MORE complete — which is why nothing about the output looks wrong. The cost is
    # invisible: one body's look re-tune restages another's composite for pixels that cannot move.
    Sabotage(
        suite='python',
        label='the recipe records every constant on every body, so one body re-tunes another',
        path='pipeline/tile/shade_planet.py',
        needle='    return values if evaluated else {}',
        replacement='    return values',
        guard='test_moving_it_leaves_the_other_body_alone',
    ),
    # The other direction, and the trap every conditional record has to answer: a gate that is
    # always shut reads as "correctly scoped" and tracks nothing at all.
    Sabotage(
        suite='python',
        label='the gate is always shut, so a layer a body DOES paint reaches no recipe',
        path='pipeline/tile/shade_planet.py',
        needle='    return values if evaluated else {}',
        replacement='    return {}',
        guard='test_the_body_that_paints_it_records_it',
    ),
    # SHADOW_TINT multiplies shaded land on every body. Dropping it leaves a recipe that still
    # looks thorough — it carries the warmth KNOB — while the vector itself moves nothing.
    Sabotage(
        suite='python',
        label='the shadow tint vector leaves the recipe, so a hue edit ships without restaging',
        path='pipeline/tile/shade_planet.py',
        needle='                               {"shadow_tint": list(shade.SHADOW_TINT)}),',
        replacement='                               {}),',
        guard='test_it_is_recorded_while_the_warmth_knob_is_open',
    ),
    # --- The SIM 3292 acquisition recipe -------------------------------------------------------
    # pygeoapi stamps every response with the request time, fixed-width ISO — so two fetches of
    # identical data have the SAME length and a DIFFERENT hash. Hashing the whole document instead
    # of `features` is the natural spelling, imports and type-checks fine, and makes the acquirer
    # re-download on every run forever while a size check agrees nothing is wrong.
    Sabotage(
        suite='python',
        label='the geometry digest covers the whole response, so a timeStamp re-acquires forever',
        path='pipeline/acquire/download_sim3292.py',
        needle='    canonical = json.dumps(document["features"], sort_keys=True, separators=(",", ":"))',
        replacement='    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))',
        guard='test_a_stamp_only_change_reads_as_FRESH_on_disk',
    ),
    # A truncated page is the one failure the response itself cannot report: pygeoapi returns no
    # `numberMatched`, so fewer features reads as a smaller ice cap rather than as a short read.
    Sabotage(
        suite='python',
        label='the unit contract stops counting features, so a truncated page passes as a smaller map',
        path='pipeline/acquire/download_sim3292.py',
        needle='    if len(features) != expected_count:',
        replacement='    if False:',
        guard='test_a_truncated_page_is_refused',
    ),
    # --- the gazetteer acquisition, whose failures are all quiet ----------------------------------
    # A REFUSED ARCHIVE MUST LEAVE THE PREVIOUS EDITION INTACT, and the one-pass version below is
    # what this module actually did until a one-bit flip in `poly.dbf` was measured against it: four
    # `line` members landed before the guard fired, leaving half of one edition beside half of
    # another. It refuses just as loudly either way, which is exactly why nothing would say so.
    Sabotage(
        suite='python',
        label='the gazetteer extracts as it verifies, so a refused archive half-overwrites a good one',
        path='pipeline/acquire/download_nomenclature.py',
        needle='            verified[name] = data\n    for name, data in verified.items():',
        replacement='            verified[name] = data\n    if True:\n      for name, data in verified.items():',
        guard='test_a_bad_digest_writes_NOTHING_not_even_the_members_before_it',
    ),
    # The `.cpg` is the ONE file here this pipeline invents, and it is invisible until someone reads
    # a name: without it GDAL decodes the UTF-8 DBF as Latin-1 and 64 features become mojibake on
    # screen. No digest can vouch for it, because it is not the publisher's.
    Sabotage(
        suite='python',
        label='the gazetteer stops declaring its DBF encoding, so 64 names decode to mojibake',
        path='pipeline/acquire/download_nomenclature.py',
        needle='        codepage.write_text("UTF-8", encoding="ascii")',
        replacement='        codepage.write_text("ISO-8859-1", encoding="ascii")',
        guard='test_the_cpg_is_written_because_the_archive_ships_none',
    ),
    # The 540-degree span is the trap: a republished file normalised into 0-360 passes every
    # digest-shaped and count-shaped check while silently dropping every seam-crossing outline.
    Sabotage(
        suite='python',
        label='the gazetteer stops checking longitude bounds, so a normalised file passes',
        path='pipeline/acquire/download_nomenclature.py',
        needle='    if abs(low - pinned_low) > 0.001 or abs(high - pinned_high) > 0.001:',
        replacement='    if False:',
        guard='test_longitudes_normalised_into_0_360_are_refused',
    ),
    # --- the gazetteer fold, where every failure produces a map that looks finished ----------------
    # THE FOLD IS THE WHOLE POINT OF THE STEP. The source draws seam-crossing features continuing
    # past 360 rather than wrapping, so without this flag 1,044 features carry vertices outside the
    # tile grid and the tiler clips them away — silently, leaving a map that renders perfectly and is
    # missing half its named features.
    Sabotage(
        suite='python',
        label='the gazetteer fold is dropped, so every seam-crossing feature is clipped away',
        path='pipeline/compose/features_geojson.py',
        needle='        "-wrapdateline",\n        "-lco", "RFC7946=YES",',
        replacement='        "-lco", "RFC7946=YES",',
        guard='test_wrapdateline_does_the_fold',
    ),
    # DECLARING THE ANGLES IS NOT THE SAME AS TRANSFORMING THEM, and PROJ only refuses the second
    # while the source SRS still names Mars. Restore ESRI:104905 on the source side and a datum shift
    # is computed between two different planets — coordinates that are plausible, wrong, and carry no
    # error with them.
    Sabotage(
        suite='python',
        label='the gazetteer is reprojected rather than relabelled, shifting Mars through an Earth datum',
        path='pipeline/compose/features_geojson.py',
        needle='"-s_srs", "EPSG:4326", "-t_srs", "EPSG:4326",',
        replacement='"-s_srs", "ESRI:104905", "-t_srs", "EPSG:4326",',
        guard='test_source_and_target_are_the_same_frame',
    ),
    # THE HALF THE FLAGS CANNOT EXPRESS. `-s_srs EPSG:4326` over a GEOGRAPHIC Mars CRS is an identity
    # on the numbers; over a PROJECTED one it reads metres as degrees and collapses the layer without
    # raising. The command is character-identical either way, so only a check over the SOURCE can
    # separate them — and SIM 3292 ships exactly the projected shape one directory away.
    Sabotage(
        suite='python',
        label='the fold stops checking its source is geographic, so a projected one is read as degrees',
        path='pipeline/compose/features_geojson.py',
        needle='    if not declared.startswith("GEOGCS"):',
        replacement='    if False:',
        guard='test_a_projected_source_is_refused',
    ),
    # The container that cost Greenland its outline, reached from the other direction: RFC 7946's own
    # fold MAKES GeometryCollections where -wrapdateline makes none, and a polygon walk that meets one
    # returns nothing for it. Measured on this catalogue: two of them.
    Sabotage(
        suite='python',
        label='the fold stops refusing GeometryCollections, so the Greenland container comes back',
        path='pipeline/compose/features_geojson.py',
        needle='    if "GeometryCollection" in containers:',
        replacement='    if False:',
        guard='test_a_geometrycollection_is_refused_by_name',
    ),
    # The check that notices the fold did not happen AT ALL. Without it the only symptom is features
    # missing from tiles, which nothing on disk reports and no count catches — the file still holds
    # all 1,717.
    Sabotage(
        suite='python',
        label='the fold stops checking its own window, so an unfolded layer passes as folded',
        path='pipeline/compose/features_geojson.py',
        needle='            if not (-180.0001 <= longitude <= 180.0001 and -90.0001 <= latitude <= 90.0001):',
        replacement='            if False:',
        guard='test_a_vertex_outside_the_window_is_refused',
    ),
    # A folded geometry carrying an unfolded longitude PROPERTY is two conventions in one file, and
    # the next reader cannot tell which of the two any given number is. The centres are east-positive
    # 0-360 in the source; they reach the tiles as geometry, folded, or not at all.
    Sabotage(
        suite='python',
        label='the unfolded centres travel as properties, mixing two longitude conventions in one file',
        path='pipeline/compose/features_geojson.py',
        needle='CARRIED_FIELDS = ("name", "clean_name", "type", "origin", "diameter")',
        replacement='CARRIED_FIELDS = ("name", "clean_name", "type", "origin", "diameter", "center_lon")',
        guard='test_the_centres_do_not_travel_as_properties',
    ),
    # --- the feature pyramid ----------------------------------------------------------------------
    # THE CEILING MUST COME FROM THE BODY. Earth's 8 is the tempting literal and it is wrong by one
    # on Mars: the vectors would outlive the raster they overlay, which shows up as an outline
    # tracing a coast that has no pixels under it — visible only to someone who zooms in and looks.
    Sabotage(
        suite='python',
        label="the feature pyramid restates its ceiling, so the vectors outlive Mars's raster",
        path='pipeline/compose/features_pmtiles.py',
        needle='MAX_ZOOM = bodies.MARS.tile_max_zoom',
        replacement='MAX_ZOOM = 8',
        guard='test_max_zoom_is_the_body_field_not_a_literal',
    ),
    # THE DERIVATION'S FRESHNESS, and these four exist because the hole shipped. `derive` skipped on
    # its source's mtime alone, so retuning the shared geometry walk left the GeoJSON untouched; the
    # cut then re-ran under its own changed recipe, produced a byte-identical archive from stale
    # outlines, and stamped the new recipe over it — erasing the only signal anything was wrong.
    # Earth's antimeridian closures survived the fix written to delete them, with every test green.
    Sabotage(
        suite='python',
        label='the archive gate stops asking whether the geometry under it is current',
        # Re-anchored onto `vector_cut`: the two composers' identical gates became one, so this
        # case is about the shared predicate rather than about Earth's copy of it.
        path='pipeline/compose/vector_cut.py',
        needle='    if not derivation_is_stamped(cut):\n        return False',
        replacement='    if False:\n        return False',
        guard='test_a_seam_knob_change_makes_the_ARCHIVE_stale_though_no_mtime_moved',
    ),
    Sabotage(
        suite='python',
        # The producing half. Without it the archive correctly reports itself stale forever and the
        # re-cut never fixes anything, which reads as a pipeline that cannot converge.
        label='the derivation stops rewriting when its recipe moved',
        path='pipeline/compose/vector_cut.py',
        needle='        and derivation_is_stamped(cut)',
        replacement='        and True',
        guard='test_derive_reruns_when_the_stamp_is_stale_and_stamps_what_it_wrote',
    ),
    Sabotage(
        suite='python',
        # Absence must read as STALE. Every store on disk predates this stamp, so a missing file
        # meaning "no objection" is precisely the state in which the guard reaches nothing.
        label='a derivation that was never stamped is taken as current',
        path='pipeline/compose/vector_cut.py',
        # Re-anchored when the sidecar read moved to `freshness.recorded_json`: the old needle
        # named the `.exists() and json.loads(` spelling, which was the whole of what that change
        # deleted. The case is about the STAMP being consulted at all, not about how it is read.
        needle=('    return freshness.recorded_json(cut.derivation_stamp())'
                ' == vector_layers.seam_recipe()'),
        replacement='    return True',
        guard='test_a_derivation_that_was_never_stamped_is_not_believed',
    ),
    Sabotage(
        suite='python',
        # The second body. Mars escaped the original bug by ordering alone — its outlines happened
        # to be derived after the seam rule landed — so its copy of the gate has never been observed
        # to matter, which is exactly the kind of guard that is vacuous without a case.
        label="Earth stops recording the GeoJSON its whole pyramid descends from",
        # The mirror of the case below, and the direction that matters more: Earth's archive is the
        # older and larger of the two, and losing a key re-cuts it exactly as surely as gaining one.
        path='pipeline/compose/countries_pmtiles.py',
        needle='    extra_recipe=lambda: {"source": source_path().name},',
        replacement='    extra_recipe=dict,',
        guard='test_the_key_set_is_exactly_what_the_sidecar_carries',
    ),
    Sabotage(
        suite='python',
        label="Mars records a source key it has no source for, re-cutting its live archive",
        # Its predecessor mutated Mars's own copy of the archive gate, which the merge deleted —
        # one predicate serves both bodies now and the case above covers it. What the merge put at
        # risk instead is the half that is still per body: Earth names the one GeoJSON its pyramid
        # descends from and Mars names none, and either archive re-cuts if that set moves by a key.
        path='pipeline/compose/features_pmtiles.py',
        needle='    extra_recipe=dict,',
        replacement='    extra_recipe=lambda: {"source": "features.geojson"},',
        guard='test_the_key_set_is_exactly_what_the_sidecar_carries',
    ),
    # An identity is what makes a feature hoverable, labellable and joinable. Carrying one anonymously
    # puts a shape in the layer that nothing can ever address — present, painted, and unreachable.
    Sabotage(
        suite='python',
        label='a nameless feature is carried anonymously, putting unreachable shapes in the layer',
        path='pipeline/compose/vector_layers.py',
        needle='    if not isinstance(identity, str) or not identity:',
        replacement='    if False:',
        guard='test_the_first_key_is_the_identity_and_a_feature_without_it_is_dropped',
    ),
    # THE SEAM DROP IS TWO CLAIMS AND BOTH FAIL SILENTLY IN OPPOSITE DIRECTIONS. Too eager, it deletes
    # 57 degrees of Terra Cimmeria's published boundary; too shy, it leaves the straight line down the
    # antimeridian that it exists to remove. Neither shows up as an error, a count, or a byte size —
    # only as a line that is there or a boundary that is not, on one meridian nobody looks at twice.
    Sabotage(
        suite='python',
        label='the seam drop stops asking for a twin, so a real meridian boundary is deleted',
        path='pipeline/compose/vector_layers.py',
        needle='        if any(other_east is not east',
        replacement='        if any(True or other_east is not east',
        guard='test_a_lone_meridian_boundary_is_KEPT',
    ),
    Sabotage(
        suite='python',
        label='the seam band narrows to the exact meridian, missing a cut the publisher left unsnapped',
        path='pipeline/compose/vector_layers.py',
        needle='SEAM_BAND_DEGREES = 1.0',
        replacement='SEAM_BAND_DEGREES = 0.0001',
        guard='test_a_cut_the_publisher_did_not_snap_to_the_meridian_is_still_dropped',
    ),
    Sabotage(
        suite='python',
        label='the degenerate-span guard goes, so every short mirrored coast edge reads as a cut',
        path='pipeline/compose/vector_layers.py',
        needle='        if high - low <= SEAM_TWIN_LATITUDE_EPSILON:\n            continue',
        replacement='        if False:\n            continue',
        guard='test_two_degenerate_spans_do_not_twin_each_other',
    ),
    Sabotage(
        suite='python',
        label='an edge ACROSS the meridian counts as one along it, cutting a feature that never split',
        path='pipeline/compose/vector_layers.py',
        needle='            if start[0] * end[0] <= 0:',
        replacement='            if False:',
        guard='test_an_edge_ACROSS_the_meridian_is_not_one_along_it',
    ),
    # A ring's start point is arbitrary, so this failure MOVES: the gap lands wherever the publisher
    # began the ring, which is nowhere near the seam and reads as a different bug entirely.
    Sabotage(
        suite='python',
        label='the cut ring stops rejoining, leaving a second gap at the ring\'s arbitrary start',
        path='pipeline/compose/vector_layers.py',
        needle='    if ring[0] == ring[-1] and edge_count > 1:',
        replacement='    if False:',
        guard='test_a_cut_mid_ring_REJOINS_the_tail_to_the_head',
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
    # --- The Viking mosaic acquisition recipe -------------------------------------------------------
    # This product is UNCOMPRESSED on a fixed grid, so a re-render that keeps the grid lands on the
    # same byte count whatever the pixels say. That makes the size pin nearly uninformative and the
    # publisher's own md5 the only check that can see one — the reverse of the Mars DEM next door,
    # where the size and the date are all there is to pin.
    Sabotage(
        suite='python',
        label='the preflight drops the publisher digest, so a re-render at the same size passes',
        path='pipeline/acquire/download_viking_mosaic.py',
        needle='        ("md5", published_md5(), EXPECTED_MD5),\n',
        replacement='',
        guard='test_a_rerender_that_keeps_the_size_and_the_date_is_still_caught',
    ),
    # A checksum sidecar is fetched by URL, so a rotted path is the failure that looks like drift:
    # without the name check the digest of some OTHER product is compared to ours and the message
    # blames a republished mosaic.
    Sabotage(
        suite='python',
        label='the checksum sidecar is trusted without checking which product it names',
        path='pipeline/acquire/download_viking_mosaic.py',
        needle='    if len(fields) != 2 or fields[1] != MOSAIC_NAME:',
        replacement='    if len(fields) != 2:',
        guard='test_a_checksum_sidecar_describing_another_product_aborts_saying_so',
    ),
    # NOT INVENTED — the product's own two detached PDS labels declare `PolarRadius = 3376200`, so
    # deleting this check is what a careful reader of the labels would do. The GeoTIFF declares a
    # sphere, and only the sphere makes the EPSG:4326 relabel an identity on the angles.
    Sabotage(
        suite='python',
        label='the flattening check goes, so an ellipsoidal edition shifts every latitude in silence',
        path='pipeline/acquire/download_viking_mosaic.py',
        needle='        if semi_minor is None or abs(semi_minor - semi_major) > 1.0:',
        replacement='        if False:',
        guard='test_an_ellipsoidal_edition_is_refused_and_the_message_names_the_labels',
    ),
    # The plausible upgrade, and the reason the module argues against itself in its own docstring:
    # the MDIM 2.1 colour mosaic is five times finer, sits one key away in the same directory, and is
    # high-pass filtered to REMOVE the regional albedo this source exists to supply.
    Sabotage(
        suite='python',
        label='the mosaic is upgraded to MDIM 2.1, whose albedo was filtered out by construction',
        path='pipeline/acquire/download_viking_mosaic.py',
        needle='MOSAIC_NAME = "Mars_Viking_ClrMosaic_global_925m.tif"',
        replacement='MOSAIC_NAME = "Mars_Viking_MDIM21_ClrMosaic_global_232m.tif"',
        guard='test_the_product_taken_is_the_925_metre_colour_mosaic_and_not_a_finer_one',
    ),
    # A GeoPackage written in place EXISTS and is short for the whole 40-minute merge, and every
    # consumer keys on exactly that -- `layer_producers` lists it as a freshness mtime, so a merge
    # that dies partway is NEWER than the composite reading it and therefore current.
    Sabotage(
        suite='python',
        label='the merge writes its GeoPackage in place, so a crash publishes a short planet',
        path='pipeline/acquire/download_rgi.py',
        needle='    staging = out.with_name(out.name + ".part")',
        replacement='    staging = out',
        guard='test_a_merge_that_dies_partway_leaves_the_previous_geopackage_untouched',
    ),
    # --- The RGI path and layer name have ONE home, and it is the acquirer that writes them ------
    # Both were spelled twice, and a second spelling agrees with the acquirer right up until one of
    # them moves. The layer case is the one `sources()` cannot see: naming the right file is not the
    # same claim as opening the right table inside it.
    Sabotage(
        suite='python',
        label='the glacier burn re-spells the layer name instead of asking its acquirer',
        path='pipeline/look/layer_producers.py',
        needle='                                   gpkg=download_rgi.GPKG, layer=download_rgi.LAYER)',
        replacement='                                   gpkg=download_rgi.GPKG, layer="glaciers")',
        guard='test_the_glacier_burn_reads_the_redirected_path_rather_than_one_bound_at_import',
    ),
    Sabotage(
        suite='python',
        label='the glacier source is re-spelled, so a redirected store is read at the old path',
        path='pipeline/look/layer_producers.py',
        needle='        sources=lambda: (download_rgi.GPKG,),',
        replacement='        sources=lambda: (snow.DATA / "raw/rgi/rgi7_g_3857.gpkg",),',
        guard='test_the_glacier_source_is_the_gpkg_its_own_acquirer_writes',
    ),
    # --- The cap mesh is the resolution limit, and the claim is a RATIO --------------------------
    # The comparison this guards was written as absolute kilometres measured at CAP_EDGE_LAT 78. It
    # went stale when the edge moved to 80 and would have gone stale again at the ratified 84, while
    # the quantity it rests on -- CAP_ELEV_PX / (2 * RINGS) -- never moved at all. The old assertion
    # was `ringKm < 15`, which the mutation below sails through: at 320 rings a ring is 3.47 km.
    Sabotage(
        suite='web',
        label='the mesh outruns the texture it samples, which the old absolute bound could not see',
        path='web/src/lib/polarCaps.ts',
        needle='export const RINGS = 160;',
        replacement='export const RINGS = 320;',
        guard='keeps the mesh coarser than the elevation texture it samples, at whatever edge is served',
    ),
    # A contract field the web can only check with is one the pipeline actually publishes.
    Sabotage(
        suite='python',
        label='caps.json stops stating the elevation texture size, so the web cannot check its mesh',
        path='pipeline/tile/cap_render.py',
        needle='                    "elev_px": CAP_ELEV_PX,\n',
        replacement='',
        guard='test_the_manifest_states_the_elevation_texture_s_size',
    ),
    # --- RGI: the acquisition decides how much of the planet the glacier layer covers ------------
    # THE FAILURE HAS NO SYMPTOM AT ITS OWN STAGE. A region that never downloads leaves a burn with
    # no polygons there, and every downstream check -- file exists, right size, mtime fresh -- is
    # satisfied by it. The map is the only thing that can tell, and it says "bare ground", which is
    # a thing maps legitimately say. Both cases below are the shape that actually shipped.
    Sabotage(
        suite='python',
        label='region 19 is filtered back out at download, so the sub-Antarctic islands go bare',
        path='pipeline/acquire/download_rgi.py',
        needle='    urls = sorted(r["url"] for r in resources if (r.get("format") or "").upper() == "SHP")',
        replacement=('    urls = sorted(r["url"] for r in resources '
                     'if (r.get("format") or "").upper() == "SHP" and "-19_" not in r["url"])'),
        guard='test_the_antarctic_region_is_one_of_them',
    ),
    Sabotage(
        suite='python',
        label='a short portal listing is merged as-is, so the layer quietly covers less than before',
        path='pipeline/acquire/download_rgi.py',
        needle='    missing = sorted(set(range(1, REGION_COUNT + 1)) - found)',
        replacement='    missing = []',
        guard='test_a_region_missing_from_the_portal_is_refused_rather_than_merged_short',
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
        path='pipeline/layers.py',
        needle='                requires_raster="oceanmask", warped_basename="seaice_3857.tif")',
        replacement='                requires_raster=None, warped_basename="seaice_3857.tif")',
        guard='test_sea_ice_without_an_ocean_mask_is_refused',
    ),
    # The two below arrived with the layer table. Deriving the stage views from one table removed the
    # old failure — a stage naming a layer the vocabulary does not have — and left a new one that
    # looks like nothing: a row whose columns are all False, or a required raster spelled wrong.
    Sabotage(
        suite='python',
        label='a layer is read by no stage at all, so declaring it builds nothing',
        path='pipeline/layers.py',
        needle='COASTLINE = Layer("coastline", in_composite=False, in_cap=True, in_block=False,',
        replacement='COASTLINE = Layer("coastline", in_composite=False, in_cap=False, in_block=False,',
        guard='test_the_stage_vocabularies_together_cover_the_whole_one_and_nothing_else',
    ),
    # The block column once carried two cases here, both retired the day the rig gained its ice
    # input: mutating `sea_ice` to `in_block=True` became today's real source, and deriving
    # BLOCK_LAYERS off `in_composite` now yields an IDENTICAL frozenset no test could distinguish.
    # The column's live guard is the flip-back case beside the ground-ratio one, whose test
    # starves the rig's ice arm behaviourally rather than comparing two equal sets.
    # --- the render directory's seam, and the gather both tiers now share ------------------------
    # Every one of these leaves a run that completes and produces a scene. What changes is whether
    # the rig was TOLD what the directory holds or inferred it, which is invisible until the run
    # where a producer skipped a file for a reason other than the region having none.
    Sabotage(
        suite='python',
        label="the gather ignores its caller's vocabulary, handing every stage every declared layer",
        path='pipeline/look/layer_producers.py',
        needle='            if layer.name in vocabulary and layer.name in body.surface_layers]',
        replacement='            if layer.name in body.surface_layers]',
        guard='test_the_vocabulary_is_an_actual_filter',
    ),
    Sabotage(
        suite='python',
        label='the white union folds on a float32 base, narrowing every pixel the compositor blends',
        path='pipeline/look/layer_producers.py',
        needle='    alpha = np.zeros(shape, dtype=float)',
        replacement='    alpha = np.zeros(shape, dtype=np.float32)',
        guard='test_the_base_is_float64_so_no_contribution_is_narrowed',
    ),
    Sabotage(
        suite='python',
        label='a stage declares images it never wrote, so the rig loads a file that is not there',
        path='pipeline/render/render_seam.py',
        needle='    absent = [image for image in named if not (render_dir / image).exists()]',
        replacement='    absent = []',
        guard='test_naming_an_image_that_is_not_there_is_refused',
    ),
    Sabotage(
        suite='python',
        label='a stage rewrites the whole declaration, so a resume erases the stages behind it',
        path='pipeline/render/render_seam.py',
        needle='    stages = _records(render_dir)\n    stages[stage] = named',
        replacement='    stages = {}\n    stages[stage] = named',
        guard='test_re_running_one_stage_leaves_the_others_standing',
    ),
    Sabotage(
        suite='python',
        label='an unfilled render directory reads as an empty one rather than as an unfinished prep',
        path='pipeline/render/render_seam.py',
        needle='    if HEIGHTFIELD not in images:',
        replacement='    if False:',
        guard='test_no_declaration_at_all_raises_rather_than_returning_nothing',
    ),
    # A reader bypasses the owner and spells the filename itself — the defect that reached seven
    # modules before render_seam owned the spellings, reintroduced at one of the exact sites the
    # rename cleaned.
    Sabotage(
        suite='python',
        label='a stage spells a render filename instead of importing its owner',
        path='pipeline/render/lake_mask.py',
        needle='    heightfield_path = render_dir / render_seam.HEIGHTFIELD',
        replacement='    heightfield_path = render_dir / "heightfield.tif"',
        guard='test_no_pipeline_module_spells_a_render_filename',
    ),
    # THE MARGIN FLOOR, WHICH SHIPPED MISSING AND DREW A GRID OVER EVERY OCEAN ON EARTH. A Cycles
    # frame is dark for about thirty pixels at its border; a margin is discarded, so any block with
    # one throws that away, and a block rendered to its exact footprint delivers it. Both branches
    # get a case because the defect was in the one that BYPASSES the law.
    Sabotage(
        suite='python',
        label='a block is sized by its OWN relief, so a flat one beside a mountain gets the floor',
        path='pipeline/block_plan.py',
        needle='    reach = haloed(relief)',
        replacement='    reach = relief',
        guard='test_a_flat_block_beside_a_mountain_inherits_the_mountains_margin',
    ),
    Sabotage(
        suite='python',
        label='the shadow law drops its floor, so flat ground plans a plane inside its own frame',
        path='pipeline/block_plan.py',
        needle='    return min(max(quantised, DENOISE_BAND_PX), CONTEXT_CEILING_PX)',
        replacement='    return min(quantised, CONTEXT_CEILING_PX)',
        guard='test_flat_ground_still_gets_a_plane_that_covers_the_traced_rectangle',
    ),
    # THE RECIPE GOING SHORT, which is the failure that bit three times in one session and is
    # silent every time: the recipe text does not move, the generation stamp still reads as
    # current, and the next resume keeps blocks rendered under a rule that no longer exists.
    Sabotage(
        suite='python',
        label='the recipe stops recording the contexts, so a law change restages nothing at all',
        path='pipeline/tile/block_render.py',
        needle='        "contexts": context_census(blocks),',
        replacement='        "contexts": {},',
        guard='test_a_context_moving_moves_the_recipe_and_a_law_change_that_moves_none_does_not',
    ),
    # THE BLOCK RUNNER. Every case below is silent: the run completes, the gates stay green, and
    # what is wrong is either a planet nobody re-rendered or a planet rendered from the wrong
    # neighbourhood. None of them raise, and the pixels look plausible in all of them.
    Sabotage(
        suite='python',
        label="the resume's generation test becomes is_stale, which calls every healthy run stale",
        path='pipeline/tile/block_render.py',
        needle='    return stamp.exists() and freshness.newest_mtime(*deps) <= stamp.stat().st_mtime',
        replacement='    return stamp.exists() and not freshness.is_stale(markers, *deps)',
        guard='test_a_directory_written_into_after_its_stamp_is_still_current',
    ),
    Sabotage(
        suite='python',
        label='a new generation leaves the mosaic stamped, so the cut can run on half a producer',
        path='pipeline/tile/block_render.py',
        needle='    freshness.done_marker(mosaic).unlink(missing_ok=True)\n'
               '    shutil.rmtree(markers, ignore_errors=True)',
        replacement='    shutil.rmtree(markers, ignore_errors=True)',
        guard='test_the_mosaics_completion_marker_is_removed',
    ),
    Sabotage(
        suite='python',
        label='the block markers stop following their mosaic, so an A/B resumes over production',
        path='pipeline/tile/block_render.py',
        needle='    return mosaic.with_name(f"{mosaic.stem}_blocks")',
        replacement='    return mosaic.parent / "planet_blocks"',
        guard='test_two_mosaics_do_not_share_a_marker_directory',
    ),
    Sabotage(
        suite='python',
        label="the raytrace inherits the composite's hillshade as a dependency it never reads",
        path='pipeline/tile/block_render.py',
        needle='    return (work / shade_planet.HEIGHT_3857, work / shade_planet.OCEAN_3857,',
        replacement='    return (work / "hs_3857.tif", work / shade_planet.HEIGHT_3857,\n'
                    '            work / shade_planet.OCEAN_3857,',
        guard='test_the_hillshade_is_not_a_raytrace_dependency',
    ),
    Sabotage(
        suite='python',
        label='the crop takes the context instead of the band, writing the wrong ground into the mosaic',
        path='pipeline/tile/block_render.py',
        needle=('    band, edge, traced = block_plan.DENOISE_BAND_PX, block.size_px, '
                'block.traced_edge_px'),
        replacement='    band, edge, traced = block.context_px, block.size_px, block.traced_edge_px',
        guard='test_the_denoise_band_is_cut_back_off',
    ),
    # The base grid is the one mutation here whose damage never raises, never logs and never
    # changes a file size: `MAX_SUBDIVISIONS` caps micropolygons PER PATCH, so a single quad silently
    # dices a 4,096-block's plane at half its pixels and delivers a slightly soft planet.
    Sabotage(
        suite='python',
        label='the plane goes back to one patch, so every block dices at half its own resolution',
        path='pipeline/render/scene_build.py',
        needle='    return max(1, math.ceil(span_px / 2 ** MAX_SUBDIVISIONS))',
        replacement='    return 1',
        guard='test_the_base_grid_covers_every_context_width_on_every_body',
    ),
    # THE PER-CALLER WIRING, three mutations, and they fail in opposite directions. Flipping the
    # DEFAULT breaks every large hero outright (OptiX cannot build the BVH at 67M micropolygons);
    # dropping the block's OPT-IN silently halves the planet's dicing. Both are the cheap version of
    # the change -- one constant instead of one argument -- which is the shape that has now caught
    # this rig twice, the denoiser being the first.
    Sabotage(
        suite='python',
        label='the base grid becomes the default, so every large hero fails to build its BVH',
        path='pipeline/render/scene_build.py',
        needle='    ap.add_argument("--base-grid", choices=("single", "fitted"), default="single",',
        replacement='    ap.add_argument("--base-grid", choices=("single", "fitted"), default="fitted",',
        guard='test_the_default_the_hero_inherits_is_the_single_quad',
    ),
    Sabotage(
        suite='python',
        label='the block runner stops asking for the base grid, so the planet dices at half',
        path='pipeline/tile/block_render.py',
        needle=('            "--denoise-device", BLOCK_DENOISE_DEVICE,\n'
                '            "--base-grid", BLOCK_BASE_GRID]'),
        replacement='            "--denoise-device", BLOCK_DENOISE_DEVICE]',
        guard='test_the_block_runner_opts_into_the_base_grid_too',
    ),
    Sabotage(
        suite='python',
        label='the recipe stops recording the dicing, so a resumed pass blends both into one mosaic',
        path='pipeline/tile/block_render.py',
        needle='        "base_grid": BLOCK_BASE_GRID,\n',
        replacement='',
        guard='test_the_recipe_records_the_base_grid',
    ),
    Sabotage(
        suite='python',
        label='the mask writer goes back to 8 bits, terracing the sea floor under the ice alpha',
        path='pipeline/render/prep_block.py',
        needle='MASK_FULL_SCALE = 65535.0',
        replacement='MASK_FULL_SCALE = 255.0',
        guard='test_a_quantised_alpha_does_not_terrace_the_sea_floor_past_one_ground_pixel',
    ),
    Sabotage(
        suite='python',
        label='the recipe stops recording the mask depth, so no rendered block restages for it',
        path='pipeline/tile/block_render.py',
        needle='        "mask_full_scale": prep_block.MASK_FULL_SCALE,\n',
        replacement='',
        guard='test_the_recipe_records_the_mask_depth',
    ),
    Sabotage(
        suite='python',
        label='the block recipe stops recording what its masks were graded with',
        path='pipeline/tile/block_render.py',
        needle='        **layer_producers.constants_for(body, layers.BLOCK_LAYERS, painted=False),\n',
        replacement='',
        guard='test_the_ice_softening_moving_moves_the_recipe',
    ),
    Sabotage(
        suite='python',
        label="the block recipe records the producers' whites, which the rig paints without",
        path='pipeline/tile/block_render.py',
        needle='        **layer_producers.constants_for(body, layers.BLOCK_LAYERS, painted=False),',
        replacement='        **layer_producers.constants_for(body, layers.BLOCK_LAYERS, painted=True),',
        guard='test_a_white_the_RIG_paints_from_does_not_reach_the_recipe',
    ),
    Sabotage(
        suite='python',
        label='a producer grades with a constant and declares none of it',
        path='pipeline/look/layer_producers.py',
        # An early return rather than `{} or {...}`, which was the first attempt and is a NO-OP:
        # an empty dict is falsy, so `or` hands back the very dict it was meant to suppress.
        needle='    return {"snow_ramp_lat_lo": snow.RAMP_LAT_LO,',
        replacement='    return {}\n    return {"snow_ramp_lat_lo": snow.RAMP_LAT_LO,',
        guard='test_every_constant_an_in_block_producer_grades_with_reaches_the_recipe',
    ),
    Sabotage(
        suite='python',
        label='the composite stops recording the whites it paints with, keeping only the grading',
        path='pipeline/look/layer_producers.py',
        needle='        if painted:\n            recorded.update(producer.paint_recipe())',
        replacement='        if False:\n            recorded.update(producer.paint_recipe())',
        guard='test_the_grading_and_painting_split_leaves_the_composite_recording_BOTH_halves',
    ),
    Sabotage(
        suite='python',
        label='the plane span is read off the heightfield, so a hero under-dices and a block over-dices',
        path='pipeline/render/scene_build.py',
        needle=('    pixels_per_unit = max(frame["res_x"], frame["res_y"]) '
                '/ frame["ortho_scale"]'),
        replacement='    pixels_per_unit = max(frame["res_x"], frame["res_y"]) / 2.0',
        guard='test_the_plane_span_is_the_planes_and_not_the_heightfields',
    ),
    # The frame CHECK and the crop OFFSET are separate mutations because they fail differently and
    # only one of them changes a shape. Cropping a plane-sized frame by the band yields a square of
    # exactly the right size, so the assertion that used to live on `crop.shape` passed through it.
    Sabotage(
        suite='python',
        label='the frame size is checked on the crop instead of the render, so an unnarrowed camera passes',
        path='pipeline/tile/block_render.py',
        needle='    if frame.shape[1:] != (traced, traced):',
        replacement='    if frame.shape[1:] < (traced, traced):',
        guard='test_a_frame_the_size_of_the_PLANE_rather_than_the_traced_rectangle_raises',
    ),
    Sabotage(
        suite='python',
        label='--limit is read for truthiness, so limit 0 starts the whole planet instead of none',
        path='pipeline/tile/block_render.py',
        needle='        if limit is not None and rendered >= limit:',
        replacement='        if limit and rendered >= limit:',
        guard='test_limit_zero_renders_nothing_at_all',
    ),
    Sabotage(
        suite='python',
        label='completion is asked of the selection, so --only on one block stamps a whole planet',
        path='pipeline/tile/block_render.py',
        needle='    complete = all((markers / block_name(block)).exists() for block in blocks)',
        replacement='    complete = all((markers / block_name(block)).exists() for block in selected)',
        guard='test_a_named_subset_never_stamps_even_when_all_of_it_renders',
    ),
    Sabotage(
        suite='python',
        label='the run stops checking its warped inputs, so a missing stage reads as a dead GPU',
        path='pipeline/tile/block_render.py',
        needle='    missing = [path.name for path in required if not path.exists()]',
        replacement='    missing = []',
        guard='test_a_missing_heightfield_stops_the_run_by_name',
    ),
    # The rig's own recipe going short by one constant. The planet keeps rendering, the gates keep
    # passing, and a look change made through that constant restages nothing at all.
    Sabotage(
        suite='python',
        label='the rig recipe forgets a constant, so a look change leaves the planet reading fresh',
        path='pipeline/render/scene_build.py',
        needle='        "SAMPLES": SAMPLES,',
        replacement='',
        guard='test_every_module_constant_is_in_the_recipe',
    ),
    Sabotage(
        suite='python',
        label='the block width drops the body ground ratio, which is exactly 1.0 on Earth',
        path='pipeline/render/prep_block.py',
        needle='    return (mercator_width * math.cos(math.radians(mid_latitude_deg(window, body)))\n'
               '            * bodies.ground_metres_per_mercator_unit(body))',
        replacement='    return mercator_width * math.cos(math.radians(mid_latitude_deg(window, body)))',
        guard='test_the_width_matches_the_closed_form_including_the_body_ratio',
    ),
    Sabotage(
        suite='python',
        label='the per-row correction is dropped, which is what ships today',
        path='pipeline/render/prep_block.py',
        needle='    return np.cos(np.radians(mid_latitude_deg(window, body))) / np.cos(np.radians(latitudes))',
        replacement='    return np.ones(window.height)',
        guard='test_one_metre_of_elevation_displaces_the_bodys_exaggeration_on_every_row',
    ),
    Sabotage(
        suite='python',
        label='the per-row correction is inverted, so the poles flatten instead of rising',
        path='pipeline/render/prep_block.py',
        needle='    return np.cos(np.radians(mid_latitude_deg(window, body))) / np.cos(np.radians(latitudes))',
        replacement='    return np.cos(np.radians(latitudes)) / np.cos(np.radians(mid_latitude_deg(window, body)))',
        guard='test_one_metre_of_elevation_displaces_the_bodys_exaggeration_on_every_row',
    ),
    Sabotage(
        suite='python',
        label='the two mids disagree, which is uniform and therefore invisible to every seam',
        path='pipeline/render/prep_block.py',
        needle='    rows = np.arange(window.row_off, window.row_off + window.height, dtype=np.float64)',
        replacement='    window = Window(window.col_off, window.row_off + 1, window.width, window.height)\n'
                    '    rows = np.arange(window.row_off, window.row_off + window.height, dtype=np.float64)',
        guard='test_one_metre_of_elevation_displaces_the_bodys_exaggeration_on_every_row',
    ),
    Sabotage(
        suite='python',
        label='the writer re-derives the law instead of calling it, so every case above lies CAUGHT',
        path='pipeline/render/prep_block.py',
        needle='    column = row_scale(window, body).reshape(-1, 1).astype(np.float32)',
        replacement='    _rows = np.arange(window.row_off, window.row_off + window.height, dtype=np.float64)\n'
                    '    _lat = np.array([block_plan.row_latitude_deg(float(r), body) for r in _rows])\n'
                    '    column = (np.cos(np.radians(mid_latitude_deg(window, body)))\n'
                    '              / np.cos(np.radians(_lat))).reshape(-1, 1).astype(np.float32)',
        guard='test_the_column_equals_the_law_to_the_float32_it_is_stored_as',
    ),
    Sabotage(
        suite='python',
        label='the written column is flipped, which doubles the error and looks like a correction',
        path='pipeline/render/prep_block.py',
        needle='    column = row_scale(window, body).reshape(-1, 1).astype(np.float32)',
        replacement='    column = row_scale(window, body)[::-1].reshape(-1, 1).astype(np.float32)',
        guard='test_it_is_written_top_down_so_row_zero_is_the_northernmost',
    ),
    Sabotage(
        suite='python',
        label='the column is sized to the delivered block, stretching the correction over the context',
        path='pipeline/render/prep_block.py',
        needle='                       height=window.height, count=1, dtype="float32",\n'
               '                       crs="EPSG:3857", transform=transform, **GTIFF_CREATE) as tif:',
        replacement='                       height=block_plan.RENDER_BLOCK_PX, count=1, dtype="float32",\n'
                    '                       crs="EPSG:3857", transform=transform, **GTIFF_CREATE) as tif:',
        guard='test_it_is_one_pixel_wide_and_as_tall_as_the_PLANE',
    ),
    Sabotage(
        suite='python',
        label='the context is sized at the block centre, which is right only while the defect exists',
        path='pipeline/block_plan.py',
        needle='        nxt = context_for(max_relief_m, poleward_sizing_latitude(row0, context, body),',
        replacement='        nxt = context_for(max_relief_m, row_latitude_deg(row0 + RENDER_BLOCK_PX / 2.0, body),',
        guard='test_no_block_row_is_narrower_than_sizing_at_its_centre',
    ),
    Sabotage(
        suite='python',
        label='the sizing latitude takes the north edge, narrowing every southern block',
        path='pipeline/block_plan.py',
        needle='    return north if abs(north) >= abs(south) else south',
        replacement='    return north',
        guard='test_the_two_hemispheres_are_sized_alike',
    ),
    Sabotage(
        suite='python',
        label='a layer requires a planet raster no producer can emit, and nothing spell-checks it',
        path='pipeline/layers.py',
        needle='                   requires_raster="watermask", warped_basename="lakedepth_3857.tif")',
        replacement='                   requires_raster="watermsk", warped_basename="lakedepth_3857.tif")',
        guard='test_every_required_raster_is_one_the_planet_seam_can_emit',
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
        needle='    return (work / HEIGHT_3857, hs, work / OCEAN_3857, work / WATER_3857,',
        replacement='    return (work / HEIGHT_3857, hs,',
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
        path='pipeline/look/palette.py',
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
        path='pipeline/look/palette.py',
        needle='        if look.sea is None:\n            raise ValueError(\n                "this look draws no sea',
        replacement='        if False:\n            raise ValueError(\n                "this look draws no sea',
        guard='test_a_look_with_no_sea_refuses_to_resolve_one',
    ),
    Sabotage(
        suite='python',
        # A body with no look inherits Earth's rather than raising -- the one-line "friendlier"
        # change that turns a hard stop into a whole plausible pyramid in another planet's colours.
        label='an unregistered body falls back to Earth\'s ramp instead of raising',
        path='pipeline/look/palette.py',
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
        path='pipeline/look/palette.py',
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
        path='pipeline/look/palette.py',
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
        path='pipeline/look/palette.py',
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
        path='web/src/lib/aboutContent.ts',
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
        path='pipeline/look/palette.py',
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
        path='pipeline/look/palette.py',
        needle='        if self.origin_m == self.extreme_m:',
        replacement='        if False:',
        guard='test_a_zero_width_ramp_is_refused_at_declaration',
    ),
    # The third copy of the assumption, in the module a type checker cannot connect to the other two.
    # Its own guard could not see this until it stopped comparing against a literal zero.
    Sabotage(
        suite='python',
        label="the shared rig restates the datum instead of reading the ramp's own origin",
        path='pipeline/render/scene_build.py',
        needle='        land_range=(look.land.origin_m, look.land.extreme_m),',
        replacement='        land_range=(0.0, look.land.extreme_m),',
        guard='test_the_origin_is_READ_and_not_coincidentally_zero',
    ),
    # Both below fail toward a planet that renders: a sea Mars never asked for, and a mask file the
    # block prep was never going to write. Neither raises, and Earth is unaffected by either.
    Sabotage(
        suite='python',
        label='every look inherits Earth\'s sea, so a body that draws none gets one anyway',
        path='pipeline/render/scene_build.py',
        needle='    sea = look.sea\n',
        replacement='    sea = look.sea or palette.EARTH_LOOK.sea\n',
        guard='test_mars_gets_no_sea_ramp',
    ),
    Sabotage(
        suite='python',
        label='the rig asks every body for an oceanmask, including the ones with no sea',
        path='pipeline/render/scene_build.py',
        needle='            if look.sea is not None or name != SEA_IMAGE}',
        replacement='            if True}',
        guard='test_the_oceanmask_is_not_asked_for',
    ),
    # The scene and its frame are the two places one fact lives, so one of them has to be
    # executable. Absent the check a wrong flag draws another planet's ramps and nothing raises.
    Sabotage(
        suite='python',
        label='a frame written for another body is rendered anyway, in this one\'s ramps',
        path='pipeline/render/scene_build.py',
        needle='    if frame["body"] != args.body:',
        replacement='    if False:',
        guard='test_a_flag_disagreeing_with_the_frame_stops_the_render',
    ),
    # --- The exaggeration belongs to the body ---------------------------------------------------
    # `scene_numbers` is the hero path's seam AND the block prep's, and the block prep runs on both
    # planets. Earth's constant here is exactly 1.0's cousin: correct where it was written, and a
    # flatter planet with no error anywhere else.
    Sabotage(
        suite='python',
        label="the render seam re-imports Earth's exaggeration instead of taking the body's",
        path='pipeline/render/render_prep.py',
        needle='        displacement_scale=exaggeration / (extent_w_m / 2.0),',
        replacement='        displacement_scale=15.0 / (extent_w_m / 2.0),',
        guard='test_mars_displaces_at_its_own_number_and_not_earths',
    ),
    # frame.json is never overwritten, so a pin can only be checked by regenerating beside it. A
    # tolerated stray or missing key makes that comparison fail for a reason that is not geometry.
    Sabotage(
        suite='python',
        label='frame.json tolerates a missing key, writing null where a number belongs',
        path='pipeline/render/render_prep.py',
        needle='    if missing or unknown:',
        replacement='    if unknown:',
        guard='test_a_missing_key_is_refused_rather_than_written_as_null',
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
        needle='    return public_root() / stage / body.path_prefix',
        replacement='    return paths.DATA / "web/public" / stage / body.path_prefix',
        guard='test_served_assets_follow_the_checkout_not_the_data_store',
    ),
    # The prefix moves to the wrong side of the stage: Earth is unaffected (its prefix is empty), so
    # this ships green and only a second body finds its caps published at the wrong URL.
    Sabotage(
        suite='python',
        label='the caps prefix is applied above the stage, publishing a second body at the wrong URL',
        path='pipeline/bodies.py',
        needle='    return public_root() / stage / body.path_prefix',
        replacement='    return public_root() / body.path_prefix / stage',
        guard='test_a_second_body_publishes_under_its_own_segment',
    ),
    # The served root stops asking `paths.ROOT` and re-derives the checkout itself — which is what a
    # module constant did, and what any "remove the indirection" tidy would restore. It is invisible
    # in an ordinary run, because on an unrelocated checkout the two answers are the same path; it
    # bites only where a fixture redirects the root and therefore believes it is isolated, and its
    # cost is test output written into web/public/, which the site build copies into dist/.
    Sabotage(
        suite='python',
        label='the served root re-derives the checkout instead of following paths.ROOT',
        path='pipeline/bodies.py',
        needle='    return paths.ROOT / "web/public"',
        replacement='    return Path(__file__).resolve().parents[1] / "web/public"',
        guard='test_both_roots_follow_a_redirect_so_a_fixture_can_isolate_every_write',
    ),
    # --- The body is required --------------------------------------------------------------------
    # Both mutations restore a silent Earth assumption. Neither raises, neither changes a pixel today,
    # and both mean a Mars pass would quietly shade with Earth's geometry into Earth's directories —
    # the one failure this whole workstream exists to make impossible.
    Sabotage(
        suite='python',
        label='--body regains a default, so a pass with no planet named silently means Earth',
        path='pipeline/tile/planet_pass.py',
        needle='    ap.add_argument("--body", required=True,',
        replacement='    ap.add_argument("--body", default="earth",',
        guard='test_omitting_the_body_is_an_error_rather_than_an_assumption',
    ),
    # The override stops being honoured, so a look A/B silently writes over the production tree.
    Sabotage(
        suite='python',
        label='--out stops overriding the body default, so an A/B overwrites the live pyramid',
        path='pipeline/tile/planet_pass.py',
        needle='    return args.out if args.out is not None else bodies.work_dir(resolve_body(args), "planet_tiles")',
        replacement='    return bodies.work_dir(resolve_body(args), "planet_tiles")',
        guard='test_an_explicit_out_still_wins_over_the_body_s_default',
    ),
    # --- The producer choice: dispatch, refusal, and the stamp that makes a switch visible -------
    # Every one of these is silent in production. The dispatcher runs SOME producer, the deps lists
    # still gate on real files, and the pass prints its usual stage lines throughout.
    Sabotage(
        suite='python',
        # The registry drops a producer the vocabulary still allows. A body naming it then falls
        # through the `KeyError` into the refusal — which reads as a typo rather than as a missing
        # implementation, and points the reader at `bodies.py` instead of at this file.
        label='the dispatch registry stops answering for a producer the vocabulary allows',
        path='pipeline/tile/planet_pass.py',
        needle='    "raytrace": Producer(_raytrace, block_render.rig_seam_refusals),\n',
        replacement='',
        guard='test_the_registry_and_the_vocabulary_are_the_same_set',
    ),
    Sabotage(
        suite='python',
        # ITEM 4's ORDERING. Moving the refusal after the warp reads as grouping the reads together
        # and is the whole defect: the answer never depended on the warp, so a wrongly-declared body
        # paid a full Earth height warp -- 6:49, on every run and every resume -- to hear the same
        # no. The producer still refuses, so nothing renders wrong; it just costs the expensive
        # shared stage first, which is exactly the failure `check_inputs` exists to prevent one
        # tier down.
        label='the producer refusal moves after the warp, so a bad declaration costs 6 49 to learn',
        path='pipeline/tile/planet_pass.py',
        needle='    refusals = cannot_run(body, rasters)\n',
        replacement='',
        guard='test_the_refusal_comes_before_the_warp',
    ),
    Sabotage(
        suite='python',
        # The raytrace producer stops answering who may choose it. Reads as removing a redundant
        # check -- `check_inputs` asks the same question inside the producer -- and re-opens the gap
        # the pass exists to close: the registry can then hold a body/producer pair that cannot run,
        # and nothing says so until a night has been spent warping for it.
        label='the raytrace claims it runs on any seam, so an impossible pairing is never refused',
        path='pipeline/tile/planet_pass.py',
        needle='    "raytrace": Producer(_raytrace, block_render.rig_seam_refusals),',
        replacement='    "raytrace": Producer(_raytrace, _composite_runs_on_any_seam),',
        guard='test_a_seam_that_cannot_feed_the_rig_refuses_the_raytrace',
    ),
    Sabotage(
        suite='python',
        # The tidy-looking version, and the most expensive mutation in this block: an unknown
        # producer quietly composites. A night of GPU is not spent, it is simply never started, and
        # the pass reports a complete planet made by a producer nobody chose.
        label='an unknown producer falls back to the composite instead of refusing',
        path='pipeline/tile/planet_pass.py',
        needle='        return PRODUCERS[body.planet_producer]\n',
        replacement='        return PRODUCERS.get(body.planet_producer, _composite)\n',
        guard='test_a_producer_nothing_runs_is_refused_by_name',
    ),
    Sabotage(
        suite='python',
        # Reads as tidying an odd entry out of a list of warp sources. It is the entry that is not
        # one, and dropping it lets a composite skip over a raytraced raster reporting it fresh.
        label='the composite drops the producer stamp, so it reads raytraced pixels as its own',
        path='pipeline/tile/shade_planet.py',
        needle='            *(layer.warped_in(work) for layer in layers.WARPED_LAYERS), params,\n'
               '            producer_seam.stamp_path(work))',
        replacement='            *(layer.warped_in(work) for layer in layers.WARPED_LAYERS), params)',
        guard='test_the_composite_names_it',
    ),
    Sabotage(
        suite='python',
        # The same edit on the other side, and the direction that publishes composited pixels under
        # a raytrace recipe. Both halves are needed: one list naming it detects nothing.
        label='the raytrace drops the producer stamp, so it reads composited pixels as its own',
        path='pipeline/tile/block_render.py',
        needle='            *(layer.warped_in(work) for layer in layers.WARPED_LAYERS), recipe,\n'
               '            producer_seam.stamp_path(work))',
        replacement='            *(layer.warped_in(work) for layer in layers.WARPED_LAYERS), recipe)',
        guard='test_the_raytrace_names_it',
    ),
    Sabotage(
        suite='python',
        # The stamp is written unconditionally, which looks simpler and is the one change that
        # inverts its whole purpose: every pass then moves its mtime, so every pass restages the
        # planet it was about to skip. Correct output, at a full re-render each time.
        label='the producer stamp is rewritten every pass, so an unchanged body restages',
        path='pipeline/tile/producer_seam.py',
        needle='    return freshness.write_if_changed(stamp_path(work),\n'
               '                                      json.dumps({"producer": producer}, indent=2) + "\\n")',
        replacement='    stamp = stamp_path(work)\n'
                    '    stamp.write_text(json.dumps({"producer": producer}, indent=2) + "\\n")\n'
                    '    return stamp',
        guard='test_an_unchanged_producer_does_not_move_the_mtime',
    ),
    Sabotage(
        suite='python',
        # THE PLACEMENT, WHICH IS WHAT THE FIRST VERSION GOT WRONG. Moving the declaration back to
        # the dispatcher reads as tidying: the pass knows the producer, so why should the producer
        # repeat it? Because `block_render.main` is a second shipped door that never reaches the
        # dispatcher, and an ABSENT stamp scores 0.0 in `newest_mtime` — so the dependency both
        # recipes name contributes nothing and the whole mechanism goes inert.
        label='only the dispatcher declares the producer, so the runner s own door bypasses it',
        path='pipeline/tile/block_render.py',
        needle='    producer_seam.declare(work, "raytrace")\n',
        replacement='',
        guard='test_the_raytrace_door_records_the_raytrace',
    ),
    Sabotage(
        suite='python',
        # Recording the BODY's answer instead of the producer that ran. Reads more principled --
        # the registry is the source of truth -- and is the one value guaranteed to agree with a
        # registry the pixels disagree with, which is precisely the state that reads as fresh.
        label='the stamp records the body s declared producer rather than the one that ran',
        path='pipeline/tile/block_render.py',
        needle='    producer_seam.declare(work, "raytrace")',
        replacement='    producer_seam.declare(work, body.planet_producer)',
        guard='test_it_declares_the_producer_that_RAN_not_the_one_the_body_asked_for',
    ),
    Sabotage(
        suite='python',
        # The seam check stops refusing anything. Mars then passes every raster check — it is not
        # asked for a file it never had — and fails inside Blender on the eighth block, under the
        # message that says the GPU is gone about a rig input no block on that body can carry.
        label='the rig-seam check accepts every planet, so a bodyless image fails as a dead GPU',
        path='pipeline/tile/block_render.py',
        needle='    return [] if "watermask" in rasters else [render_seam.INLANDLAKE, render_seam.RIVER]',
        replacement='    return []',
        guard='test_the_refusal_names_both_images_no_block_can_carry',
    ),
    Sabotage(
        suite='python',
        # A validity test in place of a producer test: it reads as the stricter check and can never
        # fire, because the vocabulary is exactly where the field's values come from.
        label='the knob refusal checks the vocabulary instead of the producer, so it never fires',
        path='pipeline/tile/planet_pass.py',
        needle='    if overrides and body.planet_producer != "composite":',
        replacement='    if overrides and body.planet_producer not in bodies.PLANET_PRODUCERS:',
        guard='test_a_raytraced_body_refuses_one',
    ),
    Sabotage(
        suite='python',
        # The completion test always says yes, which is invisible on the composite path — it
        # finishes or it raises — and cuts a pyramid from a part-rendered planet on the other.
        label='a part-rendered planet reads as complete, so the cut ships a pyramid with holes',
        path='pipeline/tile/planet_pass.py',
        needle='    return not is_stale(planet_tif)',
        replacement='    return True',
        guard='test_a_raster_with_no_marker_is_incomplete',
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
        needle='<html\n  lang="en"\n  class="no-js"\n  data-body={body}\n  data-page-role={pageRole}\n  data-globe-route={routes.globe}\n  data-lite-route={routes.lite}\n>',
        replacement='<html\n  lang="en"\n  class="no-js"\n  data-page-role={pageRole}\n  data-globe-route={routes.globe}\n  data-lite-route={routes.lite}\n>',
        guard='renders data-body on <html>, server-side and unconditionally',
    ),
    # The attribute goes on the wrong element. `:root` IS <html>, so this compiles, renders, and
    # silently matches nothing — a mistake no type can catch, since both spellings are valid Astro.
    Sabotage(
        suite='web',
        label='data-body lands on <body>, where the token block cannot see it',
        path='web/src/layouts/Base.astro',
        needle='<html\n  lang="en"\n  class="no-js"\n  data-body={body}\n  data-page-role={pageRole}\n  data-globe-route={routes.globe}\n  data-lite-route={routes.lite}\n>',
        replacement='<html\n  lang="en"\n  class="no-js"\n  data-page-role={pageRole}\n  data-globe-route={routes.globe}\n  data-lite-route={routes.lite}\n>\n  <body data-body={body}>',
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
        # The declaration alone, never the comment beside it — a prose edit broke this needle once.
        needle='  --accent: #3a6e7d;',
        replacement='  --accent: #3a6f7d;',
        guard="computes the descriptor's colour for every body the site knows",
    ),
    # The prop gains a default, which is what makes `astro check` stop asking. The page that forgets
    # to name its body then renders in Earth's chrome and passes every gate.
    Sabotage(
        suite='web',
        label='the body prop gains a default, so a page that names no planet quietly gets Earth',
        path='web/src/layouts/Base.astro',
        needle='  body,\n  pageRole,\n} = Astro.props;',
        replacement='  body = "earth",\n  pageRole,\n} = Astro.props;',
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
        # gets rendered, so the browser flag is only ever the second half of that fact. Dropping it
        # here leaves both discs rendered, uploaded and never fetched — and the pole does not go
        # blank, it keeps `shade_planet.CAP_RGB`, the flat pale plug the textures exist to cover.
        # No 404, no console line, just a colour that reads as a decision.
        #
        # The needle carries the line BELOW it because both bodies answer `true` now; `hasBorders`
        # is the nearest fact that will not be rewritten by anything touching caps.
        label="Mars stops fetching the polar caps the pipeline renders",
        path='web/src/lib/bodies.ts',
        needle='    rendersPolarCaps: true,\n    // Mars has no nations.',
        replacement='    rendersPolarCaps: false,\n    // Mars has no nations.',
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
        # Named against the ANTI-VACUITY assertion, and it did not used to be. The coherence rule —
        # heroes need a countries pyramid, since a map click hit-tested against the countries MVT is
        # the only way a panel opens — stopped being reachable from this file the day Mars published
        # vectors: Mars now HAS the pyramid, so claiming heroes is coherent and only the flag's own
        # both-answers check refuses it. Falsifying the coherence rule means mutating `PUBLISHED`.
        label='Mars claims heroes, and the flag stops varying at all',
        path='web/src/lib/bodies.ts',
        needle='    hasHeroes: false,',
        replacement='    hasHeroes: true,',
        guard='holds both answers to every flag, so none of them is a constant in disguise',
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
        # THIS USED TO DROP `descriptor.rendersPolarCaps` — the registry stops being consulted and
        # only the flags decide. That mutation is no longer falsifiable and the case is re-aimed
        # rather than deleted, because the reason is worth meeting here: every registered body
        # renders caps now, so a version that never asks the registry returns the same answer as one
        # that does, on every planet, for every flag combination. Nothing can witness it. It becomes
        # catchable again the day a body declares no caps, and the case to restore is this comment.
        #
        # `?bare` is what still gates the field, so that is what this now mutates.
        label='?bare stops stripping the polar caps, so the raster baseline keeps an overlay',
        path='web/src/lib/globeSubsystems.ts',
        needle='    polarCaps: descriptor.rendersPolarCaps && !bare && !flags.has("nocaps"),',
        replacement='    polarCaps: descriptor.rendersPolarCaps && !flags.has("nocaps"),',
        guard='strips every body down to the same floor, whatever that body publishes',
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
        # The revert that looks like a simplification: the parameter is threaded through to reach a
        # constant this module already exports, so reading it directly is one fewer hop and passes
        # every Earth assertion by construction. It is silent until a second body cuts a shallower
        # pyramid, and then the browser asks for zooms nobody packed.
        label='the DEM source reads this module\'s ceiling instead of the archive it was handed',
        path='web/src/lib/terrainSource.ts',
        needle='    maxzoom: archive.maxZoom,',
        replacement='    maxzoom: TERRAIN_MAX_ZOOM,',
        guard='declares its maxzoom from the archive\'s own depth, with nothing left to disagree',
    ),
    Sabotage(
        suite='web',
        # The other half, and no call to the builder can see it: the function stays perfect while
        # the page hands it somebody else's numbers. Hardcoding the slug is the realistic form —
        # Earth is the body in front of you, and every Earth test agrees.
        label='the page builds its DEM source from Earth rather than from the body it is drawing',
        path='web/src/components/Globe.astro',
        needle='terrainDemSource(terrainTileUrlTemplate, terrainArchive, declaredTileSize)',
        replacement='terrainDemSource(terrainTileUrlTemplate, archiveFor("earth", "terrain"), declaredTileSize)',
        guard='hands the page\'s source the ARCHIVE and not this module\'s constants',
    ),
    # --- the elevation cut stops being Earth's ---------------------------------------------------
    # Every mutation here produces a complete pyramid that no test of Earth can distinguish from the
    # right one, because Earth IS the value being hardcoded. Only a second body's numbers differ.
    Sabotage(
        suite='python',
        label='the master zoom goes back to a constant, so every planet descends from Earth\'s grid',
        path='pipeline/tile/terrain_rgb.py',
        needle='    return body.tile_max_zoom',
        replacement='    return 8',
        guard='test_each_body_s_master_grid_is_the_one_its_descent_assumes',
    ),
    Sabotage(
        suite='python',
        # The check that stands between a wrong native zoom and a half-resolution pyramid. Made
        # unfalsifiable rather than deleted, which is how a guard usually dies: still called, still
        # named in the log, answering None to everything.
        label='the master-grid check accepts any raster it is handed',
        path='pipeline/tile/terrain_rgb.py',
        needle='    if width == expected and height == expected:',
        replacement='    if True:',
        guard='test_a_master_at_another_zooms_grid_is_refused_by_name',
    ),
    Sabotage(
        suite='python',
        # Earth's `path_prefix` is empty, so the containment bound is the one place this is easy to
        # write wrong: moved one level up it passes for both planets and guards nothing.
        label='the output bound moves up to the shared work root, where both planets satisfy it',
        path='pipeline/tile/terrain_rgb.py',
        needle='    stage = bodies.work_dir(body, "planet_terrain").resolve()',
        replacement='    stage = bodies.work_dir(body, "planet_terrain").parent.resolve()',
        guard='test_a_cut_aimed_at_another_planet_s_tree_is_refused',
    ),
    Sabotage(
        suite='python',
        # The documented trap, restored: argparse hands you a sea treatment the shipped archive does
        # not use, so the bare command rebuilds a different pyramid. On a body with no sea it also
        # flattens every point below zero, which is the deepest basin on Mars.
        label='the sea default is spelled out again instead of following what shipped',
        path='pipeline/tile/terrain_rgb.py',
        needle='                    default="clamp" if SHIPPED_SEA_CLAMP else "bathy",',
        replacement='                    default="clamp",',
        guard='test_the_bare_command_reproduces_the_sea_treatment_that_is_on_the_wire',
    ),
    Sabotage(
        suite='python',
        label='the elevation cut assumes Earth when nobody names a body',
        path='pipeline/tile/terrain_rgb.py',
        needle='    ap.add_argument("--body", required=True,',
        replacement='    ap.add_argument("--body", default="earth",',
        guard='test_the_body_is_required_with_no_default',
    ),
    # --- the two elevation producers drift apart again -------------------------------------------
    # THE WRONG FIX, NOT THE ORIGINAL BUG. Faced with tiles and cap at different heights, flattening
    # BOTH toward the pole closes the seam between them and leaves every polar basin a smooth shell —
    # and it satisfies any guard phrased as "the two producers agree", because they do. Only a test
    # that asks what the tiles say about the GROUND can see it.
    Sabotage(
        suite='python',
        label='the polar flatten returns inside the shared encoder, so both surfaces agree and both are wrong',
        path='pipeline/tile/terrain_rgb.py',
        needle='    packed = np.clip(np.round((metres + BASE_SHIFT) / step), 0, 65535).astype(np.uint16)',
        replacement='    metres = metres * np.linspace(0.0, 1.0, metres.shape[0])[:, None]\n'
                    '    packed = np.clip(np.round((metres + BASE_SHIFT) / step), 0, 65535).astype(np.uint16)',
        guard='test_the_encode_is_a_pure_function_of_metres_at_every_latitude',
    ),
    # The door the behavioural guard cannot watch: an argument nobody passes YET. This is the exact
    # shape the deleted feather arrived in — optional, defaulted, and honoured by one of the two
    # callers — so the parameter list is pinned rather than the behaviour of today's callers.
    Sabotage(
        suite='python',
        label='the encoder grows an optional argument only one of its two producers would pass',
        path='pipeline/tile/terrain_rgb.py',
        needle='def encode_array(elevation: np.ndarray, step: float, sea_clamp: bool) -> np.ndarray:',
        replacement='def encode_array(elevation: np.ndarray, step: float, sea_clamp: bool,\n'
                    '                 latitudes: np.ndarray | None = None) -> np.ndarray:',
        guard='test_encode_array_takes_nothing_a_caller_could_differ_on',
    ),
    # --- the antimeridian fill ------------------------------------------------------------------
    # THE TEMPTING SIMPLIFICATION, NOT AN ABSURDITY. On real terrain the two neighbours differ by a
    # median of 2.2 m, so copying one of them is within noise of correct everywhere and no
    # measurement taken on Mars would separate them. Only a fixture built so the three candidate
    # answers cannot coincide can see this, which is why that test carries the file's warning.
    Sabotage(
        suite='python',
        label='the wrap fill copies its western neighbour instead of interpolating across the seam',
        path='pipeline/wrap_seam.py',
        needle='            midpoint = 0.5 * (west.astype(np.float64) + east.astype(np.float64))',
        replacement='            midpoint = west.astype(np.float64)',
        guard='test_the_fill_is_the_midpoint_of_BOTH_neighbours',
    ),
    # The generalisation that reads as an improvement: "why refuse a hole when we know how to fill
    # one?" Because Earth's land DEM fuses a missing Copernicus tile as ocean, so the bodies with
    # real gaps are exactly the bodies this would invent ground on, silently and at scale.
    Sabotage(
        suite='python',
        label='the wrap fill stops refusing holes off the seam and smooths every gap it finds',
        path='pipeline/wrap_seam.py',
        needle='        off_seam = off_seam[off_seam != seam]\n        if off_seam.size:',
        replacement='        off_seam = off_seam[off_seam != seam]\n        if False:',
        guard='test_a_hole_off_the_seam_raises_rather_than_being_filled',
    ),
    # A column recompute rather than a hole fill. Passes on a fully-missing seam, which is the
    # fixture anyone would reach for first; Mars's seam is 79% missing, so the 21% of real ground it
    # would overwrite is invisible until a partial fixture exists.
    Sabotage(
        suite='python',
        label='the wrap fill rewrites the whole seam column rather than only its missing pixels',
        path='pipeline/wrap_seam.py',
        needle='            column = np.where(column == missing, midpoint, column).astype(dataset.dtypes[0])',
        replacement='            column = midpoint.astype(dataset.dtypes[0])',
        guard='test_pixels_the_warp_did_fill_are_left_alone',
    ),
    # THE PLACEMENT BUG, WHICH IS THE ONE THAT ACTUALLY HAPPENED. The fill was first written inside
    # the warp's freshness branch, where it is invisible to every test that lets the warp run — and
    # every planet already on disk was warped before this stage existed, so on a real box it would
    # have done nothing at all while the diff read as a fix.
    Sabotage(
        suite='python',
        label='the wrap fill is gated on a re-warp, so no planet already on disk is ever closed',
        path='pipeline/tile/shade_planet.py',
        needle='    filled = wrap_seam.close_wrap_seam(height)',
        replacement='    filled = 0',
        guard='test_the_wrap_seam_is_closed_on_a_height_the_warp_did_not_rebuild',
    ),
    # Filling the raster and not restaging is the same defect wearing a different hat: the hillshade
    # and the composite both key on this marker, so they keep the cliff and the darkest-stop column
    # they derived from a hole that is no longer there.
    Sabotage(
        suite='python',
        label='the wrap fill changes the height and leaves the freshness marker vouching for the old bytes',
        path='pipeline/tile/shade_planet.py',
        needle='        print(f"wrap seam: filled {filled} px at the antimeridian -> height restaged", flush=True)\n'
               '        mark_done(height)',
        replacement='        print(f"wrap seam: filled {filled} px at the antimeridian", flush=True)',
        guard='test_the_wrap_seam_is_closed_on_a_height_the_warp_did_not_rebuild',
    ),
    # The concept regrowing a second home, in the half of `mercator.py` that had no scan until the
    # fill needed it. A truncation is the realistic form and passes every tolerance anyone writes.
    Sabotage(
        suite='python',
        label='a pipeline module transcribes half the Mercator plane instead of importing it',
        path='pipeline/wrap_seam.py',
        needle='    span = dataset.bounds.right - dataset.bounds.left\n'
               '    return abs(span - 2.0 * MERCATOR_HALF_M) <= dataset.res[0]',
        replacement='    span = dataset.bounds.right - dataset.bounds.left\n'
                    '    return abs(span - 2.0 * 20037508.34) <= dataset.res[0]',
        guard='test_no_module_regrows_the_mercator_half_extent',
    ),
    Sabotage(
        suite='web',
        # The silent-and-total one, moved: it used to need a flag threaded through a build directory
        # and is now expressible in exactly one place, since `terrainDemSource` takes no step. Every
        # tile still 200s and still decodes — a planet eight times too flat, with nothing logged.
        label='the DEM source decodes at one metre while the archive was cut at eight',
        path='web/src/lib/terrainSource.ts',
        needle='    ...terrainEncoding(),\n  };\n}',
        replacement='    ...terrainEncoding(1),\n  };\n}',
        guard='cannot fetch one encoding and decode with another, because there is one of each',
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
        guard='builds no address for a subsystem that is off, instead of throwing at page load',
    ),
    Sabotage(
        suite='web',
        # A gate deleted in the page rather than in the module. This is the shape a source scan is
        # the only available guard for: the gates live in a client script nothing can import.
        label='the detail panel opens for a body with no heroes rendered',
        path='web/src/components/Globe.astro',
        needle='    if (subsystems.heroes) openPanel(countryPanelContent(country));',
        replacement='    openPanel(countryPanelContent(country));',
        # Re-pointed: the subsystem scan is existence-only, and `chip-answers-taps` became a second
        # reader of `subsystems.heroes`, so deleting THIS gate stopped failing there. Proved by
        # mutation — the case went MISSED against the old guard.
        guard='opens only for a body whose places have renders',
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
        # THE NEGATIVE CONTROL TURNED POSITIVE, which is what makes this worth more than a pointer
        # planted anywhere else. MARS.md left version control while 16 other branches still track
        # it, so it joined the patterns this guard sweeps for — and `see MARS_ICE_WHITE` on this
        # very line is a reachable CONSTANT that must go on passing. One `\b` decides between them,
        # and nothing else in the suite would notice if it were dropped.
        label='a pointer at the untracked Mars brief, planted on the line that proves the boundary',
        path='pipeline/look/palette.py',
        needle='see MARS_ICE_WHITE',
        replacement='see MARS.md',
        guard='test_no_reference_to_a_file_a_clone_will_not_have',
    ),
    # The newest alternation, added the day the brief was gitignored. It needs its own case
    # because a filename the pattern ENUMERATES is exactly the half that goes missing:
    # gitignoring a path is otherwise a change nothing goes red for, and this guard knows only
    # the names written into it. The needle sits INSIDE the module docstring, so the sabotaged
    # file still parses and the guard is the only thing that can fail.
    Sabotage(
        suite='python',
        label="cite the newcomer's question brief from the module that owns the vector paths",
        path='pipeline/naturalearth.py',
        needle='WHY THIS MODULE EXISTS',
        replacement='See ' + 'ONBOARDING-QUESTIONS' + '.md.\n\nWHY THIS MODULE EXISTS',
        guard='test_no_reference_to_a_file_a_clone_will_not_have',
    ),
    Sabotage(
        suite='python',
        # THE BARE FORM, which is the half that walked through for months: the pattern anticipated
        # `see PLAN` and never grew the `see HISTORY` twin, so a diagram shipped one and nothing
        # went red. Planted WITHOUT the `.md` deliberately — `HISTORY\.md` already catches that
        # spelling, so a case the old pattern would also have caught proves nothing about the new.
        label='a pointer at the decision archive that never names the file',
        path='pipeline/bodies.py',
        needle='"""The single home for what differs between one planet and the next.',
        replacement='"""The single home for what differs between one planet and the next, see HISTORY.',
        guard='test_no_reference_to_a_file_a_clone_will_not_have',
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
        # Anchored on the preceding argument, because a bare `body.groundRadiusM,` is now a
        # substring of a second, more deeply indented call site — see the case below.
        needle='        locateOnDatum,\n        body.groundRadiusM,',
        replacement='        locateOnDatum,\n        6371008.8,',
        guard='takes the radius from the body it is drawing, not from a number',
    ),
    Sabotage(
        suite='web',
        # The SECOND caller of the same measurement. The ruler's guard reads `updateRuler`'s body
        # and cannot see this one, so the widened scan is what has to catch it — on Mars an Earth
        # radius mis-sizes every candidate by the ratio of the two, which silently changes which
        # features are pointable at rather than throwing.
        label='the feature pick sizes candidates with Earth\'s radius on every body',
        path='web/src/components/Globe.astro',
        needle='rulerGroundDistance(locateOnDatum, body.groundRadiusM, viewport.width',
        replacement='rulerGroundDistance(locateOnDatum, 6371008.8, viewport.width',
        guard="passes the drawn body's radius at EVERY call site, not only the ruler's",
    ),
    Sabotage(
        suite='web',
        # The THIRD caller of the same radius, and the newest. Framing is the pick read backwards, so
        # an Earth radius here lands the camera at the zoom a feature of that size would need on
        # Earth — off by the ratio of the two bodies, and visible only as "the fly-to overshoots".
        label='the fly-to frames Mars against Earth\'s radius',
        path='web/src/components/Globe.astro',
        needle='          viewportSize(),\n          body.groundRadiusM,',
        replacement='          viewportSize(),\n          6371008.8,',
        guard="passes the drawn body's radius at EVERY call site, not only the ruler's",
    ),
    # --- Mars's hit-testing and hover -------------------------------------------------------------
    # The pick rule is arithmetic, so every one of these produces a globe that renders perfectly and
    # answers the wrong thing — or nothing — with no error anywhere.
    Sabotage(
        suite='web',
        # The band loses its floor, so a sub-pixel crater under the pointer beats the region that
        # is actually on screen and the highlight lands on something invisible.
        label='a feature too small to see can be picked',
        path='web/src/lib/featureTargeting.ts',
        needle='  if (extent < MIN_TARGET_PX) return false;\n',
        replacement='',
        guard='prefers the terra at overview where the crater really is a speck',
    ),
    Sabotage(
        suite='web',
        # The band loses its ceiling, which restores exactly the frame that was rejected on screen:
        # a 4,688 km bracket drawn across a view it does not fit.
        label='a container too big to fit the frame is painted again',
        path='web/src/lib/featureTargeting.ts',
        needle='  return extent <= MAX_TARGET_VIEWPORT_FRACTION * viewportReferencePx(viewport);',
        replacement='  return true;',
        guard='drops the terra at the zoom where it was judged wrong',
    ),
    Sabotage(
        suite='web',
        # Smallest rather than smallest ELIGIBLE — the naive rule this whole module replaced.
        label='the pick ignores whether a candidate reads at this scale',
        path='web/src/lib/featureTargeting.ts',
        needle='    if (!readsAtThisScale(candidate, metresPerPixel, viewport)) continue;',
        replacement='    if (candidate.diameterKm === null) continue;',
        guard='picks the SMALLEST ELIGIBLE, not the smallest',
    ),
    Sabotage(
        suite='web',
        # An absent diameter becomes a zero, which is a different and wrong answer: absence is data
        # here, because the cutter drops a falsy value from the tile.
        label='a feature with no diameter is treated as one of size zero',
        path='web/src/lib/featureTargeting.ts',
        needle='      ? diameter\n      : null,',
        replacement='      ? diameter\n      : 0,',
        guard='treats a missing diameter as unsized rather than as zero',
    ),
    Sabotage(
        suite='web',
        # Without a promoted id a vector feature has no identity that survives tile splitting, so
        # every setFeatureState write addresses nothing. MapLibre answers by firing an ErrorEvent
        # and returning — no throw, and a globe whose hover silently does nothing.
        label='the feature source stops promoting an id for hover to key on',
        path='web/src/lib/featureOverlay.ts',
        needle='    promoteId: "name",',
        replacement='    // promoteId removed',
        guard='promotes the same field the pick rule returns',
    ),
    Sabotage(
        suite='web',
        # One source-layer left out of the hover write, which lights a crater's ring and leaves
        # every vallis dark — a half-working highlight nobody would call a bug from a screenshot.
        label='the hover state is written to only one of the two painted layers',
        path='web/src/lib/featureOverlay.ts',
        needle='    { source: FEATURES_SOURCE, sourceLayer: requireSourceLayer("mars", "line") },',
        replacement='    // the linear layer no longer takes a hover write',
        guard='writes to every source-layer that carries hover paint, and to nothing else',
    ),
    Sabotage(
        suite='web',
        # Built but never mounted. Its spec stays in the source for the ledger scan to find and its
        # own unit tests still pass, because they call the factory directly.
        label='the linear hit surface is built and never added to the map',
        path='web/src/components/Globe.astro',
        needle='    map.addLayer(featureLinearHitLayer());',
        replacement='    // the linear hit surface is never mounted',
        guard='adds the hit surface for features that exist only as lines',
    ),
    Sabotage(
        suite='web',
        # Only the polygons are queried, so the valles and fossae — which carry no polygon anywhere
        # in the archive — become unreachable at every zoom.
        label='only one of the two hit surfaces is queried',
        path='web/src/components/Globe.astro',
        needle='      ["feature-linear-hit", true],\n',
        replacement='',
        guard='queries BOTH hit surfaces, since the two kinds of feature are disjoint sets',
    ),
    Sabotage(
        suite='web',
        # The tap binding goes and the body is mute on a phone again — which is the state this
        # commit was asked to end, and which no desktop check would ever notice.
        label='a tap stops resolving, leaving the body silent on touch',
        path='web/src/components/Globe.astro',
        needle='      featureTracker.pointerMoved(event.point);\n      goToFeature',
        replacement='      void 0;\n      goToFeature',
        guard='answers a tap, so the body is not mute on a phone',
    ),
    Sabotage(
        suite='web',
        # The pointer still names the feature and the click goes nowhere — a globe that looks fully
        # alive on hover and does nothing at all when you act on what it told you.
        label='a pick names the feature and the camera never moves',
        path='web/src/components/Globe.astro',
        needle='      goToFeature(featureAt(event.point));',
        replacement='      // a tap names but goes nowhere',
        guard='answers a tap, so the body is not mute on a phone',
    ),
    Sabotage(
        suite='web',
        # THE BUG THIS SHIPPED WITH ONCE, restored: the click asks the tracker for its state instead
        # of resolving its own point. The tracker queues that resolve for the NEXT frame, so a tap —
        # which has no hover before it — reads null and the first tap on a phone does nothing. Every
        # other guard in the file passes unchanged, and desktop hover hides it completely.
        label='the click reads a frame-stale answer, so a phone ignores the first tap',
        path='web/src/components/Globe.astro',
        needle='      goToFeature(featureAt(event.point));',
        replacement='      goToFeature(featureTracker.current());',
        guard="resolves the click's own point instead of asking the tracker what it holds",
    ),
    Sabotage(
        suite='web',
        # Half of mirroring Earth, deleted. The camera arrives framed on a feature the visitor now
        # has no name, kind or etymology for — and the chip that WOULD have named it is suppressed
        # on touch precisely because a card was promised.
        label='the fly arrives with no card behind it',
        path='web/src/components/Globe.astro',
        needle='        openPanel(featurePanelContent(feature));',
        replacement='        // no card on arrival',
        guard='flies AND opens the card, which is the whole of mirroring Earth',
    ),
    Sabotage(
        suite='web',
        # The other half: the card opens on a globe that never went anywhere, so it describes a
        # feature somewhere off screen. Reads as a bug in the CARD rather than in the camera.
        label='the card opens and the camera stays put',
        path='web/src/components/Globe.astro',
        needle='        map.flyTo(camera);',
        replacement='        // the camera stays where it was',
        guard='flies AND opens the card, which is the whole of mirroring Earth',
    ),
    Sabotage(
        suite='web',
        # THE REGRESSION WITH NO VISIBLE SYMPTOM AT ALL. Both pages mount one component and share one
        # client chunk, so a static import ships 324 KB of Martian nomenclature to every Earth
        # visitor. Everything renders, every test that drives behaviour passes, and the only trace is
        # a bigger download. Planted as the import line itself, which is how it would really arrive.
        label='Earth downloads Mars\'s catalogue because the import went static',
        path='web/src/components/Globe.astro',
        needle='  import { createHoverTracker, type HoverTracker } from "../lib/hoverTracking";',
        replacement='  import { createHoverTracker, type HoverTracker } from "../lib/hoverTracking";\n'
                    '  import { featureNamed } from "../lib/featureIndex";',
        guard='asks for the catalogue LAZILY, or Earth downloads Mars\'s place names',
    ),
    Sabotage(
        suite='web',
        # The re-resolve goes back to asking the country tracker, which on Mars answers null
        # everywhere. A closed card leaves the outline lit under the pointer and the name gone,
        # until something moves. Nothing throws and the card itself is perfect.
        label='closing a Mars card leaves its feature lit and unnamed',
        path='web/src/components/Globe.astro',
        needle='    activeTracker = featureTracker;',
        replacement='    // the re-resolve keeps its default owner',
        guard='hands the pointer\'s chrome to the resolver that answers on this body',
    ),
    Sabotage(
        suite='web',
        # The touch suppression is lifted again. Every tap now flashes the chip under the arriving
        # card — and on Mars the card waits on a fetch, so the flash lasts as long as the network
        # does. Invisible on every desktop check.
        label='the chip flashes under the arriving card on touch',
        path='web/src/components/Globe.astro',
        needle='  @media (hover: none) {\n    .country-chip {',
        replacement='  @media (hover: none) {\n    .country-chip-disabled {',
        guard='suppresses the chip on touch for every body, now that every tap brings a card',
    ),
    Sabotage(
        suite='web',
        # The gazetteer's dictionary headword reaches the card. Every eyebrow on the body reads
        # "CRATER, CRATERS" — wrong on all 1,919 features at once, which is the kind of wrongness
        # that looks like a deliberate style choice to anyone who has not seen the alternative.
        label='the card labels a feature with the IAU\'s singular AND plural',
        path='web/src/lib/detailPanel.ts',
        needle='  return type.split(",")[0]!.trim();',
        replacement='  return type;',
        guard='keeps the singular and drops the plural',
    ),
    Sabotage(
        suite='web',
        # The tidy-up that looks obviously right: two functions turning a length into a label, so
        # collapse them. It re-rounds every published diameter to two significant figures, and the
        # card starts quoting the IAU numbers the IAU did not publish.
        label='a published diameter is rounded like a measured one',
        path='web/src/lib/detailPanel.ts',
        needle='  return `${Math.round(diameterKm).toLocaleString("en-US")} km`;',
        replacement='  return `${Number(diameterKm.toPrecision(2)).toLocaleString("en-US")} km`;',
        guard='disagrees with the scale ruler, which is the point of it existing',
    ),
    Sabotage(
        suite='web',
        # The two unsized features get a size after all. "Chaos · 0 km" is the catalogue contradicting
        # itself: the same rows the pick refuses to size, sized on the card.
        label='an unsized feature is given a diameter of zero on the card',
        path='web/src/lib/detailPanel.ts',
        needle='  return feature.diameterKm === null\n    ? type',
        replacement='  return false\n    ? type',
        guard='falls back to the kind alone where the gazetteer publishes no size',
    ),
    Sabotage(
        suite='web',
        # The lookup gets helpful. A trimmed key resolves names that can never light anything, since
        # feature state and the hit test are both keyed on the published spelling — so a search
        # result flies the camera to a feature the pointer then refuses to acknowledge.
        label='the name lookup starts matching things the tiles cannot',
        path='web/src/lib/featureIndex.ts',
        needle='  return byName.get(name) ?? null;',
        replacement='  return byName.get(name.trim()) ?? null;',
        guard='is case- and space-exact, because the tiles\' promoteId is',
    ),
    Sabotage(
        suite='web',
        # Earth's framing goes back to a literal while Mars keeps deriving. The two stop meaning the
        # same thing, and a later change to the card's width corrects one body and not the other.
        label='Earth\'s card clearance becomes a literal again',
        path='web/src/components/Globe.astro',
        needle='              right: FRAME_EDGE_PX + PANEL_CLEARANCE_PX,',
        replacement='              right: 460,',
        guard="gives Earth's padding and Mars's offset one source",
    ),
    Sabotage(
        suite='web',
        # The offset's SIGN. The camera shifts the feature toward the card instead of away from it,
        # so a deliberate pick arrives centred underneath the panel describing it. The fly still
        # runs, the zoom is still right, and the arrival looks like a card placement bug.
        label='the fly-to shifts its subject under the card instead of clear of it',
        path='web/src/components/Globe.astro',
        needle='? [-PANEL_CLEARANCE_PX / 2, 0] : [0, 0]',
        replacement='? [PANEL_CLEARANCE_PX / 2, 0] : [0, 0]',
        guard="gives Earth's padding and Mars's offset one source",
    ),
    Sabotage(
        suite='web',
        # A new painted layer id arrives without a ledger entry — the consent failure the gate was
        # built for, planted at the one place this commit adds paint.
        label='a hover layer is renamed and nobody is told it paints',
        path='web/src/lib/featureOverlay.ts',
        needle='      id: "feature-linear-hl-line",',
        replacement='      id: "feature-glow",',
        guard='names every literal-id layer in the ledger, and ledgers no layer that does not exist',
    ),
    Sabotage(
        suite='web',
        # The camera moves under a parked pointer and the answer goes stale — worse here than on
        # Earth, because the pick depends on the SCALE as well as the position.
        label='the pick is not re-run when the camera moves',
        path='web/src/components/Globe.astro',
        needle='    map.on("moveend", () => featureTracker.viewChanged());',
        replacement='    // the camera moving no longer re-resolves',
        guard='re-resolves when the camera moves, which matters more here than on Earth',
    ),
    Sabotage(
        suite='web',
        # The ceiling applies to channels again, and their diameter is a LENGTH: a 1,758 km vallis
        # overflows every zoom that shows its width, so the whole linear catalogue goes unreachable
        # while every polygon keeps working — a failure that looks like a data problem.
        label='a channel is judged by its length, so no zoom can reach it',
        path='web/src/lib/featureTargeting.ts',
        needle='  if (candidate.linear) return true;\n',
        replacement='',
        guard='answers a channel whose length crosses the frame several times',
    ),
    Sabotage(
        suite='web',
        # Back to dividing by the viewport's shorter side, which makes the judgement depend on the
        # aspect ratio: on a portrait phone the obvious thing on screen scores as an overflow and a
        # tap returns nothing, while the same camera on a desktop answers.
        label='the viewport is measured by its shorter side, so a phone loses its targets',
        path='web/src/lib/featureTargeting.ts',
        needle='  return Math.sqrt(Math.max(width, 0) * Math.max(height, 0));',
        replacement='  return Math.min(width, height);',
        guard='answers the same crater on a portrait phone, which is where this was caught',
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
        # THE ROLE DISPATCH IS AN ALLOWLIST, and this is the tidy that turns it into an else. Every
        # page the guard should ignore then reads as a lite page: a country page and the About page
        # would steer a capable first-time visitor onto the globe before they had seen either.
        label='the guard treats anything that is not a globe as a lite page',
        path='web/src/layouts/Base.astro',
        needle='          if (role !== "globe" && role !== "lite") return;',
        replacement='          if (role === "globe" || role === "lite") { /* fall through */ }',
        guard="leaves a page that is neither of a body's two alone, whatever body it dresses in",
    ),
    Sabotage(
        suite='web',
        # The site root is Earth's lite content at a second URL, and NOTHING derives that — the
        # registry says `/earth/lite/` and is right. Demote this one declaration and `/` stops
        # steering anyone: the front page quietly becomes the end of the journey for every capable
        # visitor who arrives at it, which is what flipping `liteRoute` did before the role existed.
        label='the site root stops calling itself a lite page, and the auto-steer goes with it',
        path='web/src/pages/index.astro',
        needle='pageRole="lite"',
        replacement='pageRole="plain"',
        guard='calls the site root a lite page, which no registry field can tell it',
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
        path='web/src/pages/mars/index.astro',
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
        # RE-AIMED, NOT RETIRED, and the reason is that the defect stopped being expressible. The
        # credits were a flat list whose groups carried a `body:` label, so a group could be filed
        # under the wrong planet by editing one string. They are now a `Record<BodySlug, …>`, where
        # a body's sources sit under its own key and mislabelling is not a one-line edit — the
        # structure took the mutation away, which is what the move was for. What remains reachable,
        # and is the same defect one layer down, is a source going blank: a card renders, the planet
        # still has an entry, and the credit is gone.
        label="a body's credit goes blank while its card still renders",
        path='web/src/lib/aboutContent.ts',
        needle='        name: "MOLA / HRSC Blended DEM",',
        replacement='        name: "",',
        guard='gives every source a name, a role, a licence and a credit',
    ),
    Sabotage(
        suite='python',
        # The licence change reaches the markdown a maintainer edits and misses the copy that is not
        # markdown at all. The About page states it in TypeScript, in another tree, and shows it only
        # when the page is loaded — so it is exactly the copy a sweep-by-eye skips.
        label='the About page keeps the superseded output licence after the docs move',
        path='web/src/pages/about.astro',
        needle='>CC BY-SA 4.0</a>. Use it for anything, credit',
        replacement='>CC BY-NC 4.0</a>. Use it for anything, credit',
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
        path='web/src/lib/aboutContent.ts',
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
        path='web/src/pages/mars/index.astro',
        needle='  <Globe />\n',
        replacement='  <Globe />\n  <a href="https://github.com/Alchez/terrella">source</a>\n',
        guard='is never inlined as a literal, which is the drift this constant exists to stop',
    ),
    # --- The tab strip's one convention ------------------------------------------------------------
    # Seven pages, three title shapes, two of them putting the site name on opposite ends — the drift
    # had already happened before anything owned the format, and nothing could have failed: a
    # `<title>` is a string the build never validates and no rendering test reads.
    Sabotage(
        suite='web',
        # The edit a new page really makes: copy a neighbouring `<Base>`, hand-write the title. It
        # renders, it reads fine on its own, and only the tab strip shows the two conventions.
        label='a page hand-writes its title instead of composing one',
        path='web/src/pages/about.astro',
        needle='  title={pageTitle("About")}',
        replacement='  title="About — Terrella"',
        guard="routes every page's title through pageTitle()",
    ),
    Sabotage(
        suite='web',
        # The half the first rule cannot see, and the mutation that MISSED when this guard was
        # written: calling the helper and hand-writing the format inside its argument. The extractor
        # matched braces with `\{[^}]*\}`, so the `}` closing `${body.label}` ended the capture and
        # the site name sat past it, unread. Counting braces is what made this reachable.
        label='a page calls the title helper and spells the site name inside the argument',
        path='web/src/pages/mars/index.astro',
        needle='  title={pageTitle(body.label)}',
        replacement='  title={pageTitle(`${body.label} — Terrella`)}',
        guard='never lets a page spell the site name into a title itself',
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
        # Earth's own fallback, and it has to be re-read here whenever that moves. Pointed at `/`
        # this stopped being a shared answer the day Earth's lite route became `/earth/lite/` —
        # the two bodies went on disagreeing, so the named guard fell silent and an unrelated one
        # picked the mutation up. The harness reported that as WRONG rather than as caught.
        replacement='    liteRoute: "/earth/lite/",',
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
    # The same argument the planet pass requires, on the entry point that renders the caps. A default
    # here is worse than one there: the caps are invoked automatically at the planet pass's tail, so
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
        label='the pass hands the cap pass a hardcoded earth instead of its own body',
        path='pipeline/tile/planet_pass.py',
        needle='    return [sys.executable, "-m", "pipeline.tile.cap_render", "--body", body.name]',
        replacement='    return [sys.executable, "-m", "pipeline.tile.cap_render", "--body", "earth"]',
        guard='test_the_pass_hands_its_own_body_down_to_the_cap_pass',
    ),
    Sabotage(
        suite='python',
        label='the pass stops passing --body to the cap pass at all',
        path='pipeline/tile/planet_pass.py',
        needle='    return [sys.executable, "-m", "pipeline.tile.cap_render", "--body", body.name]',
        replacement='    return [sys.executable, "-m", "pipeline.tile.cap_render"]',
        guard='test_the_pass_hands_its_own_body_down_to_the_cap_pass',
    ),
    # --- The grids are built per body ----------------------------------------------------------
    # A factory that ignores its argument is the exact failure the module constants were deleted to
    # remove, and it is invisible: the cap projects, blends and publishes — on Earth's sphere, from
    # Earth's heightfield, over Earth's shipped textures.
    Sabotage(
        suite='python',
        label='the north grid factory pins Earth, so every body inherits Earth by construction',
        path='pipeline/tile/cap_render.py',
        # The body argument alone, never the latitudes beside it — the north factory is the only
        # `body=body)` that closes its own call, and edge_lat has moved once already.
        needle='                   body=body)',
        replacement='                   body=bodies.EARTH)',
        guard='test_a_factory_carries_the_body_it_was_given_all_the_way_through',
    ),
    # The mesh spans MESH_EDGE_LAT to the pole and samples the texture by the linear AEQD law, so a
    # mesh reaching further equatorward than the disc reads outside the texture and the cap's rim
    # takes whatever the clamp returns. Two of the four latitudes never reach caps.json, so the
    # manifest cannot pin this ordering and only a source-to-source guard can.
    Sabotage(
        suite='python',
        label='the cap mesh reaches further equatorward than the texture disc it samples',
        path='web/src/lib/polarCaps.ts',
        needle='export const MESH_EDGE_LAT = 80;',
        replacement='export const MESH_EDGE_LAT = 79;',
        guard='test_the_cap_latitude_ladder_holds',
    ),
    # The URL is rebuilt from the basename, which is what it used to be. Correct for Earth, whose
    # segment is empty; every nesting body advertises its whole texture set one directory up.
    Sabotage(
        suite='python',
        label="a cap's served URL is rebuilt from its basename, 404ing every body that nests",
        path='pipeline/tile/cap_render.py',
        needle='    return "/" + asset.relative_to(bodies.public_root()).as_posix()',
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
    # The rule the whole scheme rests on: two pyramids in one archive is not a tight packing, it is
    # an address collision — and it would serve terrain bytes where relief was asked for.
    Sabotage(
        suite='web',
        label='terrain is published out of the relief archive',
        path='web/src/lib/tileAddress.ts',
        needle='      objectKey: "terrain-v2.pmtiles",',
        replacement='      objectKey: "planet-v2.pmtiles",',
        guard='never puts two pyramids in one archive',
    ),
    # The vector arm, which the guard could not see while it excluded that layer. Same collision,
    # same consequence: country tiles served where relief was addressed.
    Sabotage(
        suite='web',
        label='the vector archive is published under the relief key',
        path='web/src/lib/tileAddress.ts',
        needle='      objectKey: "countries-v2.pmtiles",',
        replacement='      objectKey: "planet-v2.pmtiles",',
        guard='never puts two pyramids in one archive',
    ),
    # The rename's compatibility half, which is temporary and therefore the half nobody re-reads.
    # Dropping it does not break a type or a current URL — it breaks every page a visitor already
    # has open, whose tile URLs are `immutable` for a year and still spell the old word.
    Sabotage(
        suite='web',
        label='the retired layer word stops resolving, blanking every page built before the rename',
        path='web/src/lib/tileAddress.ts',
        needle='const RENAMED_LAYER_WORDS: Record<string, LayerId | undefined> = { countries: "vector" };',
        replacement='const RENAMED_LAYER_WORDS: Record<string, LayerId | undefined> = {};',
        guard='resolves the old word to exactly the tile the new word resolves to',
    ),
    # The alias's only exit condition. Without the signal it is never safe to delete, so it stays
    # forever — and a temporary branch nobody can retire is the shape this repo bans.
    Sabotage(
        suite='web',
        label='the pre-rename word is served silently, with no signal for when the alias can go',
        path='web/src/lib/tileAddress.ts',
        needle='  return TILE_PATH_PATTERN.exec(pathname)?.[2] ?? null;',
        replacement='  return null;',
        guard='reports the word a path SPELLED, which is the only signal for when the alias can go',
    ),
    # The source-layer names, which must agree across a language seam no type system crosses. This
    # mutation edits TYPESCRIPT and the PYTHON suite has to go red — before the cross-language pin
    # existed, each side compared its own constants against its own literals, so renaming a layer
    # and its neighbouring literal in one language left the other untouched and every suite green.
    # What ships from that is a globe drawing nothing, with no error anywhere to say why.
    Sabotage(
        suite='python',
        label="Earth's fill layer is renamed in the browser but not in the cutter",
        path='web/src/lib/sourceLayers.ts',
        needle='    fill: "country_fill",',
        replacement='    fill: "country_fills",',
        guard='test_every_role_matches_the_producer',
    ),
    # One level up from the layer names: which PRODUCT a body publishes. Every name below can be
    # right while this word is wrong, and the frontend branches on this word to pick a style stack —
    # so the failure is Earth's manifest-filtered, hit-tested country layers pointed at Mars's tiles.
    Sabotage(
        suite='python',
        label="Mars is declared to publish Earth's product, with every layer name still correct",
        path='web/src/lib/sourceLayers.ts',
        needle='  mars: "features",',
        replacement='  mars: "countries",',
        guard='test_each_body_is_declared_to_publish_the_product_its_cutter_makes',
    ),
    # The half that makes the record above evidence rather than a third copy — and the stage name
    # the dev server DERIVES an archive's path from, so a cutter writing elsewhere serves a 500 that
    # reads as "the pipeline has not been run".
    Sabotage(
        suite='python',
        label='the vector cut sends every body to one directory',
        path='pipeline/compose/vector_cut.py',
        needle='    return bodies.work_dir(cut.body, "planet_vector")',
        replacement='    return bodies.work_dir(bodies.EARTH, "planet_vector")',
        guard='test_each_cutter_writes_into_the_body_it_serves',
    ),
    # The gate that picks a style stack, mutated to Earth's answer for every planet. No type breaks:
    # both sides of the ternary are a `VectorProduct`, and what ships is `country_fill` layers over
    # an archive that holds `feature_fill` — which MapLibre paints as empty, silently.
    Sabotage(
        suite='web',
        label='every body is handed the countries product, whatever its archive holds',
        path='web/src/lib/globeSubsystems.ts',
        needle='published.vector !== null && !bare ? VECTOR_PRODUCT[body] : null,',
        replacement='published.vector !== null && !bare ? "countries" : null,',
        guard="names a product the body's own archive holds, never another planet's",
    ),
    # THE CONSENT GATE, and it is the only guard in this table that does not ask whether the code is
    # correct. Mars shipped a permanently painted overlay nobody had seen while every correctness
    # guard was green — so these four break it the four ways it can be broken: a layer added without
    # a ledger entry, a ledger entry outliving its layer, a paint claim downgraded without touching
    # the paint, and the scan itself blinded.
    Sabotage(
        suite='web',
        label='a painted layer is added to the globe with nobody told',
        path='web/src/components/Globe.astro',
        needle='    map.addLayer(featureFillLayer());\n',
        replacement=(
            '    map.addLayer(featureFillLayer());\n'
            '    map.addLayer({ id: "feature-glow", type: "line", source: FEATURES_SOURCE,\n'
            '      paint: { "line-color": "#ff0000", "line-opacity": 1 } });\n'
        ),
        guard='names every literal-id layer in the ledger, and ledgers no layer that does not exist',
    ),
    # THE SECOND CONSENT MECHANISM, and the one the ledger above structurally cannot cover: terrain
    # is `setTerrain` over a `raster-dem` source rather than a style layer, so `paintedLayers.ts`
    # would reject an entry for it as naming a layer that does not exist. The first two exist
    # because the failure already happened — publishing `PUBLISHED.mars.terrain` was by itself
    # enough to make Mars displace at Earth's 15x, with every other guard green. The third guards
    # the NUMBER rather than the mechanism, which is the way this table can be emptied of meaning
    # while every case above still passes.
    Sabotage(
        suite='web',
        label='the ratified table collapses back to one constant, so publishing a pyramid paints with it',
        path='web/src/lib/terrainSource.ts',
        needle='  return RATIFIED_TERRAIN_EXAGGERATION[body] ?? null;',
        replacement='  return 15;',
        guard='leaves a body with no entry FLAT at the full tier, however good its pyramid is',
    ),
    Sabotage(
        suite='web',
        # The tidy that reads as finishing the job: the archive is published, so surely the body
        # should get terrain — and a fallback grants it without anyone editing the table. That edit
        # IS the ratification, which is the whole point of the table being the record.
        #
        # It replaces a case that ADDED Mars to the table, which stopped being a mutation the day
        # Mars was legitimately ratified. A case whose subject is a table entry expires when someone
        # writes that entry; this one attacks the lookup, so no amount of ratifying can retire it.
        label="an unratified body inherits a ratified one's exaggeration",
        path='web/src/lib/terrainSource.ts',
        needle='  return RATIFIED_TERRAIN_EXAGGERATION[body] ?? null;',
        replacement=(
            '  return RATIFIED_TERRAIN_EXAGGERATION[body] ?? RATIFIED_TERRAIN_EXAGGERATION.earth'
            ' ?? null;'
        ),
        guard='leaves a body with no entry FLAT at the full tier, however good its pyramid is',
    ),
    Sabotage(
        suite='web',
        # The two 15s are different quantities — one baked into renders and tiles, one a display
        # uniform — and the way they get unified is a de-duplication that looks like tidying: the
        # browser descriptor grows the field, OPTIONAL so nothing else has to change, and the table
        # reads it. After that, retuning the globe's mesh silently invalidates 203 heroes.
        label="the browser descriptor grows the pipeline's baked exaggeration",
        path='web/src/lib/bodies.ts',
        needle='  rendersPolarCaps: boolean;',
        replacement='  exaggeration?: number;\n  rendersPolarCaps: boolean;',
        guard='keeps this number independent of the BAKED exaggeration, which is 15 by coincidence',
    ),
    Sabotage(
        suite='web',
        label='the ledger keeps describing a layer the globe stopped adding',
        path='web/src/lib/countryHighlight.ts',
        needle='    id: "country-hit",',
        replacement='    id: "country-hit-renamed",',
        guard='names every literal-id layer in the ledger, and ledgers no layer that does not exist',
    ),
    Sabotage(
        suite='web',
        label="a layer's paint claim is downgraded without touching what it paints",
        path='web/src/lib/paintedLayers.ts',
        needle='    timing: "never",\n    looks:\n      "nothing. Mars\'s named features',
        replacement='    timing: "always",\n    looks:\n      "nothing. Mars\'s named features',
        guard='checks every one of them, rather than whichever ones someone remembered',
    ),
    Sabotage(
        suite='web',
        label='the layer scan is blinded, which would make the whole consent gate vacuous',
        path='web/src/lib/paintedLayers.test.ts',
        needle=r'  String.raw`\bid:\s*([^,\n]+?),\s*\n?\s*type:\s*"(${TYPE_ALTERNATION})"`, "g",',
        replacement=r'  String.raw`\bnothing_matches_this:\s*"(${TYPE_ALTERNATION})"`, "g",',
        guard='finds layer specs at all, or everything below is vacuous',
    ),
    # The invisible layer's own guard. Nothing on a globe can tell a working opacity-0 fill from a
    # deleted one, so the pin that it PAINTS NOTHING is the only thing standing between the ratified
    # decision and a future edit that quietly re-paints Mars.
    Sabotage(
        suite='web',
        label='the feature fill starts painting again, which no screenshot could distinguish',
        path='web/src/lib/featureOverlay.ts',
        needle='      "fill-opacity": 0,',
        replacement='      "fill-opacity": 0.06,',
        guard='paints nothing, and that is the ratified decision rather than an unfinished edit',
    ),
    # Earth's unpaid debt, not repeated on Mars: a source that reads a module constant agrees with
    # the registry forever, so only a range belonging to no archive can tell the two apart.
    Sabotage(
        suite='web',
        label="Mars's feature source reads a constant zoom range instead of its archive's",
        path='web/src/lib/featureOverlay.ts',
        needle='    minzoom: archive.minZoom,\n    maxzoom: archive.maxZoom,',
        replacement='    minzoom: 0,\n    maxzoom: 7,',
        guard='takes its zoom range from the archive it is handed, not from a module constant',
    ),
    # A product the registry can return and the globe has no branch for. The idle block then adds a
    # source and no layers — the same silent nothing as a wrong source-layer, one gate earlier.
    Sabotage(
        suite='web',
        label='the feature overlay loses its branch, leaving Mars a source with nothing over it',
        path='web/src/components/Globe.astro',
        # Deletes the CALL rather than the gate, which is what the guard now checks for: a branch
        # that exists without drawing anything was the shape that let this case go uncaught.
        needle='        addFeatureOverlay();\n',
        replacement='',
        guard='has a globe branch for every product the registry can hand it',
    ),
    # The loudness the literal imports gave for free. A null reaching a style spec is `undefined`,
    # and MapLibre answers an unaddressable source-layer with an ErrorEvent and a RETURN.
    Sabotage(
        suite='web',
        label='requireSourceLayer hands back an empty string instead of throwing',
        path='web/src/lib/sourceLayers.ts',
        needle='  if (name === null) {',
        replacement='  if (false) {',
        guard='THROWS rather than handing undefined to a style spec',
    ),
    # The transport contract, split out of Earth's product module. Both mutations put a planet back
    # into a file every planet reads, which is the drift the split exists to make impossible — and
    # neither breaks a type, so the compiler has nothing to say about either.
    Sabotage(
        suite='web',
        label='the vector mismatch message names Earth again',
        path='web/src/lib/vectorTiles.ts',
        needle='    `This archive stores ${declared} tiles, but the globe requests ` +',
        replacement='    `Countries archive stores ${declared} tiles, but the globe requests ` +',
        guard='names NO body and NO producer, because one function answers for every planet',
    ),
    Sabotage(
        suite='web',
        label="a per-body zoom returns to the transport module",
        path='web/src/lib/vectorTiles.ts',
        needle='export const VECTOR_CONTENT_TYPE = "application/x-protobuf";',
        replacement='export const VECTOR_CONTENT_TYPE = "application/x-protobuf";\n'
                    'export const COUNTRIES_MAX_ZOOM = 8;',
        guard='carries no per-body constant, which is the whole reason this module exists',
    ),
    # The pointer a drift warning hands the reader. It named one module for every planet until Mars
    # published a ceiling that follows its own source data — and the failure is a reader editing
    # Earth's constant to fix Mars, which changes Earth's pyramid and not Mars's.
    Sabotage(
        suite='web',
        label="Mars's zoom pointer names Earth's module again",
        path='web/src/lib/tileAddress.ts',
        needle='        "minZoom/maxZoom in PUBLISHED.mars.relief, '
               'restating MARS.tile_max_zoom in pipeline/bodies.py",',
        replacement='        "RELIEF_MIN_ZOOM/RELIEF_MAX_ZOOM in web/src/lib/reliefTiles.ts",',
        guard='sends a MARS relief drift to the pipeline, not to Earth\'s module',
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
        # Re-anchored when Mars started publishing, and again when its ceiling moved to z7. The
        # first case made Mars's `null` into Earth's archive; there is no `null` to mutate now.
        # What is left is the tidy-looking one: Mars's ceiling written as the module constants that
        # sit a few lines above it in the same file. It compiles, it reads as removing a magic
        # number, and it makes a z8 Mars address parse against a pyramid cut one rung shallower.
        label='Mars relief takes Earth\'s zoom ceiling instead of its own',
        path='web/src/lib/tileAddress.ts',
        # Anchored for the same reason as the ceiling-drift case above: two Mars entries now declare
        # the same pair, so the coordinate no longer names one of them.
        needle="      // runtime by the dev server reading the archive's own header.\n"
               "      minZoom: 0,\n      maxZoom: 7,",
        replacement="      // runtime by the dev server reading the archive's own header.\n"
                    "      minZoom: RELIEF_MIN_ZOOM,\n      maxZoom: RELIEF_MAX_ZOOM,",
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
        needle='    return bodies.work_dir(bodies.EARTH, "borders")',
        replacement='    return paths.DATA / "work/borders"',
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
    # --- what a night reports, and what it deliberately does not ----------------------------------
    # Every case here leaves the pass rendering correct pixels. What breaks is the reader's view of a
    # 22-hour run: either it goes silent, which is how four of Earth's five surface layers went
    # unreported for months, or it goes loud 4,096 times, which is the same failure spent the other
    # way. Neither shows in any output, and no other gate is about a print.
    Sabotage(
        suite='python',
        # The marker dropped from the helper. Reads like removing noise from a log, and every call
        # site still prints exactly what it printed before -- so the pass looks identical and the
        # watcher matches nothing on any body, producer or layer.
        label='the stage helper stops marking, so nothing the pass announces is reported',
        path='pipeline/progress.py',
        needle='    return f"{STAGE_MARKER} {message}"',
        replacement='    return message',
        guard='test_a_stage_no_one_has_written_yet_is_reported',
    ),
    Sabotage(
        suite='python',
        # The regex goes back to a list of phrasings. It is CORRECT for every stage on it, which is
        # what made the original survive: a stage the list has not been taught about is invisible,
        # and an invisible stage looks exactly like one that has not started.
        label='the watcher holds its own list of phrasings again instead of matching the marker',
        path='pipeline/profile/watchdog.py',
        needle='STAGE_RE = re.compile(re.escape(progress.STAGE_MARKER))',
        replacement='STAGE_RE = re.compile(r"warp height ->|per-row-z hillshade|cutting z0-8")',
        guard='test_a_stage_no_one_has_written_yet_is_reported',
    ),
    Sabotage(
        suite='python',
        # The keyword accepted and ignored: every call site still reads as if it marks a boundary.
        label='block_render takes the stage flag and drops it, so the runner announces nothing',
        path='pipeline/tile/block_render.py',
        needle='    if stage:\n        message = progress.marked(message)\n',
        replacement='',
        guard='test_the_run_starting_is_a_stage',
    ),
    Sabotage(
        suite='python',
        # The other direction, and the one that reads as fixing an omission: the per-block line is
        # the most informative line in the run, so marking it looks like an improvement. It is 4,096
        # wake-ups in a night on Earth, which is why the sidecar carries progress instead.
        label='the per-block line becomes a stage, so a night wakes the reader 4,096 times',
        path='pipeline/tile/block_render.py',
        needle="            f\"{status.done}/{status.total} ({100 * status.done / status.total:.1f}%)\")",
        replacement="            f\"{status.done}/{status.total} ({100 * status.done / status.total:.1f}%)\",\n"
                    "            stage=True)",
        guard='test_the_per_block_line_wakes_nobody',
    ),
    Sabotage(
        suite='python',
        # A failure matched only when the exception text happens to carry the word. A CUDA message
        # does; a segfault, an Xid MMU fault and a Blender exit code do not, so the failures that
        # mean the GPU is gone are exactly the ones that stay quiet.
        label='the fault net drops the runner s own words for a dead block and a dead run',
        path='pipeline/profile/watchdog.py',
        needle='FAULT_RE = re.compile(r"(Traceback|MemoryError|Killed|ABORT|FAILED|Error|error)")',
        replacement='FAULT_RE = re.compile(r"(Traceback|MemoryError|Killed|Error|error)")',
        guard='test_a_block_failing_is_a_fault_whatever_it_failed_with',
    ),
    Sabotage(
        suite='python',
        # Stage before fault, which is the order the reasons are declared in. An abort is a stage
        # boundary too, so the reader is woken either way -- and told the run reached a stage.
        label='a stage that is also a failure is reported as a stage',
        path='pipeline/profile/watchdog.py',
        needle='    if FAULT_RE.search(line):\n        return "FAULT"\n    if STAGE_RE.search(line):\n        return "STAGE"',
        replacement='    if STAGE_RE.search(line):\n        return "STAGE"\n    if FAULT_RE.search(line):\n        return "FAULT"',
        guard='test_the_run_giving_up_is_a_fault',
    ),
    Sabotage(
        suite='python',
        # Differencing instead of banding. It fires at roughly the right rate, which is what makes
        # it survive review, and the milestones drift with wherever the previous report landed.
        label='progress is differenced rather than banded, so the milestones drift off the planet',
        path='pipeline/profile/watchdog.py',
        needle='    return int(current // step) > int(previous // step)',
        replacement='    return current - previous >= step',
        guard='test_a_milestone_fires_and_the_steps_between_do_not',
    ),
    Sabotage(
        suite='python',
        # The baseline read reports. Harmless-looking, and it means a watcher pointed at a finished
        # run announces last night's result as this night's progress before anything has happened.
        label='the first sidecar read fires, so last night s status is reported as tonight s',
        path='pipeline/profile/watchdog.py',
        needle='    if previous is None:\n        return False',
        replacement='    if previous is None:\n        return True',
        guard='test_the_first_read_never_fires',
    ),
    Sabotage(
        suite='python',
        # An optional input that goes quiet when it is missing. A raytraced night watched without
        # --status then looks exactly like one whose producer never rendered a block.
        label='the missing sidecar stops saying which absence it is',
        path='pipeline/profile/watchdog.py',
        needle='        return None, "no --status given"',
        replacement='        return None, None',
        guard='test_absence_says_which_absence_it_is',
    ),
    Sabotage(
        suite='python',
        # Back to `: > pass.log`. The pass still resumes correctly -- blocks are skipped by marker
        # existence -- so nothing is lost but the record of which of them failed on every night but
        # the last, on a producer whose whole point is that it runs across several.
        label='the pass log is emptied at the top of every run, so a resumed render loses its record',
        path='pipeline/profile/run_pass.sh',
        needle='if [[ -s "$PROF/pass.log" ]]; then\n'
               '    # Named for when that run\'s log was last written rather than for now, so the filename says\n'
               '    # which night it covers, and so re-running twice inside one second cannot land on one name.\n'
               '    mv "$PROF/pass.log" "$PROF/pass-$(date -r "$PROF/pass.log" +%Y%m%dT%H%M%S).log"\n'
               'fi\n',
        replacement='',
        guard='test_a_prior_runs_log_survives_the_next_run',
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
        guard='test_the_cgroup_argument_carries_the_resolved_cap_not_a_constant',
    ),
    # --- The cap override, which exists so the three cases around it stay catchable ---------------
    # Both registered bodies render caps, so the resolver answers 16 for every planet and the case
    # above has no second number to be wrong about. MEMORY_CAP_OVERRIDE_GIB supplies one — and being
    # a seam that can weaken a guard, it gets its own cases rather than being trusted.
    Sabotage(
        suite='python',
        # The tidy that reads as dead code: a variable assigned and then assigned again. It leaves
        # every pass at the body's number, which is CORRECT today — and silently un-tests the wiring.
        label='the cap override is read, announced, and then dropped',
        path='pipeline/profile/run_pass.sh',
        needle='    MEMORY_CAP_GIB=$MEMORY_CAP_OVERRIDE_GIB\n',
        replacement='    :\n',
        guard='test_a_lower_cap_runs_on_a_box_that_refuses_earths',
    ),
    Sabotage(
        suite='python',
        # The idiomatic spelling, and the wrong one: `${OVERRIDE:-$(resolver)}` skips the resolver
        # when the variable is set, and with it the --body contract this wrapper enforces before a
        # cgroup scope is opened. An operator with the variable exported gets an unnamed planet.
        label='the cap override short-circuits the resolver, taking --body enforcement with it',
        path='pipeline/profile/run_pass.sh',
        needle='MEMORY_CAP_GIB=$("$VENV" -m pipeline.profile.pass_cap "$@") || exit 1',
        replacement='MEMORY_CAP_GIB=${MEMORY_CAP_OVERRIDE_GIB:-'
                    '$("$VENV" -m pipeline.profile.pass_cap "$@")} || exit 1',
        guard='test_the_resolver_still_runs_when_the_override_is_set',
    ),
    Sabotage(
        suite='python',
        # Validation that looks like belt-and-braces and is not: bash evaluates a non-numeric value
        # as 0 in the comparison, so every box clears every cap and the preflight prints that it
        # passed while having checked nothing.
        label='the cap override stops being validated, so a typo disables the preflight',
        path='pipeline/profile/run_pass.sh',
        needle='    if [[ ! "$MEMORY_CAP_OVERRIDE_GIB" =~ ^[0-9]+$ ]]; then',
        replacement='    if false; then',
        guard='test_a_nonsense_override_aborts_rather_than_evaluating_to_zero',
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
    Sabotage(
        suite='python',
        # A pass sized off a measurement instead of off the policy. It reads as the responsible
        # change -- the caps peak 14.41 GiB and 20 G is honest headroom -- and it is a pass running
        # outside the ratified one-heavy-job-at-a-time ceiling, which is a decision rather than a
        # constant. Nothing checked the relationship, and the cap has sat exactly AT the ceiling
        # since the caps stage pushed it there, so the first body to want more takes it silently.
        label='the pass cap is raised past the ratified heavy-job ceiling',
        path='pipeline/profile/pass_cap.py',
        needle='CAP_RENDERING_GIB = 16',
        replacement='CAP_RENDERING_GIB = 20',
        guard='test_no_pass_is_capped_above_the_ratified_ceiling',
    ),
    Sabotage(
        suite='python',
        # The base grid starts varying with the plane span. It reads as a refinement -- dice in
        # proportion to what you are dicing -- and it silently re-creates the thing a measured join
        # step was wrongly blamed on: a per-block parameter that differs across a shared edge.
        label='the base grid scales with the plane, so neighbours can dice differently again',
        path='pipeline/render/scene_build.py',
        needle='    return max(1, math.ceil(span_px / 2 ** MAX_SUBDIVISIONS))',
        replacement='    return max(1, math.ceil(span_px / 2048))',
        guard='test_the_base_grid_cannot_discriminate_between_neighbouring_blocks',
    ),
    Sabotage(
        suite='python',
        # The document goes back to naming the module the pass used to live in. It reads as a true
        # sentence -- shade_planet is still where the shared stages and the composite producer are
        # -- and it names a module with no CLI at all, so a reader who runs it gets exit 0 and no
        # output. This exact sentence carried the stale name for the whole of the arc.
        label='the docs name a planet stage that has no entry point to require a body',
        path='docs/pipeline.md',
        needle='**The four planet-raster stages take a required `--body`**: `planet_pass`,',
        replacement='**The four planet-raster stages take a required `--body`**: `shade_planet`,',
        guard='test_every_stage_the_docs_name_actually_refuses_an_empty_argv',
    ),
    Sabotage(
        suite='python',
        # The wrapper forwards argv to one module while the resolver parses it with another. Both
        # halves keep working on today's flags, because the two grammars still overlap; what breaks
        # is the day one of them grows a flag, and nothing about the failure points here.
        label='the harness forwards its argv to a module the cap resolver does not parse with',
        path='pipeline/profile/run_pass.sh',
        needle='"$VENV" -u -m pipeline.tile.planet_pass "$@" 2>&1',
        replacement='"$VENV" -u -m pipeline.tile.shade_planet "$@" 2>&1',
        guard='test_the_shell_and_the_resolver_name_the_same_module',
    ),
    Sabotage(
        suite='python',
        # A figure this module argues from goes stale against PROCESS, which is what it points at.
        # Both retired figures got here exactly this way and neither was noticed: the prose still
        # reads as sourced, and a reader who follows the pointer finds a different number with
        # nothing saying the two disagree.
        label='the module argues from a composite peak PROCESS no longer carries',
        path='pipeline/profile/pass_cap.py',
        needle='- Earth at z8: `cap_render` **14.41 GiB** · composite **12.56 GiB**',
        replacement='- Earth at z8: `cap_render` **14.41 GiB** · composite **11.02 GiB**',
        guard='test_every_figure_the_module_argues_from_is_one_PROCESS_still_carries',
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
    # The panel's own defect, restored: indexing `sizes[0]` unconditionally asks for
    # `<slug>-undefined.webp`, which 404s behind a spinner. Nothing on Earth reaches it today, which
    # is exactly why it survived — the branch only became reachable when a body with no renders
    # arrived.
    Sabotage(
        suite='web',
        label='an unrendered place asks for a hero variant that does not exist',
        path='web/src/lib/detailPanel.ts',
        needle='    sizes.length === 0\n      ? null\n      : {',
        replacement='    false\n      ? null\n      : {',
        guard='yields NO figure for an unrendered country rather than a broken image',
    ),
    # A portrait hero's key names its HEIGHT. Taking the descriptor from the key overstates every
    # portrait variant's width, so the browser settles for a rung too small — and the picture is
    # still a picture, just softer than the one that was asked for.
    Sabotage(
        suite='web',
        label='srcset descriptors claim the long edge instead of the real width',
        path='web/src/lib/detailPanel.ts',
        needle='  return Math.round(longEdge * Math.min(1, aspect));',
        replacement='  return longEdge;',
        guard='narrows a portrait variant to its real width',
    ),
    # Re-couples the card to Earth's manifest. Earth goes on working, because Earth's builder is the
    # one supplying the field — which is what makes this invisible without a shape assertion.
    Sabotage(
        suite='web',
        label='a country field creeps back into the body-neutral content contract',
        path='web/src/lib/detailPanel.ts',
        needle='  return {\n    eyebrow: countrySummary(country),',
        replacement='  return {\n    slug,\n    eyebrow: countrySummary(country),',
        guard='names no country field',
    ),
    # Half a rename. The selector resolves to null, the non-null assertion throws — but only when a
    # card is actually opened, which no unit test does.
    Sabotage(
        suite='web',
        label='a querySelector keeps a class the markup no longer carries',
        path='web/src/components/Globe.astro',
        needle='panel.querySelector(".dp-note")!.textContent = content.note;',
        replacement='panel.querySelector(".dp-caption")!.textContent = content.note;',
        guard='selects only classes the markup actually carries',
    ),
    # The note goes back to being a sentence in the markup that claims the card shows a ray-traced
    # render. True on Earth, false on Mars, and nothing renders differently on Earth either way.
    Sabotage(
        suite='web',
        label='the note stops being written and goes back to the markup',
        path='web/src/components/Globe.astro',
        needle='    <p class="dp-note"></p>',
        replacement='    <p class="dp-note">A ray-traced relief render.</p>',
        guard="leaves every slot in the markup empty, the note and the link's wording included",
    ),
    # THE FEATURE INDEX IS GUARDED FROM TWO SIDES, and the cases below are split the same way. The
    # PRODUCER's mutations are caught in pytest, because the shipped file still says what it always
    # said; the shipped FILE's mutations are caught in vitest, which is the only side that runs on a
    # checkout with no gazetteer on it. Neither side sees the other's wound.
    Sabotage(
        suite='python',
        label='the gazetteer record entered twice survives as two index rows',
        path='web/scripts/gen_feature_index.py',
        needle='        unique.setdefault(tuple(sorted(record.items(), key=lambda item: item[0])), record)',
        replacement='        unique.setdefault((len(unique),), record)',
        guard='test_rows_agreeing_in_every_field_collapse',
    ),
    # The plausible wrong collapse, and the reason the key is the whole row. It is indistinguishable
    # from the right one on today's catalogue — both emit 1,919 rows — and starts deleting features
    # the first time the IAU adopts a name that is already in use somewhere else on the planet.
    Sabotage(
        suite='python',
        label='the collapse keys on the name, so two different features become one',
        path='web/scripts/gen_feature_index.py',
        needle='        unique.setdefault(tuple(sorted(record.items(), key=lambda item: item[0])), record)',
        replacement='        unique.setdefault((record["name"],), record)',
        guard='test_a_shared_name_over_different_data_keeps_both',
    ),
    Sabotage(
        suite='python',
        label='a zero diameter is carried as a size rather than as none',
        path='web/scripts/gen_feature_index.py',
        needle='        "diameterKm": round(diameter, DIAMETER_PRECISION) if diameter > 0 else None,',
        replacement='        "diameterKm": round(diameter, DIAMETER_PRECISION) if diameter >= 0 else None,',
        guard='test_a_zero_diameter_becomes_null_rather_than_zero',
    ),
    Sabotage(
        suite='python',
        label='the sort drops its position tie-break, so input order reaches the output',
        path='web/scripts/gen_feature_index.py',
        needle='    records.sort(key=lambda row: (row["name"], row["longitude"], row["latitude"]))',
        replacement='    records.sort(key=lambda row: row["name"])',
        guard='test_the_input_order_cannot_reach_the_output',
    ),
    # A change no unit test over the producer can see, because it alters the SERIALISATION and not
    # the records: 69 names carry diacritics and would ship as \u escapes. Only regenerating the
    # committed file and comparing bytes catches it, which is what that test exists to prove it can.
    Sabotage(
        suite='python',
        label='the writer escapes non-ASCII, so the committed index stops matching it',
        path='web/scripts/gen_feature_index.py',
        needle='    args.out.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\\n",',
        replacement='    args.out.write_text(json.dumps(records, indent=2, ensure_ascii=True) + "\\n",',
        guard='test_regenerating_reproduces_the_committed_bytes',
    ),
    # Below: the shipped file, mutated one row at a time. Aarna is the anchor because its longitude
    # is unique in the file; the block re-anchors if the IAU restates it.
    Sabotage(
        suite='web',
        label='a centre keeps the gazetteer east-positive longitude instead of the folded one',
        path='web/src/lib/featureIndex.json',
        needle='    "longitude": -21.57,',
        replacement='    "longitude": 338.43,',
        guard='puts every centre inside the window the tile grid addresses',
    ),
    Sabotage(
        suite='web',
        label='a row loses the etymology the whole card is made of',
        path='web/src/lib/featureIndex.json',
        needle='    "origin": "Village in Rajasthan, India.",\n    "gazetteer": "https://planetarynames.wr.usgs.gov/Feature/16115",',
        replacement='    "origin": "",\n    "gazetteer": "https://planetarynames.wr.usgs.gov/Feature/16115",',
        guard='populates every string field on every row',
    ),
    Sabotage(
        suite='web',
        label='a diameter of zero reaches the index as a size',
        path='web/src/lib/featureIndex.json',
        needle='    "diameterKm": 43.0,\n    "longitude": -21.57,',
        replacement='    "diameterKm": 0,\n    "longitude": -21.57,',
        guard='never carries a zero or a negative',
    ),
    # The one that only the cross-module pin can see. A string passes every range check written over
    # this file — `"43.0" > 0` is true in JS — and is read by the TILES' own reader as no diameter
    # at all, which is a feature findable by search and unpointable by finger.
    Sabotage(
        suite='web',
        label='a diameter ships as a string, which the tiles read as no diameter',
        path='web/src/lib/featureIndex.json',
        needle='    "diameterKm": 43.0,\n    "longitude": -21.57,',
        replacement='    "diameterKm": "43.0",\n    "longitude": -21.57,',
        guard='reads a missing diameter the same way the tiles do',
    ),
    Sabotage(
        suite='web',
        label='two rows share a name, so a lookup can only ever return one of them',
        path='web/src/lib/featureIndex.json',
        needle='    "name": "Aarna",\n    "cleanName": "Aarna",',
        replacement='    "name": "Gale",\n    "cleanName": "Gale",',
        guard='leaves no name on two rows',
    ),
    # THE CARD'S OUTBOUND LINK, WHICH IS THE ONE FIELD NO RENDERED PAGE CAN FALSIFY. A wrong address
    # serialises, type-checks, styles and reads exactly like a right one, all the way to the click —
    # so every wound below is deliberately one a screenshot would ratify.
    Sabotage(
        suite='python',
        label='the gazetteer page ships with the scheme the publisher redirects away from',
        path='web/scripts/gen_feature_index.py',
        needle='    return "https://" + published.removeprefix("http://")',
        replacement='    return published',
        guard='test_the_publishers_http_becomes_the_https_it_redirects_to',
    ),
    Sabotage(
        suite='python',
        label='an address that is not a feature page is written into the index anyway',
        path='web/scripts/gen_feature_index.py',
        needle='    if not shape.match(published):',
        replacement='    if False:',
        guard='test_an_address_that_is_not_a_feature_page_stops_the_run',
    ),
    Sabotage(
        suite='python',
        label='a name resolving to two pages picks one and looks correct',
        path='web/scripts/gen_feature_index.py',
        needle='    ambiguous = sorted(name for name, pages in links.items() if len(pages) > 1)',
        replacement='    ambiguous = sorted(name for name, pages in links.items() if len(pages) > 2)',
        guard='test_a_name_with_two_pages_stops_the_run',
    ),
    Sabotage(
        suite='python',
        label='an anchor with no page writes a row whose card goes nowhere',
        path='web/scripts/gen_feature_index.py',
        needle='        if name not in links:',
        replacement='        if False:',
        guard='test_an_anchor_with_no_gazetteer_page_stops_the_run',
    ),
    # THE GALLERY MANIFEST IS A CONTRACT SPLIT ACROSS TWO LANGUAGES and, unlike the feature index,
    # neither half ships: `countries.json` is gitignored, so nothing anywhere compares the payload
    # to `Country`. These four are what that comparison is worth.
    Sabotage(
        suite='python',
        label='the payload stops emitting the terms a query matches',
        path='web/scripts/gen_manifest.py',
        needle='        searchTerms=search_terms(record, resolved["admin"], resolved.get("also", ())),',
        replacement='',
        guard='test_the_payload_and_the_interface_name_the_same_fields',
    ),
    # The authored half of the terms. Dropping the argument leaves a working manifest that has
    # silently lost every name Natural Earth does not publish — ten countries, no error anywhere.
    Sabotage(
        suite='python',
        label='the row stops carrying the authored aliases',
        path='web/scripts/gen_manifest.py',
        needle='        searchTerms=search_terms(record, resolved["admin"], resolved.get("also", ())),',
        replacement='        searchTerms=search_terms(record, resolved["admin"]),',
        guard='test_a_row_carries_the_authored_aliases',
    ),
    Sabotage(
        suite='python',
        label='search_terms ignores what the config authored',
        path='web/scripts/gen_manifest.py',
        needle='            [str(value).strip() for value in also]:',
        replacement='            []:',
        guard='test_authored_names_land_after_the_columns',
    ),
    Sabotage(
        suite='python',
        label='an authored alias may restate a column the manifest already reads',
        path='config/countries.toml',
        needle='also = ["Burma"]',
        replacement='also = ["Republic of the Union of Myanmar"]',
        guard='test_no_alias_restates_something_the_columns_already_give',
    ),
    Sabotage(
        suite='python',
        label='aliases are authored against a slug no country resolves to',
        path='config/countries.toml',
        needle='[countries.myanmar]',
        replacement='[countries.myanmarr]',
        guard='test_every_aliased_slug_is_a_country_that_exists',
    ),
    Sabotage(
        suite='python',
        label='`also` stops reaching the resolver',
        path='pipeline/frame/country_config.py',
        needle='        also=list(tbl.get("also", [])),',
        replacement='        also=[],',
        guard='test_resolve_carries_also_and_defaults_to_a_list',
    ),
    Sabotage(
        suite='python',
        label='a repeated alias the fold would merge is accepted',
        path='pipeline/frame/country_config.py',
        needle='            and len({v.strip().casefold() for v in value}) == len(value))',
        replacement='            and len({v.strip() for v in value}) == len(value))',
        guard='test_load_config_rejects_bad',
    ),
    Sabotage(
        suite='python',
        label='a blank alias is accepted',
        path='pipeline/frame/country_config.py',
        needle='            and all(isinstance(v, str) and v.strip() for v in value)',
        replacement='            and all(isinstance(v, str) for v in value)',
        guard='test_load_config_rejects_bad',
    ),
    # The wrong-looking-right revert. Natural Earth publishes both spellings and the bare pair reads
    # as the obvious one; taking it loses France, Norway and three others with every gate green.
    Sabotage(
        suite='python',
        label='the ISO columns revert to the pair that is null wherever a code is contested',
        path='web/scripts/gen_manifest.py',
        needle='"ISO_A2_EH", "ISO_A3_EH")',
        replacement='"ISO_A2", "ISO_A3")',
        guard='test_the_bare_iso_columns_are_not_read',
    ),
    Sabotage(
        suite='python',
        label="Natural Earth's null becomes a spelling a visitor can type",
        path='web/scripts/gen_manifest.py',
        needle='        if value and value != NE_NULL and value != name and value not in terms:',
        replacement='        if value and value != name and value not in terms:',
        guard='test_natural_earths_null_is_not_a_search_term',
    ),
    Sabotage(
        suite='python',
        label='the display name is repeated as one of its own alternatives',
        path='web/scripts/gen_manifest.py',
        needle='        if value and value != NE_NULL and value != name and value not in terms:',
        replacement='        if value and value != NE_NULL and value not in terms:',
        guard='test_the_display_name_is_not_repeated',
    ),
    Sabotage(
        suite='python',
        label='the acquirer stops reading the links it hands the card',
        path='pipeline/acquire/download_nomenclature.py',
        needle='    astray = [row["name"] for row in rows '
                'if not FEATURE_URL.match((row.get("link") or "").strip())]',
        replacement='    astray = []',
        guard='test_a_link_that_is_not_a_feature_page_is_refused',
    ),
    Sabotage(
        suite='web',
        label='a shipped row points at a host that is not the gazetteer',
        path='web/src/lib/featureIndex.json',
        needle='    "gazetteer": "https://planetarynames.wr.usgs.gov/Feature/16115",',
        replacement='    "gazetteer": "https://example.com/Feature/16115",',
        guard='gives every row a live gazetteer page rather than an address shaped like one',
    ),
    # Two features describing themselves correctly and linking to the same entry — the whole-row
    # collapse upstream cannot see this, because the rest of the two rows genuinely differs.
    Sabotage(
        suite='web',
        label='two features are sent to one gazetteer entry',
        path='web/src/lib/featureIndex.json',
        needle='    "gazetteer": "https://planetarynames.wr.usgs.gov/Feature/16115",',
        replacement='    "gazetteer": "https://planetarynames.wr.usgs.gov/Feature/2071",',
        guard='sends no two features to the same entry',
    ),
    Sabotage(
        suite='web',
        label='the Mars card goes back to having nowhere to send a reader',
        path='web/src/lib/detailPanel.ts',
        needle='    link: { href: feature.gazetteer, label: GAZETTEER_LINK_LABEL, external: true },',
        replacement='    link: null,',
        guard='sends a reader to the IAU entry the note is quoting, in a new tab',
    ),
    # The wording drifting back to one string for both bodies, which is the defect this replaced:
    # a Mars card promising a full-size render over a body that has none.
    Sabotage(
        suite='web',
        label='both bodies label their link the same way again',
        path='web/src/lib/detailPanel.ts',
        needle='export const GAZETTEER_LINK_LABEL = "IAU Gazetteer entry →";',
        replacement='export const GAZETTEER_LINK_LABEL = "Open full-size render →";',
        guard="labels the two bodies' links differently, or one card lies about where it goes",
    ),
    Sabotage(
        suite='web',
        label='the link wording goes back into the markup, where one body must be wrong',
        path='web/src/components/Globe.astro',
        needle='    <a class="dp-link" href="/"></a>',
        replacement='    <a class="dp-link" href="/">Open full-size render →</a>',
        guard="leaves every slot in the markup empty, the note and the link's wording included",
    ),
    # Only the true case of a per-card field written, over a reused element. Unreachable today
    # because one document wires one builder — which is the accident this refuses to lean on.
    Sabotage(
        suite='web',
        label='the link honours external in one direction only',
        path='web/src/components/Globe.astro',
        needle='        linkEl.removeAttribute("target");',
        replacement='        linkEl.setAttribute("target", "_self");',
        guard='honours both values of external, not just the one its own body asks for',
    ),
    # THE GAZETTEER LISTING. Every wound here is one that renders as a perfectly good page — a
    # findable name that is not findable, a lettered section that quietly holds nothing, a listing
    # and a card describing the same feature two different ways.
    Sabotage(
        suite='web',
        label='the hemisphere letter is taken from the wrong side of zero',
        path='web/src/lib/gazetteer.ts',
        needle='  const northSouth = `${Math.round(Math.abs(latitude))}° ${latitude >= 0 ? "N" : "S"}`;',
        replacement='  const northSouth = `${Math.round(Math.abs(latitude))}° ${latitude > 0 ? "N" : "S"}`;',
        guard='puts a point on the line in the positive hemisphere rather than printing nothing',
    ),
    Sabotage(
        suite='web',
        label='a position truncates towards the equator instead of rounding',
        path='web/src/lib/gazetteer.ts',
        needle='  const eastWest = `${Math.round(Math.abs(longitude))}° ${longitude >= 0 ? "E" : "W"}`;',
        replacement='  const eastWest = `${Math.trunc(Math.abs(longitude))}° ${longitude >= 0 ? "E" : "W"}`;',
        guard='rounds rather than truncates, so a feature does not drift a degree towards the equator',
    ),
    Sabotage(
        suite='web',
        label='the grouping re-sorts and throws away the collation the page was read in',
        path='web/src/lib/gazetteer.ts',
        needle='  for (const entry of sorted) {',
        replacement='  for (const entry of [...sorted].toSorted()) {',
        guard="keeps the caller's order and does not sort again",
    ),
    Sabotage(
        suite='web',
        label='the gallery goes back to its own copy of the coordinate format',
        path='web/src/components/Gallery.astro',
        needle='  const { latitude, longitude } = boundsCentre(country.bbox);',
        replacement='  const { latitude, longitude } = { latitude: 0, longitude: 0 };',
        guard='is what the gallery calls, so one page cannot drift from the other',
    ),
    # The 69 diacritic names becoming unfindable by the only search this page has. The page still
    # renders every one of them, and every other assertion about it stays true.
    Sabotage(
        suite='web',
        label='the diacritic-free name stops being text the browsers find can match',
        path='web/src/pages/mars/lite.astro',
        needle='                      <span class="gz-alias">{feature.cleanName}</span>',
        replacement='                      <span class="gz-alias" title={feature.cleanName} />',
        guard='renders the diacritic-free name as text wherever it differs',
    ),
    Sabotage(
        suite='web',
        label='Mars letters on the published name, filing the diacritics past Z',
        path='web/src/pages/mars/lite.astro',
        needle='const byLetter = byInitial(alphabetical, (feature) => feature.cleanName[0]!);',
        replacement='const byLetter = byInitial(alphabetical, (feature) => feature.name[0]!);',
        guard='letters the page on cleanName, and the cost of not doing is measured rather than assumed',
    ),
    Sabotage(
        suite='web',
        label='the listing writes its own kind label instead of the cards',
        path='web/src/pages/mars/lite.astro',
        needle='                    <span class="gz-kind">{featureTypeLabel(feature.type)}</span>',
        replacement='                    <span class="gz-kind">{feature.type}</span>',
        guard="reads the card's own formatters rather than writing a second kind and size",
    ),
    # THE SEARCH CONTROL'S TWO SEAMS. The control is built with the rail and armed later from the
    # scope its catalogue and pick path live in, so what used to be one block is now two halves that
    # can fall out of step. Both mutations below leave a button that appears, presses and lists.
    #
    # NOT COVERED HERE, and it cannot be: the guard that the control is built OUTSIDE the idle
    # wiring has a code LOCATION for a subject, and one string replacement cannot express a move.
    # It was proved by hand against `git show HEAD:...` instead — the pre-move source fails it.
    Sabotage(
        suite='web',
        # The row is chosen, the panel closes, and nothing flies or opens. A field that lists the
        # right answers and does nothing with them reads as a dead globe rather than a dead binding.
        label='the chosen row stops reaching the pick path it was pointed at',
        path='web/src/components/Globe.astro',
        needle='      onChoose: (entry) => searchPick?.(entry.name),',
        replacement='      onChoose: () => {},',
        guard='routes a chosen row through goToFeature, so one card is built one way',
    ),
    Sabotage(
        suite='web',
        # Born available, before anything can answer: the button looks live from first paint and a
        # query typed in the window before the catalogue lands returns "No feature matches that."
        label='the search button is live before it has a catalogue to search',
        path='web/src/components/Globe.astro',
        needle='    searchToggle.setAvailable(false, `${searchLabel} (loading the catalogue)`);',
        replacement='    searchToggle.setAvailable(true);',
        guard='greys the button until the catalogue lands, rather than looking live and doing nothing',
    ),
    # THE SEARCH MATCHER. Every wound below leaves a search box that works: it accepts a query, it
    # returns features, and the ones it returns are real. What changes is which names have become
    # unreachable, and a visitor who cannot find Koval'sky has no way to tell that from a visitor
    # who misremembered the name. Nothing renders wrong, so nothing but these guards can see it.
    Sabotage(
        suite='web',
        label='the fold is "simplified" to the one-liner that leaves a letter standing',
        path='web/src/lib/catalogueSearch.ts',
        needle='    .replace(/ł/g, "l")\n',
        replacement='',
        guard='folds the letter NFD cannot decompose, and the naive rule is shown to miss it',
    ),
    Sabotage(
        suite='web',
        label='a punctuated word keeps only its pieces, so the name typed without punctuation is lost',
        path='web/src/lib/catalogueSearch.ts',
        needle='  return joined ? [joined, ...word.split(/[^a-z0-9]+/).filter(Boolean)] : [];',
        replacement='  return word.split(/[^a-z0-9]+/).filter(Boolean);',
        guard='keeps both readings of a punctuated word, because different queries want different ones',
    ),
    Sabotage(
        suite='web',
        label='a punctuated word keeps only its joined form, so the part after the hyphen is lost',
        path='web/src/lib/catalogueSearch.ts',
        needle='  return joined ? [joined, ...word.split(/[^a-z0-9]+/).filter(Boolean)] : [];',
        replacement='  return joined ? [joined] : [];',
        guard='keeps both readings of a punctuated word, because different queries want different ones',
    ),
    Sabotage(
        suite='web',
        label='the query stops splitting on punctuation, so a name typed as published finds nothing',
        path='web/src/lib/catalogueSearch.ts',
        needle='  return foldForSearch(query)\n    .split(/[^a-z0-9]+/)',
        replacement='  return foldForSearch(query)\n    .split(/\\s+/)',
        guard='splits a query on punctuation as well as spaces',
    ),
    # The descriptor half, which is the only route to a crater — 1,233 features whose names never
    # say what they are. Losing it leaves a search box that answers everything except the word a
    # visitor is most likely to type first.
    Sabotage(
        suite='web',
        label='the kind stops being searchable, so no crater can be found by asking for one',
        path='web/src/lib/catalogueSearch.ts',
        needle='      if (!onName && !everyTermPrefixes(terms, row.everyToken)) continue;',
        replacement='      if (!onName) continue;',
        guard='is the only way to reach a crater, because no crater name says so',
    ),
    Sabotage(
        suite='web',
        label='a kind match can outrank a name match, so the feature asked for sinks below its kin',
        path='web/src/lib/catalogueSearch.ts',
        needle='  if (first.tier !== second.tier) return first.tier - second.tier;\n',
        replacement='',
        guard='ranks a name below nothing — a kind match never outranks a name match',
    ),
    Sabotage(
        suite='web',
        label='one term is enough, so a two-word query returns everything either word touches',
        path='web/src/lib/catalogueSearch.ts',
        needle='  return terms.every((term) => tokens.some((token) => token.startsWith(term)));',
        replacement='  return terms.some((term) => tokens.some((token) => token.startsWith(term)));',
        guard='still needs every term, whichever half answers each one',
    ),
    Sabotage(
        suite='web',
        label='where the query landed stops ordering, so the exact name sinks under the cap',
        path='web/src/lib/catalogueSearch.ts',
        needle='  if (first.lead !== second.lead) return first.lead - second.lead;\n',
        replacement='',
        guard='puts the whole name first, then the names that start with the query',
    ),
    Sabotage(
        suite='web',
        label='the size tie-break inverts, so a broad query answers with the smallest things on Mars',
        path='web/src/lib/catalogueSearch.ts',
        needle='  if (firstWeight !== secondWeight) return secondWeight - firstWeight;',
        replacement='  if (firstWeight !== secondWeight) return firstWeight - secondWeight;',
        guard='breaks a tie on size, largest first, with the unsized last',
    ),
    Sabotage(
        suite='web',
        label='the total reports the page rather than the catalogue, so "10 of 160" reads "10 of 10"',
        path='web/src/lib/catalogueSearch.ts',
        needle='      total: found.length,',
        replacement='      total: Math.min(found.length, Math.max(0, limit)),',
        guard='counts every match and returns only the page asked for',
    ),
    # THE BUNDLE SEAM, AND THE MUTATION IS THE EDIT SOMEONE WOULD ACTUALLY MAKE. `import { type X }`
    # type-checks, erases the binding and STILL emits the module — so Earth silently starts
    # downloading Martian place names with every other gate green and no visible change anywhere.
    Sabotage(
        suite='web',
        label='the type import becomes an inline-type import, which keeps the catalogue in the graph',
        path='web/src/lib/detailPanel.ts',
        needle='import type { NamedFeature } from "./featureIndex";',
        replacement='import { type NamedFeature } from "./featureIndex";',
        guard='keeps the catalogue off the chunk both bodies share',
    ),
    Sabotage(
        suite='web',
        # The row and the card's eyebrow become two expressions again. They agree on the day it is
        # written, which is the whole difficulty: the drift arrives with whichever one gains a unit.
        label='the search row writes its own summary instead of sharing the eyebrow',
        path='web/src/lib/detailPanel.ts',
        needle='    descriptor: featureSummary(feature),',
        replacement='    descriptor: featureTypeLabel(feature.type),',
        guard='writes one summary for the eyebrow and the search row, rather than two that agree today',
    ),
    Sabotage(
        suite='web',
        # The matcher is handed the card's LABEL instead of the gazetteer's singular/plural pair, so
        # "craters" answers nothing while "crater" keeps working — half a kind, silently.
        label="the matcher is given the kind's label rather than the pair it is published as",
        path='web/src/lib/detailPanel.ts',
        needle='    terms: [feature.type],',
        replacement='    terms: [featureTypeLabel(feature.type)],',
        guard='hands the matcher the RAW gazetteer type, or half of every kind stops being typeable',
    ),
    # THE SEARCH FIELD. Every wound below leaves a panel that opens, lists real features and flies
    # to them — what breaks is the part a screenshot ratifies and a visitor discovers later: a
    # panel that will not close, a highlight that is not what Enter acts on, a count that lies
    # about how much was dropped.
    #
    # THE FIRST ONE IS THE BUG THAT ACTUALLY SHIPPED, restored verbatim. A bare `close()` has no
    # local to bind to and resolves to `window.close` — real, argument-free, `void` — so it
    # type-checks, lints and runs. Only a browser can tell the difference.
    Sabotage(
        suite='web',
        label='choosing a row calls the global close(), so the panel stays over the card it opened',
        path='web/src/lib/catalogueSearchBox.ts',
        needle='    if (!entry) return;\n    setOpen(false);',
        replacement='    if (!entry) return;\n    close();',
        guard='closes itself before handing the feature over, so the card is not opened underneath it',
    ),
    Sabotage(
        suite='web',
        label='Escape calls the global close() too, so the field cannot be dismissed',
        path='web/src/lib/catalogueSearchBox.ts',
        needle='      setOpen(false);\n      return;',
        replacement='      close();\n      return;',
        guard='CLOSES ON ESCAPE — the branch a global shadow silently took over',
    ),
    Sabotage(
        suite='web',
        label='a row waits for click, so the field loses focus and closes under the pointer first',
        path='web/src/lib/catalogueSearchBox.ts',
        needle='      row.addEventListener("mousedown", (event) => {',
        replacement='      row.addEventListener("click", (event) => {',
        guard='acts on mousedown, because losing focus on mouse-down would close the panel mid-click',
    ),
    Sabotage(
        suite='web',
        label='Enter takes the first row rather than the armed one, so the arrows steer nothing',
        path='web/src/lib/catalogueSearchBox.ts',
        needle='      choose(active);',
        replacement='      choose(0);',
        guard='chooses the ARMED row, not the first one',
    ),
    Sabotage(
        suite='web',
        label='the arrows clamp instead of wrapping, so the last row cannot be reached upwards',
        path='web/src/lib/catalogueSearchBox.ts',
        needle='    setActive((active + step + shown.length) % shown.length);',
        replacement='    setActive(Math.min(shown.length - 1, Math.max(0, active + step)));',
        guard='moves the armed row and wraps at both ends',
    ),
    Sabotage(
        suite='web',
        label='the panel stops saying how many it dropped, so eight rows read as the whole answer',
        path='web/src/lib/catalogueSearchBox.ts',
        needle='    else if (results.total > results.matches.length)',
        replacement='    else if (false)',
        guard='answers a kind, which is the only route to a crater',
    ),
    Sabotage(
        suite='web',
        label='the alias is drawn on every row, so most names carry a bracketed copy of themselves',
        path='web/src/lib/catalogueSearchBox.ts',
        needle='        entry.alias === null\n          ? null',
        replacement='        false\n          ? null',
        guard='shows the diacritic-free spelling only where it differs',
    ),
    # The painted highlight and the row Enter acts on drifting apart — the list then shows one
    # answer and delivers another, which is the failure a visitor blames on themselves.
    Sabotage(
        suite='web',
        label='the field stops naming the armed row, so assistive tech and the paint disagree',
        path='web/src/lib/catalogueSearchBox.ts',
        needle='    if (active >= 0) field.setAttribute("aria-activedescendant", `${OPTION_ID_PREFIX}${active}`);',
        replacement='    if (false) field.setAttribute("aria-activedescendant", `${OPTION_ID_PREFIX}${active}`);',
        guard='keeps the highlight and the armed row as one fact, so Enter cannot surprise',
    ),
    Sabotage(
        suite='web',
        label='opening twice re-announces and re-steals focus mid-typing',
        path='web/src/lib/catalogueSearchBox.ts',
        needle='    if (next === opened) return; // idempotent',
        replacement='    if (false) return; // idempotent',
        guard='is idempotent, so a repeated open does not re-steal focus or re-announce',
    ),
    # The page's half. Each of these leaves a working search box in the wrong relationship to
    # something else on the page, which is exactly what no unit test of the widget can see.
    Sabotage(
        suite='web',
        label='the search button joins the frame group, so the rail stops stating the concern',
        path='web/src/components/Globe.astro',
        needle='    joinRailGroup(map.getContainer(), ".maplibregl-ctrl-zoom-in", searchToggle.button);',
        replacement='    joinRailGroup(map.getContainer(), ".maplibregl-ctrl-fullscreen", searchToggle.button);',
        guard='mounts the button in the CAMERA group, which is what the placement argument rests on',
    ),
    Sabotage(
        suite='web',
        label='the card is left open under the search panel that shares its corner',
        path='web/src/components/Globe.astro',
        needle='        if (open) closePanel();',
        replacement='        if (false) closePanel();',
        guard='dismisses the card when the field opens, because the two share one corner',
    ),
    Sabotage(
        suite='web',
        label='hiding the controls leaves the search field floating beside a vanished rail',
        path='web/src/components/Globe.astro',
        needle='    if (next) searchPanel?.close();',
        replacement='    if (false) searchPanel?.close();',
        guard='hands the panel to quiet mode, which cannot reach it through the stylesheet',
    ),
    Sabotage(
        suite='web',
        label='the search field narrows back to the one body that used to have it',
        path='web/src/components/Globe.astro',
        needle='  if (subsystems.vectorProduct !== null) {',
        replacement='  if (subsystems.vectorProduct === "features") {',
        guard='arms the search field for every product the registry can hand it',
    ),
    # The other half of that gate, and the one no type can see: a body may be gated IN and never
    # arm. The button is born disabled, so what ships is a control that is present, greyed and
    # captioned "loading the catalogue" forever — a rail that merely looks slow.
    Sabotage(
        suite='web',
        label='Earth gets a search button and nothing ever arms it',
        path='web/src/components/Globe.astro',
        needle='      matcher = createCatalogueSearch(manifest.countries.map(countrySearchEntry));',
        replacement='',
        guard='arms the search field for every product the registry can hand it',
    ),
    # A ROW THAT RENDERS CORRECTLY AND SEARCHES WRONGLY, which is the whole reason `alias` and
    # `terms` are separate fields. Shown-versus-matched cannot be checked by looking at a screenshot.
    Sabotage(
        suite='web',
        label="the country's other spellings are shown instead of matched",
        path='web/src/lib/detailPanel.ts',
        needle='    terms: [...country.searchTerms, country.continent],',
        replacement='    terms: [country.continent],',
        guard='carries every manifest term through, so a column added upstream is typeable at once',
    ),
    Sabotage(
        suite='web',
        label='the continent stops being typeable, so "africa" answers with nothing',
        path='web/src/lib/detailPanel.ts',
        needle='    terms: [...country.searchTerms, country.continent],',
        replacement='    terms: [...country.searchTerms],',
        guard='makes the continent both the descriptor and a term, which no other field is',
    ),
    Sabotage(
        suite='web',
        label='the card and the search row compose the same line twice',
        path='web/src/lib/detailPanel.ts',
        needle='    descriptor: countrySummary(country),',
        replacement='    descriptor: country.continent,',
        guard='writes one summary for the eyebrow and the search row',
    ),
    # THE TOKENISER. This is the wound that shipped: an abbreviation loses its joined reading and a
    # country becomes unreachable by the two letters everyone types for it — while every other query
    # in the catalogue keeps working, and the wrong country answers confidently in its place.
    Sabotage(
        suite='web',
        label='a punctuated term loses its joined reading, so "uk" cannot reach the United Kingdom',
        path='web/src/lib/catalogueSearch.ts',
        needle='  return [...new Set(terms.flatMap(phraseTokens))];',
        replacement='  return [...new Set(terms.flatMap((term) => '
                    'foldForSearch(term).split(/[^a-z0-9]+/).filter(Boolean)))];',
        guard='reads a punctuated term joined AND split, exactly as it reads a name',
    ),
    # THE NOUN. Both strings the field shows name the rows, and getting them from the body is what
    # stopped the widget saying "feature" on a planet of countries.
    Sabotage(
        suite='web',
        label='the search box goes back to naming one planet in its placeholder',
        path='web/src/lib/catalogueSearchBox.ts',
        needle='  field.placeholder = `Search ${noun.plural}`;',
        replacement='  field.placeholder = "Search features";',
        guard='takes both its user-facing strings from the body, naming no planet itself',
    ),
    Sabotage(
        suite='web',
        label='a body copies one spelling of its catalogue noun into both sentences',
        path='web/src/lib/bodies.ts',
        needle='    catalogue: { singular: "country", plural: "countries" },',
        replacement='    catalogue: { singular: "countries", plural: "countries" },',
        guard='gives every body two spellings of what its catalogue is of, and never the same one twice',
    ),
    Sabotage(
        suite='web',
        label='the button looks live before the catalogue lands, and answers nothing when pressed',
        path='web/src/components/Globe.astro',
        needle='    searchToggle.setAvailable(false, `${searchLabel} (loading the catalogue)`);',
        replacement='    searchToggle.setAvailable(true, `${searchLabel} (loading the catalogue)`);',
        guard='greys the button until the catalogue lands, rather than looking live and doing nothing',
    ),
    # THE SECOND ROUND, ALL FOUR REPORTED BY ROHAN LOOKING AT THE PAGE. Each wound below leaves a
    # panel that renders exactly as designed in a screenshot — what breaks is reachability, or what
    # is underneath, neither of which a still can carry.
    Sabotage(
        suite='web',
        label='the panel goes back to click-through, so every click on it flies the globe instead',
        path='web/src/styles/globe.css',
        needle='  pointer-events: auto;',
        replacement='  pointer-events: none;',
        guard='takes pointer events back for the panel, so a click on the field lands on the field',
    ),
    Sabotage(
        suite='web',
        label='the card goes back to sitting on top of the whole rail, on both bodies',
        path='web/src/components/Globe.astro',
        needle='    right: var(--rail-clearance);',
        replacement='    right: 1.2rem;',
        guard='clears the rail rather than covering it, on BOTH bodies',
    ),
    Sabotage(
        suite='web',
        label='a card opened from the globe lands on top of an open search panel',
        path='web/src/components/Globe.astro',
        needle='    searchPanel?.close();\n    panel.querySelector',
        replacement='    panel.querySelector',
        guard='closes the search panel when a card opens, which is the direction that was missing',
    ),
    Sabotage(
        suite='web',
        # The card goes back to dropping past the top-left row instead of the row yielding to it —
        # 48px of a ~660px screen spent to leave a strip of pills reading as debris above the card.
        label='the card drops below the chrome row again instead of taking the band',
        path='web/src/components/Globe.astro',
        needle='  .detail-panel {\n    position: fixed;\n    top: var(--page-inset);',
        replacement='  .detail-panel {\n    position: fixed;\n    top: 4.2rem;',
        guard='takes the whole narrow band rather than dropping below the row it would cover',
    ),
    Sabotage(
        suite='web',
        label='the panel keeps a desktop width ceiling on a phone, leaving dead space beside it',
        path='web/src/styles/globe.css',
        needle='    width: auto;',
        replacement='    width: min(22rem, calc(100vw - 5rem));',
        guard='fills the free width narrow by naming both edges, not by capping the width',
    ),
    Sabotage(
        suite='web',
        label='the rail button restates its own size, so the clearance can drift away from it',
        path='web/src/styles/globe.css',
        needle='  width: var(--rail-button-size);',
        replacement='  width: 2.15rem;',
        guard='derives the button size and the clearance from one declaration',
    ),
    Sabotage(
        suite='web',
        label='the shortcut stops answering, and the field can only be opened by hunting for it',
        path='web/src/lib/catalogueSearchBox.ts',
        needle='    if (event.key !== SEARCH_SHORTCUT) return;',
        replacement='    if (true) return;',
        guard='opens on the shortcut and puts the caret in the field',
    ),
    Sabotage(
        suite='web',
        label='the shortcut fires while typing, so a slash cannot be typed into the field it opens',
        path='web/src/lib/catalogueSearchBox.ts',
        needle='    if (isTypingTarget(event.target)) return;',
        replacement='    if (false) return;',
        guard='types a slash INTO the field rather than re-opening it',
    ),
    Sabotage(
        suite='web',
        label="Firefox's own quick-find opens underneath ours",
        path='web/src/lib/catalogueSearchBox.ts',
        needle="    event.preventDefault(); // Firefox's quick-find binds this key",
        replacement="    void 0; // Firefox's quick-find binds this key",
        guard='prevents the default, or Firefox quick-find opens underneath it',
    ),
    Sabotage(
        suite='web',
        label='a destroyed box leaves its key bound to a panel that is no longer on the page',
        path='web/src/lib/catalogueSearchBox.ts',
        needle='      doc.removeEventListener("keydown", onDocumentKeyDown);',
        replacement='      void 0;',
        guard='stops listening once destroyed, so a torn-down globe leaves no key bound',
    ),
    # THE FRAMING'S ONE HARD CONSTRAINT. At the ceiling the camera lands exactly where a region stops
    # being a target, so the highlight goes out on the feature you asked to be taken to — and every
    # arithmetic assertion still passes, because the arithmetic is doing what it was told.
    Sabotage(
        suite='web',
        label='the fly-to frames a feature at the size that stops it being a target',
        path='web/src/lib/featureTargeting.ts',
        needle='export const FLY_TO_VIEWPORT_FRACTION = 0.5;',
        replacement='export const FLY_TO_VIEWPORT_FRACTION = 0.7;',
        guard='stays under the ceiling that decides a feature can be pointed at',
    ),
    # Frames every feature as though it sat on the equator. Invisible on the half of the catalogue
    # that nearly does, and a whole zoom level out by 60 degrees.
    Sabotage(
        suite='web',
        label='the framing ignores how ground scale falls off with latitude',
        path='web/src/lib/featureTargeting.ts',
        needle='    2 * Math.PI * groundRadiusM * Math.cos((latitude * Math.PI) / 180);',
        replacement='    2 * Math.PI * groundRadiusM;',
        guard='takes cos(latitude) into account rather than framing every feature as equatorial',
    ),
    # Sizes the view for a camera position the transform refuses to reach. The seven polar centres
    # arrive too close, and nothing in the arithmetic can notice because the clamp happens later.
    Sabotage(
        suite='web',
        label='a polar feature is framed for a latitude the camera cannot reach',
        path='web/src/lib/featureTargeting.ts',
        needle='  const reachableLatitude = Math.max(\n    -MAX_CENTRE_LATITUDE,\n    Math.min(MAX_CENTRE_LATITUDE, latitude),\n  );',
        replacement='  const reachableLatitude = latitude;',
        guard='frames a polar feature for where the camera can actually go',
    ),
    # The projection's own zoom unit, not our asset tile size. Halving it is one zoom level on every
    # feature — and the unit test carries its own 512 rather than importing this, which is what lets
    # it disagree at all.
    Sabotage(
        suite='web',
        label='the framing scales the world by our tile size instead of the projection unit',
        path='web/src/lib/featureTargeting.ts',
        needle='const MERCATOR_TILE_PX = 512;',
        replacement='const MERCATOR_TILE_PX = 256;',
        guard='lands the diameter on the chosen share of the viewport reference',
    ),
    # An unsized feature framed at zoom 0 rather than left alone. The two zero-diameter features
    # would fly to a whole-planet view, which reads as a broken search result rather than a decision.
    Sabotage(
        suite='web',
        label='a feature with no diameter is framed instead of just centred',
        path='web/src/lib/featureTargeting.ts',
        needle='  if (diameterKm === null || !(diameterKm > 0)) return null;',
        replacement='  if (diameterKm === null || !(diameterKm > 0)) return 0;',
        guard='declines to size a feature the gazetteer publishes at zero',
    ),
    # --- the lookup that calls into the package it is describing -------------------------------------
    # `who_reads` invokes functions to answer a question ABOUT the store, which is the one instrument
    # here that can damage its own subject. Both cases below are widenings a future edit makes for
    # good reasons — cover more accessors, read the declaration more cheaply — and neither announces
    # itself: the first writes, the second just answers less.
    Sabotage(
        suite='python',
        label='the path lookup calls every function that returns a Path, writers included',
        path='scripts/who_reads.py',
        needle='ACCESSOR_SUFFIXES = ("_path", "_dir", "_root")',
        replacement='ACCESSOR_SUFFIXES = ("",)',
        guard='test_a_producer_that_returns_its_output_path_is_never_run',
    ),
    Sabotage(
        suite='python',
        label='the path lookup reads source declarations instead of executing them',
        path='scripts/who_reads.py',
        needle='    if not callable(supply) or _needs_an_argument(supply):',
        replacement='    if True:',
        guard='test_a_source_no_grep_could_find_is_reported',
    ),
    # The denoise device is the only Cycles setting the two callers of `scene_build` disagree about,
    # and every failure below is silent in the direction that matters. Losing the opt-in costs six
    # hours a pass and nothing reports it; gaining it on the hero path puts 203 pinned renders at a
    # frame size where the driver is known to fault; losing it from the recipe leaves two denoisers
    # writing one mosaic with nothing on disk saying which made which block.
    Sabotage(
        suite='python',
        label='the block runner stops asking for GPU denoise and silently pays CPU for the planet',
        path='pipeline/tile/block_render.py',
        needle=('            "--denoise-device", BLOCK_DENOISE_DEVICE,\n'
                '            "--base-grid", BLOCK_BASE_GRID]'),
        replacement='            "--base-grid", BLOCK_BASE_GRID]',
        guard='test_the_block_runner_opts_in',
    ),
    Sabotage(
        suite='python',
        label='the rig default flips to gpu, opting every hero into an untested frame size',
        path='pipeline/render/scene_build.py',
        needle='ap.add_argument("--denoise-device", choices=("cpu", "gpu"), default="cpu",',
        replacement='ap.add_argument("--denoise-device", choices=("cpu", "gpu"), default="gpu",',
        guard='test_the_default_the_hero_inherits_is_cpu',
    ),
    Sabotage(
        suite='python',
        label='the hero stage starts passing the denoise flag it must inherit instead',
        path='pipeline/frame/country_config.py',
        needle='         f" --body {bodies.EARTH.name} --render-dir {rd}"',
        replacement='         f" --body {bodies.EARTH.name} --render-dir {rd} --denoise-device gpu"',
        guard='test_the_hero_stage_does_not_pass_the_flag',
    ),
    Sabotage(
        suite='python',
        label='the block recipe forgets the denoise device, so switching it restages nothing',
        path='pipeline/tile/block_render.py',
        needle='        "denoise_device": BLOCK_DENOISE_DEVICE,',
        replacement='',
        guard='test_moving_it_moves_the_recipe',
    ),
    # The ice edge's softening. Each of the three below is silent: the alpha stays in 0..1, the
    # composite blends it, every other test passes, and what changes is the shape of an edge at
    # latitudes no unit test looked at until this one.
    Sabotage(
        suite='python',
        label='the tile producer stops softening, so only the cap side of the crossfade is smooth',
        path='pipeline/look/layer_producers.py',
        needle='        persistence_alpha = snow.soften_source_cells(\n'
               '            snow.snow_alpha(snow.unpack_persistence(window.raw), window.top, '
               'window.bottom),\n'
               '            window.ground_metres_per_px)',
        replacement='        persistence_alpha = snow.snow_alpha(\n'
                    '            snow.unpack_persistence(window.raw), window.top, window.bottom)',
        guard='test_the_tile_producer_feathers',
    ),
    Sabotage(
        suite='python',
        label='the north cap stops softening, so only the tile side of the crossfade is smooth',
        path='pipeline/look/perennial_ice.py',
        needle='    return snow.soften_source_cells(alpha, inputs.ground_metres_per_px)',
        replacement='    return alpha',
        guard='test_the_cap_producer_feathers',
    ),
    Sabotage(
        suite='python',
        label='sigma becomes a pixel count, so the blur stops tracking the source cell',
        path='pipeline/look/snow.py',
        needle='    return SOFTEN_FRACTION * SOURCE_CELL_M / np.maximum(ground_metres_per_px, 1e-6)',
        replacement='    return np.full(np.shape(ground_metres_per_px), 3.0)',
        guard='test_sigma_rises_with_latitude_exactly_as_one_over_cosine',
    ),
    Sabotage(
        suite='python',
        label='the banded filter drops its halo, so every band edge takes the array edge instead',
        path='pipeline/look/snow.py',
        needle='        halo = int(np.ceil(SOFTEN_HALO_SIGMAS * band_sigma))',
        replacement='        halo = 0',
        guard='test_a_varying_resolution_matches_a_per_row_reference',
    ),
    Sabotage(
        suite='python',
        label='the whole array becomes one band, which is the per-window sigma the arm had',
        path='pipeline/look/snow.py',
        needle='               and abs(sigma[end] - reference) <= SOFTEN_BAND_TOLERANCE * reference):',
        replacement='               and True):',
        guard='test_no_band_is_wider_in_sigma_than_the_tolerance_allows',
    ),
]


def run_suite(name: str, in_flight: str | None = None,
              only: str | None = None) -> tuple[bool, str]:
    """Run one suite, or just the one guard named by `only`. Returns (green, combined output).

    `only` is ignored where a suite cannot narrow: the caller still gets a correct answer, just a
    slower one. See `Suite.narrow`.
    """
    suite = SUITES[name]
    environment = {**os.environ, **suite.environment}
    if in_flight is not None:
        environment[IN_FLIGHT_ENV] = in_flight
    command = suite.command if only is None or suite.narrow is None else suite.narrow(only)
    result = subprocess.run(
        command,
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


def changed_paths(against: str) -> set[str]:
    """Repo-relative paths differing from `against`, staged, unstaged and untracked alike.

    All three, because `git diff <ref>` alone misses what is staged and misses new files entirely
    — which is the work most in need of a run.
    """
    paths: set[str] = set()
    for command in (["git", "diff", "--name-only", against],
                    ["git", "diff", "--name-only", "--cached", against],
                    ["git", "ls-files", "--others", "--exclude-standard"]):
        result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        paths.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return paths


def selected(pattern: str | None, suite: str | None, changed: str | None = None) -> list[Sabotage]:
    """The cases to run: by suite, by label substring, and by which files actually moved.

    PREFER `changed` TO `pattern`. A label names what breaks, so filtering on one finds the cases
    whose author reached for your word — it has twice selected a subset of a batch just added. A
    path cannot be phrased differently.
    """
    cases = SABOTAGES if suite is None else [case for case in SABOTAGES if case.suite == suite]
    if changed is not None:
        moved = changed_paths(changed)
        cases = [case for case in cases if case.path in moved]
    if pattern is None:
        return cases
    needle = pattern.lower()
    return [case for case in cases if needle in case.label.lower() or needle in case.path.lower()]


def judge_while_mutated(case: Sabotage) -> tuple[bool, str, bool]:
    """Run the narrow guard first and escalate to the whole suite unless it already answered.

    THE ESCALATION IS WHAT MAKES THE SHORTCUT SAFE. A narrow run that goes red naming this case's
    guard has settled it; every other outcome — nothing caught it, something else did, the `-k`
    selected nothing — is indistinguishable without the full suite. So `MISSED` and `WRONG` stay
    full-suite verdicts and no guard can be called vacuous by the fast path.

    The third return says whether that happened, since a run's cost is bimodal and a wall-clock
    total cannot show where it went.
    """
    green, output = run_suite(case.suite, in_flight=case.path, only=case.guard)
    if not green and any(case.guard in name for name in failing_tests(case.suite, output)):
        return green, output, False
    return (*run_suite(case.suite, in_flight=case.path), True)


def run_case(case: Sabotage, narrow: bool = True) -> tuple[bool, str, bool]:
    """Apply one sabotage, judge it, restore. Returns (green, output, escalated).

    `narrow=False` is for `--harvest`, which asks which tests catch a case: running only the guard
    you already named would answer with the name you put in.
    """
    target = REPO_ROOT / case.path
    judge = judge_while_mutated if narrow else (
        lambda one: (*run_suite(one.suite, in_flight=one.path), True))
    if not case.needle:
        target.write_text(case.replacement, encoding="utf-8")
        try:
            return judge(case)
        finally:
            target.unlink()

    backup = target.with_suffix(target.suffix + BACKUP_SUFFIX)
    source = target.read_text(encoding="utf-8")
    shutil.copy2(target, backup)
    try:
        target.write_text(source.replace(case.needle, case.replacement, 1), encoding="utf-8")
        target.touch()  # mtime, or a running Vite serves the sabotaged module after restore
        return judge(case)
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
    parser.add_argument(
        "--changed",
        nargs="?",
        const="HEAD",
        metavar="REF",
        help="only cases whose file differs from REF (default HEAD), untracked files included",
    )
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

    cases = selected(arguments.filter, arguments.suite, arguments.changed)
    if not cases:
        print(f"no case matches filter={arguments.filter!r} suite={arguments.suite!r} "
              f"changed={arguments.changed!r}")
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
    # THE DENOMINATOR, PRINTED, because a narrowed run's summary is a ratio over what it SELECTED
    # and reads exactly like a complete one. `--filter` matches LABELS, and a label names what
    # breaks rather than the noun you are hunting by: nine cases added for one layer, and
    # `--filter <layer>` selected seven, the two missed being named for their mechanism. Both were
    # caught once found, so the only cost was nearly reporting seven as the whole set.
    narrowed = "" if len(cases) == len(SABOTAGES) else (
        f" (of {len(SABOTAGES)}; the rest are not run)")
    print(f"{len(cases)} case(s){narrowed} across {', '.join(suites)}; "
          f"each edits a file and restores it.")
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
    escalations: list[str] = []

    for case in cases:
        stale = stale_reason(case)
        if stale is not None:
            print(f"STALE   {case.label}\n        {stale}")
            problems.append((case.label, stale))
            continue

        green, output, escalated = run_case(case, narrow=not arguments.harvest)
        if escalated and not arguments.harvest:
            escalations.append(case.label)

        if arguments.harvest:
            print(f"HARVEST {case.label}")
            for reported in failing_tests(case.suite, output) or ["(nothing failed)"]:
                print(f"        {reported}")
            continue

        # PARSED FAILURE NAMES, NEVER THE RAW OUTPUT. pytest echoes a parametrised argument's repr
        # into the failure detail, and the argument here is the `Sabotage` — so `guard='test_...'`
        # appears whenever any check over this table fails. `case.guard in output` was reading the
        # case back to itself and reporting CAUGHT for a mutation nothing caught.
        reported = failing_tests(case.suite, output)
        if green:
            print(f"MISSED  {case.label}\n        nothing failed; expected: {case.guard}")
            problems.append((case.label, f"not caught; expected {case.guard}"))
        elif any(case.guard in name for name in reported):
            print(f"CAUGHT  {case.label}")
            caught.append(case)
        else:
            actual = ", ".join(reported) or "(unparsed)"
            print(f"WRONG   {case.label}\n        expected: {case.guard}\n        got: {actual}")
            problems.append((case.label, f"caught by {actual}, not by {case.guard}"))

    if arguments.harvest:
        print("\nharvest only — nothing judged")
        return 0

    print(f"\n{len(caught)}/{len(cases)} caught by the named guard")
    for label, why in problems:
        print(f"  - {label}: {why}")
    # Where the wall clock went: each of these ran the whole suite because narrowing did not
    # answer, and each costs what every case used to.
    if escalations:
        print(f"\n{len(escalations)}/{len(cases)} escalated to the full suite:")
        for label in escalations:
            print(f"  - {label}")

    restored = True
    for name in suites:
        green, _ = run_suite(name)
        print(f"restored baseline ({name}): " + ("green" if green else "RED — restore failed"))
        restored = restored and green
    return 0 if not problems and restored else 1


if __name__ == "__main__":
    sys.exit(main())
