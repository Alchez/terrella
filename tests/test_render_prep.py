"""Tests for render_prep's resolution floor — the tiny-country anti-striping lever.

The floor box-lowpasses the warped heightfield only where the frame upsampled far
past the 30 m DEM, killing sub-source GLO-30 striping ("shredding") without a
re-warp. The warp itself needs rasterio I/O, so the unit tests target the two
pieces that carry the logic and the physics: floor_box_px (kernel width + the
engage/skip decision) and an oracle that the chosen kernel removes sub-floor
structure while preserving real relief — proof independent of any render.
"""
import numpy as np
from scipy.ndimage import uniform_filter

from pipeline.render import render_prep as rp

# ---- floor_box_px: kernel width + the engage/skip gate -----------------------

def test_floor_box_px_values():
    assert rp.floor_box_px(60.0, 2.71) == 22   # san marino (11x source)
    assert rp.floor_box_px(60.0, 1.36) == 44   # vatican    (22x)
    assert rp.floor_box_px(60.0, 5.03) == 12   # andorra    (6x, on the line)
    assert rp.floor_box_px(60.0, 200.0) == 0   # large country: rounds to 0
    assert rp.floor_box_px(0.0, 2.71) == 0     # floor disabled


def test_floor_gate_splits_at_five_times_source():
    # St Kitts (6.76 m/px, ~4.4x) sits just under the >5x line: its box is 9 px,
    # below the gate, so the floor does NOT engage — the volcanic islands stay
    # untouched (Fix A owns their AO). San Marino is over the line and engages.
    assert rp.floor_box_px(60.0, 6.76) < rp.FLOOR_MIN_BOX_PX
    assert rp.floor_box_px(60.0, 2.71) >= rp.FLOOR_MIN_BOX_PX
    # And a large country never engages regardless of floor.
    assert rp.floor_box_px(60.0, 90.0) < rp.FLOOR_MIN_BOX_PX


# ---- oracle: the kernel crushes sub-floor striping, keeps real relief --------

def _stripe_energy(field: np.ndarray) -> float:
    """Variance left after removing each column's mean — the along-track stripe
    lives in the per-column y-variation; a smooth x-only ramp contributes none."""
    return float(np.mean((field - field.mean(axis=0, keepdims=True)) ** 2))


def test_box_floor_attenuates_sub_floor_striping():
    # A gentle real ramp (km-scale signal) + a sub-floor along-track stripe
    # (period 2 px = ~5 m on a 2.71 m/px grid, well under the 60 m floor). The
    # floor's box kernel must crush the stripe while preserving the ramp.
    height, width = 200, 200
    row_idx, col_idx = np.mgrid[0:height, 0:width].astype("float32")
    ramp = 0.01 * col_idx                       # real signal, varies in x only
    stripe = 5.0 * ((row_idx % 2) * 2.0 - 1.0)  # +-5 m alternating rows
    field = (ramp + stripe).astype("float32")

    box = rp.floor_box_px(60.0, 2.71)           # 22 px
    smoothed = uniform_filter(field, size=box, mode="nearest")

    assert _stripe_energy(smoothed) < _stripe_energy(field) / 50   # stripe gone
    # ramp survives: interior per-column means track the original ramp
    interior = slice(box, -box)
    assert np.allclose(smoothed[interior, interior].mean(axis=0),
                       field[interior, interior].mean(axis=0), atol=0.05)
