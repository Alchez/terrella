"""The raytraced cap producer: which frames the ring needs, and that they say what was asked of them.

THE ONE THING NO GATE CAN SEE IS THE DISC ITSELF, so everything here is about the two places a
raytraced cap can be wrong without looking wrong. A pixel blended from the wrong pair of passes is
lit a few degrees off and reads as terrain; a frame rendered without the flag that was passed to it
is a plausible picture of the wrong quadrant or the wrong sun. Both stitch cleanly.

The frame plan is exercised on SHRUNKEN grids. It is a function of longitude alone, so the disc's
pixel count does not enter it — asserted rather than assumed, by planning the same pole twice at
different resolutions.
"""

import dataclasses
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from pipeline import bodies, layers, paths, planet_seam
from pipeline.look import seaice
from pipeline.tile import cap_raytrace, cap_render

EARTH = bodies.BODIES["earth"]
WHOLE_PLANET = planet_seam.KNOWN_RASTERS

#: Both shipped poles, shrunk. `px` reaches the frame plan only through `_lonlat_grid`'s shape.
NORTH = dataclasses.replace(cap_render.north_grid(EARTH), px=256)
SOUTH = dataclasses.replace(cap_render.south_grid(EARTH), px=256)


def quadrant_longitude(grid, row, col):
    """The longitudes of one quadrant of this grid, as the plan and the blend both read them."""
    longitude, _latitude = cap_render._lonlat_grid(grid)
    half = grid.px // cap_render.CAP_QUADRANT_SPLIT
    return np.asarray(longitude)[row * half:(row + 1) * half, col * half:(col + 1) * half]


class TestTheRingIsRenderedOnlyWhereItIsSampled:
    """A quadrant spans a quarter of the longitude circle, so most of the ring never reaches it.

    Rendering all 24 into all four is four times the GPU for frames no pixel samples. Rendering the
    WRONG seven is not slow, it is wrong: the blend takes each pixel from the two passes bracketing
    the azimuth it wants, and a pass that was never rendered leaves those pixels unlit.
    """

    def test_a_quadrant_takes_a_quarter_of_the_ring_plus_its_upper_neighbour(self):
        """Seven of twenty-four. The quarter is 6 lattice cells and the bracket is inclusive at both
        ends, so the seventh is the neighbour outside the quadrant's own span."""
        plan = cap_raytrace.frame_plan(NORTH)
        assert sorted(plan) == [(0, 0), (0, 1), (1, 0), (1, 1)]
        for quadrant, passes in plan.items():
            assert len(passes) == 7, f"{quadrant} asks for {len(passes)} of the ring"
            assert len(set(passes)) == len(passes), f"{quadrant} names a pass twice"

    def test_every_pixel_has_both_of_the_passes_it_will_be_blended_from(self):
        """THE COVERAGE CLAIM, checked against the same longitudes the blend reads. A pass short of
        the set does not crash the render — it leaves those pixels black in the stitched disc, which
        reads as a render artefact rather than as a missing file."""
        for grid in (NORTH, SOUTH):
            plan = cap_raytrace.frame_plan(grid)
            for (row, col), passes in plan.items():
                lower, _frac = cap_raytrace.bracketing_pass(
                    grid, quadrant_longitude(grid, row, col))
                upper = (lower + 1) % cap_raytrace.CAP_AZIMUTH_PASSES
                have = np.array(sorted(passes))
                covered = ((lower[..., None] == have).any(axis=-1)
                           & (upper[..., None] == have).any(axis=-1))
                assert covered.all(), (
                    f"{grid.name} r{row}c{col}: {int((~covered).sum()):,} px would blend from a "
                    f"pass this quadrant never renders")

    def test_the_two_poles_do_not_want_the_same_frames(self):
        """`az_sign` is the field they disagree about, so the same quadrant of each pole samples the
        opposite side of the ring. A plan shared between them renders 28 correct-looking frames for
        one pole and 28 wrong ones for the other."""
        assert cap_raytrace.frame_plan(NORTH) != cap_raytrace.frame_plan(SOUTH)

    def test_the_plan_does_not_depend_on_how_many_pixels_the_disc_has(self):
        """What justifies planning a 256 px stand-in for an 8192 px disc, and it is a real property
        rather than a testing convenience: the plan is a statement about longitudes, and a plan that
        moved with resolution would be reading something else."""
        coarse = cap_raytrace.frame_plan(dataclasses.replace(NORTH, px=256))
        finer = cap_raytrace.frame_plan(dataclasses.replace(NORTH, px=1024))
        assert coarse == finer

    def test_the_whole_ring_is_reached_across_the_four_quadrants(self):
        """The control on the narrowing above: four quarters make a circle, so every pass must be
        wanted by somebody. A plan that dropped a slice would pass every per-quadrant check and
        leave a wedge of the disc lit from one frame instead of two."""
        wanted = {index for passes in cap_raytrace.frame_plan(NORTH).values() for index in passes}
        assert wanted == set(range(cap_raytrace.CAP_AZIMUTH_PASSES))


class TestTheBracketReadsTheProducersOwnLaw:
    def test_it_is_derived_from_the_shared_rotation_and_not_from_longitude(self, monkeypatch):
        """`cap_render.azimuth_delta` is the expression the COMPOSITE lights each pixel by. Spelled
        again here, the two producers of one disc would be free to drift a few degrees apart, which
        is visible only where the disc feathers into the tiles."""
        monkeypatch.setattr(cap_render, "azimuth_delta",
                            lambda grid, longitude: np.full_like(longitude, 40.0, dtype=np.float64))
        lower, frac = cap_raytrace.bracketing_pass(NORTH, np.zeros((4, 4), dtype=np.float64))
        # 40 degrees is 2 and two thirds steps of 15.
        assert np.all(lower == 2)
        assert np.allclose(frac, 2 / 3)

    def test_a_pixel_landing_on_a_rendered_pass_takes_that_frame_whole(self):
        """The fraction is what the blend cross-fades with, so a pixel exactly on the lattice must
        read zero rather than a rounding crumb of its neighbour."""
        longitude = np.array([[0.0, -15.0, -30.0]], dtype=np.float64)  # north: delta = -longitude
        lower, frac = cap_raytrace.bracketing_pass(NORTH, longitude)
        assert np.allclose(frac, 0.0)
        assert list(lower.ravel()) == [0, 1, 2]

    def test_a_delta_infinitesimally_below_zero_lands_on_the_first_pass(self):
        """THE INPUT HAS TO REACH THE EDGE, and the obvious one does not. A delta of -359 floors to
        23 with or without the modulo, so a test written from it confirms a line it never exercises
        — which is how the mutation that deletes that modulo first came back MISSED.

        What reaches it is a delta too small to have a representable remainder: `%` rounds up to
        exactly 360.0, which divides to 24.0 and floors to an index no frame carries.
        """
        longitude = np.array([[1e-17]], dtype=np.float64)   # north: delta = -longitude
        lower, _frac = cap_raytrace.bracketing_pass(NORTH, longitude)
        assert (np.float64(-1e-17) % 360.0) == 360.0, "this platform does not round the way the guard assumes"
        assert lower.item() == 0

    def test_the_upper_neighbour_wraps_where_the_callers_close_the_ring(self):
        """The ring's own wrap, which is the callers' rather than `bracketing_pass`'s. A pixel on the
        last pass must bracket toward the FIRST, and the plan must therefore carry pass 0."""
        longitude = np.array([[-352.0]], dtype=np.float64)  # north: delta 352, in the last cell
        lower, frac = cap_raytrace.bracketing_pass(NORTH, longitude)
        assert lower.item() == cap_raytrace.CAP_AZIMUTH_PASSES - 1
        assert frac.item() > 0.0, "on the lattice exactly, this pixel needs no upper neighbour"
        wanted = cap_raytrace.frame_plan(NORTH)
        for quadrant, passes in wanted.items():
            if cap_raytrace.CAP_AZIMUTH_PASSES - 1 in passes:
                assert 0 in passes, f"{quadrant} brackets the last pass and never renders the first"


class TestTheRenderCostIsWhatWasMeasured:
    def test_both_poles_together_are_the_fifty_six_frames_the_clock_was_taken_from(self):
        """The 41-minute figure is 56 frames at a measured 44 s. A plan that quietly grew would make
        that estimate wrong in the direction nobody checks."""
        total = sum(len(passes) for grid in (cap_render.north_grid(EARTH),
                                             cap_render.south_grid(EARTH))
                    for passes in cap_raytrace.frame_plan(dataclasses.replace(grid, px=256))
                    .values())
        assert total == 56


class TestABlenderRunMustReportWhatItWasAskedFor:
    """`scene_build` echoes every flag whose absence is invisible, and this is the reader that makes
    those echoes worth printing. A dropped `--tile` photographs the whole plane at a quadrant's
    resolution; a dropped `--sun-azimuth-delta` renders the base bearing. Both succeed."""

    def _command(self, index=3, quadrant=(1, 0)):
        return cap_raytrace.blender_command(
            NORTH, cap_render.cap_render_dir(NORTH), Path("/x.blend"), Path("/x.png"),
            quadrant, index)

    def test_the_command_carries_the_caps_whole_regime(self, subtests):
        command = " ".join(str(part) for part in self._command())
        for flag, value in (("--body", "earth"), ("--tile", "1,0"),
                            ("--sun-azimuth-delta", "45.0"),
                            ("--denoise-device", cap_raytrace.CAP_DENOISE_DEVICE),
                            ("--base-grid", cap_raytrace.CAP_BASE_GRID)):
            with subtests.test(flag=flag):
                assert f"{flag} {value}" in command

    def test_the_delta_is_the_pass_index_on_the_ring(self):
        for index in range(cap_raytrace.CAP_AZIMUTH_PASSES):
            command = self._command(index=index)
            wanted = index * cap_raytrace.azimuth_step()
            assert f"{wanted}" in [str(part) for part in command]

    def test_a_run_that_reported_every_echo_is_accepted(self):
        """The success path, which is the one every real frame takes. Written first because a
        refusal guard whose happy case is untested refuses everything equally well."""
        cap_raytrace.check_echoes(self._stdout(), (1, 0), 3)

    def _stdout(self, drop=None):
        lines = [f"DENOISE_DEVICE {cap_raytrace.CAP_DENOISE_DEVICE}",
                 "SUN_AZIMUTH_DELTA 45.0000 main arrives from 0.00 fill from 180.00",
                 "TILE 1,0 camera at -0.500000,-0.500000",
                 f"BASE_GRID {cap_raytrace.CAP_BASE_GRID} BASE_PATCHES 2 SPAN_PX 8192"]
        return "\n".join(line for line in lines if drop is None or drop not in line)

    def test_a_missing_echo_is_refused_and_named(self, subtests):
        for dropped in ("DENOISE_DEVICE", "SUN_AZIMUTH_DELTA", "TILE ", "BASE_GRID"):
            with subtests.test(echo=dropped), pytest.raises(RuntimeError, match=dropped.strip()):
                cap_raytrace.check_echoes(self._stdout(drop=dropped), (1, 0), 3)

    def test_an_echo_reporting_a_DIFFERENT_quadrant_is_refused(self):
        """The failure a presence check cannot see. `--tile` arriving as a different pair renders
        successfully and the frame lands under the name of the quadrant that was asked for."""
        with pytest.raises(RuntimeError, match="TILE"):
            cap_raytrace.check_echoes(self._stdout(), (0, 1), 3)

    def test_an_echo_reporting_a_DIFFERENT_sun_is_refused(self):
        with pytest.raises(RuntimeError, match="SUN_AZIMUTH_DELTA"):
            cap_raytrace.check_echoes(self._stdout(), (1, 0), 4)


class TestAFrameIsOnlyCalledRenderedOnceItIsWhole:
    """Existence is the completeness claim the resume reads, so it has to be earned.

    A killed Blender leaves a non-empty partial PNG, which is exactly what the arm's `[ -s "$OUT" ]`
    accepted — and a partial frame does not fail on the next run, it blends garbage into the disc.
    """

    @pytest.fixture
    def staged(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "DATA", tmp_path)
        cap_raytrace.frames_dir(NORTH).mkdir(parents=True, exist_ok=True)
        return tmp_path

    def _fake_blender(self, monkeypatch, *, returncode, stdout):
        """Stand in for Blender: write something to wherever `--render` pointed, then return."""
        def run(command, **kwargs):
            del kwargs
            target = Path(command[command.index("--render") + 1])
            target.write_bytes(b"half a frame")
            return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")

        monkeypatch.setattr(cap_raytrace.subprocess, "run", run)

    def test_a_partly_written_frame_is_never_left_under_its_final_name(self, monkeypatch, staged):
        self._fake_blender(monkeypatch, returncode=137, stdout="")   # 137 is the OOM kill
        with pytest.raises(RuntimeError, match="blender exited 137"):
            cap_raytrace.render_frame(NORTH, staged / "render", (1, 0), 3)
        assert not cap_raytrace.frame_path(NORTH, (1, 0), 3).exists()

    def test_a_frame_whose_run_reported_the_wrong_flags_is_not_kept_either(self, monkeypatch,
                                                                          staged):
        """The refusal and the rename are one decision. A frame that rendered successfully at the
        wrong sun must not survive under the name of the pass that was asked for, or the next resume
        skips it and the disc blends a bearing nobody chose."""
        self._fake_blender(monkeypatch, returncode=0, stdout="rendered, said nothing")
        with pytest.raises(RuntimeError, match="did not report back"):
            cap_raytrace.render_frame(NORTH, staged / "render", (1, 0), 3)
        assert not cap_raytrace.frame_path(NORTH, (1, 0), 3).exists()

    def test_a_run_that_succeeded_and_reported_leaves_the_frame_under_its_name(self, monkeypatch,
                                                                              staged):
        """The control, and the case every real frame takes: without it the two refusals above pass
        against a function that never keeps anything."""
        self._fake_blender(monkeypatch, returncode=0, stdout="\n".join((
            f"DENOISE_DEVICE {cap_raytrace.CAP_DENOISE_DEVICE}",
            f"SUN_AZIMUTH_DELTA {3 * cap_raytrace.azimuth_step():.4f} main arrives from 0.00",
            "TILE 1,0 camera at -0.500000,-0.500000",
            f"BASE_GRID {cap_raytrace.CAP_BASE_GRID} BASE_PATCHES 2")))
        kept = cap_raytrace.render_frame(NORTH, staged / "render", (1, 0), 3)
        assert kept == cap_raytrace.frame_path(NORTH, (1, 0), 3)
        assert kept.exists()
        assert not kept.with_suffix(".part.png").exists()


class TestTheRaytraceRecipeIsNotTheCompositesWearingAnotherName:
    """`cap_is_fresh` compares one sidecar per pole against whichever producer is current, so the
    two recipes must differ for the same grid — that is what makes the switch restage both discs.
    """

    def _recipe(self):
        return json.loads(cap_raytrace.params(cap_render.north_grid(EARTH), WHOLE_PLANET))

    def test_the_two_producers_of_one_disc_write_different_recipes(self):
        grid = cap_render.north_grid(EARTH)
        assert cap_raytrace.params(grid, WHOLE_PLANET) != cap_render.cap_recipe(grid, WHOLE_PLANET)

    def test_it_names_the_producer_that_wrote_it(self):
        assert self._recipe()["producer"] == "raytrace"

    def test_it_carries_the_rig_rather_than_the_composites_knobs(self, subtests):
        """The three tiers `block_render.params` names, arriving on the cap: this module's own
        geometry, the rig's constants, and the producers' — none of which the composite recipe has
        any way to record, since Cycles applies them and `composite_params` describes numpy."""
        recipe = self._recipe()
        for key in ("rig", "azimuth_passes", "quadrant_split", "denoise_device", "base_grid",
                    "snow_rgb", "ice_rgb", "white_union", "white_exclusions", "mask_full_scale"):
            with subtests.test(key=key):
                assert key in recipe

    def test_it_does_not_carry_the_composites_own_block(self):
        """`composite_params` describes a numpy shading pass that never runs here. Recorded, it
        would put a 41-minute render behind knobs no raytraced pixel reads."""
        assert "composite" not in self._recipe()

    def test_the_rig_is_read_from_the_rig_rather_than_restated(self):
        """Through JSON on both sides: `rig_recipe` holds tuples where the serialised recipe holds
        lists, and comparing the two forms directly would fail for a reason that is not a drift."""
        from pipeline.tile import block_render
        assert self._recipe()["rig"] == json.loads(json.dumps(block_render.rig_recipe(EARTH)))

    def test_a_look_constant_moving_restages_the_disc(self, monkeypatch):
        """The claim the recipe exists to make, run rather than described. `constants_for` resolves
        each producer's constants, and nothing else here can see one move: the render directory is
        not an mtime dependency of the disc."""
        grid = cap_render.north_grid(EARTH)
        before = cap_raytrace.params(grid, WHOLE_PLANET)
        monkeypatch.setattr(seaice, "ICE_BAND", 0.99)
        assert cap_raytrace.params(grid, WHOLE_PLANET) != before

    def test_a_layer_switched_off_restages_although_its_source_stops_being_tracked(self):
        """The conditional-record idiom: turning a layer off REMOVES its file from the mtime
        dependencies, so the absence has nowhere to show except here."""
        # A REGISTERED body with its layers stripped, not a stand-in under a new name: `params`
        # reaches `palette.look_for`, which has no fallback, so an invented body fails for a reason
        # that has nothing to do with what is being asked.
        bare = dataclasses.replace(bodies.BODIES["mars"], surface_layers=frozenset())
        grid = dataclasses.replace(cap_render.north_grid(bare), body=bare)
        recipe = json.loads(cap_raytrace.params(grid, WHOLE_PLANET))
        assert set(recipe["layers_off"]) == set(layers.CAP_LAYERS)

    def test_earth_records_nothing_off_so_its_recipe_keeps_its_shape(self):
        assert "layers_off" not in self._recipe()
