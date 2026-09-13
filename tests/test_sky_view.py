"""The horizon march, which is the only part of the post-render burn a test can reach.

Everything else in `sky_view` is `main()`: argparse, three rasterio opens and a write, invoked by
`batch.py` as a shell string, so there is no seam between reading and writing to hold onto.
`horizon_svf` is pure numpy and carries the whole shape of the effect.

THE GRID MUST BE WIDER THAN TWICE `max_px`. `np.roll` is periodic, so on a 64 px grid every pixel
sees a planted ridge both ways round and there is no open ground left to compare against: the first
attempt at these fixtures read the ground beside the ridge as MORE open than ground far from it, and
the control is what caught it rather than the assertion.

Several rungs call with no `exag`, because the shipping default is the subject. Passing one makes
the test read the value it brought: zeroing the default leaves every hero's land burned flat at the
maximum, which is what these exist to catch.
"""

import numpy as np
import pytest

from pipeline.look import sky_view

#: Comfortably over twice `horizon_svf`'s 42 px march, so ground outside it is genuinely untouched.
GRID_PX = 256
MARCH_PX = 42
GROUND_SCALE_M = 300.0
#: Steep enough that the occlusion is unambiguous at the default exaggeration.
TALL_RIDGE_M = 4000.0
#: Low enough that the horizon angle is nowhere near saturated, which is the regime both the
#: exaggeration lever and the distance normalisation actually operate in. Qatar and Paraguay are the
#: countries whose `sky_view_strength` is tuned up for terrain like it.
LOW_RIDGE_M = 40.0

MIDDLE = GRID_PX // 2


def ridge_at(column: int, height_m: float = TALL_RIDGE_M) -> np.ndarray:
    """A flat plate with one north-south wall in it."""
    heights = np.zeros((GRID_PX, GRID_PX))
    heights[:, column] = height_m
    return heights


@pytest.fixture(scope="module")
def svf_across_a_ridge() -> np.ndarray:
    """One march over a mid-grid wall, shared because each call is ~0.06 s."""
    return sky_view.horizon_svf(ridge_at(MIDDLE), m_per_px=GROUND_SCALE_M)


def test_ground_beyond_the_march_reads_fully_open(svf_across_a_ridge) -> None:
    """The control every other rung rests on: outside the march there is nothing to occlude with.

    It reads exactly 1.0 rather than approximately, since an unoccluded pixel accumulates
    `1 - sin(arctan(0))` in all sixteen directions.
    """
    assert svf_across_a_ridge[MIDDLE, MIDDLE + 100] == 1.0


def test_a_ridge_occludes_the_ground_beside_it(svf_across_a_ridge) -> None:
    """The property the whole module exists for, read at the shipping exaggeration."""
    beside = svf_across_a_ridge[MIDDLE, MIDDLE + 1]
    assert beside < 0.6, (
        f"a {TALL_RIDGE_M:.0f} m wall one pixel away left the sky {beside:.4f} open. The march is "
        "not finding the horizon, so every hero's valleys would burn at the same depth as its ridges"
    )


def test_the_horizon_angle_falls_off_with_distance() -> None:
    """A LOW ridge, because a tall one cannot see this at all.

    At 4000 m the angle is saturated everywhere inside the march, so what falls off there is the
    COUNT of directions still reaching the wall rather than the angle: dropping `distance_px` from
    the denominator left every rung in this file green when the fixture was the tall ridge.
    """
    row = sky_view.horizon_svf(ridge_at(MIDDLE, LOW_RIDGE_M), m_per_px=GROUND_SCALE_M)[MIDDLE]
    assert row[MIDDLE + 1] < 0.7
    assert row[MIDDLE + 10] > 0.85


def test_the_march_stops_at_max_px(svf_across_a_ridge) -> None:
    """Abrupt by construction rather than by tuning, and it is what makes the reduced SVF
    resolution affordable."""
    row = svf_across_a_ridge[MIDDLE]
    assert row[MIDDLE + MARCH_PX - 1] < 1.0
    assert row[MIDDLE + MARCH_PX] == 1.0


def test_the_factor_stays_inside_the_range_its_name_claims(svf_across_a_ridge) -> None:
    """0..1, which holds only because the horizon angle is clipped at zero.

    A ridge TOP looks down on everything around it, so its horizon gradient is negative and its
    factor exceeds 1 unclipped. The burn renormalises per country, so such an outlier does not
    error: it compresses every other pixel's darkening toward nothing. The ridge column itself is
    read here because it is the only place the defect appears.
    """
    assert svf_across_a_ridge.min() >= 0.0
    assert svf_across_a_ridge[:, MIDDLE].max() <= 1.0


def test_the_exaggeration_is_what_makes_low_relief_readable() -> None:
    """The lever, on terrain that reads as nothing without it.

    The occluded arm takes the default rather than naming a number, so a moved default fails here.
    """
    low_ridge = ridge_at(MIDDLE, LOW_RIDGE_M)
    shipping = sky_view.horizon_svf(low_ridge, m_per_px=GROUND_SCALE_M)[MIDDLE, MIDDLE + 1]
    unlevered = sky_view.horizon_svf(low_ridge, m_per_px=GROUND_SCALE_M, exag=1.0)[MIDDLE,
                                                                                  MIDDLE + 1]
    assert shipping < 0.7
    assert 0.9 < unlevered < 1.0


def test_the_march_wraps_around_the_grid_edge() -> None:
    """PINNED AS IT IS, NOT AS IT SHOULD BE. `np.roll` is periodic, so a ridge on a hero's west edge
    occludes its east edge as though the two were adjacent, and the value is pinned so that padding
    the march instead fails here rather than silently restaging 203 heroes.

    Unratified: the fix is a look change on every hero and the maintainer's to call.
    """
    west_edge = sky_view.horizon_svf(ridge_at(0), m_per_px=GROUND_SCALE_M)
    assert west_edge[MIDDLE, MIDDLE] == 1.0
    assert west_edge[MIDDLE, GRID_PX - 1] == pytest.approx(west_edge[MIDDLE, 1])
