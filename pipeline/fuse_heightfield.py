#!/usr/bin/env python3
"""Fuse GLO-30 land elevation with GEBCO bathymetry into one heightfield.

Recipe (decided 2026-07-04, refined same day, see PLAN.md):
  ocean  = WBM class 1, or outside GLO-30 tile coverage (open-ocean cells),
           or WBM lake/river (2/3) within 1 m of sea level - ESA classifies
           coastal lagoons and tidal channels as lake/river; at sea level
           they are visually sea (Chilika, backwaters, Sundarbans)
  sea    = GEBCO upsampled with cubic spline, clamped to <= -1 m
  land   = GLO-30 resampled with area average
Outputs, on the same grid, tiled with overviews:
  heightfield_{tag}.tif  Float32 fused elevation
  oceanmask_{tag}.tif    Byte 0/1 — drives the land/sea material split
  watermask_{tag}.tif    Byte 4-class: 0 land, 1 ocean, 2 inland lake,
                         3 inland river (WBM water the ocean rule did not
                         absorb; class 1 is pixel-identical to the ocean mask)
Runs windowed, so memory stays flat regardless of extent.

Stage-level idempotency: refuses to overwrite an existing output; delete the
files (or choose another --outdir) to redo. --watermask-only backfills just
the water mask next to existing outputs without recomputing anything else.

Usage:
  fuse_heightfield.py --bounds W S E N --res-arcsec 3 --outdir data/work/india
  fuse_heightfield.py --res-arcsec 3 --outdir data/work/india --watermask-only
"""

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window
from rasterio.enums import Resampling

DATA = Path.home() / "projects/maps/data"
DEM_VRT = DATA / "work/dem_mosaic.vrt"
WBM_VRT = DATA / "work/wbm_mosaic.vrt"
GEBCO = DATA / "raw/gebco/gebco_2026_n40.0_s0.0_w60.0_e100.0_geotiff.tif"

DEM_NODATA = -9999  # VRT fill where no GLO-30 tile exists
WBM_NODATA = 255
BLOCK = 8192  # processing window size in pixels


def make_grid(bounds, res_arcsec):
    west, south, east, north = bounds
    res = res_arcsec / 3600.0
    width = round((east - west) / res)
    height = round((north - south) / res)
    return from_origin(west, north, res, res), width, height


def classify_water(ocean, wbm):
    """4-class water mask: 0 land, 1 ocean, 2 inland lake, 3 inland river.

    Inland = WBM lake/river that the ocean rule did not absorb, so class 1
    stays pixel-identical to the ocean mask by construction."""
    out = np.zeros(wbm.shape, dtype="uint8")
    out[ocean] = 1
    out[(wbm == 2) & ~ocean] = 2
    out[(wbm == 3) & ~ocean] = 3
    return out


def print_class_counts(counts):
    total = counts.sum()
    for code, name in enumerate(("land", "ocean", "lake", "river")):
        print(f"  {code} {name:6s}: {counts[code]:>13,} px "
              f"{100.0 * counts[code] / total:6.2f}%", flush=True)


def backfill_watermask(mask_path, out_water):
    """Write the water mask next to a finished fusion, reusing its ocean mask.

    Rereads only the WBM; taking the ocean classification from the stored
    mask (rather than re-deriving it from DEM + WBM) means the two masks
    cannot drift."""
    with rasterio.open(mask_path) as ms:
        profile = ms.profile
        vrt_kw = dict(crs=ms.crs, transform=ms.transform,
                      width=ms.width, height=ms.height)
        height, width = ms.height, ms.width
    profile.update(bigtiff="if_safer")

    counts = np.zeros(4, dtype=np.int64)
    with rasterio.open(mask_path) as ms, \
         rasterio.open(WBM_VRT) as wbm_src, \
         WarpedVRT(wbm_src, resampling=Resampling.nearest, **vrt_kw) as wbm, \
         rasterio.open(out_water, "w", **profile) as fw:
        nwin = ((height + BLOCK - 1) // BLOCK) * ((width + BLOCK - 1) // BLOCK)
        done = 0
        for row in range(0, height, BLOCK):
            for col in range(0, width, BLOCK):
                win = Window(col, row,  # pyright: ignore[reportCallIssue] — rasterio untyped, attrs init invisible
                             min(BLOCK, width - col), min(BLOCK, height - row))
                wm = classify_water(ms.read(1, window=win) == 1,
                                    wbm.read(1, window=win))
                fw.write(wm, 1, window=win)
                counts += np.bincount(wm.ravel(), minlength=4)
                done += 1
                print(f"[{done}/{nwin}] windows", flush=True)
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bounds", nargs=4, type=float,
                    metavar=("W", "S", "E", "N"))
    ap.add_argument("--res-arcsec", type=float, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--watermask-only", action="store_true",
                    help="backfill the water mask from an existing fusion")
    args = ap.parse_args()

    tag = f"{args.res_arcsec:g}s".replace(".", "p")
    out_height = args.outdir / f"heightfield_{tag}.tif"
    out_mask = args.outdir / f"oceanmask_{tag}.tif"
    out_water = args.outdir / f"watermask_{tag}.tif"

    if args.watermask_only:
        if out_water.exists():
            sys.exit(f"{out_water} already exists — delete to redo")
        if not out_mask.exists():
            sys.exit(f"{out_mask} not found — run the full fusion first")
        counts = backfill_watermask(out_mask, out_water)
        print_class_counts(counts)
        with rasterio.open(out_water, "r+") as ds:
            ds.build_overviews([2, 4, 8, 16, 32], Resampling.nearest)
        print("complete", flush=True)
        return

    if args.bounds is None:
        ap.error("--bounds is required for a full fusion run")
    if out_height.exists() or out_mask.exists() or out_water.exists():
        sys.exit(f"output already exists in {args.outdir} — delete to redo")
    args.outdir.mkdir(parents=True, exist_ok=True)

    transform, width, height = make_grid(args.bounds, args.res_arcsec)
    print(f"target grid: {width} x {height} @ {args.res_arcsec}\"", flush=True)

    profile: dict[str, Any] = dict(
        driver="GTiff", crs="EPSG:4326", transform=transform,
        width=width, height=height, count=1,
        tiled=True, blockxsize=512, blockysize=512, compress="deflate",
        bigtiff="if_safer",
    )
    vrt_kw = dict(crs="EPSG:4326", transform=transform,
                  width=width, height=height)

    with rasterio.open(DEM_VRT) as dem_src, \
         rasterio.open(WBM_VRT) as wbm_src, \
         rasterio.open(GEBCO) as geb_src, \
         WarpedVRT(dem_src, resampling=Resampling.average, **vrt_kw) as dem, \
         WarpedVRT(wbm_src, resampling=Resampling.nearest, **vrt_kw) as wbm, \
         WarpedVRT(geb_src, resampling=Resampling.cubic_spline, **vrt_kw) as geb, \
         rasterio.open(out_height, "w", dtype="float32", predictor=3,
                       **profile) as fh, \
         rasterio.open(out_mask, "w", dtype="uint8", **profile) as fm, \
         rasterio.open(out_water, "w", dtype="uint8", **profile) as fw:

        nwin = ((height + BLOCK - 1) // BLOCK) * ((width + BLOCK - 1) // BLOCK)
        done = 0
        counts = np.zeros(4, dtype=np.int64)
        for row in range(0, height, BLOCK):
            for col in range(0, width, BLOCK):
                win = Window(col, row,  # pyright: ignore[reportCallIssue] — rasterio untyped, attrs init invisible
                             min(BLOCK, width - col), min(BLOCK, height - row))
                d = dem.read(1, window=win)
                w = wbm.read(1, window=win)
                g = geb.read(1, window=win)

                land = np.where(d == DEM_NODATA, 0, d)
                coastal_water = ((w == 2) | (w == 3)) & (np.abs(land) <= 1.0)
                ocean = (w == 1) | (w == WBM_NODATA) | coastal_water
                fused = np.where(ocean, np.minimum(g, -1.0), land)

                fh.write(fused.astype("float32"), 1, window=win)
                fm.write(ocean.astype("uint8"), 1, window=win)
                wm = classify_water(ocean, w)
                fw.write(wm, 1, window=win)
                counts += np.bincount(wm.ravel(), minlength=4)
                done += 1
                print(f"[{done}/{nwin}] windows", flush=True)

    print_class_counts(counts)
    # class codes must not be averaged — a 2 next to a 0 is not a 1
    for path, rs in ((out_height, Resampling.average),
                     (out_mask, Resampling.average),
                     (out_water, Resampling.nearest)):
        with rasterio.open(path, "r+") as ds:
            ds.build_overviews([2, 4, 8, 16, 32], rs)
    print("complete", flush=True)


if __name__ == "__main__":
    main()
