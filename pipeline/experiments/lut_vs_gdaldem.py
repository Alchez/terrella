#!/usr/bin/env python3
"""Go/no-go: does the LUT reproduce `gdaldem color-relief` on the real 12.19 Gpx planet?

ARCHIVED — A RECORD OF METHOD, NOT A RUNNABLE CHECK. `compare()` reads
`land_3857.tif` / `sea_3857.tif`, and those were deleted along with the
color-relief stage they came from, so this cannot execute again without re-adding that stage.
It is kept because it lived only in gitignored `data/work/_profile/` and was tracked nowhere:
the "a superseded path gets deleted, git is the archive" rule explicitly does not apply under
`data/`, where deletion is permanent. Rescued here when that directory was reclaimed, so the
oracle's DESIGN survives even though its inputs do not — this is the script behind the decision
to delete the `gdaldem color-relief` stage in favour of a LUT.

The oracle is INDEPENDENT and PRE-EXISTING: land_3857.tif / sea_3857.tif were written by gdaldem
during the pass, before this LUT was designed. They are not fixtures built to agree.

Also measures the LUT's own wall clock, so "how much does deleting the stage save" is a
measurement rather than a projection. NOTE the honest caveat: this script WRITES both rasters so
they can be compared, which the real design does not -- inside composite() the LUT is applied to a
window already in RAM and nothing is written. So the timing here is an UPPER bound on the real cost.
"""

import resource
import sys
import time

import numpy as np
import rasterio
from rasterio.windows import Window

# Import, never retype: bug 7 of the day was a hand-typed constant. These come from the modules
# that actually run in production.
from pipeline.render import palette
from pipeline.tile.shade_planet import WINDOW_ROWS

HEIGHT = "data/work/planet_tiles/height_3857.tif"
OUTS = {"land": "data/work/_profile/lut_land.tif", "sea": "data/work/_profile/lut_sea.tif"}


def build() -> float:
    luts = {kind: palette.relief_lut(kind) for kind in OUTS}
    print(f"LUT sizes: " + ", ".join(f"{k}={v.shape} ({v.nbytes/1024:.1f} KB)"
                                     for k, v in luts.items()), flush=True)
    started = time.time()
    with rasterio.open(HEIGHT) as src:
        profile = dict(driver="GTiff", width=src.width, height=src.height, count=3,
                       dtype="uint8", crs=src.crs, transform=src.transform, tiled=True,
                       blockxsize=512, blockysize=512, compress="deflate", BIGTIFF="YES")
        writers = {k: rasterio.open(p, "w", **profile) for k, p in OUTS.items()}
        try:
            for row0 in range(0, src.height, WINDOW_ROWS):
                row1 = min(src.height, row0 + WINDOW_ROWS)
                window = Window(0, row0, src.width, row1 - row0)
                heights = src.read(1, window=window)
                for kind, writer in writers.items():
                    writer.write(palette.lut_lookup(luts[kind], kind, heights), window=window)
                del heights
                if row0 % (WINDOW_ROWS * 80) == 0:
                    print(f"  {row0/src.height*100:5.1f}%", flush=True)
        finally:
            for writer in writers.values():
                writer.close()
    elapsed = time.time() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024
    print(f"\nLUT pass (BOTH surfaces, one read of height): {elapsed:.1f}s  peak RSS {peak:.2f} GiB")
    print(f"  gdaldem baseline for the same work: 751s + 948s = 1699s (two reads of height)")
    print(f"  -> {1699/elapsed:.1f}x faster, and the real design also drops the writes\n")
    return elapsed


def compare() -> int:
    from pipeline.verify import compare_rasters
    failures = []
    for kind, path in OUTS.items():
        reference = f"data/work/planet_tiles/{kind}_3857.tif"
        print(f"=== {kind}: gdaldem ({reference}) vs LUT ===")
        for band in (1, 2, 3):
            result = compare_rasters(reference, path, tolerance=1, band=band)
            print(f"-- band {band} --")
            print(result.report())
            print()
            if not result.within_tolerance:
                failures.append(f"{kind} band {band}: {result.beyond_tolerance:,} px beyond 1 DN")
    if failures:
        for failure in failures:
            print(f"FAILED: {failure}")
        return 1
    print("GO: the LUT reproduces gdaldem within the uint8 contract. The stage is deletable.")
    return 0


if __name__ == "__main__":
    if "--compare-only" not in sys.argv:
        build()
    raise SystemExit(compare())
