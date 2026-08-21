"""Tests for `pipeline.block_plan`.

Every triple in `RENDERED_BLOCKS` comes from a `.done` marker written by the render probe during the
1,358-block judging run, by code sharing no line with the module under test.

THE TABLE DESCRIBES A PAST RUN, SO IT CARRIES THAT RUN'S PARAMETERS AND NOT TODAY'S. It used to
derive each block's latitude from `RENDER_BLOCK_PX`, which silently made a record of what was
rendered depend on what is CURRENTLY configured: doubling the block edge moved the latitude of
every historical row and the table stopped describing anything. `PROBE_BLOCK_PX` and `PROBE_RATIO`
are the run's own, pinned here, and nothing below reads a live constant for them.

WHAT THE PROBE PINS IS THE REACH, NOT THE RATIO, which is what lets the table survive the ratio
moving to 1.0. A margin of `m` written under ratio `r` and quantum `q` says the underlying per-axis
reach lay in `((m - q) / r, m / r]` — an independent measurement of a physical quantity, with the
policy divided back out. `implied_context_band` turns that into the width today's law must choose,
and the band is a few quanta wide against reaches in the hundreds.

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

#: The judging run's own block edge. The rows below are ITS block origins; at today's edge nine of
#: the ten are not block origins at all, which is exactly why this cannot be the live constant.
PROBE_BLOCK_PX = 2048

#: The margin ratio in force when those markers were written. The reach each margin implies is
#: recovered by dividing it back out, so the table keeps its evidential value at any ratio.
PROBE_RATIO = 0.39

#: The probe's floor and ceiling, needed to tell a margin the law CHOSE from one it was clamped to.
#: A clamped margin bounds the reach on one side only.
PROBE_FLOOR_PX = 64
PROBE_CEILING_PX = 768

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


def earth_context(relief_m: float, latitude_deg: float) -> int:
    earth = bodies.EARTH
    return block_plan.context_for(
        relief_m, latitude_deg,
        exaggeration=earth.exaggeration,
        ground_scale=bodies.ground_metres_per_mercator_unit(earth),
        map_units_per_pixel=earth.map_units_per_pixel,
        altitude_deg=SUN_ALTITUDE_DEG)


def probe_latitude(row: int) -> float:
    """The latitude the probe computed for a block whose top edge is at `row`."""
    return block_plan.row_latitude_deg(row + PROBE_BLOCK_PX / 2.0, bodies.EARTH)


def implied_context_band(margin: int) -> tuple[int, int]:
    """The width today's law must choose, bounded by what the probe's own margin implies.

    A margin the probe CHOSE says `(m - q) / r < reach <= m / r`. A margin it clamped says only one
    of those, and reading a clamp as a choice is how a table like this quietly stops constraining
    anything — the 847 m row is a floor case and would otherwise claim the reach was ~164 px when
    all it says is "not more than that".
    """
    quantum = block_plan.CONTEXT_QUANTUM_PX
    low = 0.0 if margin <= PROBE_FLOOR_PX else (margin - PROBE_FLOOR_PX) / PROBE_RATIO
    high = math.inf if margin >= PROBE_CEILING_PX else margin / PROBE_RATIO

    def quantised(reach: float) -> int:
        if reach == math.inf:
            return block_plan.CONTEXT_CEILING_PX
        chosen = math.ceil(reach / quantum) * quantum
        return min(max(chosen, block_plan.DENOISE_BAND_PX), block_plan.CONTEXT_CEILING_PX)

    return quantised(low), quantised(high)


@pytest.mark.parametrize(("row", "relief_m", "margin"), RENDERED_BLOCKS)
def test_earth_reproduces_the_reach_of_blocks_that_were_actually_rendered(row, relief_m, margin):
    """The independent oracle, with the ratio that produced it divided back out.

    It cannot assert the probe's margin any more — that number was 0.39 of the reach and today's
    law takes all of it — but the reach itself is a measurement of terrain and sun, and it did not
    change when the policy did.
    """
    low, high = implied_context_band(margin)
    assert low <= earth_context(relief_m, probe_latitude(row)) <= high


def test_the_probes_own_ratio_would_now_fail_that_band():
    """THE POSITIVE CONTROL, and without it the band above could be wide enough to prove nothing.

    Reverting to 0.39 must put every unclamped row outside its own band. If this stops failing, the
    band has widened to the point where the parametrised test is decoration.
    """
    escaped = 0
    for row, relief_m, margin in RENDERED_BLOCKS:
        if margin in (PROBE_FLOOR_PX, PROBE_CEILING_PX):
            continue
        low, _ = implied_context_band(margin)
        assert margin < low, f"the old ratio's {margin} px sits inside the band for row {row}"
        escaped += 1
    assert escaped >= 8, "too few unclamped rows left to make this a control"


def test_context_rounds_up_rather_than_to_nearest():
    """`ceil` against `round`, on a case constructed to sit just past a quantum boundary.

    THE BOUNDARY CASES CANNOT BE HARVESTED ANY MORE. Two of the rendered rows landed within 0.2% of
    a boundary at ratio 0.39; scaling the ratio moved both off it, and no row of a ten-row table is
    near a boundary at an arbitrary new ratio. So the case is INVERTED out of the law instead —
    pick the quanta, solve for the relief that produces them — which pins the rounding direction
    without pretending a rendered block happens to sit there.
    """
    earth = bodies.EARTH
    latitude = probe_latitude(68608)
    quantum = block_plan.CONTEXT_QUANTUM_PX
    target_quanta = 4.004
    # The law is linear in relief, so its own closed form inverts exactly.
    relief_m = (target_quanta * quantum
                * math.tan(math.radians(SUN_ALTITUDE_DEG))
                * earth.map_units_per_pixel
                * math.cos(math.radians(latitude))
                / (block_plan.CONTEXT_RATIO * earth.exaggeration
                   * math.cos(math.radians(45.0))))
    assert earth_context(relief_m, latitude) == math.ceil(target_quanta) * quantum
    assert earth_context(relief_m, latitude) != round(target_quanta) * quantum


# --------------------------------------------------------------- the body seam

def test_ground_scale_alone_accounts_for_1_878x():
    """Isolating the one term: same exaggeration, same pixel size, only the map-unit ratio moves.

    Asserted on its own because the body-to-body figure below is NOT this number, and the two are
    easy to conflate.
    """
    mars_scale = bodies.ground_metres_per_mercator_unit(bodies.MARS)
    common = dict(exaggeration=15.0, map_units_per_pixel=305.7483, altitude_deg=SUN_ALTITUDE_DEG)
    with_scale = block_plan.context_for(4000.0, 40.0, ground_scale=mars_scale, **common)
    without = block_plan.context_for(4000.0, 40.0, ground_scale=1.0, **common)
    assert 1.0 / mars_scale == pytest.approx(1.8780, abs=1e-4)
    assert with_scale > without


def test_dropping_ground_scale_undersizes_mars_rather_than_erroring():
    """The failure mode is silence: a truncated shadow simply stops, with no edge to notice."""
    mars = bodies.MARS
    correct = block_plan.context_for(
        4000.0, 40.0, exaggeration=mars.exaggeration,
        ground_scale=bodies.ground_metres_per_mercator_unit(mars),
        map_units_per_pixel=mars.map_units_per_pixel, altitude_deg=SUN_ALTITUDE_DEG)
    earthed = block_plan.context_for(
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
        return block_plan.context_for(
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
        block_plan.context_for(  # pyright: ignore[reportCallIssue]
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

#: Each case must be illegal for its OWN stated reason, so every extent below is a legal number of
#: blocks unless the case is about the extent. A window that is refused twice over tests whichever
#: branch runs first, and the block edge doubling silently turned four of these into that: a 2048
#: extent stopped being a whole block, so "leaves the grid" was never reached again.
@pytest.mark.parametrize(("window", "expected"), [
    (px_window(256, 0, block_plan.RENDER_BLOCK_PX, block_plan.RENDER_BLOCK_PX),
     "cell boundary"),                                          # origin off a cell boundary
    (px_window(0, 256, block_plan.RENDER_BLOCK_PX, block_plan.RENDER_BLOCK_PX),
     "cell boundary"),
    (px_window(0, 0, block_plan.CELL_PX, block_plan.RENDER_BLOCK_PX),
     "whole number"),                                           # extent not a whole block
    (px_window(0, 0, block_plan.RENDER_BLOCK_PX, 3000), "whole number"),
    (px_window(0, 0, 0, block_plan.RENDER_BLOCK_PX), "empty"),
    (px_window(131072 - block_plan.RENDER_BLOCK_PX // 2, 0,
               block_plan.RENDER_BLOCK_PX, block_plan.RENDER_BLOCK_PX),
     "leaves"),                                                 # runs off the east edge
    (px_window(-block_plan.RENDER_BLOCK_PX, 0,
               block_plan.RENDER_BLOCK_PX, block_plan.RENDER_BLOCK_PX), "leaves"),
])
def test_illegal_windows_raise_for_the_reason_they_were_written_for(window, expected):
    with pytest.raises(ValueError, match=expected):
        block_plan.check_alignment(window, bodies.EARTH)


def test_a_cell_aligned_block_multiple_window_is_legal():
    edge = block_plan.RENDER_BLOCK_PX
    block_plan.check_alignment(px_window(block_plan.CELL_PX, 2 * block_plan.CELL_PX,
                                         2 * edge, edge), bodies.EARTH)


def test_whole_grid_is_itself_legal():
    for body in (bodies.EARTH, bodies.MARS):
        block_plan.check_alignment(block_plan.whole_grid(body), body)


# --------------------------------------------------------------- planning

def test_plan_covers_the_window_exactly_once():
    edge = block_plan.RENDER_BLOCK_PX
    window = px_window(edge, 2 * edge, 2 * edge, 2 * edge)
    relief = np.full((2, 2), 1000.0)
    blocks = block_plan.plan(relief, window, bodies.EARTH, altitude_deg=SUN_ALTITUDE_DEG)
    assert len(blocks) == 4
    corners = {(b.col0, b.row0) for b in blocks}
    assert corners == {(edge, 2 * edge), (2 * edge, 2 * edge),
                       (edge, 3 * edge), (2 * edge, 3 * edge)}
    assert all(b.size_px == block_plan.RENDER_BLOCK_PX for b in blocks)


def test_plan_rejects_a_relief_grid_of_the_wrong_shape():
    with pytest.raises(ValueError):
        block_plan.plan(np.zeros((3, 3)),
                        px_window(0, 0, 2 * block_plan.RENDER_BLOCK_PX,
                                  2 * block_plan.RENDER_BLOCK_PX),
                        bodies.EARTH, altitude_deg=SUN_ALTITUDE_DEG)


def test_a_flat_block_beside_a_mountain_inherits_the_mountains_margin():
    """THE DEFECT THIS REPLACES, and the halo is what makes it work.

    An all-ocean block used to take its margin for free from an `ocean_share` shortcut, because a
    flat sea cannot receive a shadow. True, and beside the point: the margin is also what keeps the
    rendered frame's dark border out of the delivered pixels, and that border reaches as far as the
    SURROUNDING relief is tall. So a flat block next to a mountain range needs the mountain's
    margin, which is exactly what `haloed` already gives it — the shortcut was overriding the right
    answer with a cheap one.
    """
    edge = block_plan.RENDER_BLOCK_PX
    window = px_window(0, 16 * edge, 2 * edge, edge)
    relief = np.array([[0.0, 8000.0]])
    blocks = block_plan.plan(relief, window, bodies.EARTH, altitude_deg=SUN_ALTITUDE_DEG)
    assert blocks[0].context_px == blocks[1].context_px > block_plan.DENOISE_BAND_PX


def test_no_block_is_ever_planned_without_a_margin():
    """THE GUARD THE DEFECT NEEDED, and it has to be asked of the PLAN rather than of the law.

    `margin_for` was never the thing that returned zero on the ocean blocks — `plan`'s own shortcut
    was, bypassing the law entirely, so a guard pointed only at `margin_for` would have stayed green
    through the whole defect. This asks every block a planner can emit.
    """
    edge = block_plan.RENDER_BLOCK_PX
    window = px_window(0, 0, 4 * edge, 2 * edge)
    relief = np.array([[0.0, 12000.0, 0.0, 3000.0], [8000.0, 0.0, 500.0, 0.0]])
    blocks = block_plan.plan(relief, window, bodies.EARTH, altitude_deg=SUN_ALTITUDE_DEG)
    assert blocks, "no blocks planned, so the assertion below would pass vacuously"
    assert all(b.context_px >= block_plan.DENOISE_BAND_PX for b in blocks)


def test_flat_ground_still_gets_a_plane_that_covers_the_traced_rectangle():
    """THE FLOOR IS STRUCTURAL NOW, and it is the one bound whose failure is not merely a seam.

    Flat ground asks for no shadow reach at all, which is where the law's own zero comes from. A
    context below `DENOISE_BAND_PX` would leave the traced rectangle overhanging its own plane, so
    Cycles would path-trace a ring of frame with no heightfield under it — sky, not terrain, cropped
    straight into the mosaic. The old floor existed for the frame's dark border and was a look
    number; this one cannot be turned down.
    """
    assert block_plan.context_for(0.0, 0.0, exaggeration=15.0, ground_scale=1.0,
                                  map_units_per_pixel=305.7483,
                                  altitude_deg=SUN_ALTITUDE_DEG) == block_plan.DENOISE_BAND_PX


def test_no_planned_block_can_have_a_plane_narrower_than_its_traced_frame():
    """The same bound, asked of the PLAN, because the law is not the only thing that can produce a
    block — `plan`'s own ocean shortcut once bypassed it entirely and returned zero."""
    window = px_window(0, 0, block_plan.RENDER_BLOCK_PX * 2, block_plan.RENDER_BLOCK_PX)
    relief = np.array([[0.0, 0.0]])
    blocks = block_plan.plan(relief, window, bodies.EARTH, altitude_deg=SUN_ALTITUDE_DEG)
    assert blocks, "no blocks planned, so the assertion below would pass vacuously"
    assert all(b.plane_edge_px >= b.traced_edge_px for b in blocks)


def test_plan_takes_no_ocean_share_any_more():
    """The shortcut is gone, and its parameter with it: a `plan` that still ACCEPTED an ocean share
    while ignoring it would read to the next caller as a knob that does something."""
    with pytest.raises(TypeError):
        block_plan.plan(np.zeros((1, 2)),
                        px_window(0, 0, 2 * block_plan.RENDER_BLOCK_PX,
                                  block_plan.RENDER_BLOCK_PX),
                        bodies.EARTH, altitude_deg=SUN_ALTITUDE_DEG,
                        ocean_share=np.zeros((1, 2)))  # pyright: ignore[reportCallIssue]


# --------------------------------------------------------------- the ceilings

def test_context_clamps_at_the_ceiling():
    absurd = earth_context(500_000.0, 84.0)
    assert absurd == block_plan.CONTEXT_CEILING_PX


def test_the_ceiling_does_not_bind_on_any_block_that_was_rendered():
    """A CLAMPED BLOCK KEEPS ITS DEFECT WHILE LOOKING FIXED, which is what this is really about.

    Measured on Earth's own relief cache at this block edge, the widest ask is 1,856 px — the three
    row-0 blocks at 84.5N holding 5,076 m of haloed relief — so the ceiling is headroom rather than
    a clamp. That measurement needs the store; this is the weaker check that survives without it,
    and it says none of the rendered blocks reaches the ceiling either.
    """
    for row, relief_m, margin in RENDERED_BLOCKS:
        _, high = implied_context_band(margin)
        assert earth_context(relief_m, probe_latitude(row)) <= high
        assert high < block_plan.CONTEXT_CEILING_PX


def test_the_three_widths_are_distinct_and_only_the_block_edge_can_overflow_the_frame():
    edge = block_plan.RENDER_BLOCK_PX
    block = block_plan.Block(col0=0, row0=0, size_px=edge, context_px=576)
    assert block.traced_edge_px == edge + 2 * block_plan.DENOISE_BAND_PX
    assert block.plane_edge_px == edge + 2 * 576
    assert block.plane_edge_px > block.traced_edge_px > block.size_px
    assert block.fits
    widest = block_plan.Block(col0=0, row0=0, size_px=edge,
                              context_px=block_plan.CONTEXT_CEILING_PX)
    assert widest.fits, "a plane is geometry; no context however wide is a frame"
    huge = block_plan.Block(col0=0, row0=0, size_px=block_plan.TRACED_CEILING_PX, context_px=128)
    assert not huge.fits


def test_the_plane_window_is_the_delivered_window_grown_by_the_context():
    edge = block_plan.RENDER_BLOCK_PX
    block = block_plan.Block(col0=4 * edge, row0=8 * edge, size_px=edge, context_px=192)
    delivered, plane = block.delivered_window, block.plane_window
    assert (delivered.col_off, delivered.row_off) == (4 * edge, 8 * edge)
    assert (delivered.width, delivered.height) == (edge, edge)
    assert (plane.col_off, plane.row_off) == (4 * edge - 192, 8 * edge - 192)
    assert plane.width == plane.height == edge + 2 * 192


def test_a_block_at_column_zero_reads_from_negative_columns():
    """The wrap is the reader's job, but the plan must express it rather than silently clamping."""
    block = block_plan.Block(col0=0, row0=32768, size_px=block_plan.RENDER_BLOCK_PX,
                             context_px=128)
    assert block.plane_window.col_off == -128


class TestFoldingCellsUpToBlocks:
    """`relief_scan` records cells; `plan` consumes blocks. These two are the bridge.

    EVERY GRID HERE IS SIZED FROM `CELLS_PER_BLOCK` RATHER THAN SPELLED. They were all 4x4, which
    was the fold's shape at the block edge those cases were written under, and doubling the edge
    turned each of them from "one block's cells" into "a quarter of one" — the whole class failing
    on an assertion about arithmetic it was not testing.
    """

    @property
    def cells(self) -> int:
        return block_plan.CELLS_PER_BLOCK

    def _grid(self, fill=0.0):
        return np.full((self.cells, self.cells), fill)

    def test_the_cells_that_span_a_block_are_derived_from_the_two_constants(self):
        """Never written down, so re-tuning either stays coherent. The cache is deliberately FINER
        than the block, which is what lets a block-edge change re-fold it instead of re-reading a
        46 GB master."""
        assert block_plan.CELLS_PER_BLOCK == block_plan.RENDER_BLOCK_PX // block_plan.CELL_PX
        assert block_plan.CELL_PX < block_plan.RENDER_BLOCK_PX

    def test_relief_is_the_range_across_a_blocks_cells_and_not_the_greatest_elevation(self):
        """The distinction `plan`'s own docstring pins with the 13,940 m Andes witness."""
        high, low = self._grid(), self._grid()
        high[1, 1] = 6000.0                     # a summit in one cell
        low[self.cells - 1, self.cells - 1] = -8000.0   # a trench in another, of the same block
        relief = block_plan.relief_from_cells(high, low)
        assert relief.shape == (1, 1)
        assert relief[0, 0] == pytest.approx(14000.0), "the fold returned an elevation, not a range"

    def test_the_reduce_is_max_of_maxima_and_not_a_mean(self):
        """Averaging would hide a single steep cell, which is the one the context exists for."""
        high = self._grid()
        high[0, 0] = 4000.0
        assert block_plan.relief_from_cells(high, self._grid())[0, 0] == pytest.approx(4000.0)

    def test_a_block_with_no_elevation_data_raises_rather_than_scoring_zero(self):
        """Relief 0 yields the narrowest context there is, so a block whose data merely failed to
        arrive would render with its neighbours' shadows truncated at the seam and nothing to
        notice."""
        empty = self._grid(np.nan)
        with pytest.raises(ValueError, match="no elevation data"):
            block_plan.relief_from_cells(empty, empty)

    def test_a_partly_no_data_block_still_uses_the_cells_that_have_data(self):
        high, low = self._grid(np.nan), self._grid(np.nan)
        high[2, 2], low[2, 2] = 1200.0, 200.0
        assert block_plan.relief_from_cells(high, low)[0, 0] == pytest.approx(1000.0)

    def test_a_cell_grid_that_is_not_a_whole_number_of_blocks_is_refused(self):
        ragged = np.zeros((self.cells, self.cells + 2))
        with pytest.raises(ValueError, match="not a whole number"):
            block_plan.relief_from_cells(ragged, ragged)

    def test_mismatched_high_and_low_grids_are_refused(self):
        with pytest.raises(ValueError, match="different cell grids"):
            block_plan.relief_from_cells(self._grid(), np.zeros((self.cells * 2,
                                                                self.cells * 2)))

    def test_ocean_share_folds_by_mean_because_every_cell_covers_the_same_pixels(self):
        share = self._grid()
        share[0, :] = 1.0
        assert block_plan.share_from_cells(share)[0, 0] == pytest.approx(1.0 / self.cells)

    def test_the_folded_pair_is_what_plan_accepts(self):
        """The two ends of the contract, joined — a fold whose shape `plan` rejects is no bridge."""
        cells = block_plan.CELLS_PER_BLOCK * 2
        high, low = np.full((cells, cells), 3000.0), np.zeros((cells, cells))
        window = Window(0, 0, 2 * block_plan.RENDER_BLOCK_PX,  # pyright: ignore[reportCallIssue]
                        2 * block_plan.RENDER_BLOCK_PX)
        blocks = block_plan.plan(block_plan.relief_from_cells(high, low), window, bodies.EARTH,
                                 altitude_deg=45.0)
        assert len(blocks) == 4
        assert all(block.context_px > 0 for block in blocks)
