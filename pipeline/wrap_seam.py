"""Close the one column a global warp cannot fill — where the raster meets itself at ±180.

Warping a global source into EPSG:3857 leaves the easternmost pixel column with nothing to sample.
The source ends at +180 and the resampling kernel wants ground beyond it, which exists only on the
far side of the seam; GDAL has no notion that the two edges are neighbours, so it writes nodata.

THE REASON THAT IS NOT A COSMETIC EDGE CASE is that downstream nothing can tell "missing" from "very
low ground" — they are the same float. Measured on Mars: the elevation ramp painted the column at
the bottom of its scale, the since-deleted `look/hillshade` read it as a 30 km cliff and shadowed the
column BESIDE it, and `tile/terrain_rgb.encode_array` packed it as a real height. One warp artifact,
two adjacent dark columns, a straight line from pole to pole, shipped.

THE FILL IS THE MIDPOINT OF THE TWO NEIGHBOURS, AND THAT IS EXACT RATHER THAN TOLERABLE. The seam
column sits one pixel east of the second-to-last column and one pixel west of column 0, so their
mean is a linear interpolation evaluated exactly where the missing sample belongs — not an
approximation chosen for being cheap. Validated against the 13,594 rows of Mars's seam the warp DID
fill, i.e. against ground truth rather than against taste: median error 5.8 m, p95 52 m, worst
232 m, mean +3.2 m, on terrain spanning 29 km. Filling with zero instead measures 3,008 m median.

WHY THIS REFUSES EVERYWHERE ELSE RATHER THAN FILLING. A general "interpolate every hole" rule
invents ground silently on a body whose source genuinely has gaps, and Earth's land DEM is exactly
such a source — a missing Copernicus tile fuses as ocean with nothing raised. The seam is the one
hole whose neighbours are known to BE its neighbours, because the projection says so. Any other
hole is a data problem to be seen, not smoothed, so this raises instead.
"""

from pathlib import Path

import numpy as np
import rasterio

from pipeline.mercator import MERCATOR_HALF_M
from pipeline.raster_io import band_window, column_window, row_bands

#: Source rows held at once while scanning for holes. At the widest grid this pipeline warps
#: (65536 px) a band of this many float32 rows is ~268 MB, which leaves the one-heavy-job cap room
#: for GDAL's own block cache beside it.
SCAN_ROW_BUDGET = 1024


def spans_the_world(dataset) -> bool:
    """Does this raster cover the whole Mercator plane in longitude, to within one pixel?

    TO WITHIN A PIXEL, NOT TO THE DECIMAL, and the tolerance is the load-bearing part. Earth's
    heightfield overshoots `MERCATOR_HALF_M` by 12.25 m where Mars lands on it exactly, and both are
    global; a test written against the digits would accept one body, reject the other, and describe
    itself as a check on the projection while actually checking whose warp wrote the file.
    """
    span = dataset.bounds.right - dataset.bounds.left
    return abs(span - 2.0 * MERCATOR_HALF_M) <= dataset.res[0]


def close_wrap_seam(raster: Path, band_rows: int = SCAN_ROW_BUDGET) -> int:
    """Fill `raster`'s antimeridian column in place from its two neighbours; return pixels filled.

    IDEMPOTENT BY WAY OF THE DECLARATION, which is what makes it safe in a resumable pipeline: a
    closed raster declares no nodata, so a second call returns 0 without reading a pixel. That also
    makes the postcondition a thing a reader can check — after this, the file SAYS it has no missing
    data, and `terrain_rgb.encode_array`'s NaN-only guard is correct for this body rather than
    accidentally correct because nobody declared a sentinel.

    Raises rather than returns on the two failures that must not pass quietly: a raster that is not
    global (its edges are not neighbours, so there is nothing to interpolate ACROSS) and a hole
    anywhere off the seam (see the module docstring — that is data to look at, not to smooth).
    """
    with rasterio.open(raster, "r+") as dataset:
        missing = dataset.nodata
        if missing is None:
            return 0
        if not spans_the_world(dataset):
            raise SystemExit(
                f"{raster} declares nodata {missing} but spans "
                f"{dataset.bounds.right - dataset.bounds.left:.1f} map units against a world of "
                f"{2 * MERCATOR_HALF_M:.1f} — its east and west edges are not neighbours, so a wrap "
                f"fill would interpolate across ground that is not there")

        width, height = dataset.width, dataset.height
        seam = width - 1
        holes_per_column = np.zeros(width, dtype=np.int64)
        for row0, row1 in row_bands(height, band_rows):
            block = dataset.read(1, window=band_window(width, row0, row1))
            holes_per_column += (block == missing).sum(axis=0)

        off_seam = np.flatnonzero(holes_per_column)
        off_seam = off_seam[off_seam != seam]
        if off_seam.size:
            raise SystemExit(
                f"{raster} has nodata in {off_seam.size} column(s) other than its wrap seam — "
                f"first at column {int(off_seam[0])} ({int(holes_per_column[off_seam[0]])} px), "
                f"{int(holes_per_column.sum() - holes_per_column[seam])} px in total. Only the seam "
                f"has known neighbours; a hole anywhere else is a gap in the source and filling it "
                f"would invent ground. Fix the fusion, do not widen this.")

        filled = int(holes_per_column[seam])
        if filled:
            # Read as float64 before averaging: the raster is float32, and the midpoint of two
            # float32s rounded back to float32 is the value we want written, not an accumulation.
            west = dataset.read(1, window=column_window(height, seam - 1, seam))[:, 0]
            east = dataset.read(1, window=column_window(height, 0, 1))[:, 0]
            column = dataset.read(1, window=column_window(height, seam, width))[:, 0]
            midpoint = 0.5 * (west.astype(np.float64) + east.astype(np.float64))
            column = np.where(column == missing, midpoint, column).astype(dataset.dtypes[0])
            dataset.write(column.reshape(height, 1), 1,
                          window=column_window(height, seam, width))

        # LAST, AND ONLY AFTER THE WRITE. The declaration is the file's claim about its own
        # contents, so clearing it before the fill would leave a window in which a crash produced a
        # raster that reads as complete and is not — the `.done` marker rule, one level down.
        dataset.nodata = None
    return filled
