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
    """Source-scan drift guards: the three tile writers carry the shared core,
    and fusion's writers never gain the threading flag."""

    @pytest.mark.parametrize("relative", ["render/hillshade.py", "tile/shade.py",
                                          "tile/shade_planet.py"])
    def test_tile_writers_use_the_shared_core(self, relative):
        assert "**GTIFF_CREATE" in (PIPELINE / relative).read_text()

    @pytest.mark.parametrize("relative", ["fuse/fuse_planet.py", "fuse/fuse_heightfield.py"])
    def test_fusion_writers_stay_unthreaded(self, relative):
        assert "num_threads" not in (PIPELINE / relative).read_text()
