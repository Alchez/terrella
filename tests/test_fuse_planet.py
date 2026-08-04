"""fuse_planet.enforce_land_guard: the output-side check that a tileList-listed land cell
actually fused land. Born when stale dem/wbm mosaic VRTs made every Antarctic tile
invisible to fusion, the whole continent fused as ocean, and every input-side gate passed —
the tileList preflight checks tiles on DISK, and the in-cell gap check defines land from the
same stale WBM mosaic. The fused ocean mask is the one input that cannot go stale.
"""

import os

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


class TestEnforceLandGuard:
    def test_a_single_land_pixel_passes_and_keeps_the_outputs(self, tmp_path):
        chunk = _chunk_dir(tmp_path, [[1, 1], [1, 0]])  # 0 = land
        assert fuse_planet.enforce_land_guard(chunk) is True
        for raster in planet_seam.PLANET_RASTERS:
            assert (chunk / f"{raster}_{fuse_planet.TAG}.tif").exists()
        assert not (chunk / "error.log").exists()

    def test_pure_ocean_fails_deletes_all_outputs_and_names_the_fix(self, tmp_path):
        chunk = _chunk_dir(tmp_path, [[1, 1], [1, 1]])
        assert fuse_planet.enforce_land_guard(chunk) is False
        for raster in planet_seam.PLANET_RASTERS:
            assert not (chunk / f"{raster}_{fuse_planet.TAG}.tif").exists()
        assert "build_mosaics" in (chunk / "error.log").read_text()

    def test_a_guard_failure_reopens_the_resume_slot(self, tmp_path):
        """fuse_cell skips any cell whose heightfield exists — after a guard failure the
        heightfield specifically must be gone, or the next sweep would skip straight over
        the garbage cell instead of retrying it."""
        chunk = _chunk_dir(tmp_path, [[1]])
        fuse_planet.enforce_land_guard(chunk)
        assert not (chunk / f"heightfield_{fuse_planet.TAG}.tif").exists()


def _cell(chunks_dir, name, rasters):
    """One fused cell: a real 1x1 GTiff per named raster, which `gdalbuildvrt` can actually index."""
    outdir = chunks_dir / name
    outdir.mkdir(parents=True, exist_ok=True)
    transform = from_bounds(0.0, 0.0, 10.0, 10.0, 1, 1)  # pyright: ignore[reportCallIssue] — rasterio untyped
    for raster in rasters:
        with rasterio.open(outdir / f"{raster}_{fuse_planet.TAG}.tif", "w", driver="GTiff",
                           width=1, height=1, count=1, dtype="uint8",
                           crs="EPSG:4326", transform=transform) as dataset:
            dataset.write(np.zeros((1, 1), dtype="uint8"), 1)
    return outdir


class TestBuildVrtIfChanged:
    """Rebuilding the planet VRTs must be free when nothing moved.

    NOT AN OPTIMISATION. Every 3857 warp downstream is gated on the VRT's mtime, so an
    unconditional `-overwrite` restages the whole 46 GB planet — a full re-warp, an 8:28 hillshade,
    a 53.8 min composite and a 3:44 cut — to reproduce pixels that were already correct. Anyone who
    edits this module and re-runs `--build-vrts` to check their work pays that.
    """

    def test_an_unchanged_source_set_leaves_the_file_untouched(self, tmp_path):
        """Backdated on purpose: a rewrite would stamp `now`, so an unmoved mtime is proof the file
        was never replaced — regardless of the filesystem's timestamp granularity."""
        chunks = tmp_path / "chunks"
        _cell(chunks, "e000_n00", ["heightfield"])
        vrt = tmp_path / "planet_heightfield.vrt"
        sources = sorted(chunks.glob("*/heightfield_10s.tif"))
        assert fuse_planet.build_vrt_if_changed(vrt, sources) is True
        os.utime(vrt, (0, 0))
        before = vrt.read_bytes()
        assert fuse_planet.build_vrt_if_changed(vrt, sources) is False
        assert vrt.stat().st_mtime == 0
        assert vrt.read_bytes() == before

    def test_a_changed_source_set_replaces_the_file(self, tmp_path):
        chunks = tmp_path / "chunks"
        _cell(chunks, "e000_n00", ["heightfield"])
        vrt = tmp_path / "planet_heightfield.vrt"
        fuse_planet.build_vrt_if_changed(vrt, sorted(chunks.glob("*/heightfield_10s.tif")))
        os.utime(vrt, (0, 0))
        _cell(chunks, "e010_n00", ["heightfield"])
        assert fuse_planet.build_vrt_if_changed(
            vrt, sorted(chunks.glob("*/heightfield_10s.tif"))) is True
        assert vrt.stat().st_mtime > 0

    def test_the_scratch_target_never_survives(self, tmp_path):
        """A leftover `.vrt.new` beside the real one is a second, unreferenced index of the planet."""
        chunks = tmp_path / "chunks"
        _cell(chunks, "e000_n00", ["heightfield"])
        vrt = tmp_path / "planet_heightfield.vrt"
        sources = sorted(chunks.glob("*/heightfield_10s.tif"))
        fuse_planet.build_vrt_if_changed(vrt, sources)
        fuse_planet.build_vrt_if_changed(vrt, sources)
        assert list(tmp_path.glob("*.new")) == []

    def test_the_scratch_target_shares_the_vrts_directory(self, tmp_path):
        """`gdalbuildvrt` writes source paths RELATIVE to the VRT, so building elsewhere and moving
        the result would rewrite every one of them and never compare equal."""
        chunks = tmp_path / "chunks"
        _cell(chunks, "e000_n00", ["heightfield"])
        vrt = tmp_path / "planet_heightfield.vrt"
        fuse_planet.build_vrt_if_changed(vrt, sorted(chunks.glob("*/heightfield_10s.tif")))
        assert 'relativeToVRT="1"' in vrt.read_text()


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

    def test_a_half_fused_planet_is_refused_rather_than_declared(self, store):
        """Earth declares the lake-depth layer, which is computed off watermask class 2. A planet
        stage that emitted no watermask cannot supply it, and saying so here beats discovering it
        as a `None` class code inside a composite worker thread."""
        _cell(fuse_planet.CHUNKS_DIR, "e000_n00", ["heightfield", "oceanmask"])
        with pytest.raises(ValueError, match="lake_depth"):
            fuse_planet.build_vrts()
        assert not planet_seam.declaration_path(bodies.EARTH).exists()
