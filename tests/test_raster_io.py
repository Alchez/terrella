"""pipeline/raster_io: the single home for the shared GTiff format core and the
full-width band-window arithmetic (.

The drift these guard is four-times observed: the same fix landing at one call
site and missing its siblings (float32+windows, warp-once, NUM_THREADS, the
rasterio-Window pyright ignore). The source-scan tests pin the adoption — a
site quietly re-inlining its own copy fails here, not on a planet pass.
"""

from pathlib import Path

import pytest
from rasterio.windows import Window

from pipeline.raster_io import GTIFF_CREATE, band_window, row_bands

PIPELINE = Path(__file__).resolve().parents[1] / "pipeline"


class TestRowBands:
    def test_exact_division(self):
        assert list(row_bands(512, 256)) == [(0, 256), (256, 512)]

    def test_short_last_band(self):
        assert list(row_bands(500, 256)) == [(0, 256), (256, 500)]

    def test_single_short_raster(self):
        assert list(row_bands(100, 256)) == [(0, 100)]

    def test_start_offset(self):
        assert list(row_bands(500, 256, start=256)) == [(256, 500)]

    def test_empty_raster(self):
        assert list(row_bands(0, 256)) == []

    def test_bands_tile_the_range_exactly(self):
        """Every row appears exactly once, in order — the property the hand-rolled
        min() at each call site was implementing."""
        covered = [row for row0, row1 in row_bands(1013, 97) for row in range(row0, row1)]
        assert covered == list(range(1013))


class TestBandWindow:
    def test_equals_hand_rolled(self):
        assert band_window(131072, 128, 256) == Window(0, 128, 131072, 128)  # pyright: ignore[reportCallIssue]

    def test_full_width_at_origin(self):
        window = band_window(64, 0, 8)
        assert (window.col_off, window.row_off, window.width, window.height) == (0, 0, 64, 8)


class TestGtiffCreate:
    def test_format_core_pinned(self):
        assert GTIFF_CREATE == {"tiled": True, "blockxsize": 512,
                                "blockysize": 512, "compress": "deflate"}

    def test_threading_stays_per_call_site(self):
        """num_threads must NEVER enter the shared core: fuse_planet sets
        GDAL_NUM_THREADS=1 on purpose (its parallelism is across cells) and an
        explicit creation option would override it — oversubscribing fusion."""
        assert "num_threads" not in GTIFF_CREATE


class TestAdoption:
    """Source-scan drift guards: every tile writer carries the shared core, and fusion's writers
    never gain the threading flag.

    The planet shader and its compositor both left this list when the composite did. Neither
    wrote a raster afterwards — one warps and cuts through GDAL subprocesses, the other had become a
    constants module — so requiring the core of either would have pinned a string no call site can
    carry. `tile/shade.py` has since been deleted too, its lake ramp moving to `look/lake_depth.py`
    and its Mercator constant to `mercator.py`. `look/hillshade.py` left the list by being deleted,
    as the composite's last unimported leaf.

    IT HAD DRIFTED TO ONE MEMBER AND THAT ONE WAS THE DELETED MODULE, so five real tile writers were
    unwatched while the guard read as live. THE LIST IS CURATED RATHER THAN DERIVED, deliberately: a
    scan for `rasterio.open(..., "w")` across the package returns eighteen modules, and ten of them
    — the acquirers, the fusers, the hero-path masks — correctly carry no creation core, because the
    subject here is the tile pyramid's own writers and not every raster writer. Adding a tile writer
    means adding it here; that is the cost of a subject the code cannot name.
    """

    @pytest.mark.parametrize("relative", ["render/prep_block.py", "render/prep_cap.py",
                                          "tile/block_render.py", "tile/relief_scan.py",
                                          "tile/terrain_rgb.py"])
    def test_tile_writers_use_the_shared_core(self, relative):
        assert "GTIFF_CREATE" in (PIPELINE / relative).read_text()

    @pytest.mark.parametrize("relative", ["fuse/fuse_planet.py", "fuse/fuse_heightfield.py"])
    def test_fusion_writers_stay_unthreaded(self, relative):
        assert "num_threads" not in (PIPELINE / relative).read_text()
