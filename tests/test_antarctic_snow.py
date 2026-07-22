"""snow.antarctic_snow_mask: the shared rule that forces Antarctic land white in BOTH the tile
composite and the south cap. NSIDC-0791 persistence is NH-only and RGI region 19 is excluded, so
nothing else whitens the continent; one home for the rule keeps the two paths agreeing across the
-84 cap<->tile seam.
"""

import numpy as np

from pipeline.render import snow


class TestAntarcticSnowMask:
    def test_southern_land_is_forced_white(self):
        land = np.ones((1, 4), bool)
        latitude = np.array([-70.0])
        assert (snow.antarctic_snow_mask(land, latitude) == 1.0).all()

    def test_ocean_is_never_forced(self):
        """Only LAND is whitened -- the Southern Ocean keeps its sea/ice rendering."""
        land = np.zeros((2, 4), bool)
        latitude = np.array([-80.0, -75.0])
        assert (snow.antarctic_snow_mask(land, latitude) == 0.0).all()

    def test_land_north_of_the_cutoff_stays_bare(self):
        """Sub-Antarctic land north of -60 stays on the tan land ramp (the deferred RGI-19 case)."""
        land = np.ones((3, 4), bool)
        latitude = np.array([-59.0, -40.0, 10.0])
        assert (snow.antarctic_snow_mask(land, latitude) == 0.0).all()

    def test_per_row_latitude_broadcasts_down_columns(self):
        """The Mercator tile path passes a 1-D per-row latitude; it must apply across every column."""
        land = np.ones((2, 5), bool)
        latitude = np.array([-70.0, -50.0])  # row 0 forced, row 1 bare
        mask = snow.antarctic_snow_mask(land, latitude)
        assert (mask[0] == 1.0).all() and (mask[1] == 0.0).all()

    def test_per_pixel_latitude_is_used_element_for_element(self):
        """The AEQD cap passes a 2-D per-pixel latitude; no reshape."""
        land = np.ones((2, 2), bool)
        latitude = np.array([[-70.0, -55.0], [-40.0, -80.0]])
        assert snow.antarctic_snow_mask(land, latitude).tolist() == [[1.0, 0.0], [0.0, 1.0]]

    def test_it_is_the_AND_of_land_and_cold(self):
        """Companion: forced only where land AND south of the cutoff -- a cold ocean pixel and a warm
        land pixel are both 0, so neither term alone is doing the work."""
        land = np.array([[True, False], [True, False]])
        latitude = np.array([-80.0, -30.0])  # row 0 cold, row 1 warm
        assert snow.antarctic_snow_mask(land, latitude).tolist() == [[1.0, 0.0], [0.0, 0.0]]

    def test_a_custom_cutoff_moves_the_line(self):
        """Companion: the guard tracks lat_max rather than reading a constant -60."""
        land = np.ones((2, 1), bool)
        latitude = np.array([-58.0, -52.0])
        assert snow.antarctic_snow_mask(land, latitude, lat_max=-55.0).ravel().tolist() == [1.0, 0.0]

    def test_returns_float32(self):
        """composite does np.maximum(snow_a, mask) with a float snow_a, so the mask must be float."""
        assert snow.antarctic_snow_mask(np.ones((1, 1), bool), np.array([-80.0])).dtype == np.float32
