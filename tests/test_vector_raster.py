"""The reproject-then-burn owner, and the silent failure it exists to make unrepresentable.

THESE TESTS DRIVE THE REAL `ogr2ogr` AND `gdal_rasterize`, deliberately. The defect under test is a
GDAL BEHAVIOUR — that `gdal_rasterize` accepts a vector in the wrong CRS, burns nothing, and exits 0
— so a mocked subprocess would be testing the mock's opinion of GDAL rather than GDAL. CI installs
`gdal-bin` and `tests/test_planet_seam.py` already runs `gdalbuildvrt` unguarded, which is the
precedent followed here.

Every fixture is synthetic and lives in `tmp_path`; nothing reads the production store, so the file
passes under `MAPS_DATA=<empty dir>` exactly as CI runs it.

THE SYNTHETIC GRID REPRODUCES THE REAL FAILURE MODE RATHER THAN A CONVENIENT ONE. Degrees fed to a
metre grid are not rejected for being out of range — the world Mercator extent is ±20,037,508 m, so
±180 lands in a blob 40 m across at the origin and rounds away to nothing. A toy grid a few hundred
metres wide would make the trap arm burn pixels and the test would pass for the wrong reason.
"""

import json
import subprocess
from pathlib import Path

import pytest
import rasterio

from pipeline import vector_raster

#: The full EPSG:3857 world, the extent every planet raster in this project is cut on.
WORLD_3857 = (-20037508.343, -20037508.343, 20037508.343, 20037508.343)
GRID_PX = 256


def _polygon_4326(path: Path) -> Path:
    """A lon/lat block big enough to cover many pixels once projected, and to vanish if it is not.

    Deliberately away from the origin: a polygon straddling (0, 0) would land ON the centre pixel in
    the trap arms and burn one, which is a weaker distinction than burning none.
    """
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {},
                      "geometry": {"type": "Polygon",
                                   "coordinates": [[[100.0, 60.0], [140.0, 60.0],
                                                    [140.0, 80.0], [100.0, 80.0],
                                                    [100.0, 60.0]]]}}],
    }))
    return path


def _burnt(raster: Path) -> int:
    with rasterio.open(raster) as dataset:
        return int((dataset.read(1) != 0).sum())


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return _polygon_4326(tmp_path / "unit.geojson")


class TestTheArgvContract:
    """Pinned as argv so the flags are checkable without a GDAL run, and so the coastline's
    pre-existing command is provably unchanged by moving it here."""

    def test_the_reprojection_uses_t_srs_and_never_a_srs(self):
        """The single most important flag in this module. `-a_srs` assigns a label and moves no
        coordinate, so substituted here it produces the all-zero raster the class below measures."""
        argv = vector_raster.reproject_argv(Path("in.shp"), "EPSG:3857", Path("out.gpkg"))
        assert "-t_srs" in argv
        assert "-a_srs" not in argv

    def test_the_rasterize_argv_is_the_command_the_coastline_already_ran(self):
        """Byte-identity for `cap_render._bake_coastline`, checked at the flags rather than by
        re-rendering a cap. This literal is that call site's command before the extraction; if it
        ever has to change, Earth's shipped caps restage and that is the decision to take knowingly.
        """
        edge = 1111949.266
        assert vector_raster.rasterize_argv(
            Path("coast.gpkg"), (-edge, -edge, edge, edge), 8192, 8192, Path("coast.tif")
        ) == ["gdal_rasterize", "-q", "-burn", "1", "-init", "0", "-ot", "Byte",
              "-te", str(-edge), str(-edge), str(edge), str(edge),
              "-ts", "8192", "8192", "coast.gpkg", "coast.tif"]

    def test_naming_no_layer_leaves_the_command_exactly_as_it_was(self):
        """The default has to be ABSENCE and not a name, or the shipped coastline command changes.

        `-l` was added for the GeoPackage caller, whose file can hold several layers; every caller
        that came first hands over a single-layer GeoJSON or shapefile where `gdal_rasterize` needs
        no telling. A default of "the first layer" would be the same command spelled two ways.
        """
        argv = vector_raster.rasterize_argv(Path("v.json"), WORLD_3857, 4, 4, Path("o.tif"))
        assert "-l" not in argv

    def test_a_named_layer_is_selected_by_name(self):
        """A GeoPackage is many layers in one file, so burning it without saying which is a
        question `gdal_rasterize` answers by position — and the wrong answer burns cleanly."""
        argv = vector_raster.rasterize_argv(Path("v.gpkg"), WORLD_3857, 4, 4, Path("o.tif"),
                                            layer="rock")
        assert argv[argv.index("rock") - 1] == "-l"

    def test_each_creation_option_becomes_its_own_co_flag(self):
        argv = vector_raster.rasterize_argv(Path("v.json"), WORLD_3857, 4, 4, Path("o.tif"),
                                            creation_options=("TILED=YES", "COMPRESS=DEFLATE"))
        assert argv.count("-co") == 2
        assert argv[argv.index("TILED=YES") - 1] == "-co"
        assert argv[argv.index("COMPRESS=DEFLATE") - 1] == "-co"


class TestTheTrapBurnsNothingAndIsRefused:
    """Both wrong chains, measured. Each one exits 0 and writes a well-formed raster, which is why
    a return code and a file-exists check are both worthless here."""

    def test_the_correct_chain_burns_pixels(self, source, tmp_path):
        """The anti-vacuity for the two arms below: without it they pass against a source that
        rasterises to nothing for some reason of its own."""
        out = vector_raster.burn_onto_grid(
            source, "EPSG:3857", WORLD_3857, GRID_PX, GRID_PX,
            projected=tmp_path / "p.geojson", out=tmp_path / "ok.tif",
            must_draw="the synthetic block")
        assert _burnt(out) > 100

    def test_rasterizing_the_unprojected_vector_burns_nothing(self, source, tmp_path):
        """Arm one: `gdal_rasterize` handed 4326 degrees and a metre extent. Exit 0, a raster of the
        requested size, and every pixel zero."""
        argv = vector_raster.rasterize_argv(source, WORLD_3857, GRID_PX, GRID_PX,
                                            tmp_path / "trap.tif")
        # check=False on purpose: the exit code IS the assertion. gdal_rasterize succeeds here, and
        # that success beside an empty raster is the entire defect this module exists to catch.
        assert subprocess.run(argv, capture_output=True, check=False).returncode == 0
        assert _burnt(tmp_path / "trap.tif") == 0

    def test_a_srs_instead_of_t_srs_burns_nothing(self, source, tmp_path):
        """Arm two, and the one that looks most like working code: the vector is 'given' the target
        CRS, so the file says EPSG:3857 and its numbers are still degrees."""
        mislabelled = tmp_path / "mislabelled.geojson"
        subprocess.run(["ogr2ogr", "-overwrite", "-a_srs", "EPSG:3857",
                        str(mislabelled), str(source)], check=True, capture_output=True)
        subprocess.run(vector_raster.rasterize_argv(mislabelled, WORLD_3857, GRID_PX, GRID_PX,
                                                    tmp_path / "trap2.tif"),
                       check=True, capture_output=True)
        assert _burnt(tmp_path / "trap2.tif") == 0

    def test_the_guard_refuses_an_empty_burn_and_names_the_subject(self, source, tmp_path):
        """What `must_draw` buys: the same silent zero, turned into a sentence naming what was
        expected and pointing at the CRS as the thing to check."""
        with pytest.raises(vector_raster.NothingBurnt) as raised:
            vector_raster.burn_onto_grid(
                source, "EPSG:4326", WORLD_3857, GRID_PX, GRID_PX,
                projected=tmp_path / "p.geojson", out=tmp_path / "empty.tif",
                must_draw="the synthetic block")
        assert "the synthetic block" in str(raised.value)
        assert "EPSG:4326" in str(raised.value)


class TestTheGuardIsTheCallersClaim:
    def test_without_must_draw_an_empty_burn_is_returned_rather_than_refused(self, source, tmp_path):
        """A caller whose geometry may honestly miss the grid — a unit that does not reach a small
        cap disc — must get its empty mask back. Defaulting the guard on would cry wolf there."""
        out = vector_raster.burn_onto_grid(
            source, "EPSG:4326", WORLD_3857, GRID_PX, GRID_PX,
            projected=tmp_path / "p.geojson", out=tmp_path / "empty.tif")
        assert _burnt(out) == 0

    def test_drew_nothing_answers_both_ways(self, source, tmp_path):
        """The oracle behind the guard, shown able to return each answer — a detector that only
        ever says True would make every test above pass while detecting nothing."""
        empty = vector_raster.burn_onto_grid(
            source, "EPSG:4326", WORLD_3857, GRID_PX, GRID_PX,
            projected=tmp_path / "a.geojson", out=tmp_path / "a.tif")
        drawn = vector_raster.burn_onto_grid(
            source, "EPSG:3857", WORLD_3857, GRID_PX, GRID_PX,
            projected=tmp_path / "b.geojson", out=tmp_path / "b.tif")
        assert vector_raster.drew_nothing(empty) is True
        assert vector_raster.drew_nothing(drawn) is False


class TestTheCreationOptionsReachTheFile:
    def test_a_planet_sized_caller_gets_a_tiled_deflated_raster(self, source, tmp_path):
        """The one axis two shipping callers differ on: a cap-sized target takes the defaults, a
        32768-square planet mask cannot be an untiled uncompressed Byte raster.

        Sized past one block on purpose — GDAL writes 256-square blocks whatever is asked, so at
        `GRID_PX` the whole image is a single block and rasterio reports it untiled either way.
        """
        out = vector_raster.burn_onto_grid(
            source, "EPSG:3857", WORLD_3857, GRID_PX * 2, GRID_PX * 2,
            projected=tmp_path / "p.geojson", out=tmp_path / "co.tif",
            creation_options=("TILED=YES", "COMPRESS=DEFLATE"))
        with rasterio.open(out) as dataset:
            assert dataset.profile["tiled"] is True
            assert dataset.profile["compress"] == "deflate"


class TestTheTwoStepSurvivesASecondRun:
    """Running it TWICE, which is the thing no caller had ever done and no test had ever asked.

    The projected intermediate outlives a run, and `ogr2ogr` cannot write over an existing GeoJSON
    by any flag — so this pair succeeded exactly once and raised `CalledProcessError` on every
    re-run after. It shipped because nothing produces the intermediate twice until a grid CHANGES,
    which on this project means a body's tile ceiling moving; Mars z6 -> z7 was the first, four
    minutes into a pass that had already re-warped a 65536-square heightfield.

    Against the repo rule that a stage is idempotent and resumable, one arm of this is not a
    regression test but the missing half of the original contract.
    """

    def test_a_second_identical_run_succeeds(self, source, tmp_path):
        paths = dict(projected=tmp_path / "p.geojson", out=tmp_path / "burn.tif")
        first = vector_raster.burn_onto_grid(
            source, "EPSG:3857", WORLD_3857, GRID_PX, GRID_PX, **paths,
            must_draw="the synthetic block")
        before = first.read_bytes()
        assert paths["projected"].exists(), "the intermediate must survive, or this proves nothing"
        again = vector_raster.burn_onto_grid(
            source, "EPSG:3857", WORLD_3857, GRID_PX, GRID_PX, **paths,
            must_draw="the synthetic block")
        assert again.read_bytes() == before, "a re-run must reproduce the raster, not merely finish"

    def test_a_second_run_at_a_new_size_rebuilds_rather_than_reusing(self, source, tmp_path):
        """THE CASE THAT MOTIVATED IT: the same vector onto a grid that changed under it, which is
        what a moved ceiling asks for. The burn must follow the new size, not the intermediate."""
        paths = dict(projected=tmp_path / "p.geojson", out=tmp_path / "burn.tif")
        vector_raster.burn_onto_grid(source, "EPSG:3857", WORLD_3857, GRID_PX, GRID_PX, **paths,
                                     must_draw="the synthetic block")
        grown = vector_raster.burn_onto_grid(
            source, "EPSG:3857", WORLD_3857, GRID_PX * 2, GRID_PX * 2, **paths,
            must_draw="the synthetic block")
        with rasterio.open(grown) as dataset:
            assert (dataset.width, dataset.height) == (GRID_PX * 2, GRID_PX * 2)

    def test_a_corrupt_intermediate_does_not_survive_into_the_burn(self, source, tmp_path):
        """The unlink is what makes the re-run honest rather than merely quiet: whatever was at the
        intermediate's path, the reprojection replaces it. Without it GDAL refuses outright, so a
        stale file could never be read as fresh -- but the guard should hold if that ever changes."""
        paths = dict(projected=tmp_path / "p.geojson", out=tmp_path / "burn.tif")
        paths["projected"].write_text("not geojson at all")
        out = vector_raster.burn_onto_grid(
            source, "EPSG:3857", WORLD_3857, GRID_PX, GRID_PX, **paths,
            must_draw="the synthetic block")
        assert _burnt(out) > 100
        assert json.loads(paths["projected"].read_text())["type"] == "FeatureCollection"
