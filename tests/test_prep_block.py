"""The block prep: what it asks the registries for, and the two constants that are inert on Earth.

The port's whole risk is that it ran only ever on Earth, where the map-unit-to-ground ratio is
exactly 1.0 and every body-shaped term can be dropped without a symptom. So the guards here are
paired: Earth's answer, and the same answer on a body where the term is not the identity.
"""

import json
import math

import numpy as np
import pytest

from pipeline import block_plan, bodies, layers
from pipeline.block_plan import Block
from pipeline.look import layer_producers, snow
from pipeline.render import prep_block


def plane_window(col, row, size, context):
    """The window a block is cut from, built through its one owner.

    `prep_block` used to spell this arithmetic itself, beside an identical copy on `Block`, and
    changing either moved no test. The helper is here rather than there so the test still says
    which numbers it means without being a second implementation of them.
    """
    return Block(col0=col, row0=row, size_px=size, context_px=context).plane_window


ROWS, COLS = 8, 16


def _window(body, raw):
    """One southern window, far enough south that the Antarctic patch is live rather than zero."""
    top, bottom = -11_000_000.0, -12_000_000.0
    return raw, layer_producers.LayerWindow(
        raw=None, watercode=np.zeros((ROWS, COLS), dtype=np.uint8),
        land=np.ones((ROWS, COLS), dtype=bool),
        latitude=snow.latitude_per_row(top, bottom, ROWS), top=top, bottom=bottom)


class TestTheGroundWidthIsTheBodysAndNotTheProjectionsphere:
    """`ground_metres_per_mercator_unit` is EXACTLY 1.0 on Earth, so an Earth-only test passes
    whether the term is read or dropped. Mars is 1.878, and dropping it undersizes the frame —
    which reaches `displacement_scale` and renders a plausible planet at the wrong relief."""

    def _equator_window(self, body):
        row = block_plan.grid_px(body) // 2 - block_plan.RENDER_BLOCK_PX // 2
        return plane_window(0, row, block_plan.RENDER_BLOCK_PX, 0)

    def _predicted(self, window, body, *, ratio):
        """The closed form, with the body ratio passed in so the dropped-term arm is expressible."""
        mid = block_plan.row_latitude_deg(window.row_off + window.height / 2, body)
        return (window.width * body.map_units_per_pixel * math.cos(math.radians(mid)) * ratio)

    @pytest.mark.parametrize("body", [bodies.EARTH, bodies.MARS])
    def test_the_width_matches_the_closed_form_including_the_body_ratio(self, body):
        """Measured against a TARGET rather than against the other body: comparing Earth to Mars
        drags both bodies' latitudes into one number and answers 'the knob is connected' when the
        question is 'is this value right'."""
        window = self._equator_window(body)
        ratio = bodies.ground_metres_per_mercator_unit(body)
        assert prep_block.ground_width_m(window, body) == pytest.approx(
            self._predicted(window, body, ratio=ratio), rel=1e-12)

    def test_dropping_the_ratio_is_a_difference_the_check_above_can_see_on_mars(self):
        """The positive control. The arm that drops the term must MOVE the number, or the test
        above passes on a body where the term was never read."""
        window = self._equator_window(bodies.MARS)
        dropped = self._predicted(window, bodies.MARS, ratio=1.0)
        assert prep_block.ground_width_m(window, bodies.MARS) != pytest.approx(dropped, rel=1e-9)

    def test_dropping_the_ratio_is_invisible_on_earth(self):
        """And the negative control, which is why the arc kept shipping this defect: Earth's ratio
        IS 1.0, so the dropped arm and the correct arm are the same number to the last bit."""
        window = self._equator_window(bodies.EARTH)
        assert prep_block.ground_width_m(window, bodies.EARTH) == self._predicted(
            window, bodies.EARTH, ratio=1.0)

    def test_earth_alone_cannot_tell_the_term_from_its_absence(self):
        """Stated as an executable claim rather than a comment, because it is the reason the test
        above exists at all: on Earth the ratio IS the identity."""
        assert bodies.ground_metres_per_mercator_unit(bodies.EARTH) == 1.0
        assert bodies.ground_metres_per_mercator_unit(bodies.MARS) != 1.0

    def test_the_width_shrinks_with_latitude(self):
        """Mercator metres are not ground metres away from the equator, which is the other half of
        the correction and the half that is live on every body."""
        equator = prep_block.ground_width_m(self._equator_window(bodies.EARTH), bodies.EARTH)
        polar = prep_block.ground_width_m(
            plane_window(0, 0, block_plan.RENDER_BLOCK_PX, 0), bodies.EARTH)
        assert polar < equator


class TestTheContextIsCutAndNeverDelivered:
    def test_the_window_grows_by_the_context_on_every_side(self):
        window = plane_window(4096, 2048, 2048, 256)
        assert (window.col_off, window.row_off) == (4096 - 256, 2048 - 256)
        assert (window.width, window.height) == (2048 + 512, 2048 + 512)

    def test_a_zero_context_is_expressible_but_never_defaulted(self):
        """The CLI requires `--context`, because a silently-zero one loses every shadow crossing
        the boundary, on both sides, with no edge to notice. Expressible because the window
        arithmetic is a pure function; what refuses it is the law, which floors at the band."""
        window = plane_window(0, 0, 2048, 0)
        assert (window.width, window.height) == (2048, 2048)

    def test_what_the_rig_is_told_is_the_traced_edge_and_not_the_plane(self, tmp_path):
        """THE SEAM WHERE THE THREE WIDTHS MEET, and the one place a swap is expressible.

        `write_frame` hands the rig a heightfield the size of the PLANE and a resolution the size
        of the TRACED rectangle, with `camera_fraction` the ratio between them. Passing the plane
        as the resolution renders the context — the defect the whole unit exists to remove — and
        every downstream shape check would still pass, because the crop is taken by offset.
        """
        block = Block(col0=0, row0=block_plan.grid_px(bodies.EARTH) // 2,
                      size_px=block_plan.RENDER_BLOCK_PX, context_px=1024)
        window = block.plane_window
        numbers = prep_block.render_prep.scene_numbers(
            window.width, window.height, prep_block.ground_width_m(window, bodies.EARTH),
            exaggeration=bodies.EARTH.exaggeration, hero_long_edge=block.traced_edge_px,
            camera_fraction=block.traced_edge_px / block.plane_edge_px)
        assert numbers["res_x"] == numbers["res_y"] == block.traced_edge_px
        assert numbers["res_x"] < block.plane_edge_px, "the camera would be photographing context"
        # The camera spans the traced rectangle exactly, in the plane's own units.
        assert numbers["ortho_scale"] == pytest.approx(
            2.0 * block.traced_edge_px / block.plane_edge_px)


class TestTheBlockStageAsksForItsOwnLayersAndNotTheComposites:
    """The raytrace column reaching behaviour, which is the only thing that makes it more than a
    field. Since the rig grew an ice input the block gathers everything the composite does, and
    the agreement is pinned here BEHAVIOURALLY: flipping the column back off starves the rig's
    ice arm and fails this, not only the literal pins in test_bodies."""

    def _gathered(self, vocabulary):
        packed = np.full((ROWS, COLS), 9_000.0, dtype="float32")
        raw, window = _window(bodies.EARTH, packed)
        layer_raw: dict[str, np.ndarray | None] = {
            layer.name: raw for layer in layers.WARPED_LAYERS}
        contributions, _ = layer_producers.gather(bodies.EARTH, layer_raw, window, vocabulary)
        return set(contributions)

    def test_the_block_gathers_sea_ice_like_the_composite(self):
        assert layers.SEA_ICE.name in self._gathered(layers.COMPOSITE_LAYERS)
        assert layers.SEA_ICE.name in self._gathered(layers.BLOCK_LAYERS)

    def test_both_still_gather_the_white_the_rig_can_paint(self):
        """The companion that can fail: if the block vocabulary gathered nothing at all the test
        above would pass for the wrong reason."""
        for name in (layers.PERENNIAL_ICE.name, layers.GLACIERS.name):
            assert name in self._gathered(layers.BLOCK_LAYERS)

    def test_the_vocabulary_is_an_actual_filter(self):
        """The stage vocabularies agree on Earth today, so only a deliberately narrow one can
        prove the gather honours its caller's vocabulary at all — a gather that ignored it would
        hand every caller every layer the body declares, and no stage set could show it."""
        narrowed = self._gathered(frozenset({layers.PERENNIAL_ICE.name}))
        assert layers.PERENNIAL_ICE.name in narrowed
        assert layers.GLACIERS.name not in narrowed
        assert layers.SEA_ICE.name not in narrowed


class TestSeaIceIsGatedToTheOcean:
    """The coastal-collapse guard: the same alpha damps displacement in the rig, so ice that
    leaked onto shoreline land would drag it toward sea level at full exaggeration."""

    def test_ice_that_reaches_land_is_refused(self):
        contribution = np.full((ROWS, COLS), 0.85)
        ocean = np.zeros((ROWS, COLS), dtype=bool)
        assert prep_block.gated_sea_ice(contribution, ocean) is None

    def test_ice_on_the_ocean_survives_the_gate_exactly(self):
        contribution = np.full((ROWS, COLS), 0.85)
        ocean = np.zeros((ROWS, COLS), dtype=bool)
        ocean[:, : COLS // 2] = True
        gated = prep_block.gated_sea_ice(contribution, ocean)
        assert gated is not None
        assert gated[:, : COLS // 2].min() == 0.85
        assert not gated[:, COLS // 2:].any()

    def test_no_contribution_and_no_surviving_pixel_both_read_as_nothing_to_write(self):
        """Both land in the skip-and-declare-empty path: `build` writes no image, and the block's
        declaration says so rather than leaving an absence to interpret."""
        ocean = np.ones((ROWS, COLS), dtype=bool)
        assert prep_block.gated_sea_ice(None, ocean) is None
        assert prep_block.gated_sea_ice(np.zeros((ROWS, COLS)), ocean) is None


class TestTheWhiteUnionIsFoldedByItsOwner:
    def test_sea_ice_is_not_in_the_union_even_when_it_was_gathered(self):
        """`shade.composite` gates ice on the ocean selector where the union paints land, so an ice
        contribution folded in here would paint pack ice onto the shore it borders."""
        assert layers.SEA_ICE not in layer_producers.WHITE_UNION
        contributions = {layers.SEA_ICE.name: np.ones((ROWS, COLS))}
        alpha, _ = layer_producers.fold_white(contributions, (ROWS, COLS))
        assert not alpha.any()

    def test_the_base_is_float64_so_no_contribution_is_narrowed(self):
        alpha, _ = layer_producers.fold_white({}, (ROWS, COLS))
        assert alpha.dtype == np.float64

    def test_a_caller_that_does_not_paint_gets_no_paint(self):
        contributions = {layers.PERENNIAL_ICE.name: np.ones((ROWS, COLS))}
        alpha, carried = layer_producers.fold_white(contributions, (ROWS, COLS))
        assert alpha.all() and carried is None

    def test_the_merge_hook_sees_the_alpha_from_before_its_own_layer_folds(self):
        """What the hook exists for: the compositor's paint merge asks which layer WON a pixel, so
        it must compare against the running maximum rather than the finished one."""
        seen = []
        contributions = {layers.PERENNIAL_ICE.name: np.full((ROWS, COLS), 0.5),
                         layers.GLACIERS.name: np.ones((ROWS, COLS))}
        layer_producers.fold_white(
            contributions, (ROWS, COLS),
            merge=lambda carried, alpha, name, contribution: seen.append(
                (name, float(alpha.max()))))
        assert seen == [(layers.PERENNIAL_ICE.name, 0.0), (layers.GLACIERS.name, 0.5)]


class TestTheFrameGoesThroughTheHerosOwnSeam:
    """`write_frame` must satisfy `frame_json_text`'s FULL vocabulary. The exact call shipped
    broken while every gate was green, because nothing ran the shipping path: the validating
    serialiser refused the block payload the first time a real prep reached it."""

    def test_the_payload_round_trips_the_validating_serialiser(self, tmp_path):
        block = Block(col0=44032, row0=3584, size_px=2048, context_px=320)
        prep_block.write_frame(bodies.EARTH, block, tmp_path)
        written = json.loads((tmp_path / "frame.json").read_text())
        assert written["body"] == "earth"
        assert written["frame_lonlat"] is None, "a block is a grid window, not a lon/lat frame"
        assert written["dst_crs"] == "EPSG:3857"
        assert written["width_px"] == block.plane_edge_px, "the heightfield is the plane's"
        assert written["res_x"] == block.traced_edge_px, "and the render is the traced rectangle's"
        assert written["xres_m"] * written["width_px"] == pytest.approx(written["extent_w_m"])


class TestTheRecipeRecordsWhatExistenceCannotSee:
    """A prose README with a git SHA names the whole tree and moves on any checkout; a recipe names
    the values this cut baked in, so a freshness check can compare them."""

    def _written(self, monkeypatch, tmp_path, body):
        monkeypatch.setattr(prep_block.planet_seam, "declared",
                            lambda _body: frozenset({"heightfield"}))
        window = plane_window(0, 4096, 2048, 256)
        prep_block.write_recipe(body, window, tmp_path, [prep_block.render_seam.HEIGHTFIELD])
        return json.loads((tmp_path / prep_block.RECIPE_NAME).read_text())

    def test_the_two_terms_that_are_the_identity_on_earth_are_both_recorded(
            self, monkeypatch, tmp_path):
        recipe = self._written(monkeypatch, tmp_path, bodies.MARS)
        assert recipe["ground_scale"] == bodies.ground_metres_per_mercator_unit(bodies.MARS) != 1.0
        assert recipe["exaggeration"] == bodies.MARS.exaggeration != bodies.EARTH.exaggeration

    def test_what_the_body_could_not_supply_is_recorded_as_OFF_and_never_as_absent(
            self, monkeypatch, tmp_path):
        """`layers_off` and `rasters_off` on their own rule: the ones that are OFF, never the ones
        that are on, so Earth's recipe stays empty and a full planet does not restage."""
        mars = self._written(monkeypatch, tmp_path, bodies.MARS)
        assert mars["layers_off"] == ["glaciers", "lake_depth", "sea_ice"]
        assert mars["rasters_off"] == ["oceanmask", "watermask"]

    def test_earth_records_nothing_off_at_all(self, monkeypatch, tmp_path):
        monkeypatch.setattr(prep_block.planet_seam, "declared",
                            lambda _body: frozenset({"heightfield", "oceanmask", "watermask"}))
        window = plane_window(0, 4096, 2048, 256)
        prep_block.write_recipe(bodies.EARTH, window, tmp_path,
                                [prep_block.render_seam.HEIGHTFIELD])
        recipe = json.loads((tmp_path / prep_block.RECIPE_NAME).read_text())
        assert recipe["layers_off"] == [] and recipe["rasters_off"] == []

    def test_an_unchanged_recipe_does_not_move_its_own_mtime(self, monkeypatch, tmp_path):
        """Written through `freshness.write_if_changed`, which is what lets a constant stand in as
        an mtime dependency: the file moves if and only if a VALUE moved."""
        first = self._written(monkeypatch, tmp_path, bodies.MARS)
        stamp = (tmp_path / prep_block.RECIPE_NAME).stat().st_mtime_ns
        assert self._written(monkeypatch, tmp_path, bodies.MARS) == first
        assert (tmp_path / prep_block.RECIPE_NAME).stat().st_mtime_ns == stamp


class TestTheMidLatitudeIsTheWindowsAndNotTheBlocks:
    def test_the_margin_moves_the_mid_row(self, tmp_path):
        """A margin is asymmetric about the equator's rows in latitude terms, so taking the
        DELIVERED block's centre instead of the rendered window's would size the frame from a
        latitude the render never uses."""
        with_margin = plane_window(0, 1024, 2048, 512)
        without = plane_window(0, 1024, 2048, 0)
        assert with_margin.row_off + with_margin.height / 2 == pytest.approx(
            without.row_off + without.height / 2), "centres agree; the SPAN is what differs"
        assert prep_block.ground_width_m(with_margin, bodies.EARTH) > prep_block.ground_width_m(
            without, bodies.EARTH)

    def test_the_width_is_taken_at_the_mid_latitude_and_not_at_an_edge(self):
        window = plane_window(0, 1024, 2048, 0)
        mid = block_plan.row_latitude_deg(window.row_off + window.height / 2, bodies.EARTH)
        expected = (window.width * bodies.EARTH.map_units_per_pixel
                    * math.cos(math.radians(mid)))
        assert prep_block.ground_width_m(window, bodies.EARTH) == pytest.approx(expected)
