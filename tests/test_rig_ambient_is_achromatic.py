"""The rig's ambient must carry no hue, because a tint REPLACES a near-white rather than tinting it.

`RIG.world_rgba` is not a backdrop swatch, it is the scene's only coloured light: the two suns
carry energy and angle and nothing else. Authored as `F2E7D5`, it arrives with a linear B/R of
0.749, and a surface whose own colour is nearly white has almost no blue to defend. Measured on the
Iceland hero arms, the warm ambient costs snow 9 of its 14 DN of blue, the sea 4 of 56, and land
essentially nothing. That asymmetry is why this bit the poles alone.

WHAT THESE PIN. The decision (no hue), that it was a HUE-ONLY move (the luminance of the colour it
replaces is preserved, so this is not the twice-rejected ambient raise wearing a new hat), and the
consequence on the surface that was damaged. The luminance anchor is derived from `F2E7D5` here so
the warm world survives as this file's reference point and nowhere else in the tree.

Freshness needs no test of its own: `rig_recipe` is `dataclasses.asdict(RIG)` and
`test_scene_build_sync` pins that identity, so this constant cannot move without restaging.
"""

import dataclasses
import importlib
import sys
import types
from typing import cast

import numpy as np
import pytest

from pipeline import bodies, layers
from pipeline.look import layer_producers, palette

#: Rec.709, the weighting every luminance claim in this repo is made in.
LUMINANCE = np.array([0.2126, 0.7152, 0.0722])

#: The warm ambient this replaces, as it was authored: an sRGB hex, not a linear triple.
WARM_WORLD_HEX = (0xF2, 0xE7, 0xD5)


@pytest.fixture(scope="module")
def scene_build():
    """`scene_build` with bpy stubbed, the same import the sync suite uses.

    The stub is removed afterwards so no other test can lean on it.
    """
    stubbed = "bpy" not in sys.modules
    if stubbed:
        sys.modules["bpy"] = types.ModuleType("bpy")
    try:
        yield importlib.import_module("pipeline.render.scene_build")
    finally:
        if stubbed:
            del sys.modules["bpy"]


def reflected(albedo_srgb8, world_rgba):
    """What a diffuse surface returns under an illuminant, per channel and in LINEAR light.

    Cycles integrates per channel, so an illuminant multiplies an albedo channel-wise. Only the
    ratio between channels is asserted on: the absolute scale here is not the render's, which also
    carries both suns.
    """
    return np.array(palette.srgb8_to_linear(albedo_srgb8)) * np.array(world_rgba[:3])


def blue_to_red(linear_rgb):
    return float(linear_rgb[2] / linear_rgb[0])


def earth_snow_white():
    """Earth's authored sunlit white, from the registry that owns it rather than from `palette`.

    Asking the producer keeps this honest if a body's white moves, and keeps it from becoming the
    global spelling the rig has just stopped carrying. Earth's paint ignores its window (its two
    poles are one colour, unlike Mars's), which is why there is nothing to build one from here.
    """
    paint = layer_producers.producer_for(bodies.EARTH, layers.PERENNIAL_ICE).paint(
        cast(layer_producers.LayerWindow, None))
    assert paint is not None, "Earth's perennial ice declares no white"
    return paint[0]


class TestTheDecision:
    def test_the_world_carries_no_hue(self, scene_build):
        red, green, blue = scene_build.RIG.world_rgba[:3]
        assert red == green == blue, f"the ambient is still tinted: {scene_build.RIG.world_rgba}"

    def test_it_is_a_light_and_the_suns_stay_colourless(self, scene_build):
        """The anti-vacuity arm: neutralising the world is only worth doing while it is the ONLY
        coloured emitter. A sun given a colour later would restore the defect by another route,
        and `Rig` has no field to hold one."""
        fields = {field.name for field in dataclasses.fields(scene_build.RIG)}
        assert not {name for name in fields
                    if name.startswith(("sun_", "fill_")) and name.endswith(("rgba", "color"))}


class TestItMovesHueNotBrightness:
    def test_it_holds_the_luminance_of_the_colour_it_replaces(self, scene_build):
        """1.0x, not a value that looked right. Raising the world to brighten was tried and
        rejected (ART, Light balance): it brightens without modeling."""
        warm = np.array(palette.srgb8_to_linear(WARM_WORLD_HEX))
        assert float(np.dot(LUMINANCE, scene_build.RIG.world_rgba[:3])) == pytest.approx(
            float(np.dot(LUMINANCE, warm)), abs=1e-6)

    def test_its_strength_did_not_move(self, scene_build):
        """The companion to the above. Luminance held in the colour and then given back in the
        strength is the same rejected raise, split over two fields."""
        assert scene_build.RIG.world_strength == 0.3


class TestTheSurfaceThatWasDamaged:
    def test_a_near_white_keeps_its_blue_to_red_ratio(self, scene_build):
        """The reason, stated on the surface. A grey illuminant scales every channel alike, so an
        albedo's hue survives it exactly; only the brightness falls."""
        white = earth_snow_white()
        assert blue_to_red(reflected(white, scene_build.RIG.world_rgba)) == pytest.approx(
            blue_to_red(np.array(palette.srgb8_to_linear(white))), rel=1e-9)

    def test_the_warm_world_it_replaces_fails_that(self):
        """The positive control, so a passing suite above is never the oracle silently doing
        nothing. `F2E7D5` must still visibly destroy the ratio, by its own B/R of 0.749."""
        white = earth_snow_white()
        warm = (*palette.srgb8_to_linear(WARM_WORLD_HEX), 1.0)
        authored = blue_to_red(np.array(palette.srgb8_to_linear(white)))
        assert blue_to_red(reflected(white, warm)) == pytest.approx(authored * 0.7494, rel=1e-3)
