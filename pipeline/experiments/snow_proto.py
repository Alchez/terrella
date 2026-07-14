#!/usr/bin/env python3
"""Prototype: drive snow from NSIDC-0791 snow-persistence (SP) as a SOFT ALPHA.

Replaces the sparse WorldCover class-70 permanent-ice mask (which leaves mid/high-latitude
ranges bare) with observed snow persistence from the MODIS climatology. Persistence — the
fraction of the climatology a pixel is snow-covered — drives a smooth snow alpha, so snow
fades realistically at its margins instead of a hard cartoon edge. Reuses the cached
shaded-region layers (knob_images.load_base), so each region re-composites in seconds.

    python -m pipeline.experiments.snow_proto \
        --sp data/raw/snow/NSIDC-0791_SP_0.01Deg_WY2001-2023_V01.0.nc \
        --regions <scratchpad>/stress/alps <scratchpad>/stress/andes ... \
        --out <scratchpad>/snowproto --low 0.30 --high 0.60
"""

import argparse
import math
import subprocess
from pathlib import Path

import numpy as np
import rasterio
from scipy.ndimage import zoom

from pipeline.render import palette
from pipeline.experiments.knob_images import BASELINE, load_base, save_png

# rough region centre latitudes, only used for the SVF de-inflation inside load_base
REGION_MIDLAT = dict(alps=45.0, sahara=25.0, scandinavia=65.0, andes=-30.0,
                     indonesia=0.0, southasia=30.0)

SP_SCALE = 1e-4     # NSIDC-0791 packing: unpacked persistence = 0.0001 x packed (0..10000 -> 0..1)
SP_FILL = 65535     # packed fill value (ocean / no valid MODIS observation)

# Latitude-ramped snow threshold: the persistence cutoff for "snowy on the map" rises toward
# the poles, where huge areas are seasonally snow-covered every winter. Anchored to the two
# validated endpoints — Alps (45 deg) want ~0.40, Scandinavia (63 deg) want ~0.60. This is still
# observed snow; only the display sensitivity varies with latitude (not a fabricated snowline).
RAMP_LAT_LO, RAMP_LAT_HI = 45.0, 63.0
RAMP_LOW_MIN, RAMP_LOW_MAX = 0.40, 0.60
RAMP_BAND = 0.32          # high = low + band (soft-alpha width)
EARTH_RADIUS = 6378137.0  # Web Mercator sphere radius


def run(cmd):
    subprocess.run([str(part) for part in cmd], check=True, capture_output=True)


def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def latitude_per_row(region_dir, shape):
    """Latitude of each pixel row from the region's Web-Mercator grid (lat varies by row only)."""
    with rasterio.open(region_dir / "height.vrt") as dataset:
        top, bottom = dataset.bounds.top, dataset.bounds.bottom
    height = shape[0]
    rows = np.arange(height)
    merc_y = top - (rows + 0.5) * (top - bottom) / height
    return np.degrees(2.0 * np.arctan(np.exp(merc_y / EARTH_RADIUS)) - math.pi / 2.0)


def ramp_thresholds(latitude):
    """Per-row (low, high) persistence thresholds ramped by |latitude|."""
    frac = np.clip((np.abs(latitude) - RAMP_LAT_LO) / (RAMP_LAT_HI - RAMP_LAT_LO), 0.0, 1.0)
    low = RAMP_LOW_MIN + frac * (RAMP_LOW_MAX - RAMP_LOW_MIN)
    return low, low + RAMP_BAND


def sp_subdataset(nc_path):
    """A GDAL-openable reference to the persistence variable in the SP NetCDF."""
    with rasterio.open(nc_path) as dataset:
        subs = dataset.subdatasets
    if not subs:
        return str(nc_path)
    coords = ("lat", "lon", "latitude", "longitude", "time", "crs", "x", "y")
    data = [s for s in subs if s.split(":")[-1].strip('"').lower() not in coords]
    # prefer the continuous climatology (9999 levels, smooth) over the day-quantized
    # snow_persistence (366 levels) — smoother soft-alpha margins
    for candidate in data:
        if "climatology" in candidate.split(":")[-1].lower():
            return candidate
    for candidate in data:
        if "persist" in candidate.split(":")[-1].lower():
            return candidate
    return (data or subs)[-1]


def warp_sp(sub, region_dir, shape):
    """Warp the SP variable onto a region's Mercator preview grid; return persistence 0..1."""
    with rasterio.open(region_dir / "height.vrt") as dataset:
        te = [repr(dataset.bounds.left), repr(dataset.bounds.bottom),
              repr(dataset.bounds.right), repr(dataset.bounds.top)]
    height, width = shape
    out = region_dir / "_sp_merc.tif"
    # -srcnodata so the 65535 fill is excluded from bilinear (else it bleeds a white
    # fringe onto coastlines where fill borders valid land)
    run(["gdalwarp", "-overwrite", "-q", "-s_srs", "EPSG:4326", "-t_srs", "EPSG:3857",
         "-srcnodata", str(SP_FILL), "-dstnodata", str(SP_FILL),
         "-te", *te, "-ts", str(width), str(height), "-r", "bilinear", "-ot", "Float32",
         sub, out])
    with rasterio.open(out) as dataset:
        packed = dataset.read(1).astype(float)
    valid = np.isfinite(packed) & (packed != SP_FILL)
    persistence = np.where(valid, packed, 0.0) * SP_SCALE
    return np.clip(persistence, 0.0, 1.0)


def composite_with_snow(base, persistence, low, high):
    knobs = BASELINE
    land, sea = base["land"].copy(), base["sea"].copy()
    ocean, water = base["ocean"], base["water"]

    lum = 0.299 * land[0] + 0.587 * land[1] + 0.114 * land[2]
    warm = np.array([1.0, 1.0 - 0.5 * knobs["warmth"], 1.0 - knobs["warmth"]]).reshape(3, 1, 1)
    land = np.clip((lum[None] + (land - lum[None]) * knobs["saturation"]) * warm, 0, 255)
    sea_lum = 0.299 * sea[0] + 0.587 * sea[1] + 0.114 * sea[2]
    sea = np.clip(sea_lum[None] + (sea - sea_lum[None]) * knobs["sea_saturation"], 0, 255)
    color = np.where(ocean[None], sea, land)
    color = np.where(water[None], np.array(palette.WATER_RGB, float).reshape(3, 1, 1), color)

    hillshade = base["hs_base"]
    flat = 255.0 * math.sin(math.radians(knobs["alt"]))
    light = np.clip(hillshade / flat, knobs["ambient"], knobs["hi"])
    burn = knobs["svf_strength"] * np.clip(
        (base["occ"] - knobs["svf_threshold"]) / (1 - knobs["svf_threshold"]), 0, 1) ** 1.4
    sh, sw = base["occ_shape"]
    height, width = base["shape"]
    svf = np.clip(np.asarray(zoom(1.0 - burn, (height / sh, width / sw), order=1)), 0, 1)
    svf = np.where(ocean | water, 1.0, svf)
    light = np.where(water, np.clip(light, 0.85, knobs["hi"]), light)
    light = np.where(ocean, knobs["sea_lift"] + (light - 1.0) * knobs["sea_shade"], light)
    light = np.where(ocean | water, light,
                     knobs["ambient"] + (light - knobs["ambient"]) * knobs["exposure"])
    base_rgb = color * (light * svf)

    # soft-alpha snow from persistence; snow still takes the hillshade so it isn't flat white.
    # low/high may be scalars or per-row arrays (latitude ramp) -> reshape to broadcast over columns
    low_arr = np.reshape(low, (-1, 1)) if np.ndim(low) else low
    high_arr = np.reshape(high, (-1, 1)) if np.ndim(high) else high
    alpha = smoothstep((persistence - low_arr) / np.maximum(1e-6, high_arr - low_arr))
    alpha = np.where(ocean | water, 0.0, alpha)
    snow_light = np.clip(light, knobs["snow_floor"], knobs["hi"])
    snow_rgb = np.array(palette.SNOW_RGB, float).reshape(3, 1, 1) * snow_light
    final = base_rgb * (1 - alpha)[None] + snow_rgb * alpha[None]
    return np.clip(final, 0, 255).astype("uint8")


def render(region_dir, sub, out_dir, low, high, long_edge, ramp):
    name = region_dir.name
    base = load_base(region_dir, REGION_MIDLAT.get(name, 30.0), long_edge)
    persistence = warp_sp(sub, region_dir, base["shape"])
    if ramp:
        latitude = latitude_per_row(region_dir, base["shape"])
        low, high = ramp_thresholds(latitude)
        note = (f"ramp |lat| {np.abs(latitude).min():.0f}-{np.abs(latitude).max():.0f} "
                f"-> low {np.min(low):.2f}-{np.max(low):.2f}")
    else:
        note = f"fixed low {low:.2f}/high {high:.2f}"
    rgb = composite_with_snow(base, persistence, low, high)
    save_png(rgb, out_dir / f"{name}_snow.png")
    print(f"{name}: persistence max {persistence.max():.2f}, {note}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sp", type=Path, required=True)
    ap.add_argument("--regions", type=Path, nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--low", type=float, default=0.30, help="persistence where snow begins")
    ap.add_argument("--high", type=float, default=0.60, help="persistence for full snow")
    ap.add_argument("--ramp", action="store_true",
                    help="ramp the threshold by latitude instead of fixed --low/--high")
    ap.add_argument("--long-edge", type=int, default=2000)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sub = sp_subdataset(args.sp)
    print(f"SP source: {sub}", flush=True)
    for region in args.regions:
        render(region, sub, args.out, args.low, args.high, args.long_edge, args.ramp)
    print(f"done -> {args.out}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
