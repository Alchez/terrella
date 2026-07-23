"""scene_build's look constants are DERIVED from palette — this guards the derivation.

scene_build runs only under Blender's Python (`import bpy`), so it was historically
ast-parsed and never imported, and its constants were COPIES — which is how three
divergences accumulated undetected (sea ramp, water tint, sun altitude; the 2026-07-21
ART.md audit). Since the 2026-07-23 sea-sync the constants are imports from
`pipeline.render.palette`; these tests stub bpy and import the module in the venv, so
any re-inlined literal fails HERE instead of on a hero render.
"""

import importlib
import math
import sys
import types

import pytest

from pipeline.render import palette


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
        assert scene_build.SEA_RANGE == (palette.SEA_MIN_M, 0.0)
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
