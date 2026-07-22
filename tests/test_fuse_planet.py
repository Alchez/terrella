"""fuse_planet.enforce_land_guard: the output-side check that a tileList-listed land cell
actually fused land. Born 2026-07-22: stale dem/wbm mosaic VRTs made every Antarctic tile
invisible to fusion, the whole continent fused as ocean, and every input-side gate passed —
the tileList preflight checks tiles on DISK, and the in-cell gap check defines land from the
same stale WBM mosaic. The fused ocean mask is the one input that cannot go stale.
"""

import numpy as np
import rasterio
from rasterio.transform import from_bounds

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
        for layer in ("heightfield", "oceanmask", "watermask"):
            assert (chunk / f"{layer}_{fuse_planet.TAG}.tif").exists()
        assert not (chunk / "error.log").exists()

    def test_pure_ocean_fails_deletes_all_outputs_and_names_the_fix(self, tmp_path):
        chunk = _chunk_dir(tmp_path, [[1, 1], [1, 1]])
        assert fuse_planet.enforce_land_guard(chunk) is False
        for layer in ("heightfield", "oceanmask", "watermask"):
            assert not (chunk / f"{layer}_{fuse_planet.TAG}.tif").exists()
        assert "build_mosaics" in (chunk / "error.log").read_text()

    def test_a_guard_failure_reopens_the_resume_slot(self, tmp_path):
        """fuse_cell skips any cell whose heightfield exists — after a guard failure the
        heightfield specifically must be gone, or the next sweep would skip straight over
        the garbage cell instead of retrying it."""
        chunk = _chunk_dir(tmp_path, [[1]])
        fuse_planet.enforce_land_guard(chunk)
        assert not (chunk / f"heightfield_{fuse_planet.TAG}.tif").exists()
