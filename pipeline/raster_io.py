"""Single home for the raster conventions every windowed writer shares.

Born from PLAN's commonification list (2026-07-23): the same fix has landed at
one call site and been missed at its siblings four separate times — float32 +
windowed reads (composite had it, hillshade didn't), warp-once (lakedepth had
it, snow didn't), NUM_THREADS (warps had it, writers didn't), and the pyright
ignore for rasterio's untyped Window (fuse/render_prep had it, four new sites
didn't). One fix, one home; tests/test_raster_io.py pins the adoption.
"""

from typing import Any, Iterator

from rasterio.windows import Window

# The GTiff FORMAT core the three tile-path writers share (hillshade, shade's
# region writer, shade_planet's composite writer). Deliberately format-only:
# threading (num_threads) is per-call-site policy, because fuse_planet sets
# GDAL_NUM_THREADS=1 on purpose (its parallelism is across cells) and an
# explicit creation option would override it — putting the flag here would
# silently oversubscribe fusion (HISTORY § optimisation #3 landed).
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
