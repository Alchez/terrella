"""The pass watchdog: what wakes a reader in the night, and what deliberately does not.

This module had no test of its own until the raytrace producer arrived, and the gap was not
theoretical. It held a regex of the stage phrasings it expected `shade_planet` to print, so it
could only see stages someone had come back and taught it about: four of Earth's five surface
layers and both of the two stages Mars runs that Earth does not had never been reported, silently,
because an unreported stage looks exactly like a stage that has not started yet. A second producer
printing an entirely different vocabulary is the same failure at full size.

So the pass declares its boundaries through `pipeline/progress.py` and this watcher matches one
marker. What the tests below pin is that direction, not the strings: **anything** the helper emits
is reported, and the two lines a producer repeats thousands of times are not.

THE WAKE POLICY IS THE REAL SUBJECT. The watchdog EXITS on an event so the harness can wake the
reader, which makes every match a turn spent. Earth is 4,096 blocks; a marker on the per-block line
would be 4,096 wake-ups in a night, which is not a smaller version of reporting nothing but a
different failure. Progress within a stage is therefore read from the producer's own status
document, where it is a number that can be sampled, and the log carries boundaries and faults.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import bodies, progress
from pipeline.profile import watchdog
from pipeline.tile import block_render, shade_planet

ROOT = Path(__file__).resolve().parents[1]


def status_document(**overrides) -> str:
    """A `raytrace_status.json` body, with only the fields these tests steer named at call sites."""
    return json.dumps({"state": "rendering", "body": "earth", "progress": "100/4096",
                       "percent": 2.44, "failures": 0, "last_block": "r03c07 62.3s",
                       "blocks_per_min": 1.1, "eta_min": 3633.0, "free_gb": 812.0, **overrides})


class TestTheMarkerIsTheWholeVocabulary:
    """The point of the sentinel: a stage nobody has told the watcher about is still reported."""

    def test_a_stage_no_one_has_written_yet_is_reported(self, capsys):
        progress.stage("melt the ice caps -> 3857 ...")
        assert watchdog.classify(capsys.readouterr().out.strip()) == "STAGE"

    def test_an_ordinary_print_is_not_a_stage(self, capsys):
        """The negative half, and the reason the marker is unlovely: an ordinary sentence about a
        stage must not read as one, or the watchdog wakes on the pass talking to itself."""
        print("warp height -> 3857 ...")
        assert watchdog.classify(capsys.readouterr().out.strip()) is None

    def test_the_marker_is_imported_rather_than_spelled_here(self):
        """A second spelling in the watcher is the exact failure the sentinel replaced, one file
        further along, and it would fail in the silent direction."""
        assert watchdog.STAGE_RE.search(progress.marked("x"))
        assert progress.STAGE_MARKER in watchdog.STAGE_RE.pattern.replace("\\", "")


class TestTheProducersOwnOutputIsReportedOrDeliberatelyQuiet:
    """Driven through `block_render.log` rather than against copies of its format strings.

    A test that rebuilt the lines from the code's field names would be a second producer of them,
    which is how the first sweep of this question went wrong: it asserted about a line assembled
    from a layer's identifier that no loop anywhere prints.
    """

    @staticmethod
    def _emitted(capsys) -> str:
        return capsys.readouterr().out.strip()

    def test_the_run_starting_is_a_stage(self, capsys):
        block_render.log("earth: 0/4096 blocks already done, 4096 to render, 812 GB free",
                         stage=True)
        assert watchdog.classify(self._emitted(capsys)) == "STAGE"

    def test_the_per_block_line_wakes_nobody(self, tmp_path, capsys, monkeypatch):
        """4,096 of these on Earth, one every ~19 s, and the whole reason the sidecar exists.

        DRIVEN THROUGH `run` RATHER THAN THROUGH `log`, because the mistake this guards against is
        made at the CALL SITE — `stage=True` added to the line inside the loop reads like fixing an
        omission — and a test that calls `log` itself would pass over it while looking correct.
        """
        mosaic, markers = self._rendering_run(tmp_path, monkeypatch, blocks=3)
        block_render.run(bodies.EARTH, tmp_path, mosaic)

        printed = capsys.readouterr().out.splitlines()
        per_block = [line for line in printed if "context" in line and "plane" in line]
        assert len(per_block) == 3, f"the harness rendered no blocks; printed: {printed}"
        assert [watchdog.classify(line) for line in per_block] == [None, None, None], (
            "the per-block line is a stage marker, so a night wakes the reader 4,096 times"
        )
        assert any(watchdog.classify(line) == "STAGE" for line in printed), (
            "anti-vacuity: nothing at all in this run is a stage, so the assertion above is empty"
        )
        assert markers.exists()

    @staticmethod
    def _rendering_run(work: Path, monkeypatch, *, blocks: int):
        """A `block_render.run` that plans real blocks and renders them without Blender or a store."""
        from pipeline.block_plan import Block
        from pipeline.look import palette

        plan = [Block(col0=column * 512, row0=0, size_px=512, context_px=1024)
                for column in range(blocks)]
        monkeypatch.setattr(block_render.planet_seam, "declared",
                            lambda body: frozenset(block_render.planet_seam.KNOWN_RASTERS))
        monkeypatch.setattr(block_render, "plan_blocks", lambda body, w: plan)
        monkeypatch.setattr(block_render, "ensure_mosaic", lambda mosaic, body: None)
        for name in (shade_planet.HEIGHT_3857, shade_planet.OCEAN_3857, shade_planet.WATER_3857):
            (work / name).write_bytes(b"")
        (work / block_render.PARAMS_NAME).write_text(block_render.params(
            bodies.EARTH, frozenset(block_render.planet_seam.KNOWN_RASTERS),
            palette.look_for("earth"), block_render.rig_recipe(bodies.EARTH), []))
        mosaic = work / shade_planet.PLANET_RGB
        mosaic.write_bytes(b"")
        markers = block_render.markers_in(mosaic)

        def marked_done(body, block, mosaic_path, scratch, marker_dir):
            marker_dir.mkdir(parents=True, exist_ok=True)
            (marker_dir / block_render.block_name(block)).touch()

        monkeypatch.setattr(block_render, "render_block", marked_done)
        # The run's own disk guard, which would otherwise abort before the first block: it reserves
        # room for a whole uncompressed Earth grid and this box does not have it free.
        monkeypatch.setattr(block_render, "disk_floor_bytes", lambda *a, **k: 0.0)
        return mosaic, markers

    def test_a_block_failing_is_a_fault_whatever_it_failed_with(self, capsys):
        """Matched on the runner's own word rather than on the exception text: a CUDA message
        carries "error" and a segfault carries nothing, and the two must report alike."""
        block_render.log("[9/4096] r03c07 FAILED (1 in a row): blender exited with -11")
        assert watchdog.classify(self._emitted(capsys)) == "FAULT"

    def test_the_run_giving_up_is_a_fault(self, capsys):
        block_render.log("ABORT: 8 consecutive failures — this is the GPU, not a block", stage=True)
        assert watchdog.classify(self._emitted(capsys)) == "FAULT", (
            "a stage boundary that is also a failure is read for the failure"
        )

    def test_a_night_ending_short_is_a_stage(self, capsys):
        """The resumable case: this is the line that says where the render got to."""
        block_render.log("stopped with 2841 block(s) still to render; re-run to resume", stage=True)
        assert watchdog.classify(self._emitted(capsys)) == "STAGE"


class TestTheCompositesOwnStagesSurvivedTheChange:
    """The producer that ships today, so the sentinel cannot have been bought at its expense."""

    @pytest.mark.parametrize("body", [bodies.EARTH, bodies.MARS], ids=lambda b: b.name)
    def test_the_cut_is_reported_on_every_body(self, tmp_path, capsys, monkeypatch, body):
        """A REGRESSION THIS FILE EXISTS FOR. The marker carries the body's own zoom ceiling and
        the old regex spelled Earth's, so Mars's cut had never been reported. Driven through
        `build_tiles` rather than rebuilt from `tile_cut`, because rebuilding it is what let the two
        spellings drift in the first place.
        """
        out = tmp_path / body.name
        out.mkdir()
        monkeypatch.setattr(shade_planet, "tiles_are_fresh", lambda *a, **k: False)
        monkeypatch.setattr(shade_planet, "_run",
                            lambda *a, **k: (out / "tiles_new").mkdir(exist_ok=True))
        shade_planet.build_tiles(out / "planet_rgb.tif", out, body)

        printed = capsys.readouterr().out.splitlines()
        cut = [line for line in printed if "cutting z" in line]
        assert cut, f"{body.name} printed no cut marker at all; this harness is broken, not the code"
        assert all(watchdog.classify(line) == "STAGE" for line in cut), (
            f"{body.name} cuts z{shade_planet.tile_cut(body)['max_zoom']} and its cut is unreported"
        )

    def test_the_every_window_row_count_stays_quiet(self, capsys):
        """~18 wake-ups saying nothing new, and the reason "every print" was never the answer."""
        print("  composited rows 4096/131072")
        assert watchdog.classify(capsys.readouterr().out.strip()) is None


class TestANewStageCannotBeAddedUnreported:
    """The tripwire on the disease itself, rather than on any of the stages it infected.

    Every hole this file closes was written the same way: a stage announced with a bare `print`,
    correct at its call site, invisible to the watcher, and silent about being invisible. A source
    scan is the only oracle that reaches that, because the defect is a line that runs fine.

    WHAT IT CATCHES IS ONE CONVENTION IN ONE POPULATION, AND BOTH LIMITS ARE DELIBERATE. The
    convention is a trailing `...`, which is how this repo announces work about to take a while and
    is the shape every missed layer build had; a boundary phrased another way is covered by the
    tests above that drive the code printing it. The population is the modules that already
    announce stages, found by scanning for the import rather than listed here, so it grows the day
    a module joins and cannot silently go stale. A brand-new module that adopts nothing is outside
    it, which is the case a reviewer sees and the case this cannot.
    """

    ANNOUNCEMENT = re.compile(r"""print\(\s*f?["'][^"']*\.\.\.["']""")

    @staticmethod
    def modules_that_announce_stages() -> list[Path]:
        found = [path for path in sorted((ROOT / "pipeline").rglob("*.py"))
                 if "progress.stage(" in path.read_text() or "progress.marked(" in path.read_text()]
        assert len(found) >= 5, f"the sentinel's callers came back as {found}; this scan is broken"
        return found

    def test_no_module_that_announces_stages_also_announces_with_a_bare_print(self, subtests):
        for module in self.modules_that_announce_stages():
            with subtests.test(module.name):
                offenders = [line for line in module.read_text().splitlines()
                             if self.ANNOUNCEMENT.search(line)]
                assert not offenders, (
                    f"{module.name} announces a stage without progress.stage(), so the watchdog "
                    f"cannot see it and nothing will ever go red about it: {offenders}"
                )

    def test_the_scan_can_actually_find_one(self):
        """The positive control. A scan whose regex matched nothing would pass the test above on
        every module forever, which is the failure shape this whole file is about."""
        assert self.ANNOUNCEMENT.search('    print("warp height -> 3857 ...", flush=True)')
        assert self.ANNOUNCEMENT.search("    print(f'grade {name} ...')")
        assert not self.ANNOUNCEMENT.search("    progress.stage('warp height -> 3857 ...')")

    def test_every_stage_owner_the_pass_runs_is_in_the_population(self, subtests):
        """Anti-vacuity on the scan's REACH. It is a scan for an import, so a module that dropped
        the sentinel leaves the population quietly and takes its own guard with it — which is one
        rename away from the guard passing over the very modules it was written for."""
        announcing = {path.name for path in self.modules_that_announce_stages()}
        for owner in ("planet_pass.py", "shade_planet.py", "block_render.py", "cap_render.py",
                      "layer_producers.py"):
            with subtests.test(owner):
                assert owner in announcing


class TestTheSidecarCarriesProgressAndTheLogCannot:
    """`raytrace_status.json` is rewritten in place after every block, so reading it is O(1) on a
    night that renders 4,096 of them. The throttle is what a number buys: a regex cannot decline
    to match the 3,999 lines between two milestones."""

    def test_a_milestone_fires_and_the_steps_between_do_not(self, subtests):
        for previous, current, fires in [(None, 62.0, False), (12.0, 12.4, False),
                                         (12.0, 15.1, True), (9.9, 10.0, True),
                                         (62.0, 64.9, False), (62.0, 65.0, True)]:
            with subtests.test(f"{previous} -> {current}"):
                assert watchdog.crossed_step(previous, current, 5.0) is fires

    def test_the_first_read_never_fires(self):
        """A watcher started over last night's finished status must not announce it as tonight's."""
        assert watchdog.crossed_step(None, 100.0, 5.0) is False

    def test_absence_says_which_absence_it_is(self, subtests, tmp_path):
        """An optional input that says nothing when it is missing makes the broken wiring the quiet
        case: a raytraced night watched without `--status` would look exactly like one whose
        producer never rendered a block."""
        half = tmp_path / "half.json"
        half.write_text('{"state": "rend')           # killed mid-write
        for label, path, said in [("not wired", None, "no --status"),
                                  ("not yet written", tmp_path / "raytrace_status.json",
                                   "not written yet"),
                                  ("corrupt", half, "unreadable")]:
            with subtests.test(label):
                status, absence = watchdog.read_status(path)
                assert status is None
                assert absence is not None and said in absence

    def test_a_readable_status_comes_back_whole(self, tmp_path):
        path = tmp_path / block_render.STATUS_NAME
        path.write_text(status_document(percent=41.0))
        status, absence = watchdog.read_status(path)
        assert absence is None
        assert status is not None and status["percent"] == 41.0

    def test_every_field_the_report_shows_is_one_the_producer_writes(self, subtests, tmp_path):
        """The report and `Status.write` are two readers of one document, and nothing makes them
        agree. Asserted against a REAL status file rather than the fixture above, so a renamed key
        shows up here instead of in a night's report as `None`."""
        mosaic = tmp_path / "planet_rgb.tif"
        mosaic.touch()
        real = block_render.Status(bodies.EARTH, mosaic, tmp_path / block_render.STATUS_NAME,
                                   total=4096, already=100)
        real.state, real.last = "rendering", "r03c07 62.3s"
        real.write()
        summary = watchdog.summarise_status(json.loads(real.path.read_text()), None)
        for shown in ("earth", "rendering", "100/4096", "2.44"):
            with subtests.test(shown):
                assert shown in summary
        assert "None" not in summary.replace("eta None", ""), (
            f"a field the report shows is not one the producer writes: {summary}"
        )


class TestTheModuleRunsAndSaysWhatItTakes:

    def test_the_status_flag_is_accepted(self, tmp_path):
        """Driven through the real CLI: the flag existing in the parser is the whole wiring, and a
        module that cannot be pointed at the sidecar reports nothing between the warp and the cut.
        """
        result = subprocess.run(
            [sys.executable, "-m", "pipeline.profile.watchdog", "--help"],
            cwd=ROOT, capture_output=True, text=True, check=True)
        assert "--status" in result.stdout
        assert "--progress-step" in result.stdout

    def test_the_help_argues_from_no_stage_and_no_cap_it_does_not_own(self):
        """Both stale claims came from the same place: prose about a specific composite stage under
        a cap that stopped being 12 G when `pass_cap` started answering per body. The hillshade does
        not run on a raytraced pass at all, so a reader hitting this alarm at 3 a.m. was routed to a
        stage that is not in the pass.
        """
        from pipeline.profile import pass_cap
        source = (ROOT / "pipeline" / "profile" / "watchdog.py").read_text()
        assert "hillshade" not in source
        assert f"{pass_cap.STANDING_GIB} G cap" not in source
        assert f"{pass_cap.CAP_RENDERING_GIB} G cap" not in source
