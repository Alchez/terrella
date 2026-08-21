"""Tests for `pipeline.block_plan`.

Every triple in `RENDERED_BLOCKS` comes from a `.done` marker written by the render probe during the
1,358-block judging run, by code sharing no line with the module under test. All 1,358 reproduce; the
ten here span the range and include the two within 0.2% of a quantum boundary, which are what pin the
rounding direction.

Rows are pinned and latitude derived, rather than read back from the marker: markers record latitude
to two decimals, and that is enough to flip a quantum on those two blocks.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from rasterio.windows import Window

from pipeline import block_plan, bodies, mercator

SUN_ALTITUDE_DEG = 45.0


def px_window(col_off: int, row_off: int, width: int, height: int) -> Window:
    """`rasterio.windows.Window` has no typed constructor, so the ignore lives here once.

    Twelve of them scattered through the cases would be twelve places to keep in step, and the
    thing being suppressed is identical at every one.
    """
    return Window(col_off, row_off, width, height)  # pyright: ignore[reportCallIssue]

#: (grid row of the block's top edge, greatest relief reaching it in metres, margin the probe used).
RENDERED_BLOCKS = [
    (89088, 6759.0, 192),    # southamerica, lat -55.78
    (68608, 13940.0, 256),   # southamerica, lat -11.18 — 3.004 quanta, pins ceil over round
    (65536, 6736.0, 128),    # rift, lat -2.81
    (54784, 9952.0, 192),    # eastasia, lat 25.80
    (47104, 847.0, 64),      # westnortham, lat 43.07 — the floor: even trivial relief takes a quantum
    (37888, 2534.0, 128),    # siberia, lat 58.81
    (26112, 4023.0, 192),    # arctic, lat 71.97
    (89088, 5330.0, 192),    # southamerica, lat -55.78 — 2.003 quanta, the second boundary case
    (3584, 3594.0, 512),     # arctic, lat 83.83
    (3584, 4136.0, 576),     # arctic, lat 83.83 — the largest margin the judging run produced
]


def earth_margin(relief_m: float, latitude_deg: float) -> int:
    earth = bodies.EARTH
    return block_plan.margin_for(
        relief_m, latitude_deg,
        exaggeration=earth.exaggeration,
        ground_scale=bodies.ground_metres_per_mercator_unit(earth),
        map_units_per_pixel=earth.map_units_per_pixel,
        altitude_deg=SUN_ALTITUDE_DEG)


@pytest.mark.parametrize(("row", "relief_m", "expected"), RENDERED_BLOCKS)
def test_earth_reproduces_blocks_that_were_actually_rendered(row, relief_m, expected):
    latitude = block_plan.row_latitude_deg(row + block_plan.RENDER_BLOCK_PX / 2.0, bodies.EARTH)
    assert earth_margin(relief_m, latitude) == expected


def test_margin_rounds_up_rather_than_to_nearest():
    """The two boundary cases above only discriminate if rounding is genuinely `ceil`.

    Stated as its own case because a `round` would still pass eight of the ten parametrised ones,
    and a reader should not have to recompute quanta to see which two carry the property.
    """
    latitude = block_plan.row_latitude_deg(68608 + block_plan.RENDER_BLOCK_PX / 2.0, bodies.EARTH)
    earth = bodies.EARTH
    raw = (block_plan.MARGIN_RATIO
           * (earth.exaggeration / math.cos(math.radians(latitude)))
           * 13940.0 / math.tan(math.radians(SUN_ALTITUDE_DEG))
           / earth.map_units_per_pixel * math.cos(math.radians(45.0)))
    quanta = raw / block_plan.MARGIN_QUANTUM_PX
    assert math.floor(quanta) < quanta < math.floor(quanta) + 0.01, "case no longer near a boundary"
    assert earth_margin(13940.0, latitude) == math.ceil(quanta) * block_plan.MARGIN_QUANTUM_PX


# --------------------------------------------------------------- the body seam

def test_ground_scale_alone_accounts_for_1_878x():
    """Isolating the one term: same exaggeration, same pixel size, only the map-unit ratio moves.

    Asserted on its own because the body-to-body figure below is NOT this number, and the two are
    easy to conflate.
    """
    mars_scale = bodies.ground_metres_per_mercator_unit(bodies.MARS)
    common = dict(exaggeration=15.0, map_units_per_pixel=305.7483, altitude_deg=SUN_ALTITUDE_DEG)
    with_scale = block_plan.margin_for(4000.0, 40.0, ground_scale=mars_scale, **common)
    without = block_plan.margin_for(4000.0, 40.0, ground_scale=1.0, **common)
    assert 1.0 / mars_scale == pytest.approx(1.8780, abs=1e-4)
    assert with_scale > without


def test_dropping_ground_scale_undersizes_mars_rather_than_erroring():
    """The failure mode is silence: a truncated shadow simply stops, with no edge to notice."""
    mars = bodies.MARS
    correct = block_plan.margin_for(
        4000.0, 40.0, exaggeration=mars.exaggeration,
        ground_scale=bodies.ground_metres_per_mercator_unit(mars),
        map_units_per_pixel=mars.map_units_per_pixel, altitude_deg=SUN_ALTITUDE_DEG)
    earthed = block_plan.margin_for(
        4000.0, 40.0, exaggeration=mars.exaggeration, ground_scale=1.0,
        map_units_per_pixel=mars.map_units_per_pixel, altitude_deg=SUN_ALTITUDE_DEG)
    assert earthed < correct


def test_mars_differs_from_earth_by_exaggeration_and_pixel_size_too():
    """At matched relief and latitude the two bodies differ by 1.252x, NOT by the ground scale.

    Mars exaggerates at 20x against Earth's 15x and its grid is z7, so a map unit spans twice the
    pixels. Anything carrying Earth's exaggeration or pixel size passes every Earth case above and
    is wrong here by a third.
    """
    def body_margin(body, relief_m):
        return block_plan.margin_for(
            relief_m, 40.0, exaggeration=body.exaggeration,
            ground_scale=bodies.ground_metres_per_mercator_unit(body),
            map_units_per_pixel=body.map_units_per_pixel, altitude_deg=SUN_ALTITUDE_DEG)

    earth, mars = bodies.EARTH, bodies.MARS
    ratio = ((mars.exaggeration / bodies.ground_metres_per_mercator_unit(mars)
              / mars.map_units_per_pixel)
             / (earth.exaggeration / bodies.ground_metres_per_mercator_unit(earth)
                / earth.map_units_per_pixel))
    assert ratio == pytest.approx(1.2520, abs=1e-4)
    # 12,000 m rather than a gentler figure on purpose: at 1.252x the two bodies only land in
    # DIFFERENT quanta once the raw margin is a few hundred pixels, so a smaller relief asserts
    # nothing at all. The ratio above is the property; this is the case where it survives rounding.
    assert body_margin(mars, 12_000.0) > body_margin(earth, 12_000.0)


def test_altitude_has_no_default_because_no_root_module_owns_one():
    with pytest.raises(TypeError):
        block_plan.margin_for(  # pyright: ignore[reportCallIssue]
            4000.0, 40.0, exaggeration=15.0, ground_scale=1.0, map_units_per_pixel=305.7483)


def test_row_latitude_reads_the_projection_sphere_not_the_body():
    """Every grid here is EPSG:3857, so the same FRACTION down any body's grid is the same latitude.

    Reading the radius off the body registry would put Mars's rows tens of degrees out with no
    visible symptom.

    Compared against `mercator` directly rather than between the two bodies: the half-pixel offset
    to a row CENTRE differs at two pixel sizes, so a body-to-body equality would hold only to about
    2e-4 degrees, and a tolerance that loose would also admit a wrong sphere at high latitude.
    """
    for body in (bodies.EARTH, bodies.MARS):
        for row in (1024, 8192, block_plan.grid_px(body) // 2):
            northing = mercator.MERCATOR_HALF_M - (row + 0.5) * body.map_units_per_pixel
            expected = mercator.latitude_at(northing, mercator.WEB_MERCATOR_RADIUS_M)
            assert block_plan.row_latitude_deg(row, body) == pytest.approx(float(expected),
                                                                          abs=1e-9)

    # The control: Mars's OWN radius is a plausible thing to reach for and gives a wildly different
    # answer, so the assertion above is discriminating rather than trivially true.
    row = block_plan.grid_px(bodies.MARS) // 4
    northing = mercator.MERCATOR_HALF_M - (row + 0.5) * bodies.MARS.map_units_per_pixel
    wrong = float(mercator.latitude_at(northing, bodies.MARS.ground_radius_m))
    assert abs(block_plan.row_latitude_deg(row, bodies.MARS) - wrong) > 10.0


def test_polar_rows_clip_to_mercators_limit():
    """Row 0 is past 85.05 N, where `1/cos(lat)` runs away and the z-factor with it.

    `hillshade.per_row_zfactor_hillshade` applies exactly this clip before building its z-factor, so
    without it a margin would be sized from a latitude the shading never uses. The top and bottom
    rows of every body's grid are in that regime.
    """
    for body in (bodies.EARTH, bodies.MARS):
        edge = block_plan.grid_px(body)
        assert block_plan.row_latitude_deg(0, body) == block_plan.MERCATOR_LATITUDE_LIMIT_DEG
        assert block_plan.row_latitude_deg(edge - 1, body) == -block_plan.MERCATOR_LATITUDE_LIMIT_DEG
        # The control: a row well inside the limit must NOT be clipped, or the two assertions above
        # would also pass with the function returning the limit unconditionally.
        assert abs(block_plan.row_latitude_deg(edge // 2, body)) < 1.0


def test_grid_edge_follows_each_body_max_zoom():
    assert block_plan.grid_px(bodies.EARTH) == 131072   # 512 << 8
    assert block_plan.grid_px(bodies.MARS) == 65536     # 512 << 7


# --------------------------------------------------------------- the halo

def test_halo_wraps_in_longitude():
    """A mountain in the first column must raise the margin of the last one: the planet is cyclic."""
    relief = np.zeros((3, 8), dtype=np.float64)
    relief[1, 0] = 9000.0
    widened = block_plan.haloed(relief)
    assert widened[1, -1] == 9000.0
    assert widened[1, 1] == 9000.0
    assert widened[1, 4] == 0.0, "the wrap must not leak across the whole row"


def test_halo_clamps_in_latitude():
    """The north pole does not shadow the south pole, so rows edge-replicate instead of wrapping."""
    relief = np.zeros((4, 4), dtype=np.float64)
    relief[0, 2] = 9000.0
    widened = block_plan.haloed(relief)
    assert widened[-1, 2] == 0.0, "top row leaked to the bottom: rows must not wrap"
    assert widened[1, 2] == 9000.0


def test_halo_takes_the_neighbourhood_maximum_diagonally_too():
    relief = np.zeros((3, 3), dtype=np.float64)
    relief[1, 1] = 5000.0
    widened = block_plan.haloed(relief)
    assert (widened == 5000.0).all()


def test_halo_does_not_mutate_its_input():
    relief = np.zeros((3, 3), dtype=np.float64)
    relief[1, 1] = 5000.0
    block_plan.haloed(relief)
    assert relief[0, 0] == 0.0


# --------------------------------------------------------------- alignment

@pytest.mark.parametrize("window", [
    px_window(256, 0, 2048, 2048),        # origin off a cell boundary
    px_window(0, 256, 2048, 2048),
    px_window(0, 0, 1024, 2048),          # extent not a whole number of blocks
    px_window(0, 0, 2048, 3000),
    px_window(0, 0, 0, 2048),             # empty
    px_window(131072 - 1024, 0, 2048, 2048),   # leaves the grid
    px_window(-2048, 0, 2048, 2048),
])
def test_illegal_windows_raise(window):
    with pytest.raises(ValueError):
        block_plan.check_alignment(window, bodies.EARTH)


def test_a_cell_aligned_block_multiple_window_is_legal():
    block_plan.check_alignment(px_window(512, 1024, 4096, 2048), bodies.EARTH)


def test_whole_grid_is_itself_legal():
    for body in (bodies.EARTH, bodies.MARS):
        block_plan.check_alignment(block_plan.whole_grid(body), body)


# --------------------------------------------------------------- planning

def test_plan_covers_the_window_exactly_once():
    window = px_window(2048, 4096, 4096, 4096)
    relief = np.full((2, 2), 1000.0)
    blocks = block_plan.plan(relief, window, bodies.EARTH, altitude_deg=SUN_ALTITUDE_DEG)
    assert len(blocks) == 4
    corners = {(b.col0, b.row0) for b in blocks}
    assert corners == {(2048, 4096), (4096, 4096), (2048, 6144), (4096, 6144)}
    assert all(b.size_px == block_plan.RENDER_BLOCK_PX for b in blocks)


def test_plan_rejects_a_relief_grid_of_the_wrong_shape():
    with pytest.raises(ValueError):
        block_plan.plan(np.zeros((3, 3)), px_window(0, 0, 4096, 4096), bodies.EARTH,
                        altitude_deg=SUN_ALTITUDE_DEG)


def test_a_flat_block_beside_a_mountain_inherits_the_mountains_margin():
    """THE DEFECT THIS REPLACES, and the halo is what makes it work.

    An all-ocean block used to take its margin for free from an `ocean_share` shortcut, because a
    flat sea cannot receive a shadow. True, and beside the point: the margin is also what keeps the
    rendered frame's dark border out of the delivered pixels, and that border reaches as far as the
    SURROUNDING relief is tall. So a flat block next to a mountain range needs the mountain's
    margin, which is exactly what `haloed` already gives it — the shortcut was overriding the right
    answer with a cheap one.
    """
    window = px_window(0, 65536, 4096, 2048)
    relief = np.array([[0.0, 8000.0]])
    blocks = block_plan.plan(relief, window, bodies.EARTH, altitude_deg=SUN_ALTITUDE_DEG)
    assert blocks[0].margin_px == blocks[1].margin_px > block_plan.MARGIN_MINIMUM_PX


def test_no_block_is_ever_planned_without_a_margin():
    """THE GUARD THE DEFECT NEEDED, and it has to be asked of the PLAN rather than of the law.

    `margin_for` was never the thing that returned zero on the ocean blocks — `plan`'s own shortcut
    was, bypassing the law entirely, so a guard pointed only at `margin_for` would have stayed green
    through the whole defect. This asks every block a planner can emit.
    """
    window = px_window(0, 0, 4096 * 2, 2048 * 2)
    relief = np.array([[0.0, 12000.0, 0.0, 3000.0], [8000.0, 0.0, 500.0, 0.0]])
    blocks = block_plan.plan(relief, window, bodies.EARTH, altitude_deg=SUN_ALTITUDE_DEG)
    assert blocks, "no blocks planned, so the assertion below would pass vacuously"
    assert all(b.margin_px >= block_plan.MARGIN_MINIMUM_PX for b in blocks)


def test_the_shadow_law_alone_never_returns_less_than_the_minimum():
    """Flat ground asks for no shadow reach at all, which is where the law's own zero comes from."""
    assert block_plan.margin_for(0.0, 0.0, exaggeration=15.0, ground_scale=1.0,
                                 map_units_per_pixel=305.7483,
                                 altitude_deg=SUN_ALTITUDE_DEG) == block_plan.MARGIN_MINIMUM_PX


def test_plan_takes_no_ocean_share_any_more():
    """The shortcut is gone, and its parameter with it: a `plan` that still ACCEPTED an ocean share
    while ignoring it would read to the next caller as a knob that does something."""
    with pytest.raises(TypeError):
        block_plan.plan(np.zeros((1, 2)), px_window(0, 0, 4096, 2048), bodies.EARTH,
                        altitude_deg=SUN_ALTITUDE_DEG,
                        ocean_share=np.zeros((1, 2)))  # pyright: ignore[reportCallIssue]


# --------------------------------------------------------------- the ceilings

def test_margin_clamps_at_the_ceiling():
    absurd = earth_margin(500_000.0, 84.0)
    assert absurd == block_plan.MARGIN_CEILING_PX


def test_the_ceiling_does_not_bind_on_any_block_that_was_rendered():
    """The judging run's largest margin was 576, so the 768 ceiling is headroom, not a clamp.

    If this fails the ratio has moved, and the margin/frame coupling recorded in the plan is live
    again — it is not a licence to raise the ceiling.
    """
    for row, relief_m, expected in RENDERED_BLOCKS:
        latitude = block_plan.row_latitude_deg(row + block_plan.RENDER_BLOCK_PX / 2.0, bodies.EARTH)
        assert earth_margin(relief_m, latitude) == expected < block_plan.MARGIN_CEILING_PX


def test_rendered_edge_and_frame_fit():
    fitting = block_plan.Block(col0=0, row0=0, size_px=2048, margin_px=576)
    assert fitting.rendered_edge_px == 3200
    assert fitting.fits
    huge = block_plan.Block(col0=0, row0=0, size_px=2048, margin_px=4096)
    assert not huge.fits


def test_render_window_is_the_delivered_window_grown_by_the_margin():
    block = block_plan.Block(col0=4096, row0=8192, size_px=2048, margin_px=192)
    delivered, rendered = block.delivered_window, block.render_window
    assert (delivered.col_off, delivered.row_off) == (4096, 8192)
    assert (delivered.width, delivered.height) == (2048, 2048)
    assert (rendered.col_off, rendered.row_off) == (4096 - 192, 8192 - 192)
    assert rendered.width == rendered.height == 2048 + 2 * 192


def test_a_block_at_column_zero_renders_from_negative_columns():
    """The wrap is the reader's job, but the plan must express it rather than silently clamping."""
    block = block_plan.Block(col0=0, row0=32768, size_px=2048, margin_px=128)
    assert block.render_window.col_off == -128


class TestFoldingCellsUpToBlocks:
    """`relief_scan` records cells; `plan` consumes blocks. These two are the bridge."""

    def test_four_cells_span_a_block_on_every_body(self):
        """Derived from the two constants, never written down, so re-tuning either stays coherent."""
        assert block_plan.CELLS_PER_BLOCK == block_plan.RENDER_BLOCK_PX // block_plan.CELL_PX
        assert block_plan.CELLS_PER_BLOCK == 4

    def test_relief_is_the_range_across_a_blocks_cells_and_not_the_greatest_elevation(self):
        """The distinction `plan`'s own docstring pins with the 13,940 m Andes witness."""
        high = np.zeros((4, 4))
        low = np.zeros((4, 4))
        high[1, 1] = 6000.0     # a summit in one cell
        low[3, 3] = -8000.0     # a trench in another, of the same block
        relief = block_plan.relief_from_cells(high, low)
        assert relief.shape == (1, 1)
        assert relief[0, 0] == pytest.approx(14000.0), "the fold returned an elevation, not a range"

    def test_the_reduce_is_max_of_maxima_and_not_a_mean(self):
        """Averaging would hide a single steep cell, which is the one the margin exists for."""
        high = np.zeros((4, 4))
        high[0, 0] = 4000.0
        assert block_plan.relief_from_cells(high, np.zeros((4, 4)))[0, 0] == pytest.approx(4000.0)

    def test_a_block_with_no_elevation_data_raises_rather_than_scoring_zero(self):
        """Relief 0 yields margin 0, so a block whose data merely failed to arrive would render
        with its neighbours' shadows truncated at the seam and nothing to notice."""
        empty = np.full((4, 4), np.nan)
        with pytest.raises(ValueError, match="no elevation data"):
            block_plan.relief_from_cells(empty, empty)

    def test_a_partly_no_data_block_still_uses_the_cells_that_have_data(self):
        high = np.full((4, 4), np.nan)
        low = np.full((4, 4), np.nan)
        high[2, 2], low[2, 2] = 1200.0, 200.0
        assert block_plan.relief_from_cells(high, low)[0, 0] == pytest.approx(1000.0)

    def test_a_cell_grid_that_is_not_a_whole_number_of_blocks_is_refused(self):
        ragged = np.zeros((4, 6))
        with pytest.raises(ValueError, match="not a whole number"):
            block_plan.relief_from_cells(ragged, ragged)

    def test_mismatched_high_and_low_grids_are_refused(self):
        with pytest.raises(ValueError, match="different cell grids"):
            block_plan.relief_from_cells(np.zeros((4, 4)), np.zeros((8, 8)))

    def test_ocean_share_folds_by_mean_because_every_cell_covers_the_same_pixels(self):
        share = np.zeros((4, 4))
        share[0, :] = 1.0
        assert block_plan.share_from_cells(share)[0, 0] == pytest.approx(0.25)

    def test_the_folded_pair_is_what_plan_accepts(self):
        """The two ends of the contract, joined — a fold whose shape `plan` rejects is no bridge."""
        cells = block_plan.CELLS_PER_BLOCK * 2
        high, low = np.full((cells, cells), 3000.0), np.zeros((cells, cells))
        window = Window(0, 0, 2 * block_plan.RENDER_BLOCK_PX,  # pyright: ignore[reportCallIssue]
                        2 * block_plan.RENDER_BLOCK_PX)
        blocks = block_plan.plan(block_plan.relief_from_cells(high, low), window, bodies.EARTH,
                                 altitude_deg=45.0)
        assert len(blocks) == 4
        assert all(block.margin_px > 0 for block in blocks)
