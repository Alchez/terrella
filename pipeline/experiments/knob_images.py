#!/usr/bin/env python3
"""Render one preview image PER KNOB from an already-shaded region's cached layers.

The shade stage's expensive layers (Mercator reproject, color-relief, baseline hillshade,
masks) are already on disk from a `pipeline.tile.shade` run. This harness reads them back at
preview resolution and re-runs ONLY the numpy composite under one perturbed knob at a time,
so each variant costs milliseconds. The `alt` knob is the sole exception: it changes the
hillshade itself, so that one variant runs a fresh gdaldem hillshade on the cached height VRT.

Output: <out>/00_baseline.png plus NN_<knob>_<value>.png, one isolated knob change each,
all at the same downscaled size for honest side-by-side eyeballing (shown individually, not
montaged). Mirrors pipeline/tile/shade.py's composite math exactly so previews are faithful.

    python -m pipeline.experiments.knob_images \
        --region <scratchpad>/southasia --mid-lat 30 --out <scratchpad>/knobs
"""

import argparse
import math
import subprocess
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from scipy.ndimage import zoom

from pipeline.render import palette, relief
from pipeline.render.sky_view import horizon_svf

EXAG = 15.0
MERCATOR = "EPSG:3857"

# baseline = the locked production knobs (pipeline/tile/shade.py KNOBS)
BASELINE = dict(alt=45.0, ambient=0.50, hi=1.30, exposure=1.30, saturation=1.18, warmth=0.06,
                svf_strength=0.20, svf_threshold=0.45, sea_shade=0.26, sea_lift=1.08,
                sea_saturation=0.90, snow_floor=0.78)

# one perturbation per knob — a visible-but-plausible nudge in the direction worth exploring
VARIANTS = [
    ("alt", 35.0),             # lower sun -> longer shadows, more relief drama
    ("ambient", 0.40),         # deeper shadow floor -> more contrast
    ("hi", 1.45),              # brighter sunlit peaks
    ("exposure", 1.50),        # punchier land contrast
    ("saturation", 1.35),      # richer land colour
    ("warmth", 0.14),          # warmer sand (more Ramspott)
    ("svf_strength", 0.35),    # deeper valley / crevice shadow
    ("svf_threshold", 0.30),   # concavity darkening spreads to gentler basins
    ("sea_shade", 0.12),       # flatter, calmer sea surface
    ("sea_lift", 1.15),        # brighter sea
    ("sea_saturation", 1.10),  # more saturated teal sea
    ("snow_floor", 0.90),      # brighter, cleaner snow
]


def run(cmd):
    subprocess.run([str(part) for part in cmd], check=True, capture_output=True)


def read3(path, shape):
    with rasterio.open(path) as dataset:
        return dataset.read([1, 2, 3], out_shape=(3, *shape),
                            resampling=Resampling.bilinear).astype(float)


def read1(path, shape, resample):
    with rasterio.open(path) as dataset:
        return dataset.read(1, out_shape=shape, resampling=resample)


def preview_shape(region, long_edge):
    with rasterio.open(region / "height.vrt") as dataset:
        full_w, full_h = dataset.width, dataset.height
    scale = long_edge / max(full_w, full_h)
    return round(full_h * scale), round(full_w * scale)


def load_base(region, mid_lat, long_edge):
    """Read the cached shade layers at preview resolution + recompute SVF once."""
    shape = preview_shape(region, long_edge)
    height, width = shape
    # c_land/c_sea were deleted with the color-relief stage.
    heights = read1(region / "height.vrt", shape).astype("float32")
    ocean = read1(region / "ocean.vrt", shape, Resampling.nearest) != 0
    watercode = read1(region / "water.vrt", shape, Resampling.nearest)
    water = (watercode == 2) | (watercode == 3)
    snow_mask = read1(region / "snow_cls.tif", shape, Resampling.nearest) == 70
    hs_base = read1(region / "hs.tif", shape, Resampling.bilinear).astype(float)

    # SVF (occlusion) recomputed from the height VRT at reduced res, m/px de-inflated by
    # cos(lat) so horizon geometry is physical — identical recipe to shade.py
    with rasterio.open(region / "height.vrt") as dataset:
        svf_edge = 1600
        scale = svf_edge / max(dataset.width, dataset.height)
        sh, sw = round(dataset.height * scale), round(dataset.width * scale)
        low = dataset.read(1, out_shape=(sh, sw), resampling=Resampling.average).astype(float)
        m_per_px = (dataset.bounds.right - dataset.bounds.left) / sw * math.cos(math.radians(mid_lat))
    low = np.nan_to_num(np.where(low < -500, np.nan, low), nan=0.0)
    svf = horizon_svf(low, m_per_px)
    occ = 1.0 - (svf - svf.min()) / (svf.max() - svf.min() + 1e-6)

    return dict(shape=shape, land=land, sea=sea, ocean=ocean, water=water,
                snow_mask=snow_mask, hs_base=hs_base, occ=occ, occ_shape=(sh, sw))


def hillshade_at_alt(region, mid_lat, alt, shape):
    """Fresh hillshade for the alt knob (baseline z-factor), read back at preview res."""
    zfactor = relief.mercator_zfactor(mid_lat, EXAG)
    hs_tif = region / f"hs_alt{int(alt)}.tif"
    run(["gdaldem", "hillshade", region / "height.vrt", hs_tif, "-z", f"{zfactor:.4f}",
         "-alt", str(alt), "-az", "315", "-compute_edges"])
    return read1(hs_tif, shape, Resampling.bilinear).astype(float)


def composite(base, hillshade_arr, knobs):
    """Exact port of pipeline/tile/shade.py composite(), parameterised by knobs."""
    height, width = base["shape"]
    land, sea = base["land"].copy(), base["sea"].copy()
    ocean, water, snow_mask = base["ocean"], base["water"], base["snow_mask"]

    lum = 0.299 * land[0] + 0.587 * land[1] + 0.114 * land[2]
    warm = np.array([1.0, 1.0 - 0.5 * knobs["warmth"], 1.0 - knobs["warmth"]]).reshape(3, 1, 1)
    land = np.clip((lum[None] + (land - lum[None]) * knobs["saturation"]) * warm, 0, 255)
    sea_lum = 0.299 * sea[0] + 0.587 * sea[1] + 0.114 * sea[2]
    sea = np.clip(sea_lum[None] + (sea - sea_lum[None]) * knobs["sea_saturation"], 0, 255)
    color = np.where(ocean[None], sea, land)
    color = np.where(snow_mask[None], np.array(palette.SNOW_RGB, float).reshape(3, 1, 1), color)
    color = np.where(water[None], np.array(palette.WATER_RGB, float).reshape(3, 1, 1), color)

    flat = 255.0 * math.sin(math.radians(knobs["alt"]))
    light = np.clip(hillshade_arr / flat, knobs["ambient"], knobs["hi"])
    burn = knobs["svf_strength"] * np.clip(
        (base["occ"] - knobs["svf_threshold"]) / (1 - knobs["svf_threshold"]), 0, 1) ** 1.4
    sh, sw = base["occ_shape"]
    svf_factor = np.clip(np.asarray(zoom(1.0 - burn, (height / sh, width / sw), order=1)), 0, 1)
    svf_factor = np.where(ocean | water, 1.0, svf_factor)
    light = np.where(water, np.clip(light, 0.85, knobs["hi"]), light)
    light = np.where(ocean, knobs["sea_lift"] + (light - 1.0) * knobs["sea_shade"], light)
    light = np.where(snow_mask, np.maximum(light, knobs["snow_floor"]), light)
    light = np.where(ocean | water, light,
                     knobs["ambient"] + (light - knobs["ambient"]) * knobs["exposure"])
    return np.clip(color * (light * svf_factor), 0, 255).astype("uint8")


def save_png(rgb, path):
    _, height, width = rgb.shape
    tmp = path.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", driver="GTiff", height=height, width=width,
                       count=3, dtype="uint8", photometric="RGB") as out:
        out.write(rgb)
    run(["gdal_translate", "-q", "-of", "PNG", tmp, path])
    tmp.unlink()
    path.with_suffix(path.suffix + ".aux.xml").unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", type=Path, required=True, help="dir with cached shade layers")
    ap.add_argument("--mid-lat", type=float, default=30.0)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--long-edge", type=int, default=2000)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    print(f"loading cached layers from {args.region} at long-edge {args.long_edge}...", flush=True)
    base = load_base(args.region, args.mid_lat, args.long_edge)
    print(f"preview grid {base['shape'][1]} x {base['shape'][0]}", flush=True)

    save_png(composite(base, base["hs_base"], BASELINE), args.out / "00_baseline.png")
    print("wrote 00_baseline.png", flush=True)

    for index, (knob, value) in enumerate(VARIANTS, start=1):
        knobs = dict(BASELINE, **{knob: value})
        hs = hillshade_at_alt(args.region, args.mid_lat, value, base["shape"]) \
            if knob == "alt" else base["hs_base"]
        tag = f"{value:.2f}".rstrip("0").rstrip(".")
        name = f"{index:02d}_{knob}_{tag}.png"
        save_png(composite(base, hs, knobs), args.out / name)
        print(f"wrote {name}  ({knob}: {BASELINE[knob]} -> {value})", flush=True)

    print(f"\ndone: {1 + len(VARIANTS)} images in {args.out}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
