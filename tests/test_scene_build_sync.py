"""scene_build's look constants are DERIVED from palette — this guards the derivation.

scene_build runs only under Blender's Python (`import bpy`), so it was historically
ast-parsed and never imported, and its constants were COPIES — which is how three
divergences accumulated undetected (sea ramp, water tint, sun altitude; the ART.md audit).
Since the sea-sync the constants are imports from
`pipeline.look.palette`; these tests stub bpy and import the module in the venv, so
any re-inlined literal fails HERE instead of on a hero render.
"""

import argparse
import ast
import dataclasses
import importlib
import json
import math
import re
import sys
import types
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

from pipeline import block_plan, bodies
from pipeline.look import palette
from pipeline.render import prep_block, render_prep, render_seam

#: What a filled render directory declares on each body, which is what the rig may load.
#:
#: NOT HAND-PICKED PER TEST: these are `prep_block.build`'s own two outcomes. Earth's planet seam
#: declares an oceanmask and a watermask, so the cut writes all four mandatory images; Mars declares
#: the heightfield alone, so it writes one and the rig must render without the other three. The
#: rowscale rides along on both and is optional, so it is not part of what is asserted here.
EARTH_DECLARED = frozenset({render_seam.HEIGHTFIELD, render_seam.OCEANMASK,
                            render_seam.INLANDLAKE, render_seam.RIVER})
MARS_DECLARED = frozenset({render_seam.HEIGHTFIELD})


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
        assert scene_build.RIG.lake_stops == rgba_stops(palette.LAKE_STOPS)

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


class TestTheRigsFilenamesHaveOneOwner:
    """`render_seam` owns the six spellings and the rig reads them from there.

    The drift this closes is not hypothetical: the prep that WRITES these files and the rig that
    LOADS them are different modules in different interpreters, and every one of the six was a
    literal in both. A rename touching one side is a scene that loads nothing, reported as a
    missing image rather than as the rename it is.
    """

    def test_the_rig_loads_only_images_the_seam_declares(self, scene_build):
        loaded = {spec.filename for spec in scene_build.TEXTURES.values()}
        assert loaded <= render_seam.KNOWN_IMAGES
        assert render_seam.HEIGHTFIELD in loaded, "the elevation is always loaded"

    def test_the_sea_image_is_the_oceanmask_by_name_and_not_by_position(self, scene_build):
        """`SEA_IMAGE` is a node name and the table maps it to a filename; a table reordered so
        that `.001` became a different mask would drop the wrong image for a sea-less body."""
        filename = scene_build.TEXTURES[scene_build.SEA_IMAGE].filename
        assert filename == render_seam.OCEANMASK


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
        earth_images = scene_build.textures_for(palette.EARTH_LOOK, EARTH_DECLARED)
        mars_images = scene_build.textures_for(palette.MARS_LOOK, MARS_DECLARED)
        assert scene_build.SEA_IMAGE in earth_images
        assert scene_build.SEA_IMAGE not in mars_images

    def test_earths_image_table_and_its_order_are_untouched(self, scene_build):
        """WHICH textures are mandatory is the claim; the list form is kept because it is strictly
        stronger than a set and costs nothing. Order itself no longer answers to anything — it was
        pinned for a dump-diff against a hand-built .blend that is retired, and the dump sorts by
        node name anyway."""
        mandatory = [name for name, spec in scene_build.TEXTURES.items() if not spec.optional]
        assert list(scene_build.textures_for(palette.EARTH_LOOK, EARTH_DECLARED)) == mandatory


class TestTheMandatoryImagesAreTheDirectorysAnswerAndNotTheLooks:
    """What the rig loads is what the prep DECLARED it wrote, which is the rule the optional four
    have always followed and the mandatory four were exempt from.

    THE EXEMPTION IS WHAT BLOCKED MARS. `prep_block.build` writes `inlandlake.png` and `river.png`
    only when the planet seam declared a watermask, and the rig loaded both for every look, so a
    body with no inland water was refused before its first block rather than rendered without them.
    The refusal was correct about the rig and is what this replaces.

    A LOOK STILL ANSWERS FOR THE SEA, and that has not collapsed into the declaration: `Look.sea`
    decides whether the sea BRANCH exists in the graph, the declaration decides whether the IMAGE
    can be loaded, and the pair that must never pass silently is a look with a sea over a directory
    with no oceanmask. That renders a planet of land, which is the failure the declaration rule
    exists to prevent, so it raises here rather than resolving to the smaller set.
    """

    def test_a_body_with_no_inland_water_loads_neither_mask(self, scene_build):
        names = scene_build.textures_for(palette.MARS_LOOK, MARS_DECLARED)
        assert {spec.filename for spec in names.values()} == {render_seam.HEIGHTFIELD}

    def test_a_body_that_declares_them_still_loads_both(self, scene_build):
        """The other direction, so the filter is not simply dropping them everywhere."""
        loaded = {spec.filename
                  for spec in scene_build.textures_for(palette.EARTH_LOOK, EARTH_DECLARED).values()}
        assert {render_seam.INLANDLAKE, render_seam.RIVER} <= loaded

    def test_a_look_with_a_sea_over_a_directory_with_no_oceanmask_refuses(self, scene_build):
        """The one pair that must not resolve quietly. Dropping the image because it was not
        declared would wire the sea ramp to nothing and render Earth as a planet of land, which is
        indistinguishable from a correct render of a body that has no sea."""
        with pytest.raises(ValueError, match="oceanmask"):
            scene_build.textures_for(palette.EARTH_LOOK, MARS_DECLARED)

    def test_the_recipe_does_not_move_when_the_declaration_does(self, scene_build):
        """The cost guard, and it is the reason this could land at all. `rig_recipe` records the
        whole TEXTURES table rather than the subset a directory loads, so making the load
        declaration-driven moves no recipe key and restages none of Earth's 1,024 blocks."""
        before = json.dumps(scene_build.rig_recipe(palette.EARTH_LOOK), sort_keys=True)
        after = json.dumps(scene_build.rig_recipe(palette.EARTH_LOOK), sort_keys=True)
        assert before == after
        assert "declared" not in before and render_seam.INLANDLAKE in before

    #: The subscript keys the builder may use with no conditional around them, AS SOURCE TEXT.
    #:
    #: Spelled rather than derived because the scan below reads the AST: it sees the expression a
    #: line uses for a node, never the node it resolves to at run time. Only the heightfield
    #: belongs here, and the reason is `render_seam.declared`'s own — it is the completion test, so
    #: a directory that declared anything at all declared that.
    ALWAYS_DECLARED: ClassVar[frozenset[str]] = frozenset({
        "texture_for(render_seam.HEIGHTFIELD).name",
    })

    def test_the_builder_subscripts_only_always_declared_images_unconditionally(self, scene_build):
        """The wiring half, which no stubbed-bpy test can reach by running it.

        `build_material` links `tex[...]` for every mandatory image, and two of those subscripts
        were unconditional — so a directory that legitimately declared neither raised `KeyError`
        deep in the graph rather than skipping the mix. Only the heightfield may be subscripted
        without a guard, because it is the one image `render_seam.declared` treats as the
        completion test and therefore the one every filled directory has.

        WHAT THIS CANNOT SEE is whether the enclosing condition is the RIGHT one: any `if` counts,
        so a subscript nested under a vacuous guard reads as covered here. It catches the shape the
        defect actually had, which is a subscript at the function's top level.
        """
        source = Path(scene_build.__file__).read_text()
        tree = ast.parse(source)
        builder = next(node for node in ast.walk(tree)
                       if isinstance(node, ast.FunctionDef) and node.name == "build_material")
        guarded, unguarded = self._subscripts(builder)
        assert unguarded <= self.ALWAYS_DECLARED, (
            f"build_material subscripts tex{sorted(unguarded - self.ALWAYS_DECLARED)} outside any "
            "conditional; a body whose prep declared none of those raises KeyError in the graph "
            f"instead of skipping the mix (guarded, and therefore fine: {sorted(guarded)})")

    def test_that_scan_can_see_an_unguarded_subscript(self, scene_build):
        """The control. The assertion above is satisfied by a walk that found no subscripts at
        all, which is what a renamed local or a restructured builder would produce."""
        builder = next(node for node in ast.walk(ast.parse(Path(scene_build.__file__).read_text()))
                       if isinstance(node, ast.FunctionDef) and node.name == "build_material")
        guarded, unguarded = self._subscripts(builder)
        assert guarded | unguarded, "the scan found no tex[...] subscripts at all"

    @staticmethod
    def _subscripts(builder: ast.FunctionDef) -> tuple[set[str], set[str]]:
        """Every `tex[...]` key in the builder, split by whether an `if` encloses it.

        The key is read as a NAME rather than a literal wherever the builder spells one, so
        `tex[spec.name]` is reported under the node name its spec carries; an unresolvable key is
        reported as unguarded, which fails toward flagging rather than toward silence.
        """
        guarded: set[str] = set()
        unguarded: set[str] = set()

        def walk(node: ast.AST, inside_if: bool) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.If):
                    for grandchild in ast.iter_child_nodes(child):
                        walk(grandchild, True)
                    continue
                if (isinstance(child, ast.Subscript) and isinstance(child.value, ast.Name)
                        and child.value.id == "tex"
                        # The build loop's `tex[name] = ...` is where the dict is FILLED, so it is
                        # not a read that can miss and must not be counted as one.
                        and not isinstance(child.ctx, ast.Store)):
                    key = (child.slice.value
                           if isinstance(child.slice, ast.Constant)
                           and isinstance(child.slice.value, str)
                           else ast.unparse(child.slice))
                    (guarded if inside_if else unguarded).add(key)
                walk(child, inside_if)

        walk(builder, False)
        return guarded, unguarded


class TestTheFlagIsCrossCheckedAgainstTheFrame:
    """CLAUDE.md's treatment for a fact that must live in two places: make one copy executable so
    drift fails loudly. The check runs before any bpy call, which is what lets a stub reach it."""

    def _run(self, scene_build, monkeypatch, tmp_path, *, flag, frame):
        (tmp_path / "frame.json").write_text(json.dumps(frame))
        monkeypatch.setattr(sys, "argv", [
            "blender", "--", "--body", flag, "--render-dir", str(tmp_path),
            "--out", str(tmp_path / "out.blend")])
        with pytest.raises(SystemExit) as exit_info:
            scene_build.main()
        return str(exit_info.value)

    def test_a_flag_disagreeing_with_the_frame_stops_the_render(self, scene_build, monkeypatch,
                                                                tmp_path):
        message = self._run(scene_build, monkeypatch, tmp_path,
                            flag="mars", frame={"body": "earth"})
        assert "written for 'earth'" in message

    def test_a_frame_with_no_body_is_refused_rather_than_assumed_to_be_earth(
            self, scene_build, monkeypatch, tmp_path):
        """The 203 frames on disk predate the field. Guessing would draw a plausible wrong planet,
        which is the same refusal as the flag having no default."""
        message = self._run(scene_build, monkeypatch, tmp_path,
                            flag="earth", frame={"width_px": 8192})
        assert "records no body" in message and "backfilling" in message

    def test_an_agreeing_frame_gets_past_the_check(self, scene_build, monkeypatch, tmp_path):
        """Anti-vacuity: both tests above would pass if the check rejected every frame. Agreement
        must reach the next statement, which is the first bpy call and dies on the stub — an
        exception the check itself can never raise, so it is unambiguous proof of passage."""
        (tmp_path / "frame.json").write_text(json.dumps({"body": "earth"}))
        monkeypatch.setattr(sys, "argv", [
            "blender", "--", "--body", "earth", "--render-dir", str(tmp_path),
            "--out", str(tmp_path / "out.blend")])
        with pytest.raises(AttributeError, match="bpy"):
            scene_build.main()


class TestFlatTintsAreThePalettes:
    """THE SNOW AND SEA-ICE WHITES ARE NO LONGER HERE, and their absence is the point rather than a
    gap in this suite. They were `RIG` constants asserted equal to `palette.SNOW_RGB` and
    `palette.ICE_RGB` — assertions that were green throughout while the rig painted every body in
    Earth's whites, because a body never entered either side of them. A colour that is the BODY's
    cannot be guarded by comparing one global to another, so it moved to a seam that carries the
    body: `tests/test_rig_whites_are_the_bodys.py`, which drives the registry, the prep's reducer
    and the rig's accessor end to end. Water stays because it genuinely is one tint on every body
    that has lakes, and no second instance has contradicted it.
    """

    def test_water_is_the_relational_tint(self, scene_build):
        """The 98C5C8 drift's cure: the hero flat water IS palette.WATER_RGB."""
        assert scene_build.RIG.water_rgba == (*palette.srgb8_to_linear(palette.WATER_RGB), 1.0)


class TestTheRigRecipeCarriesTheLook:
    """The recipe's other half: the body's ramps, which are not this module's to own.

    THE CAPITALS SCAN THAT USED TO LIVE HERE IS GONE, not weakened. It required every module-level
    ALL-CAPS name to appear in a hand-written recipe, which caught a forgotten constant and was
    blind by construction to a value spelled inline in a function body. `rig_recipe` now derives
    from `RIG`, so omission is unrepresentable rather than policed, and
    `TestTheRecipeIsDerivedRatherThanEnumerated` is what holds that.
    """

    def test_the_look_rides_along_rather_than_being_restated(self, scene_build):
        """A ramp is as much a render input as a sun is, and it is the body's rather than this
        module's — so it is recorded under its own key from `look_constants`, not copied."""
        recipe = scene_build.rig_recipe(palette.EARTH_LOOK)
        constants = scene_build.look_constants(palette.EARTH_LOOK)
        assert recipe["look"]["land_range"] == list(constants.land_range)
        assert len(recipe["look"]["land_stops"]) == len(constants.land_stops)

    def test_a_sealess_look_records_the_absence(self, scene_build):
        """`None` is the statement that this planet draws no sea, and the recipe has to carry it:
        a body that GAINED a sea would otherwise restage nothing."""
        sealess = palette.Look(land=palette.EARTH_LOOK.land, sea=None)
        recipe = scene_build.rig_recipe(sealess)
        assert recipe["look"]["sea_stops"] is None
        assert recipe["sea_texture"] is None


class TestSunAltitudeIsShared:
    def test_x_tilt_derives_from_sun_alt_deg(self, scene_build):
        """The 46-vs-45 split's cure: the X tilt is 90 − the shared altitude."""
        assert math.degrees(scene_build.RIG.sun_rotation[0]) == pytest.approx(
            90.0 - palette.SUN_ALT_DEG)

    def test_the_discs_width_derives_from_the_shared_one(self, scene_build):
        """THE ALTITUDE'S SIBLING, and it had drifted into two copies the same way.

        `cast_shadow` carried its own 12.0 with a comment naming the rig's, which is the 46-vs-45
        split's exact shape. It becomes load-bearing the moment the context law reads it: the ring
        is sized from this width, so a drift silently mis-sizes every block on the planet.
        """
        assert math.degrees(scene_build.RIG.sun_angle) == pytest.approx(
            palette.SUN_ANGULAR_DIAMETER_DEG)

    def test_the_sun_arrives_from_the_north_west(self, scene_build):
        """THE ASSERTION THIS REPLACES PINNED A COORDINATE AND THE RIG SHIPPED 90 DEGREES OFF.

        It read `SUN_ROTATION[2] == -45.0`, which is a statement about a euler and not about light:
        a Blender sun shines along its local -Z, so that euler put the light ARRIVING from 225, the
        south-west, against a cartographic convention of north-west that every other surface in the
        project follows. The old assertion stays true with the light coming from anywhere, so it
        could never have caught it, and nothing else looked.

        Ratified at 315 on real z8 tiles in the product globe rather than on images.
        """
        assert scene_build.arrival_azimuth_deg(scene_build.RIG.sun_rotation) == pytest.approx(315.0)

    def test_the_fill_arrives_from_the_south_east_its_comment_already_claimed(self, scene_build):
        """The comment said SE while the light came from NE. Both were wrong by the same 90."""
        assert scene_build.arrival_azimuth_deg(scene_build.RIG.fill_rotation) == pytest.approx(135.0)

    def test_rotating_the_pair_together_is_what_the_bearing_pin_catches(self, scene_build):
        """THE MUTATION THE OLD GUARD COULD NOT SEE, run rather than described.

        Rotating a sun by any amount leaves a coordinate assertion satisfiable by simply editing it
        to match, and that is how the defect survived a guard for two years. A bearing is derived,
        so a moved euler moves it and there is nothing to edit into agreement.
        """
        tilt = scene_build.RIG.sun_rotation[0]
        # The bearing runs OPPOSITE to the euler — arrival is (180 - z) — which is one more reason
        # not to read a rotation as a compass direction by eye.
        for turn_deg, expected in ((90.0, 225.0), (180.0, 135.0), (-90.0, 45.0)):
            turned = (tilt, 0.0, scene_build.RIG.sun_rotation[2] + math.radians(turn_deg))
            assert scene_build.arrival_azimuth_deg(turned) == pytest.approx(expected)

    def test_a_sun_below_the_horizon_has_no_bearing_to_report(self, scene_build):
        """The one case where the elevation term does not divide out, refused rather than silently
        returning the opposite bearing."""
        with pytest.raises(ValueError, match="below the horizon"):
            scene_build.arrival_azimuth_deg((math.radians(200.0), 0.0, 0.0))


class TestTheWholeRigCanBeTurnedToOneBearing:
    """The cap's raytraced arm needs the light at an arbitrary bearing, which Cycles cannot do per
    pixel — so it turns the rig rigidly, once per pass, and blends. These pin the conversion.

    THE SIGN CONVENTION IS MEASURED AND NOT REASONED. +90 on the euler's Z took the arrival bearing
    from 315 to 225, which is the arm's own record of getting it backwards first. A frame lit from
    the wrong side of the meridian is a plausible frame, so nothing downstream would have said so.
    """

    def test_zero_leaves_the_euler_untouched(self, scene_build):
        """THE DEFAULT PATH, and it is every hero and every one of 1,024 blocks. The arithmetic runs
        on all of them, so it has to be the identity rather than merely close to it."""
        for rotation in (scene_build.RIG.sun_rotation, scene_build.RIG.fill_rotation):
            assert scene_build.rotate_arrival(rotation, 0.0) == rotation

    def test_the_arrival_bearing_moves_by_exactly_what_was_asked(self, scene_build, subtests):
        """BOTH LIGHTS, because the cap turns the whole rig and a fill left behind would make a
        rendered pass a different intervention from the per-pixel one it has to reproduce."""
        for name in ("sun_rotation", "fill_rotation"):
            rotation = getattr(scene_build.RIG, name)
            before = scene_build.arrival_azimuth_deg(rotation)
            for delta in (7.5, 15.0, 90.0, 180.0, -30.0, 345.0):
                with subtests.test(light=name, delta=delta):
                    turned = scene_build.rotate_arrival(rotation, delta)
                    moved = (scene_build.arrival_azimuth_deg(turned) - before) % 360.0
                    assert moved == pytest.approx(delta % 360.0, abs=1e-6)

    def test_the_euler_turns_OPPOSITE_to_the_bearing(self, scene_build):
        """The measurement above stated as the thing a reader would get wrong. A Blender sun shines
        along its local -Z, so asking the light to arrive further clockwise turns the euler
        anticlockwise, and the two cancel to a frame that looks fine."""
        turned = scene_build.rotate_arrival(scene_build.RIG.sun_rotation, 90.0)
        assert turned[2] < scene_build.RIG.sun_rotation[2]
        assert scene_build.arrival_azimuth_deg(turned) == pytest.approx(45.0)

    def test_a_full_turn_lands_back_where_it_started(self, scene_build):
        """The wrap the arm's first self-check refused: a residual is itself an angle, so comparing
        it linearly rejects a correct 180-degree frame where `moved` reads +180 and the ask
        normalises to -180 — the same rotation, 360 apart on a straight number line."""
        for delta in (360.0, -360.0, 180.0, -180.0):
            turned = scene_build.rotate_arrival(scene_build.RIG.sun_rotation, delta)
            assert scene_build.arrival_azimuth_deg(turned) == pytest.approx(
                (315.0 + delta) % 360.0)

    def test_a_light_yawed_about_Y_has_no_bearing_this_can_report(self, scene_build):
        """`arrival_azimuth_deg`'s arithmetic drops the Y euler entirely, so a yawed light would be
        reported at a bearing it does not arrive from and `rotate_arrival`'s own self-check would
        confirm a rotation that never happened. Refused rather than silently answered."""
        with pytest.raises(ValueError, match="Y"):
            scene_build.arrival_azimuth_deg((math.radians(45.0), math.radians(30.0), 0.0))

    def test_the_rig_it_ships_with_is_not_yawed(self, scene_build):
        """The control on the refusal above: it is only admissible because no light in the rig is
        yawed, so a refusal that fired on the shipping path would be a broken guard rather than a
        strict one."""
        assert scene_build.RIG.sun_rotation[1] == 0.0
        assert scene_build.RIG.fill_rotation[1] == 0.0


class TestTheCameraCanPhotographOneTileOfThePlane:
    """A cap's disc is one plane rendered in quadrants: `CAP_PX` in a single frame is OOM-killed at
    the 16 G cap, and the neighbours are literally the same plane, so an off-tile ridge casts into
    frame for free with no context margin to buy.

    THE SPLIT IS DERIVED FROM `ortho_scale`, NEVER PASSED. The camera fraction the prep chose is
    already in the frame, so a driver that asked for tile 1,1 of a frame framed for the whole plane
    is a contradiction this can see — where a split arriving as its own argument would simply agree
    with whichever caller was wrong.
    """

    #: One quadrant of a square plane: `2.0 / CAP_QUADRANT_SPLIT`.
    QUADRANT = 1.0

    def test_the_four_quadrants_sit_where_the_judged_renders_put_them(self, scene_build, subtests):
        """The arm's own numbers, which are what both 8192 discs on disk were photographed at."""
        for (row, col), expected in (((0, 0), (-0.5, 0.5)), ((0, 1), (0.5, 0.5)),
                                     ((1, 0), (-0.5, -0.5)), ((1, 1), (0.5, -0.5))):
            with subtests.test(row=row, col=col):
                assert scene_build.tile_camera_location(
                    self.QUADRANT, 2.0, (row, col)) == pytest.approx(expected)

    def test_row_zero_is_the_TOP_of_the_plane(self, scene_build):
        """Stitching is blind to this: a flipped row order reassembles into a seamless disc showing
        the hemisphere upside down, which on a polar cap is a plausible picture of nowhere."""
        top = scene_build.tile_camera_location(self.QUADRANT, 2.0, (0, 0))[1]
        bottom = scene_build.tile_camera_location(self.QUADRANT, 2.0, (1, 0))[1]
        assert top > bottom

    def test_the_tiles_abut_exactly_with_no_overlap_and_no_gap(self, scene_build, subtests):
        """A SECOND SPLIT, because the quadrant case passes by construction for any law that
        happens to put four cameras at the corners. A one-pixel gap in a stitched disc reads as a
        render artefact rather than as a wrong argument, so nobody would look here."""
        for split in (2, 4, 8):
            with subtests.test(split=split):
                scale = 2.0 / split
                xs = [scene_build.tile_camera_location(scale, 2.0, (0, col))[0]
                      for col in range(split)]
                assert xs[0] == pytest.approx(-1.0 + scale / 2)
                assert xs[-1] == pytest.approx(1.0 - scale / 2)
                assert np.allclose(np.diff(xs), scale)

    def test_the_untiled_plane_is_its_own_single_tile(self, scene_build):
        """A camera seeing the whole plane is a 1x1 grid, and its only tile is the origin — the
        same place `build_camera` puts a camera nobody tiled."""
        assert scene_build.tile_camera_location(2.0, 2.0, (0, 0)) == pytest.approx((0.0, 0.0))

    def test_a_tile_outside_the_grid_the_ortho_scale_implies_is_refused(self, scene_build):
        """The frame says four tiles; asking for a fifth photographs empty space past the plane and
        stitches a disc with a quarter of it missing."""
        with pytest.raises(ValueError, match="2x2"):
            scene_build.tile_camera_location(self.QUADRANT, 2.0, (0, 2))

    def test_a_camera_fraction_that_does_not_divide_the_plane_is_refused(self, scene_build):
        """0.35 of a plane tiles it 2.857 times, so no set of tiles covers it. The frame is the
        thing that is wrong, and it is wrong before a single frame has been rendered."""
        with pytest.raises(ValueError, match="whole number"):
            scene_build.tile_camera_location(0.7, 2.0, (0, 0))

    def test_a_rectangular_plane_is_refused_rather_than_tiled_along_one_axis(self, scene_build):
        """The law here spaces rows by `ortho_scale`, which is the plane's own step only while it is
        square. A block's plane is not, and the generalisation has no second instance to verify it,
        so this refuses instead of guessing what a tiled block would mean."""
        with pytest.raises(ValueError, match="square"):
            scene_build.tile_camera_location(self.QUADRANT, 1.2, (0, 0))


class TestTheTileFlagIsParsedBeforeBlenderStarts:
    def test_it_arrives_as_a_row_and_a_column(self, scene_build):
        assert scene_build.tile_index("1,0") == (1, 0)

    def test_a_malformed_tile_is_an_argument_error_rather_than_a_render(self, scene_build,
                                                                       subtests):
        """A `--tile 1` that reached Blender would take the whole 41-minute ring down at the first
        frame, or worse, be read as something."""
        for text in ("1", "1,2,3", "a,b", "", "1;2"):
            with subtests.test(text=text), pytest.raises(argparse.ArgumentTypeError):
                scene_build.tile_index(text)

    def test_a_negative_index_is_refused_where_python_would_wrap_it(self, scene_build):
        """`-1` is a legal int and a legal list index, and it would silently photograph the last
        tile while the driver's recipe recorded the first."""
        with pytest.raises(argparse.ArgumentTypeError):
            scene_build.tile_index("-1,0")


class TestEveryBlockGetsAMicropolygonPerPixel:
    """THE DICING GUARD, and what it protects against does not raise, log or look broken.

    `MAX_SUBDIVISIONS` caps subdivision PER PATCH. The plane is added as a single quad, so without
    a base grid the cap is 2**12 = 4096 micropolygons along the whole plane edge whatever the render
    asks for. Past that Cycles dices coarser than the pixels and the displacement detail the
    raytrace exists for is quietly lost — measured at 26.10 DN mean where the cap bound by 8x.

    ASKED OF EVERY PLANNED BLOCK ON EVERY REGISTERED BODY, not of a chosen one: the context width
    varies per block, so the widest plane on the planet is the case that binds and it is not the
    one anybody would pick by hand. Pure arithmetic, so it needs no store, no GPU and no Blender.
    """

    def _frame(self, block, body):
        """The frame numbers this block would be rendered through, from the shipping seam."""
        window = block.plane_window
        return render_prep.scene_numbers(
            window.width, window.height, prep_block.ground_width_m(window, body),
            exaggeration=body.exaggeration, hero_long_edge=block.traced_edge_px,
            camera_fraction=block.traced_edge_px / block.plane_edge_px)

    def _widest_blocks(self, body):
        """One block per context width the law can produce on this body, the ceiling included."""
        widths = {block_plan.DENOISE_BAND_PX, block_plan.CONTEXT_CEILING_PX,
                  block_plan.CONTEXT_QUANTUM_PX * 7, block_plan.CONTEXT_CEILING_PX // 2}
        edge = block_plan.RENDER_BLOCK_PX
        return [block_plan.Block(col0=0, row0=block_plan.grid_px(body) // 2,
                                 size_px=edge, context_px=width) for width in sorted(widths)]

    @pytest.mark.parametrize("body", [bodies.EARTH, bodies.MARS], ids=lambda b: b.name)
    def test_the_base_grid_covers_every_context_width_on_every_body(self, scene_build, body):
        for block in self._widest_blocks(body):
            frame = self._frame(block, body)
            span = scene_build.plane_span_px(frame)
            patches = scene_build.base_patches(span)
            reachable = patches * 2 ** scene_build.RIG.max_subdivisions
            assert reachable >= span, (
                f"{body.name} at context {block.context_px}: {patches} patches reach "
                f"{reachable} micropolygons per edge against a plane spanning {span:.0f} px")

    def test_the_base_grid_cannot_discriminate_between_neighbouring_blocks(self, scene_build):
        """THE BASE GRID IS ONE VALUE FOR THE WHOLE PLANET, so it cannot explain a per-block seam.

        Written because it was blamed for one. A measured +0.545 DN join step was attributed to a
        block whose plane span moved 4,992 to 5,120 "and its fitted base grid changed with it".
        `base_patches` is `ceil(span / 2**MAX_SUBDIVISIONS)` and the cap is 4,096, so both spans
        give TWO patches: nothing changed, and the real cause is still unidentified. Measured over
        the real plan, every one of Earth's 1,024 blocks lands on the same patch count.

        THE ASSERTION IS DELIBERATELY THE WEAK ONE. It does not pin the value, which would go red
        on any harmless change to the block edge; it pins that the value is UNIFORM, which is the
        property the false attribution needed and did not have. If a future geometry makes the grid
        vary per block, this goes red and the grid becomes a candidate again -- which is the day
        someone should be allowed to blame it.
        """
        counts = set()
        for body in (bodies.EARTH, bodies.MARS):
            for block in self._widest_blocks(body):     # the law's whole context range, store-free
                counts.add(scene_build.base_patches(scene_build.plane_span_px(
                    self._frame(block, body))))
        assert len(counts) == 1, (
            f"the base grid now takes {sorted(counts)} across planned blocks, so it CAN differ "
            f"between neighbours and is a live candidate for a join step again"
        )

    def test_the_plane_span_is_the_planes_and_not_the_heightfields(self, scene_build):
        """The number this is computed FROM is where it would go wrong, and both paths disagree
        with the tempting answer in opposite directions: a block's plane is wider than what its
        camera sees, and a hero's grid is far wider than what it is rendered at."""
        block = block_plan.Block(col0=0, row0=block_plan.grid_px(bodies.EARTH) // 2,
                                 size_px=block_plan.RENDER_BLOCK_PX, context_px=1024)
        frame = self._frame(block, bodies.EARTH)
        assert scene_build.plane_span_px(frame) == pytest.approx(block.plane_edge_px, rel=1e-6)
        assert frame["res_x"] == block.traced_edge_px < block.plane_edge_px

    def test_removing_the_grid_is_what_this_catches(self, scene_build):
        """THE MUTATION, run rather than trusted. A guard whose subject is already satisfied by the
        single quad would pass with the base grid deleted and say nothing."""
        block = block_plan.Block(col0=0, row0=block_plan.grid_px(bodies.EARTH) // 2,
                                 size_px=block_plan.RENDER_BLOCK_PX,
                                 context_px=block_plan.CONTEXT_CEILING_PX)
        span = scene_build.plane_span_px(self._frame(block, bodies.EARTH))
        assert scene_build.base_patches(span) > 1, "the cap does not bind, so this proves nothing"
        assert 1 * 2 ** scene_build.RIG.max_subdivisions < span, (
            "a bare quad would reach far enough here, so removing the grid would not fail")

    def test_a_hero_frame_also_needs_more_than_one_patch(self, scene_build):
        """CARRIED BY THE SAME CODE AND IT IS NOT A BLOCK-ONLY FIX. A hero renders 7,680 px across
        a plane spanning the frame, against a single quad's 4,096 — so every hero on disk was diced
        at roughly half its own resolution, and the base grid moves them. That is a look change
        owed a judgement, recorded here so it cannot be discovered from the pixels later."""
        hero = render_prep.scene_numbers(16384, 12000, 4.0e6, exaggeration=bodies.EARTH.exaggeration)
        span = scene_build.plane_span_px(hero)
        assert span == pytest.approx(render_prep.HERO_LONG_EDGE / render_prep.FRAME_MARGIN, rel=1e-3)
        assert span > 2 ** scene_build.RIG.max_subdivisions
        assert scene_build.base_patches(span) == 2


class TestTheRecipeIsDerivedRatherThanEnumerated:
    """The recipe's failure mode is OMISSION, and today it is policed rather than prevented.

    `TestTheRigRecipeNamesEveryConstantHere` above scans the module for ALL-CAPS names and demands
    each in the recipe. That catches a forgotten constant, and it is blind by construction to a value
    written inline in a function body: an inline literal has no module-level name to find. Three
    instances of the same class have now shipped, and the last of them, `snow_image_node.interpolation
    = "Closest"`, reaches every rendered pixel and no freshness record.

    A constant held in a dataclass cannot go missing from a recipe derived from that dataclass, so
    these pin the derivation rather than a second enumeration of it.
    """

    def test_the_rig_constants_are_one_structure(self, scene_build):
        """A dataclass instance, so `dataclasses.asdict` can be the recipe."""
        assert dataclasses.is_dataclass(scene_build.RIG)
        assert dataclasses.fields(scene_build.RIG), "an empty structure satisfies every check below"

    def test_the_recipe_carries_the_structure_exactly(self, scene_build):
        """Derived, so a field added to `RIG` is in the recipe with nothing to remember.

        Equality rather than a subset: a subset would let the recipe carry a stale key for a field
        that no longer exists, which reads as a value being tracked when nothing produces it.
        """
        recipe = scene_build.rig_recipe(palette.EARTH_LOOK)
        assert recipe["rig"] == dataclasses.asdict(scene_build.RIG)

    def test_the_structure_holds_what_the_module_used_to_spell_as_capitals(self, scene_build):
        """The anti-vacuity arm, in the shape the capitals scan already uses.

        An empty or gutted `RIG` passes the two checks above trivially, and that is exactly what a
        half-finished conversion produces.
        """
        fields = {field.name for field in dataclasses.fields(scene_build.RIG)}
        assert {"samples", "sun_strength", "world_rgba", "clamp_indirect"} <= fields

    def test_the_view_transform_is_the_rigs_rather_than_a_literal(self, scene_build):
        """The tone map decides what every pixel's linear value comes out AS, and it reached no
        recipe at all: changing it moved every pixel and restaged nothing.

        The conversion that structured this module took the values already spelled as module-level
        capitals and left the ones written inline in `configure_render`. This is the largest of
        those, not the last of them.
        """
        assert scene_build.RIG.view_transform, "the rig states no view transform"
        recipe = scene_build.rig_recipe(palette.EARTH_LOOK)
        assert recipe["rig"]["view_transform"] == scene_build.RIG.view_transform

    def test_every_rig_field_is_actually_read_by_the_builder(self, scene_build, subtests):
        """The derivation's OTHER direction, and it had no guard until the inline sweep needed one.

        Every check above asks whether the recipe carries the structure. None asks whether the
        structure carries anything the builder applies, so a field that no `RIG.<name>` ever reads
        is recorded, restages every block when it changes, and reaches no pixel — a whole planet
        re-rendered for a value nothing consumes. A misspelled field name lands exactly there and
        the suite stays green, which is how 26 fields arriving at once could go wrong quietly.

        SOURCE TEXT, because the claim is about the builder's spelling and not about a runtime
        value: reading it any other way compares two vocabularies.
        """
        source = Path(scene_build.__file__).read_text(encoding="utf-8")
        fields = [field.name for field in dataclasses.fields(scene_build.RIG)]
        assert len(fields) > 20, "too few fields for this scan to be meaningful"
        for name in fields:
            with subtests.test(field=name):
                assert f"RIG.{name}" in source, (
                    f"`Rig.{name}` is in the recipe and no `RIG.{name}` appears in the builder, so "
                    f"changing it restages every block and moves no pixel")

    def test_no_rig_constant_is_left_at_module_level(self, scene_build):
        """The conversion is only worth doing if it is complete.

        A constant left outside the structure is a constant the derivation cannot see, which is the
        hole this replaces rather than a smaller version of it. The texture table is excluded
        because it is its own structure, checked below, and `SEA_IMAGE` because it names a row of
        that table rather than carrying a value.

        THE TEST FOR ADDING A NAME HERE IS NOT "IT IS NOT A COLOUR". `PLANE_WIDTH_UNITS` is
        excluded because it decides what a UNIT MEANS rather than what a pixel comes out as: every
        other number in the module is a fraction or a multiple of it, so moving it renders
        identically. A value that changes a rendered pixel while the rest of the frame arithmetic
        stands still belongs in `Rig`, however few pixels it moves.
        """
        allowed = {"TEXTURES", "SEA_IMAGE", "RIG", "PLANE_WIDTH_UNITS"}
        stragglers = {name for name in vars(scene_build)
                      if name.isupper() and not name.startswith("_") and name not in allowed}
        assert not stragglers, f"still module-level capitals: {sorted(stragglers)}"


class TestEveryTextureNodeIsDeclaredRatherThanSpelledInline:
    """The seven image nodes are one table, and the three conditional ones are not special.

    Snow, lake depth and sea ice each set a node name, an interpolation and an extension as literals
    inside `build_material`, so none of the three reaches `rig_recipe`. The other four come from
    the old `IMAGES`, which carried name and interpolation but NOT extension, so it was inline for
    all seven. Interpolation is a look decision exactly as a colour is: `Closest` gives a mask a hard
    edge and `Linear` feathers it, and extension decides whether one pole's row wraps into the other.
    """

    def test_every_texture_states_all_four_of_its_values(self, scene_build):
        for name, spec in scene_build.TEXTURES.items():
            assert spec.name == name, f"{name} disagrees with its own key"
            assert spec.filename, f"{name} names no raster"
            assert spec.interpolation, f"{name} states no interpolation"
            assert spec.extension, f"{name} states no extension"

    def test_the_conditional_textures_are_declared_like_every_other(self, scene_build):
        """Snow, lake depth and sea ice are ordinary rows that happen to be optional.

        Being optional is a property of the RASTER being present, never of the values being spelled
        somewhere the recipe cannot reach.
        """
        declared = {spec.filename for spec in scene_build.TEXTURES.values()}
        assert {render_seam.SNOWMASK, render_seam.LAKEDEPTH, render_seam.SEAICE} <= declared

    def test_the_texture_table_is_in_the_recipe(self, scene_build):
        """KEYED BY THE RASTER, NOT THE NODE, and the node's name is the one field left out. It is
        an identity rather than a look value, so recording it put a whole planet re-render behind a
        rename that moves no pixel. Everything else in the row rides in untouched."""
        recipe = scene_build.rig_recipe(palette.EARTH_LOOK)
        for spec in scene_build.TEXTURES.values():
            recorded = dataclasses.asdict(spec)
            del recorded["name"]
            assert recipe["textures"][spec.filename] == recorded

    def test_the_masks_keep_the_interpolations_they_ship_with(self, scene_build):
        """A conversion that quietly re-decided a look value would be a regression wearing a
        refactor's clothes. These are the values on disk today."""
        by_file = {spec.filename: spec for spec in scene_build.TEXTURES.values()}
        assert by_file[render_seam.SNOWMASK].interpolation == "Closest"
        assert by_file[render_seam.LAKEDEPTH].interpolation == "Linear"
        assert by_file[render_seam.SEAICE].interpolation == "Linear"
        assert by_file[render_seam.ROWSCALE].extension == "EXTEND"


class TestTheBuilderSpellsNoLookValueWhereTheRecipeCannotSeeIt:
    """`rig_recipe` records `Rig`, the texture table and the look. Anything else the builder decides
    is a value the recipe cannot see, so a change to it leaves every rendered block reading fresh.

    THE TEXTURE TABLE ABOVE WAS ONE INSTANCE OF THIS, NOT THE WHOLE OF IT, which is why this is its
    own class: the scan below rules on the camera, the subdivision, the lights, the node graph and
    the Cycles settings as well, and a reader asking why `engine = 'CYCLES'` is pinned would never
    look under a heading about image nodes.
    """

    #: The one attribute a bare literal may name, because its value cannot reach a pixel: a node's
    #: identity. A consistent rename renders byte-identically, and recording one would put a whole
    #: planet re-render behind a change that moves nothing.
    #:
    #: `colorspace_settings.name` is a different attribute that happens to share the word, and it is
    #: very much pixel-moving — it reaches EVERY raster the rig loads.
    IDENTITY_ATTRIBUTE = "name"

    #: AN ALLOWLIST, AND THE INVERSION IS THE WHOLE POINT. What stood here named the attributes that
    #: DO move pixels — `interpolation`, `extension`, `view_transform` — so an attribute nobody
    #: thought of was unguarded and SILENT. bpy tags nothing as look-bearing, so neither direction
    #: can be derived from it; what differs is which way an omission fails. Listing the movers meant
    #: a module holding `blend_type`, `displacement_method`, `space`, `levels` and two dozen others
    #: read as clean. Listing the one inert attribute means a new one is red until someone rules on
    #: it.
    #:
    #: The value filter went with it. Restricting to `str` constants made every number, bool and
    #: tuple invisible whatever the attribute was called, which hid the subdivision levels, the
    #: BSDF roughness and the fill sun's `use_shadow`.

    #: Inline literals that provably cannot reach a pixel. A sun lamp in Cycles is a DIRECTION, so
    #: where the object stands is not a light term; the builder's own comment says so.
    COSMETIC_INLINE: ClassVar[frozenset[str]] = frozenset({
        ".location = (4.076245, 1.005454, 5.903862)",
    })

    #: Inline literals that are not values anyone tunes: any other setting stops the builder being
    #: what its own name says it is, so there is nothing here for a recipe to track.
    #:
    #: `use_nodes` is a PRECONDITION rather than a setting — False leaves no node tree to configure,
    #: so the failure is the whole graph and not a drifted pixel. `data_type` is what a node factory
    #: BUILDS: `make_float_mix`'s docstring calls it "`make_mix`'s FLOAT twin", and the twinning is
    #: this attribute, so recording it would record the function's identity as though it were a
    #: look. Everything else that was deferred here now lives in `Rig`.
    STRUCTURAL_INLINE: ClassVar[frozenset[str]] = frozenset({
        ".use_nodes = True",
        ".data_type = 'FLOAT'",
        ".data_type = 'RGBA'",
    })

    #: Retired: the sweep landed. Kept empty rather than deleted so the set algebra below still
    #: reads as three named categories, and so a value added back here is a deliberate act.
    DEFERRED_INLINE: ClassVar[frozenset[str]] = frozenset()

    @staticmethod
    def _literal(value: ast.expr) -> str | None:
        """`value` rendered as source if it is a literal, else None.

        Tuples and lists count and are the reason this is not `isinstance(value, ast.Constant)`:
        the fill sun's position is three floats in a tuple, which is a look value in every sense
        and matches no scalar test.
        """
        if isinstance(value, ast.Constant):
            return ast.unparse(value)
        if isinstance(value, ast.Tuple | ast.List) and all(
                isinstance(item, ast.Constant) for item in value.elts):
            return ast.unparse(value)
        return None

    def _inline_values(self, source: str) -> list[str]:
        found = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Assign):
                continue
            literal = self._literal(node.value)
            if literal is None:
                continue
            for target in node.targets:
                if not isinstance(target, ast.Attribute):
                    continue
                colorspace = (target.attr == self.IDENTITY_ATTRIBUTE
                              and isinstance(target.value, ast.Attribute)
                              and target.value.attr == "colorspace_settings")
                if target.attr != self.IDENTITY_ATTRIBUTE or colorspace:
                    found.append(f".{target.attr} = {literal}")
        return found

    def test_every_inline_literal_in_the_builder_is_one_somebody_ruled_on(self, scene_build):
        """The guard that catches the NEXT inline literal rather than the ones already listed.

        Everything above pins values that exist today. This asks the structural question none of
        them can: does the builder hand a bare literal to an attribute nobody has ruled on? A
        conversion only holds if re-introducing the pattern goes red.

        This is what found `load_image`'s `colorspace_settings.name = "Non-Color"`, which reaches
        EVERY raster the rig loads and was on no list of the file's inline values.

        BOTH DIRECTIONS, BECAUSE A PIN LIST ROTS BOTH WAYS. An unruled site is a value that reaches
        a pixel with nothing watching it. A ruling with no site left is worse in a quieter way: the
        next reader takes this list for a description of the file, and it has stopped being one.

        AND THE SECOND DIRECTION IS THE SCANNER'S OWN CONTROL, which is why it is not merely tidy.
        A scanner that matched nothing would satisfy every "no unruled sites" assertion ever
        written; here it fails instead, naming every ruling whose site it could not find.
        """
        found = set(self._inline_values(Path(scene_build.__file__).read_text(encoding="utf-8")))
        ruled = self.COSMETIC_INLINE | self.STRUCTURAL_INLINE | self.DEFERRED_INLINE
        assert not found - ruled, (
            "inline literals nobody has ruled on, invisible to `rig_recipe`:\n  "
            + "\n  ".join(sorted(found - ruled))
            + "\nEither derive the value from `Rig` — which restages the whole planet — or add it "
              "to DEFERRED_INLINE with the value it ships today.")
        assert not ruled - found, (
            "rulings whose site is gone, so this list no longer describes the builder:\n  "
            + "\n  ".join(sorted(ruled - found)))

    def test_the_scan_finds_an_inline_value_when_there_is_one(self):
        """`scene_dump`'s own lesson, applied to this scanner: before trusting a passing comparison,
        run it once against a known-bad input and watch it fail.

        A scanner that silently matches nothing reports a clean module and a gutted regex the same
        way, and that is exactly how the first version of this project's dump oracle passed on a
        broken scene.
        """
        known_bad = (
            "def build():\n"
            "    node.interpolation = 'Closest'\n"
            "    node.extension = 'REPEAT'\n"
            "    img.colorspace_settings.name = 'Non-Color'\n"
            "    scene.view_settings.view_transform = 'Standard'\n"
            "    node.name = 'Displacement'\n"
        )
        found = self._inline_values(known_bad)
        assert len(found) == 4, f"expected the four pixel-moving ones, got {found}"
        assert not any("Displacement" in entry for entry in found), (
            "a node's own name is an identity, not a look value, and must not be flagged")

    def test_an_attribute_nobody_listed_is_flagged_rather_than_ignored(self):
        """The inversion, and the failure a hand-listed set of pixel-moving names cannot avoid.

        Every one of these decides pixels — `MIX` against `MULTIPLY` is a different composite,
        `DISPLACEMENT` against `BUMP` is real geometry against a shading trick, and a displacement
        read in `WORLD` space is a different height. None was on the list, so a module holding all
        three read as clean.
        """
        known_bad = (
            "def build():\n"
            "    mix.blend_type = 'MULTIPLY'\n"
            "    mat.displacement_method = 'BUMP'\n"
            "    disp.space = 'WORLD'\n"
        )
        found = self._inline_values(known_bad)
        assert len(found) == 3, f"expected all three unlisted attributes, got {found}"

    def test_the_scan_is_not_blind_to_a_literal_that_is_not_a_string(self):
        """The second blind spot, and it is independent of the list: a `str` filter on the value
        made every number, bool and tuple invisible whatever the attribute was called.

        The first three are in the shipping rig: subdivision levels are geometry, roughness is the
        whole surface response, and a fill sun that casts no shadow is a light term. The tuple is
        here because the scanner must SEE one — whether a particular tuple reaches a pixel is the
        pin list's ruling to make, and the rig's one tuple is exempt for a reason it states.
        """
        known_bad = (
            "def build():\n"
            "    mod.levels = 1\n"
            "    bsdf.inputs['Roughness'].default_value = 1.0\n"
            "    sun.use_shadow = False\n"
            "    ob.location = (4.076245, 1.005454, 5.903862)\n"
        )
        found = self._inline_values(known_bad)
        assert len(found) == 4, f"expected all four non-string literals, got {found}"


class TestNoNodeCarriesBlendersAutoName:
    """A node's identity is its `name`, and Blender's default for one is the type plus a counter.

    THE COUNTER IS THE DEFECT AND NOT THE UGLINESS. Two nodes handed the same name do not both
    keep it: bpy appends `.001` to the second silently, so a collision reintroduces the very
    suffix this removes and leaves the graph addressable only by creation order. That is why
    uniqueness is asserted rather than assumed.

    NONE OF THESE REACH A PIXEL, which `TestTheBuilderSpellsNoLookValueWhereTheRecipeCannotSeeIt`
    rules on by naming `name` its one inert attribute. What is guarded here is legibility, and
    legibility is load-bearing for anything that reaches into the BUILT graph by name — every
    arm probe does, since bpy hands out a fresh wrapper per access and `is` never matches.
    """

    #: Blender's own suffix for a name it had to disambiguate.
    AUTO_SUFFIX = re.compile(r"\.\d{3}$")

    def test_no_node_name_carries_the_auto_suffix(self, scene_build):
        """The texture half comes from the table at runtime and the rest from the builder's source,
        because that is where each is spelled: a table entry is a value, a mix name is a literal."""
        offenders = sorted(name for name in self._every_name(scene_build)
                           if self.AUTO_SUFFIX.search(name))
        assert not offenders, (
            f"nodes still carrying Blender's auto-name counter: {offenders}. The counter is "
            "assigned by creation order, so it renames itself when a node is added above it.")

    def test_no_two_nodes_share_a_name(self, scene_build):
        """A collision does not fail — bpy resolves it by appending the suffix to the loser, so
        the graph silently regains exactly what the test above forbids."""
        names = self._every_name(scene_build)
        duplicated = sorted({name for name in names if names.count(name) > 1})
        assert not duplicated, f"two nodes would be given the same name, bpy renames one: {duplicated}"

    def test_every_node_the_builder_creates_is_given_a_name(self, scene_build):
        """The arm that catches a node added without one, which Blender then auto-names. Counting
        rather than matching: a `nodes.new` and its `.name =` are two statements apart."""
        source = Path(scene_build.__file__).read_text()
        created, named = self._builder_node_counts(source)
        assert created == named, (
            f"build_material creates {created} nodes directly but names {named} of them; an "
            "unnamed node takes Blender's type name plus a counter")

    def test_the_scan_can_see_an_auto_name(self, scene_build):
        """The control. Every assertion above is satisfied by an extractor that found nothing, and
        the builder is exactly the shape — helpers, keywords, conditionals — that produces that."""
        found = self._names_in_source(
            "def make_mix(nt, name, label):\n"
            "    pass\n"
            "def build_material(ob, render_dir, displacement_scale, look, present):\n"
            "    lake = make_mix(nt, 'Mix.001', 'Lake')\n"
            "    disp.name = 'Displacement.002'\n")
        assert sorted(found) == ["Displacement.002", "Mix.001"], (
            f"the scan missed one of the two shapes it has to see: {sorted(found)}")

    def _every_name(self, scene_build) -> list[str]:
        """Both halves as one list, so uniqueness is asked across the whole graph rather than
        within either half. A texture colliding with a mix is as silent as two mixes colliding."""
        return (list(scene_build.TEXTURES)
                + self._names_in_source(Path(scene_build.__file__).read_text()))

    @staticmethod
    def _names_in_source(source: str) -> list[str]:
        """Every name `build_material` spells, from `.name = "..."` and from the make_* helpers.

        THE HELPER SET IS DERIVED RATHER THAN LISTED: a module-level function whose first three
        parameters are `(nt, name, label)` is a node constructor, so one written later is scanned
        with nothing here to remember. A listed set would go short exactly when the rig grows.
        """
        tree = ast.parse(source)
        constructors = {node.name for node in tree.body
                        if isinstance(node, ast.FunctionDef)
                        and [arg.arg for arg in node.args.args[:3]] == ["nt", "name", "label"]}
        builder = next(node for node in ast.walk(tree)
                       if isinstance(node, ast.FunctionDef) and node.name == "build_material")
        names: list[str] = []
        for node in ast.walk(builder):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Attribute)
                    and node.targets[0].attr == "name"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                names.append(node.value.value)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in constructors and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                names.append(node.args[1].value)
        return names

    @staticmethod
    def _builder_node_counts(source: str) -> tuple[int, int]:
        """`(nodes created directly, names assigned)` inside `build_material`.

        Direct only: a helper names the node it makes, so counting those would compare a helper's
        internals against the builder's.
        """
        builder = next(node for node in ast.walk(ast.parse(source))
                       if isinstance(node, ast.FunctionDef) and node.name == "build_material")
        created = sum(1 for node in ast.walk(builder)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr == "new" and isinstance(node.func.value, ast.Attribute)
                      and node.func.value.attr == "nodes")
        named = sum(1 for node in ast.walk(builder)
                    if isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Attribute)
                    and node.targets[0].attr == "name")
        return created, named


class TestRenamingANodeDoesNotRestageThePlanet:
    """`rig_recipe` records what can move a rendered pixel, and a node's name provably cannot.

    THE RECIPE USED TO OVER-TRACK BY ITS OWN SIBLING'S REASONING.
    `TestTheBuilderSpellsNoLookValueWhereTheRecipeCannotSeeIt` names `name` its ONE inert
    attribute, on the grounds that a consistent rename renders byte-identically; the table was
    nonetheless recorded whole, so the identity rode in beside the look values and any rename
    cleared all 1,024 markers plus both cap discs for pixels that did not move.

    OVER- AND UNDER-TRACKING ARE BOTH SILENT, so the exclusion is one NAMED FIELD rather than a
    chosen subset: a field added to `TextureSpec` later is recorded with nothing here to remember,
    which is the same reason the table is derived rather than enumerated. The control below is
    what keeps the exclusion honest, since an exclusion that grew would look exactly like this.
    """

    def test_renaming_every_node_leaves_the_recipe_byte_identical(self, scene_build, monkeypatch):
        """A rename touches the table's keys, its specs and `SEA_IMAGE` together, because the key
        IS the node name. None of that may reach the recipe."""
        before = json.dumps(scene_build.rig_recipe(palette.EARTH_LOOK), sort_keys=True)
        monkeypatch.setattr(scene_build, "SEA_IMAGE", f"Renamed {scene_build.SEA_IMAGE}")
        monkeypatch.setattr(scene_build, "TEXTURES", {
            f"Renamed {spec.name}": dataclasses.replace(spec, name=f"Renamed {spec.name}")
            for spec in scene_build.TEXTURES.values()})
        after = json.dumps(scene_build.rig_recipe(palette.EARTH_LOOK), sort_keys=True)
        assert before == after, "a node rename still moves the recipe, so it restages the planet"

    def test_a_look_bearing_field_in_the_same_row_still_moves_it(self, scene_build, monkeypatch):
        """THE CONTROL, and it decides that the exclusion is a field rather than the whole row.
        `interpolation` sits in the same dataclass and reaches every coastline: an oceanmask read
        Linear instead of Closest feathers the lot. If this passes green the recipe has stopped
        watching the table at all, which is indistinguishable from the fix above."""
        before = json.dumps(scene_build.rig_recipe(palette.EARTH_LOOK), sort_keys=True)
        monkeypatch.setattr(scene_build, "TEXTURES", {
            name: dataclasses.replace(spec, interpolation="Cubic")
            for name, spec in scene_build.TEXTURES.items()})
        after = json.dumps(scene_build.rig_recipe(palette.EARTH_LOOK), sort_keys=True)
        assert before != after, "an interpolation change no longer reaches the recipe"

    def test_no_two_textures_read_the_same_raster(self, scene_build):
        """The recipe is keyed on the filename now, so a duplicate would drop a whole row and take
        its interpolation and extension out of the recipe with it, silently. `texture_for` already
        assumed this by returning the first match; here it is asserted."""
        filenames = [spec.filename for spec in scene_build.TEXTURES.values()]
        duplicated = sorted({name for name in filenames if filenames.count(name) > 1})
        assert not duplicated, f"two texture rows read one raster, so the recipe drops one: {duplicated}"

    def test_the_sea_texture_key_names_a_raster_rather_than_a_node(self, scene_build):
        """The second place a node name used to reach the recipe. It records WHICH texture the sea
        branch reads, and the raster answers that as well as the node did without moving on a
        rename."""
        recipe = scene_build.rig_recipe(palette.EARTH_LOOK)
        assert recipe["sea_texture"] == render_seam.OCEANMASK
        assert scene_build.rig_recipe(palette.MARS_LOOK)["sea_texture"] is None
