"""Guards for the per-cell relief cache.

THE ORACLE PROBLEM THIS FILE HAS: production runs one strip size over a 46 GB raster and a test
runs another over a toy one, so an assertion that only checks "the numbers look plausible" would
pass on a scan that reduced the wrong axis. Every invariance test here therefore has a companion
proving it can fail, in the idiom `test_terrain_rgb` established for the same master.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import numpy as np
import pytest
import rasterio
from conftest import write_planet_vrt
from rasterio.transform import from_bounds

from pipeline import block_plan, bodies, mercator, paths, planet_seam, raster_io
from pipeline.tile import relief_scan

#: Zoom 2 gives a 2048 px grid: four cells across, so exactly one render block, and four bands at
#: the production strip size. Small enough to write in a test, big enough that the strip walk runs
#: more than once — which `test_the_fixture_runs_the_strip_walk_more_than_once` pins rather than
#: assumes.
TEST_ZOOM = 2
TEST_EDGE = block_plan.CELL_PX << TEST_ZOOM
TEST_CELLS = TEST_EDGE // block_plan.CELL_PX


def _body(name: str, *, layers: frozenset[str] = frozenset()) -> bodies.Body:
    """A synthetic body with its own store directory and a grid a test can afford to write."""
    return dataclasses.replace(bodies.EARTH, name=name, path_prefix=name,
                               surface_layers=layers, tile_max_zoom=TEST_ZOOM)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Relocate the data store, so nothing here reads or writes a real planet."""
    monkeypatch.setattr(paths, "DATA", tmp_path)
    return tmp_path


def _raster(path, array, *, nodata=None) -> None:
    """A real single-band GTiff on the whole Mercator square, because the scan reads real rasters."""
    half = mercator.MERCATOR_HALF_M
    height, width = array.shape
    path.parent.mkdir(parents=True, exist_ok=True)
    profile: dict[str, Any] = dict(
        driver="GTiff", width=width, height=height, count=1, dtype=array.dtype.name,
        crs="EPSG:3857", transform=from_bounds(-half, -half, half, half, width, height))
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as writer:  # pyright: ignore[reportCallIssue]
        writer.write(array, 1)


def _prepare(body, elevations, *, ocean=None, nodata=None, declare=("heightfield",)):
    """Put a master (and optionally an ocean mask) on disk and declare the seam, as a producer does.

    `declare` is separate from `ocean` on purpose: the pair is what lets a test put a mask on disk
    that the seam does not declare, which is the case the gating rule exists for.
    """
    work = relief_scan.work_dir(body)
    _raster(relief_scan.master_path(work), elevations, nodata=nodata)
    if ocean is not None:
        _raster(relief_scan.ocean_master_path(work), ocean)
    planet_seam.planet_dir(body).mkdir(parents=True, exist_ok=True)
    for raster in declare:
        write_planet_vrt(planet_seam.vrt_path(body, raster))
    planet_seam.declare(body, declare)
    return work


def _flat(value: float) -> np.ndarray:
    return np.full((TEST_EDGE, TEST_EDGE), value, dtype=np.float32)


class TestTheStripWalkMatchesTheWholeRaster:
    """Production reads in strips and only a test can afford not to, so the two must agree."""

    def test_the_fixture_runs_the_strip_walk_more_than_once(self) -> None:
        """A one-band fixture would make every agreement below vacuous."""
        bands = list(raster_io.row_bands(TEST_EDGE, block_plan.CELL_PX))
        assert len(bands) == 4, "the strip walk must run several times or agreement proves nothing"
        assert bands[-1][1] == TEST_EDGE

    def test_every_band_size_gives_the_same_cells(self, store) -> None:
        elevations = _flat(0.0)
        elevations[300, 700] = 4000.0     # inside cell (0, 1)
        elevations[1500, 1500] = -900.0   # inside cell (2, 2)
        answers = []
        for index, band_rows in enumerate((block_plan.CELL_PX, 2 * block_plan.CELL_PX, TEST_EDGE)):
            body = _body(f"stride{index}")
            work = _prepare(body, elevations)
            relief_scan.scan(body, band_rows=band_rows)
            answers.append(relief_scan.read_relief(work))
        for high, low in answers[1:]:
            assert np.array_equal(high, answers[0][0])
            assert np.array_equal(low, answers[0][1])
        assert answers[0][0][0, 1] == pytest.approx(4000.0)
        assert answers[0][1][2, 2] == pytest.approx(-900.0)

    def test_the_agreement_oracle_can_actually_fail(self, store) -> None:
        """A check that cannot fail is indistinguishable from one that passed."""
        body = _body("differs")
        peaked = _flat(0.0)
        peaked[300, 700] = 4000.0
        work = _prepare(body, peaked)
        relief_scan.scan(body)
        first = relief_scan.read_relief(work)[0]

        other = _body("differs2")
        work2 = _prepare(other, _flat(0.0))
        relief_scan.scan(other)
        assert not np.array_equal(first, relief_scan.read_relief(work2)[0])

    def test_a_band_size_that_is_not_a_whole_cell_is_refused(self, store) -> None:
        body = _body("ragged")
        _prepare(body, _flat(0.0))
        with pytest.raises(ValueError, match="not a positive multiple"):
            relief_scan.scan(body, band_rows=block_plan.CELL_PX + 1)


class TestNoDataIsMaskedByDeclarationAndNotByRange:
    """HISTORY, *the column the warp could not fill*: a declared sentinel is a real number to a
    consumer that does not ask, and this master declares -32768.0."""

    def test_the_declared_sentinel_does_not_become_the_lowest_elevation(self, store) -> None:
        body = _body("sentinel")
        elevations = _flat(100.0)
        elevations[10, 10] = -32768.0
        work = _prepare(body, elevations, nodata=-32768.0)
        relief_scan.scan(body)
        _, low = relief_scan.read_relief(work)
        assert low[0, 0] == pytest.approx(100.0), "the nodata sentinel was read as terrain"

    def test_the_sentinel_guard_can_fail_when_the_raster_does_not_declare_it(self, store) -> None:
        """Undeclared, the same value IS an elevation — which is what makes the test above real."""
        body = _body("undeclared")
        elevations = _flat(100.0)
        elevations[10, 10] = -32768.0
        work = _prepare(body, elevations, nodata=None)
        relief_scan.scan(body)
        _, low = relief_scan.read_relief(work)
        assert low[0, 0] == pytest.approx(-32768.0)

    def test_an_elevation_above_earths_ceiling_survives(self, store) -> None:
        """The prototype clamped at 9500 m. Mars reaches 21,202 m, so porting that line would turn
        its tallest cells into no-data and hand those blocks a margin of zero."""
        body = _body("olympus")
        elevations = _flat(0.0)
        elevations[10, 10] = 21202.0
        work = _prepare(body, elevations)
        relief_scan.scan(body)
        high, _ = relief_scan.read_relief(work)
        assert high[0, 0] == pytest.approx(21202.0), "an Earth-shaped clamp was ported"


class TestTheOceanArmFollowsTheSeamAndNotTheFilesystem:
    def test_a_body_declaring_a_mask_gets_a_share_grid(self, store) -> None:
        body = _body("wet")
        ocean = np.zeros((TEST_EDGE, TEST_EDGE), dtype=np.uint8)
        ocean[: block_plan.CELL_PX, : block_plan.CELL_PX] = 1
        work = _prepare(body, _flat(0.0), ocean=ocean,
                        declare=("heightfield", "oceanmask"))
        _, ocean_out = relief_scan.scan(body)
        assert ocean_out is not None
        share = relief_scan.read_ocean(work)
        assert share[0, 0] == pytest.approx(1.0)
        assert share[0, 1] == pytest.approx(0.0)

    def test_a_mask_on_disk_that_the_seam_does_not_declare_is_ignored(self, store) -> None:
        """A missing raster cannot tell 'this body has none' from 'the producer crashed', so the
        declaration decides and the file's presence never does."""
        body = _body("dry")
        ocean = np.ones((TEST_EDGE, TEST_EDGE), dtype=np.uint8)
        work = _prepare(body, _flat(0.0), ocean=ocean, declare=("heightfield",))
        assert relief_scan.ocean_master_path(work).exists()
        _, ocean_out = relief_scan.scan(body)
        assert ocean_out is None
        assert not relief_scan.ocean_path(work).exists()


class TestTheRecipe:
    def test_the_body_goes_in_the_path_and_not_the_recipe(self, store) -> None:
        body = _body("named")
        work = _prepare(body, _flat(0.0))
        relief_scan.scan(body)
        recorded = json.loads(relief_scan.params_path(work).read_text())
        assert "named" not in json.dumps(recorded)
        assert work.is_relative_to(store / "work" / "named")

    def test_a_body_emitting_everything_records_no_rasters_off(self, store) -> None:
        """The conditional-record idiom: an unconditional key restages a planet for no pixel."""
        body = _body("complete")
        work = _prepare(body, _flat(0.0), ocean=np.zeros((TEST_EDGE, TEST_EDGE), dtype=np.uint8),
                        declare=planet_seam.PLANET_RASTERS)
        relief_scan.scan(body)
        assert "rasters_off" not in json.loads(relief_scan.params_path(work).read_text())

    def test_a_body_missing_a_raster_records_which(self, store) -> None:
        body = _body("partial")
        work = _prepare(body, _flat(0.0))
        relief_scan.scan(body)
        recorded = json.loads(relief_scan.params_path(work).read_text())
        assert recorded["rasters_off"] == ["oceanmask", "watermask"]


class TestFreshness:
    def test_a_second_scan_leaves_the_cache_alone(self, store) -> None:
        body = _body("twice")
        work = _prepare(body, _flat(0.0))
        relief_scan.scan(body)
        stamped = relief_scan.relief_path(work).stat().st_mtime_ns
        relief_scan.scan(body)
        assert relief_scan.relief_path(work).stat().st_mtime_ns == stamped

    def test_a_master_written_since_the_stamp_restages(self, store) -> None:
        body = _body("moved")
        work = _prepare(body, _flat(0.0))
        relief_scan.scan(body)
        stamped = relief_scan.relief_path(work).stat().st_mtime_ns
        _raster(relief_scan.master_path(work), _flat(500.0))
        relief_scan.scan(body)
        assert relief_scan.relief_path(work).stat().st_mtime_ns != stamped
        assert relief_scan.read_relief(work)[0][0, 0] == pytest.approx(500.0)

    def test_the_cache_is_never_left_at_its_final_path_half_written(self, store) -> None:
        """The `.part` rule: existence is what every resume in this repo trusts."""
        body = _body("whole")
        work = _prepare(body, _flat(0.0))
        relief_scan.scan(body)
        assert not relief_scan.relief_path(work).with_suffix(".part").exists()


class TestTheGridIsTheBodysOwn:
    def test_a_master_of_the_wrong_size_is_refused_by_name(self, store) -> None:
        body = _body("mismatched")
        work = relief_scan.work_dir(body)
        _raster(relief_scan.master_path(work),
                np.zeros((TEST_EDGE // 2, TEST_EDGE // 2), dtype=np.float32))
        planet_seam.planet_dir(body).mkdir(parents=True, exist_ok=True)
        write_planet_vrt(planet_seam.vrt_path(body, "heightfield"))
        planet_seam.declare(body, ("heightfield",))
        with pytest.raises(ValueError, match=f"{TEST_EDGE}x{TEST_EDGE} grid"):
            relief_scan.scan(body)
