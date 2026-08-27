"""fuse_planet.enforce_land_guard: the output-side check that a tileList-listed land cell
actually fused land. Born when stale dem/wbm mosaic VRTs made every Antarctic tile
invisible to fusion, the whole continent fused as ocean, and every input-side gate passed —
the tileList preflight checks tiles on DISK, and the in-cell gap check defines land from the
same stale WBM mosaic. The fused ocean mask is the one input that cannot go stale.
"""


import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from pipeline import bodies, paths, planet_seam
from pipeline.fuse import fuse_planet


def _chunk_dir(tmp_path, ocean_mask_rows):
    """A fused chunk: a real oceanmask GTiff plus text stand-ins for the other layers.

    The guard opens only the mask; heightfield/watermask just need to exist so the tests
    can prove the deletion path touches all three.
    """
    mask_array = np.asarray(ocean_mask_rows, dtype="uint8")
    mask_height, mask_width = mask_array.shape
    transform = from_bounds(0.0, 0.0, 10.0, 10.0, mask_width, mask_height)  # pyright: ignore[reportCallIssue] — rasterio untyped
    with rasterio.open(tmp_path / f"oceanmask_{fuse_planet.TAG}.tif", "w", driver="GTiff",
                       width=mask_width, height=mask_height, count=1, dtype="uint8",
                       crs="EPSG:4326", transform=transform) as dataset:
        dataset.write(mask_array, 1)
    (tmp_path / f"heightfield_{fuse_planet.TAG}.tif").write_text("stand-in")
    (tmp_path / f"watermask_{fuse_planet.TAG}.tif").write_text("stand-in")
    return tmp_path


TILE = "Copernicus_DSM_COG_10_S68_00_W180_00_DEM"


def _wbm(path, value):
    """A stand-in WBM mosaic covering `TILE`'s degree square with one class code.

    255 is the mosaic's nodata: what a VRT returns where it indexes no source, which is exactly
    what a stale mosaic looks like over a tile that IS on disk.
    """
    transform = from_bounds(-180.0, -68.0, -179.0, -67.0, 8, 8)  # pyright: ignore[reportCallIssue]
    with rasterio.open(path, "w", driver="GTiff", width=8, height=8, count=1, dtype="uint8",
                       crs="EPSG:4326", transform=transform, nodata=255) as dataset:
        dataset.write(np.full((8, 8), value, dtype="uint8"), 1)
    return path


class TestEnforceLandGuard:
    def test_a_single_land_pixel_passes_and_keeps_the_outputs(self, tmp_path):
        chunk = _chunk_dir(tmp_path, [[1, 1], [1, 0]])  # 0 = land
        assert fuse_planet.enforce_land_guard(chunk) is True
        for raster in planet_seam.PLANET_RASTERS:
            assert (chunk / f"{raster}_{fuse_planet.TAG}.tif").exists()
        assert not (chunk / "error.log").exists()

    def test_a_guard_failure_reopens_the_resume_slot(self, tmp_path):
        """fuse_cell skips any cell whose heightfield exists — after a guard failure the
        heightfield specifically must be gone, or the next sweep would skip straight over
        the garbage cell instead of retrying it."""
        chunk = _chunk_dir(tmp_path, [[1]])
        fuse_planet.enforce_land_guard(chunk)
        assert not (chunk / f"heightfield_{fuse_planet.TAG}.tif").exists()


class TestAnAllOceanCellIsNotEvidenceOfAStaleMosaic:
    """The guard's premise was "tiles are listed, so this cell has land", and it is false.

    GLO-30 PUBLISHES TILES OVER OPEN WATER. They carry the water-body mask and 0 m elevation, so a
    cell can list tiles, have every one of them present and indexed, and still hold no land. Two of
    Earth's 648 do: `w180_s70` (Scott Island's square, WBM class 1 throughout) and `w010_n80` (north
    of Greenland, two indexed tiles both all-ocean). Both fused to 100% ocean in July as well as
    today, from two different mosaic snapshots.

    NEITHER HAD EVER BEEN CHECKED. The guard landed 2026-07-22 in `df7c656`; `w010_n80`'s chunk is
    nine days older and `fuse_cell` skips a cell whose output exists, so no run since has re-asked.

    WHAT THE GUARD IS ACTUALLY FOR still has to fail, and it is a different fact: tiles present ON
    DISK but absent from the VRT, which enumerates its sources at build time. Then the mosaic serves
    NODATA over exactly the tiles the cell is listed for, the fusion reads nodata as ocean, and a
    continent fuses away. The discriminator is therefore whether the cell's listed tiles are
    REACHABLE THROUGH THE MOSAIC — a fact about the input — and not anything about the output, which
    is identical in both cases.
    """

    def test_a_landless_cell_whose_tiles_ARE_indexed_survives(self, tmp_path):
        wbm = _wbm(tmp_path / "wbm.vrt", 1)  # ocean: the tile is served and holds no land
        chunk = _chunk_dir(tmp_path, [[1, 1], [1, 1]])
        assert fuse_planet.enforce_land_guard(chunk, listed_tiles=[TILE], wbm_vrt=wbm) is True
        for raster in planet_seam.PLANET_RASTERS:
            assert (chunk / f"{raster}_{fuse_planet.TAG}.tif").exists()
        assert not (chunk / "error.log").exists()

    def test_a_cell_whose_tiles_are_NOT_indexed_still_fails(self, tmp_path):
        """The Antarctic failure this guard was built for, and it must stay caught."""
        wbm = _wbm(tmp_path / "wbm.vrt", 255)  # nodata: the mosaic serves nothing here
        chunk = _chunk_dir(tmp_path, [[1, 1], [1, 1]])
        assert fuse_planet.enforce_land_guard(chunk, listed_tiles=[TILE], wbm_vrt=wbm) is False
        for raster in planet_seam.PLANET_RASTERS:
            assert not (chunk / f"{raster}_{fuse_planet.TAG}.tif").exists()
        assert "build_mosaics" in (chunk / "error.log").read_text()

    def test_land_in_the_mosaic_that_the_fusion_LOST_still_fails(self, tmp_path):
        """The tile is served AND holds land, yet the fused mask is all ocean — so something
        between the two dropped it. Indexed-ness must not become a blanket excuse."""
        wbm = _wbm(tmp_path / "wbm.vrt", 0)  # class 0 = land
        chunk = _chunk_dir(tmp_path, [[1, 1], [1, 1]])
        assert fuse_planet.enforce_land_guard(chunk, listed_tiles=[TILE], wbm_vrt=wbm) is False

    def test_it_reads_the_tiles_the_CELL_lists_and_not_the_whole_cell(self, tmp_path):
        """`w010_n80` is 90% nodata — open ocean beyond its two tiles — so a whole-cell test for
        'any real pixel' would read that nodata and refuse a cell that is merely mostly empty."""
        wbm = _wbm(tmp_path / "wbm.vrt", 1)
        chunk = _chunk_dir(tmp_path, [[1, 1], [1, 1]])
        far = "Copernicus_DSM_COG_10_N45_00_E009_00_DEM"  # nowhere near the stand-in mosaic
        assert fuse_planet.enforce_land_guard(chunk, listed_tiles=[far], wbm_vrt=wbm) is False, \
            "a tile the mosaic cannot serve at all is the stale case"


def _cell(chunks_dir, name, rasters, tag=None, rows=1):
    """One fused cell: a real GTiff per named raster, which `gdalbuildvrt` can actually index.

    `rows` exists so a mask can be written FINER than the heightfield beside it, which is the shape
    `--masks` produces and the one `planet_seam._require_nested_grids` has an opinion about.
    """
    outdir = chunks_dir / name
    outdir.mkdir(parents=True, exist_ok=True)
    for raster in rasters:
        transform = from_bounds(0.0, 0.0, 10.0, 10.0, 1, rows)  # pyright: ignore[reportCallIssue] — rasterio untyped
        with rasterio.open(outdir / f"{raster}_{tag or fuse_planet.TAG}.tif", "w", driver="GTiff",
                           width=1, height=rows, count=1, dtype="uint8",
                           crs="EPSG:4326", transform=transform) as dataset:
            dataset.write(np.zeros((rows, 1), dtype="uint8"), 1)
    return outdir


class TestTheMasksOnlyPassDrivesTheRightCell:
    """The flags `--masks` turns into, and the sentinel it resumes on.

    NOT COVERED BY THE GRID TESTS, and it is the half a wrong run wastes an hour on: the grid tests
    prove `make_grid` is right, and these prove the pass actually asks for it.
    """

    @pytest.fixture
    def spy(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fuse_planet, "CHUNKS_DIR", tmp_path)
        seen = {}

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        def _capture(cmd, **_kwargs):
            seen["cmd"] = cmd
            return _Result()

        monkeypatch.setattr(fuse_planet.subprocess, "run", _capture)
        return seen

    def test_it_asks_for_a_finer_latitude_and_no_heightfield(self, spy):
        fuse_planet.fuse_cell("e000_n00", (0, 0, 10, 10), listed_tiles=(), masks_only=True)
        assert "--masks-only" in spy["cmd"]
        assert "--lat-res-arcsec" in spy["cmd"]
        assert spy["cmd"][spy["cmd"].index("--lat-res-arcsec") + 1] == str(
            fuse_planet.MASK_LAT_ARCSEC)
        assert spy["cmd"][spy["cmd"].index("--res-arcsec") + 1] == str(fuse_planet.RES_ARCSEC), \
            "longitude must stay coarse — refining it would upsample native GLO-30"

    def test_the_square_pass_is_untouched_by_any_of_it(self, spy):
        fuse_planet.fuse_cell("e000_n00", (0, 0, 10, 10), listed_tiles=())
        assert "--masks-only" not in spy["cmd"] and "--lat-res-arcsec" not in spy["cmd"]

    def test_a_masks_pass_resumes_on_ITS_OWN_output(self, spy, tmp_path):
        """Keyed on the heightfield it would re-run every finished cell forever, since a masks-only
        run never writes one."""
        outdir = tmp_path / "e000_n00"
        outdir.mkdir()
        (outdir / f"oceanmask_{fuse_planet.MASK_TAG}.tif").write_text("done")
        assert fuse_planet.fuse_cell("e000_n00", (0, 0, 10, 10), listed_tiles=(),
                                     masks_only=True) == ("e000_n00", "skipped")
        assert "cmd" not in spy, "a finished cell must not be fused again"

    def test_a_square_heightfield_does_not_mark_the_masks_pass_done(self, spy, tmp_path):
        """The two passes share a chunk directory, so each must read only its own sentinel."""
        outdir = tmp_path / "e000_n00"
        outdir.mkdir()
        (outdir / f"heightfield_{fuse_planet.TAG}.tif").write_text("done")
        fuse_planet.fuse_cell("e000_n00", (0, 0, 10, 10), listed_tiles=(), masks_only=True)
        assert "cmd" in spy, "the fine masks are still owed on this cell"


class TestBuildVrtsDeclaresWhatItBuilt:
    @pytest.fixture
    def store(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "DATA", tmp_path)
        monkeypatch.setattr(fuse_planet, "CHUNKS_DIR",
                            planet_seam.planet_dir(bodies.EARTH) / "chunks")
        return tmp_path

    def test_a_full_sweep_declares_all_three(self, store):
        _cell(fuse_planet.CHUNKS_DIR, "e000_n00", planet_seam.PLANET_RASTERS)
        fuse_planet.build_vrts()
        assert planet_seam.declared(bodies.EARTH) == planet_seam.KNOWN_RASTERS

    def test_the_declaration_is_written_after_the_vrts_it_names(self, store):
        """Its presence is the completion stamp, so it must never predate what it promises."""
        _cell(fuse_planet.CHUNKS_DIR, "e000_n00", planet_seam.PLANET_RASTERS)
        fuse_planet.build_vrts()
        declaration = planet_seam.declaration_path(bodies.EARTH).stat().st_mtime
        for raster in planet_seam.PLANET_RASTERS:
            assert planet_seam.vrt_path(bodies.EARTH, raster).stat().st_mtime <= declaration

    def test_the_masks_can_come_from_a_FINER_grid_than_the_heightfield(self, store):
        """The `--masks` shape: masks at 1" latitude beside a square 10" heightfield.

        Ten rows against one is the ratio the real pass produces, and it must survive
        `planet_seam.declare` — the guard there refuses grids that do not nest, so this is the test
        that the intended arrangement is legal rather than merely untested.
        """
        _cell(fuse_planet.CHUNKS_DIR, "e000_n00", ["heightfield"])
        _cell(fuse_planet.CHUNKS_DIR, "e000_n00", ["oceanmask", "watermask"],
              tag=fuse_planet.MASK_TAG, rows=10)
        fuse_planet.build_vrts(fuse_planet.MASK_TAG)
        assert planet_seam.declared(bodies.EARTH) == planet_seam.KNOWN_RASTERS
        with rasterio.open(planet_seam.vrt_path(bodies.EARTH, "oceanmask")) as mask, \
             rasterio.open(planet_seam.vrt_path(bodies.EARTH, "heightfield")) as height:
            assert mask.height == height.height * 10
            assert mask.width == height.width

    def test_the_mask_tag_is_PASSED_and_never_probed_for(self, store):
        """Fine chunks on disk must not repoint the planet on their own.

        A half-finished mask pass leaves some cells fine and some square; if `build_vrts` chose by
        what it found, that state would silently publish a partial planet. Default call, fine chunks
        present: it must still index the square masks.
        """
        _cell(fuse_planet.CHUNKS_DIR, "e000_n00", planet_seam.PLANET_RASTERS)
        _cell(fuse_planet.CHUNKS_DIR, "e000_n00", ["oceanmask", "watermask"],
              tag=fuse_planet.MASK_TAG, rows=10)
        fuse_planet.build_vrts()
        with rasterio.open(planet_seam.vrt_path(bodies.EARTH, "oceanmask")) as mask:
            assert mask.height == 1, "the square masks are what a default build indexes"

    def test_a_half_fused_planet_is_refused_rather_than_declared(self, store):
        """Earth declares the lake-depth layer, which is computed off watermask class 2. A planet
        stage that emitted no watermask cannot supply it, and saying so here beats discovering it
        as a `None` class code inside a composite worker thread."""
        _cell(fuse_planet.CHUNKS_DIR, "e000_n00", ["heightfield", "oceanmask"])
        with pytest.raises(ValueError, match="lake_depth"):
            fuse_planet.build_vrts()
        assert not planet_seam.declaration_path(bodies.EARTH).exists()
