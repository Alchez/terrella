"""The rig paints each body's ice in a white that body's own producers declare.

What this refuses is a white held on the rig itself. Such a global agrees with Earth's registry
answer by coincidence of value, so no Earth pixel disagrees and nothing goes red, while a raytraced
Mars paints its polar deposits in Earth's snow with the mask correct, the recipe recorded and every
gate green. `perennial_ice` is `in_block`, so Martian ice really does reach the rig.

"The rig asks the registry" cannot be literal, because `scene_build` runs in Blender's Python, which
reaches `palette` (numpy only) but not `layer_producers` and its rasterio and GDAL. So the answer
travels the way every other per-window fact does: resolved by the prep, written into the render
directory, declared through `render_seam`. These tests assert that contract end to end rather than
any one call, so they stay true whichever transport is built.

Derived from the registry rather than listing bodies, so a third body joins by existing.
"""

import dataclasses
import importlib
import sys
import types

import numpy as np
import pytest

from pipeline import bodies, layers
from pipeline.look import layer_producers, palette
from pipeline.render import prep_block, render_seam


@pytest.fixture(scope="module")
def scene_build():
    """`scene_build` with bpy stubbed, the same import the sync suite has used since the sea-sync.

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


#: The ice layers whose paint reaches a Cycles render. Not a literal list: a layer joins by being
#: declared `in_block`, which is the same question `prep_block` asks when it decides what to cut.
WHITE_LAYERS = frozenset({layers.PERENNIAL_ICE.name, layers.GLACIERS.name, layers.SEA_ICE.name})


def polar_window(latitude_deg: float, rows: int = 4) -> layer_producers.LayerWindow:
    """A minimal window at one latitude, enough for a paint producer to answer.

    A paint may vary within a window, which is why this takes a latitude at all: Mars's producer
    resolves per row against its two poles. Everything else is the smallest shape that satisfies the
    dataclass, and no producer reads it to decide a colour.
    """
    latitude = np.full(rows, latitude_deg, dtype=np.float64)
    ones = np.ones((rows, 1), dtype=np.float64)
    return layer_producers.LayerWindow(
        raw=None, watercode=None, land=ones.astype(bool), ocean=~ones.astype(bool),
        latitude=latitude,
        ground_metres_per_px=ones, top=0.0, bottom=0.0)


def registry_whites(body: bodies.Body) -> dict[str, tuple]:
    """The sunlit white this body's own producers declare for each ice layer that reaches the rig.

    Asked of the producer rather than read off `palette`, because that indirection is the contract:
    a test reaching for `palette.SNOW_RGB` here would pass for Mars while Mars rendered wrong.
    """
    whites: dict[str, tuple] = {}
    for layer_name in sorted(body.surface_layers & WHITE_LAYERS & layers.BLOCK_LAYERS):
        producer = layer_producers.PRODUCER_BY_BODY_LAYER.get((body.name, layer_name))
        if producer is None:
            continue
        for latitude_deg in (85.0, -85.0):
            paint = producer.paint(polar_window(latitude_deg))
            if paint is None:
                continue
            sunlit = np.asarray(paint[0], dtype=np.float64).reshape(3, -1)[:, 0]
            whites[f"{layer_name}@{latitude_deg:+.0f}"] = tuple(np.rint(sunlit).astype(int))
    return whites


def rig_white(scene_build, body: bodies.Body, render_dir) -> tuple:
    """The sunlit white the rig actually paints this body's ice with, driven END TO END.

    BOTH HALVES OF THE SEAM RUN HERE and that is deliberate. The prep's own reducer resolves the
    body's registry answer for a window, `render_seam` transports it, and the rig's own accessor
    reads it back — so this fails if either side stops honouring the other, which a test that
    inspected one constant could not do. It needs no GPU: everything up to the shader socket is
    ordinary Python.
    """
    resolved: dict[str, tuple] = {}
    for layer in layer_producers.WHITE_UNION:
        producer = layer_producers.PRODUCER_BY_BODY_LAYER.get((body.name, layer.name))
        if producer is None or layer.name not in body.surface_layers:
            continue
        answered = producer.paint(polar_window(85.0))
        if answered is not None:
            resolved[layer.name] = answered
    paint = prep_block.merged_paint(resolved, layer_producers.WHITE_UNION, "the white union")
    assert paint is not None, f"{body.name} declares no white for the union"
    render_seam.declare_paint(render_dir, render_seam.SNOWMASK, *paint)
    linear = scene_build.declared_albedo(render_dir, render_seam.SNOWMASK)[:3]
    return tuple(round(255 * (12.92 * channel if channel <= 0.0031308
                              else 1.055 * channel ** (1 / 2.4) - 0.055))
                 for channel in linear)


class TestTheRigPaintsEachBodysOwnWhite:
    """The headline contract."""

    @pytest.mark.parametrize("name", sorted(bodies.BODIES))
    def test_the_rig_white_is_one_the_bodys_registry_declares(self, scene_build, name, tmp_path):
        """Whatever the rig paints ice with must be a colour this body's producers chose.

        Not "equals `palette.SNOW_RGB`", which is the assertion that has been green throughout and
        is exactly why nothing caught this: it is true of Earth by construction and true of Mars
        only because the rig ignores Mars.
        """
        body = bodies.BODIES[name]
        declared = registry_whites(body)
        if not declared:
            pytest.skip(f"{name} declares no ice layer that reaches a Cycles render")
        painted = rig_white(scene_build, body, tmp_path)
        assert painted in set(declared.values()), (
            f"the rig paints {name}'s ice {painted}, which none of its producers declare: "
            f"{declared}. A rig holding its own white renders every body in whichever one was "
            f"authored first."
        )

    def test_two_bodies_with_different_whites_do_not_render_the_same_one(self, scene_build,
                                                                        tmp_path):
        """The general statement, so a third body is covered without being named here.

        A rig holding ONE white cannot satisfy two bodies that declare different ones, and this is
        what says so without asserting any particular colour.
        """
        rendered = {name: rig_white(scene_build, bodies.BODIES[name], tmp_path / name)
                    for name in sorted(bodies.BODIES)
                    if registry_whites(bodies.BODIES[name])}
        declared = {name: set(registry_whites(bodies.BODIES[name]).values())
                    for name in rendered}
        disagreeing = [(a, b) for a in declared for b in declared
                       if a < b and not (declared[a] & declared[b])]
        assert disagreeing, "no two bodies declare different whites; this guard has nothing to hold"
        for first, second in disagreeing:
            assert rendered[first] != rendered[second], (
                f"{first} and {second} declare disjoint whites {declared[first]} and "
                f"{declared[second]}, yet the rig renders both as {rendered[first]}"
            )


class TestMarsIsTheInstanceThatMakesItVisible:
    """Named rather than derived, because the measurement behind it is Mars's alone."""

    def test_mars_ice_reaches_a_cycles_render(self):
        """The premise the contract rests on: if no Martian ice layer reached the rig, a global
        white would be harmless. `perennial_ice` is `in_block`, so it does."""
        mars = bodies.BODIES["mars"]
        assert mars.surface_layers & WHITE_LAYERS & layers.BLOCK_LAYERS, (
            "Mars declares no ice layer reaching a Cycles render; this suite's premise is gone"
        )

    def test_mars_declares_a_white_earth_does_not_have(self):
        """The oracle, stated as a fact about the registry rather than about a render.

        The two whites were decided separately: Earth's is authored on its own physics, since
        blue-in-shadow is glacial ice absorbing red and does not travel, and Mars's is authored on a
        rendered frame. Nothing makes them converge, so sharing a value would mean one body had
        inherited the other's rather than agreeing with it.
        """
        martian = set(registry_whites(bodies.BODIES["mars"]).values())
        terrestrial = set(registry_whites(bodies.BODIES["earth"]).values())
        assert martian, "Mars declares no white at all"
        assert not (martian & terrestrial), (
            f"Mars {martian} and Earth {terrestrial} share a white; the two bodies were measured "
            f"separately and should not agree"
        )

    def test_the_rig_does_not_paint_mars_in_earths_white(self, scene_build, tmp_path):
        """In one sentence: a raytraced Mars must not be painted in Earth's snow."""
        assert rig_white(scene_build, bodies.BODIES["mars"], tmp_path) not in set(
            registry_whites(bodies.BODIES["earth"]).values()), (
            "the rig paints Martian polar ice in Earth's snow white"
        )


class TestEarthDoesNotMove:
    """The positive control. Every assertion above is satisfiable without changing an Earth pixel,
    and if it stops being so, the seam has moved a body that was already ratified.
    """

    def test_earths_registry_white_is_still_the_authored_constant(self):
        """Earth's producers answer `palette.SNOW_RGB`, so routing the rig through the registry
        leaves Earth's rendered white bit-identical."""
        assert palette.SNOW_RGB in set(registry_whites(bodies.BODIES["earth"]).values())

    def test_the_rig_still_paints_earth_the_authored_white(self, scene_build, tmp_path):
        """If this fails, the seam moved Earth.

        The values are 8-bit sRGB on both sides, so this is byte equality and not a tolerance: the
        registry hands back `palette.SNOW_RGB` and the seam carries it unchanged, which is what
        makes routing the rig through the registry cost Earth nothing.
        """
        assert rig_white(scene_build, bodies.BODIES["earth"], tmp_path) == palette.SNOW_RGB


class TestTheRigHoldsNoWhiteOfItsOwn:
    """The other half of the seam: no fallback to fall back to.

    A rig keeping a default satisfies every assertion above and still renders a body in another
    body's white the moment a prep forgets to declare one.
    """

    def test_the_rig_constants_carry_no_ice_albedo(self, scene_build):
        fields = {field.name for field in dataclasses.fields(scene_build.RIG)}
        assert not (fields & {"snow_rgba", "ice_rgba"}), (
            f"{fields & {'snow_rgba', 'ice_rgba'}} is a second authority for a colour the body's "
            f"registry already owns"
        )

    def test_an_undeclared_paint_raises_rather_than_defaulting(self, scene_build, tmp_path):
        """The load-bearing refusal. A guess here is invisible in every artifact it produces."""
        with pytest.raises(FileNotFoundError, match="painted in"):
            scene_build.declared_albedo(tmp_path, render_seam.SNOWMASK)


class TestTheOldTrackingIsGone:
    """Moving the albedo out of `Rig` took it out of `rig_recipe`, which is where a white re-tune
    used to reach freshness. That it now reaches it through `constants_for(painted=True)` instead
    is `test_block_render.TestTheRecipeRecordsWhatThePrepGradesWith`'s to hold — the recipe's own
    suite, with the harness and the control already built. This asserts only the half that belongs
    here: that the rig stopped carrying it.
    """

    def test_the_rig_recipe_no_longer_carries_the_white(self, scene_build):
        assert "snow_rgba" not in scene_build.rig_recipe(palette.EARTH_LOOK)
