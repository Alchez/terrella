"""Synthesise a water-body mask for the void DEM tiles from ESA WorldCover.

download_cop30_void.py fetches the withheld GLO-30 DEM tiles from OpenTopography, but
OpenTopography serves DEM only — no WBM. Without a WBM, fuse_heightfield's ocean rule
treats WBM-nodata as open ocean, so the whole void re-renders as sea (min -1.0 m in
landlocked Armenia — the bug we are fixing). This builds a stand-in WBM from ESA
WorldCover 2021 class 80 ("permanent water bodies"):

  class 80  -> 2 (inland lake)      everything else -> 0 (land)

No sea (1): the void is landlocked terrain plus the Caspian, which ESA's own WBM also
classes as lake (verified against held tiles: 88-100% class 2, 0% sea), so lake keeps the
Caspian consistent with the rest of the map. No river (3): thin rivers fold into class 80
as lake — the same simplification the Armenia hybrid prototype validated. Water detail
lands at the 1-arcsec grid, matching the standard WBM everywhere else (not WorldCover's
10 m), so the void countries are not anomalously crisp.

One WBM tile per void DEM tile, on that tile's exact grid, into data/raw/cop30_void/wbm/.
build_mosaics.sh globs that dir into the WBM mosaic; fuse_heightfield then runs unchanged.

Reuses snow_mask.py's WorldCover fetch (same bucket, dir, and naming). Idempotent: skips
WBM tiles already built and WorldCover tiles already held; delete data/raw/cop30_void/wbm
to redo.

Usage: python3 build_void_wbm.py
"""

import concurrent.futures as cf
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

from pipeline import paths
from pipeline.fetch import download_one
from pipeline.render.snow_mask import (
    BUCKET_URL,
    WORKERS,
    tiles_for_bounds,
)
from pipeline.render.snow_mask import DATA_DIR as WC_DIR

VOID_DIR = paths.DATA / "raw/cop30_void"
WATER_CLASS = 80   # ESA WorldCover "permanent water bodies"
WBM_LAKE = 2       # fuse_heightfield inland-lake class


def union_bounds(tiles: list[Path]):
    """(west, south, east, north) enclosing every tile — the WorldCover fetch window."""
    west = south = east = north = None
    for tile in tiles:
        with rasterio.open(tile) as dataset:
            bounds = dataset.bounds
        west = bounds.left if west is None else min(west, bounds.left)
        south = bounds.bottom if south is None else min(south, bounds.bottom)
        east = bounds.right if east is None else max(east, bounds.right)
        north = bounds.top if north is None else max(north, bounds.top)
    return west, south, east, north


def ensure_worldcover(bounds) -> Path:
    """Fetch the WorldCover tiles overlapping bounds, build a VRT, return it."""
    names = tiles_for_bounds(*bounds)
    print(f"WorldCover: {len(names)} tiles overlap the void extent", flush=True)
    WC_DIR.mkdir(parents=True, exist_ok=True)
    counts = {"ok": 0, "skipped": 0, "absent": 0}
    failures = []
    with cf.ThreadPoolExecutor(WORKERS) as pool:
        futs = {pool.submit(download_one, f"{BUCKET_URL}/{nm}", WC_DIR / nm,
                            timeout=120, absent_on_404=True): nm
                for nm in names}
        for fut in cf.as_completed(futs):
            status = fut.result()
            if status.startswith("failed"):
                failures.append(f"{futs[fut]}  {status}")
            else:
                counts[status] += 1
    if failures:
        sys.exit("WorldCover downloads failed — rerun to retry:\n  "
                 + "\n  ".join(failures))
    print(f"  fetched {counts['ok']}, held {counts['skipped']}, "
          f"absent {counts['absent']}", flush=True)
    held = [WC_DIR / nm for nm in names if (WC_DIR / nm).exists()]
    if not held:
        sys.exit("no WorldCover tiles over the void extent — bucket/naming changed?")
    if counts["absent"]:
        print(f"  NOTE: {counts['absent']} tiles absent (ocean cells) — any Caspian "
              f"there falls back to land; check the per-tile water% below", flush=True)
    vrt = VOID_DIR / "worldcover_void.vrt"
    subprocess.run(["gdalbuildvrt", "-overwrite", str(vrt)] + [str(path) for path in held],
                   check=True, capture_output=True)
    return vrt


def build_wbm(dem_tile: Path, wbm_tile: Path, wc_vrt: Path) -> int:
    """Warp WorldCover onto the DEM tile grid, threshold class 80. Returns water px."""
    with rasterio.open(dem_tile) as dataset:
        bounds, width, height = dataset.bounds, dataset.width, dataset.height
        crs, transform = dataset.crs, dataset.transform
    # gdalwarp -te/-ts reproduces the DEM grid exactly, so the WBM registers
    # pixel-for-pixel; mode downsamples 10 m classes to the 1-arcsec cell by
    # majority (categorical — never average class codes).
    tmp_cls = wbm_tile.with_name(wbm_tile.name + ".cls.tif.tmp")
    subprocess.run(
        ["gdalwarp", "-overwrite", "-q", "-of", "GTiff",
         "-t_srs", crs.to_wkt(),
         "-te", repr(bounds.left), repr(bounds.bottom), repr(bounds.right), repr(bounds.top),
         "-ts", str(width), str(height), "-r", "mode", "-ot", "Byte",
         "-wm", "512", "-multi", "-wo", "NUM_THREADS=ALL_CPUS",
         str(wc_vrt), str(tmp_cls)], check=True, capture_output=True)
    with rasterio.open(tmp_cls) as class_ds:
        wbm = np.where(class_ds.read(1) == WATER_CLASS, WBM_LAKE, 0).astype("uint8")
    tmp_cls.unlink(missing_ok=True)

    profile: dict[str, Any] = dict(
        driver="GTiff", width=width, height=height, count=1, dtype="uint8",
        crs=crs, transform=transform, tiled=True, blockxsize=512,
        blockysize=512, compress="deflate")
    tmp = wbm_tile.with_name(wbm_tile.name + ".tmp")
    with rasterio.open(tmp, "w", **profile) as out:
        out.write(wbm, 1)
    os.replace(tmp, wbm_tile)
    return int((wbm > 0).sum())


def main() -> int:
    dem_dir, wbm_dir = VOID_DIR / "dem", VOID_DIR / "wbm"
    dem_tiles = sorted(dem_dir.glob("*_DEM.tif"))
    if not dem_tiles:
        sys.exit(f"no void DEM tiles in {dem_dir} — run download_cop30_void.py first")
    wbm_dir.mkdir(parents=True, exist_ok=True)

    wc_vrt = ensure_worldcover(union_bounds(dem_tiles))

    print(f"\nbuilding {len(dem_tiles)} WBM tiles:", flush=True)
    for dem_tile in dem_tiles:
        wbm_tile = wbm_dir / dem_tile.name.replace("_DEM", "_WBM")
        if wbm_tile.exists():
            print(f"  {wbm_tile.name}  skipped (exists)", flush=True)
            continue
        px = build_wbm(dem_tile, wbm_tile, wc_vrt)
        with rasterio.open(dem_tile) as dataset:
            tot = dataset.width * dataset.height
        print(f"  {wbm_tile.name}  water {px:,} px ({100 * px / tot:.1f}%)", flush=True)
    print("complete", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
