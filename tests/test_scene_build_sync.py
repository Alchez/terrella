"""scene_build's look constants are DERIVED from palette — this guards the derivation.

scene_build runs only under Blender's Python (`import bpy`), so it was historically
ast-parsed and never imported, and its constants were COPIES — which is how three
divergences accumulated undetected (sea ramp, water tint, sun altitude; the ART.md audit).
Since the sea-sync the constants are imports from
`pipeline.look.palette`; these tests stub bpy and import the module in the venv, so
any re-inlined literal fails HERE instead of on a hero render.
"""

import importlib
import json
import math
import sys
import types

import pytest

from pipeline.look import palette
from pipeline.render import render_seam


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


class TestTheRigsFilenamesHaveOneOwner:
    """`render_seam` owns the six spellings and the rig reads them from there.

    The drift this closes is not hypothetical: the prep that WRITES these files and the rig that
    LOADS them are different modules in different interpreters, and every one of the six was a
    literal in both. A rename touching one side is a scene that loads nothing, reported as a
    missing image rather than as the rename it is.
    """

    def test_the_rig_loads_only_images_the_seam_declares(self, scene_build):
        loaded = {filename for filename, _ in scene_build.IMAGES.values()}
        assert loaded <= render_seam.KNOWN_IMAGES
        assert render_seam.HEIGHTFIELD in loaded, "the elevation is always loaded"

    def test_the_sea_image_is_the_oceanmask_by_name_and_not_by_position(self, scene_build):
        """`SEA_IMAGE` is a node name and the table maps it to a filename; a table reordered so
        that `.001` became a different mask would drop the wrong image for a sea-less body."""
        filename, _ = scene_build.IMAGES[scene_build.SEA_IMAGE]
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
    def test_water_is_the_relational_tint(self, scene_build):
        """The 98C5C8 drift's cure: the hero flat water IS palette.WATER_RGB."""
        assert scene_build.WATER_RGBA == (*palette.srgb8_to_linear(palette.WATER_RGB), 1.0)

    def test_snow_is_the_shared_white(self, scene_build):
        assert scene_build.SNOW_RGBA == (*palette.srgb8_to_linear(palette.SNOW_RGB), 1.0)

    def test_ice_is_the_palettes_cool_white(self, scene_build):
        """A single albedo where the composite keys a (sunlit, shadowed) pair: Cycles lights the
        sheet itself, so the pair's shadowed half was the fake light key's job."""
        assert scene_build.ICE_RGBA == (*palette.srgb8_to_linear(palette.ICE_RGB), 1.0)


class TestTheRigRecipeNamesEveryConstantHere:
    """The freshness recipe for a raytraced planet is `rig_recipe`, and the failure it has to be
    proof against is OMISSION rather than error.

    A constant added here and forgotten there reaches every pixel and moves no mtime, so a planet
    rendered with the old value keeps reading as current forever — and the render is the most
    expensive output the project has. Nothing about a missing key is visible from the recipe's own
    side, which is why the check runs from the MODULE's side: every all-caps name this file defines
    must appear, so forgetting is red here rather than silent for a night.
    """

    def _capitals(self, scene_build):
        return {name for name in vars(scene_build)
                if name.isupper() and not name.startswith("_")}

    def test_every_module_constant_is_in_the_recipe(self, scene_build):
        recipe = scene_build.rig_recipe(palette.EARTH_LOOK)
        assert self._capitals(scene_build) <= set(recipe)

    def test_the_scan_finds_the_constants_it_claims_to(self, scene_build):
        """The anti-vacuity arm. An empty capital set would satisfy the subset above trivially, and
        that is exactly what a rename to lower case or a moved constant block would produce."""
        found = self._capitals(scene_build)
        assert {"SAMPLES", "SUN_STRENGTH", "WORLD_RGBA", "IMAGES"} <= found

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
        assert scene_build.SEA_IMAGE not in recipe["IMAGES"]


class TestSunAltitudeIsShared:
    def test_x_tilt_derives_from_sun_alt_deg(self, scene_build):
        """The 46-vs-45 split's cure: the X tilt is 90 − the shared altitude."""
        assert math.degrees(scene_build.SUN_ROTATION[0]) == pytest.approx(
            90.0 - palette.SUN_ALT_DEG)

    def test_azimuth_unchanged(self, scene_build):
        assert math.degrees(scene_build.SUN_ROTATION[2]) == pytest.approx(-45.0)
