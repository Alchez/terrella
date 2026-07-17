#!/usr/bin/env python3
"""Experiment: shade ONE planet chunk in Web Mercator and knob-sweep it vs a hero.

The first real artifact of the tile shading stage — proves the Mercator+latitude-band
recipe (relief.mercator_zfactor), the shared palette, SVF, and snow reproduce the hero
family on planet data, before we commit to a global pipeline. Not production: it hard-
codes the Nepal cell and writes a contact sheet to eyeball.

Structure mirrors the cost model: the expensive layers (reproject, color-relief, SVF,
snow) are computed ONCE; hillshade is recomputed per (light, exaggeration) variant
(~seconds); the composite is pure numpy (~ms), so a whole grid is nearly free.

    python -m pipeline.experiments.tile_chunk --chunk e080_n20 --mid-lat 25 \
        --hero blender/renders/heroes/nepal.png --out data/work/tile_proto/nepal_merc
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

DATA = Path.home() / "projects/maps/data"
WORLDCOVER_VRT = DATA / "raw/worldcover/worldcover.vrt"
Z8_MERC_RES = 305.7483  # metres/pixel of a 512px WebMercatorQuad tile at zoom 8
EXAG = 15.0             # locked hero vertical exaggeration
MERCATOR = "EPSG:3857"

# tuned prototype defaults (tile_recipe.py) — the composite knobs, all cheap to vary
DEFAULTS = dict(ambient=0.50, hi=1.30, exposure=1.30, saturation=1.18, warmth=0.06,
                svf_strength=0.20, svf_threshold=0.45, sea_shade=0.26, sea_lift=1.08,
                sea_saturation=0.90, snow_floor=0.78, alt=45.0)


def run(cmd):
    subprocess.run([str(part) for part in cmd], check=True, capture_output=True)


def warp_to_merc(src, dst, resample, te=None, size=None, ot=None):
    cmd = ["gdalwarp", "-overwrite", "-q", "-t_srs", MERCATOR, "-r", resample]
    if te is None:
        cmd += ["-tr", Z8_MERC_RES, Z8_MERC_RES]
    else:
        cmd += ["-te", *te, "-ts", size[0], size[1]]
    if ot:
        cmd += ["-ot", ot]
    run(cmd + [str(src), str(dst)])


def read1(path, shape=None, resample=Resampling.nearest):
    with rasterio.open(path) as dataset:
        if shape is None:
            return dataset.read(1)
        return dataset.read(1, out_shape=shape, resampling=resample)


def save_png(rgb_uint8, path):
    _, height, width = rgb_uint8.shape
    tmp = path.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", driver="GTiff", height=height, width=width,
                       count=3, dtype="uint8") as out:
        out.write(rgb_uint8)
    run(["gdal_translate", "-q", "-of", "PNG", tmp, path])
    tmp.unlink()
    (path.with_suffix(path.suffix + ".aux.xml")).unlink(missing_ok=True)


def prep_base_layers(chunk_dir, out, mid_lat):
    """Everything independent of the light/exaggeration knobs, computed once."""
    merc = out / "merc"
    merc.mkdir(parents=True, exist_ok=True)
    height_merc = merc / "height.tif"
    warp_to_merc(chunk_dir / "heightfield_10s.tif", height_merc, "bilinear")
    with rasterio.open(height_merc) as dataset:
        bounds = [repr(value) for value in dataset.bounds]
        grid_h, grid_w = dataset.height, dataset.width
    size = (str(grid_w), str(grid_h))

    ocean_merc = merc / "ocean.tif"
    water_merc = merc / "water.tif"
    snow_cls_merc = merc / "snow_cls.tif"
    warp_to_merc(chunk_dir / "oceanmask_10s.tif", ocean_merc, "near", bounds, size)
    warp_to_merc(chunk_dir / "watermask_10s.tif", water_merc, "near", bounds, size)
    warp_to_merc(WORLDCOVER_VRT, snow_cls_merc, "near", bounds, size, ot="Byte")

    # color-relief on the Mercator heightfield, land + sea ramps from the shared palette
    land_ramp, sea_ramp = merc / "ramp_land.txt", merc / "ramp_sea.txt"
    palette.write_color_relief(land_ramp, "land")
    palette.write_color_relief(sea_ramp, "sea")
    land_tif, sea_tif = merc / "color_land.tif", merc / "color_sea.tif"
    run(["gdaldem", "color-relief", height_merc, land_ramp, land_tif])
    run(["gdaldem", "color-relief", height_merc, sea_ramp, sea_tif])

    ocean = read1(ocean_merc) != 0
    water = read1(water_merc)
    water = (water == 2) | (water == 3)
    snow_mask = read1(snow_cls_merc) == 70  # ESA WorldCover class 70 = permanent snow/ice

    # SVF once, at reduced res, from the Mercator heightfield (m/px de-inflated by cos(lat)
    # so the horizon geometry is physical, matching the z-factor correction)
    with rasterio.open(height_merc) as dataset:
        long_edge = 2200
        sw = max(1, round(dataset.width / max(dataset.width, dataset.height) * long_edge))
        sh = max(1, round(dataset.height / max(dataset.width, dataset.height) * long_edge))
        low = dataset.read(1, out_shape=(sh, sw), resampling=Resampling.average).astype(float)
        m_per_px = (dataset.bounds.right - dataset.bounds.left) / sw * math.cos(math.radians(mid_lat))
    low = np.nan_to_num(np.where(low < -500, np.nan, low), nan=0.0)
    svf = horizon_svf(low, m_per_px)
    occ = 1.0 - (svf - svf.min()) / (svf.max() - svf.min() + 1e-6)

    return dict(height_merc=height_merc, grid=(grid_h, grid_w),
                land=_read3(land_tif), sea=_read3(sea_tif),
                ocean=ocean, water=water, snow_mask=snow_mask,
                occ=occ, occ_shape=(sh, sw))


def _read3(path):
    with rasterio.open(path) as dataset:
        return dataset.read([1, 2, 3]).astype(float)


def hillshade(height_merc, out_path, zfactor, alt, multidirectional):
    cmd = ["gdaldem", "hillshade", height_merc, out_path, "-z", f"{zfactor:.4f}",
           "-alt", str(alt), "-compute_edges"]
    cmd += ["-multidirectional"] if multidirectional else ["-az", "315"]
    run(cmd)
    return read1(out_path).astype(float)


def composite(base, hillshade_arr, knobs):
    """Pure-numpy composite of cached layers + hillshade under one knob set (~ms)."""
    height, width = base["grid"]
    land, sea = base["land"].copy(), base["sea"].copy()
    ocean, water, snow_mask = base["ocean"], base["water"], base["snow_mask"]

    lum = 0.299 * land[0] + 0.587 * land[1] + 0.114 * land[2]
    land = lum[None] + (land - lum[None]) * knobs["saturation"]
    warm = np.array([1.0, 1.0 - 0.5 * knobs["warmth"], 1.0 - knobs["warmth"]]).reshape(3, 1, 1)
    land = np.clip(land * warm, 0, 255)
    sea_lum = 0.299 * sea[0] + 0.587 * sea[1] + 0.114 * sea[2]
    sea = np.clip(sea_lum[None] + (sea - sea_lum[None]) * knobs["sea_saturation"], 0, 255)
    color = np.where(ocean[None], sea, land)

    snow_rgb = np.array(palette.SNOW_RGB, float).reshape(3, 1, 1)
    color = np.where(snow_mask[None], snow_rgb, color)
    water_rgb = np.array(palette.WATER_RGB, float).reshape(3, 1, 1)
    color = np.where(water[None], water_rgb, color)

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


def downscale(rgb, target_h):
    _, height, width = rgb.shape
    target_w = round(width * target_h / height)
    return np.asarray(zoom(rgb, (1, target_h / height, target_w / width), order=1)).astype("uint8")


def montage(panels, cols, gap=12):
    """Grid of equal-size RGB panels with white gutters."""
    height = max(p.shape[1] for p in panels)
    width = max(p.shape[2] for p in panels)
    padded = []
    for panel in panels:
        canvas = np.full((3, height, width), 255, np.uint8)
        canvas[:, :panel.shape[1], :panel.shape[2]] = panel
        padded.append(canvas)
    while len(padded) % cols:
        padded.append(np.full((3, height, width), 255, np.uint8))
    rows = []
    vgap = np.full((3, height, gap), 255, np.uint8)
    for r in range(0, len(padded), cols):
        row = padded[r]
        for panel in padded[r + 1:r + cols]:
            row = np.concatenate([row, vgap, panel], axis=2)
        rows.append(row)
    hgap = np.full((3, gap, rows[0].shape[2]), 255, np.uint8)
    out = rows[0]
    for row in rows[1:]:
        out = np.concatenate([out, hgap, row], axis=1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", default="e080_n20")
    ap.add_argument("--mid-lat", type=float, default=25.0)
    ap.add_argument("--hero", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--panel-h", type=int, default=900)
    args = ap.parse_args()

    chunk_dir = DATA / "work/planet/chunks" / args.chunk
    args.out.mkdir(parents=True, exist_ok=True)
    print(f"prepping base layers for {args.chunk} (mid-lat {args.mid_lat})...", flush=True)
    base = prep_base_layers(chunk_dir, args.out, args.mid_lat)

    exag_mults = [0.8, 1.0, 1.2]
    lights = [("single-NW", False), ("multidir", True)]
    base_z = relief.mercator_zfactor(args.mid_lat, EXAG)
    print(f"base z-factor at {args.mid_lat} = {base_z:.2f} (15 / cos)", flush=True)

    panels, legend = [], []
    for mult in exag_mults:
        for light_name, multidir in lights:
            hs = hillshade(base["height_merc"], args.out / f"hs_{light_name}_{mult}.tif",
                           base_z * mult, DEFAULTS["alt"], multidir)
            rgb = composite(base, hs, DEFAULTS)
            panels.append(downscale(rgb, args.panel_h))
            legend.append(f"exag x{mult} / {light_name}")
            print(f"  composited exag x{mult} {light_name}", flush=True)

    sheet = montage(panels, cols=len(lights))
    save_png(sheet, args.out / "sweep.png")

    # closest-to-default variant beside the hero
    default_idx = legend.index("exag x1.0 / single-NW")
    hero = downscale(read1_rgb(args.hero), args.panel_h)
    vs = montage([panels[default_idx], hero], cols=2)
    save_png(vs, args.out / "vs_hero.png")

    print("\nsweep.png grid (row = exaggeration, col = light):", flush=True)
    for i, label in enumerate(legend):
        print(f"  panel {i // len(lights)},{i % len(lights)}: {label}", flush=True)
    print(f"\nwrote {args.out}/sweep.png and vs_hero.png", flush=True)


def read1_rgb(path):
    with rasterio.open(path) as dataset:
        return dataset.read([1, 2, 3])


if __name__ == "__main__":
    raise SystemExit(main())
