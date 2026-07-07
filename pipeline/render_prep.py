#!/usr/bin/env python3
"""Prepare fused heightfield + ocean mask for Blender rendering.

Warps both rasters from EPSG:4326 (degrees; east-west stretched away from the
equator) into an Albers equal-area conic projection centered on the frame, so
one pixel covers the same ground distance everywhere and terrain is not
distorted. Downsamples to a Blender-friendly texture size and writes plain
Float32 / Byte TIFFs (Blender reads float TIFFs; remember to set the image to
Non-Color in the shader).

Heights stay in real meters; vertical exaggeration is applied in Blender.

With --watermask (the 4-class mask from fusion) it additionally emits
watermask_aea.tif plus the shader-facing binary masks inlandlake_aea.png and
river_aea.png — 0/255, because Blender divides 8-bit images by 255 on load.

Per-output idempotency: existing outputs are skipped, never overwritten, so
new outputs can be backfilled next to old ones. When heightfield_aea.tif
already exists the grid is taken from it, not re-derived, so backfilled masks
stay aligned with any render already made from it.

Usage:
  render_prep.py --heightfield data/work/india/heightfield_3s.tif \
                 --mask data/work/india/oceanmask_3s.tif \
                 [--watermask data/work/india/watermask_3s.tif] \
                 --outdir data/work/india/render [--width 16384]
"""

import argparse
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


def write_class_png(watermask_path, out_path, cls):
    """Binary 0/255 PNG for one water class of the warped 4-class mask."""
    with rasterio.open(watermask_path) as src:
        binary = (src.read(1) == cls).astype("uint8") * 255
        profile = dict(driver="PNG", width=src.width, height=src.height,
                       count=1, dtype="uint8",
                       crs=src.crs, transform=src.transform)
    with rasterio.open(out_path, "w", **profile) as out:
        out.write(binary, 1)
    print(f"wrote {out_path} ({int((binary > 0).sum()):,} px set)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--heightfield", type=Path, required=True)
    ap.add_argument("--mask", type=Path, required=True)
    ap.add_argument("--watermask", type=Path,
                    help="4-class water mask; adds watermask_aea.tif + "
                         "inlandlake_aea.png + river_aea.png")
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--width", type=int, default=16384)
    args = ap.parse_args()

    out_h = args.outdir / "heightfield_aea.tif"
    out_m = args.outdir / "oceanmask_aea.tif"
    out_w = args.outdir / "watermask_aea.tif"
    args.outdir.mkdir(parents=True, exist_ok=True)

    if out_h.exists():
        with rasterio.open(out_h) as f:
            transform, width, height = f.transform, f.width, f.height
        print(f"grid from existing {out_h.name}: {width} x {height}, "
              f"{transform.a:.0f} m/px (--width ignored)", flush=True)
    else:
        with rasterio.open(args.heightfield) as src:
            left, bottom, right, top = transform_bounds(
                src.crs, DST_CRS, *src.bounds, densify_pts=64)
        width = args.width
        xres = (right - left) / width
        height = round((top - bottom) / xres)
        transform = from_origin(left, top, xres, xres)
        print(f"projected grid: {width} x {height}, {xres:.0f} m/px",
              flush=True)

    wrote = 0
    for src_path, out_path, rs, dtype, pred in (
            (args.heightfield, out_h, Resampling.bilinear, "float32", 3),
            (args.mask, out_m, Resampling.nearest, "uint8", 2),
            (args.watermask, out_w, Resampling.nearest, "uint8", 2)):
        if src_path is None:
            continue
        if out_path.exists():
            print(f"{out_path.name} exists — skipping", flush=True)
            continue
        warp(src_path, out_path, transform, width, height, rs, dtype, pred)
        wrote += 1

    if args.watermask:
        for cls, name in ((2, "inlandlake_aea.png"), (3, "river_aea.png")):
            out_png = args.outdir / name
            if out_png.exists():
                print(f"{name} exists — skipping", flush=True)
                continue
            write_class_png(out_w, out_png, cls)
            wrote += 1

    print("complete" if wrote else "nothing to do — all outputs exist",
          flush=True)


if __name__ == "__main__":
    main()
