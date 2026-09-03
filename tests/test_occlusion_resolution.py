"""The region preview and the planet must occlude at the SAME ground resolution.

Found: they disagreed by 12.9x. The region path sized its sky-view downsample with a
region-local `long_edge = 2400` (~760 m/px of ground at Iran) while the planet used
`SVF_LONG_EDGE = 4096` over a raster 18x wider (~9,784 m/px). The region exists to PREDICT the
planet, so every A/B run through it — including the tuning that set `svf_strength` and
`svf_threshold` — was judged at a resolution production does not have.

Neither number was wrong locally, which is why nothing caught it: 2400 is a sensible preview size
and 4096 is a sensible global one. The bug only exists in the comparison, and nothing compared
them. So these tests compare them, and they assert on GROUND metres per pixel — the quantity that
actually has to match — rather than on either path's pixel counts.
"""

import math

import pytest

from pipeline import bodies
from pipeline.look.sky_view import OCCLUSION_TARGET_M_PER_PX, occlusion_shape
from pipeline.mercator import Z8_MERC_RES

# The planet grid's pixel, which is now the BODY's rather than a module constant. Earth's, because
# these are Earth's measured production numbers (131072 x 93009, 2907 x 4096 occlusion).
Z8_RES = bodies.EARTH.map_units_per_pixel

PLANET_WIDTH, PLANET_HEIGHT = 131072, 93009   # the production grid, top 85.05N, bottom -60S


def ground_m_per_px(full_width: int, full_height: int, full_res_m_per_px: float) -> float:
    """Ground scale a path actually achieves, from the shape `occlusion_shape` hands it."""
    _, small_width = occlusion_shape(full_width, full_height, full_res_m_per_px)
    return full_res_m_per_px * (full_width / small_width)


class TestBothPathsLandOnTheSameGroundScale:

    def test_planet_hits_the_shared_target(self):
        achieved = ground_m_per_px(PLANET_WIDTH, PLANET_HEIGHT, Z8_RES)
        assert achieved == pytest.approx(OCCLUSION_TARGET_M_PER_PX, rel=0.01)

    @pytest.mark.parametrize("cells, mid_lat", [(2, 35.0), (1, 5.0), (2, 55.0), (4, 65.0)])
    def test_region_hits_the_same_target(self, cells: int, mid_lat: float):
        """A region of any size or latitude must resolve what the planet resolves — no better."""
        width = round(cells * 10.0 / 360.0 * 2 * math.pi * 6378137.0 / Z8_MERC_RES)
        full_res = Z8_MERC_RES * math.cos(math.radians(mid_lat))
        achieved = ground_m_per_px(width, width, full_res)
        assert achieved == pytest.approx(OCCLUSION_TARGET_M_PER_PX, rel=0.05)

    def test_the_old_region_size_would_fail_this(self):
        """Can-fail companion: pin the magnitude of the bug this file exists to prevent.

        Without it, a future edit could restore a region-local pixel count and these tests would
        still pass on the planet alone.
        """
        iran_width, iran_height = 7281, 4456
        old_small_width = round(iran_width / max(iran_width, iran_height) * 2400)
        old_ground = (Z8_MERC_RES * math.cos(math.radians(35.0))) * (iran_width / old_small_width)
        assert old_ground == pytest.approx(760.0, abs=10.0)
        assert OCCLUSION_TARGET_M_PER_PX / old_ground == pytest.approx(12.9, abs=0.5)


class TestOcclusionShapeContract:

    def test_never_upsamples(self):
        """A source already coarser than the target must be used as-is, not blown up."""
        assert occlusion_shape(100, 50, OCCLUSION_TARGET_M_PER_PX * 4) == (50, 100)

    def test_preserves_aspect(self):
        rows, cols = occlusion_shape(PLANET_WIDTH, PLANET_HEIGHT, Z8_RES)
        assert cols / rows == pytest.approx(PLANET_WIDTH / PLANET_HEIGHT, rel=0.01)

    def test_planet_shape_is_unchanged_by_the_refactor(self):
        """Production must be byte-identical: the old code read (2907, 4096) and so must this."""
        assert occlusion_shape(PLANET_WIDTH, PLANET_HEIGHT, Z8_RES) == (2907, 4096)
