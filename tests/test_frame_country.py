"""Tests for pad_frame — the frame padding + world-clamp math.

The world-clamp is the antimeridian guard: an island near ±180 must not pad
past the edge (Tuvalu 179.9 → 180.1 would cross). A silent failure here yields
a frame that can't fuse, so these are the highest-value regressions in the suite.
"""
import pytest

from pipeline.frame.frame_country import pad_frame


def test_pad_frame_normal_country_rounds_outward():
    # span = max(8, 4) = 8; pad = 5% * 8 = 0.4, rounded outward to 0.1°
    assert pad_frame((80.0, 26.0, 88.0, 30.0), 5.0) == (79.6, 25.6, 88.4, 30.4)


def test_pad_frame_pads_by_the_larger_span():
    # tall, narrow bbox: span = max(2, 20) = 20; pad = 5% * 20 = 1.0
    assert pad_frame((10.0, 0.0, 12.0, 20.0), 5.0) == (9.0, -1.0, 13.0, 21.0)


def test_pad_frame_clamps_east_at_antimeridian():
    # Tuvalu-like: island near 179.9°E; the pad would push east to 180.1°
    frame = pad_frame((179.0, -9.5, 179.9, -5.5), 5.0)
    assert frame == (178.8, -9.7, 180.0, -5.3)
    assert frame[2] == 180.0  # east clamped, not 180.1


def test_pad_frame_clamps_all_world_edges():
    west, south, east, north = pad_frame((-179.95, -89.95, 179.95, 89.95), 5.0)
    assert (west, south, east, north) == (-180.0, -90.0, 180.0, 90.0)


@pytest.mark.parametrize("bbox", [
    (-179.0, -89.0, 179.0, 89.0),
    (170.0, 80.0, 179.9, 89.9),
    (-100.0, -50.0, -90.0, -40.0),
    (0.0, 0.0, 1.0, 1.0),
])
@pytest.mark.parametrize("pad_pct", [0.0, 5.0, 15.0, 50.0])
def test_pad_frame_never_escapes_the_world(bbox, pad_pct):
    west, south, east, north = pad_frame(bbox, pad_pct)
    assert -180.0 <= west < east <= 180.0
    assert -90.0 <= south < north <= 90.0
