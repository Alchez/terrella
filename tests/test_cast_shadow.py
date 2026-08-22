"""Tests for the directional cast-shadow term, against an ANALYTIC oracle.

A shadow map is exactly the kind of output that looks plausible while being wrong — it is grey
where you expect grey, and a 90-degree azimuth error or a dropped exaggeration still produces a
convincing-looking picture. So nothing here compares against a stored raster or an eyeballed
crop. Every assertion is checked against geometry computable by hand:

    relief of h metres, exaggerated by z, standing on a grid of m metres per pixel, lit from
    altitude a, casts its shadow z*h / tan(a) / m pixels along the ground

and the penumbra spans exactly SUN_ANGULAR_DIAMETER degrees about a, because that is how long
the horizon takes to cross the sun's disc.

Per the recurring-bug rule (PLAN, "the one recurring bug is testing a PROXY"), each property has
a companion that shows the check can FAIL: a sun that never moves, an exaggeration that is
ignored, or a reach that never truncates would all produce a shadow map that passes a naive
"is it shadowed near the wall" test.
"""

import math

import numpy as np
import pytest

from pipeline.look.cast_shadow import (
    SUN_ANGULAR_DIAMETER,
    shadow_mask,
    shadow_reach_px,
    sun_offsets,
)

M_PER_PX = 305.7483   # the z8 grid, so the numbers here are production-scale
ZFACTOR = 15.0        # the locked hero exaggeration
WALL_HEIGHT = 2000.0  # casts ~98 px at a 45-degree sun — long enough to resolve a penumbra
WALL_COLUMN = 150
WIDTH = 600           # > WALL_COLUMN + reach, so np.roll's wrap never reaches the wall


def wall_grid(rows: int = 1) -> np.ndarray:
    """Flat ground with one infinitely long wall — the geometry the oracle is written for."""
    heights = np.zeros((rows, WIDTH), dtype=np.float32)
    heights[:, WALL_COLUMN] = WALL_HEIGHT
    return heights


def oracle_shadow_px(altitude_deg: float, zfactor: float = ZFACTOR) -> float:
    """Ground distance, in pixels, at which the wall's horizon sits exactly at `altitude_deg`."""
    return zfactor * WALL_HEIGHT / math.tan(math.radians(altitude_deg)) / M_PER_PX


def lit_distance(mask: np.ndarray) -> int:
    """Distance in pixels from the wall to the first fully-lit pixel east of it."""
    east = mask[0, WALL_COLUMN + 1:]
    lit = np.flatnonzero(east == 0.0)
    return int(lit[0]) + 1


class TestSunDirection:
    """The compass convention is the one thing a plausible-looking output cannot reveal."""

    @pytest.mark.parametrize("azimuth, expected", [
        (0.0, (-1.0, 0.0)),     # light from the north -> march up the raster
        (90.0, (0.0, 1.0)),     # from the east -> march right
        (180.0, (1.0, 0.0)),    # from the south -> march down
        (270.0, (0.0, -1.0)),   # from the west -> march left
    ])
    def test_cardinal_offsets(self, azimuth: float, expected: tuple[float, float]):
        row_step, column_step = sun_offsets(azimuth)
        assert row_step == pytest.approx(expected[0], abs=1e-12)
        assert column_step == pytest.approx(expected[1], abs=1e-12)

    def test_production_azimuth_marches_northwest(self):
        row_step, column_step = sun_offsets(315.0)
        assert row_step < 0 and column_step < 0          # up and to the left
        assert row_step == pytest.approx(column_step)    # exactly diagonal

    def test_shadow_falls_away_from_the_sun(self):
        """Can-fail companion: a sign error puts the shadow on the sunward side of the wall."""
        mask = shadow_mask(wall_grid(), ZFACTOR, M_PER_PX, azimuth=270.0)
        assert mask[0, WALL_COLUMN + 5] == 1.0   # east of the wall, away from a western sun
        assert mask[0, WALL_COLUMN - 5] == 0.0   # west of it, facing the sun


class TestAnalyticWall:
    """Shadow extent and penumbra against hand-computed geometry."""

    def test_umbra_reaches_the_predicted_distance(self):
        mask = shadow_mask(wall_grid(), ZFACTOR, M_PER_PX, altitude=45.0, azimuth=270.0)
        # Fully occluded while the horizon sits a half-disc ABOVE the sun.
        umbra = int(oracle_shadow_px(45.0 + SUN_ANGULAR_DIAMETER / 2.0))
        assert np.all(mask[0, WALL_COLUMN + 1:WALL_COLUMN + 1 + umbra] == 1.0)

    def test_fully_lit_beyond_the_predicted_penumbra(self):
        mask = shadow_mask(wall_grid(), ZFACTOR, M_PER_PX, altitude=45.0, azimuth=270.0)
        # Fully lit once the horizon has dropped a half-disc BELOW the sun.
        penumbra_end = math.ceil(oracle_shadow_px(45.0 - SUN_ANGULAR_DIAMETER / 2.0))
        assert np.all(mask[0, WALL_COLUMN + 1 + penumbra_end:] == 0.0)

    def test_penumbra_is_soft_and_monotonic(self):
        mask = shadow_mask(wall_grid(), ZFACTOR, M_PER_PX, altitude=45.0, azimuth=270.0)
        umbra = int(oracle_shadow_px(45.0 + SUN_ANGULAR_DIAMETER / 2.0))
        penumbra_end = math.ceil(oracle_shadow_px(45.0 - SUN_ANGULAR_DIAMETER / 2.0))
        band = mask[0, WALL_COLUMN + 1 + umbra:WALL_COLUMN + 1 + penumbra_end]
        assert np.all(np.diff(band) <= 0)              # never brightens back up
        assert np.any((band > 0.0) & (band < 1.0))     # a real gradient, not a hard step

    def test_rows_do_not_wrap(self):
        """The north pole must not shadow the south pole — rows edge-replicate, columns wrap.

        Can-fail companion for the axis-0 `np.roll` this replaced: with a tall wall on the LAST
        row and a sun from the north, a vertical wrap would shadow the FIRST rows from below.
        """
        heights = np.zeros((60, WIDTH), dtype=np.float32)
        heights[-1, :] = WALL_HEIGHT
        mask = shadow_mask(heights, ZFACTOR, M_PER_PX, azimuth=180.0, reach_px=40)
        assert np.all(mask[:5] == 0.0)

    def test_columns_still_wrap(self):
        """The planet IS cyclic in longitude, so the column wrap is a feature, not an oversight."""
        heights = np.zeros((1, WIDTH), dtype=np.float32)
        heights[0, -1] = WALL_HEIGHT
        mask = shadow_mask(heights, ZFACTOR, M_PER_PX, azimuth=270.0, reach_px=40)
        # Column 0 marches west, off the raster, and must land on the last column's wall.
        assert mask[0, 0] == 1.0

    def test_flat_ground_casts_nothing(self):
        """Can-fail companion: an off-by-one that compared a pixel with itself would shadow here."""
        mask = shadow_mask(np.zeros((4, WIDTH), dtype=np.float32), ZFACTOR, M_PER_PX,
                           azimuth=270.0)
        assert np.all(mask == 0.0)


class TestLeversActuallyMove:
    """Each production lever, shown to change the output in the direction geometry demands."""

    # These ratios stay inside the default `reach_px`. Geometry that overruns it is tested
    # deliberately in `test_reach_truncates_the_march`, not stumbled into here — a truncated
    # shadow would otherwise read as a broken lever rather than a working one.

    def test_a_higher_sun_shortens_the_shadow(self):
        low = shadow_mask(wall_grid(), ZFACTOR, M_PER_PX, altitude=40.0, azimuth=270.0)
        high = shadow_mask(wall_grid(), ZFACTOR, M_PER_PX, altitude=60.0, azimuth=270.0)
        assert lit_distance(high) < lit_distance(low)
        # and by the predicted RATIO, not merely in the right direction
        assert lit_distance(low) / lit_distance(high) == pytest.approx(
            oracle_shadow_px(40.0 - SUN_ANGULAR_DIAMETER / 2.0)
            / oracle_shadow_px(60.0 - SUN_ANGULAR_DIAMETER / 2.0), rel=0.05)

    def test_exaggeration_lengthens_the_shadow_proportionally(self):
        gentle = shadow_mask(wall_grid(), ZFACTOR / 3.0, M_PER_PX, azimuth=270.0)
        exaggerated = shadow_mask(wall_grid(), ZFACTOR, M_PER_PX, azimuth=270.0)
        assert lit_distance(exaggerated) / lit_distance(gentle) == pytest.approx(3.0, rel=0.05)

    def test_per_row_zfactor_broadcasts(self):
        """The Mercator correction is a column vector; each row must shadow by its own z."""
        zfactor = np.array([[ZFACTOR / 2.0], [ZFACTOR]], dtype=np.float32)
        mask = shadow_mask(wall_grid(rows=2), zfactor, M_PER_PX, azimuth=270.0)
        near = np.flatnonzero(mask[0, WALL_COLUMN + 1:] == 0.0)[0] + 1
        far = np.flatnonzero(mask[1, WALL_COLUMN + 1:] == 0.0)[0] + 1
        assert far / near == pytest.approx(2.0, rel=0.05)

    def test_reach_truncates_the_march(self):
        """Can-fail companion: `reach_px` is a real cost lever, so it must really cut shadows off."""
        truncated = shadow_mask(wall_grid(), ZFACTOR, M_PER_PX, azimuth=270.0, reach_px=20)
        assert np.all(truncated[0, WALL_COLUMN + 21:] == 0.0)
        assert truncated[0, WALL_COLUMN + 20] == 1.0     # still shadowed right up to the cut
        assert shadow_mask(wall_grid(), ZFACTOR, M_PER_PX, azimuth=270.0, reach_px=0).max() == 0.0

    def test_default_reach_covers_the_production_case(self):
        """The default must not silently truncate the terrain it will actually meet."""
        everest_exaggerated = shadow_reach_px(8849.0, ZFACTOR, M_PER_PX, altitude=45.0)
        assert everest_exaggerated == pytest.approx(434.0, abs=1.0)
        # 200 is deliberately below that: the sizing helper exists so the truncation is a CHOICE.
        assert shadow_reach_px(WALL_HEIGHT, ZFACTOR, M_PER_PX, 45.0) == pytest.approx(
            oracle_shadow_px(45.0), rel=1e-6)


class TestOutputContract:
    """Shape and dtype, so this stays a drop-in multiplier for the main hillshade."""

    def test_shape_and_dtype_preserved(self):
        mask = shadow_mask(wall_grid(rows=3), ZFACTOR, M_PER_PX)
        assert mask.shape == (3, WIDTH)
        assert mask.dtype == np.float32

    def test_range_is_a_fraction(self):
        mask = shadow_mask(wall_grid(rows=3), ZFACTOR, M_PER_PX)
        assert mask.min() >= 0.0 and mask.max() <= 1.0
