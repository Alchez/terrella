#!/usr/bin/env python3
"""Download OSI SAF sea-ice concentration and build a frequency-of-occurrence climatology.

The sea half of the polar look: a static, timeless "how often is this sea-water frozen"
field that drives a translucent white overlay over the bathymetry, exactly the way land
snow persistence (NSIDC-0791) drives snow over land. Sea ice is the SEA-side mirror of that
layer, so this climatology is packed identically (see PACK_SCALE / PACK_FILL below, which
match snow.SP_SCALE / snow.SP_FILL) and consumed the same way by pipeline/render/seaice.py.

Source: OSI SAF Global Sea Ice Concentration climate data record OSI-450-a, v3 (product_id
osi-450-a, product_version 3.0), monthly-mean fields. Passive microwave (SMMR/SSM/I/SSMIS),
25 km, BOTH hemispheres, distributed as one NetCDF per hemisphere per month on the met.no
THREDDS server over anonymous HTTP -- no NASA Earthdata login and no ~60-day token churn
(the reason this was chosen over the equivalent NSIDC CDR; see PLAN 2b). License: EUMETSAT,
free of charge, "Copyright EUMETSAT".

Each file is on an EASE-Grid 2.0 azimuthal grid (EPSG:6931 north / 6932 south), variable
`ice_conc` in percent (scale_factor 0.01, _FillValue -32767). We reduce the record to one
number per pixel: FREQUENCY OF OCCURRENCE = fraction of monthly samples whose concentration
reaches the 15% ice-edge threshold, over the 1991-2020 WMO 30-year normal (a period wholly
inside OSI-450-a, so no splice with the 430-a interim record). Perennial pack ice -> 1.0,
the seasonal fringe fades toward 0 -- the true analog of snow persistence, and the reason a
graded concentration record beats a binary median-edge line for our soft look.

Output (data/raw/seaice/):
  monthly/ice_conc_{nh,sh}_ease2-250_cdr-v3p0_YYYYMM.nc   raw source files (720 of them)
  freq_{nh,sh}_ease2.tif                                  per-hemisphere frequency, native EASE2
  seaice_frequency_1991-2020_4326.tif                     the SOURCE render layer reads:
      global EPSG:4326, packed UInt16 (0..10000 = 0..1 frequency, PACK_FILL where undefined)

Idempotency: each monthly file streams to a .part name, is size-checked, then atomically
renamed (download_glo30.download_one), so a file under its final name is always complete and
re-runs skip it. The reduction rebuilds only if its output is missing (or --force). Edition
oracle: the versioned THREDDS path (conc_450a_files) + the cdr-v3p0 filename self-pin the
release -- a renamed/withdrawn file 404s and aborts the run -- and assert_edition() reads the
first file's global attributes to refuse a silently re-versioned record.

Usage:
  python3 -m pipeline.acquire.download_seaice                 # download 720 files + build
  python3 -m pipeline.acquire.download_seaice --download-only # fetch the monthly files only
  python3 -m pipeline.acquire.download_seaice --build-only    # rebuild the climatology on disk
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.fill import fillnodata
from scipy.ndimage import gaussian_filter

from pipeline.acquire.download_glo30 import download_one

DATA_DIR = Path.home() / "projects/maps/data/raw/seaice"
MONTHLY_DIR = DATA_DIR / "monthly"
THREDDS = ("https://thredds.met.no/thredds/fileServer/osisaf/met.no/reprocessed"
           "/ice/conc_450a_files/monthly")

# 1991-2020: the current WMO 30-year normal, wholly inside OSI-450-a (1978-2020), so no splice
# with the OSI-430-a interim record.
YEARS = range(1991, 2021)
MONTHS = range(1, 13)
HEMISPHERES = ("nh", "sh")  # separate files; EPSG:6931 (north) / 6932 (south)

ICE_THRESHOLD_PACKED = 1500   # 15% in the file's units (percent x 100); the standard ice edge
CONC_FILL = -32767            # ice_conc _FillValue (land / no observation)
SMOOTH_SIGMA_PX = 2.0         # Gaussian sigma in native EASE2 pixels (~25 km each) -- feathers the
                              # coarse passive-microwave ice edge into the soft look. Snow needs no
                              # such blur: its ~1 km source is already smooth. Tunable.

# The frequency climatology is packed exactly like snow persistence so seaice.py's unpack is a
# copy of snow.unpack_persistence: packed 0..10000 = frequency 0..1, PACK_FILL where undefined.
# MUST stay equal to snow.SP_SCALE / snow.SP_FILL.
PACK_SCALE = 1e-4
PACK_FILL = 65535

FREQ_NODATA = -9999.0         # float sentinel carried through the EASE2 -> 4326 warp
OUTPUT_RES_DEG = 0.1          # 4326 grid step (~11 km) -- finer than the 25 km source, tiny on disk
FINAL = DATA_DIR / "seaice_frequency_1991-2020_4326.tif"


def _run(cmd):
    subprocess.run([str(part) for part in cmd], check=True, capture_output=True)


def file_name(hemisphere: str, year: int, month: int) -> str:
    """The monthly-mean file name for one hemisphere/year/month."""
    return f"ice_conc_{hemisphere}_ease2-250_cdr-v3p0_{year}{month:02d}.nc"


def file_url(hemisphere: str, year: int, month: int) -> str:
    """Anonymous THREDDS fileServer URL for one monthly file (per-year subfolders)."""
    return f"{THREDDS}/{year}/{file_name(hemisphere, year, month)}"


def all_files() -> list[tuple[str, Path]]:
    """(url, local destination) for every hemisphere/year/month in the normal period."""
    return [(file_url(hemisphere, year, month),
             MONTHLY_DIR / file_name(hemisphere, year, month))
            for hemisphere in HEMISPHERES
            for year in YEARS
            for month in MONTHS]


def assert_edition(nc_path: Path) -> None:
    """Refuse to proceed if this file is not OSI-450-a v3 -- the record was re-versioned.

    The versioned URL already pins the release (a moved file 404s); this is the second guard,
    reading the record's own identity so a same-named but re-baselined file cannot slip through.
    """
    with rasterio.open(f'NETCDF:"{nc_path}":ice_conc') as src:
        tags = src.tags()
    product = tags.get("NC_GLOBAL#product_id")
    version = tags.get("NC_GLOBAL#product_version")
    if product != "osi-450-a" or version != "3.0":
        sys.exit(f"edition drift: {nc_path.name} reports product_id={product!r} "
                 f"version={version!r}, expected 'osi-450-a' / '3.0' -- stop and check")


def download_all() -> int:
    """Fetch every monthly file SERIALLY (OSI SAF forbids parallel downloads). Resumable."""
    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)
    jobs = all_files()
    counts = {"ok": 0, "skipped": 0}
    failures: list[str] = []
    checked_edition = False
    for index, (url, dest) in enumerate(jobs, 1):
        status = download_one(url, dest)
        if status.startswith("failed"):
            failures.append(f"{url}  {status}")
        else:
            counts[status] += 1
            if not checked_edition and dest.exists():
                assert_edition(dest)  # first real file: verify the release identity once
                checked_edition = True
        if index % 60 == 0 or index == len(jobs):
            print(f"[{index}/{len(jobs)}] ok={counts['ok']} "
                  f"skipped={counts['skipped']} failed={len(failures)}", flush=True)

    if failures:
        log = DATA_DIR / "failures.txt"
        log.write_text("\n".join(failures) + "\n")
        print(f"{len(failures)} failures written to {log} -- rerun to retry", flush=True)
        return 1
    return 0


def hemisphere_frequency(hemisphere: str) -> Path:
    """Reduce one hemisphere's 360 monthly files to a native-EASE2 frequency-of-occurrence tif.

    frequency = (# months with ice_conc >= 15%) / (# months with a valid observation). Land and
    no-observation pixels (the _FillValue) are excluded from BOTH counts, so a pixel that is never
    validly observed stays undefined (FREQ_NODATA) rather than reading as permanent open water.
    Ocean pixels are observed every month, so their denominator is the full record.
    """
    paths = [MONTHLY_DIR / file_name(hemisphere, year, month)
             for year in YEARS for month in MONTHS
             if (MONTHLY_DIR / file_name(hemisphere, year, month)).exists()]
    if not paths:
        sys.exit(f"no {hemisphere} monthly files on disk -- run the download first")

    with rasterio.open(f'NETCDF:"{paths[0]}":ice_conc') as first:
        shape, transform, crs = first.shape, first.transform, first.crs
    ice_count = np.zeros(shape, dtype=np.int32)
    valid_count = np.zeros(shape, dtype=np.int32)
    for path in paths:
        with rasterio.open(f'NETCDF:"{path}":ice_conc') as src:
            band = src.read(1)
        valid = band != CONC_FILL
        valid_count += valid
        ice_count += valid & (band >= ICE_THRESHOLD_PACKED)
    print(f"  {hemisphere}: reduced {len(paths)} monthly files", flush=True)

    valid_mask = valid_count > 0
    freq_raw = np.where(valid_mask, ice_count / np.maximum(valid_count, 1), 0.0).astype(np.float32)
    # Fill land / no-observation cells with the NEAREST valid ocean frequency, THEN smooth (both in
    # the native equal-area EASE2 grid, so the sigma is a fixed distance everywhere). Why the fill:
    # OSI SAF's land mask is coarse (25 km), so coastal ocean pixels our fine ocean_3857 mask keeps
    # often sit in a cell OSI calls land (frequency 0) -- without this they render as blocky bare-sea
    # patches inside the pack (the open-water edge itself is already smooth). The nearest-fill lets the
    # adjacent real ice reach the coast, and lets a plain Gaussian feather the edge without a masked
    # normalization. Extending frequency over land is harmless: shade.composite gates ice on `ocean`,
    # so a land pixel never reads the value.
    # fillnodata spreads the nearest valid ocean frequency into the land/no-obs cells (GDAL IDW,
    # mask=0 is filled), so a coarse-land coastal cell inherits the adjacent real ice.
    filled = fillnodata(freq_raw, mask=valid_mask.astype("uint8"))
    frequency = gaussian_filter(filled, SMOOTH_SIGMA_PX).astype(np.float32)
    out_path = DATA_DIR / f"freq_{hemisphere}_ease2.tif"
    profile: dict[str, Any] = dict(driver="GTiff", width=shape[1], height=shape[0],
                                   count=1, dtype="float32", crs=crs, transform=transform,
                                   nodata=FREQ_NODATA, tiled=True, compress="deflate")
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(frequency, 1)
    return out_path


def build_climatology() -> None:
    """Both hemispheres -> a global EPSG:4326 packed-UInt16 frequency raster (the render source)."""
    hemisphere_tifs = [hemisphere_frequency(hemisphere) for hemisphere in HEMISPHERES]

    merged_4326 = DATA_DIR / "freq_1991-2020_4326_f32.tif"
    _run(["gdalwarp", "-overwrite", "-q", "-t_srs", "EPSG:4326",
          "-te", "-180", "-90", "180", "90",
          "-tr", str(OUTPUT_RES_DEG), str(OUTPUT_RES_DEG), "-r", "bilinear",
          "-srcnodata", str(FREQ_NODATA), "-dstnodata", str(FREQ_NODATA),
          "-ot", "Float32", *map(str, hemisphere_tifs), str(merged_4326)])

    with rasterio.open(merged_4326) as src:
        frequency = src.read(1)
        transform, crs = src.transform, src.crs
    defined = np.isfinite(frequency) & (frequency != FREQ_NODATA)
    packed = np.where(defined,
                      np.clip(np.rint(frequency / PACK_SCALE), 0, 10000),
                      PACK_FILL).astype(np.uint16)
    profile: dict[str, Any] = dict(driver="GTiff", width=packed.shape[1],
                                   height=packed.shape[0], count=1, dtype="uint16",
                                   crs=crs, transform=transform, nodata=PACK_FILL,
                                   tiled=True, compress="deflate")
    with rasterio.open(FINAL, "w", **profile) as dst:
        dst.write(packed, 1)
    merged_4326.unlink(missing_ok=True)
    print(f"built {FINAL} ({packed.shape[1]}x{packed.shape[0]}, packed UInt16)", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--download-only", action="store_true",
                      help="fetch the 720 monthly files, skip the reduction")
    mode.add_argument("--build-only", action="store_true",
                      help="rebuild the climatology from files already on disk")
    parser.add_argument("--force", action="store_true",
                        help="rebuild the climatology even if the output exists")
    args = parser.parse_args()

    if not args.build_only:
        if download_all() != 0:
            return 1
    if not args.download_only:
        if FINAL.exists() and not args.force:
            print(f"{FINAL} exists -- pass --force to rebuild", flush=True)
        else:
            build_climatology()
    print(f"complete -> {DATA_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
