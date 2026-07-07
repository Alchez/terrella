#!/usr/bin/env python3
"""Prototype: do intra-lake depth gradients read at hero scale?

Fakes lake bathymetry on the finished Route A render, without re-rendering:
a shore-distance transform on the lake mask, normalized per lake, is
GLOBathy's basin-shape signal without its calibration (Patterson's classic
buffered-shoreline trick). The tint is applied as albedo scaling in linear
light, so the render's shading and cast shadows survive on the water.

This answers the gating question only (does a gradient read at ~230 m/px?).
Production would be a real depth channel from fusion plus a lake ramp in the
shader — see the PLAN.md open question.

Usage:
  lake_depth_prototype.py --render blender/renders/india_hero_8k_v3_water.png \
      --watermask data/work/india/render/watermask_aea.tif \
      --outdir data/work/india/render/overlay
"""

import argparse
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from scipy import ndimage

ORTHO_SCALE = 2.06
PLANE_WIDTH_UNITS = 2.0

# levers: basin shape exponent and the depth ramp (position 0 = shore).
# Shore is anchored at the flat Route A teal — a lighter rim dissolves the
# shoreline against pale high-plateau land (tried, rejected). Lakes whose
# deepest point is closer than SIZE_FULL_PX to shore get proportionally less
# contrast, so ponds stay flat instead of jumping to the dark end.
SHAPE_EXPONENT = 0.7
RAMP = [(0.00, "98C5C8"), (1.00, "649BA4")]
FLAT_TEAL = "98C5C8"
SIZE_FULL_PX = 6.0

CROP_SITES = {"tibet_lakes": (88.0, 31.5), "namtso": (90.6, 30.7),
              "pangong": (78.9, 33.75)}
CROP = 900


def hex_rgb(h):
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], "float32") / 255


def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    return np.where(c <= 0.0031308, c * 12.92,
                    1.055 * np.clip(c, 0, None) ** (1 / 2.4) - 0.055)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", type=Path, required=True)
    ap.add_argument("--watermask", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--tag", default="", help="suffix for output filenames")
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    tag = f"_{args.tag}" if args.tag else ""

    with rasterio.open(args.render) as f:
        rgb = f.read().astype("float32") / 255.0  # (bands, H, W)
        h, w = f.height, f.width
    with rasterio.open(args.watermask) as f:
        wm = f.read(1)
        mt, m_crs = f.transform, f.crs
        mh, mw = f.height, f.width

    # render px -> AEA -> mask px (both affine over the same frame center)
    extent_w = mt.a * mw
    m_per_px = (ORTHO_SCALE / max(w, h)) * extent_w / PLANE_WIDTH_UNITS
    cx = mt.c + extent_w / 2.0
    cy = mt.f - (mt.a * mh) / 2.0  # mask pixels are square, north-up
    x = cx + (np.arange(w) + 0.5 - w / 2.0) * m_per_px
    y = cy - (np.arange(h) + 0.5 - h / 2.0) * m_per_px
    mc = np.clip(((x - mt.c) / mt.a).astype(np.int64), 0, mw - 1)
    mr = np.clip(((mt.f - y) / mt.a).astype(np.int64), 0, mh - 1)
    lake = wm[np.ix_(mr, mc)] == 2
    print(f"lake px at render res: {int(lake.sum()):,}", flush=True)

    edt = ndimage.distance_transform_edt(lake).astype("float32")
    lab, nlab = ndimage.label(lake)
    peak = ndimage.maximum(edt, labels=lab, index=np.arange(1, nlab + 1))
    peak_of = np.concatenate([[1.0], np.maximum(peak, 1e-6)]).astype("float32")
    shape = np.zeros_like(edt)
    shape[lake] = ((edt[lake] / peak_of[lab[lake]]) ** SHAPE_EXPONENT
                   * np.minimum(peak_of[lab[lake]] / SIZE_FULL_PX, 1.0))
    print(f"{nlab:,} lakes; deepest-point distance max {edt.max():.1f} px",
          flush=True)

    # per-channel sRGB ramp -> linear ratio against the flat teal
    pos = np.array([p for p, _ in RAMP], "float32")
    cols = np.stack([hex_rgb(c) for _, c in RAMP])  # (stops, 3)
    flat_lin = srgb_to_linear(hex_rgb(FLAT_TEAL))
    sh = shape[lake]
    for b in range(3):
        ramp_srgb = np.interp(sh, pos, cols[:, b]).astype("float32")
        ratio = srgb_to_linear(ramp_srgb) / flat_lin[b]
        chan = rgb[b]
        lin = srgb_to_linear(chan[lake]) * ratio
        chan[lake] = linear_to_srgb(lin)

    out = np.clip(rgb * 255.0 + 0.5, 0, 255).astype("uint8")
    out_8k = args.outdir / f"lakedepth_prototype{tag}_8k.png"
    with rasterio.open(out_8k, "w", driver="PNG", width=w, height=h,
                       count=out.shape[0], dtype="uint8") as f:
        f.write(out)
    print(f"wrote {out_8k}", flush=True)

    # 2K preview + flat-vs-tinted crop pairs
    with rasterio.open(out_8k) as f:
        ph = round(h * 2048 / w)
        small = f.read(out_shape=(f.count, ph, 2048),
                       resampling=Resampling.average)
    with rasterio.open(args.outdir / f"lakedepth_preview{tag}_2k.png", "w",
                       driver="PNG", width=2048, height=ph,
                       count=small.shape[0], dtype="uint8") as f:
        f.write(small)

    import pyproj
    fwd = pyproj.Transformer.from_crs("EPSG:4326", m_crs, always_xy=True)
    with rasterio.open(args.render) as f:
        orig = f.read()  # rgb was tinted in place; crops need the original
    for name, (lon, lat) in CROP_SITES.items():
        px, py = fwd.transform(lon, lat)
        col = int(w / 2.0 + (px - cx) / m_per_px)
        row = int(h / 2.0 - (py - cy) / m_per_px)
        r0, c0 = row - CROP // 2, col - CROP // 2
        left = orig[:3, r0:r0 + CROP, c0:c0 + CROP]
        right = out[:3, r0:r0 + CROP, c0:c0 + CROP]
        divider = np.full((3, CROP, 8), 255, dtype=np.uint8)
        pair = np.concatenate([left, divider, right], axis=2)
        p = args.outdir / f"ab_lakedepth{tag}_{name}.png"
        with rasterio.open(p, "w", driver="PNG", width=pair.shape[2],
                           height=CROP, count=3, dtype="uint8") as f:
            f.write(pair)
        print(f"wrote {p}", flush=True)


if __name__ == "__main__":
    main()
