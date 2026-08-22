"""`snow.rasterize_antarctic_rock`: SCAR ADD's outcrop burnt onto the Mercator grid.

DRIVES THE REAL `gdal_rasterize`, on `test_vector_raster.py`'s argument: the defects here are GDAL
behaviours — a burn that draws nothing and exits 0, a `-l` that names a layer the file does not have
— so a mocked subprocess would test the mock's opinion of GDAL. Every fixture is synthetic and lives
in `tmp_path`, so the file passes under `MAPS_DATA=<empty dir>` exactly as CI runs it.

AN EMPTY BURN IS THE ONE FAILURE NOTHING DOWNSTREAM CAN SEE, which is why it raises here rather than
being left to a caller. `antarctic_snow_mask` subtracts this mask from a rule that already covers the
whole continent, so a raster of zeros is not a visibly broken layer: it is precisely the look that
shipped before this layer existed, over every pixel of Antarctica, with nothing missing from any
output and no consumer able to tell it from "there is no exposed rock".
"""

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
import rasterio

from pipeline import vector_raster
from pipeline.look import snow

#: The full EPSG:3857 world, the extent every planet raster in this project is cut on. A test grid
#: over a convenient corner would let a wrong-CRS source land inside it by accident; this is the
#: extent the shipping caller uses, so a degrees-into-metres mistake vanishes here as it would there.
WORLD_3857 = (-20037508.343, -20037508.343, 20037508.343, 20037508.343)
GRID_PX = 256

#: Antarctic Peninsula latitudes on the Greenwich side, and far from the origin on purpose: a
#: polygon straddling (0, 0) would land on the centre pixel even when a projection went wrong.
ROCK_LONLAT = ((10.0, -75.0), (40.0, -75.0), (40.0, -70.0), (10.0, -70.0))
#: Somewhere no Antarctic layer should ever draw, for the layer-selection arm below.
DECOY_LONLAT = ((-140.0, 40.0), (-110.0, 40.0), (-110.0, 60.0), (-140.0, 60.0))


def _geojson(path: Path, ring: tuple[tuple[float, float], ...]) -> Path:
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {},
                      "geometry": {"type": "Polygon",
                                   "coordinates": [[list(point) for point in (*ring, ring[0])]]}}],
    }))
    return path


def _gpkg(tmp_path: Path, layers: dict[str, tuple[tuple[float, float], ...]]) -> Path:
    """A 3857 GeoPackage with one named layer per entry — the shape the acquirer leaves on disk.

    Reprojected here with `-t_srs` exactly as `download_add_rock` does, so the fixture is the real
    product's CRS rather than a labelled 4326 that would burn nothing for the wrong reason.
    """
    out = tmp_path / "rock_3857.gpkg"
    for index, (name, ring) in enumerate(layers.items()):
        source = _geojson(tmp_path / f"{name}.geojson", ring)
        subprocess.run(["ogr2ogr", "-f", "GPKG", "-t_srs", "EPSG:3857", "-nln", name,
                        *(["-update"] if index else []), str(out), str(source)],
                       check=True, capture_output=True)
    return out


def _pixel(raster: Path, lon_lat_3857: tuple[float, float]) -> int:
    with rasterio.open(raster) as dataset:
        row, col = dataset.index(*lon_lat_3857)
        return int(dataset.read(1)[row, col])


def _to_3857(lon: float, lat: float) -> tuple[float, float]:
    """Web Mercator forward, written out rather than imported from the module under test's stack.

    An oracle sharing the projection with the code it checks agrees with it by construction; this is
    the textbook form, and its disagreement with a broken burn is the whole signal.
    """
    radius = 6378137.0
    return (np.radians(lon) * radius,
            radius * np.log(np.tan(np.pi / 4.0 + np.radians(lat) / 2.0)))


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return _gpkg(tmp_path, {"rock": ROCK_LONLAT})


class TestTheOutcropLandsWhereItIs:
    def test_the_polygons_own_pixels_are_burnt_and_the_rest_are_not(self, source, tmp_path):
        """A located claim, not a count: `.any()` passes on a burn displaced by a whole hemisphere.

        Both halves are needed. The inside pixel alone passes for a raster of all ones, which is the
        failure that would whiten nothing and read as "Antarctica has no ice"; the outside pixel
        alone passes for a raster of all zeros, which is the failure that shipped as today's look.
        """
        out = tmp_path / "addrock_3857.tif"
        snow.rasterize_antarctic_rock(WORLD_3857, GRID_PX, GRID_PX, out,
                                      gpkg=source, layer="rock")
        assert _pixel(out, _to_3857(25.0, -72.5)) == 1
        assert _pixel(out, _to_3857(-125.0, 50.0)) == 0

    def test_it_is_a_zero_one_byte_mask(self, source, tmp_path):
        """`antarctic_snow_mask` casts it to bool, so any non-zero would read as rock — a raster of
        counts or of nodata sentinels would remove the white from the whole continent."""
        out = tmp_path / "addrock_3857.tif"
        snow.rasterize_antarctic_rock(WORLD_3857, GRID_PX, GRID_PX, out,
                                      gpkg=source, layer="rock")
        with rasterio.open(out) as dataset:
            band = dataset.read(1)
            assert dataset.dtypes[0] == "uint8"
            assert set(np.unique(band).tolist()) == {0, 1}


class TestAnEmptyBurnRaisesRatherThanShipping:
    def test_geometry_that_misses_the_grid_raises(self, source, tmp_path):
        """The grid moved to the far north, so the Antarctic polygon has nothing to land on.

        Stands in for the real trap — a source in the wrong CRS — because both produce the same
        thing: two commands that succeed and a raster full of zeros. Reproduced by moving the grid
        rather than the source's CRS so the arm cannot pass on a projection failure instead.
        """
        out = tmp_path / "addrock_3857.tif"
        northern = (0.0, 5_000_000.0, 10_000_000.0, 15_000_000.0)
        with pytest.raises(vector_raster.NothingBurnt, match="Antarctic"):
            snow.rasterize_antarctic_rock(northern, 64, 64, out, gpkg=source, layer="rock")

    def test_the_guard_is_not_simply_always_raising(self, source, tmp_path):
        """The companion the arm above needs: the same call over the grid that DOES contain the
        polygon has to come back without raising, or the guard would be a refusal to burn."""
        out = tmp_path / "addrock_3857.tif"
        assert snow.rasterize_antarctic_rock(WORLD_3857, GRID_PX, GRID_PX, out,
                                             gpkg=source, layer="rock") == out


class TestTheNamedLayerIsTheOneBurnt:
    def test_a_second_layer_in_the_same_file_contributes_nothing(self, tmp_path):
        """A GeoPackage holds many layers and `gdal_rasterize` burns whichever it is pointed at.

        Named rather than left to "the file has one layer", which is true of today's product and is
        a property of the acquirer rather than of the format — and the failure is silent in the
        direction that matters: the wrong layer burns cleanly and removes white from wherever that
        other geometry happens to sit.
        """
        source = _gpkg(tmp_path, {"rock": ROCK_LONLAT, "decoy": DECOY_LONLAT})
        out = tmp_path / "addrock_3857.tif"
        snow.rasterize_antarctic_rock(WORLD_3857, GRID_PX, GRID_PX, out,
                                      gpkg=source, layer="rock")
        assert _pixel(out, _to_3857(25.0, -72.5)) == 1
        assert _pixel(out, _to_3857(-125.0, 50.0)) == 0

    def test_naming_a_layer_the_file_does_not_have_fails_loudly(self, source, tmp_path):
        """`gdal_rasterize` exits non-zero on an unknown layer, so this is already loud — pinned so
        a future switch to a shape that tolerates it (a bare call with no `-l`, which falls back to
        the file's only layer) has to be a decision rather than a tidy."""
        out = tmp_path / "addrock_3857.tif"
        with pytest.raises(subprocess.CalledProcessError):
            snow.rasterize_antarctic_rock(WORLD_3857, GRID_PX, GRID_PX, out,
                                          gpkg=source, layer="outcrop")
