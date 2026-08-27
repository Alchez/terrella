"""Extract the GLOBathy rasters worth reading at z8 and build their mosaic VRT.

GLOBathy ships 1,427,688 per-lake 1" GeoTIFFs in one 16.73 GB zip. At 306 m/px most are a
single pixel or two, so the tile pipeline only wants the ones large enough to show a depth
gradient: the prototype's SIZE_FULL_PX=6 (deepest point >=6 px from shore) means >=12 px
across, i.e. ~3.7 km.

MIN_BYTES is a deliberately crude stand-in for that. Measured: file size tracks
lake AREA while the criterion is the NARROW dimension, so the two diverge (a 13,914 B raster
measured 7.1 px across; a 3,661 B one measured 13.1 px). Precision is not worth buying,
because both errors are harmless: an over-included lake renders near-flat, which is the
correct answer for it anyway, and an under-included one keeps today's flat WATER_RGB. What
the threshold actually buys is INODES, not disk -- >=5 KB keeps 171 k files for 16.07 GB
while >=30 KB keeps 28 k for 14.56 GB, because the big lakes carry nearly all the bytes. So
pick it generously and let the data decide the gradient.

The Caspian (Hylak_id 1) is extracted but kept OUT of the VRT: fusion reclassifies it to
watermask class 1 (ocean), so the lake path can never read it, and GEBCO's measured
bathymetry beats a modelled cone there. It alone is 2.26 GB -- 12% of the dataset -- and it
is the one lake we can check GLOBathy's cone against, so it is worth having on disk.

Idempotent: a raster already extracted is skipped; --vrt-only rebuilds the index alone.

Usage:
  python3 -m pipeline.acquire.extract_globathy            # extract + build the VRT
  python3 -m pipeline.acquire.extract_globathy --vrt-only
"""

import argparse
import re
import subprocess
import sys
import zipfile

from pipeline import datasets, paths

DATA = paths.DATA
RASTER_DIR = DATA / "work/globathy/rasters"
VRT_PATH = DATA / "work/globathy/lakedepth.vrt"

MIN_BYTES = 10_000     # ~84% of all GLOBathy pixels in ~6% of its files (see docstring)
CASPIAN_HYLAK_ID = 1   # handled by the ocean path via GEBCO -- never by the lake ramp
NAME_RE = re.compile(r"/(\d+)_bathymetry\.tif$")


def wanted(archive: zipfile.ZipFile) -> list[tuple[int, str]]:
    """(hylak_id, member) for every raster at or above MIN_BYTES."""
    picks = []
    for info in archive.infolist():
        match = NAME_RE.search(info.filename)
        if match and info.file_size >= MIN_BYTES:
            picks.append((int(match.group(1)), info.filename))
    return picks


def extract(archive: zipfile.ZipFile, picks: list[tuple[int, str]]) -> int:
    """Extract each pick to RASTER_DIR/<hylak_id>.tif via a .part + rename, so an
    interrupted run never leaves a truncated raster looking complete."""
    written = 0
    for index, (hylak_id, member) in enumerate(picks, 1):
        dest = RASTER_DIR / f"{hylak_id}.tif"
        if dest.exists():
            continue
        part = dest.with_suffix(".part")
        with archive.open(member) as src, open(part, "wb") as out:
            out.write(src.read())
        part.replace(dest)
        written += 1
        if index % 10_000 == 0:
            print(f"  {index:,}/{len(picks):,} ...", flush=True)
    return written


def build_vrt(picks: list[tuple[int, str]]) -> None:
    """Index every extracted raster EXCEPT the Caspian into one mosaic VRT."""
    sources = [str(RASTER_DIR / f"{hylak_id}.tif") for hylak_id, _ in picks
               if hylak_id != CASPIAN_HYLAK_ID]
    listing = VRT_PATH.parent / "vrt_sources.txt"
    listing.write_text("\n".join(sources) + "\n")
    print(f"gdalbuildvrt over {len(sources):,} rasters ...", flush=True)
    subprocess.run(["gdalbuildvrt", "-overwrite", "-input_file_list", str(listing),
                    str(VRT_PATH)], check=True)
    print(f"built {VRT_PATH}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--vrt-only", action="store_true",
                        help="rebuild the VRT over already-extracted rasters")
    args = parser.parse_args()

    RASTER_DIR.mkdir(parents=True, exist_ok=True)
    archive = zipfile.ZipFile(datasets.globathy_zip())
    picks = wanted(archive)
    total_gb = sum(info.file_size for info in archive.infolist()
                   if NAME_RE.search(info.filename) and info.file_size >= MIN_BYTES) / 1e9
    print(f"{len(picks):,} rasters >= {MIN_BYTES:,} B ({total_gb:.2f} GB) -> {RASTER_DIR}",
          flush=True)

    if not args.vrt_only:
        written = extract(archive, picks)
        print(f"extracted {written:,} new ({len(picks) - written:,} already present)",
              flush=True)
    build_vrt(picks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
