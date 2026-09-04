"""Tests for the pass that runs the stages either side of the planet raster.

The load-bearing cases are the ones a single stage cannot hold: that `--body` crosses the process
boundary into the cap pass intact, and that a part-rendered raster is not cut into tiles.
"""

import dataclasses
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

from pipeline import bodies, freshness
from pipeline.tile import cap_pass, planet_pass

REPO = Path(__file__).resolve().parents[1]


class TestTheBodyIsRequired:
    """`--body` has no default, and that is the point of it.

    A pipeline that assumes Earth when nobody said so is the most expensive failure mode this
    registry exists to prevent: it does not raise, it produces a complete, plausible, entirely wrong
    pyramid. Cheap to re-run, ruinous to discover late — so the argument is required rather than
    defaulted, and every documented invocation names the planet it means.
    """

    def test_omitting_the_body_is_an_error_rather_than_an_assumption(self):
        with pytest.raises(SystemExit):
            planet_pass.build_parser().parse_args([])

    def test_a_named_body_resolves_to_its_own_work_tree(self):
        args = planet_pass.build_parser().parse_args(["--body", "earth"])
        assert planet_pass.resolve_out(args) == bodies.work_dir(bodies.EARTH, "planet_tiles")

    def test_an_explicit_out_still_wins_over_the_body_s_default(self, tmp_path):
        """The override has to survive, because a look A/B is run by pointing --out elsewhere."""
        args = planet_pass.build_parser().parse_args(["--body", "earth", "--out", str(tmp_path)])
        assert planet_pass.resolve_out(args) == tmp_path

    def test_an_unknown_body_is_rejected_by_the_registry_not_silently_accepted(self):
        args = planet_pass.build_parser().parse_args(["--body", "pluto"])
        with pytest.raises(KeyError):
            planet_pass.resolve_body(args)

    @staticmethod
    def _stages_the_docs_name():
        """The modules `docs/pipeline.md` says take a required `--body`, PARSED rather than restated.

        A hand-written list here would be a second copy of that sentence, free to drift in its own
        direction, which is the failure this whole file is about one tier down.
        """
        line = next(text for text in (REPO / "docs" / "pipeline.md").read_text().splitlines()
                    if "planet-raster stages take a required" in text)
        head, _, _ = line.partition("None of them defaults")
        return re.findall(r"`([a-z_]+)`", head)

    def test_the_sentence_naming_them_is_still_there_to_parse(self):
        """Anti-vacuity: reworded, the sweep below would check nothing and report success."""
        named = self._stages_the_docs_name()
        assert len(named) >= 3, f"parsed only {named} out of docs/pipeline.md"

    def test_every_stage_the_docs_name_actually_refuses_an_empty_argv(self, subtests):
        """THE CLAIM IS PROSE, SO NOTHING COULD GO RED WHEN ONE OF THEM STOPPED BEING AN ENTRY POINT.

        That is not hypothetical: the sentence named the planet shader for as long as the pass lived
        there, and kept naming it after the sequence moved out. A module with no CLI does not fail
        visibly when run — it imports, runs no main, and exits 0, which is indistinguishable from
        success, so a reader following the document got a stage that accepted anything and did
        nothing.

        DRIVES THE CLI rather than looking for a `build_parser` attribute. The first version of this
        asked for that name and reported `pack_pmtiles` as broken, which builds its parser inline in
        `main`: the oracle was testing a naming convention and inventing a defect.
        """
        for stage in self._stages_the_docs_name():
            with subtests.test(stage=stage):
                finished = subprocess.run(
                    [sys.executable, "-m", f"pipeline.tile.{stage}"],
                    cwd=REPO, capture_output=True, text=True, timeout=120,
                    check=False)     # a refusing stage is what this asserts about
                assert finished.returncode != 0, (
                    f"docs/pipeline.md says `{stage}` takes a required --body, but running it with "
                    f"no arguments succeeded: it has no CLI at all, so the sentence names a stage "
                    f"that cannot be invoked"
                )
                assert "--body" in finished.stderr, (
                    f"`{stage}` refused, but not for want of --body: {finished.stderr[:200]}"
                )

    def test_the_pass_hands_its_own_body_down_to_the_cap_pass(self, subtests):
        """The caps run as a SUBPROCESS at the tail of this pass, so the body crosses a process
        boundary as a string on a command line — the one place the registry cannot protect it.

        Without this, a Mars pass produces Mars and then shells out to a cap render that renders
        EARTH, into Earth's directories, over Earth's shipped textures. Every stage reports success.

        Written as a round trip rather than as two pinned strings on purpose: it builds the real
        command and parses it with the real parser on the other side, so renaming the flag on either
        side fails here instead of at the next multi-body render.
        """
        for name in sorted(bodies.BODIES):
            with subtests.test(name):
                body = bodies.get(name)
                command = planet_pass.cap_pass_command(body)
                module = command.index("pipeline.tile.cap_pass")
                parsed = cap_pass.build_parser().parse_args(command[module + 1:])
                assert bodies.get(parsed.body) is body

        with subtests.test("a body the registry does not know yet"):
            # THE LOOP ABOVE CANNOT CATCH A HARDCODED "earth" while the registry holds one body —
            # every assertion in it would pass against a command that ignored its argument entirely.
            # This is the arm that says the command names the body it was GIVEN, and it is the arm
            # that will still be doing work on the day a second planet is added.
            other = dataclasses.replace(bodies.EARTH, name="other", path_prefix="other")
            command = planet_pass.cap_pass_command(other)
            assert command[command.index("--body") + 1] == "other"

    def test_a_body_publishing_no_caps_is_refused_by_the_cap_pass_itself(self, monkeypatch):
        """The SECOND gate, and it is not redundant with the pass declining to invoke this.

        Reaching `cap_pass.main` means an operator ran it directly, and the answer has to be the
        same one. It matters because the render would otherwise SUCCEED: a body declaring no surface
        layers needs only the heightfield, so there is no missing file to stop it — it would spend
        ~14 GB a pole to publish discs shaded by ramps that body has never been given.

        Asserted through the real entry point with the real parser, because the refusal has to
        happen before anything reads a raster, and only running `main` proves the order.

        THE CAPLESS BODY IS SYNTHETIC AND HAS TO BE. It used to be found by scanning the registry,
        which held one while Mars's ramps were unratified; ratifying them turned Mars's caps on and
        took the last negative instance with it. A guard that sources its negative instance from a
        live field is a guard that quietly stops testing anything when that field flips. It goes
        INTO the registry for the call, because `main` resolves a name off argv.
        """
        capless = dataclasses.replace(bodies.EARTH, name="capless", path_prefix="capless",
                                      renders_polar_caps=False)
        monkeypatch.setitem(bodies.BODIES, capless.name, capless)
        with mock.patch.object(sys, "argv", ["cap_pass", "--body", capless.name]), \
                pytest.raises(SystemExit) as refusal:
            cap_pass.main()
        message = str(refusal.value)
        assert capless.name in message and "renders_polar_caps" in message, message

    def test_the_pass_skips_the_cap_subprocess_for_a_body_that_publishes_none(self):
        """The FIRST gate, asserted on the branch rather than on the flag.

        A test reading `body.renders_polar_caps` back would pass against a pass that consulted it
        and then shelled out anyway. What must be true is that no cap subprocess is spawned, so the
        assertion is on the decision the pass makes with the field.

        The synthetic body is what keeps the loop from being one-sided: every registered planet
        renders caps now, so the registry alone would only ever exercise the True arm and a
        `runs_cap_pass` hardcoded to True would pass.
        """
        capless = dataclasses.replace(bodies.EARTH, name="capless", renders_polar_caps=False)
        for body in [bodies.get(name) for name in sorted(bodies.BODIES)] + [capless]:
            assert planet_pass.runs_cap_pass(body) is body.renders_polar_caps


class TestAPartlyRenderedPlanetIsNotCut:
    """A raytraced pass stopped part-way is the NORMAL state, not a crash, and it must not ship.

    `build_tiles` cannot answer this: it compares the tiles against the raster, and a half-rendered
    raster is newer than the tiles, so its own gate says cut. Only the completion marker separates
    "this planet is finished" from "this planet is four hundred blocks in".
    """

    def test_a_raster_with_no_marker_is_incomplete(self, tmp_path):
        raster = tmp_path / "planet_rgb.tif"
        raster.write_bytes(b"")
        assert planet_pass.raster_is_complete(raster) is False

    def test_a_marked_raster_is_complete(self, tmp_path):
        """The anti-vacuity half: a predicate that answered False for everything would pass the
        test above and would never cut a tile again."""
        raster = tmp_path / "planet_rgb.tif"
        raster.write_bytes(b"")
        freshness.mark_done(raster)
        assert planet_pass.raster_is_complete(raster) is True

    def test_a_raster_rewritten_after_its_marker_is_incomplete_again(self, tmp_path):
        """The resume case: a marker from an earlier finished run keeps vouching while a later run
        overwrites the raster and stops. That is the exact state this predicate exists to catch."""
        raster = tmp_path / "planet_rgb.tif"
        raster.write_bytes(b"")
        freshness.mark_done(raster)
        os.utime(raster, (time.time() + 10, time.time() + 10))
        assert planet_pass.raster_is_complete(raster) is False


def test_the_cli_offers_no_knob_flag() -> None:
    """`--knob` tuned composite constants, so it can no longer reach a planet pixel."""
    with pytest.raises(SystemExit):
        planet_pass.build_parser().parse_args(["--body", "earth", "--knob", "ambient=0.5"])
