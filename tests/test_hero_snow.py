"""The hero lane's snow: the tiles' producers and fold, on a country's own grid."""

import numpy as np
import pytest
from scipy import ndimage

from pipeline import bodies, layers, render_files
from pipeline.frame import country_config
from pipeline.look import palette, salt, snow
from pipeline.render import render_seam, snow_mask

ROWS, COLUMNS = 48, 36
GROUND_M = 400.0


def packed_persistence() -> np.ndarray:
    """Packed NSIDC values across the whole ramp, with one fill cell that must read as no snow."""
    packed = (np.random.default_rng(11).random((ROWS, COLUMNS)) * 10000.0).astype(np.float32)
    packed[0, 0] = snow.SP_FILL
    return packed


def glacier_outlines() -> np.ndarray:
    outlines = np.zeros((ROWS, COLUMNS), np.uint8)
    outlines[30:34, 5:9] = 1
    return outlines


def latitude_field() -> np.ndarray:
    """Falls along both axes, as a conic grid's does, so no row has one latitude."""
    rows, columns = np.indices((ROWS, COLUMNS))
    return 70.0 - 28.0 * rows / (ROWS - 1) - 6.0 * columns / (COLUMNS - 1)


def the_law(packed: np.ndarray, latitude: np.ndarray, glaciers: np.ndarray) -> np.ndarray:
    """The tiles' snow law re-derived from its constants rather than from the code that runs it:
    persistence smoothstepped above a threshold ramped by |latitude|, softened at a fraction of the
    source cell, then maxed with the glacier outlines."""
    persistence = np.where(packed == snow.SP_FILL, 0.0, packed.astype(float) * snow.SP_SCALE)
    ramp = np.clip((np.abs(latitude) - snow.RAMP_LAT_LO) / (snow.RAMP_LAT_HI - snow.RAMP_LAT_LO), 0.0, 1.0)
    low = snow.RAMP_LOW_MIN + ramp * (snow.RAMP_LOW_MAX - snow.RAMP_LOW_MIN)
    fraction = np.clip((persistence - low) / snow.RAMP_BAND, 0.0, 1.0)
    alpha = fraction * fraction * (3.0 - 2.0 * fraction)
    sigma = snow.SOFTEN_FRACTION * snow.SOURCE_CELL_M / GROUND_M
    return np.maximum(ndimage.gaussian_filter(alpha, sigma=sigma, mode="nearest"), glaciers.astype(float))


def salt_ground() -> np.ndarray:
    """One square of salt at full strength and one where the white is salt's."""
    full, gate = np.zeros((ROWS, COLUMNS)), np.zeros((ROWS, COLUMNS), bool)
    full[4:8, 4:8] = 1.0
    gate[20:26, 20:26] = True
    return salt.pack(full, gate)


def white(latitude: np.ndarray, salted: "np.ndarray | None" = None):
    land = np.ones((ROWS, COLUMNS), bool)
    sources = {layers.PERENNIAL_ICE.name: packed_persistence(), layers.GLACIERS.name: glacier_outlines(),
               layers.SALT_FLATS.name: salted}
    return snow_mask.hero_white(
        bodies.EARTH, sources, ocean=~land, watercode=np.zeros((ROWS, COLUMNS), np.uint8),
        latitude=latitude, ground_metres_per_px=GROUND_M)


class TestTheHeroFoldsTheTilesLaw:
    def test_the_white_is_the_tile_law_read_at_each_pixels_own_latitude(self):
        alpha, paint, salt_alpha, _salt_paint = white(latitude_field())
        expected = the_law(packed_persistence(), latitude_field(), glacier_outlines())
        np.testing.assert_allclose(alpha, expected, rtol=0.0, atol=1e-12)
        assert paint == (palette.SNOW_RGB, palette.SNOW_SHADOW_RGB)
        assert salt_alpha is None

    def test_the_fixture_needs_each_pixels_latitude_and_not_its_rows(self):
        """The control on the fixture: were every pixel read at its row's mean latitude, the law
        would come out different, so the test above cannot pass on a per-row reading."""
        per_row = np.repeat(latitude_field().mean(axis=1, keepdims=True), COLUMNS, axis=1)
        assert not np.allclose(the_law(packed_persistence(), per_row, glacier_outlines()),
                               the_law(packed_persistence(), latitude_field(), glacier_outlines()))

    def test_a_grid_reaching_the_antarctic_rule_is_refused(self):
        """South of it the white is the forced Antarctic patch less SCAR ADD's exposed rock, and
        this stage burns no rock, so it would paint the outcrop white."""
        latitude = latitude_field() - 125.0
        with pytest.raises(ValueError, match="Antarctic"):
            white(latitude)


class TestTheHeroPaintsItsSaltFlats:
    def test_the_salt_takes_the_white_it_claims_and_returns_its_own_alpha(self):
        snow_alpha, _paint, salt_alpha, salt_paint = white(latitude_field(), salt_ground())
        law = the_law(packed_persistence(), latitude_field(), glacier_outlines())
        full, gate = salt.unpack(salt_ground())
        assert salt_alpha is not None
        np.testing.assert_allclose(snow_alpha, law * (1.0 - np.maximum(full, gate)), atol=1e-12)
        np.testing.assert_allclose(salt_alpha, np.maximum(full, law * gate), atol=1e-12)
        assert salt_paint == (palette.SALT_RGB, palette.SALT_SHADOW_RGB)

    def test_the_fixture_puts_white_under_the_gate(self):
        """The control: with no white under the gate the salt there would be zero either way."""
        law = the_law(packed_persistence(), latitude_field(), glacier_outlines())
        assert law[20:26, 20:26].max() > 0.5

    def test_the_stage_writes_and_declares_both_masks(self, tmp_path):
        snow_alpha, paint, salt_alpha, salt_paint = white(latitude_field(), salt_ground())
        snow_mask.write_masks(tmp_path, snow_alpha, paint, salt_alpha, salt_paint)
        assert set(render_seam.stage_images(tmp_path, render_seam.SNOW) or []) == {
            render_files.SNOWMASK, render_files.SALTMASK}
        assert render_seam.paint_for(tmp_path, render_files.SALTMASK) == (palette.SALT_RGB,
                                                                          palette.SALT_SHADOW_RGB)

    def test_no_salt_mask_where_the_grid_has_no_salt(self, tmp_path):
        snow_alpha, paint, salt_alpha, salt_paint = white(latitude_field(), np.zeros((ROWS, COLUMNS), np.uint8))
        snow_mask.write_masks(tmp_path, snow_alpha, paint, salt_alpha, salt_paint)
        assert render_seam.stage_images(tmp_path, render_seam.SNOW) == [render_files.SNOWMASK]
        assert not (tmp_path / render_files.SALTMASK).exists()


class TestResumingOnTheRecipe:
    def test_a_mask_with_no_recipe_beside_it_is_not_current(self, tmp_path):
        """The shape of every hero folder made before the switch: a mask from another law, which
        resuming on the file's existence alone would keep."""
        (tmp_path / render_files.SNOWMASK).write_bytes(b"a mask from another law")
        assert not snow_mask.is_current(tmp_path, bodies.EARTH)

    def test_a_recorded_recipe_is_current_until_a_constant_moves(self, tmp_path, monkeypatch):
        render_seam.declare(tmp_path, render_seam.SNOW, [])
        snow_mask.record(tmp_path, bodies.EARTH)
        assert snow_mask.is_current(tmp_path, bodies.EARTH)
        monkeypatch.setattr(snow, "RAMP_BAND", snow.RAMP_BAND + 0.01)
        assert not snow_mask.is_current(tmp_path, bodies.EARTH)


def test_the_snow_stage_is_told_which_body_it_paints():
    """The producers are keyed by body, and a stage that assumed Earth would paint any body in
    Earth's snow."""
    config = {"defaults": {"pad_pct": 5.0, "hero_long_edge": 7680, "warp_long_edge": 8192,
                           "fusion": "auto", "resolution_floor_m": 60.0},
              "scope": {"exclude": [], "include": []}, "countries": {}}
    row = {"admin": "Nepal", "sov": "Nepal", "bbox": (80.0, 26.0, 88.0, 30.0), "idx": 0}
    resolved = country_config.resolve("nepal", row, config)
    assert resolved is not None
    stage = next(command for command in country_config.stage_commands(resolved)
                 if "pipeline.render.snow_mask" in command)
    assert f"--body {bodies.EARTH.name}" in stage
