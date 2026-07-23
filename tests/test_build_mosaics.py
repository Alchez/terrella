"""build_mosaics.sh freshness skip: rebuild only when the tile store changed.

The batch runner invokes the script once per country, but the store changes only
when a download actually lands — the other ~200 invocations rebuilt two 26k-source
VRTs identically (~17 s each, ~53 min per full walk). The skip must survive all
three ways the store can change:

  - a NEW tile (fresh mtime, longer source list)
  - a DELETED tile (every remaining source is OLDER than the VRT — only comparing
    the source list against the last build's .sources sidecar can catch it)
  - a RE-DOWNLOADED tile (same name, same count — only the newer-than check sees it)

These tests drive the real script (bash + gdalbuildvrt) against a throwaway data
root via the MAPS_DATA override, with tiny 2x2 GeoTIFFs standing in for GLO-30.
"""

import os
import subprocess
from pathlib import Path

import numpy as np
import rasterio
import rasterio.transform

SCRIPT = Path(__file__).resolve().parents[1] / "pipeline" / "fuse" / "build_mosaics.sh"


def write_tile(path: Path, west: float, south: float) -> None:
    """A 2x2 float32 GeoTIFF covering the 1x1 degree cell at (west, south)."""
    transform = rasterio.transform.from_origin(west, south + 1.0, 0.5, 0.5)
    with rasterio.open(path, "w", driver="GTiff", width=2, height=2, count=1,
                       dtype="float32", crs="EPSG:4326", transform=transform) as out:
        out.write(np.zeros((1, 2, 2), dtype=np.float32))


def make_store(root: Path, tile_count: int = 2) -> None:
    for sub in ("raw/glo30/dem", "raw/glo30/wbm", "work"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    for index in range(tile_count):
        write_tile(root / "raw/glo30/dem" / f"tile_{index}_DEM.tif", 10.0 + index, 40.0)
        write_tile(root / "raw/glo30/wbm" / f"tile_{index}_WBM.tif", 10.0 + index, 40.0)


def run_script(root: Path) -> str:
    result = subprocess.run(["bash", str(SCRIPT)],
                            env={**os.environ, "MAPS_DATA": str(root)},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


def source_count(vrt: Path) -> int:
    return vrt.read_text().count("<SourceFilename")


class TestBuild:
    def test_first_run_builds_vrts_and_sidecars(self, tmp_path):
        make_store(tmp_path)
        out = run_script(tmp_path)
        assert "done:" in out
        for name in ("dem_mosaic", "wbm_mosaic"):
            assert (tmp_path / "work" / f"{name}.vrt").exists()
            assert (tmp_path / "work" / f"{name}.vrt.sources").exists()
        assert source_count(tmp_path / "work/dem_mosaic.vrt") == 2
        assert source_count(tmp_path / "work/wbm_mosaic.vrt") == 2


class TestFreshnessSkip:
    def test_unchanged_store_skips_rebuild(self, tmp_path):
        make_store(tmp_path)
        run_script(tmp_path)
        dem_vrt = tmp_path / "work/dem_mosaic.vrt"
        wbm_vrt = tmp_path / "work/wbm_mosaic.vrt"
        before = (dem_vrt.stat().st_mtime_ns, wbm_vrt.stat().st_mtime_ns)
        out = run_script(tmp_path)
        assert "mosaics fresh" in out
        assert (dem_vrt.stat().st_mtime_ns, wbm_vrt.stat().st_mtime_ns) == before

    def test_new_tile_triggers_rebuild(self, tmp_path):
        make_store(tmp_path)
        run_script(tmp_path)
        write_tile(tmp_path / "raw/glo30/dem/tile_2_DEM.tif", 12.0, 40.0)
        write_tile(tmp_path / "raw/glo30/wbm/tile_2_WBM.tif", 12.0, 40.0)
        out = run_script(tmp_path)
        assert "done:" in out
        assert source_count(tmp_path / "work/dem_mosaic.vrt") == 3

    def test_deleted_tile_triggers_rebuild(self, tmp_path):
        """Deletion leaves every remaining source OLDER than the VRT, so a pure
        mtime design would skip wrongly — the .sources comparison must catch it."""
        make_store(tmp_path, tile_count=3)
        run_script(tmp_path)
        (tmp_path / "raw/glo30/dem/tile_2_DEM.tif").unlink()
        (tmp_path / "raw/glo30/wbm/tile_2_WBM.tif").unlink()
        out = run_script(tmp_path)
        assert "done:" in out
        assert source_count(tmp_path / "work/dem_mosaic.vrt") == 2
        assert source_count(tmp_path / "work/wbm_mosaic.vrt") == 2

    def test_touched_tile_triggers_rebuild(self, tmp_path):
        """A re-downloaded tile changes no names and no counts — only the
        newer-than-VRT check sees it. One stale side must rebuild BOTH VRTs
        (the pair is consumed together by fuse_heightfield)."""
        make_store(tmp_path)
        run_script(tmp_path)
        dem_vrt = tmp_path / "work/dem_mosaic.vrt"
        wbm_vrt = tmp_path / "work/wbm_mosaic.vrt"
        wbm_before = wbm_vrt.stat().st_mtime_ns
        touched_ns = dem_vrt.stat().st_mtime_ns + 1_000_000_000
        os.utime(tmp_path / "raw/glo30/dem/tile_0_DEM.tif",
                 ns=(touched_ns, touched_ns))
        out = run_script(tmp_path)
        assert "done:" in out
        assert wbm_vrt.stat().st_mtime_ns != wbm_before
