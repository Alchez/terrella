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

It records `body` and `exaggeration` alongside, because a pinned frame could
not previously say which exaggeration produced its own displacement_scale.
The body alone would not have said it: it resolves to whatever that planet's
exaggeration is TODAY, so a frame pinned before a change would silently
claim the new value. `body` is what scene_build cross-checks its own --body
against; `exaggeration` is the recipe.

Every mask the shader consumes is also emitted as a 0/255 PNG (Blender
divides 8-bit images by 255 on load): oceanmask.png always, and with
--watermask (the 4-class mask from fusion) additionally watermask.tif
plus inlandlake.png and river.png.

Per-output idempotency: existing outputs are skipped, never overwritten, so
new outputs can be backfilled next to old ones. When heightfield.tif
already exists the grid AND projection are taken from it, not re-derived
(--frame is then unneeded), so backfilled outputs stay aligned with any
render already made from it.

Usage:
  render_prep.py --body earth \
                 --heightfield data/work/nepal/heightfield_3s.tif \
                 --mask data/work/nepal/oceanmask_3s.tif \
                 --frame 79.6 25.9 88.7 31.0 \
                 [--watermask data/work/nepal/watermask_3s.tif] \
                 --outdir data/work/nepal/render [--width 16384]
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any

import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds
from rasterio.windows import Window

from pipeline import bodies
from pipeline.render import render_seam

FRAME_MARGIN = 1.0006  # camera overshoot: the plane underfills the frame a hair
HERO_LONG_EDGE = 7680  # hero render long edge in px; the short axis follows
                       # raster aspect (a tall country caps at 7680 tall, not
                       # 7680 wide — Maldives would be 56k px otherwise)

BLOCK = 8192

FLOOR_MIN_BOX_PX = 10  # a resolution floor engages only once its box-mean kernel
                       # reaches this width — i.e. the frame upsampled >~5x past
                       # the floor (only tiny countries do). Coarser grids skip
                       # it, so mid/large countries are never softened.


def floor_box_px(floor_m: float, xres_m: float) -> int:
    """Box-mean kernel width (px) for a resolution floor of floor_m meters on a
    grid of xres_m m/px, or 0 when no floor is requested. Compared against
    FLOOR_MIN_BOX_PX to decide whether the floor engages."""
    return round(floor_m / xres_m) if floor_m > 0 else 0


def aea_crs(frame):
    """Albers equal-area conic centered on a (W, S, E, N) lon/lat frame:
    standard parallels 1/6 in from the latitude edges, origin at center."""
    west, south, east, north = frame
    return (f"+proj=aea +lat_1={south + (north - south) / 6.0:g} "
            f"+lat_2={north - (north - south) / 6.0:g} "
            f"+lat_0={(south + north) / 2.0:g} +lon_0={(west + east) / 2.0:g} "
            f"+datum=WGS84 +units=m")


def scene_numbers(width_px, height_px, extent_w_m, *, exaggeration,
                  hero_long_edge=HERO_LONG_EDGE):
    """Blender scene numbers for a warped grid (docs/framing-math.md).

    The displacement plane is always 2 Blender units wide, so one unit is
    half the frame width in meters — every number here is that conversion
    applied to the locked global look constants. The render resolution puts
    hero_long_edge on the grid's longer axis; for landscape grids this is
    identical to the retired fixed-width rule.

    `exaggeration` IS KEYWORD-ONLY AND REQUIRED, and this used to import
    Earth's 15x directly. It is `Body.exaggeration`, which is 20x on Mars,
    and this function is not the hero path's alone: the block prep calls it
    too and says so ("scene_numbers is the whole seam"), so a Mars block
    prepared through the old import displaced at two thirds of correct with
    nothing to notice. No default, for the reason no field on `Body` has
    one — the type checker names every call site at once."""
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
        displacement_scale=exaggeration / (extent_w_m / 2.0),
        **res,
    )


#: frame.json's keys, in the one order they are written in.
#:
#: THE ORDER IS LOAD-BEARING AND USED NOT TO HAVE AN OWNER. A frame that exists is never
#: overwritten, so the only way to check a pin is to regenerate beside it and compare; the CRS
#: spelling is normalised for exactly that reason. Backfilling `body` and `exaggeration` into 203
#: pinned frames put a second writer beside this one, and two writers of one key order is the drift
#: this constant exists to refuse.
FRAME_KEYS = ("body", "frame_lonlat", "dst_crs", "width_px", "height_px", "xres_m",
              "extent_w_m", "extent_h_m", "exaggeration", "plane_height_units",
              "ortho_scale", "displacement_scale", "res_x", "res_y")


def frame_json_text(payload: dict[str, Any]) -> str:
    """Serialise a frame payload in `FRAME_KEYS` order, refusing a missing or unknown key.

    Refusing rather than tolerating, because both directions are silent otherwise: a dropped key
    leaves a consumer reading `None` as a number, and a stray one makes a regenerated frame differ
    from its pin for a reason that has nothing to do with the geometry.
    """
    missing = [key for key in FRAME_KEYS if key not in payload]
    unknown = sorted(set(payload) - set(FRAME_KEYS))
    if missing or unknown:
        raise ValueError(f"frame payload does not match FRAME_KEYS: missing {missing}, "
                         f"unknown {unknown}")
    return json.dumps({key: payload[key] for key in FRAME_KEYS}, indent=2) + "\n"


def finalize(tmp, final):
    """Atomically move a fully-written tmp (plus any GDAL .aux.xml sidecar for
    PNGs) into place. The final path appears last, so its existence always
    means 'complete' — an abrupt kill mid-write leaves only ignorable .tmp."""
    aux = tmp.with_name(tmp.name + ".aux.xml")
    if aux.exists():
        os.replace(aux, final.with_name(final.name + ".aux.xml"))
    os.replace(tmp, final)


def warp(src_path, out_path, dst_crs, transform, width, height, resampling,
         dtype, predictor, floor_m=0.0):
    tmp = out_path.with_name(out_path.name + ".tmp")
    profile: dict[str, Any] = dict(
        driver="GTiff", crs=dst_crs, transform=transform,
        width=width, height=height, count=1, dtype=dtype,
        tiled=True, blockxsize=512, blockysize=512,
        compress="deflate", predictor=predictor, bigtiff="if_safer",
    )
    xres = transform.a  # pyright: ignore[reportAttributeAccessIssue] — affine untyped
    box = floor_box_px(floor_m, xres)
    with rasterio.open(src_path) as src, \
         WarpedVRT(src, crs=dst_crs, transform=transform, width=width,
                   height=height, resampling=resampling) as vrt, \
         rasterio.open(tmp, "w", **profile) as out:
        if box >= FLOOR_MIN_BOX_PX:
            # Resolution floor: this frame upsampled far past the 30 m DEM, so
            # its sub-floor detail is source striping, not terrain — box-lowpass
            # it out. Only tiny frames reach here, so the whole grid fits in
            # memory; the streaming block path below stays the large-country /
            # OOM guard and never floors (masks pass floor_m=0 and skip this).
            from scipy.ndimage import uniform_filter
            data = vrt.read(1).astype(dtype)
            out.write(uniform_filter(data, size=box, mode="nearest"), 1)
            print(f"  resolution floor {floor_m:g} m -> {box} px box "
                  f"({xres:.2f} m/px): smoothed", flush=True)
        else:
            for row in range(0, height, BLOCK):
                for col in range(0, width, BLOCK):
                    win = Window(col, row,  # pyright: ignore[reportCallIssue] — rasterio untyped, attrs init invisible
                                 min(BLOCK, width - col), min(BLOCK, height - row))
                    out.write(vrt.read(1, window=win).astype(dtype), 1, window=win)
    finalize(tmp, out_path)
    print(f"wrote {out_path}", flush=True)


def write_class_png(watermask_path, out_path, cls):
    """Binary 0/255 PNG for one water class of the warped 4-class mask."""
    tmp = out_path.with_name(out_path.name + ".tmp")
    with rasterio.open(watermask_path) as src:
        binary = (src.read(1) == cls).astype("uint8") * 255
        profile: dict[str, Any] = dict(driver="PNG", width=src.width,
                                       height=src.height, count=1,
                                       dtype="uint8", crs=src.crs,
                                       transform=src.transform)
    with rasterio.open(tmp, "w", **profile) as out:
        out.write(binary, 1)
    finalize(tmp, out_path)
    print(f"wrote {out_path} ({int((binary > 0).sum()):,} px set)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", required=True, choices=sorted(bodies.BODIES),
                    help="which planet this frame belongs to; supplies the vertical exaggeration "
                         "and is recorded in frame.json so the scene can cross-check its own flag")
    ap.add_argument("--heightfield", type=Path, required=True)
    ap.add_argument("--mask", type=Path, required=True)
    ap.add_argument("--watermask", type=Path,
                    help=f"4-class water mask; adds {render_seam.WATERMASK} + "
                         f"{render_seam.INLANDLAKE} + {render_seam.RIVER}")
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--width", type=int, default=16384)
    ap.add_argument("--hero-long-edge", type=int, default=HERO_LONG_EDGE,
                    help="hero render long edge in px (per-country override; "
                         "config/countries.toml is the durable home for it)")
    ap.add_argument("--floor-m", type=float, default=0.0,
                    help="resolution floor (m): box-lowpass the heightfield "
                         "where the frame upsampled >~5x past it, killing "
                         "sub-source DEM striping on tiny countries; 0 = off. "
                         "config/countries.toml resolution_floor_m is the home")
    ap.add_argument("--frame", nargs=4, type=float, metavar=("W", "S", "E", "N"),
                    help="padded lon/lat frame from frame_country.py; "
                         f"required unless {render_seam.HEIGHTFIELD} already exists")
    args = ap.parse_args()
    body = bodies.BODIES[args.body]

    out_h = args.outdir / render_seam.HEIGHTFIELD
    out_m = args.outdir / render_seam.OCEANMASK_TIF
    out_w = args.outdir / render_seam.WATERMASK
    out_f = args.outdir / "frame.json"
    args.outdir.mkdir(parents=True, exist_ok=True)

    if out_h.exists():
        with rasterio.open(out_h) as heightfield_dataset:
            dst_crs = heightfield_dataset.crs
            transform, width, height = (heightfield_dataset.transform,
                                        heightfield_dataset.width,
                                        heightfield_dataset.height)
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
                                exaggeration=body.exaggeration,
                                hero_long_edge=args.hero_long_edge)
        # normalize the CRS spelling so a regenerated frame.json is
        # byte-identical whether the projection came from --frame or the file
        crs_norm = CRS.from_string(dst_crs) \
            if isinstance(dst_crs, str) else dst_crs
        payload = dict(
            body=body.name,
            frame_lonlat=args.frame,
            dst_crs=crs_norm.to_proj4(),
            width_px=width, height_px=height, xres_m=xres,
            extent_w_m=width * xres, extent_h_m=height * xres,
            exaggeration=body.exaggeration,
            **numbers)
        tmp_f = out_f.with_name(out_f.name + ".tmp")
        tmp_f.write_text(frame_json_text(payload))
        os.replace(tmp_f, out_f)
        print(f"wrote {out_f}", flush=True)
        wrote += 1
    for src_path, out_path, rs, dtype, pred, fm in (
            (args.heightfield, out_h, Resampling.bilinear, "float32", 3, args.floor_m),
            (args.mask, out_m, Resampling.nearest, "uint8", 2, 0.0),
            (args.watermask, out_w, Resampling.nearest, "uint8", 2, 0.0)):
        if src_path is None:
            continue
        if out_path.exists():
            print(f"{out_path.name} exists — skipping", flush=True)
            continue
        warp(src_path, out_path, dst_crs, transform, width, height, rs,
             dtype, pred, floor_m=fm)
        wrote += 1

    png_jobs = [(out_m, 1, render_seam.OCEANMASK)]
    if args.watermask:
        png_jobs += [(out_w, 2, render_seam.INLANDLAKE), (out_w, 3, render_seam.RIVER)]
    for src_tif, cls, name in png_jobs:
        out_png = args.outdir / name
        if out_png.exists():
            print(f"{name} exists — skipping", flush=True)
            continue
        write_class_png(src_tif, out_png, cls)
        wrote += 1

    # Declared unconditionally, INCLUDING on the "nothing to do" path, because the record is a
    # statement about this stage having finished rather than about it having written bytes. A resume
    # that skipped every warp has still produced the directory the rig is about to read.
    print(f"declared {render_seam.declare(args.outdir, render_seam.PREP,
                                          [render_seam.HEIGHTFIELD] + [n for _, _, n in png_jobs])}",
          flush=True)
    print("complete" if wrote else "nothing to do — all outputs exist",
          flush=True)


if __name__ == "__main__":
    main()
