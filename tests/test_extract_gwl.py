"""The GWL_FCS30 extraction keeps the saline class alone, bridges the strips the classifier left
across saline ground at a tile's north edge, and drops the saline cells WorldCover calls plants.

Offline: `bridged` is the pure half, and `main` runs against an archive of small synthetic tiles and
a WorldCover store of small synthetic tiles, its fetch stubbed.
"""

import zipfile

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import from_bounds

from pipeline import datasets, paths
from pipeline.acquire.earth import download_gwl, download_worldcover, extract_gwl

SALINE, NOT_WETLAND, WATER = extract_gwl.SALINE, extract_gwl.NOT_WETLAND, 180
#: WorldCover's classes, and 0 where it has none.
TREE, GRASS, BUILT, BARE, SNOW, OPEN_WATER, WETLAND, NO_CLASS = 10, 30, 50, 60, 70, 80, 90, 0


def _column(*classes: int) -> np.ndarray:
    return np.array(classes, np.uint8)[:, None]


class TestTheBridge:
    def test_unclassified_rows_between_saline_are_bridged(self):
        values = _column(NOT_WETLAND, NOT_WETLAND, NOT_WETLAND, SALINE, SALINE, SALINE)
        filled = extract_gwl.bridged(values, np.array([True]), deepest_row=4)
        assert filled[:, 0].tolist() == [True, True, True, False, False]

    def test_saline_starting_below_the_strip_is_ground_the_classifier_saw(self):
        values = _column(*[NOT_WETLAND] * 6, SALINE, SALINE)
        assert not extract_gwl.bridged(values, np.array([True]), deepest_row=4).any()

    def test_a_cell_the_classifier_called_water_stays_water(self):
        values = _column(NOT_WETLAND, WATER, NOT_WETLAND, SALINE, SALINE)
        filled = extract_gwl.bridged(values, np.array([True]), deepest_row=4)
        assert filled[:, 0].tolist() == [True, False, True, False, False]

    def test_nothing_is_bridged_without_saline_across_the_edge(self):
        values = _column(NOT_WETLAND, NOT_WETLAND, SALINE, SALINE, SALINE)
        assert not extract_gwl.bridged(values, np.array([False]), deepest_row=4).any()


def test_the_strips_were_measured_on_the_archive_the_pin_names():
    archive, measured_md5 = extract_gwl.STRIPS_MEASURED_ON
    assert download_gwl.ARCHIVES[archive][1] == measured_md5


SIDE = 16
NORTH, STRIP, EMPTY = "GWL_FCS30_2020_W70S15.tif", "GWL_FCS30_2020_W70S20.tif", "GWL_FCS30_2020_W70S30.tif"


def _tiles() -> dict[str, tuple[float, np.ndarray]]:
    """Three 5 degree tiles by their north edge: saline down to the south edge of the first across
    columns 2 to 5, a strip of three rows over the second's saline in columns 2 to 6 with one water
    cell in it, and a third holding none."""
    north = np.zeros((SIDE, SIDE), np.uint8)
    north[-1, 2:6] = SALINE
    strip = np.zeros((SIDE, SIDE), np.uint8)
    strip[3:, 2:7] = SALINE
    strip[1, 3] = WATER
    return {NORTH: (-15.0, north), STRIP: (-20.0, strip), EMPTY: (-30.0, np.zeros((SIDE, SIDE), np.uint8))}


@pytest.fixture
def fetched(monkeypatch) -> list[str]:
    """Every WorldCover tile the extraction asks for, fetched by nobody: the bucket answers 'absent'
    for whatever the test has not written into the store."""
    asked: list[str] = []

    def fetch_tiles(names, *, progress_every=0):
        asked.extend(names)
        return {"ok": 0, "skipped": len(names), "absent": 0}
    monkeypatch.setattr(download_worldcover, "fetch_tiles", fetch_tiles)
    return asked


@pytest.fixture
def store(monkeypatch, tmp_path, fetched):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr("sys.argv", ["extract_gwl"])
    datasets.gwl().mkdir(parents=True)
    archive = datasets.gwl() / extract_gwl.STRIPS_MEASURED_ON[0]
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, (north_edge, values) in _tiles().items():
            staged = tmp_path / name
            with rasterio.open(staged, "w", driver="GTiff", width=SIDE, height=SIDE, count=1,
                               dtype="uint8", crs="EPSG:4326",
                               transform=from_origin(-70.0, north_edge, 5 / SIDE, 5 / SIDE)) as sink:
                sink.write(values, 1)
            bundle.write(staged, name)
            staged.unlink()
    monkeypatch.setattr(download_gwl, "ARCHIVES", {archive.name: (archive.stat().st_size, "md5")})
    return tmp_path


def _through_the_vrt(north_edge: float) -> np.ndarray:
    with rasterio.open(extract_gwl.saline_vrt()) as mosaic:
        return mosaic.read(1, window=from_bounds(-70, north_edge - 5, -65, north_edge, mosaic.transform))


class TestAnExtraction:
    def test_the_vrt_holds_the_saline_class_with_the_strip_bridged(self, store):
        assert extract_gwl.main() == 0
        strip = _through_the_vrt(-20.0)
        assert strip[:3, 2].all() and strip[:3, 4:6].all()
        assert strip[1, 3] == 0 and strip[0, 3] == 1
        assert not strip[:3, 6].any()
        assert strip[3:, 2:7].all() and strip.sum() == 13 * 5 + 3 * 4 - 1
        assert _through_the_vrt(-15.0).sum() == 4

    def test_a_tile_without_saline_writes_nothing(self, store):
        extract_gwl.main()
        with rasterio.open(extract_gwl.saline_vrt()) as mosaic:
            indexed = sorted(name.rsplit("/", 1)[-1] for name in mosaic.files if name.endswith(".tif"))
        assert indexed == [NORTH, STRIP]
        assert not (extract_gwl.tile_dir() / EMPTY).exists()

    def test_a_second_run_under_the_same_recipe_writes_nothing(self, store):
        extract_gwl.main()
        stamps = {path: path.stat().st_mtime_ns for path in extract_gwl.tile_dir().parent.rglob("*")}
        extract_gwl.main()
        assert stamps == {path: path.stat().st_mtime_ns for path in extract_gwl.tile_dir().parent.rglob("*")}

    def test_a_changed_strip_makes_the_extraction_stale(self, monkeypatch, store):
        extract_gwl.main()
        monkeypatch.setitem(extract_gwl.STRIPS, STRIP, (NORTH, 1))
        assert not extract_gwl.is_fresh()

    def test_a_run_that_dies_leaves_the_extraction_stale_under_the_recipe_it_began_with(self, monkeypatch, store):
        """A rebuild that dies after rewriting tiles must not leave the old recipe vouching for them."""
        extract_gwl.main()
        began_with = dict(extract_gwl.STRIPS)
        monkeypatch.setitem(extract_gwl.STRIPS, STRIP, (NORTH, 1))

        def dies(_tiles):
            raise RuntimeError("killed")
        monkeypatch.setattr(extract_gwl, "build_vrt", dies)
        with pytest.raises(RuntimeError):
            extract_gwl.main()
        monkeypatch.setattr(extract_gwl, "STRIPS", began_with)
        assert not extract_gwl.is_fresh()

    def test_a_missing_archive_names_the_acquirer(self, monkeypatch, store):
        monkeypatch.setitem(download_gwl.ARCHIVES, "GWL_FCS30_2020_E0_E30.zip", (1, "md5"))
        with pytest.raises(SystemExit, match="download_gwl"):
            extract_gwl.main()


def _worldcover(lat: int, lon: int, classes: np.ndarray) -> None:
    """A WorldCover tile with this SW corner in the store, its 3 degrees split into `classes`' pixels."""
    rows, cols = classes.shape
    path = datasets.worldcover() / download_worldcover.tile_name(lat, lon)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=cols, height=rows, count=1, dtype="uint8",
                       crs="EPSG:4326", transform=from_origin(lon, lat + 3, 3 / cols, 3 / rows)) as sink:
        sink.write(classes, 1)


def _filled(code: int, side: int = 12) -> np.ndarray:
    return np.full((side, side), code, np.uint8)


#: The north tile's saline row. Column 2's centre lies west of 69°W, in the WorldCover tile at
#: 21°S 72°W, and columns 3 to 5 east of it, in the one at 21°S 69°W.
NORTH_ROW, WEST_CELL, EAST_CELLS = SIDE - 1, 2, slice(3, 6)


class TestTheWorldCoverFilter:
    """A saline cell stays saline where WorldCover calls the ground under its centre bare, snow and
    ice, or water, or names no class there."""

    @pytest.mark.parametrize("code", [TREE, GRASS, BUILT, WETLAND])
    def test_a_saline_cell_worldcover_calls_anything_else_is_dropped(self, store, code):
        _worldcover(-21, -72, _filled(BARE))
        _worldcover(-21, -69, _filled(code))
        extract_gwl.main()
        row = _through_the_vrt(-15.0)[NORTH_ROW]
        assert row[WEST_CELL] == 1 and not row[EAST_CELLS].any()

    @pytest.mark.parametrize("code", [BARE, SNOW, OPEN_WATER, NO_CLASS])
    def test_a_saline_cell_on_bare_ground_snow_water_or_no_class_stays(self, store, code):
        _worldcover(-21, -72, _filled(TREE))
        _worldcover(-21, -69, _filled(code))
        extract_gwl.main()
        row = _through_the_vrt(-15.0)[NORTH_ROW]
        assert row[WEST_CELL] == 0 and row[EAST_CELLS].all()

    def test_a_saline_cell_under_no_worldcover_tile_stays_saline(self, store):
        """The bucket has no tile for a cell of open sea."""
        _worldcover(-21, -72, _filled(TREE))
        extract_gwl.main()
        row = _through_the_vrt(-15.0)[NORTH_ROW]
        assert row[WEST_CELL] == 0 and row[EAST_CELLS].all()

    @pytest.mark.parametrize("centre, around, kept", [(BARE, TREE, 1), (TREE, BARE, 0)])
    def test_the_class_under_a_cells_centre_decides_it(self, store, centre, around, kept):
        """At 60 pixels to 3 degrees about 35 WorldCover pixels lie under a cell, so the one under its
        centre is outvoted by the rest."""
        side = 60
        classes = _filled(around, side)
        lon = -70 + (EAST_CELLS.start + 0.5) * 5 / SIDE
        lat = -15 - (NORTH_ROW + 0.5) * 5 / SIDE
        classes[int((-18 - lat) // (3 / side)), int((lon + 69) // (3 / side))] = centre
        _worldcover(-21, -69, classes)
        extract_gwl.main()
        assert _through_the_vrt(-15.0)[NORTH_ROW, EAST_CELLS.start] == kept

    def test_it_asks_for_exactly_the_worldcover_tiles_under_its_saline_cells(self, store, fetched):
        """The north tile's saline row lies south of 18°S and straddles 69°W, the strip's saline runs
        from 20°S to 25°S across 21°S and 24°S, and the empty tile asks for nothing."""
        extract_gwl.main()
        assert sorted(fetched) == sorted(download_worldcover.tile_name(lat, lon)
                                         for lat in (-21, -24, -27) for lon in (-72, -69))

    def test_a_tile_the_filter_empties_leaves_no_file_behind(self, store):
        extract_gwl.main()
        assert (extract_gwl.tile_dir() / NORTH).exists()
        _worldcover(-21, -72, _filled(TREE))
        _worldcover(-21, -69, _filled(TREE))
        extract_gwl.recipe_path().unlink()
        extract_gwl.main()
        assert not (extract_gwl.tile_dir() / NORTH).exists()
        assert (extract_gwl.tile_dir() / STRIP).exists()

    def test_a_changed_class_makes_the_extraction_stale(self, monkeypatch, store):
        extract_gwl.main()
        assert extract_gwl.is_fresh()
        monkeypatch.setattr(extract_gwl, "WORLDCOVER_KEEPS", {BARE: "bare or sparse vegetation"})
        assert not extract_gwl.is_fresh()

    def test_another_worldcover_edition_makes_the_extraction_stale(self, monkeypatch, store):
        extract_gwl.main()
        assert extract_gwl.is_fresh()
        monkeypatch.setattr(download_worldcover, "BUCKET_URL",
                            download_worldcover.BUCKET_URL.replace("v200", "v100"))
        assert not extract_gwl.is_fresh()
