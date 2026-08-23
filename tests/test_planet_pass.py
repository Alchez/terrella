"""Tests for the pass that picks a producer and runs the stages either side of it.

The load-bearing cases are the two that no single producer can hold: that the dispatch registry
answers for every producer the body vocabulary allows, and that the producer stamp is a dependency
of BOTH producers — without which each one reads the other's raster as its own completed output.
"""

import dataclasses
import os
import sys
import time
from unittest import mock

import pytest

from pipeline import bodies, freshness
from pipeline.tile import block_render, cap_render, planet_pass, shade_planet


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
                module = command.index("pipeline.tile.cap_render")
                parsed = cap_render.build_parser().parse_args(command[module + 1:])
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

        Reaching `cap_render.main` means an operator ran it directly, and the answer has to be the
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
        with mock.patch.object(sys, "argv", ["cap_render", "--body", capless.name]), \
                pytest.raises(SystemExit) as refusal:
            cap_render.main()
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


class TestEveryProducerTheVocabularyAllowsCanBeDispatched:
    """The registry answers for the whole vocabulary, or a body names something nothing runs.

    A dispatcher written as an `if` would fall through to the other producer instead, which is a
    night of GPU spent making the wrong kind of planet with no error anywhere.
    """

    def test_the_registry_and_the_vocabulary_are_the_same_set(self):
        assert set(planet_pass.PRODUCERS) == set(bodies.PLANET_PRODUCERS)

    def test_neither_side_is_empty(self):
        """The anti-vacuity half: two empty sets are equal and prove nothing."""
        assert planet_pass.PRODUCERS

    def test_every_registered_body_dispatches(self, subtests):
        for name in sorted(bodies.BODIES):
            with subtests.test(name):
                assert callable(planet_pass.producer_for(bodies.get(name)))

    def test_a_producer_nothing_runs_is_refused_by_name(self):
        """No fallback, on the rule `bodies.get` and `palette.look_for` already state."""
        stranger = dataclasses.replace(bodies.EARTH, planet_producer="etch-a-sketch")
        with pytest.raises(SystemExit, match="etch-a-sketch"):
            planet_pass.producer_for(stranger)


class TestTheProducerIsADependencyOfBothProducers:
    """The stamp is what makes a producer switch visible, and it only works if BOTH lists name it.

    `freshness.done_marker` derives from the output alone, so the two producers of `planet_rgb.tif`
    share one completion marker. Each one's freshness question is otherwise answered by the other's
    work: whichever ran last leaves a raster newer than every source and every recipe the OTHER one
    tracks, so that one skips and republishes the wrong producer's pixels under its own recipe.
    """

    def test_the_composite_names_it(self, tmp_path):
        deps = shade_planet.composite_deps(tmp_path, tmp_path / "hs.tif", tmp_path / "p.json")
        assert planet_pass.producer_stamp(tmp_path) in deps

    def test_the_raytrace_names_it(self, tmp_path):
        deps = block_render.raytrace_deps(tmp_path, tmp_path / "r.json")
        assert planet_pass.producer_stamp(tmp_path) in deps

    def test_it_is_the_same_path_on_both_sides(self, tmp_path):
        """One basename with one owner: two spellings would leave each producer watching its own
        file, which is the shape that cannot detect a switch in either direction."""
        composite = set(shade_planet.composite_deps(tmp_path, tmp_path / "hs.tif",
                                                    tmp_path / "p.json"))
        raytrace = set(block_render.raytrace_deps(tmp_path, tmp_path / "r.json"))
        assert planet_pass.producer_stamp(tmp_path) in composite & raytrace

    def test_the_stamp_records_the_body_s_own_answer(self, tmp_path, subtests):
        for name in sorted(bodies.BODIES):
            with subtests.test(name):
                body = bodies.get(name)
                stamp = planet_pass.write_producer_stamp(tmp_path, body)
                assert body.planet_producer in stamp.read_text()

    def test_an_unchanged_producer_does_not_move_the_mtime(self, tmp_path):
        """Which is what makes it a dependency rather than a restage: re-running an unchanged body
        must rebuild nothing, and `write_if_changed` is what guarantees that."""
        first = planet_pass.write_producer_stamp(tmp_path, bodies.EARTH)
        before = first.stat().st_mtime_ns
        planet_pass.write_producer_stamp(tmp_path, bodies.EARTH)
        assert first.stat().st_mtime_ns == before

    def test_a_changed_producer_does_move_it(self, tmp_path):
        """The positive control for the test above, and the behaviour the whole file exists for."""
        stamp = planet_pass.write_producer_stamp(tmp_path, bodies.EARTH)
        before = stamp.read_text()
        switched = dataclasses.replace(bodies.EARTH, planet_producer="raytrace")
        assert planet_pass.write_producer_stamp(tmp_path, switched).read_text() != before


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


class TestAKnobOverrideMustReachAPixel:
    """Every KNOBS entry is a composite constant, and the cap pass is a separate process with its
    own defaults — so on a raytraced body an override reaches nothing at all.

    Accepted silently it reads as a look experiment that simply had no visible effect, which is
    indistinguishable from the look being insensitive to the knob.
    """

    def test_a_composite_body_accepts_one(self):
        planet_pass.apply_knob_overrides(bodies.EARTH, [])

    def test_a_raytraced_body_refuses_one(self):
        raytraced = dataclasses.replace(bodies.EARTH, planet_producer="raytrace")
        with pytest.raises(SystemExit, match="reach no pixel"):
            planet_pass.apply_knob_overrides(raytraced, ["ambient=0.5"])

    def test_a_raytraced_body_with_no_override_is_not_refused(self):
        """The refusal is about the override, not about the producer: an ordinary raytraced pass
        must not be stopped by a check on a flag nobody passed."""
        raytraced = dataclasses.replace(bodies.EARTH, planet_producer="raytrace")
        planet_pass.apply_knob_overrides(raytraced, [])

    def test_an_unknown_knob_is_still_refused_on_a_composite_body(self):
        with pytest.raises(SystemExit, match="unknown knob"):
            planet_pass.apply_knob_overrides(bodies.EARTH, ["nosuchknob=1"])
