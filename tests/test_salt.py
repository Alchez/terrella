"""Salt flats on a grid: each outline on its level floor, the lakes it holds, and the white it joins."""

import json
import subprocess

import numpy as np
import pytest
from rasterio.transform import from_origin

from pipeline import naturalearth, paths
from pipeline.look import salt

SIZE = 60
PIXEL_M = 100.0
TRANSFORM = from_origin(0.0, SIZE * PIXEL_M, PIXEL_M, PIXEL_M)
FLOOR_M = 1000.0


def square(col0: int, row0: int, col1: int, row1: int) -> dict:
    """A polygon on the fixture grid covering columns col0..col1-1 and rows row0..row1-1 exactly."""
    left, right = col0 * PIXEL_M, col1 * PIXEL_M
    top, bottom = (SIZE - row0) * PIXEL_M, (SIZE - row1) * PIXEL_M
    return {"type": "Polygon",
            "coordinates": [[(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)]]}


def region(rows: slice, cols: slice) -> np.ndarray:
    mask = np.zeros((SIZE, SIZE), bool)
    mask[rows, cols] = True
    return mask


OUTLINE = square(10, 10, 30, 30)
INSIDE = region(slice(10, 30), slice(10, 30))
HILL = region(slice(12, 16), slice(12, 16))
LAKE_MOSTLY_INSIDE = region(slice(20, 28), slice(24, 34))
LAKE_MOSTLY_OUTSIDE = region(slice(5, 13), slice(26, 41))
LAKE_APART = region(slice(45, 51), slice(45, 51))
WHITE_APART = region(slice(35, 39), slice(5, 9))
WHITE_ON_THE_OUTSIDE_LAKE = region(slice(6, 9), slice(36, 39))


def fixture_field():
    heightfield = np.full((SIZE, SIZE), FLOOR_M)
    heightfield[HILL] = FLOOR_M + 100.0
    lake = LAKE_MOSTLY_INSIDE | LAKE_MOSTLY_OUTSIDE | LAKE_APART
    gate = WHITE_APART | WHITE_ON_THE_OUTSIDE_LAKE
    return salt.field(heightfield, lake, TRANSFORM, [OUTLINE], gate)


class TestTheSaltOnAGrid:
    def test_the_outline_is_salt_on_its_level_floor_and_not_on_a_hill_inside_it(self):
        full, _gate = fixture_field()
        floor = INSIDE & ~HILL & ~LAKE_MOSTLY_OUTSIDE
        assert (full[floor] == 1.0).all()
        assert (full[HILL] == 0.0).all()

    def test_level_ground_outside_the_outline_is_not_salt(self):
        """The whole fixture is at the floor's height, so growing across level ground would take it."""
        full, _gate = fixture_field()
        outside = ~(INSIDE | LAKE_MOSTLY_INSIDE)
        assert (full[outside] == 0.0).all()

    def test_a_lake_lying_mostly_inside_the_outline_is_salt_whole_past_the_outline(self):
        full, _gate = fixture_field()
        assert (full[LAKE_MOSTLY_INSIDE] == 1.0).all()
        assert (LAKE_MOSTLY_INSIDE & ~INSIDE).any(), "the fixture's lake must reach past the outline"

    def test_a_lake_lying_mostly_outside_is_a_lake_even_where_the_outline_overlaps_it(self):
        """The Great Salt Lake Desert's outline brushes the Great Salt Lake: none of that is salt."""
        full, gate = fixture_field()
        assert (LAKE_MOSTLY_OUTSIDE & INSIDE).any(), "the fixture's lake must overlap the outline"
        assert (full[LAKE_MOSTLY_OUTSIDE] == 0.0).all()
        assert not gate[LAKE_MOSTLY_OUTSIDE].any()

    def test_a_lake_the_salt_does_not_touch_is_left_alone(self):
        full, _gate = fixture_field()
        assert (full[LAKE_APART] == 0.0).all()

    def test_the_connected_white_passes_through(self):
        _full, gate = fixture_field()
        assert gate[WHITE_APART].all()
        assert not gate[~(WHITE_APART | WHITE_ON_THE_OUTSIDE_LAKE)].any()

    def test_a_partly_covered_edge_pixel_is_partly_salt(self):
        half = {"type": "Polygon", "coordinates": [[(1000.0, 3000.0), (3050.0, 3000.0), (3050.0, 5000.0),
                                                    (1000.0, 5000.0), (1000.0, 3000.0)]]}
        full, _gate = salt.field(np.full((SIZE, SIZE), FLOOR_M), np.zeros((SIZE, SIZE), bool),
                                 TRANSFORM, [half], np.zeros((SIZE, SIZE), bool))
        assert 0.0 < full[20, 30] < 1.0


class TestTheWhiteConnectedToAnOutline:
    def test_a_white_component_touching_the_outline_is_kept_and_grown_one_cell(self):
        alpha = np.zeros((12, 12))
        alpha[2:4, 2:4] = 0.8
        alpha[4, 4] = 0.2                     # joined to the blob only across a corner
        alpha[8:10, 8:10] = 0.9               # white that no outline touches
        inside = np.zeros((12, 12), bool)
        inside[1:3, 1:3] = True
        kept = (alpha > 0) & ~region_small(slice(8, 10), slice(8, 10))
        expected = np.zeros((12, 12), bool)
        for row, col in zip(*np.nonzero(kept), strict=True):
            expected[max(0, row - 1):row + 2, max(0, col - 1):col + 2] = True
        np.testing.assert_array_equal(salt.white_cells(alpha, inside), expected)


def region_small(rows: slice, cols: slice) -> np.ndarray:
    mask = np.zeros((12, 12), bool)
    mask[rows, cols] = True
    return mask


class TestSaltTakesItsShareOfTheWhite:
    """The outcome, through the packed raster both tiers read."""

    CASES = (  # full, gate, white -> salt, snow
        (1.0, False, 1.0, 1.0, 0.0),
        (0.0, True, 1.0, 1.0, 0.0),
        (0.0, True, 0.3, 0.3, 0.0),
        (0.5, False, 1.0, 0.5, 0.5),
        (0.0, False, 0.8, 0.0, 0.8),
        (1.0, False, 0.0, 1.0, 0.0),
    )

    def test_each_case(self):
        full = np.array([case[0] for case in self.CASES])
        gate = np.array([case[1] for case in self.CASES])
        white = np.array([case[2] for case in self.CASES])
        snow_left, salt_alpha = salt.take(white, salt.pack(full, gate))
        tolerance = 1.0 / salt.FULL_LEVELS
        np.testing.assert_allclose(salt_alpha, [case[3] for case in self.CASES], atol=tolerance)
        np.testing.assert_allclose(snow_left, [case[4] for case in self.CASES], atol=tolerance)

    def test_the_packing_round_trips(self):
        full = np.linspace(0.0, 1.0, 50)
        gate = np.arange(50) % 3 == 0
        got_full, got_gate = salt.unpack(salt.pack(full, gate))
        np.testing.assert_allclose(got_full, full, atol=1.0 / (2 * salt.FULL_LEVELS))
        np.testing.assert_array_equal(got_gate, gate)


class TestTheOutlinesAreNaturalEarths:
    def test_every_polygon_in_the_layer_is_read_in_lon_lat(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "DATA", tmp_path)
        path = naturalearth.layer(salt.LAYER)
        path.parent.mkdir(parents=True)
        salar = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {
            "type": "Polygon", "coordinates": [[[-68.0, -20.0], [-67.0, -20.0], [-67.0, -19.5],
                                                [-68.0, -19.5], [-68.0, -20.0]]]}}]}
        subprocess.run(["ogr2ogr", "-f", "ESRI Shapefile", str(path), "/vsistdin/"],
                       input=json.dumps(salar), text=True, check=True)
        (outline,) = salt.outlines()
        assert outline["type"] == "Polygon"
        lons = [point[0] for point in outline["coordinates"][0]]
        assert min(lons) == pytest.approx(-68.0) and max(lons) == pytest.approx(-67.0)
