"""Tests for render_prep's resolution floor and for what frame.json records.

The floor box-lowpasses the warped heightfield only where the frame upsampled far
past the 30 m DEM, killing sub-source GLO-30 striping ("shredding") without a
re-warp. The warp itself needs rasterio I/O, so the unit tests target the two
pieces that carry the logic and the physics: floor_box_px (kernel width + the
engage/skip decision) and an oracle that the chosen kernel removes sub-floor
structure while preserving real relief — proof independent of any render.

The second half guards `scene_numbers` and `frame_json_text`, which are the seam
the block prep shares with the hero path and the one owner of frame.json's key
order respectively.
"""
import json

import numpy as np
import pytest
from scipy.ndimage import uniform_filter

from pipeline import bodies
from pipeline.look import palette
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


# ---- the exaggeration is the body's, not Earth's ----------------------------

def _unit_grid(exaggeration: float) -> dict:
    """Scene numbers for a square grid whose half-width is 1 m, so `displacement_scale` reduces to
    the exaggeration itself and a wrong one cannot hide behind the metres-per-unit conversion."""
    return rp.scene_numbers(100, 100, 2.0, exaggeration=exaggeration)


class TestTheExaggerationComesFromTheBody:
    """`scene_numbers` used to import Earth's 15x. It is the block prep's seam too ("scene_numbers
    is the whole seam", its own docstring), and the block prep runs on both planets."""

    def test_the_scale_is_the_exaggeration_the_caller_passed(self):
        assert _unit_grid(15.0)["displacement_scale"] == 15.0
        assert _unit_grid(20.0)["displacement_scale"] == 20.0

    def test_mars_displaces_at_its_own_number_and_not_earths(self):
        """The instance this guard exists for: Earth's import gave a Mars block 15/20 of its
        displacement, which is a flatter planet rather than an error."""
        earth = _unit_grid(bodies.EARTH.exaggeration)
        mars = _unit_grid(bodies.MARS.exaggeration)
        assert earth["displacement_scale"] != mars["displacement_scale"]
        assert mars["displacement_scale"] / earth["displacement_scale"] == pytest.approx(
            bodies.MARS.exaggeration / bodies.EARTH.exaggeration)

    def test_the_hero_number_still_reaches_the_scene_through_earths_field(self):
        """The bridge the removed `render_prep.EXAGGERATION` leg used to be: Earth's heroes must
        keep rendering at the authored constant, now via the registry rather than an import."""
        assert bodies.EARTH.exaggeration == palette.EXAGGERATION

    def test_there_is_no_default_to_forget(self):
        with pytest.raises(TypeError):
            rp.scene_numbers(100, 100, 2.0)  # pyright: ignore[reportCallIssue]


# ---- frame.json's key order has one owner -----------------------------------

def _payload(**overrides):
    base = dict(body="earth", frame_lonlat=[0.0, 0.0, 1.0, 1.0], dst_crs="+proj=aea",
                width_px=100, height_px=100, xres_m=1.0, extent_w_m=100.0, extent_h_m=100.0,
                exaggeration=15.0, plane_height_units=2.0, ortho_scale=2.0,
                displacement_scale=1.0, res_x=7680, res_y=7680)
    return {**base, **overrides}


class TestFrameJsonHasOneWriter:
    """A frame that exists is never overwritten, so the only way to check a pin is to regenerate
    beside it and compare. Backfilling put a second writer beside this one."""

    def test_the_order_is_the_declared_one_whatever_order_it_is_built_in(self):
        shuffled = dict(reversed(list(_payload().items())))
        assert list(json.loads(rp.frame_json_text(shuffled))) == list(rp.FRAME_KEYS)

    def test_a_missing_key_is_refused_rather_than_written_as_null(self):
        short = _payload()
        del short["exaggeration"]
        with pytest.raises(ValueError, match="missing \\['exaggeration'\\]"):
            rp.frame_json_text(short)

    def test_an_unknown_key_is_refused_rather_than_carried(self):
        """A stray key makes a regenerated frame differ from its pin for a reason that has nothing
        to do with geometry, which is the harder failure to read."""
        with pytest.raises(ValueError, match="unknown \\['exagerration'\\]"):
            rp.frame_json_text(_payload(exagerration=15.0))

    def test_the_recorded_body_and_exaggeration_are_both_present(self):
        """`body` alone resolves to whatever that planet's exaggeration is TODAY, so a frame
        pinned before a change would silently claim the new value."""
        assert "body" in rp.FRAME_KEYS and "exaggeration" in rp.FRAME_KEYS
