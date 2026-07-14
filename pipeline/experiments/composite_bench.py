"""Benchmark the composite optimizations against the current code, on real windows.

Measures, and VERIFIES pixel-identical output for:
  #1 share-across-variants: current does composite() twice (v1,v2); optimized does
     composite(v1) once then patches only the OCEAN pixels for v2 (land/snow/water are
     sea-knob-independent, so they're identical by construction).
  #2 precompute snow/glacier: current spawns a gdalwarp + gdal_rasterize per window;
     precomputed = read a slice from a global raster. We time the per-window subprocess
     cost vs a plain windowed read to show the gap.
  #3 window size: throughput (rows/s) at 192 vs 768 rows.

Runs a few windows only (the live tiling job is using cores, so ABSOLUTE times are
inflated ~2-3x by contention — the RELATIVE speedups and the identity checks are the point).
"""
import time

import numpy as np
import rasterio
from rasterio.windows import Window

from pipeline.tile import shade_planet as sp, shade
from pipeline.tile.shade import KNOBS
from pipeline.render import snow

WORK = sp.ROOT / "data/work/planet_tiles"
V1 = {"sea_shade": 0.55, "sea_lift": 1.00, "sea_svf": 0.5}
V2 = {"sea_shade": 0.72, "sea_lift": 0.98, "sea_svf": 0.7}


def load_window(row0, rows, width, transform):
    win = Window(0, row0, width, rows)
    top = transform.f + row0 * transform.e
    bottom = transform.f + (row0 + rows) * transform.e
    bounds = (transform.c, bottom, transform.c + width * transform.a, top)
    land = sp.read3_window(WORK / "land_3857.tif", win)
    sea = sp.read3_window(WORK / "sea_3857.tif", win)
    ocean = sp.read1_window(WORK / "ocean_3857.tif", win) != 0
    wc = sp.read1_window(WORK / "water_3857.tif", win)
    water = (wc == 2) | (wc == 3)
    hs = sp.read1_window(WORK / "hs_3857.tif", win).astype(float)
    persistence = snow.warp_persistence(bounds, width, rows, WORK / "_bench_sp.tif")
    snow_a = snow.snow_alpha(persistence, top, bottom)
    glac = snow.rasterize_glaciers(bounds, width, rows, WORK / "_bench_rgi.tif")
    if glac is not None:
        snow_a = np.maximum(snow_a, glac.astype(float))
    occ = np.ones((4, 4096), np.float32)  # SVF slice shape; value irrelevant to timing/identity
    return dict(land=land, sea=sea, ocean=ocean, water=water, hs=hs, snow_a=snow_a,
                occ=occ, grid=(rows, width))


def composite_current(w, knobs):
    """Exactly the production path: set the sea knobs, run the whole composite."""
    KNOBS.update(knobs)
    return shade.composite(w["land"], w["sea"], w["ocean"], w["water"], w["snow_a"],
                           w["hs"], w["occ"], (4, 4096), w["grid"])


def composite_shared_patch(w, knobs_a, knobs_b):
    """Optimized: full composite for A, then recompute ONLY ocean pixels for B."""
    rgb_a = composite_current(w, knobs_a).copy()
    # Recompute the pre-sea intermediates the ocean patch needs (mirrors shade.composite).
    land, sea, hs, ocean, water = w["land"], w["sea"], w["hs"], w["ocean"], w["water"]
    height, width = w["grid"]
    land = np.asarray(land, np.float32); sea = np.asarray(sea, np.float32); hs = np.asarray(hs, np.float32)
    lum = 0.299 * land[0] + 0.587 * land[1] + 0.114 * land[2]
    land = np.clip((lum[None] + (land - lum[None]) * KNOBS["saturation"])
                   * np.array([1.0, 1.0 - 0.5 * KNOBS["warmth"], 1.0 - KNOBS["warmth"]],
                              np.float32).reshape(3, 1, 1), 0, 255)
    sea_lum = 0.299 * sea[0] + 0.587 * sea[1] + 0.114 * sea[2]
    sea = np.clip(sea_lum[None] + (sea - sea_lum[None]) * KNOBS["sea_saturation"], 0, 255)
    color = np.where(ocean[None], sea, land)
    color = np.where(water[None], np.array(shade.palette.WATER_RGB, np.float32).reshape(3, 1, 1), color)
    flat = 255.0 * np.sin(np.radians(KNOBS["alt"]))
    light_raw = np.clip(hs / flat, KNOBS["ambient"], KNOBS["hi"])
    from scipy.ndimage import zoom
    burn = KNOBS["svf_strength"] * np.clip((w["occ"] - KNOBS["svf_threshold"])
                                           / (1 - KNOBS["svf_threshold"]), 0, 1) ** 1.4
    svf = np.clip(np.asarray(zoom(1.0 - burn, (height / 4, width / 4096), order=1)), 0, 1)
    svf = np.where(water, 1.0, svf)  # ocean keeps land-style svf here (pre sea_svf)

    rgb_b = rgb_a.copy()
    oc = ocean  # boolean mask
    light_o = knobs_b["sea_lift"] + (light_raw[oc] - 1.0) * knobs_b["sea_shade"]
    svf_o = 1.0 - (1.0 - svf[oc]) * knobs_b["sea_svf"]
    factor = light_o * svf_o
    for band in range(3):
        rgb_b[band][oc] = np.clip(color[band][oc] * factor, 0, 255).astype(np.uint8)
    return rgb_a, rgb_b


def main():
    with rasterio.open(WORK / "height_3857.tif") as h:
        width, transform = h.width, h.transform
    rows = 192
    test_rows = [18000, 30000, 46000, 64000, 78000]  # spread of latitudes

    print(f"loading {len(test_rows)} windows ({rows} rows x {width} px) ...", flush=True)
    windows = [load_window(r, rows, width, transform) for r in test_rows]

    # correctness: optimized v2 must equal the current composite(v2) exactly
    print("\n#1 correctness (optimized-v2 == current-v2):", flush=True)
    for i, w in enumerate(windows):
        ref_v2 = composite_current(w, V2)
        _, opt_v2 = composite_shared_patch(w, V1, V2)
        same = np.array_equal(ref_v2, opt_v2)
        diff = int(np.abs(ref_v2.astype(int) - opt_v2.astype(int)).max())
        print(f"  window {test_rows[i]:6d}: identical={same}  max_abs_diff={diff}", flush=True)

    # timing: current (2x composite) vs optimized (composite + ocean patch)
    print("\n#1 timing per window (current 2x composite vs shared+patch):", flush=True)
    cur_tot = opt_tot = 0.0
    for i, w in enumerate(windows):
        t = time.time(); composite_current(w, V1); composite_current(w, V2); cur = time.time() - t
        t = time.time(); composite_shared_patch(w, V1, V2); opt = time.time() - t
        cur_tot += cur; opt_tot += opt
        print(f"  window {test_rows[i]:6d}: current={cur:.2f}s  optimized={opt:.2f}s  "
              f"({100*(cur-opt)/cur:.0f}% faster)", flush=True)
    print(f"  TOTAL: current={cur_tot:.2f}s  optimized={opt_tot:.2f}s  "
          f"-> {100*(cur_tot-opt_tot)/cur_tot:.0f}% faster for a 2-variant run", flush=True)

    # #2: per-window snow/glacier subprocess cost vs a plain windowed read of the same size
    print("\n#2 snow/glacier: per-window subprocess vs precomputed slice-read:", flush=True)
    w0 = load_window(30000, rows, width, transform)  # triggers the subprocesses
    win = Window(0, 30000, width, rows)
    top = transform.f + 30000 * transform.e
    bottom = transform.f + (30000 + rows) * transform.e
    bounds = (transform.c, bottom, transform.c + width * transform.a, top)
    t = time.time(); snow.warp_persistence(bounds, width, rows, WORK / "_bench_sp.tif"); t_warp = time.time() - t
    t = time.time(); snow.rasterize_glaciers(bounds, width, rows, WORK / "_bench_rgi.tif"); t_rgi = time.time() - t
    t = time.time(); sp.read1_window(WORK / "hs_3857.tif", win); t_read = time.time() - t
    print(f"  snow warp subprocess : {t_warp:.2f}s", flush=True)
    print(f"  glacier rasterize sub: {t_rgi:.2f}s", flush=True)
    print(f"  (a precomputed slice read of the same window ~ {t_read:.2f}s)", flush=True)
    print(f"  => precompute saves ~{t_warp + t_rgi - 2*t_read:.2f}s/window", flush=True)

    # #3 window size throughput
    print("\n#3 window size throughput (composite rows/s):", flush=True)
    for wr in (192, 768):
        w = load_window(30000, wr, width, transform)
        t = time.time(); composite_current(w, V1); dt = time.time() - t
        print(f"  {wr:4d} rows: {dt:.2f}s -> {wr/dt:.0f} rows/s", flush=True)

    for f in ("_bench_sp.tif", "_bench_rgi.tif"):
        (WORK / f).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
