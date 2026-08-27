"""The cap ladder's pure layer: which axes exist, how a rung's values are typed, and — the point of
the whole file — that a sweep cannot leave a shipped constant swapped out.

WHY THIS FILE IS WEIGHTED THE WAY IT IS. Rendering a rung needs the fused planet VRTs and peaks
~14 GB, so nothing here renders. What it guards instead is the failure the two scripts this module
replaces actually shipped: neither restored the value it patched, and both were invisible to every
gate because they lived in the one directory pyright is told to skip. Their symptom was not a crash
— it was correct-looking pixels under a freshness sidecar that declared them current.

So the load-bearing assertions are the RESTORE ones, and each is written to fail if the restore is
removed rather than merely to observe that it happens.
"""

import dataclasses
from typing import Any, cast

import pytest

from pipeline import bodies, planet_seam
from pipeline.tile import cap_ladder, cap_render, shade

#: A planet whose seam emitted all three rasters — what Earth declares, and the only
#: shape these tests care about unless they say otherwise.
WHOLE_PLANET = planet_seam.KNOWN_RASTERS

#: The knob the predecessor swept, and the one whose stale ladder proved the restore has to be
#: mechanical: it ended on 0.0 long after the shipped value moved to 0.75.
SWEPT_KNOB = "ice_relief_damp"


@pytest.fixture(autouse=True)
def shipped_state_is_pristine():
    """Every test here mutates process-wide state on purpose. Snapshot both homes and put them back,
    so a failing assertion cannot leak a swapped constant into whatever test file runs next — which
    is precisely the bug under test, and it would be absurd to reproduce it in the suite."""
    knobs = cast(dict[str, Any], shade.KNOBS)
    before_knobs = dict(knobs)
    before_quality = cap_render.CAP_WEBP_QUALITY
    yield
    knobs.clear()
    knobs.update(before_knobs)
    cap_render.CAP_WEBP_QUALITY = before_quality


class TestTheAxisListIsDerived:
    def test_every_numeric_knob_is_sweepable(self):
        """Derived from KNOBS, not transcribed. A hand-written list would omit the next knob added
        to the composite, and the omission would read as 'not sweepable' rather than as a bug."""
        numeric = {name for name, value in cast(dict[str, Any], shade.KNOBS).items()
                   if isinstance(value, (int, float))}
        assert numeric <= set(cap_ladder.sweepable_axes())
        assert SWEPT_KNOB in cap_ladder.sweepable_axes()

    def test_the_encoder_and_the_render_size_are_sweepable_too(self):
        """The three axes span the three ways a cap pixel can change: what the composite computes,
        how big the render is, and how the encoder writes it."""
        assert {"quality", "px"} <= set(cap_ladder.sweepable_axes())

    def test_string_valued_knobs_are_not_offered(self):
        """`snow_curve`/`lake_curve` name branches, not points on a scale. Offering them would let
        `--values gamma8,log1p` reach `float()` and die mid-sweep instead of at the CLI."""
        strings = {name for name, value in cast(dict[str, Any], shade.KNOBS).items()
                   if isinstance(value, str)}
        assert strings, "KNOBS must still carry the curve names, or this test proves nothing"
        assert not (strings & set(cap_ladder.sweepable_axes()))


class TestValuesAreTypedByTheirAxis:
    def test_a_knob_rung_stays_a_float(self):
        assert cap_ladder.parse_values(SWEPT_KNOB, "1.0,0.75,0.5,0.0") == [1.0, 0.75, 0.5, 0.0]

    def test_a_pixel_rung_is_whole(self):
        """`px=4096.5` must not survive to `dataclasses.replace`: gdalwarp's `-ts` would stringify a
        float and fail partway through a sweep that had already spent minutes."""
        assert [int(value) for value in cap_ladder.parse_values("px", "4096, 8192")] == [4096, 8192]

    def test_a_fractional_pixel_rung_is_refused_rather_than_rounded(self):
        """Rounding would render 4096 and archive it as `4096.7`, leaving a judging directory whose
        pictures and filenames disagree — worse than the typo it was covering for."""
        with pytest.raises(ValueError, match="whole numbers"):
            cap_ladder.parse_values("px", "4096.7")
        with pytest.raises(ValueError, match="whole numbers"):
            cap_ladder.parse_values("quality", "85.5")

    def test_an_empty_ladder_is_rejected_at_the_cli(self):
        with pytest.raises(ValueError, match="at least one rung"):
            cap_ladder.parse_values(SWEPT_KNOB, " , ")


class TestASweepCannotLeaveTheShippedValueSwapped:
    """The file's reason to exist. Each test asserts the value is BACK, having first asserted it was
    genuinely swapped — an assertion that only checks the restore would pass against a no-op."""

    def test_a_knob_is_restored_after_a_normal_rung(self):
        knobs = cast(dict[str, Any], shade.KNOBS)
        shipped = knobs[SWEPT_KNOB]
        with cap_ladder.swapped(SWEPT_KNOB, 0.0):
            assert knobs[SWEPT_KNOB] == 0.0, "the swap must actually take effect"
        assert knobs[SWEPT_KNOB] == shipped

    def test_a_knob_is_restored_when_the_rung_raises(self):
        """The predecessors' restore was the next loop iteration, so a crash mid-ladder left the
        process running under whichever rung had died — and anything it wrote afterwards, including
        the freshness sidecar, described a look nobody chose."""
        knobs = cast(dict[str, Any], shade.KNOBS)
        shipped = knobs[SWEPT_KNOB]
        with pytest.raises(RuntimeError), cap_ladder.swapped(SWEPT_KNOB, 0.0):
            raise RuntimeError("gdalwarp died mid-rung")
        assert knobs[SWEPT_KNOB] == shipped

    def test_the_encoder_quality_is_restored_the_same_way(self):
        shipped = cap_render.CAP_WEBP_QUALITY
        with pytest.raises(RuntimeError), cap_ladder.swapped("quality", 60):
            assert cap_render.CAP_WEBP_QUALITY == 60
            raise RuntimeError("interrupted")
        assert cap_render.CAP_WEBP_QUALITY == shipped

    def test_the_recipe_the_sidecar_records_returns_to_the_shipped_one(self):
        """The end-to-end statement of the bug, in the currency that actually mattered. `cap_recipe`
        reads the module constants, so a leaked swap makes the sidecar describe the swept look —
        which is how damp-0.0 pixels came to sit under a recipe the freshness gate called current."""
        grid = cap_render.north_grid(bodies.EARTH)
        shipped_recipe = cap_render.cap_recipe(grid, WHOLE_PLANET)
        with cap_ladder.swapped(SWEPT_KNOB, 0.0):
            assert cap_render.cap_recipe(grid, WHOLE_PLANET) != shipped_recipe, (
                "sweeping this knob must move the recipe, or the sidecar could never have lied"
            )
        assert cap_render.cap_recipe(grid, WHOLE_PLANET) == shipped_recipe

    def test_an_unknown_axis_is_refused_rather_than_silently_added(self):
        """`KNOBS` is a plain dict at runtime, so a typo'd axis would otherwise CREATE a key —
        sweeping a knob the composite never reads and reporting a clean run over identical pixels."""
        knobs = cast(dict[str, Any], shade.KNOBS)
        with (pytest.raises(KeyError, match="unknown axis"),
              cap_ladder.swapped("ice_releif_damp", 0.5)):  # codespell:ignore
            pass
        assert "ice_releif_damp" not in knobs  # codespell:ignore


class TestGridAxesRebuildRatherThanPatch:
    def test_a_pixel_rung_returns_a_new_grid_and_leaves_the_shipped_one_alone(self):
        """`px` is a frozen-dataclass field, so it is varied by building a second grid. The shipped
        grid must be untouched: it is what `restore_live_caps` and `cap_recipe` read."""
        shipped = cap_render.north_grid(bodies.EARTH)
        rung = cap_ladder.grid_for_rung(shipped, "px", 4096)
        assert rung.px == 4096
        assert shipped.px == cap_render.CAP_PX
        assert rung == dataclasses.replace(shipped, px=4096)  # nothing else moved with it

    def test_a_knob_rung_leaves_the_grid_exactly_as_it_was(self):
        shipped = cap_render.north_grid(bodies.EARTH)
        assert cap_ladder.grid_for_rung(shipped, SWEPT_KNOB, 0.5) is shipped

    def test_swapping_a_grid_axis_patches_nothing(self):
        """A grid axis has nothing to restore, and must not reach the KNOBS branch and invent a
        `px` key there."""
        knobs = cast(dict[str, Any], shade.KNOBS)
        before = dict(knobs)
        with cap_ladder.swapped("px", 4096):
            assert dict(knobs) == before
        assert "px" not in knobs


class TestTheLadderIsBodyScoped:
    def test_the_archive_lives_under_the_body_being_swept(self):
        """A ladder writes into the body's own work tree, so two bodies' sweeps of the same axis
        cannot overwrite each other's rungs."""
        earth = cap_ladder.ladder_dir(bodies.EARTH, SWEPT_KNOB)
        assert earth == cap_render.cap_work_dir(bodies.EARTH) / "ladder" / SWEPT_KNOB
        other = dataclasses.replace(bodies.EARTH, name="testbody", path_prefix="testbody")
        assert cap_ladder.ladder_dir(other, SWEPT_KNOB) != earth

    def test_the_body_is_required_with_no_default(self):
        """Matching the cap and planet passes. A defaulted body would let a sweep of one planet's
        knob land in another planet's served directory."""
        parser = cap_ladder.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--axis", SWEPT_KNOB, "--values", "0.5"])
        args = parser.parse_args(["--body", "earth", "--axis", SWEPT_KNOB, "--values", "0.5"])
        assert args.body == "earth"

    def test_the_axis_and_the_rungs_are_both_required(self):
        parser = cap_ladder.build_parser()
        for incomplete in (["--body", "earth"],
                           ["--body", "earth", "--axis", SWEPT_KNOB],
                           ["--body", "earth", "--values", "0.5"]):
            with pytest.raises(SystemExit):
                parser.parse_args(incomplete)
