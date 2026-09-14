"""Salt flats on a grid: each outline and each saline patch on its level floor, the lakes they hold,
and the white they join."""

import json
import subprocess

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from rasterio.warp import transform as warp_points

from pipeline import naturalearth, paths
from pipeline.acquire.earth import extract_gwl
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
NO_PATCHES = (np.zeros((SIZE, SIZE)), np.zeros((SIZE, SIZE), bool))
NO_GATE = np.zeros((SIZE, SIZE), bool)
LEVEL = np.full((SIZE, SIZE), FLOOR_M)


def fixture_field():
    heightfield = np.full((SIZE, SIZE), FLOOR_M)
    heightfield[HILL] = FLOOR_M + 100.0
    lake = LAKE_MOSTLY_INSIDE | LAKE_MOSTLY_OUTSIDE | LAKE_APART
    gate = WHITE_APART | WHITE_ON_THE_OUTSIDE_LAKE
    return salt.field(heightfield, lake, TRANSFORM, [OUTLINE], NO_PATCHES, gate)


def patches_of(share: np.ndarray, heightfield: np.ndarray = LEVEL) -> tuple[np.ndarray, np.ndarray]:
    paint, cells, _on_floor = salt.patch_field(share, heightfield)
    return paint, cells


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
        full, _gate = salt.field(LEVEL, np.zeros((SIZE, SIZE), bool), TRANSFORM, [half], NO_PATCHES,
                                 NO_GATE)
        assert 0.0 < full[20, 30] < 1.0


class TestASalinePatchOnAGrid:
    """A patch is 8-connected ground where GWL_FCS30's saline share reaches `salt.PATCH_SHARE`."""

    @staticmethod
    def share() -> np.ndarray:
        """One patch at 0.9, a row of 0.3 along its top, and a row of 0.3 two cells above that."""
        share = np.zeros((SIZE, SIZE))
        share[20:30, 20:30] = 0.9
        share[19, 20:30] = 0.3
        share[17, 20:30] = 0.3
        return share

    def test_a_patch_on_its_floor_is_painted_at_its_share_with_a_one_cell_rim(self):
        paint, cells, _on_floor = salt.patch_field(self.share(), LEVEL)
        np.testing.assert_allclose(paint[20:30, 20:30], 0.9)
        np.testing.assert_allclose(paint[19, 20:30], 0.3)
        assert not paint[17].any()
        assert cells[20:30, 20:30].all() and not cells[19].any()

    def test_a_patch_is_not_salt_on_a_hill_inside_it_and_the_white_joins_it_off_its_floor_only(self):
        heightfield = LEVEL.copy()
        heightfield[22:24, 22:24] = FLOOR_M + 100.0
        paint, _cells, on_floor = salt.patch_field(self.share(), heightfield)
        assert not paint[22:24, 22:24].any() and not on_floor[22:24, 22:24].any()
        assert on_floor[25:30, 25:30].all()

    def test_each_patch_stands_on_its_own_floor(self):
        share = np.zeros((SIZE, SIZE))
        share[5:10, 5:10] = 1.0
        share[40:45, 40:45] = 1.0
        heightfield = LEVEL.copy()
        heightfield[35:50, 35:50] = FLOOR_M + 500.0
        paint, _cells, _on_floor = salt.patch_field(share, heightfield)
        assert (paint[5:10, 5:10] == 1.0).all() and (paint[40:45, 40:45] == 1.0).all()


class TestAPatchTakesTheLakeStepAnOutlineTakes:
    LAKE = region(slice(40, 50), slice(40, 50))

    def test_a_lake_a_patch_mostly_holds_is_salt_whole(self):
        share = np.zeros((SIZE, SIZE))
        share[40:50, 40:46] = 1.0
        full, _gate = salt.field(LEVEL, self.LAKE, TRANSFORM, [], patches_of(share), NO_GATE)
        assert (full[self.LAKE] == 1.0).all()

    def test_a_lake_a_patch_only_brushes_is_a_lake_under_the_patch_as_well(self):
        share = np.zeros((SIZE, SIZE))
        share[40:50, 40:43] = 1.0
        gate = self.LAKE.copy()
        full, got_gate = salt.field(LEVEL, self.LAKE, TRANSFORM, [], patches_of(share), gate)
        assert (full[self.LAKE] == 0.0).all() and not got_gate[self.LAKE].any()

    def test_an_outline_and_a_patch_holding_a_lake_between_them_make_it_salt(self):
        """Each holds 30% of the lake, which neither would turn alone."""
        share = np.zeros((SIZE, SIZE))
        share[40:50, 47:50] = 1.0
        full, _gate = salt.field(LEVEL, self.LAKE, TRANSFORM, [square(40, 40, 43, 50)], patches_of(share),
                                 NO_GATE)
        assert (full[self.LAKE] == 1.0).all()


class TestTheWhiteJoinsFromOutlinesAndPatches:
    def test_a_patch_cell_marks_the_snow_cell_holding_it(self):
        """One 100 m cell of a 20 km Mercator grid, at 10.0229 E, 0.0663 N, lands in the 0.01 degree
        cell holding it. The grid spans many target cells because GDAL landed nothing from a 400 m
        one."""
        seed = np.zeros((200, 200), bool)
        seed[37, 25] = True
        mercator = from_origin(1_113_195.0, 11_132.0, 100.0, 100.0)
        ground = salt.ground_on([], (seed, mercator, "EPSG:3857"), from_origin(9.99, 0.11, 0.01, 0.01),
                                (22, 22))
        assert ground[4, 3] and ground.sum() == 1

    def test_an_outline_is_burnt_as_it_was(self):
        outline = {"type": "Polygon", "coordinates": [[(10.0, 0.0), (10.02, 0.0), (10.02, 0.05),
                                                       (10.0, 0.05), (10.0, 0.0)]]}
        ground = salt.ground_on([outline], None, from_origin(10.0, 0.05, 0.01, 0.01), (5, 5))
        assert ground[:, :2].all() and not ground[:, 2:].any()


TILE_PX = 100
TILE_DEG = 5.0
PLANET_PX_M = 20_000.0
PLANET = Affine(PLANET_PX_M, 0.0, -111_319.49, 0.0, -PLANET_PX_M, 111_325.14)
PLANET_SHAPE = (45, 67)


def tile_cells(west: float, north: float, lon: tuple[float, float], lat: tuple[float, float]) -> np.ndarray:
    """A tile's 0/1 saline cells, saline over a lon/lat box."""
    cell = TILE_DEG / TILE_PX
    cols = np.arange(TILE_PX) * cell + west + cell / 2
    rows = north - np.arange(TILE_PX) * cell - cell / 2
    return ((rows[:, None] >= lat[0]) & (rows[:, None] <= lat[1])
            & (cols[None, :] >= lon[0]) & (cols[None, :] <= lon[1])).astype(np.uint8)


def planet_lonlat() -> tuple[np.ndarray, np.ndarray]:
    """Each planet cell's centre, lon and lat."""
    rows, cols = np.mgrid[0:PLANET_SHAPE[0], 0:PLANET_SHAPE[1]]
    x, y = PLANET.c + (cols + 0.5) * PLANET.a, PLANET.f + (rows + 0.5) * PLANET.e
    return np.degrees(x / 6_378_137.0), np.degrees(2 * np.arctan(np.exp(y / 6_378_137.0)) - np.pi / 2)


class TestThePlanetBakeHoldsEveryPatchAndOutlineWhole:
    """Two saline tiles side by side, 0 to 5 E and 5 to 10 E, 5 S to the equator, on a 20 km grid
    whose windows start two cells past a tile, so the tile to the east sees only part of what
    reaches it from the west."""

    LAT = (-3.0, -2.0)

    @pytest.fixture
    def store(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "DATA", tmp_path)
        monkeypatch.setattr(salt, "PLANET_MARGIN_PX", 2)
        monkeypatch.setattr(salt, "outlines", list)
        monkeypatch.setattr(salt, "connected_white", lambda bounds, geometries, seed=None:
                            (np.zeros((4, 4), bool), from_origin(0.0, 0.0, 0.01, 0.01)))
        extract_gwl.tile_dir().mkdir(parents=True)
        names = []
        for west in (0.0, 5.0):
            name = extract_gwl.tile_dir() / f"tile_{west:.0f}.tif"
            with rasterio.open(name, "w", driver="GTiff", width=TILE_PX, height=TILE_PX, count=1,
                               dtype="uint8", crs="EPSG:4326",
                               transform=from_origin(west, 0.0, TILE_DEG / TILE_PX, TILE_DEG / TILE_PX)) as sink:
                sink.write(tile_cells(west, 0.0, (1.0, 8.0), self.LAT), 1)
            names.append(str(name))
        subprocess.run(["gdalbuildvrt", "-q", str(extract_gwl.saline_vrt()), *names], check=True)
        return tmp_path

    @staticmethod
    def bake(tmp_path, heightfield: np.ndarray) -> np.ndarray:
        rasters = {}
        for name, array in (("height", heightfield.astype(np.float32)),
                            ("water", np.zeros(PLANET_SHAPE, np.uint8))):
            rasters[name] = tmp_path / f"{name}_3857.tif"
            with rasterio.open(rasters[name], "w", driver="GTiff", width=PLANET_SHAPE[1],
                               height=PLANET_SHAPE[0], count=1, dtype=array.dtype, crs="EPSG:3857",
                               transform=PLANET) as sink:
                sink.write(array, 1)
        out = tmp_path / "salt_3857.tif"
        left, top = PLANET.c, PLANET.f
        bounds = (left, top - PLANET_SHAPE[0] * PLANET_PX_M, left + PLANET_SHAPE[1] * PLANET_PX_M, top)
        salt.build_planet(bounds, PLANET_SHAPE[1], PLANET_SHAPE[0], out, rasters["height"], rasters["water"])
        with rasterio.open(out) as baked:
            full, _gate = salt.unpack(baked.read(1))
        return full

    def test_a_patch_split_between_two_tiles_stands_on_the_floor_of_all_of_it(self, store):
        """Most of the patch lies at 1000 m; its east end at 1015 m is off that floor, though it is
        most of what the eastern tile's window first sees."""
        lon, lat = planet_lonlat()
        band = (lat > self.LAT[0]) & (lat < self.LAT[1])
        heightfield = np.where(band & (lon >= 5.5), FLOOR_M + 15.0, FLOOR_M)
        full = self.bake(store, heightfield)
        whole_cells = (lat > self.LAT[0] + 0.2) & (lat < self.LAT[1] - 0.2)
        assert (full[whole_cells & (lon > 1.5) & (lon < 5.0)] > 0.9).all()
        assert (full[band & (lon > 5.8)] == 0.0).all()

    def test_an_outline_a_tile_window_cuts_stands_on_the_floor_of_all_of_it(self, monkeypatch, store):
        """The outline's west two thirds lie at 1000 m and its east third at 1015 m, and the
        eastern tile's window first sees mostly the east third, which paints nothing at its edge."""
        lon, lat = planet_lonlat()
        outline_lat = (-4.6, -3.6)
        outline = {"type": "Polygon", "coordinates": [[(2.0, outline_lat[0]), (7.0, outline_lat[0]),
                                                       (7.0, outline_lat[1]), (2.0, outline_lat[1]),
                                                       (2.0, outline_lat[0])]]}
        monkeypatch.setattr(salt, "outlines", lambda: [outline])
        band = (lat > outline_lat[0]) & (lat < outline_lat[1])
        heightfield = np.where(band & (lon >= 5.2), FLOOR_M + 15.0, FLOOR_M)
        full = self.bake(store, heightfield)
        assert (full[band & (lon > 2.5) & (lon < 5.0)] > 0.9).all()
        assert (full[band & (lon > 5.5) & (lon < 7.0)] == 0.0).all()


class TestTheShareIsEachTilesOwn:
    """Two tiles like GWL_FCS30's, whose cells fall short of 5 degrees, so no one grid holds both."""

    CELL_DEG = 0.0499

    def tile(self, west: float, cells: np.ndarray) -> str:
        path = extract_gwl.tile_dir() / f"tile_{west:.0f}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=TILE_PX, height=TILE_PX, count=1, dtype="uint8",
                           crs="EPSG:4326", transform=from_origin(west, 0.0, self.CELL_DEG, self.CELL_DEG)) as sink:
            sink.write(cells, 1)
        return str(path)

    def test_a_cell_inside_a_tile_takes_that_tiles_own_average(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "DATA", tmp_path)
        extract_gwl.tile_dir().mkdir(parents=True)
        stripes = np.zeros((TILE_PX, TILE_PX), np.uint8)
        stripes[:, ::3] = 1
        names = [self.tile(0.0, stripes), self.tile(5.0, stripes)]
        subprocess.run(["gdalbuildvrt", "-q", str(extract_gwl.saline_vrt()), *names], check=True)
        grid = from_origin(5.5, -0.5, 0.13, 0.13)
        share = salt.saline_share("EPSG:4326", grid, (30, 30), salt.saline_tiles())
        own = np.zeros((30, 30), np.float32)
        with rasterio.open(names[1]) as source:
            reproject(rasterio.band(source, 1), own, dst_transform=grid, dst_crs="EPSG:4326",
                      resampling=Resampling.average)
        np.testing.assert_allclose(share, own, atol=1e-6)

    def test_a_cell_across_the_sliver_between_two_tiles_is_not_lost(self, monkeypatch, tmp_path):
        """The west tile ends 0.01 degrees short of 5 E; a cell centred in that sliver belongs to it."""
        monkeypatch.setattr(paths, "DATA", tmp_path)
        extract_gwl.tile_dir().mkdir(parents=True)
        full = np.ones((TILE_PX, TILE_PX), np.uint8)
        names = [self.tile(0.0, full), self.tile(5.0, full)]
        subprocess.run(["gdalbuildvrt", "-q", str(extract_gwl.saline_vrt()), *names], check=True)
        grid = from_origin(4.895, -1.0, 0.2, 0.2)     # column 0 centres at 4.995, inside the sliver
        share = salt.saline_share("EPSG:4326", grid, (5, 3), salt.saline_tiles())
        assert (share > 0.9).all()


class TestAHeroGridPaintsThePatches:
    def test_a_grid_no_outline_reaches_paints_the_patch_on_it(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "DATA", tmp_path)
        monkeypatch.setattr(salt, "outlines", list)
        monkeypatch.setattr(salt, "connected_white", lambda bounds, geometries, seed=None:
                            (np.zeros((4, 4), bool), from_origin(0.0, 0.0, 0.01, 0.01)))
        extract_gwl.tile_dir().mkdir(parents=True)
        tile = extract_gwl.tile_dir() / "tile.tif"
        with rasterio.open(tile, "w", driver="GTiff", width=TILE_PX, height=TILE_PX, count=1, dtype="uint8",
                           crs="EPSG:4326", transform=from_origin(0.0, 0.0, TILE_DEG / TILE_PX,
                                                                  TILE_DEG / TILE_PX)) as sink:
            sink.write(tile_cells(0.0, 0.0, (1.0, 4.0), (-3.0, -2.0)), 1)
        subprocess.run(["gdalbuildvrt", "-q", str(extract_gwl.saline_vrt()), str(tile)], check=True)
        # A UTM grid, 10 km cells, over 0.5 to 4.5 E and 4 S to 1 S.
        transform = Affine(10_000.0, 0.0, 222_000.0, 0.0, -10_000.0, 9_890_000.0)
        shape = (34, 45)
        full, _gate = salt.unpack(salt.land(np.full(shape, FLOOR_M), np.zeros(shape, np.uint8),
                                            "EPSG:32731", transform))
        point = warp_points("EPSG:4326", "EPSG:32731", [2.5], [-2.5])
        row, col = int((point[1][0] - transform.f) / transform.e), int((point[0][0] - transform.c) / transform.a)
        assert full[row, col] > 0.9


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
