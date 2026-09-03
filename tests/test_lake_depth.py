"""Tests for the GLOBathy lake-depth layer: the ramp, the depth->position curve, the mask.

Two of these are load-bearing beyond their size:

  * `test_shore_stop_is_water_rgb` pins LAKE_STOPS[0] to WATER_RGB. An untracked colour
    relationship drifting silently is precisely how the whole inland-water thread started --
    test_palette.py froze the land/sea ramps but not WATER_RGB, the sea rework
    moved the sea out from under it, and nothing failed until it was spotted by eye in a
    screenshot. This is that guard, for the relationship that replaces it.
  * `TestLakesOnly` is the Caspian regression at unit level: the Caspian is watermask class 1
    since the re-fuse specifically so GEBCO's measured bathymetry beats GLOBathy's
    modelled cone there, and `lakes_only` is what enforces it.

Per
very lines the bug was in, so it passed on a broken scene), each guard here also has a
companion proving it FAILS on a known-bad input.
"""

import itertools

import numpy as np
import pytest

from pipeline.look import lake_depth, palette

CURVES = ["log1p", "sqrt", "linear"]


class TestLakeRamp:
    def test_shore_stop_is_water_rgb(self):
        """A lake's gradient must begin at exactly the flat tint its rivers and shallows
        use, or the two drift apart and the shoreline shows a seam."""
        assert palette._srgb8(palette.LAKE_STOPS[0][1]) == palette.WATER_RGB

    def test_shore_stop_guard_is_not_blind(self, monkeypatch):
        """The guard above must actually fire when the relationship breaks."""
        monkeypatch.setattr(palette, "LAKE_STOPS",
                            [(0.0, (1.0, 0.0, 0.0)), (1.0, (0.0, 0.0, 0.0))])
        assert palette._srgb8(palette.LAKE_STOPS[0][1]) != palette.WATER_RGB

    def test_lut_starts_at_water_rgb_and_ends_at_the_deep_stop(self):
        lut = palette.lake_lut()
        assert lut[0] == palette.WATER_RGB
        assert lut[-1] == palette._srgb8(palette.LAKE_STOPS[-1][1])

    def test_lut_darkens_monotonically_with_depth(self):
        """Deeper must never render lighter. Guards against a re-tune that reorders stops --
        ColorRamp stops re-sort by position, a gotcha this project has already been bitten by.
        """
        luminance = [0.299 * red + 0.587 * green + 0.114 * blue
                     for red, green, blue in palette.lake_lut()]
        assert all(later <= earlier + 1e-9
                   for earlier, later in itertools.pairwise(luminance))

    def test_srgb8_to_linear_roundtrips(self):
        """LAKE_STOPS[0] is derived through this, so a bug here silently shifts the shore."""
        for color in (palette.WATER_RGB, palette.SNOW_RGB, (0, 0, 0), (255, 255, 255)):
            assert palette._srgb8(palette.srgb8_to_linear(color)) == color


class TestLakePosition:
    @pytest.mark.parametrize("curve", CURVES)
    def test_shore_is_zero(self, curve):
        assert lake_depth.lake_position(np.array([0.0], "float32"), curve)[0] == 0.0

    @pytest.mark.parametrize("curve", CURVES)
    def test_deepest_lake_reaches_the_end(self, curve):
        position = lake_depth.lake_position(np.array([palette.LAKE_MAX_M], "float32"), curve)
        assert position[0] == pytest.approx(1.0)

    @pytest.mark.parametrize("curve", CURVES)
    def test_position_stays_in_range(self, curve):
        """The contract the LUT index depends on. LAKE_MAX_M is Baikal, GLOBathy's deepest,
        so nothing should exceed it -- but a curve that can return >1 is one re-tune of
        LAKE_MAX_M away from indexing off the end of the ramp."""
        depths = np.array([-5.0, 0.0, 1.0, 11.2, 1642.0, 5000.0], "float32")
        position = lake_depth.lake_position(depths, curve)
        assert position.min() >= 0.0
        assert position.max() <= 1.0

    @pytest.mark.parametrize("curve", CURVES)
    def test_position_is_monotonic(self, curve):
        depths = np.array([0.0, 5.0, 11.2, 50.0, 230.0, 1642.0], "float32")
        position = lake_depth.lake_position(depths, curve)
        assert all(later >= earlier for earlier, later in itertools.pairwise(position))

    def test_log1p_spreads_shallow_lakes_where_sqrt_does_not(self):
        """The measured reason log1p won: the median lake is 11.2 m, and sqrt parks it in
        the first tenth of the ramp (region p10-p90 spread 0.14 vs log1p's 0.38), i.e. sqrt
        is a no-op dressed as caution."""
        median_lake = np.array([11.2], "float32")
        assert lake_depth.lake_position(median_lake, "log1p")[0] > 0.3
        assert lake_depth.lake_position(median_lake, "sqrt")[0] < 0.1

    def test_unknown_curve_raises(self):
        with pytest.raises(ValueError, match="unknown LAKE_CURVE"):
            lake_depth.lake_position(np.array([1.0], "float32"), "cubic")


class TestLakesOnly:
    """watermask: 0 land, 1 ocean, 2 inland lake, 3 inland river."""

    def _depth(self):
        return np.full((2, 2), 40.0, dtype="float32")

    def test_lake_keeps_its_depth(self):
        result = lake_depth.lakes_only(self._depth(), np.full((2, 2), 2, "uint8"))
        assert (result == 40.0).all()

    def test_ocean_is_zeroed_so_the_caspian_keeps_gebco(self):
        """The Caspian is class 1 since the re-fuse precisely so GEBCO's MEASURED bathymetry
        wins over GLOBathy's cone -- which on the Caspian correlates just 0.53 and claims
        155 m where the truth is under 20 m."""
        result = lake_depth.lakes_only(self._depth(), np.full((2, 2), 1, "uint8"))
        assert (result == 0.0).all()

    def test_river_is_zeroed(self):
        """River depth was rejected outright: no global bed data exists."""
        result = lake_depth.lakes_only(self._depth(), np.full((2, 2), 3, "uint8"))
        assert (result == 0.0).all()

    def test_land_is_zeroed(self):
        result = lake_depth.lakes_only(self._depth(), np.zeros((2, 2), "uint8"))
        assert (result == 0.0).all()

    def test_mixed_window_masks_per_pixel(self):
        watercode = np.array([[2, 1], [3, 0]], dtype="uint8")
        result = lake_depth.lakes_only(self._depth(), watercode)
        assert result is not None  # lakes_only returns None only for a None depth; not this case
        assert result.tolist() == [[40.0, 0.0], [0.0, 0.0]]

    def test_none_passes_through(self):
        """warp_depth returns None when the VRT is absent, so shading still runs flat-only."""
        assert lake_depth.lakes_only(None, np.full((2, 2), 2, "uint8")) is None


class TestInlandWater:
    """`inland_water` selects the flat-tint classes (2 lake, 3 river) and MUST exclude ocean
    (class 1) -- the mirror of lakes_only's rule. The cap builder bypassed this and used
    `watermask.astype(bool)`, which caught class 1 and painted the whole Arctic sea flat WATER_RGB
    over the depth ramp (the 'disc glow'). These pin class 1 out for good."""

    def test_selects_lakes_and_rivers_only(self):
        codes = np.array([0, 1, 2, 3], dtype="uint8")
        assert lake_depth.inland_water(codes).tolist() == [False, False, True, True]

    def test_ocean_class_1_is_not_inland_water(self):
        """The exact regression: ocean is class 1, so it must stay False and keep the sea ramp."""
        assert not lake_depth.inland_water(np.full((2, 2), 1, "uint8")).any()

    def test_astype_bool_is_the_bug_and_this_check_catches_it(self):
        """Companion: the shortcut the cap used (`astype(bool)`) misclassifies ocean as inland
        water, and inland_water must disagree with it -- on exactly class 1."""
        codes = np.array([0, 1, 2, 3], dtype="uint8")
        assert codes.astype(bool).tolist() == [False, True, True, True]  # class 1 wrongly True
        assert lake_depth.inland_water(codes).tolist() != codes.astype(bool).tolist()


#: THE FOUR WIRING CASES HERE WENT WITH `shade.composite`. They asserted that a deep lake renders
#: darker than a shallow one, that no depth reproduces the flat fill, and that a zero-depth rim
#: lands on exactly `WATER_RGB` — all of it through the numpy compositor, which no body runs. The
#: CURVE itself survives above, and `render/lake_mask.py` is the hero path that still reads it.
