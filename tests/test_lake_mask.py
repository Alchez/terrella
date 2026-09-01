"""The hero lake-depth stage's pure core: depth metres + watermask -> ramp position.

`lake_mask.depth_to_position` composes the two shared single-home implementations
(`lake_depth.lakes_only` for the class gate, `shade.lake_position` for the curve), so
these tests pin the composition — the gating, the range contract, the log1p endpoints
the tile side documents, and the "off" A/B carry-over — not the internals, which have
their own suites (test_lake_depth, test_shade-side coverage).
"""

import numpy as np
import pytest

from pipeline.render.lake_mask import depth_to_position
from pipeline.tile import shade


@pytest.fixture(autouse=True)
def restore_lake_curve(monkeypatch):
    """`LAKE_CURVE` is a module constant now, not a key in a dict this file mutated in place.

    The fixture stays because the "off" control below still has to set it, and a leaked value would
    silently flatten every later test's water.
    """
    monkeypatch.setattr(shade, "LAKE_CURVE", shade.LAKE_CURVE)


def position_of(depth_metres, watercode=2):
    depth = np.full((1, 1), depth_metres, dtype=np.float32)
    codes = np.full((1, 1), watercode, dtype=np.uint8)
    return float(depth_to_position(depth, codes)[0, 0])


class TestClassGating:
    def test_only_lakes_get_depth(self):
        """Class 2 ramps; class 3 (river, no bed data) and class 1 (ocean/Caspian,
        GEBCO's bathymetry) must stay at position 0 whatever GLOBathy claims."""
        depth = np.full((1, 4), 100.0, dtype=np.float32)
        codes = np.array([[0, 1, 2, 3]], dtype=np.uint8)
        position = depth_to_position(depth, codes)
        assert position[0, 2] > 0.0
        assert position[0, 0] == position[0, 1] == position[0, 3] == 0.0


class TestCurve:
    def test_output_stays_in_ramp_range(self):
        depths = np.linspace(0.0, 5000.0, 64, dtype=np.float32).reshape(8, 8)
        codes = np.full((8, 8), 2, dtype=np.uint8)
        position = depth_to_position(depths, codes)
        assert float(position.min()) == 0.0
        assert float(position.max()) <= 1.0

    def test_log1p_endpoints(self):
        """Zero depth is the shore tint (position 0), Baikal is the ramp's far end,
        and the median lake (11.2 m) lands ≈ 0.34 — the documented log1p spread."""
        assert position_of(0.0) == 0.0
        assert position_of(1642.0) == pytest.approx(1.0)
        assert position_of(11.2) == pytest.approx(0.34, abs=0.01)

    def test_off_curve_is_flat_water(self, monkeypatch):
        """The flat-water A/B control carries over: "off" -> all zeros -> the
        scene's ColorRamp emits exactly the flat WATER_RGB everywhere."""
        monkeypatch.setattr(shade, "LAKE_CURVE", "off")
        assert position_of(1642.0) == 0.0

    def test_dtype_is_float32(self):
        depth = np.full((2, 2), 50.0, dtype=np.float32)
        codes = np.full((2, 2), 2, dtype=np.uint8)
        assert depth_to_position(depth, codes).dtype == np.float32
