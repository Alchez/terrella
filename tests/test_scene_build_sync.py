"""scene_build's look constants are DERIVED from palette — this guards the derivation.

scene_build runs only under Blender's Python (`import bpy`), so it was historically
ast-parsed and never imported, and its constants were COPIES — which is how three
divergences accumulated undetected (sea ramp, water tint, sun altitude; the ART.md audit).
Since the sea-sync the constants are imports from
`pipeline.look.palette`; these tests stub bpy and import the module in the venv, so
any re-inlined literal fails HERE instead of on a hero render.
"""

import importlib
import math
import sys
import types

import pytest

from pipeline.look import palette


@pytest.fixture(scope="module")
def scene_build():
    """Import scene_build with bpy stubbed (it is only touched at render time, never
    at module import). The stub is removed afterwards so no other test can lean on it."""
    stubbed = "bpy" not in sys.modules
    if stubbed:
        sys.modules["bpy"] = types.ModuleType("bpy")
    try:
        yield importlib.import_module("pipeline.render.scene_build")
    finally:
        if stubbed:
            del sys.modules["bpy"]


def rgba_stops(stops):
    return [(pos, (*rgb, 1.0)) for pos, rgb in stops]


class TestRampsAreThePalettes:
    """These used to address module attributes bound to `EARTH_LOOK` at import. `look_constants`
    keeps every assertion behind one indirection and lets the same set run for a second body."""

    def test_sea_stops(self, scene_build):
        earth = scene_build.look_constants(palette.EARTH_LOOK)
        assert earth.sea_stops == rgba_stops(palette.SEA_STOPS)

    def test_land_stops(self, scene_build):
        earth = scene_build.look_constants(palette.EARTH_LOOK)
        assert earth.land_stops == rgba_stops(palette.LAND_STOPS)

    def test_lake_stops(self, scene_build):
        """Still a module attribute, because the lake ramp is not on `Look` — it is one shared
        depth ramp with no per-body values authored yet."""
        assert scene_build.LAKE_STOPS == rgba_stops(palette.LAKE_STOPS)

    def test_ranges(self, scene_build):
        """BOTH ends read off the Surface, which is what this used to be unable to see.

        It compared against a literal `0.0`, so the rig restating that literal — the third copy of
        the datum-is-zero assumption, in the one module a type checker cannot connect to the other
        two — was indistinguishable from the rig reading the ramp.
        """
        earth = palette.EARTH_LOOK
        assert earth.sea is not None
        constants = scene_build.look_constants(earth)
        assert constants.sea_range == (earth.sea.extreme_m, earth.sea.origin_m)
        assert constants.land_range == (earth.land.origin_m, earth.land.extreme_m)
        # The bridge to the authored constants stays, one level up: those are what `RAMP_GLOBALS`
        # guards, and losing it would let the assembled look drift from the values it was written
        # from while this test happily compared the look against itself.
        assert (earth.sea.extreme_m, earth.land.extreme_m) == (palette.SEA_MIN_M, palette.LAND_MAX_M)

    def test_the_origin_is_READ_and_not_coincidentally_zero(self, scene_build):
        """The test above cannot fail on a re-hardcoded `0.0`, and pretending otherwise is worse
        than not guarding it.

        Earth's ramps both start at 0 m, so `origin_m` and the literal are the same value and no
        assertion over Earth can tell a read from a restatement. Passing a look with a moved origin
        supplies the difference — which is what taking the look as an ARGUMENT bought: this used to
        need `importlib.reload` around a monkeypatched module global.
        """
        moved = palette.Look(
            land=palette.Surface(stops=palette.EARTH_LOOK.land.stops,
                                 origin_m=-1234.0, extreme_m=palette.LAND_MAX_M),
            sea=palette.EARTH_LOOK.sea,
        )
        assert scene_build.look_constants(moved).land_range == (-1234.0, palette.LAND_MAX_M)
        assert scene_build.look_constants(palette.EARTH_LOOK).land_range == (
            0.0, palette.LAND_MAX_M)


class TestASeaLessLookDropsTheSeaBranch:
    """The generalisation's second instance. Every assertion above passes on Earth by
    construction, so Mars is what decides whether the rig takes a look or still binds one."""

    def test_mars_gets_no_sea_ramp(self, scene_build):
        assert palette.MARS_LOOK.sea is None
        mars = scene_build.look_constants(palette.MARS_LOOK)
        assert (mars.sea_range, mars.sea_stops) == (None, None)

    def test_mars_still_gets_its_own_land_ramp(self, scene_build):
        mars = scene_build.look_constants(palette.MARS_LOOK)
        assert mars.land_stops == rgba_stops(palette.MARS_LAND_STOPS)
        assert mars.land_range == (palette.MARS_LOOK.land.origin_m,
                                   palette.MARS_LOOK.land.extreme_m)
        assert mars.land_range != scene_build.look_constants(palette.EARTH_LOOK).land_range

    def test_the_oceanmask_is_not_asked_for(self, scene_build):
        """A sea-less body never names the raster its planet seam declines to declare, so the
        rig cannot fail on a missing file that was never supposed to exist."""
        earth_images = scene_build.images_for(palette.EARTH_LOOK)
        mars_images = scene_build.images_for(palette.MARS_LOOK)
        assert scene_build.SEA_IMAGE in earth_images
        assert scene_build.SEA_IMAGE not in mars_images
        assert set(earth_images) - set(mars_images) == {scene_build.SEA_IMAGE}

    def test_the_lake_and_river_masks_stay_mandatory_for_every_look(self, scene_build):
        """The oceanmask is the only image a LOOK can answer for, because it selects between this
        look's two ramps. Inland water is a planet-seam declaration rather than a colour, so keying
        it off `sea is None` here would answer a question the look was never asked."""
        for look in (palette.EARTH_LOOK, palette.MARS_LOOK):
            names = scene_build.images_for(look)
            assert "Image Texture.002" in names and "Image Texture.003" in names

    def test_earths_image_table_and_its_order_are_untouched(self, scene_build):
        """The dump-diff against the hand-built .blend sees creation order, so the sea-less arm
        must not have reordered the arm that renders 203 heroes."""
        assert list(scene_build.images_for(palette.EARTH_LOOK)) == list(scene_build.IMAGES)


class TestFlatTintsAreThePalettes:
    def test_water_is_the_relational_tint(self, scene_build):
        """The 98C5C8 drift's cure: the hero flat water IS palette.WATER_RGB."""
        assert scene_build.WATER_RGBA == (*palette.srgb8_to_linear(palette.WATER_RGB), 1.0)

    def test_snow_is_the_shared_white(self, scene_build):
        assert scene_build.SNOW_RGBA == (*palette.srgb8_to_linear(palette.SNOW_RGB), 1.0)


class TestSunAltitudeIsShared:
    def test_x_tilt_derives_from_sun_alt_deg(self, scene_build):
        """The 46-vs-45 split's cure: the X tilt is 90 − the shared altitude."""
        assert math.degrees(scene_build.SUN_ROTATION[0]) == pytest.approx(
            90.0 - palette.SUN_ALT_DEG)

    def test_azimuth_unchanged(self, scene_build):
        assert math.degrees(scene_build.SUN_ROTATION[2]) == pytest.approx(-45.0)
