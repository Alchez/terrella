#!/usr/bin/env python3
"""Download the global GEBCO_2026 bathymetry grid and build its mosaic VRT.

The one-time global bootstrap for the sea half of the heightfield (the land
half is per-country GLO-30 via download_glo30.py). fuse_heightfield.py reads
data/raw/gebco/gebco_2026_global.vrt; this script fetches the 8 GeoTIFF tiles
that VRT indexes and (re)builds it.

The grid is GEBCO_2026 "ice surface elevation" (land + ice-sheet *surface*,
not sub-ice bedrock) at 15 arc-seconds, distributed as 8 tiles of 90x90
degrees that tile the globe. Files stream from CEDA over plain HTTPS,
WORKERS at a time, reusing download_glo30.download_one: each streams to a
.part name, is size-checked against Content-Length, then atomically renamed,
so a file under its final name is always complete and re-runs skip it. Unlike
GLO-30's unversioned S3 bucket (which needs an ETag oracle), the edition here
is pinned by the versioned URL path (gebco_2026/ice_surface_elevation) — the
same self-pinning WorldCover uses; a renamed/withdrawn tile 404s and aborts
the run loudly (the naming-drift oracle).

Idempotent: with all 8 tiles present it only rebuilds the VRT (instant — a
VRT is a small XML index, no pixel data). ~7.5 GB of tiles on disk.

Usage: python3 download_gebco.py
"""

import concurrent.futures as cf
import subprocess
import sys

import rasterio

from pipeline import paths
from pipeline.acquire.download_glo30 import download_one

BASE_URL = ("https://dap.ceda.ac.uk/bodc/gebco/global/gebco_2026"
            "/ice_surface_elevation/geotiff")
DATA_DIR = paths.DATA / "raw/gebco"
VRT_PATH = DATA_DIR / "gebco_2026_global.vrt"
NODATA = -32767  # GEBCO_2026 Int16 fill; must match fuse_heightfield's read
WORKERS = 4

# The 8 tiles that tile the globe: two 90-degree latitude bands x four
# longitude quadrants. Names match the bucket's convention exactly.
LAT_BANDS = ((90, 0), (0, -90))
LON_BANDS = ((-180, -90), (-90, 0), (0, 90), (90, 180))
TILES = [f"gebco_2026_n{north}.0_s{south}.0_w{west}.0_e{east}.0_geotiff.tif"
         for north, south in LAT_BANDS for west, east in LON_BANDS]


def build_vrt() -> None:
    """Rebuild the global mosaic VRT over exactly the 8 tiles."""
    tifs = [str(DATA_DIR / tile) for tile in TILES]
    subprocess.run(["gdalbuildvrt", "-overwrite", "-vrtnodata", str(NODATA),
                    str(VRT_PATH), *tifs], check=True)
    with rasterio.open(VRT_PATH) as vrt_ds:
        bounds = vrt_ds.bounds
    print(f"built {VRT_PATH.name}: {vrt_ds.width} x {vrt_ds.height}, "
          f"bounds ({bounds.left:g}, {bounds.bottom:g}, {bounds.right:g}, {bounds.top:g})",
          flush=True)


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    jobs = [(f"{BASE_URL}/{tile}", DATA_DIR / tile) for tile in TILES]
    print(f"{len(jobs)} GEBCO_2026 ice-surface tiles -> {DATA_DIR}", flush=True)

    counts = {"ok": 0, "skipped": 0}
    failures: list[str] = []
    with cf.ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(download_one, url, dest): url
                   for url, dest in jobs}
        for fut in cf.as_completed(futures):
            status = fut.result()
            if status.startswith("failed"):
                failures.append(f"{futures[fut]}  {status}")
            else:
                counts[status] += 1
            print(f"ok={counts['ok']} skipped={counts['skipped']} "
                  f"failed={len(failures)}", flush=True)

    if failures:
        print("\n".join(failures), file=sys.stderr)
        sys.exit(f"{len(failures)} tile(s) failed — the versioned CEDA path may "
                 f"have moved (edition change); stop and check before rerunning")

    build_vrt()
    print("complete", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
