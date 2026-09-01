"""Fuse GLO-30 land elevation with GEBCO bathymetry into one heightfield.

Recipe:
  ocean  = WBM class 1, or outside GLO-30 tile coverage (open-ocean cells),
           or WBM lake/river (2/3) within 1 m of sea level - ESA classifies
           coastal lagoons and tidal channels as lake/river; at sea level
           they are visually sea (Chilika, backwaters, Sundarbans),
           or the Caspian Sea (see is_caspian)
  sea    = GEBCO upsampled with cubic spline, clamped to <= -1 m
  land   = GLO-30 resampled with area average
Outputs, on the same grid, tiled with overviews:
  heightfield_{tag}.tif  Float32 fused elevation
  oceanmask_{tag}.tif    Byte 0/1 — drives the land/sea material split
  watermask_{tag}.tif    Byte 4-class: 0 land, 1 ocean, 2 inland lake,
                         3 inland river (WBM water the ocean rule did not
                         absorb; class 1 is pixel-identical to the ocean mask)
Runs windowed, so memory stays flat regardless of extent.

Stage-level idempotency: refuses to overwrite an existing output; delete the
files (or choose another --outdir) to redo. --watermask-only backfills just
the water mask next to existing outputs without recomputing anything else.

Usage:
  fuse_heightfield.py --bounds W S E N --res-arcsec 3 --outdir data/work/india
  fuse_heightfield.py --res-arcsec 3 --outdir data/work/india --watermask-only
"""

import argparse
import contextlib
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window

from pipeline import datasets, paths

# over the 8 GeoTIFF tiles of GEBCO_2026 (build with gdalbuildvrt); overridable
# per run with --gebco (e.g. the old regional tile for a byte-for-byte regression)

DEM_NODATA = -9999  # VRT fill where no GLO-30 tile exists
WBM_NODATA = 255
BLOCK = 8192  # processing window size in pixels

# The Caspian: the one inland water body we route through GEBCO + the sea ramp.
# WBM calls it a lake (class 2) and its surface sits at -28 m, so the coastal_water
# rule (|land| <= 1) can't reach it and the heightfield would take GLO-30's FLAT lake
# surface -- discarding real measured bathymetry GEBCO already holds (-464 m mid-basin,
# -1026 m deepest; probed). It is uniquely safe to treat as ocean because it
# lies below sea level THROUGHOUT, so its absolute elevations map onto the existing sea
# ramp with no new ramp and no per-lake datum -- unlike Baikal (+456 m) or the Great
# Lakes (+183 m), whose margins would hit the land ramp.
#
# The bbox is load-bearing, not laziness: it is what stops the rule reaching the Dead
# Sea (-430 m surface, also a WBM lake), which has NO GEBCO bathymetry and would collapse
# to min(gebco, -1) = -1 -- a flat bright slab, i.e. a regression. The surface test then
# excludes the Mingevir Reservoir (+83 m), the only other lake inside the box.
CASPIAN_BBOX = (46.5, 36.5, 55.5, 47.5)  # west, south, east, north (EPSG:4326)
CASPIAN_MAX_SURFACE_M = -5.0  # its surface is a uniform -28 m; +83 m Mingevir is not


def dem_vrt() -> Path:
    """The GLO-30 land-elevation mosaic. `build_mosaics.sh` writes it and spells this path too."""
    return paths.DATA / "work/dem_mosaic.vrt"


def wbm_vrt() -> Path:
    """The GLO-30 water-body-mask mosaic, written beside the DEM's by the same script.

    Consumed as a PAIR with `dem_vrt()`: a fresh DEM against a stale mask fuses new land as ocean,
    so the script rebuilds both when either is stale.
    """
    return paths.DATA / "work/wbm_mosaic.vrt"


def make_grid(bounds, res_arcsec, lat_res_arcsec=None) -> tuple[Affine, int, int]:
    """The output grid, square by default and finer in LATITUDE ALONE when asked.

    WHY ONLY ONE AXIS CAN BE REFINED HERE. The high-latitude coastline staircase is a latitude
    artefact: a source row is a fixed ground distance at every latitude, while a Web-Mercator pixel
    spans `305.748 * cos(lat)` in BOTH axes, so a source COLUMN and an output pixel shrink together
    and the longitude ratio is 1.011 everywhere. Only rows are replicated. Refining longitude would
    upsample 3 arcsec of native GLO-30 to 1 at 79.5N and invent data, for 100x the pixels instead of
    10x; refining latitude is at the source's own resolution, which is 1 arcsec in every GLO-30 band.

    THE RATIO MUST BE A WHOLE NUMBER, and that is a correctness bound rather than tidiness:
    `planet_seam._require_nested_grids` refuses a mask whose pixel edges fall between the
    heightfield's, because the misregistration it causes is sub-pixel, systematic, and invisible in
    any image. Refusing it here is refusing it where the grid is chosen.
    """
    west, south, east, north = bounds
    res = res_arcsec / 3600.0
    width = round((east - west) / res)
    if lat_res_arcsec is None:
        return from_origin(west, north, res, res), width, round((north - south) / res)
    ratio = res_arcsec / lat_res_arcsec
    if ratio < 1 or abs(ratio - round(ratio)) > 1e-9:
        raise ValueError(
            f"a latitude resolution of {lat_res_arcsec}\" against {res_arcsec}\" of longitude is a "
            f"ratio of {ratio:g} rather than a whole number, so the rows would not nest inside the "
            f"square grid's and every consumer would read the mask a fraction of a pixel off the "
            f"terrain it classifies")
    lat_res = lat_res_arcsec / 3600.0
    return (from_origin(west, north, res, lat_res), width,
            round((north - south) / lat_res))


def grid_tag(res_arcsec, lat_res_arcsec=None):
    """The filename tag for a grid: `10s` square, `1x10s` for 1" latitude by 10" longitude.

    ONE OWNER BECAUSE TWO MODULES SPELL IT. This writes `oceanmask_<tag>.tif` and `fuse_planet`
    GLOBS for it to index the VRTs, so a second copy of this format is a set of chunks nothing can
    find — an empty VRT rather than an error.

    A LATITUDE EQUAL TO THE LONGITUDE IS THE SQUARE TAG, deliberately: `--lat-res-arcsec 10` beside
    `--res-arcsec 10` describes the grid that is already on disk, and giving it a second name would
    fuse the planet again into files no consumer reads.
    """
    lon = f"{res_arcsec:g}".replace(".", "p")
    if lat_res_arcsec is None or lat_res_arcsec == res_arcsec:
        return f"{lon}s"
    return f"{f'{lat_res_arcsec:g}'.replace('.', 'p')}x{lon}s"


def is_caspian(transform, win, wbm, land):
    """Caspian pixels in this window: WBM lake, below-sea-level surface, inside the bbox.

    Intersecting with WBM class 2 means the DEM's own shoreline defines the edge, so
    GEBCO's coarse 15" coast never does (and `min(gebco, -1)` keeps shallow margins
    continuous rather than cutting a ring). Returns a plain False for windows that miss
    the bbox entirely -- the planet is 648 cells and only four touch the Caspian, so
    this must not allocate a BLOCK-sized array 644 times for nothing."""
    west, south, east, north = CASPIAN_BBOX
    lons = transform.c + (win.col_off + np.arange(win.width) + 0.5) * transform.a
    lats = transform.f - (win.row_off + np.arange(win.height) + 0.5) * -transform.e
    in_lon = (lons >= west) & (lons <= east)
    in_lat = (lats >= south) & (lats <= north)
    if not in_lon.any() or not in_lat.any():
        return False
    return (wbm == 2) & (land < CASPIAN_MAX_SURFACE_M) & (in_lat[:, None] & in_lon[None, :])


def classify_water(ocean, wbm):
    """4-class water mask: 0 land, 1 ocean, 2 inland lake, 3 inland river.

    Inland = WBM lake/river that the ocean rule did not absorb, so class 1
    stays pixel-identical to the ocean mask by construction."""
    out = np.zeros(wbm.shape, dtype="uint8")
    out[ocean] = 1
    out[(wbm == 2) & ~ocean] = 2
    out[(wbm == 3) & ~ocean] = 3
    return out


def print_class_counts(counts):
    total = counts.sum()
    for code, name in enumerate(("land", "ocean", "lake", "river")):
        print(f"  {code} {name:6s}: {counts[code]:>13,} px "
              f"{100.0 * counts[code] / total:6.2f}%", flush=True)


def backfill_watermask(mask_path, out_water):
    """Write the water mask next to a finished fusion, reusing its ocean mask.

    Rereads only the WBM; taking the ocean classification from the stored
    mask (rather than re-deriving it from DEM + WBM) means the two masks
    cannot drift."""
    with rasterio.open(mask_path) as ms:
        profile = ms.profile
        vrt_kw = dict(crs=ms.crs, transform=ms.transform,
                      width=ms.width, height=ms.height)
        height, width = ms.height, ms.width
    profile.update(bigtiff="if_safer")

    counts = np.zeros(4, dtype=np.int64)
    with rasterio.open(mask_path) as ms, \
         rasterio.open(wbm_vrt()) as wbm_src, \
         WarpedVRT(wbm_src, resampling=Resampling.nearest, **vrt_kw) as wbm, \
         rasterio.open(out_water, "w", **profile) as fw:
        nwin = ((height + BLOCK - 1) // BLOCK) * ((width + BLOCK - 1) // BLOCK)
        done = 0
        for row in range(0, height, BLOCK):
            for col in range(0, width, BLOCK):
                win = Window(col, row,  # pyright: ignore[reportCallIssue] — rasterio untyped, attrs init invisible
                             min(BLOCK, width - col), min(BLOCK, height - row))
                wm = classify_water(ms.read(1, window=win) == 1,
                                    wbm.read(1, window=win))
                fw.write(wm, 1, window=win)
                counts += np.bincount(wm.ravel(), minlength=4)
                done += 1
                print(f"[{done}/{nwin}] windows", flush=True)
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bounds", nargs=4, type=float,
                    metavar=("W", "S", "E", "N"))
    ap.add_argument("--res-arcsec", type=float, required=True)
    ap.add_argument("--land-resampling", default="average",
                    choices=["average", "max", "bilinear", "cubic"],
                    help="DEM->grid resampling; 'max' preserves thin high land "
                         "(atolls) that 'average' washes to sea level")
    ap.add_argument("--outdir", type=Path, required=True)
    ap.add_argument("--gebco", type=Path, default=datasets.gebco_vrt(),
                    help="bathymetry source (default: the global GEBCO_2026 mosaic)")
    ap.add_argument("--dem-vrt", type=Path, default=dem_vrt(),
                    help="land-elevation mosaic (default: the GLO-30 mosaic); override "
                         "to splice a fallback DEM under GLO-30 over source voids")
    ap.add_argument("--wbm-vrt", type=Path, default=wbm_vrt(),
                    help="water-body mask mosaic (default: the GLO-30 WBM mosaic); "
                         "override alongside --dem-vrt so void-fill land is classified")
    ap.add_argument("--lat-res-arcsec", type=float,
                    help="finer LATITUDE resolution, leaving longitude at --res-arcsec. The "
                         "high-latitude coastline staircase is a latitude artefact (a source "
                         "column and a Mercator pixel both shrink by cos(lat), so only rows "
                         "replicate), and GLO-30 is 1 arcsec in latitude at every band — so this "
                         "is native resolution, not interpolation. Must divide --res-arcsec.")
    ap.add_argument("--masks-only", action="store_true",
                    help="write the ocean and water masks and no heightfield. GEBCO is never "
                         "opened: it feeds only the fused elevation, while the land/sea rule needs "
                         "DEM and WBM alone. Pairs with --lat-res-arcsec to refine the coastline "
                         "without paying for a finer elevation master nobody asked for.")
    ap.add_argument("--watermask-only", action="store_true",
                    help="backfill the water mask from an existing fusion")
    ap.add_argument("--coverage-warn", action="store_true",
                    help="downgrade the >1%% coverage-gap abort to a warning. For the "
                         "planet sweep, where fuse_planet's tileList preflight already "
                         "proved every land tile is on disk, so an in-window gap means a "
                         "corrupt (not missing) tile — worth flagging, not worth aborting "
                         "the cell mid-sweep. The country path leaves this off (fail loud).")
    args = ap.parse_args()

    tag = grid_tag(args.res_arcsec, args.lat_res_arcsec)
    out_height = args.outdir / f"heightfield_{tag}.tif"
    out_mask = args.outdir / f"oceanmask_{tag}.tif"
    out_water = args.outdir / f"watermask_{tag}.tif"

    if args.watermask_only:
        if out_water.exists():
            sys.exit(f"{out_water} already exists — delete to redo")
        if not out_mask.exists():
            sys.exit(f"{out_mask} not found — run the full fusion first")
        counts = backfill_watermask(out_mask, out_water)
        print_class_counts(counts)
        with rasterio.open(out_water, "r+") as ds:
            ds.build_overviews([2, 4, 8, 16, 32], Resampling.nearest)
        print("complete", flush=True)
        return

    if args.bounds is None:
        ap.error("--bounds is required for a full fusion run")
    # The skip predicate is what this run PRODUCES, not the full set: a masks-only run beside an
    # existing square fusion emits no heightfield, so demanding one would make it re-run forever.
    produced = [out_mask, out_water] if args.masks_only else [out_height, out_mask, out_water]
    if all(path.exists() for path in produced):
        print(f"fusion outputs exist in {args.outdir} — skipping", flush=True)
        return
    args.outdir.mkdir(parents=True, exist_ok=True)
    # Crash-safety: write to .tmp siblings and os.replace only on full success,
    # so an abrupt kill (OOM / blackout) leaves ignorable .tmp files, never a
    # partial final that resume would trust (same discipline as download_*.part).
    tmp_height = out_height.with_name(out_height.name + ".tmp")
    tmp_mask = out_mask.with_name(out_mask.name + ".tmp")
    tmp_water = out_water.with_name(out_water.name + ".tmp")

    transform, width, height = make_grid(args.bounds, args.res_arcsec, args.lat_res_arcsec)
    print(f"target grid: {width} x {height} @ {args.res_arcsec}\" lon x "
          f"{args.lat_res_arcsec or args.res_arcsec:g}\" lat"
          f"{' (masks only)' if args.masks_only else ''}", flush=True)

    profile: dict[str, Any] = dict(
        driver="GTiff", crs="EPSG:4326", transform=transform,
        width=width, height=height, count=1,
        tiled=True, blockxsize=512, blockysize=512, compress="deflate",
        bigtiff="if_safer",
    )
    vrt_kw = dict(crs="EPSG:4326", transform=transform,
                  width=width, height=height)

    # AN ExitStack RATHER THAN A `with` CHAIN, because two of these are conditional: `--masks-only`
    # opens neither GEBCO nor the heightfield writer. GEBCO is skippable at all only because it
    # feeds `fused` and nothing else — the land/sea rule below reads DEM and WBM alone — and it is
    # the expensive one, a cubic-spline warp of a global mosaic.
    with contextlib.ExitStack() as stack:
        dem_src = stack.enter_context(rasterio.open(args.dem_vrt))
        wbm_src = stack.enter_context(rasterio.open(args.wbm_vrt))
        dem = stack.enter_context(WarpedVRT(
            dem_src, resampling=getattr(Resampling, args.land_resampling), **vrt_kw))
        wbm = stack.enter_context(WarpedVRT(wbm_src, resampling=Resampling.nearest, **vrt_kw))
        geb = fh = None
        if not args.masks_only:
            geb_src = stack.enter_context(rasterio.open(args.gebco))
            geb = stack.enter_context(WarpedVRT(
                geb_src, resampling=Resampling.cubic_spline, **vrt_kw))
            fh = stack.enter_context(rasterio.open(tmp_height, "w", dtype="float32",
                                                   predictor=3, **profile))
        fm = stack.enter_context(rasterio.open(tmp_mask, "w", dtype="uint8", **profile))
        fw = stack.enter_context(rasterio.open(tmp_water, "w", dtype="uint8", **profile))

        nwin = ((height + BLOCK - 1) // BLOCK) * ((width + BLOCK - 1) // BLOCK)
        done = 0
        counts = np.zeros(4, dtype=np.int64)
        gap_px = land_px = 0
        for row in range(0, height, BLOCK):
            for col in range(0, width, BLOCK):
                win = Window(col, row,  # pyright: ignore[reportCallIssue] — rasterio untyped, attrs init invisible
                             min(BLOCK, width - col), min(BLOCK, height - row))
                dem_win = dem.read(1, window=win)
                wbm_win = wbm.read(1, window=win)

                land = np.where(dem_win == DEM_NODATA, 0, dem_win)
                coastal_water = ((wbm_win == 2) | (wbm_win == 3)) & (np.abs(land) <= 1.0)
                caspian = is_caspian(transform, win, wbm_win, land)
                ocean = (wbm_win == 1) | (wbm_win == WBM_NODATA) | coastal_water | caspian
                gap_px += int(((dem_win == DEM_NODATA) & (wbm_win == 0)).sum())  # WBM-land, no DEM tile
                land_px += int((wbm_win == 0).sum())
                if fh is not None and geb is not None:
                    fused = np.where(ocean, np.minimum(geb.read(1, window=win), -1.0), land)
                    fh.write(fused.astype("float32"), 1, window=win)
                fm.write(ocean.astype("uint8"), 1, window=win)
                wm = classify_water(ocean, wbm_win)
                fw.write(wm, 1, window=win)
                counts += np.bincount(wm.ravel(), minlength=4)
                done += 1
                print(f"[{done}/{nwin}] windows", flush=True)

    print_class_counts(counts)
    gap_frac = gap_px / max(land_px, 1)
    if gap_frac > 0.01:
        message = (f"COVERAGE GAP: {gap_frac:.1%} of land pixels ({gap_px:,}) have no "
                   f"GLO-30 tile — a DEM tile is missing/corrupt in this frame and would "
                   f"render as a flat nodata block (the Georgia bug). Re-download the "
                   f"frame's tiles and re-fuse.")
        if not args.coverage_warn:
            sys.exit(message)
        print(f"WARNING: {message}", flush=True)
    if gap_px:
        print(f"coverage: {gap_frac:.3%} land gap ({gap_px:,} px) — below fail "
              f"threshold, flat-filled", flush=True)
    # class codes must not be averaged — a 2 next to a 0 is not a 1
    written = [(tmp_mask, out_mask, Resampling.average),
               (tmp_water, out_water, Resampling.nearest)]
    if not args.masks_only:
        written.insert(0, (tmp_height, out_height, Resampling.average))
    for path, _final, rs in written:
        with rasterio.open(path, "r+") as ds:
            ds.build_overviews([2, 4, 8, 16, 32], rs)
    for tmp, final, _rs in written:
        os.replace(tmp, final)
    print("complete", flush=True)


if __name__ == "__main__":
    main()
