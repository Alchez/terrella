"""snow.antarctic_snow_mask: the shared rule that forces Antarctic land white in BOTH the tile
composite and the south cap. RGI region 19 is excluded and NSIDC-0791 persistence saturates over the
whole continent -- median 0.9999 measured on exposed rock itself, against a ramp cutoff of 0.60 --
so nothing else whitens it and nothing else could un-whiten it either; one home for the rule keeps
the two paths agreeing across the -84 cap<->tile seam.
"""

import numpy as np

from pipeline.look import snow


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


class TestExposedRockComesOutFromUnderTheWhite:
    """SCAR ADD's rock outcrop, SUBTRACTED rather than unioned.

    THE SUBTRACTION IS THE DESIGN AND NOT AN IMPLEMENTATION CHOICE. A union of "where the data says
    ice" would need a data-availability branch, and the boundary between "the dataset answers here"
    and "the latitude rule answers here" is a hard edge across the ice shelves — which is exactly
    what the superseded MODIS arm drew, as thin tan outlines. Removing rock from a rule that
    otherwise covers the whole continent has no such boundary anywhere.

    `rock` stays OPTIONAL because the argument is about a dataset and the rule is not: a body that
    declares no rock layer, or a window built before the raster existed, must get today's answer
    exactly rather than a plausible one.
    """

    def test_rock_on_cold_land_is_not_forced_white(self):
        land = np.ones((1, 3), bool)
        latitude = np.array([-75.0])
        rock = np.array([[True, False, True]])
        assert snow.antarctic_snow_mask(land, latitude, rock=rock).ravel().tolist() == \
            [0.0, 1.0, 0.0]

    def test_rock_outside_the_cold_land_region_changes_nothing(self):
        """Rock north of the cutoff and rock on ocean are both already 0.0, so neither can move.

        The arm that makes this non-vacuous is the case above: without it, a mask that simply
        returned zeros everywhere would satisfy this one.
        """
        land = np.array([[True, False]])
        latitude = np.array([-40.0])
        rock = np.ones((1, 2), bool)
        assert (snow.antarctic_snow_mask(land, latitude, rock=rock) ==
                snow.antarctic_snow_mask(land, latitude)).all()

    def test_omitting_rock_reproduces_todays_answer_exactly(self):
        """The default is not "no rock anywhere", it is "this caller has nothing to say about rock".

        Both spellings are checked because `rock=None` is what a body without the layer passes and
        an omitted argument is what every existing call site passes, and a signature that made them
        differ would break one of the two silently.
        """
        land = np.array([[True, True], [True, False]])
        latitude = np.array([-70.0, -50.0])
        expected = [[1.0, 1.0], [0.0, 0.0]]
        assert snow.antarctic_snow_mask(land, latitude).tolist() == expected
        assert snow.antarctic_snow_mask(land, latitude, rock=None).tolist() == expected

    def test_rock_takes_the_same_two_latitude_shapes_the_rule_does(self):
        """The AEQD cap passes 2-D per-pixel latitude and the Mercator path 1-D per-row, and rock is
        a full 2-D field on both. A rock term that only worked against one of them would pass every
        tile test and fail on the cap alone, which is the seam this rule exists to hold."""
        land = np.ones((2, 2), bool)
        rock = np.array([[True, False], [False, False]])
        per_row = snow.antarctic_snow_mask(land, np.array([-70.0, -70.0]), rock=rock)
        per_pixel = snow.antarctic_snow_mask(
            land, np.array([[-70.0, -70.0], [-70.0, -70.0]]), rock=rock)
        assert per_row.tolist() == per_pixel.tolist() == [[0.0, 1.0], [1.0, 1.0]]

    def test_it_still_returns_float32_with_rock_applied(self):
        rock = np.array([[True, False]])
        mask = snow.antarctic_snow_mask(np.ones((1, 2), bool), np.array([-80.0]), rock=rock)
        assert mask.dtype == np.float32
