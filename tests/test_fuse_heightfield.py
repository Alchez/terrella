"""Tests for the fusion rules that decide which pixels are 'ocean'.

The load-bearing tests are the two exclusions in `TestIsCaspian`: the Caspian rule is a
deliberate special case, and its bbox and surface threshold are the only things stopping
it from reaching water bodies that would REGRESS if routed through GEBCO — above all the
Dead Sea, which is also a below-sea-level WBM lake but has no GEBCO bathymetry, so it
would collapse to `min(gebco, -1) = -1` and render as a flat bright slab.
"""

import numpy as np
import pytest
from rasterio.transform import from_origin
from rasterio.windows import Window

from pipeline.fuse import fuse_heightfield

RES = 10 / 3600.0  # the 10-arcsecond planet master


def _probe(cell_west, cell_north, lon, lat, wbm_value, land_value):
    """Run is_caspian on a small window centred on one lon/lat of a 10-degree cell."""
    transform = from_origin(cell_west, cell_north, RES, RES)
    window = Window(int((lon - cell_west) / RES),  # pyright: ignore[reportCallIssue] — rasterio untyped
                    int((cell_north - lat) / RES), 4, 4)
    wbm = np.full((4, 4), wbm_value, dtype=np.uint8)
    land = np.full((4, 4), land_value, dtype=np.float32)
    result = fuse_heightfield.is_caspian(transform, window, wbm, land)
    return bool(np.any(result))


class TestIsCaspian:
    @pytest.mark.parametrize("lon,lat,label", [
        (51.0, 41.5, "deep basin"),
        (50.5, 45.5, "north shelf"),
        (53.5, 41.0, "Kara-Bogaz-Gol side"),
    ])
    def test_caspian_water_is_absorbed(self, lon, lat, label):
        """WBM lake at the Caspian's uniform -28 m surface, inside the bbox."""
        assert _probe(50, 50, lon, lat, wbm_value=2, land_value=-28) is True

    def test_land_inside_the_bbox_is_untouched(self):
        """The bbox alone must not flood anything — WBM has to agree it is water."""
        assert _probe(50, 50, 51.0, 41.5, wbm_value=0, land_value=-28) is False

    def test_river_inside_the_bbox_is_untouched(self):
        """Only class 2 (lake); inland rivers keep their flat-water treatment."""
        assert _probe(50, 50, 51.0, 41.5, wbm_value=3, land_value=-28) is False

    def test_mingevir_reservoir_is_excluded_by_surface(self):
        """The only other WBM lake in the bbox sits at +83 m — the surface test drops it."""
        assert _probe(40, 50, 47.0, 40.5, wbm_value=2, land_value=83) is False

    def test_dead_sea_is_excluded_by_bbox(self):
        """A below-sea-level WBM lake with NO GEBCO bathymetry: absorbing it would collapse
        to min(gebco, -1) = -1 and render as a flat bright slab. The bbox is the only guard."""
        assert _probe(30, 40, 35.5, 31.5, wbm_value=2, land_value=-430) is False

    def test_baikal_is_excluded_by_bbox(self):
        """Above sea level, so its margins would hit the land ramp — out of scope entirely."""
        assert _probe(100, 60, 107.5, 53.5, wbm_value=2, land_value=456) is False

    def test_far_window_short_circuits_without_allocating(self):
        """648 cells, 4 of which touch the Caspian: the other 644 must not pay for a
        BLOCK-sized boolean array per window."""
        transform = from_origin(100, 60, RES, RES)
        big = Window(0, 0, 8192, 8192)  # pyright: ignore[reportCallIssue] — rasterio untyped
        result = fuse_heightfield.is_caspian(
            transform, big, np.zeros((8192, 8192), np.uint8),
            np.zeros((8192, 8192), np.float32))
        assert result is False
