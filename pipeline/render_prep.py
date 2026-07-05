#!/usr/bin/env python3
"""Prepare fused heightfield + ocean mask for Blender rendering.

Warps both rasters from EPSG:4326 (degrees; east-west stretched away from the
equator) into an Albers equal-area conic projection centered on the frame, so
one pixel covers the same ground distance everywhere and terrain is not
distorted. Downsamples to a Blender-friendly texture size and writes plain
Float32 / Byte TIFFs (Blender reads float TIFFs; remember to set the image to
Non-Color in the shader).

Heights stay in real meters; vertical exaggeration is applied in Blender.

Stage-level idempotency: refuses to overwrite existing outputs.

Usage:
  render_prep.py --heightfield data/work/india/heightfield_3s.tif \
                 --mask data/work/india/oceanmask_3s.tif \
                 --outdir data/work/india/render [--width 16384]
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds
from rasterio.windows import Window

# Albers equal-area conic for the India frame (66-99E / 4-38N): standard
# parallels at ~1/6 in from the frame's latitude edges, origin at frame center.
DST_CRS = "+proj=aea +lat_1=10 +lat_2=32 +lat_0=21 +lon_0=82.5 +datum=WGS84 +units=m"

BLOCK = 8192


def warp(src_path, out_path, transform, width, height, resampling, dtype, predictor):
    profile = dict(
        driver="GTiff", crs=DST_CRS, transform=transform,
        width=width, height=height, count=1, dtype=dtype,
        tiled=True, blockxsize=512, blockysize=512,
        compress="deflate", predictor=predictor, bigtiff="if_safer",
    )
    with rasterio.open(src_path) as src, \
         WarpedVRT(src, crs=DST_CRS, transform=transform, width=width,
                   height=height, resampling=resampling) as vrt, \
         rasterio.open(out_path, "w", **profile) as out:
        for row in range(0, height, BLOCK):
            for col in range(0, width, BLOCK):
                win = Window(col, row,
                             min(BLOCK, width - col), min(BLOCK, height - row))
                out.write(vrt.read(1, window=win).astype(dtype), 1, window=win)
    print(f"wrote {out_path}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--heightfield", type=Path, required=True)
    ap.add_argument("--mask", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--width", type=int, default=16384)
    args = ap.parse_args()

    out_h = args.outdir / "heightfield_aea.tif"
    out_m = args.outdir / "oceanmask_aea.tif"
    if out_h.exists() or out_m.exists():
        sys.exit(f"output already exists in {args.outdir} — delete to redo")
    args.outdir.mkdir(parents=True, exist_ok=True)

    with rasterio.open(args.heightfield) as src:
        left, bottom, right, top = transform_bounds(
            src.crs, DST_CRS, *src.bounds, densify_pts=64)
    xres = (right - left) / args.width
    height = round((top - bottom) / xres)
    transform = from_origin(left, top, xres, xres)
    print(f"projected grid: {args.width} x {height}, {xres:.0f} m/px", flush=True)

    warp(args.heightfield, out_h, transform, args.width, height,
         Resampling.bilinear, "float32", 3)
    warp(args.mask, out_m, transform, args.width, height,
         Resampling.nearest, "uint8", 2)
    print("complete", flush=True)


if __name__ == "__main__":
    main()
