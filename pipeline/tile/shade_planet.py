#!/usr/bin/env python3
"""Shade the whole (non-Antarctic) planet into ONE seamless Web-Mercator RGB raster.

Supersedes the 194-strip `tile_planet.py`, whose seam-avoidance hacks (a single global
z-factor, SVF off, per-strip `gdaldem` edges) caused the defects seen on the first globe:
blown-out tropics / flat high latitudes (wrong exaggeration), and faint block seams.

The fix is to compute every shading input GLOBALLY and STREAMING, so nothing is normalised
or edge-extrapolated per block, then composite in RAM-budgeted horizontal windows (the
composite is per-pixel, so windowing it cannot seam):

  1. warp the 4326 planet heightfield + masks once to a WebMercatorQuad-aligned 3857 grid;
  2. `gdaldem color-relief` the height globally (per-pixel -> seamless);
  3. custom per-row-z hillshade (pipeline/render/hillshade.py) -> seamless + correct 15x;
  4. sky-view factor once on a global downsample with a single global normalisation;
  5. composite each full-width horizontal window (reusing tile/shade.py::composite) with the
     latitude-ramped snow (blue-white shadows) and RGI glaciers, and cap both polar edges
     (>84N, <-59.5S -> flat deep-sea) so MapLibre's globe shows clean polar discs;
  6. add overviews and cut z0-8 512px tiles.

Every stage skips if its output already exists (resumable). Grid matches the existing tile
pyramid exactly (131072 x 93009).

    python -m pipeline.tile.shade_planet --out data/work/planet_tiles            # shade only
    python -m pipeline.tile.shade_planet --out data/work/planet_tiles --tiles    # + cut tiles
"""

import argparse
import gc
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window

from pipeline.render import hillshade, palette, snow
from pipeline.render.sky_view import horizon_svf
from pipeline.tile import shade
from pipeline.tile.shade import KNOBS

ROOT = Path.home() / "projects/maps"
PLANET = ROOT / "data/work/planet"
Z8_RES = 305.7483          # metres/pixel of a 512px WebMercatorQuad tile at zoom 8
EXAG = 15.0
ALT, AZ = KNOBS["alt"], 315.0
WINDOW_ROWS = 256          # full-width composite window. Height is the hard RAM lever (windows
                           # are full 131072-wide): with float32 composite this peaks ~6 GB. 384
                           # rows in float64 peaked ~18 GB and got OOM-killed. Launch the job with
                           # GDAL_CACHEMAX=512 to leave headroom for other work.
SVF_LONG_EDGE = 4096       # global sky-view downsample (long edge = raster width)
CAP_NORTH, CAP_SOUTH = 84.0, -59.5   # latitudes above/below which the poles are capped flat
CAP_RGB = (67, 118, 132)   # flat deep-sea colour for the polar caps (matches deep-ocean render)


def _run(cmd):
    subprocess.run([str(part) for part in cmd], check=True)


def warp_inputs(work: Path):
    """Warp height + ocean/water masks to the shared WMQ-aligned 3857 grid (skip if present)."""
    height = work / "height_3857.tif"
    if not height.exists():
        print("warp height -> 3857 ...", flush=True)
        _run(["gdalwarp", "-q", "-t_srs", "EPSG:3857", "-tr", Z8_RES, Z8_RES, "-tap",
              "-r", "bilinear", "-ot", "Float32", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
              "-co", "BIGTIFF=YES", "-co", "NUM_THREADS=ALL_CPUS",
              PLANET / "planet_heightfield.vrt", height])
    with rasterio.open(height) as dataset:
        bounds = [repr(value) for value in dataset.bounds]
        size = [str(dataset.width), str(dataset.height)]
    for name, src in (("ocean", "planet_oceanmask.vrt"), ("water", "planet_watermask.vrt")):
        out = work / f"{name}_3857.tif"
        if not out.exists():
            print(f"warp {name} -> 3857 ...", flush=True)
            _run(["gdalwarp", "-q", "-t_srs", "EPSG:3857", "-te", *bounds, "-ts", *size,
                  "-r", "near", "-ot", "Byte", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
                  "-co", "BIGTIFF=YES", PLANET / src, out])
    return height


def color_and_hillshade(work: Path, height: Path):
    """Global color-relief (land + sea) and the seamless per-row-z hillshade (skip if present)."""
    land, sea, hs = work / "land_3857.tif", work / "sea_3857.tif", work / "hs_3857.tif"
    # Land and sea are guarded independently so a palette change to one surface only
    # re-colours that surface (delete sea_3857.tif -> only sea regenerates; land stays).
    for surface, out in (("land", land), ("sea", sea)):
        if not out.exists():
            ramp = work / f"ramp_{surface}.txt"
            palette.write_color_relief(ramp, surface)
            print(f"color-relief ({surface}) ...", flush=True)
            _run(["gdaldem", "color-relief", "-q", height, ramp, out,
                  "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=YES"])
    if not hs.exists():
        print(f"per-row-z hillshade (EXAG={EXAG}) ...", flush=True)
        hillshade.per_row_zfactor_hillshade(height, hs, EXAG, ALT, AZ)
    return land, sea, hs


def global_occlusion(height: Path):
    """Sky-view occlusion (1 = valley, 0 = open) on a global downsample, normalised globally."""
    with rasterio.open(height) as dataset:
        full_w, full_h = dataset.width, dataset.height
        small_w = SVF_LONG_EDGE
        small_h = max(1, round(full_h / full_w * small_w))
        low = dataset.read(1, out_shape=(small_h, small_w),
                           resampling=Resampling.average).astype(float)
    low = np.nan_to_num(np.where(low < -500, np.nan, low), nan=0.0)
    m_per_px = Z8_RES * (full_w / small_w)
    svf = horizon_svf(low, m_per_px)
    occ = 1.0 - (svf - svf.min()) / (svf.max() - svf.min() + 1e-6)
    return occ  # shape (small_h, small_w)


def read3_window(path, window):
    with rasterio.open(path) as dataset:
        return dataset.read([1, 2, 3], window=window).astype(np.float32)


def read1_window(path, window):
    with rasterio.open(path) as dataset:
        return dataset.read(1, window=window)


def composite_planet(work: Path, land, sea, hs, occ, variants=None,
                     window_rows=WINDOW_ROWS, max_windows=None):
    """Composite the whole planet window-by-window into seamless RGB GeoTIFF(s).

    `variants` maps a name -> a dict of sea-knob overrides (sea_shade/sea_lift/sea_svf);
    each name is emitted as planet_rgb_<name>.tif in ONE shared pass — the expensive
    per-window work (reads, snow warp, glacier rasterize) is done once and only the cheap
    sea-light math + write differs per variant. `variants=None` keeps the production path:
    a single planet_rgb.tif shaded with the default KNOBS. `window_rows` is the RAM lever;
    `max_windows` (smoke test) stops after N windows, leaving a partially-filled raster.
    """
    if variants is None:
        variants = {None: None}
    outs = {name: (work / f"planet_rgb{f'_{name}' if name else ''}.tif",
                   work / f"planet_rgb{f'_{name}' if name else ''}.done")
            for name in variants}
    if max_windows is None and all(tif.exists() and dn.exists() for tif, dn in outs.values()):
        print("planet_rgb present -> skip composite", flush=True)
        return {name: tif for name, (tif, _) in outs.items()}
    with rasterio.open(work / "height_3857.tif") as h:
        width, height, transform = h.width, h.height, h.transform
    small_h, small_w = occ.shape
    profile = dict(driver="GTiff", width=width, height=height, count=3, dtype="uint8",
                   crs="EPSG:3857", transform=transform, tiled=True, blockxsize=512,
                   blockysize=512, compress="deflate", photometric="RGB", BIGTIFF="YES")
    ocean_p, water_p = work / "ocean_3857.tif", work / "water_3857.tif"
    writers = {name: rasterio.open(tif, "w", **profile) for name, (tif, _) in outs.items()}
    try:
        for index, row0 in enumerate(range(0, height, window_rows)):
            if max_windows is not None and index >= max_windows:
                break
            row1 = min(height, row0 + window_rows)
            win = Window(0, row0, width, row1 - row0)
            win_h = row1 - row0
            win_top = transform.f + row0 * transform.e
            win_bottom = transform.f + row1 * transform.e
            win_bounds = (transform.c, win_bottom, transform.c + width * transform.a, win_top)

            land_win, sea_win = read3_window(land, win), read3_window(sea, win)
            ocean_win = read1_window(ocean_p, win) != 0
            watercode = read1_window(water_p, win)
            water_win = (watercode == 2) | (watercode == 3)
            hs_win = read1_window(hs, win).astype(float)

            # snow: warp persistence + rasterize glaciers for this window's bounds.
            # Clear temps first — gdal_rasterize opens an existing file in UPDATE mode (would
            # burn onto the previous window's glaciers), and window heights differ at the edge.
            for temp in ("_sp_win.tif", "_rgi_win.tif"):
                (work / temp).unlink(missing_ok=True)
            persistence = snow.warp_persistence(win_bounds, width, win_h, work / "_sp_win.tif")
            snow_a = snow.snow_alpha(persistence, win_top, win_bottom)
            glacier = snow.rasterize_glaciers(win_bounds, width, win_h, work / "_rgi_win.tif")
            if glacier is not None:
                snow_a = np.maximum(snow_a, glacier.astype(float))

            # sky-view occlusion slice for this window (smooth -> nearest rows are fine)
            sr0 = int(row0 / height * small_h)
            sr1 = max(sr0 + 1, int(round(row1 / height * small_h)))
            occ_win = occ[sr0:sr1]

            # polar cap mask is shared across variants (geometry, not colour).
            latitude = snow.latitude_per_row(win_top, win_bottom, win_h)
            cap = (latitude > CAP_NORTH) | (latitude < CAP_SOUTH)

            for name, knobs in variants.items():
                if knobs:
                    KNOBS.update(knobs)  # only the sea knobs differ between variants
                rgb = shade.composite(land_win, sea_win, ocean_win, water_win, snow_a, hs_win,
                                      occ_win, (sr1 - sr0, small_w), (win_h, width))
                if cap.any():  # force the smeared polar edges to a flat deep-sea disc
                    for band in range(3):
                        rgb[band][cap] = CAP_RGB[band]
                writers[name].write(rgb, window=win)
                del rgb

            # release the window's big arrays each iteration so RSS can't creep up over the
            # hundreds of windows (fragmentation growth OOM-killed the earlier float64 runs).
            del land_win, sea_win, hs_win, persistence, snow_a, glacier, occ_win
            if index % 20 == 0:
                gc.collect()
                print(f"  composited rows {row0}/{height}", flush=True)
    finally:
        for writer in writers.values():
            writer.close()
    for temp in ("_sp_win.tif", "_rgi_win.tif"):
        (work / temp).unlink(missing_ok=True)
    if max_windows is None:  # a smoke test leaves a partial raster -> don't mark it done
        for _, dn in outs.values():
            dn.touch()
    for name, (tif, _) in outs.items():
        print(f"wrote {tif}", flush=True)
    return {name: tif for name, (tif, _) in outs.items()}


def build_tiles(planet_tif: Path, out: Path):
    """Overviews + z0-8 512px tiles into a staging dir, then swap over the live tiles."""
    print("overviews ...", flush=True)
    _run(["gdaladdo", "-r", "average", planet_tif, "2", "4", "8", "16", "32", "64", "128", "256"])
    staging = out / "tiles_new"
    print(f"cutting z0-8 512px tiles -> {staging} ...", flush=True)
    _run(["gdal", "raster", "tile", "--min-zoom=0", "--max-zoom=8", "--tile-size=512",
          "--resampling=cubic", "--convention=xyz", "--skip-blank", "--resume",
          str(planet_tif), str(staging)])
    live = out / "tiles"
    if live.exists():
        old = out / "tiles_old"
        if old.exists():
            _run(["rm", "-rf", str(old)])
        live.rename(old)
    staging.rename(live)
    print(f"tiles live -> {live} (previous kept at {out / 'tiles_old'})", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "data/work/planet_tiles")
    ap.add_argument("--tiles", action="store_true", help="also cut z0-8 tiles from the mosaic")
    args = ap.parse_args()
    work = args.out
    work.mkdir(parents=True, exist_ok=True)

    height = warp_inputs(work)
    land, sea, hs = color_and_hillshade(work, height)
    print("global sky-view factor ...", flush=True)
    occ = global_occlusion(height)
    planet_tif = composite_planet(work, land, sea, hs, occ)[None]
    if args.tiles:
        build_tiles(planet_tif, work)
    print("DONE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
