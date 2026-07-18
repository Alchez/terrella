#!/usr/bin/env python3
"""Shade the whole (non-Antarctic) planet into ONE seamless Web-Mercator RGB raster.

Supersedes the 194-strip `tile_planet.py`, whose seam-avoidance hacks (a single global
z-factor, SVF off, per-strip `gdaldem` edges) caused the defects seen on the first globe:
blown-out tropics / flat high latitudes (wrong exaggeration), and faint block seams. That
script was deleted on 2026-07-16 rather than left runnable beside this one -- it defaulted
to the same --out and would have cut tiles into the LIVE pyramid with no rollback. Read it
with `git show a7b7223:pipeline/tile/tile_planet.py`; the record is HISTORY 2026-07-14.

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
  6. cut z0-8 512px tiles (no overview step -- `gdal raster tile` never reads them; see build_tiles).

Every stage skips if its output is FRESH -- present, completed, and newer than everything it
derives from (`is_stale`). An exists()-only guard cannot tell "built" from "still correct":
the 2026-07-15 Caspian re-fuse rewrote 4 of the 540 chunks, and a plain re-run would have
skipped every stage and silently re-cut tiles from the pre-Caspian, pre-sea-rework rasters.
Grid matches the existing tile pyramid exactly (131072 x 93009).

    python -m pipeline.tile.shade_planet --out data/work/planet_tiles            # shade only
    python -m pipeline.tile.shade_planet --out data/work/planet_tiles --tiles    # + cut tiles
"""

import argparse
import gc
import json
import math
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window

from pipeline.render import hillshade, lake_depth, palette, snow
from pipeline.render.sky_view import horizon_svf
from pipeline.tile import shade
from pipeline.tile.shade import KNOBS

ROOT = Path.home() / "projects/maps"
PLANET = ROOT / "data/work/planet"
Z8_RES = 305.7483          # metres/pixel of a 512px WebMercatorQuad tile at zoom 8
EXAG = 15.0
ALT, AZ = KNOBS["alt"], 315.0
WINDOW_ROWS = 256          # the snow-persistence banded-warp height (Phase A) AND composite_planet's
                           # DEFAULT window. Must stay 256: the persistence raster is banded at this
                           # height to be byte-identical to the per-window warp it replaced, and the
                           # composite reads slices of that fixed raster. Also the RAM lever for the
                           # serial default (full 131072-wide float32 windows peak ~6 GB; 384 rows in
                           # float64 peaked ~18 GB, OOM). Launch with GDAL_CACHEMAX=512 for headroom.
COMPOSITE_ROWS = 128       # PRODUCTION composite window (optimisation #5, 2026-07-18). Smaller than
                           # WINDOW_ROWS purely to fit N_WORKERS concurrent windows under the 12 G cap
                           # -- 256/N3 OOMs, and 128 is not a speed lever by itself (serial rows/s ~
                           # equal). It shifts the look sub-perceptibly (SVF window slicing; worst 15
                           # DN on amplified mountain-snow edges, invisible at true scale -- Rohan
                           # judged it on a render 2026-07-18). Reads 128-row slices of the 256-banded
                           # persistence, exactly as the delta A/B validated. → HISTORY 2026-07-18.
N_WORKERS = 4              # composite worker threads. The knee: numpy is DRAM-bandwidth-bound, so
                           # threads scale 1.8×@2 / 3.1×@4 / 3.4×@6, and RAM grows linearly (128-row
                           # peak: N4 8.5 G, N6 11.3 G). 4 = ~3.1× at safe margin under 12 G.
SVF_LONG_EDGE = 4096       # global sky-view downsample (long edge = raster width)
CAP_NORTH, CAP_SOUTH = 84.0, -59.5   # latitudes above/below which the poles are capped flat
CAP_RGB = (67, 118, 132)   # flat deep-sea colour for the polar caps (matches deep-ocean render)
INFLIGHT_BUFFER = 2        # windows read AHEAD of the workers (optimisation #5): the main thread
                           # may queue max_workers + this many window-input bundles before it must
                           # block on the oldest result and write it. Bounds peak RAM to
                           # (max_workers + INFLIGHT_BUFFER) windows in flight; keep it small.


def _run(cmd):
    subprocess.run([str(part) for part in cmd], check=True)


def done_marker(output: Path) -> Path:
    """The completion stamp beside `output` (height_3857.tif -> height_3857.done)."""
    return output.with_suffix(".done")


def mark_done(output: Path) -> None:
    """Stamp `output` complete. Call ONLY after its stage has returned successfully."""
    done_marker(output).touch()


def newest_mtime(*inputs: Path) -> float:
    """Newest mtime among `inputs`, recursing into directories. Missing paths score 0.0.

    Directories are walked rather than stat'ed because a VRT's own mtime does NOT move when
    the chunks it points at are re-fused -- which is exactly how the Caspian re-fuse stayed
    invisible to the old guard. The planet is 540 cells x 3 rasters, so this is ~1.6k stats.
    """
    newest = 0.0
    for path in inputs:
        if not path.exists():
            continue
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    newest = max(newest, child.stat().st_mtime)
        else:
            newest = max(newest, path.stat().st_mtime)
    return newest


def is_stale(output: Path, *inputs: Path) -> bool:
    """True if `output` must be rebuilt: never completed, or older than any of `inputs`.

    Freshness is read from the .done marker, never from `output` itself: GDAL creates its
    target at the START of a run, so a crashed pass leaves a full-sized, freshly-stamped,
    half-written raster that an mtime test on the raster would happily accept as current.
    """
    if not output.exists() or not done_marker(output).exists():
        return True
    return newest_mtime(*inputs) > done_marker(output).stat().st_mtime


def write_if_changed(path: Path, text: str) -> Path:
    """Write `text` to `path` only when it differs, and return `path`.

    The only-when-different part is load-bearing, not an optimisation: it lets a generated
    file stand in as a dependency for `is_stale`. Tunables like KNOBS and the ramp colours
    live in source, whose mtime moves on any `git checkout` and would force a full planet
    rebuild; materialised here, their mtime moves if and only if a VALUE actually changed.
    """
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
    return path


# KNOBS entries consumed by the HILLSHADE stage rather than by composite(). Excluded from
# composite_params below.
#
# The exclusion is not an optimisation, it is correctness: these already have a file of their own
# (hs_params.json), and they reach planet_rgb through composite_deps' dependency on `hs` -- change
# one, the hillshade restages, its mtime moves, and the composite restages behind it. Recording
# them HERE as well would restage a 53.8 min composite + 3:44 tile cut for byte-identical pixels
# every time the fill is merely present at strength 0 -- which is exactly what it did when
# `fill_strength` was first added to KNOBS (caught 2026-07-17, before any pass ran).
#
# `alt` is deliberately NOT in here: the hillshade takes it AND composite reads it (`flat =
# 255*sin(alt)`), so it belongs in both records. The filter defaults to INCLUDE, so a new composite
# knob is tracked unless someone deliberately names it here.
HILLSHADE_ONLY_KNOBS = frozenset({"fill_strength"})


def hs_params() -> str:
    """The hillshade's tunables, recorded as hs_3857's dependency — composite_params' sibling.

    Split out of build_hillshade on 2026-07-17 so BOTH halves of the freshness contract are
    testable from the outside. The asymmetry was itself the hazard: composite_params had tests
    pinning what it must and must not record, and this side had none, while every freshness bug so
    far has been a tunable that failed to reach one of these two records.

    The fill sun's geometry is recorded ONLY when it is actually on. This exists to answer "would a
    rerun produce different pixels?", and at strength 0 the fill provably cannot -- it is skipped
    entirely and the result is bit-identical (tests/test_hillshade.py). Recording it unconditionally
    would restage an 8:28 hillshade, a 53.8 min composite and a 3:44 tile cut to reproduce the same
    bytes, and would falsely report the LIVE pyramid as stale. Turning the fill on flips this dict
    and correctly restages all three.

    Composite-stage knobs must NOT appear here: this raster cannot see them, so recording one
    restages an 11:48 hillshade that would produce identical bytes.
    """
    params: dict[str, Any] = {"exag": EXAG, "alt": ALT, "az": AZ}
    if KNOBS["fill_strength"] != 0.0:
        params["fill"] = {"strength": KNOBS["fill_strength"],
                          "alt": hillshade.FILL_ALTITUDE, "az": hillshade.FILL_AZIMUTH}
    return json.dumps(params, sort_keys=True, indent=2)


def composite_params(variants, window_rows=WINDOW_ROWS) -> str:
    """The composite's tunables, recorded as planet_rgb's dependency.

    KNOBS and the palette colours never reach a file of their own, so without this a knob or
    palette edit (WATER_RGB -> 8EC6C4, or a lake-ramp re-tune) would leave a stale planet_rgb
    looking fresh. LAKE_STOPS earns its place the hard way: an untracked colour relationship
    is exactly how WATER_RGB drifted silently against the sea. `lake_curve` needs no entry of
    its own -- it rides in KNOBS. Must be read BEFORE the variant loop, which mutates KNOBS.

    `window_rows` (the composite window height) is recorded because it is NOT just a RAM lever:
    it slices the SVF occlusion per window, so a change perturbs the output sub-perceptibly (the
    256->128 A/B, 2026-07-18). Without it here, switching the production window height would leave a
    stale planet_rgb looking fresh -- the same untracked-input trap as WATER_RGB. `max_workers` is
    deliberately NOT recorded: threading is byte-identical (proven), so it changes no pixel.

    HILLSHADE_ONLY_KNOBS are filtered out -- see its comment: they are tracked by hs_params.json and
    arrive here through `hs`, so repeating them would force composites that change nothing.
    """
    knobs = {key: value for key, value in KNOBS.items() if key not in HILLSHADE_ONLY_KNOBS}
    return json.dumps({"knobs": knobs, "water_rgb": palette.WATER_RGB,
                       "composite_window_rows": window_rows,
                       # land/sea stops moved in here on 2026-07-16 when color-relief was
                       # deleted: they used to be tracked by ramp_{land,sea}.txt's mtime, whose
                       # whole purpose was to gate the gdaldem stages. With those gone, nothing
                       # else would notice a ramp re-tune and planet_rgb would sit falsely fresh
                       # -- the exact failure this function exists to prevent.
                       "land_stops": palette.LAND_STOPS, "sea_stops": palette.SEA_STOPS,
                       "land_max_m": palette.LAND_MAX_M, "sea_min_m": palette.SEA_MIN_M,
                       "lut_step_m": palette.LUT_STEP_M,
                       "snow_rgb": palette.SNOW_RGB,
                       "snow_shadow_rgb": palette.SNOW_SHADOW_RGB,
                       "lake_stops": palette.LAKE_STOPS,
                       "lake_max_m": palette.LAKE_MAX_M,
                       "cap": [CAP_NORTH, CAP_SOUTH, list(CAP_RGB)],
                       "variants": {str(name): knobs for name, knobs in variants.items()}},
                      sort_keys=True, indent=2)


def composite_deps(work, hs, params) -> tuple:
    """Everything planet_rgb must be newer than.

    `height_3857.tif` replaced land_3857/sea_3857 here on 2026-07-16: composite() now applies the
    ramps itself from elevation, so the height raster IS the colour input. The ramp constants ride
    in `params` (composite_params) rather than in ramp_*.txt, which no longer exists.

    `snow_persistence_3857.tif` + `glacier_3857.tif` joined on 2026-07-18 (optimisation #4): the
    composite reads pre-warped snow slices per window instead of forking gdalwarp/gdal_rasterize in
    the loop, so a re-warp (new NSIDC/RGI, or a re-fuse to a new grid) must restage it. `glacier`
    may be absent (RGI not downloaded) -- `newest_mtime` scores a missing path 0.0, so listing it
    unconditionally is safe. The ramp TUNABLES (`RAMP_*`) run at composite time inside `snow_alpha`,
    so they ride in `composite_params`, NOT here -- this pair tracks the warp SOURCES only.
    """
    return (work / "height_3857.tif", hs, work / "ocean_3857.tif", work / "water_3857.tif",
            work / "lakedepth_3857.tif", work / "snow_persistence_3857.tif",
            work / "glacier_3857.tif", params)


def warp_inputs(work: Path):
    """Warp height + ocean/water masks to the shared WMQ-aligned 3857 grid (skip if fresh).

    Each warp depends on the chunk DIRECTORY, not just its VRT -- re-fusing a cell leaves the
    VRT untouched, so the directory walk is the only thing that sees the change.
    """
    chunks = PLANET / "chunks"
    height = work / "height_3857.tif"
    if is_stale(height, PLANET / "planet_heightfield.vrt", chunks):
        print("warp height -> 3857 ...", flush=True)
        height.unlink(missing_ok=True)  # gdalwarp UPDATES an existing target; it must be gone
        _run(["gdalwarp", "-q", "-t_srs", "EPSG:3857", "-tr", Z8_RES, Z8_RES, "-tap",
              "-r", "bilinear", "-ot", "Float32", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
              "-co", "BIGTIFF=YES", "-co", "NUM_THREADS=ALL_CPUS",
              PLANET / "planet_heightfield.vrt", height])
        mark_done(height)
    with rasterio.open(height) as dataset:
        bounds = [repr(value) for value in dataset.bounds]
        size = [str(dataset.width), str(dataset.height)]
        # Numeric forms for the snow warps below, which take a (left, bottom, right, top) tuple and
        # int width/height rather than the gdalwarp -te/-ts string lists the mask warps splice in.
        grid_bounds = tuple(dataset.bounds)
        grid_width, grid_height = dataset.width, dataset.height
    for name, src in (("ocean", "planet_oceanmask.vrt"), ("water", "planet_watermask.vrt")):
        out = work / f"{name}_3857.tif"
        if is_stale(out, PLANET / src, chunks):
            print(f"warp {name} -> 3857 ...", flush=True)
            out.unlink(missing_ok=True)
            _run(["gdalwarp", "-q", "-t_srs", "EPSG:3857", "-te", *bounds, "-ts", *size,
                  "-r", "near", "-ot", "Byte", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
                  "-co", "BIGTIFF=YES", PLANET / src, out])
            mark_done(out)

    # GLOBathy lake depth, warped ONCE here rather than per window: it is an 83k-source VRT,
    # and a many-source VRT re-reads every source on each touch (the same reason the tiler
    # materialises before cutting). Deliberately NOT in the loop above -- depth is continuous,
    # so it needs bilinear/Float32, while `near`/Byte is right for the class codes and would
    # quantise every lake to whole metres and hard-step its gradient.
    # Its dependency is the VRT alone, unlike the chunk directory above: extract_globathy
    # rebuilds the VRT whenever the raster set changes, so its mtime really does move.
    depth_out = work / "lakedepth_3857.tif"
    if not lake_depth.LAKE_VRT.exists():
        print(f"no {lake_depth.LAKE_VRT.name} -> lakes stay flat "
              f"(run pipeline.acquire.extract_globathy)", flush=True)
    elif is_stale(depth_out, lake_depth.LAKE_VRT):
        print("warp lake depth -> 3857 ...", flush=True)
        depth_out.unlink(missing_ok=True)
        _run(["gdalwarp", "-q", "-t_srs", "EPSG:3857", "-te", *bounds, "-ts", *size,
              "-srcnodata", str(lake_depth.GLOBATHY_NODATA), "-dstnodata", "0",
              "-r", "bilinear", "-ot", "Float32", "-co", "TILED=YES",
              "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=YES",
              "-co", "NUM_THREADS=ALL_CPUS", lake_depth.LAKE_VRT, depth_out])
        mark_done(depth_out)

    # Snow persistence + RGI glaciers, warped ONCE here rather than per window (optimisation #4).
    # The old composite loop forked gdalwarp + gdal_rasterize for every window (~728 subprocesses)
    # into two fixed-path temps -- the shared paths that blocked threading the composite. Same
    # precedent as lakedepth above. Persistence stores the RAW PACKED Float32 (snow.warp_persistence_
    # raster's docstring: the composite unpacks per window in float64, so a slice is bit-identical to
    # the old per-window warp). Glacier is a 0/1 Byte mask; absent RGI leaves it unbuilt and the snow
    # is persistence-only, exactly as before.
    persistence_out = work / "snow_persistence_3857.tif"
    if not snow.SP_NC.exists():
        print(f"no {snow.SP_NC.name} -> snow layer unavailable (composite would fail)", flush=True)
    elif is_stale(persistence_out, snow.SP_NC):
        print("warp snow persistence -> 3857 (banded) ...", flush=True)
        persistence_out.unlink(missing_ok=True)
        # band_rows == the composite window height, aligned to it: each band is exactly the
        # per-window warp it replaces, so the mosaic is byte-identical to the old per-window path.
        # A single whole-grid warp would DECIMATE this coarse source (snow.warp_persistence_raster).
        snow.warp_persistence_raster(grid_bounds, grid_width, grid_height, persistence_out,
                                     band_rows=WINDOW_ROWS)
        mark_done(persistence_out)

    glacier_out = work / "glacier_3857.tif"
    if not snow.RGI_GPKG.exists():
        print(f"no {snow.RGI_GPKG.name} -> glaciers skipped (persistence-only snow)", flush=True)
    elif is_stale(glacier_out, snow.RGI_GPKG):
        print("rasterize RGI glaciers -> 3857 ...", flush=True)
        snow.rasterize_glaciers_raster(grid_bounds, grid_width, grid_height, glacier_out)
        mark_done(glacier_out)
    return height


def build_hillshade(work: Path, height: Path):
    """The seamless per-row-z hillshade (skip if fresh).

    Was `color_and_hillshade`: the two `gdaldem color-relief` passes it also ran were deleted on
    2026-07-16 (28:19 and 24.4% of all pass CPU, single-threaded; profile said `libgdal` 19.37%
    interpolation vs `libdeflate` 4.33%, so no threading flag could reach it). composite() now
    applies the ramps from elevation via a 17.6 KB LUT -- verified against gdaldem's own output
    over all 12.19 G px, 6/6 bands, zero pixels beyond 1 DN.
    """
    hs = work / "hs_3857.tif"
    hs_params_path = write_if_changed(work / "hs_params.json", hs_params())
    if is_stale(hs, height, hs_params_path):
        fill_note = (f", fill {KNOBS['fill_strength']:.2f}" if KNOBS["fill_strength"] else "")
        print(f"per-row-z hillshade (EXAG={EXAG}{fill_note}) ...", flush=True)
        hillshade.per_row_zfactor_hillshade(height, hs, EXAG, ALT, AZ,
                                            fill_strength=KNOBS["fill_strength"])
        mark_done(hs)
    return hs


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


@dataclass
class _WindowInputs:
    """One window's RAW reads plus its geometry — everything a window needs from disk.

    Populated on the MAIN thread only: rasterio datasets are not thread-safe, so every GDAL
    read lives here and the pure-numpy compute (`_compute_shared`/`_compose`) takes this bundle.
    The fields are the untransformed slices (`ocean_raw`, not `ocean != 0`); the cheap numpy
    that derives masks/alpha from them runs on the worker, which is where optimisation #5 wants
    the CPU. `depth_raw`/`glacier_raw` are None when that optional input was never built.
    """

    win: Window
    win_h: int
    win_top: float
    win_bottom: float
    height_win: np.ndarray
    ocean_raw: np.ndarray
    watercode: np.ndarray
    hs_raw: np.ndarray
    depth_raw: np.ndarray | None
    persistence_raw: np.ndarray
    glacier_raw: np.ndarray | None
    occ_win: np.ndarray


@dataclass
class _WindowShared:
    """The per-window work that does NOT depend on the sea knobs, so a multi-variant pass
    computes it once and every variant's `_compose` reuses it. Snow alpha, the polar-cap mask
    and the three masks are all variant-independent; only `shade.composite`'s sea-light math
    (and thus the KNOBS it reads) differs between variants.
    """

    ocean_win: np.ndarray
    water_win: np.ndarray
    hs_win: np.ndarray
    depth_win: np.ndarray | None
    snow_a: np.ndarray
    cap: np.ndarray


def _compute_shared(inputs: _WindowInputs) -> _WindowShared:
    """Derive the variant-independent per-window arrays from the raw reads (pure numpy).

    This is exactly the old loop's pre-variant body, lifted out verbatim so the serial and
    threaded paths run identical arithmetic on identical inputs — byte-identity by construction.
    Runs on a worker thread in the threaded path; numpy releases the GIL, which is the whole
    basis of optimisation #5.
    """
    ocean_win = inputs.ocean_raw != 0
    watercode = inputs.watercode
    water_win = (watercode == 2) | (watercode == 3)
    hs_win = inputs.hs_raw.astype(float)
    # Lake depth, zeroed off class 2 so rivers stay flat and the (class 1) Caspian keeps GEBCO's
    # measured bathymetry instead of GLOBathy's cone.
    depth_win = (lake_depth.lakes_only(inputs.depth_raw, watercode)
                 if inputs.depth_raw is not None else None)
    # unpack_persistence runs the float64 unpack per window (as the old per-window path did), so
    # snow_alpha sees bit-identical input. Glacier is optional (persistence-only when RGI absent).
    persistence_win = snow.unpack_persistence(inputs.persistence_raw)
    snow_a = snow.snow_alpha(persistence_win, inputs.win_top, inputs.win_bottom)
    if inputs.glacier_raw is not None:
        snow_a = np.maximum(snow_a, inputs.glacier_raw.astype(float))
    latitude = snow.latitude_per_row(inputs.win_top, inputs.win_bottom, inputs.win_h)
    cap = (latitude > CAP_NORTH) | (latitude < CAP_SOUTH)
    return _WindowShared(ocean_win, water_win, hs_win, depth_win, snow_a, cap)


def _compose(inputs: _WindowInputs, shared: _WindowShared) -> np.ndarray:
    """Shade one window into RGB with the CURRENT KNOBS, then force the polar edges flat.

    Reads KNOBS through `shade.composite`; on the threaded path KNOBS is never mutated mid-pass
    (single variant), so this is a pure function of its two arguments there. On the serial
    multi-variant path the caller mutates KNOBS between variants, exactly as before.
    """
    rgb = shade.composite(inputs.height_win, shared.ocean_win, shared.water_win, shared.snow_a,
                          shared.hs_win, inputs.occ_win, inputs.occ_win.shape,
                          (inputs.win_h, inputs.height_win.shape[1]), depth=shared.depth_win)
    if shared.cap.any():  # force the smeared polar edges to a flat deep-sea disc
        for band in range(3):
            rgb[band][shared.cap] = CAP_RGB[band]
    return rgb


def _compute_window_rgb(inputs: _WindowInputs) -> tuple[Window, np.ndarray]:
    """One worker unit: shared work + single-variant compose. Returns (window, rgb) so the main
    thread can write it in order. Used only by the threaded single-variant path."""
    return inputs.win, _compose(inputs, _compute_shared(inputs))


def composite_planet(work: Path, hs, compute_occlusion: Callable[[], np.ndarray], variants=None,
                     window_rows=WINDOW_ROWS, max_windows=None, max_workers=1, row_start=0):
    """Composite the whole planet window-by-window into seamless RGB GeoTIFF(s).

    `variants` maps a name -> a dict of sea-knob overrides (sea_shade/sea_lift/sea_svf);
    each name is emitted as planet_rgb_<name>.tif in ONE shared pass — the expensive
    per-window work (reads, snow warp, glacier rasterize) is done once and only the cheap
    sea-light math + write differs per variant. `variants=None` keeps the production path:
    a single planet_rgb.tif shaded with the default KNOBS. `window_rows` is the RAM lever;
    `max_windows` (smoke test) stops after N windows, leaving a partially-filled raster.
    `row_start` begins the window loop below the top (for compositing one region, e.g. a
    256-vs-128 window-height A/B over a chosen latitude band); like `max_windows` it produces a
    partial raster, so it never marks the output done.

    `max_workers` > 1 threads the single-variant compute (optimisation #5): the main thread reads
    each window and writes the finished RGB back in window order, while up to `max_workers` workers
    run the pure-numpy `_compute_window_rgb` (numpy drops the GIL, so threads scale ~3x before DRAM
    bandwidth saturates -- measured 2026-07-16). A bounded in-flight deque caps peak RAM at
    `max_workers + INFLIGHT_BUFFER` windows. Multi-variant passes IGNORE it and stay serial: that
    loop mutates the global KNOBS between variants, which is not safe to run concurrently.

    `compute_occlusion` is a CALLABLE, not the array itself, and that IS the sky-view guard.
    Measured 2026-07-17 on the first instrumented tile cut: computing it costs 2:33
    single-threaded reading the whole 31 GB master -- and on a tiles-only re-run the composite
    is fresh, so the array was built and discarded, 41% of that pass. Every other stage is
    gated by `is_stale`, but SVF has no file of its own to stamp, so deferring it behind the
    same freshness check is the equivalent guard. Keep the call BELOW the early return.
    """
    if variants is None:
        variants = {None: None}
    outs = {name: work / f"planet_rgb{f'_{name}' if name else ''}.tif" for name in variants}
    params = write_if_changed(work / "composite_params.json", composite_params(variants, window_rows))
    deps = composite_deps(work, hs, params)
    # One shared params file is sound because every variant is composited in a single pass:
    # the guard rebuilds all of them or none.
    if max_windows is None and not any(is_stale(tif, *deps) for tif in outs.values()):
        print("planet_rgb fresh -> skip composite", flush=True)
        return outs
    print("global sky-view factor ...", flush=True)
    occ = compute_occlusion()
    with rasterio.open(work / "height_3857.tif") as h:
        width, height, transform = h.width, h.height, h.transform
    small_h, small_w = occ.shape
    # dict[str, Any]: GDAL creation options are a heterogeneous bag, and `**profile` otherwise
    # hands rasterio.open's bool-typed `sharing`/`thread_safe` an inferred `str | int`.
    profile: dict[str, Any] = dict(
        driver="GTiff", width=width, height=height, count=3, dtype="uint8",
        crs="EPSG:3857", transform=transform, tiled=True, blockxsize=512,
        blockysize=512, compress="deflate", photometric="RGB", BIGTIFF="YES",
        num_threads="ALL_CPUS")
    ocean_p, water_p = work / "ocean_3857.tif", work / "water_3857.tif"
    depth_p = work / "lakedepth_3857.tif"
    persistence_p = work / "snow_persistence_3857.tif"
    glacier_p = work / "glacier_3857.tif"

    def read_window(row0: int) -> _WindowInputs:
        """Gather one window's raw reads + geometry — MAIN thread only (GDAL is not thread-safe)."""
        row1 = min(height, row0 + window_rows)
        win = Window(0, row0, width,  # pyright: ignore[reportCallIssue] — rasterio untyped, attrs init invisible
                     row1 - row0)
        # sky-view occlusion slice for this window (smooth -> nearest rows are fine)
        sr0 = int(row0 / height * small_h)
        sr1 = max(sr0 + 1, int(round(row1 / height * small_h)))
        return _WindowInputs(
            win=win, win_h=row1 - row0,
            win_top=transform.f + row0 * transform.e,
            win_bottom=transform.f + row1 * transform.e,
            height_win=read1_window(work / "height_3857.tif", win),
            ocean_raw=read1_window(ocean_p, win),
            watercode=read1_window(water_p, win),
            hs_raw=read1_window(hs, win),
            depth_raw=read1_window(depth_p, win) if depth_p.exists() else None,
            persistence_raw=read1_window(persistence_p, win),
            glacier_raw=read1_window(glacier_p, win) if glacier_p.exists() else None,
            occ_win=occ[sr0:sr1])

    rows = list(range(row_start, height, window_rows))
    if max_windows is not None:  # smoke test: only the first N windows
        rows = rows[:max_windows]
    # Thread ONLY the production single-variant path (see the docstring): the A/B loop mutates the
    # shared KNOBS, so it stays serial. Both paths run the SAME `_compute_shared`/`_compose`, so a
    # single-variant threaded pass is byte-identical to the serial one by construction.
    threaded = max_workers > 1 and len(variants) == 1
    started = time.monotonic()
    writers = {name: rasterio.open(tif, "w", **profile) for name, tif in outs.items()}
    try:
        if threaded:
            writer = writers[next(iter(variants))]
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                inflight: deque[Any] = deque()  # futures, oldest first -> writes stay in order
                for index, row0 in enumerate(rows):
                    inflight.append(pool.submit(_compute_window_rgb, read_window(row0)))
                    if len(inflight) >= max_workers + INFLIGHT_BUFFER:
                        win, rgb = inflight.popleft().result()  # block on the oldest, then write
                        writer.write(rgb, window=win)
                        del rgb
                    if index % 20 == 0:
                        gc.collect()
                        print(f"  composited rows {row0}/{height}", flush=True)
                while inflight:  # drain the tail in order
                    win, rgb = inflight.popleft().result()
                    writer.write(rgb, window=win)
                    del rgb
        else:
            for index, row0 in enumerate(rows):
                inputs = read_window(row0)
                shared = _compute_shared(inputs)
                for name, knobs in variants.items():
                    if knobs:
                        # Variant keys are data, not literals, so they take the same untyped view
                        # of KNOBS that shade.py's --knob override does.
                        cast(dict[str, Any], KNOBS).update(knobs)  # only the sea knobs differ
                    rgb = _compose(inputs, shared)
                    writers[name].write(rgb, window=inputs.win)
                    del rgb
                # release the window's big arrays each iteration so RSS can't creep up over the
                # hundreds of windows (fragmentation growth OOM-killed the earlier float64 runs).
                del inputs, shared
                if index % 20 == 0:
                    gc.collect()
                    print(f"  composited rows {row0}/{height}", flush=True)
    finally:
        for writer in writers.values():
            writer.close()
    elapsed = time.monotonic() - started
    mode = f"threaded x{max_workers}" if threaded else "serial"
    print(f"composite: {len(rows)} windows in {elapsed:.1f}s "
          f"({len(rows) / max(elapsed, 1e-9):.2f} win/s, {mode})", flush=True)
    if max_windows is None and row_start == 0:  # a partial raster (smoke/region) is never done
        for tif in outs.values():
            mark_done(tif)
    for tif in outs.values():
        print(f"wrote {tif}", flush=True)
    return outs


def build_tiles(planet_tif: Path, out: Path):
    """Cut z0-8 512px tiles into a staging dir, then swap over the live tiles.

    THERE IS NO gdaladdo STEP, deliberately. `gdal raster tile` builds each low zoom from the tiles
    it just generated, never from the source's overviews -- proven 2026-07-16 by tiling one raster
    with and without them for byte-identical output at identical wall time. The overviews this
    function used to build cost ~3 min and ~4 GB appended to the master, for nothing. The
    2026-07-14 note that justified them credited a confounded fix: materialising the 194-source VRT
    to a GTiff was the real speed-up; the overviews rode along on the same commit untested.

    `--overview-resampling=cubic` pins what is otherwise an UNDOCUMENTED default -- identified by
    elimination (2026-07-16): unset, it silently inherits `--resampling`. This is byte-identical to
    today and is what built the verified 07-14 pyramid, so it is a pin, not a change. z0-7 carry
    most of the globe's zoomed-out surface; they should not ride on a default GDAL may alter.

    `--webviewer=none`: the default is `all`, which emits leaflet/openlayers/mapml/stac files into
    the pyramid. We serve our own MapLibre page, and they would ride into PMTiles.
    """
    staging = out / "tiles_new"
    print(f"cutting z0-8 512px tiles -> {staging} ...", flush=True)
    _run(["gdal", "raster", "tile", "--min-zoom=0", "--max-zoom=8", "--tile-size=512",
          "--resampling=cubic", "--overview-resampling=cubic", "--convention=xyz",
          "--skip-blank", "--webviewer=none", "--resume", str(planet_tif), str(staging)])
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
    hs = build_hillshade(work, height)
    # Passed unevaluated: composite_planet runs it only if the composite is actually stale.
    # Production composite is threaded at COMPOSITE_ROWS/N_WORKERS (optimisation #5); the snow
    # persistence stays banded at WINDOW_ROWS (256), sliced 128 rows at a time.
    planet_tif = composite_planet(work, hs, lambda: global_occlusion(height),
                                  window_rows=COMPOSITE_ROWS, max_workers=N_WORKERS)[None]
    if args.tiles:
        build_tiles(planet_tif, work)
    print("DONE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
