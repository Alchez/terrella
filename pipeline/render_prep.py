#!/usr/bin/env python3
"""Prepare fused heightfield + ocean mask for Blender rendering.

Warps both rasters from EPSG:4326 (degrees; east-west stretched away from the
equator) into an Albers equal-area conic projection centered on the frame, so
one pixel covers the same ground distance everywhere and terrain is not
distorted. Downsamples to a Blender-friendly texture size and writes plain
Float32 / Byte TIFFs (Blender reads float TIFFs; remember to set the image to
Non-Color in the shader).

Heights stay in real meters; vertical exaggeration is applied in Blender.

The projection is built per frame with --frame W S E N (the padded lon/lat
window from frame_country.py): standard parallels 1/6 in from the frame's
latitude edges, origin at the frame center. Every derivation is spelled out
in docs/framing-math.md.

Also emits frame.json — the per-country numbers the Blender stages need
(scene_build.py runs inside Blender's Python, which cannot read geographic
metadata, and overlay_borders.py must model the camera identically). A
hand-authored frame.json is never overwritten: that is the pinning mechanism
for frames whose renders predate the formulas (India v3).

Every mask the shader consumes is also emitted as a 0/255 PNG (Blender
divides 8-bit images by 255 on load): oceanmask_aea.png always, and with
--watermask (the 4-class mask from fusion) additionally watermask_aea.tif
plus inlandlake_aea.png and river_aea.png.

Per-output idempotency: existing outputs are skipped, never overwritten, so
new outputs can be backfilled next to old ones. When heightfield_aea.tif
already exists the grid AND projection are taken from it, not re-derived
(--frame is then unneeded), so backfilled outputs stay aligned with any
render already made from it.

Usage:
  render_prep.py --heightfield data/work/nepal/heightfield_3s.tif \
                 --mask data/work/nepal/oceanmask_3s.tif \
                 --frame 79.6 25.9 88.7 31.0 \
                 [--watermask data/work/nepal/watermask_3s.tif] \
                 --outdir data/work/nepal/render [--width 16384]
"""

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds
from rasterio.windows import Window

EXAGGERATION = 15.0    # locked global vertical exaggeration (PLAN.md)
FRAME_MARGIN = 1.0006  # camera overshoot: the plane underfills the frame a hair
HERO_LONG_EDGE = 7680  # hero render long edge in px; the short axis follows
                       # raster aspect (a tall country caps at 7680 tall, not
                       # 7680 wide — Maldives would be 56k px otherwise)

BLOCK = 8192


def aea_crs(frame):
    """Albers equal-area conic centered on a (W, S, E, N) lon/lat frame:
    standard parallels 1/6 in from the latitude edges, origin at center."""
    w, s, e, n = frame
    return (f"+proj=aea +lat_1={s + (n - s) / 6.0:g} "
            f"+lat_2={n - (n - s) / 6.0:g} "
            f"+lat_0={(s + n) / 2.0:g} +lon_0={(w + e) / 2.0:g} "
            f"+datum=WGS84 +units=m")


def scene_numbers(width_px, height_px, extent_w_m, hero_long_edge=HERO_LONG_EDGE):
    """Blender scene numbers for a warped grid (docs/framing-math.md).

    The displacement plane is always 2 Blender units wide, so one unit is
    half the frame width in meters — every number here is that conversion
    applied to the locked global look constants. The render resolution puts
    hero_long_edge on the grid's longer axis; for landscape grids this is
    identical to the retired fixed-width rule."""
    plane_h = 2.0 * height_px / width_px
    if height_px > width_px:
        res = dict(res_x=round(hero_long_edge * width_px / height_px),
                   res_y=hero_long_edge)
    else:
        res = dict(res_x=hero_long_edge,
                   res_y=round(hero_long_edge * height_px / width_px))
    return dict(
        plane_height_units=plane_h,
        ortho_scale=max(2.0, plane_h) * FRAME_MARGIN,
        displacement_scale=EXAGGERATION / (extent_w_m / 2.0),
        **res,
    )


def warp(src_path, out_path, dst_crs, transform, width, height, resampling,
         dtype, predictor):
    profile: dict[str, Any] = dict(
        driver="GTiff", crs=dst_crs, transform=transform,
        width=width, height=height, count=1, dtype=dtype,
        tiled=True, blockxsize=512, blockysize=512,
        compress="deflate", predictor=predictor, bigtiff="if_safer",
    )
    with rasterio.open(src_path) as src, \
         WarpedVRT(src, crs=dst_crs, transform=transform, width=width,
                   height=height, resampling=resampling) as vrt, \
         rasterio.open(out_path, "w", **profile) as out:
        for row in range(0, height, BLOCK):
            for col in range(0, width, BLOCK):
                win = Window(col, row,  # pyright: ignore[reportCallIssue] — rasterio untyped, attrs init invisible
                             min(BLOCK, width - col), min(BLOCK, height - row))
                out.write(vrt.read(1, window=win).astype(dtype), 1, window=win)
    print(f"wrote {out_path}", flush=True)


def write_class_png(watermask_path, out_path, cls):
    """Binary 0/255 PNG for one water class of the warped 4-class mask."""
    with rasterio.open(watermask_path) as src:
        binary = (src.read(1) == cls).astype("uint8") * 255
        profile: dict[str, Any] = dict(driver="PNG", width=src.width,
                                       height=src.height, count=1,
                                       dtype="uint8", crs=src.crs,
                                       transform=src.transform)
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
    ap.add_argument("--hero-long-edge", type=int, default=HERO_LONG_EDGE,
                    help="hero render long edge in px (per-country override; "
                         "config/countries.toml is the durable home for it)")
    ap.add_argument("--frame", nargs=4, type=float, metavar=("W", "S", "E", "N"),
                    help="padded lon/lat frame from frame_country.py; "
                         "required unless heightfield_aea.tif already exists")
    args = ap.parse_args()

    out_h = args.outdir / "heightfield_aea.tif"
    out_m = args.outdir / "oceanmask_aea.tif"
    out_w = args.outdir / "watermask_aea.tif"
    out_f = args.outdir / "frame.json"
    args.outdir.mkdir(parents=True, exist_ok=True)

    if out_h.exists():
        with rasterio.open(out_h) as f:
            dst_crs = f.crs
            transform, width, height = f.transform, f.width, f.height
        xres = transform.a  # pyright: ignore[reportAttributeAccessIssue] — affine untyped
        print(f"grid + CRS from existing {out_h.name}: {width} x {height}, "
              f"{xres:.0f} m/px (--width/--frame ignored)", flush=True)
    else:
        if args.frame is None:
            ap.error("--frame W S E N is required when no heightfield exists")
        dst_crs = aea_crs(args.frame)
        print(f"projection: {dst_crs}", flush=True)
        with rasterio.open(args.heightfield) as src:
            left, bottom, right, top = transform_bounds(
                src.crs, dst_crs, *src.bounds, densify_pts=64)
        width = args.width
        xres = (right - left) / width
        height = round((top - bottom) / xres)
        transform = from_origin(left, top, xres, xres)
        print(f"projected grid: {width} x {height}, {xres:.0f} m/px",
              flush=True)

    wrote = 0
    if out_f.exists():
        print("frame.json exists — skipping (pinned frames stay pinned)",
              flush=True)
    else:
        numbers = scene_numbers(width, height, width * xres,
                                args.hero_long_edge)
        # normalize the CRS spelling so a regenerated frame.json is
        # byte-identical whether the projection came from --frame or the file
        crs_norm = CRS.from_string(dst_crs) \
            if isinstance(dst_crs, str) else dst_crs
        payload = dict(
            frame_lonlat=args.frame,
            dst_crs=crs_norm.to_proj4(),
            width_px=width, height_px=height, xres_m=xres,
            extent_w_m=width * xres, extent_h_m=height * xres,
            **numbers)
        out_f.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"wrote {out_f}", flush=True)
        wrote += 1
    for src_path, out_path, rs, dtype, pred in (
            (args.heightfield, out_h, Resampling.bilinear, "float32", 3),
            (args.mask, out_m, Resampling.nearest, "uint8", 2),
            (args.watermask, out_w, Resampling.nearest, "uint8", 2)):
        if src_path is None:
            continue
        if out_path.exists():
            print(f"{out_path.name} exists — skipping", flush=True)
            continue
        warp(src_path, out_path, dst_crs, transform, width, height, rs,
             dtype, pred)
        wrote += 1

    png_jobs = [(out_m, 1, "oceanmask_aea.png")]
    if args.watermask:
        png_jobs += [(out_w, 2, "inlandlake_aea.png"), (out_w, 3, "river_aea.png")]
    for src_tif, cls, name in png_jobs:
        out_png = args.outdir / name
        if out_png.exists():
            print(f"{name} exists — skipping", flush=True)
            continue
        write_class_png(src_tif, out_png, cls)
        wrote += 1

    print("complete" if wrote else "nothing to do — all outputs exist",
          flush=True)


if __name__ == "__main__":
    main()
