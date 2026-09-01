"""Single home for the raster conventions every windowed writer shares.

The same fix has landed at one call site and been missed at its siblings four separate times —
float32 + windowed reads (composite had it, hillshade didn't), warp-once (lakedepth had it, snow
didn't), NUM_THREADS (warps had it, writers didn't), and the pyright ignore for rasterio's untyped
Window (fuse/render_prep had it, four new sites didn't). One fix, one home; tests/test_raster_io.py
pins the adoption.
"""

from collections.abc import Iterator
from typing import Any

from rasterio.windows import Window

# The GTiff FORMAT core the tile-path writers share: `prep_block`, `prep_cap`,
# `block_render`, `relief_scan` and `terrain_rgb`, the list
# `test_raster_io.test_tile_writers_use_the_shared_core` curates.
# Deliberately format-only:
# threading (num_threads) is per-call-site policy, because fuse_planet sets
# GDAL_NUM_THREADS=1 on purpose (its parallelism is across cells) and an
# explicit creation option would override it — putting the flag here would
# silently oversubscribe fusion
GTIFF_CREATE: dict[str, Any] = {
    "tiled": True, "blockxsize": 512, "blockysize": 512, "compress": "deflate"}


def row_bands(height: int, band_rows: int, start: int = 0) -> Iterator[tuple[int, int]]:
    """Yield (row0, row1) full-width row bands covering rows start..height.

    The final band is short when band_rows does not divide the span — the min()
    every call site used to hand-roll, and the off-by-one a new sibling gets
    wrong once.
    """
    for row0 in range(start, height, band_rows):
        yield row0, min(height, row0 + band_rows)


def band_window(width: int, row0: int, row1: int) -> Window:
    """A full-width rasterio Window over rows row0..row1.

    Also the single home of the pyright ignore for rasterio's Window: it ships
    no py.typed and its old-style attrs __init__ is invisible to the checker.
    """
    return Window(0, row0, width, row1 - row0)  # pyright: ignore[reportCallIssue]


def column_window(height: int, col0: int, col1: int) -> Window:
    """A full-height rasterio Window over columns col0..col1 — `band_window` transposed.

    Here rather than at its caller for the reason in the module docstring: this is the second shape
    of window this pipeline builds, and the pyright ignore above is only a single home while every
    shape is built through this module.
    """
    return Window(col0, 0, col1 - col0, height)  # pyright: ignore[reportCallIssue]
