#!/usr/bin/env python3
"""Shade planet chunks into one seamless Web Mercator RGB raster, ready to tile.

The production form of the tile_chunk experiment: reproject each chunk's height + masks
to a WebMercatorQuad-aligned 3857 grid, mosaic them (VRT), then shade the MOSAIC once
(color-relief x hillshade x SVF, composited by mask) so there are no chunk-edge seams.
Knobs are locked to the values validated on the Nepal chunk (single-NW sun, the physical
15x exaggeration via the latitude z-factor, the tuned composite defaults).

Snow comes from whatever ESA WorldCover is on disk (worldcover.vrt); a full-planet run
needs a global snow layer first (PLAN Phase 2). The composite loads the whole region into
RAM — fine per-region; a planet run must window it.

    python -m pipeline.tile.shade --cells e070_n20 e080_n20 ... --out data/work/tiles/southasia
"""

import argparse
import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from scipy.ndimage import zoom

from pipeline.render import palette, relief
from pipeline.render.sky_view import horizon_svf

DATA = Path.home() / "projects/maps/data"
WORLDCOVER_VRT = DATA / "raw/worldcover/worldcover.vrt"
CHUNKS = DATA / "work/planet/chunks"
Z8_MERC_RES = 305.7483  # metres/pixel of a 512px WebMercatorQuad tile at zoom 8
EXAG = 15.0
MERCATOR = "EPSG:3857"

KNOBS = dict(alt=45.0, ambient=0.50, hi=1.30, exposure=1.30, saturation=1.18, warmth=0.06,
             svf_strength=0.20, svf_threshold=0.45, sea_shade=0.26, sea_lift=1.08,
             sea_saturation=0.90, snow_floor=0.78)


def run(cmd):
    subprocess.run([str(part) for part in cmd], check=True, capture_output=True)


def cell_mid_lat(name: str) -> float:
    """Centre latitude of a 10-degree cell from its name, e.g. e080_n20 -> 25.0."""
    lat_part = name.split("_")[1]
    lat = int(lat_part[1:]) * (1 if lat_part[0] == "n" else -1)
    return lat + 5.0


def reproject_cell(name: str, merc_dir: Path):
    """Warp one cell's height + masks to a WMQ-aligned 3857 grid (-tap keeps chunks
    pixel-aligned to each other and to the tile grid, so the mosaic is seamless)."""
    chunk = CHUNKS / name
    height = merc_dir / f"{name}_height.tif"
    run(["gdalwarp", "-overwrite", "-q", "-t_srs", MERCATOR,
         "-tr", Z8_MERC_RES, Z8_MERC_RES, "-tap", "-r", "bilinear",
         chunk / "heightfield_10s.tif", height])
    with rasterio.open(height) as dataset:
        te = [repr(value) for value in dataset.bounds]
        ts = [str(dataset.width), str(dataset.height)]
    for layer in ("oceanmask", "watermask"):
        run(["gdalwarp", "-overwrite", "-q", "-t_srs", MERCATOR, "-te", *te, "-ts", *ts,
             "-r", "near", chunk / f"{layer}_10s.tif", merc_dir / f"{name}_{layer}.tif"])


def build_vrt(vrt_path, sources):
    run(["gdalbuildvrt", "-overwrite", vrt_path, *sources])


def read3(path):
    with rasterio.open(path) as dataset:
        return dataset.read([1, 2, 3]).astype(float)


def read1(path, shape=None):
    with rasterio.open(path) as dataset:
        if shape is None:
            return dataset.read(1)
        return dataset.read(1, out_shape=shape, resampling=Resampling.nearest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    merc = args.out / "merc"
    merc.mkdir(parents=True, exist_ok=True)

    print(f"reprojecting {len(args.cells)} cells to WMQ-aligned Mercator...", flush=True)
    for name in args.cells:
        reproject_cell(name, merc)

    height_vrt = args.out / "height.vrt"
    ocean_vrt = args.out / "ocean.vrt"
    water_vrt = args.out / "water.vrt"
    build_vrt(height_vrt, [merc / f"{n}_height.tif" for n in args.cells])
    build_vrt(ocean_vrt, [merc / f"{n}_oceanmask.tif" for n in args.cells])
    build_vrt(water_vrt, [merc / f"{n}_watermask.tif" for n in args.cells])

    with rasterio.open(height_vrt) as dataset:
        te = [repr(value) for value in dataset.bounds]
        ts = [str(dataset.width), str(dataset.height)]
        grid_h, grid_w = dataset.height, dataset.width
    print(f"region mosaic: {grid_w} x {grid_h} px in Mercator", flush=True)

    # snow from whatever WorldCover is on disk (partial coverage -> no snow where absent)
    snow_cls = args.out / "snow_cls.tif"
    run(["gdalwarp", "-overwrite", "-q", "-t_srs", MERCATOR, "-te", *te, "-ts", *ts,
         "-r", "near", "-ot", "Byte", WORLDCOVER_VRT, snow_cls])

    # color-relief (shared palette) on the mosaic; hillshade with the physical z-factor
    # at the region's centre latitude (single band is fine per-region; planet bands it)
    land_ramp, sea_ramp = args.out / "ramp_land.txt", args.out / "ramp_sea.txt"
    palette.write_color_relief(land_ramp, "land")
    palette.write_color_relief(sea_ramp, "sea")
    land_tif, sea_tif, hs_tif = args.out / "c_land.tif", args.out / "c_sea.tif", args.out / "hs.tif"
    run(["gdaldem", "color-relief", height_vrt, land_ramp, land_tif])
    run(["gdaldem", "color-relief", height_vrt, sea_ramp, sea_tif])
    mid_lat = sum(cell_mid_lat(n) for n in args.cells) / len(args.cells)
    zfactor = relief.mercator_zfactor(mid_lat, EXAG)
    print(f"hillshade z-factor at region mid-lat {mid_lat:.1f} = {zfactor:.2f}", flush=True)
    run(["gdaldem", "hillshade", height_vrt, hs_tif, "-z", f"{zfactor:.4f}",
         "-alt", str(KNOBS["alt"]), "-az", "315", "-compute_edges"])

    # composite (whole region in RAM)
    land, sea = read3(land_tif), read3(sea_tif)
    ocean = read1(ocean_vrt) != 0
    watercode = read1(water_vrt)
    water = (watercode == 2) | (watercode == 3)
    snow_mask = read1(snow_cls) == 70
    hs = read1(hs_tif).astype(float)

    with rasterio.open(height_vrt) as dataset:
        long_edge = 2400
        sw = max(1, round(dataset.width / max(dataset.width, dataset.height) * long_edge))
        sh = max(1, round(dataset.height / max(dataset.width, dataset.height) * long_edge))
        low = dataset.read(1, out_shape=(sh, sw), resampling=Resampling.average).astype(float)
        m_per_px = (dataset.bounds.right - dataset.bounds.left) / sw * math.cos(math.radians(mid_lat))
    low = np.nan_to_num(np.where(low < -500, np.nan, low), nan=0.0)
    svf = horizon_svf(low, m_per_px)
    occ = 1.0 - (svf - svf.min()) / (svf.max() - svf.min() + 1e-6)

    rgb = composite(land, sea, ocean, water, snow_mask, hs, occ, (sh, sw), (grid_h, grid_w))

    out_tif = args.out / "region_rgb.tif"
    with rasterio.open(height_vrt) as src:
        profile: dict[str, Any] = dict(
            driver="GTiff", height=grid_h, width=grid_w, count=3, dtype="uint8",
            crs=src.crs, transform=src.transform, tiled=True, blockxsize=512,
            blockysize=512, compress="deflate", photometric="RGB")
    with rasterio.open(out_tif, "w", **profile) as out:
        out.write(rgb)
    print(f"wrote {out_tif}", flush=True)


def composite(land, sea, ocean, water, snow_mask, hs, occ, occ_shape, grid):
    height, width = grid
    lum = 0.299 * land[0] + 0.587 * land[1] + 0.114 * land[2]
    land = np.clip((lum[None] + (land - lum[None]) * KNOBS["saturation"])
                   * np.array([1.0, 1.0 - 0.5 * KNOBS["warmth"], 1.0 - KNOBS["warmth"]]).reshape(3, 1, 1),
                   0, 255)
    sea_lum = 0.299 * sea[0] + 0.587 * sea[1] + 0.114 * sea[2]
    sea = np.clip(sea_lum[None] + (sea - sea_lum[None]) * KNOBS["sea_saturation"], 0, 255)
    color = np.where(ocean[None], sea, land)
    color = np.where(snow_mask[None], np.array(palette.SNOW_RGB, float).reshape(3, 1, 1), color)
    color = np.where(water[None], np.array(palette.WATER_RGB, float).reshape(3, 1, 1), color)

    flat = 255.0 * math.sin(math.radians(KNOBS["alt"]))
    light = np.clip(hs / flat, KNOBS["ambient"], KNOBS["hi"])
    burn = KNOBS["svf_strength"] * np.clip(
        (occ - KNOBS["svf_threshold"]) / (1 - KNOBS["svf_threshold"]), 0, 1) ** 1.4
    sh, sw = occ_shape
    svf_factor = np.clip(np.asarray(zoom(1.0 - burn, (height / sh, width / sw), order=1)), 0, 1)
    svf_factor = np.where(ocean | water, 1.0, svf_factor)
    light = np.where(water, np.clip(light, 0.85, KNOBS["hi"]), light)
    light = np.where(ocean, KNOBS["sea_lift"] + (light - 1.0) * KNOBS["sea_shade"], light)
    light = np.where(snow_mask, np.maximum(light, KNOBS["snow_floor"]), light)
    light = np.where(ocean | water, light,
                     KNOBS["ambient"] + (light - KNOBS["ambient"]) * KNOBS["exposure"])
    return np.clip(color * (light * svf_factor), 0, 255).astype("uint8")


if __name__ == "__main__":
    raise SystemExit(main())
