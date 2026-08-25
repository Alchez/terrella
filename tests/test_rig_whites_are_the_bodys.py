"""The rig's ice whites must be the BODY's, and today they are one global spelling of Earth's.

WHAT THIS GUARDS, AND WHY A GLOBAL SURVIVED SO LONG. `scene_build.RIG.snow_rgba` is
`palette.SNOW_RGB` and reaches every render of every body, while the composite tier asks the
producer registry, which answers `_earth_white` for Earth and `_mars_ice_white` for Mars. The two
agree on Earth by coincidence of VALUE — the registry hands back the very constant the rig reads —
so no Earth pixel has ever disagreed and nothing has ever gone red. On Mars they do not agree at
all: its whites are warm (F3EFE7 north, FFEFC6 south, measured off the Viking mosaic) against
Earth's cool blue-white E8F1F6, and `palette`'s own note says blue-in-shadow "is Earth physics and
does not travel".

`perennial_ice` is in `layers.BLOCK_LAYERS`, so a raytraced Mars reaches the rig and paints its
polar deposits in Earth's white. Nothing on disk can show it: the mask is correct, the recipe is
recorded, every gate is green.

THE INTERPRETER BOUNDARY IS WHY "THE RIG ASKS THE REGISTRY" CANNOT BE LITERAL. `scene_build` runs
in Blender's Python, which reaches `palette` (numpy only) but not `layer_producers`, which pulls
rasterio, GDAL and the download modules. So the authority must reach the rig the way every other
per-window fact already does — resolved by the prep, written into the render directory, declared
through `render_seam`. These tests therefore assert the CONTRACT (the rig renders the body's white)
and not a call, so they stay true whichever transport is built.

Derived from the registry rather than listing bodies, on the rule that a guard catching omission
from a hand-written list should derive the list instead: a third body joins these assertions by
existing.
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

    A PAINT MAY VARY WITHIN A WINDOW, which is why this takes a latitude at all: Mars's producer
    chooses per row, because its two poles are different colours. Everything else is the smallest
    shape that satisfies the dataclass — no producer reads it to decide a colour.
    """
    latitude = np.full(rows, latitude_deg, dtype=np.float64)
    ones = np.ones((rows, 1), dtype=np.float64)
    return layer_producers.LayerWindow(
        raw=None, watercode=None, land=ones.astype(bool), latitude=latitude,
        ground_metres_per_px=ones, top=0.0, bottom=0.0)


def registry_whites(body: bodies.Body) -> dict[str, tuple]:
    """The sunlit white this body's own producers declare for each ice layer that reaches the rig.

    Asked of the producer rather than read off `palette`, because that indirection IS the fix: a
    test that reached for `palette.SNOW_RGB` here would pass for Mars while Mars renders wrong.
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
    """The headline contract, and the one that is red today."""

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
        """The premise the defect rests on: if no Martian ice layer reached the rig, the global
        would be harmless. `perennial_ice` is `in_block`, so it does."""
        mars = bodies.BODIES["mars"]
        assert mars.surface_layers & WHITE_LAYERS & layers.BLOCK_LAYERS, (
            "Mars declares no ice layer reaching a Cycles render; this suite's premise is gone"
        )

    def test_mars_declares_a_warm_white_earth_does_not_have(self):
        """The oracle, stated as a fact about the registry rather than about a render.

        Mars's deposits are warm (F3EFE7 / FFEFC6, measured off the Viking mosaic); Earth's snow is
        cool blue-white. `palette`'s own note says blue-in-shadow is Earth physics that does not
        travel, so this is not a near-miss that a tolerance could absorb.
        """
        martian = set(registry_whites(bodies.BODIES["mars"]).values())
        terrestrial = set(registry_whites(bodies.BODIES["earth"]).values())
        assert martian, "Mars declares no white at all"
        assert not (martian & terrestrial), (
            f"Mars {martian} and Earth {terrestrial} share a white; the two bodies were measured "
            f"separately and should not agree"
        )

    def test_the_rig_does_not_paint_mars_in_earths_white(self, scene_build, tmp_path):
        """The defect in one sentence: a raytraced Mars discards a Viking measurement."""
        assert rig_white(scene_build, bodies.BODIES["mars"], tmp_path) not in set(
            registry_whites(bodies.BODIES["earth"]).values()), (
            "the rig paints Martian polar ice in Earth's snow white"
        )


class TestEarthDoesNotMove:
    """The positive control. Every assertion above must be satisfiable WITHOUT changing an Earth
    pixel, or the fix ships a look change nobody judged on a body that has already been ratified.
    """

    def test_earths_registry_white_is_still_the_authored_constant(self):
        """What the fix must preserve: Earth's producers answer `palette.SNOW_RGB`, so routing the
        rig through the registry leaves Earth's rendered white bit-identical."""
        assert palette.SNOW_RGB in set(registry_whites(bodies.BODIES["earth"]).values())

    def test_the_rig_still_paints_earth_the_authored_white(self, scene_build, tmp_path):
        """Green before the fix and green after. If this ever fails, the fix moved Earth.

        The values are 8-bit sRGB on both sides, so this is byte equality and not a tolerance: the
        registry hands back `palette.SNOW_RGB` and the seam carries it unchanged, which is what
        makes routing the rig through the registry cost Earth nothing.
        """
        assert rig_white(scene_build, bodies.BODIES["earth"], tmp_path) == palette.SNOW_RGB


class TestTheRigHoldsNoWhiteOfItsOwn:
    """The other half of the fix: no fallback to fall back TO.

    A rig that kept a default would satisfy every assertion above while still rendering a body in
    another body's white the moment a prep forgot to declare one — the silent path this whole seam
    exists to remove.
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
