#!/usr/bin/env python3
"""Shade planet chunks into one seamless Web Mercator RGB raster, ready to tile.

The production form of the tile_chunk experiment: reproject each chunk's height + masks
to a WebMercatorQuad-aligned 3857 grid, mosaic them (VRT), then shade the MOSAIC once
(color-relief x hillshade x SVF, composited by mask) so there are no chunk-edge seams.
Knobs are locked to the values validated on the Nepal chunk (single-NW sun, the physical
15x exaggeration via the latitude z-factor, the tuned composite defaults).

Snow comes from NSIDC-0791 snow persistence (pipeline/render/snow.py) as a latitude-ramped
soft alpha — replacing WorldCover class 70, which left mid/high-latitude ranges bare. The
composite loads the whole region into RAM — fine per-region; a planet run must window it.

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

from pipeline.render import hillshade, lake_depth, palette, relief, snow
from pipeline.render.sky_view import horizon_svf

DATA = Path.home() / "projects/maps/data"
CHUNKS = DATA / "work/planet/chunks"
Z8_MERC_RES = 305.7483  # metres/pixel of a 512px WebMercatorQuad tile at zoom 8
EXAG = 15.0
MERCATOR = "EPSG:3857"

KNOBS = dict(alt=45.0, ambient=0.50, hi=1.30, exposure=1.05, saturation=1.18, warmth=0.06,
             svf_strength=0.20, svf_threshold=0.45, sea_shade=0.55, sea_lift=1.00,
             sea_saturation=0.90, sea_svf=0.5, snow_lo=0.55, snow_hi_pt=1.05,
             lake_curve="log1p")  # depth->ramp mapping; see lake_position()


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
    ap.add_argument("--knob", action="append", default=[], metavar="KEY=VALUE",
                    help="override a locked KNOBS entry (repeatable), e.g. --knob snow_floor=0.85")
    ap.add_argument("--zfactor", type=float, default=None,
                    help="use a single global hillshade z-factor instead of the per-region "
                         "mid-latitude one — for seamless multi-block planet shading")
    ap.add_argument("--per-row-z", action="store_true",
                    help="hillshade with a per-latitude-row z-factor (EXAG/cos(lat)) via the "
                         "custom seamless shader — correct exaggeration at every latitude")
    args = ap.parse_args()
    for override in args.knob:
        key, _, value = override.partition("=")
        if key not in KNOBS:
            raise SystemExit(f"unknown knob {key!r}; valid: {', '.join(sorted(KNOBS))}")
        # Most knobs are floats; lake_curve names a mapping, so coerce by the existing type.
        KNOBS[key] = value if isinstance(KNOBS[key], str) else float(value)
        print(f"knob override: {key} = {KNOBS[key]}", flush=True)
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
        bounds = dataset.bounds
        grid_h, grid_w = dataset.height, dataset.width
    print(f"region mosaic: {grid_w} x {grid_h} px in Mercator", flush=True)

    # The ramps are applied inside composite() from the elevation itself (palette.relief_lut,
    # 2026-07-16) -- the two `gdaldem color-relief` passes that used to materialise c_land/c_sea
    # were 24.4% of all planet-pass CPU and reproduced to <=1 DN by a 17.6 KB lookup table.
    hs_tif = args.out / "hs.tif"
    mid_lat = sum(cell_mid_lat(n) for n in args.cells) / len(args.cells)
    if args.per_row_z:
        print(f"hillshade: per-row z-factor (EXAG={EXAG}/cos(lat)), custom seamless shader", flush=True)
        hillshade.per_row_zfactor_hillshade(height_vrt, hs_tif, EXAG, KNOBS["alt"], 315.0)
    else:
        zfactor = args.zfactor if args.zfactor is not None else relief.mercator_zfactor(mid_lat, EXAG)
        print(f"hillshade z-factor {zfactor:.2f} (region mid-lat {mid_lat:.1f})", flush=True)
        run(["gdaldem", "hillshade", height_vrt, hs_tif, "-z", f"{zfactor:.4f}",
             "-alt", str(KNOBS["alt"]), "-az", "315", "-compute_edges"])

    # composite (whole region in RAM)
    heights = read1(height_vrt).astype("float32")
    ocean = read1(ocean_vrt) != 0
    watercode = read1(water_vrt)
    water = (watercode == 2) | (watercode == 3)
    hs = read1(hs_tif).astype(float)

    # snow: NSIDC-0791 persistence -> latitude-ramped soft alpha (pipeline/render/snow.py)
    persistence = snow.warp_persistence(
        (bounds.left, bounds.bottom, bounds.right, bounds.top), grid_w, grid_h,
        args.out / "sp_merc.tif")
    snow_a = snow.snow_alpha(persistence, bounds.top, bounds.bottom)
    glacier = snow.rasterize_glaciers(
        (bounds.left, bounds.bottom, bounds.right, bounds.top), grid_w, grid_h,
        args.out / "rgi_merc.tif")
    if glacier is not None:
        snow_a = np.maximum(snow_a, glacier.astype(float))
        print(f"unioned RGI glaciers: {int((glacier > 0).sum()):,} px", flush=True)

    # lake depth: GLOBathy modelled depth, tint-only (pipeline/render/lake_depth.py)
    depth = lake_depth.lakes_only(
        lake_depth.warp_depth((bounds.left, bounds.bottom, bounds.right, bounds.top),
                              grid_w, grid_h, args.out / "lakedepth_merc.tif"),
        watercode)
    if depth is not None and (depth > 0).any():
        print(f"lake depth: {int((depth > 0).sum()):,} px, max {depth.max():.0f} m, "
              f"curve={KNOBS['lake_curve']}", flush=True)
    else:
        print("lake depth: none in this region -> lakes stay flat", flush=True)

    with rasterio.open(height_vrt) as dataset:
        long_edge = 2400
        sw = max(1, round(dataset.width / max(dataset.width, dataset.height) * long_edge))
        sh = max(1, round(dataset.height / max(dataset.width, dataset.height) * long_edge))
        low = dataset.read(1, out_shape=(sh, sw), resampling=Resampling.average).astype(float)
        m_per_px = (dataset.bounds.right - dataset.bounds.left) / sw * math.cos(math.radians(mid_lat))
    low = np.nan_to_num(np.where(low < -500, np.nan, low), nan=0.0)
    svf = horizon_svf(low, m_per_px)
    occ = 1.0 - (svf - svf.min()) / (svf.max() - svf.min() + 1e-6)

    rgb = composite(heights, ocean, water, snow_a, hs, occ, (sh, sw), (grid_h, grid_w),
                    depth=depth)

    out_tif = args.out / "region_rgb.tif"
    with rasterio.open(height_vrt) as src:
        profile: dict[str, Any] = dict(
            driver="GTiff", height=grid_h, width=grid_w, count=3, dtype="uint8",
            crs=src.crs, transform=src.transform, tiled=True, blockxsize=512,
            blockysize=512, compress="deflate", photometric="RGB")
    with rasterio.open(out_tif, "w", **profile) as out:
        out.write(rgb)
    print(f"wrote {out_tif}", flush=True)


def lake_position(depth, curve):
    """Lake depth (m below surface) -> 0..1 along the lake ramp.

    This curve is the honesty/legibility dial, and the two pull against each other. The median
    lake is 11.2 m deep while Baikal is 1642 -- three orders of magnitude -- so a LINEAR axis
    parks 99% of lakes in the first 2% of the ramp and shows nothing. LOG1P spreads them
    (median -> 0.34) but hands most of the ramp to shallow water, which is exactly where
    GLOBathy's cone is least trustworthy (on the Caspian it claims 155 m where the truth is
    under 20 m, measured 2026-07-15), so it also maximises the visibility of the layer's worst
    error. SQRT (median -> 0.08) is the conservative middle. Judge on renders, not in the
    abstract.
    """
    if curve == "log1p":
        # Clamped like the others: LAKE_MAX_M is Baikal, so nothing should exceed it today,
        # but an unclamped log1p returns >1 for anything that does -- one re-tune of
        # LAKE_MAX_M to a shallower cap away from indexing off the end of the ramp.
        return (np.log1p(np.clip(depth, 0.0, palette.LAKE_MAX_M))
                / math.log1p(palette.LAKE_MAX_M))
    if curve == "sqrt":
        return np.sqrt(np.clip(depth, 0.0, palette.LAKE_MAX_M) / palette.LAKE_MAX_M)
    if curve == "linear":
        return np.clip(depth, 0.0, palette.LAKE_MAX_M) / palette.LAKE_MAX_M
    raise ValueError(f"unknown lake_curve {curve!r} (log1p | sqrt | linear)")


def composite(heights, ocean, water, snow_a, hs, occ, occ_shape, grid, depth=None):
    """Composite one window of the planet/region from ELEVATION, not pre-coloured rasters.

    `heights` is metres on the fused heightfield; the land and sea ramps are applied here via
    `palette.relief_lut`, which replaced two `gdaldem color-relief` passes on 2026-07-16.
    Those cost **28:19 and 24.4% of all pass CPU**, single-threaded, each reading the full 31 GB
    height raster to write 1 GB. Profiled: `libgdal 19.37%` (a per-pixel SEARCH over 241 ramp
    rows) vs `libdeflate 4.33%` -- so no threading flag could fix it. Our ramp rows are uniformly
    spaced, so the index is a divide, not a search; gdaldem cannot know that, numpy can. Verified
    against gdaldem's own output over all 12.19 G px, 6/6 bands: 96.7% identical, 3.3% at exactly
    1 DN, **zero beyond the uint8 contract**, and 2.5x faster in one read instead of two.

    Applying the ramps HERE rather than in each caller is deliberate: a per-call-site copy of a
    shared decision is precisely how the float32 window fix reached `composite` and never reached
    `hillshade` (11.6 GB, 2026-07-16). One implementation, both shade paths.
    """
    height, width = grid
    # float32 throughout — the output is 8-bit, and on the full-width planet windows float64
    # doubled peak RAM (~18 GB) and OOM-killed the box. asarray is a no-op when already float32.
    heights = np.asarray(heights, dtype=np.float32)
    land = palette.lut_lookup(palette.relief_lut("land"), "land", heights).astype(np.float32)
    sea = palette.lut_lookup(palette.relief_lut("sea"), "sea", heights).astype(np.float32)
    hs = np.asarray(hs, dtype=np.float32)
    snow_a = np.asarray(snow_a, dtype=np.float32)
    occ = np.asarray(occ, dtype=np.float32)
    lum = 0.299 * land[0] + 0.587 * land[1] + 0.114 * land[2]
    land = np.clip((lum[None] + (land - lum[None]) * KNOBS["saturation"])
                   * np.array([1.0, 1.0 - 0.5 * KNOBS["warmth"], 1.0 - KNOBS["warmth"]],
                              dtype=np.float32).reshape(3, 1, 1),
                   0, 255)
    sea_lum = 0.299 * sea[0] + 0.587 * sea[1] + 0.114 * sea[2]
    sea = np.clip(sea_lum[None] + (sea - sea_lum[None]) * KNOBS["sea_saturation"], 0, 255)
    color = np.where(ocean[None], sea, land)
    # Inland water: flat WATER_RGB by default. Where a lake carries GLOBathy depth, ramp it
    # instead -- on ABSOLUTE depth, never normalised per lake, since a per-lake normalisation
    # is the artificial gradient the 2026-07-07 prototype was rejected for (a pond would read
    # like Baikal). `depth` is already zeroed off watermask class 2 by the caller, so rivers
    # and the (class 1) Caspian cannot reach this branch.
    flat_water = np.array(palette.WATER_RGB, dtype=np.float32).reshape(3, 1, 1)
    if depth is None or KNOBS["lake_curve"] == "off":
        lake_color = flat_water  # 'off' is the A/B control: today's flat inland water
    else:
        depth = np.asarray(depth, dtype=np.float32)
        lut = np.array(palette.lake_lut(), dtype=np.float32).T  # (3, size)
        index = np.clip(lake_position(depth, KNOBS["lake_curve"]) * (lut.shape[1] - 1),
                        0, lut.shape[1] - 1).astype(np.int32)
        lake_color = np.where((depth > 0.0)[None], lut[:, index], flat_water)
    color = np.where(water[None], lake_color, color)

    flat = 255.0 * math.sin(math.radians(KNOBS["alt"]))
    light = np.clip(hs / flat, KNOBS["ambient"], KNOBS["hi"])
    burn = KNOBS["svf_strength"] * np.clip(
        (occ - KNOBS["svf_threshold"]) / (1 - KNOBS["svf_threshold"]), 0, 1) ** 1.4
    sh, sw = occ_shape
    svf_factor = np.clip(np.asarray(zoom(1.0 - burn, (height / sh, width / sw), order=1)), 0, 1)
    # Inland water stays flat; ocean gets a fraction (sea_svf) of the land-style occlusion
    # so basins and shelf edges read as recessed instead of a flat sheet.
    svf_factor = np.where(water, 1.0, svf_factor)
    svf_factor = np.where(ocean, 1.0 - (1.0 - svf_factor) * KNOBS["sea_svf"], svf_factor)
    light = np.where(water, np.clip(light, 0.85, KNOBS["hi"]), light)
    light = np.where(ocean, KNOBS["sea_lift"] + (light - 1.0) * KNOBS["sea_shade"], light)
    light = np.where(ocean | water, light,
                     KNOBS["ambient"] + (light - KNOBS["ambient"]) * KNOBS["exposure"])
    base_rgb = color * (light * svf_factor)

    # soft-alpha snow: blend snow over land by the ramped persistence alpha (no snow on water).
    # Snow colour is keyed to the hillshade light: glacial blue-white in shadow -> bright white
    # in sun (a two-colour ramp, not a neutral multiply), so snow keeps relief form instead of
    # muddying to grey on rugged terrain the way SNOW_RGB*light did.
    alpha = np.where(ocean | water, 0.0, snow_a)
    snow_t = np.clip((light - KNOBS["snow_lo"]) / (KNOBS["snow_hi_pt"] - KNOBS["snow_lo"]), 0.0, 1.0)
    snow_shadow = np.array(palette.SNOW_SHADOW_RGB, dtype=np.float32).reshape(3, 1, 1)
    snow_lit = np.array(palette.SNOW_RGB, dtype=np.float32).reshape(3, 1, 1)
    snow_rgb = snow_shadow + (snow_lit - snow_shadow) * snow_t[None]
    final = base_rgb * (1.0 - alpha)[None] + snow_rgb * alpha[None]
    return np.clip(final, 0, 255).astype("uint8")


if __name__ == "__main__":
    raise SystemExit(main())
