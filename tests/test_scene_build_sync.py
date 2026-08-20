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
    def test_sea_stops(self, scene_build):
        assert scene_build.SEA_STOPS == rgba_stops(palette.SEA_STOPS)

    def test_land_stops(self, scene_build):
        assert scene_build.LAND_STOPS == rgba_stops(palette.LAND_STOPS)

    def test_lake_stops(self, scene_build):
        assert scene_build.LAKE_STOPS == rgba_stops(palette.LAKE_STOPS)

    def test_ranges(self, scene_build):
        """BOTH ends read off the Surface, which is what this used to be unable to see.

        It compared against a literal `0.0`, so the rig restating that literal — the third copy of
        the datum-is-zero assumption, in the one module a type checker cannot connect to the other
        two — was indistinguishable from the rig reading the ramp. Sourcing both ends here means a
        re-hardcoded zero fails on the first body whose ramp does not start at one.
        """
        earth = palette.EARTH_LOOK
        assert earth.sea is not None
        assert scene_build.SEA_RANGE == (earth.sea.extreme_m, earth.sea.origin_m)
        assert scene_build.LAND_RANGE == (earth.land.origin_m, earth.land.extreme_m)
        # The bridge to the authored constants stays, one level up: those are what `RAMP_GLOBALS`
        # guards, and losing it would let the assembled look drift from the values it was written
        # from while this test happily compared the look against itself.
        assert (earth.sea.extreme_m, earth.land.extreme_m) == (palette.SEA_MIN_M, palette.LAND_MAX_M)

    def test_the_origin_is_READ_and_not_coincidentally_zero(self, scene_build, monkeypatch):
        """The test above cannot fail on a re-hardcoded `0.0`, and pretending otherwise is worse
        than not guarding it.

        Earth's ramps both start at 0 m, so `origin_m` and the literal are the same value and no
        assertion over Earth can tell a read from a restatement. Heroes are Earth-only, so there is
        no second body to supply the difference either — the way out is to supply one that does not
        exist in production: patch the look, re-import, and watch the rig follow. Restored by a
        second reload, because the module-scoped fixture hands the same object to every test here.
        """
        moved = palette.Look(
            land=palette.Surface(stops=palette.EARTH_LOOK.land.stops,
                                 origin_m=-1234.0, extreme_m=palette.LAND_MAX_M),
            sea=palette.EARTH_LOOK.sea,
        )
        monkeypatch.setattr(palette, "EARTH_LOOK", moved)
        try:
            reloaded = importlib.reload(scene_build)
            assert reloaded.LAND_RANGE == (-1234.0, palette.LAND_MAX_M)
        finally:
            monkeypatch.undo()
            importlib.reload(scene_build)
        assert scene_build.LAND_RANGE == (0.0, palette.LAND_MAX_M)


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
