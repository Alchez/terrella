"""Earth's fill light is a blue sky's, and every surface but the land is recoloured so it does not show.

The fill lights the shade, and on Earth that light is the sky's, so it takes a blackbody colour from
the look; Mars's sky is not blue and its fill stays white. A blue fill left alone turns snow, salt,
sea ice, water and the sea bluer on every face, and the land cooler in its shade, which is the part
wanted. So the rig multiplies each of the others through by what the fill does to flat, sunlit, open
ground, and there they render as they did under a white fill.

No gate here renders, so none of this can see a pixel. What it holds is the arithmetic, the wiring
and the two bodies' values; whether the result looks right was judged on rendered blocks.
"""

import ast
import dataclasses
import importlib
import math
import sys
import types
from pathlib import Path
from typing import cast

import numpy as np
import pytest

from pipeline import bodies, layers, render_files
from pipeline.look import layer_producers, palette

#: Rec.709, the weighting every luminance claim in this repo is made in.
LUMINANCE = np.array([0.2126, 0.7152, 0.0722])

WHITE = (1.0, 1.0, 1.0)

#: Blender 5.1.2's blackbody, read off a light: every temperature from 12,000 K up returns 12,000 K's
#: colour, and the temperature field refuses anything below 800 K.
BLACKBODY_CEILING_K = 12000.0
BLACKBODY_FLOOR_K = 800.0


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


def planckian(kelvin: float) -> tuple[float, float, float]:
    """A blackbody's colour in linear Rec.709 at unit luminance, by Kang et al. (2002).

    Unit luminance is how Blender scales a light's temperature colour, and the builder refuses a
    Blender that scales it otherwise. Kang's fit holds from 4,000 to 25,000 K and agrees with
    Blender's own blackbody within 0.2%, so it is an oracle the rig does not share.
    """
    x = (-3.0258469e9 / kelvin ** 3 + 2.1070379e6 / kelvin ** 2 + 0.2226347e3 / kelvin
         + 0.240390)
    y = 3.0817580 * x ** 3 - 5.87338670 * x ** 2 + 3.75112997 * x - 0.37001483
    tristimulus = np.array([x / y, 1.0, (1.0 - x - y) / y])
    to_rec709 = np.array([[3.2406, -1.5372, -0.4986],
                          [-0.9689, 1.8758, 0.0415],
                          [0.0557, -0.2040, 1.0570]])
    linear = to_rec709 @ tristimulus
    red, green, blue = linear / float(LUMINANCE @ linear)
    return float(red), float(green), float(blue)


def earths_fill() -> tuple[float, float, float]:
    kelvin = palette.EARTH_LOOK.fill_kelvin
    assert kelvin is not None, "Earth's fill is white, so nothing below has a colour to cancel"
    return planckian(kelvin)


def flat_open_ground(scene_build, albedo, fill_rgb) -> np.ndarray:
    """What flat, sunlit ground with nothing above it returns, per channel and in linear light.

    Lambertian: each sun lands by the cosine of its tilt from the zenith, over pi, and a uniform
    world arrives whole. Written from the rig's fields here rather than by calling the builder,
    so the two statements of the law are separate.
    """
    rig = scene_build.RIG
    sun = rig.sun_strength * math.cos(rig.sun_rotation[0])
    fill = rig.fill_strength * math.cos(rig.fill_rotation[0]) * np.asarray(fill_rgb)
    world = np.asarray(rig.world_rgba[:3]) * rig.world_strength
    return np.asarray(albedo) * ((sun + fill) / math.pi + world)


def blue_to_red(linear_rgb) -> float:
    return float(linear_rgb[2] / linear_rgb[0])


def earth_snow_white() -> np.ndarray:
    """Earth's authored sunlit snow, from the registry that owns it rather than from `palette`, in
    linear light. Earth's paint ignores its window."""
    paint = layer_producers.producer_for(bodies.EARTH, layers.PERENNIAL_ICE).paint(
        cast(layer_producers.LayerWindow, None))
    assert paint is not None, "Earth's perennial ice declares no white"
    return np.array(palette.srgb8_to_linear(paint[0]))


class TestEachBodyFillsFromItsOwnSky:
    def test_earths_fill_is_blenders_12000_k(self):
        """His pick, over 15,000 K, on the tile blocks he judged. A temperature is a look value."""
        assert palette.EARTH_LOOK.fill_kelvin == 12000.0

    def test_mars_fill_is_white(self):
        """His call after seeing both. Mars's sky is not blue, and the rovers' measured skylight,
        a pinkish 4,575 K, was rendered on both Mars blocks and not chosen."""
        assert palette.MARS_LOOK.fill_kelvin is None

    @pytest.mark.parametrize("name", sorted(palette.LOOK_BY_BODY))
    def test_no_look_asks_blender_for_a_colour_it_cannot_render(self, name):
        """Past the ceiling Blender renders 12,000 K and raises nothing, so a hotter look would be
        judged as a change and ship as none."""
        kelvin = palette.LOOK_BY_BODY[name].fill_kelvin
        assert kelvin is None or BLACKBODY_FLOOR_K <= kelvin <= BLACKBODY_CEILING_K, kelvin


class TestAFillChangeRestagesEveryRender:
    def test_the_recipe_records_the_looks_fill(self, scene_build):
        recipe = scene_build.rig_recipe(palette.EARTH_LOOK, render_files.KNOWN_IMAGES)
        assert recipe["look"]["fill_kelvin"] == palette.EARTH_LOOK.fill_kelvin

    def test_moving_it_moves_the_recipe(self, scene_build):
        """The look section is spelled field by field, so a look value it forgets restages
        nothing."""
        cooler = dataclasses.replace(palette.EARTH_LOOK, fill_kelvin=10000.0)
        assert (scene_build.rig_recipe(cooler, render_files.KNOWN_IMAGES)
                != scene_build.rig_recipe(palette.EARTH_LOOK, render_files.KNOWN_IMAGES))


class TestSnowKeepsItsColourUnderTheBlueFill:
    """The surface he judged the blue fill on. It read too blue to him, and the white he preferred
    is the one it now returns on flat ground."""

    def test_flat_sunlit_snow_returns_what_it_did_under_a_white_fill(self, scene_build):
        fill = earths_fill()
        white = earth_snow_white()
        compensation = scene_build.fill_compensation(fill)
        albedo = scene_build.compensated((*white, 1.0), compensation)[:3]
        np.testing.assert_allclose(flat_open_ground(scene_build, albedo, fill),
                                   flat_open_ground(scene_build, white, WHITE), rtol=1e-9)

    def test_without_it_the_snow_turns_blue(self, scene_build):
        """The positive control: the fill really does move snow, by more than the tolerance above
        could hide."""
        white = earth_snow_white()
        fill = earths_fill()
        shift = (blue_to_red(flat_open_ground(scene_build, white, fill))
                 / blue_to_red(flat_open_ground(scene_build, white, WHITE)))
        assert shift > 1.05, shift

    def test_the_compensation_is_the_one_he_judged(self, scene_build):
        """The factor the approved blocks were rendered with, computed from Kang's colour at the
        white fill's luminance; on those blocks it brought sea, lakes, salt and Greenland's snow
        back to the white fill's within about 1 DN."""
        np.testing.assert_allclose(
            scene_build.fill_compensation(earths_fill()),
            (1.021, 1.0007, 0.9368), rtol=2e-3)

    def test_a_white_fill_compensates_nothing(self, scene_build):
        """Exactly, so Mars renders as it did."""
        assert scene_build.fill_compensation(WHITE) == (1.0, 1.0, 1.0)


class TestTheCompensationReachesEverySurfaceButTheLand:
    """Every colour `build_material` hands a node is multiplied through by the compensation, except
    the land ramp's.

    The land is left out on purpose: the cooler shade on rock is what the blue fill was chosen for,
    and compensating it gives that back. The other six were retuned by his eye on rendered blocks.

    Source text, because the claim is about what the builder writes at each site. A colour site is
    a ramp's stops or an RGBA socket's default; the list of what each wraps is source text too.
    """

    COMPENSATED = frozenset({
        "declared_albedo(render_dir, render_files.SNOWMASK)",
        "declared_albedo(render_dir, render_files.SALTMASK)",
        "declared_albedo(render_dir, render_files.SEAICE)",
        "RIG.water_rgba",
        "RIG.lake_stops",
        "constants.sea_stops",
    })
    UNCOMPENSATED = frozenset({"constants.land_stops"})
    WRAPPERS = frozenset({"compensated", "compensated_stops"})

    @classmethod
    def colour_sites(cls, source: str) -> tuple[set[str], set[str]]:
        """(what the wrapped sites wrap, what the bare sites pass) inside `build_material`."""
        function = next(node for node in ast.walk(ast.parse(source))
                        if isinstance(node, ast.FunctionDef) and node.name == "build_material")
        values = []
        for node in ast.walk(function):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "make_ramp"):
                values.append(node.args[3])
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if not (isinstance(target, ast.Attribute) and target.attr == "default_value"):
                        continue
                    socket = target.value
                    rgba_input = (isinstance(socket, ast.Call) and isinstance(socket.func, ast.Name)
                                  and socket.func.id == "mix_socket")
                    output = isinstance(socket, ast.Subscript) and ast.unparse(socket).endswith(
                        ".outputs[0]")
                    if rgba_input or output:
                        values.append(node.value)
        wrapped, bare = set(), set()
        for value in values:
            if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id in cls.WRAPPERS):
                wrapped.add(ast.unparse(value.args[0]))
            else:
                bare.add(ast.unparse(value))
        return wrapped, bare

    def test_every_colour_but_the_lands_is_compensated(self, scene_build):
        wrapped, bare = self.colour_sites(Path(scene_build.__file__).read_text(encoding="utf-8"))
        assert bare == self.UNCOMPENSATED, f"colours reaching a node uncompensated: {sorted(bare)}"
        assert wrapped == self.COMPENSATED, f"compensated: {sorted(wrapped)}"

    def test_the_scan_sees_a_bare_colour(self):
        """The control. A scan that found no sites would pass nothing above, but it would also fail
        the equality, so this checks the other thing: a wrap stripped off is read as bare."""
        wrapped, bare = self.colour_sites(
            "def build_material(ob, render_dir, displacement_scale, look, present, compensation):\n"
            "    land = make_ramp(nt, 'Land Ramp', 'Land', constants.land_stops)\n"
            "    sea = make_ramp(nt, 'Sea Ramp', 'Sea', compensated_stops(constants.sea_stops, c))\n"
            "    mix_socket(snow, 'B').default_value = declared_albedo(render_dir, SNOW)\n"
            "    rgb.outputs[0].default_value = compensated(RIG.water_rgba, c)\n"
            "    float_socket(ice, 'B').default_value = RIG.ice_flatten_floor\n")
        assert wrapped == {"constants.sea_stops", "RIG.water_rgba"}
        assert bare == {"constants.land_stops", "declared_albedo(render_dir, SNOW)"}
