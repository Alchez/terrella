#!/usr/bin/env python3
"""Fuse GLO-30 land elevation with GEBCO bathymetry into one heightfield.

Recipe (decided 2026-07-04, refined same day, see PLAN.md):
  ocean  = WBM class 1, or outside GLO-30 tile coverage (open-ocean cells),
           or WBM lake/river (2/3) within 1 m of sea level - ESA classifies
           coastal lagoons and tidal channels as lake/river; at sea level
           they are visually sea (Chilika, backwaters, Sundarbans)
  sea    = GEBCO upsampled with cubic spline, clamped to <= -1 m
  land   = GLO-30 resampled with area average
Outputs a Float32 heightfield and a Byte ocean mask on the same grid, tiled
with overviews. Runs windowed, so memory stays flat regardless of extent.

Stage-level idempotency: refuses to overwrite an existing output; delete the
files (or choose another --outdir) to redo.

Usage:
  fuse_heightfield.py --bounds W S E N --res-arcsec 3 --outdir data/work/india
"""

import argparse
import sys
from pathlib import Path

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bounds", nargs=4, type=float, required=True,
                    metavar=("W", "S", "E", "N"))
    ap.add_argument("--res-arcsec", type=float, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    args = ap.parse_args()

    tag = f"{args.res_arcsec:g}s".replace(".", "p")
    out_height = args.outdir / f"heightfield_{tag}.tif"
    out_mask = args.outdir / f"oceanmask_{tag}.tif"
    if out_height.exists() or out_mask.exists():
        sys.exit(f"output already exists in {args.outdir} — delete to redo")
    args.outdir.mkdir(parents=True, exist_ok=True)

    transform, width, height = make_grid(args.bounds, args.res_arcsec)
    print(f"target grid: {width} x {height} @ {args.res_arcsec}\"", flush=True)

    profile = dict(
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
         rasterio.open(out_mask, "w", dtype="uint8", **profile) as fm:

        nwin = ((height + BLOCK - 1) // BLOCK) * ((width + BLOCK - 1) // BLOCK)
        done = 0
        for row in range(0, height, BLOCK):
            for col in range(0, width, BLOCK):
                win = Window(col, row,
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
                done += 1
                print(f"[{done}/{nwin}] windows", flush=True)

    for path in (out_height, out_mask):
        with rasterio.open(path, "r+") as ds:
            ds.build_overviews([2, 4, 8, 16, 32], Resampling.average)
    print("complete", flush=True)


if __name__ == "__main__":
    main()
