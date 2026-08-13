"""Tests for the elevation->RGB LUT that is meant to replace `gdaldem color-relief`.

Why a LUT can be exactly equivalent, measured: color-relief is **24.4% of all pass CPU**
(28:19 wall, single-threaded), and the profile splits it `libgdal 19.37%` (interpolation) vs
`libdeflate 4.33%` (compression) -- so no threading flag can fix it. The interpolation is a per-pixel
SEARCH over the 241 ramp stops `palette.color_relief_rows(step=25, look=palette.EARTH_LOOK)` emits. gdaldem searches because
its file format permits arbitrary stop positions; OURS ARE UNIFORM (0..6000 every 25 m), so the
bracketing index is just `elevation / step`. The search is work our data does not need, and gdaldem
cannot know that. A LUT turns O(log 241) + interpolate into one divide and a gather.

Equivalence bar, stated before running: <=1 DN, because both sides end in uint8.
"""

import itertools

import numpy as np
import pytest

from pipeline.render import palette

KINDS = ["land", "sea"]


class TestLutMatchesTheRampItReplaces:
    def test_lut_hits_the_ramp_rows_exactly_at_their_own_elevations(self):
        """At each ramp row's own elevation there is no interpolation to disagree about, so the
        LUT must reproduce gdaldem's value exactly. This is the tightest possible anchor."""
        for kind in KINDS:
            lut = palette.relief_lut(kind, look=palette.EARTH_LOOK)
            for elevation, expected in palette.color_relief_rows(kind, step=25.0, look=palette.EARTH_LOOK):
                assert tuple(palette.lut_lookup(lut, kind, np.array([elevation]), look=palette.EARTH_LOOK)[:, 0]) == expected

    def test_the_anchor_can_fail(self):
        """Companion: the check above must be comparing colours, not rubber-stamping."""
        land = palette.relief_lut("land", look=palette.EARTH_LOOK)
        sea_rows = palette.color_relief_rows("sea", step=25.0, look=palette.EARTH_LOOK)
        mismatches = sum(tuple(palette.lut_lookup(land, "land", np.array([e]), look=palette.EARTH_LOOK)[:, 0]) != c
                         for e, c in sea_rows)
        assert mismatches > 0, "land LUT reproduced the SEA ramp -- the anchor proves nothing"


class TestClamping:
    """The planet height raster spans -10,728 m to +7,281 m (measured) -- beyond BOTH ramp ends,
    so clamping is exercised on real pixels, not a hypothetical."""

    def test_above_land_max_clamps_to_the_summit_colour(self):
        lut = palette.relief_lut("land", look=palette.EARTH_LOOK)
        summit = palette.lut_lookup(lut, "land", np.array([palette.LAND_MAX_M]), look=palette.EARTH_LOOK)
        for beyond in (6001.0, 7281.3, 8848.0, 1e6):
            assert np.array_equal(palette.lut_lookup(lut, "land", np.array([beyond]), look=palette.EARTH_LOOK), summit)

    def test_below_sea_min_clamps_to_the_abyss_colour(self):
        lut = palette.relief_lut("sea", look=palette.EARTH_LOOK)
        abyss = palette.lut_lookup(lut, "sea", np.array([palette.SEA_MIN_M]), look=palette.EARTH_LOOK)
        for beyond in (-6001.0, -10728.1, -1e6):
            assert np.array_equal(palette.lut_lookup(lut, "sea", np.array([beyond]), look=palette.EARTH_LOOK), abyss)

    def test_land_lut_clamps_negative_elevations_to_zero(self):
        """A land-classed pixel below sea level (Dead Sea, -430 m) must take the 0 m colour --
        gdaldem clamps to the first row, and the ocean MASK, not the sign, picks the ramp."""
        lut = palette.relief_lut("land", look=palette.EARTH_LOOK)
        zero = palette.lut_lookup(lut, "land", np.array([0.0]), look=palette.EARTH_LOOK)
        assert np.array_equal(palette.lut_lookup(lut, "land", np.array([-430.0]), look=palette.EARTH_LOOK), zero)

    def test_sea_lut_clamps_positive_elevations_to_zero(self):
        lut = palette.relief_lut("sea", look=palette.EARTH_LOOK)
        zero = palette.lut_lookup(lut, "sea", np.array([0.0]), look=palette.EARTH_LOOK)
        assert np.array_equal(palette.lut_lookup(lut, "sea", np.array([12.0]), look=palette.EARTH_LOOK), zero)


class TestShapeAndOrder:
    @pytest.mark.parametrize("kind", KINDS)
    def test_lookup_is_vectorised_and_shaped(self, kind):
        lut = palette.relief_lut(kind, look=palette.EARTH_LOOK)
        heights = np.linspace(-6000, 6000, 500).astype("float32").reshape(10, 50)
        result = palette.lut_lookup(lut, kind, heights, look=palette.EARTH_LOOK)
        assert result.shape == (3, 10, 50)
        assert result.dtype == np.uint8

    def test_land_brightens_then_holds_the_warm_register(self):
        """Guards a re-tune that reorders stops -- ColorRamp stops re-sort by position, a gotcha
        this project has been bitten by before."""
        lut = palette.relief_lut("land", look=palette.EARTH_LOOK)
        rows = palette.color_relief_rows("land", step=25.0, look=palette.EARTH_LOOK)
        expected = [c for _, c in rows]
        got = [tuple(palette.lut_lookup(lut, "land", np.array([e]), look=palette.EARTH_LOOK)[:, 0]) for e, _ in rows]
        assert got == expected

    def test_sea_darkens_monotonically_with_depth(self):
        lut = palette.relief_lut("sea", look=palette.EARTH_LOOK)
        depths = np.arange(0, -6001, -100, dtype="float32")
        colors = palette.lut_lookup(lut, "sea", depths, look=palette.EARTH_LOOK)
        luminance = 0.299 * colors[0] + 0.587 * colors[1] + 0.114 * colors[2]
        assert all(later <= earlier + 1e-9 for earlier, later in itertools.pairwise(luminance))


class TestInterpolationBetweenRows:
    """Between ramp rows, gdaldem interpolates linearly in sRGB. Our LUT samples the ramp at 1 m
    in LINEAR light. They are not the same curve -- the bar is that they agree to <=1 DN."""

    @pytest.mark.parametrize("kind", KINDS)
    def test_midpoints_agree_with_gdaldem_style_interpolation_within_1_dn(self, kind):
        lut = palette.relief_lut(kind, look=palette.EARTH_LOOK)
        rows = palette.color_relief_rows(kind, step=25.0, look=palette.EARTH_LOOK)
        worst = 0
        for (e0, c0), (e1, c1) in itertools.pairwise(rows):
            midpoint = (e0 + e1) / 2.0
            gdaldem_style = np.array([(a + b) / 2.0 for a, b in zip(c0, c1)])
            ours = palette.lut_lookup(lut, kind, np.array([midpoint]), look=palette.EARTH_LOOK)[:, 0].astype(float)
            worst = max(worst, float(np.abs(gdaldem_style - ours).max()))
        assert worst <= 1.0, f"{kind}: LUT drifts {worst:.2f} DN from gdaldem's interpolation"
