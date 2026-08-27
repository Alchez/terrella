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


class TestTheGridCanBeFinerInLATITUDEALONE:
    """The high-latitude coastline lattice is a LATITUDE artefact, so the fix is a latitude grid.

    WHY ONLY ONE AXIS. The fusion master is geographic, so a source row is a fixed ground distance
    at every latitude while a Web-Mercator pixel spans `305.748 * cos(lat)` in BOTH axes. A source
    COLUMN shrinks by `cos(lat)` too, so the longitude ratio is 1.011 everywhere and only ROWS are
    replicated — 5.55x at 79.5N. Refining longitude would upsample 3 arcsec of native GLO-30 to 1
    and invent data; refining latitude is at the source's own resolution, which is 1 arcsec in
    latitude at every band.

    THE CONSUMER OF THIS IS `planet_seam._require_nested_grids`, which refuses a mask whose pixels
    straddle the heightfield's. That is why the ratio matters and not merely the size: these tests
    pin that a whole-number multiple is what comes out.
    """

    def test_the_default_is_square_and_unchanged(self):
        """The isotropic call must be untouched — every existing chunk on disk was written by it."""
        transform, width, height = fuse_heightfield.make_grid((10, 70, 20, 80), 10)
        assert (width, height) == (3600, 3600)
        assert transform.a == pytest.approx(RES)
        assert transform.e == pytest.approx(-RES)

    def test_a_finer_latitude_multiplies_ROWS_and_leaves_columns_alone(self):
        transform, width, height = fuse_heightfield.make_grid((10, 70, 20, 80), 10,
                                                              lat_res_arcsec=1)
        assert width == 3600, "longitude must not move: refining it would invent data"
        assert height == 36000
        assert transform.a == pytest.approx(RES), "the column width is the longitude resolution"
        assert transform.e == pytest.approx(-RES / 10)

    def test_the_origin_is_the_cells_corner_either_way(self):
        """A shifted origin would put the fine mask off the terrain it classifies, and the size
        ratio would still be a clean 10 — so nothing downstream would notice."""
        square = fuse_heightfield.make_grid((10, 70, 20, 80), 10)[0]
        fine = fuse_heightfield.make_grid((10, 70, 20, 80), 10, lat_res_arcsec=1)[0]
        assert (fine.c, fine.f) == (square.c, square.f) == (10, 80)

    def test_the_row_count_is_a_whole_multiple_so_the_grids_NEST(self):
        """`planet_seam._require_nested_grids` refuses anything else, so this is the property that
        actually has to hold rather than a restatement of the arithmetic above."""
        _, _, square = fuse_heightfield.make_grid((10, 70, 20, 80), 10)
        _, _, fine = fuse_heightfield.make_grid((10, 70, 20, 80), 10, lat_res_arcsec=1)
        assert fine % square == 0

    def test_a_latitude_resolution_that_does_not_divide_the_longitude_one_is_refused(self):
        """2.5 into 10 is 4 rows per row and nests; 3 does not, and the failure it causes is a
        sub-pixel misregistration that no image makes obvious."""
        with pytest.raises(ValueError, match="whole number"):
            fuse_heightfield.make_grid((10, 70, 20, 80), 10, lat_res_arcsec=3)


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
