"""Fetch the GLO-30 DEM tiles that OpenTopography holds but AWS GLO-30 Public withholds.

The AWS "GLO-30 Public" bucket (download_glo30.py's source) omits ~two dozen tiles over
the South Caucasus under export restrictions — DEM *and* water mask both absent, so
fuse_heightfield mis-reads the whole area as ocean (min -1.0 m in landlocked Armenia).
ESA released those tiles in DGED 2023_1, which OpenTopography serves keyless over plain
HTTPS. This fetches exactly the withheld set — OpenTopography's tile index minus AWS's —
as 2023_1 DEM into a SEPARATE dir, so the 2021 edition everywhere else stays untouched and
edition-traceable. The two sets are spatially disjoint (2021 everywhere, 2023_1 only in the
holes), so the rebuilt mosaic has no overlapping sources. build_mosaics.sh globs this dir
alongside the AWS dir.

The water mask for these tiles is NOT here (OpenTopography serves DEM only) — it comes from
build_void_wbm.py, which synthesises a WBM from ESA WorldCover over the same extent.

Idempotent/resumable: reuses fetch.download_one (streams to .part, size-checks
against Content-Length, atomic rename); held files are skipped, failures retried next run.
Delete data/raw/cop30_void/COP30_hh.vrt to re-check the index against a newer OT edition.

Usage: python3 download_cop30_void.py
"""

import concurrent.futures as cf
import re
import sys
from pathlib import Path

from pipeline import paths
from pipeline.acquire.download_glo30 import (
    TILE_LIST,
    WORKERS,
    fetch_tile_list,
)
from pipeline.fetch import download_one

OT_ENDPOINT = "https://opentopography.s3.sdsc.edu"
OT_PREFIX = "raster/COP30/COP30_hh"          # keyless public COG mirror, DGED 2023_1
DATA_DIR = paths.DATA / "raw/cop30_void"
KEY_RE = re.compile(r"[NS]\d\d_00_[EW]\d\d\d_00")  # the N40_00_E044_00 tile key


def ot_index(vrt_path: Path) -> dict[str, str]:
    """{tile key: OT DEM filename} for every tile in OpenTopography's COP30 index."""
    # Two groups: the full DEM stem and the tile key it contains, so the key
    # falls out of the match directly (no separate, possibly-None re-search).
    matches = set(re.findall(r"(Copernicus_DSM_10_([NS]\d\d_00_[EW]\d\d\d_00)_DEM)",
                             vrt_path.read_text()))
    return {key: stem + ".tif" for stem, key in matches}


def main() -> int:
    dem_dir = DATA_DIR / "dem"
    dem_dir.mkdir(parents=True, exist_ok=True)

    # The withheld set is exactly what OT's index has and AWS's tileList lacks.
    if not TILE_LIST.exists():
        fetch_tile_list()
    aws_keys = set(KEY_RE.findall(TILE_LIST.read_text()))

    vrt = DATA_DIR / "COP30_hh.vrt"
    if not vrt.exists():
        status = download_one(f"{OT_ENDPOINT}/{OT_PREFIX}.vrt", vrt)
        if status.startswith("failed"):
            sys.exit(f"could not fetch OpenTopography index: {status}")
    ot = ot_index(vrt)

    withheld = sorted(set(ot) - aws_keys)
    print(f"OT index {len(ot)} tiles, AWS tileList {len(aws_keys)} — "
          f"{len(withheld)} withheld to fetch", flush=True)
    if not withheld:
        print("nothing withheld — AWS and OT indices agree")
        return 0

    jobs = [(f"{OT_ENDPOINT}/{OT_PREFIX}/{ot[key]}", dem_dir / ot[key]) for key in withheld]
    counts = {"ok": 0, "skipped": 0}
    failures: list[str] = []
    with cf.ThreadPoolExecutor(WORKERS) as pool:
        futs = {pool.submit(download_one, url, dest): dest for url, dest in jobs}
        for index, fut in enumerate(cf.as_completed(futs), 1):
            status = fut.result()
            if status.startswith("failed"):
                failures.append(f"{futs[fut].name}  {status}")
            else:
                counts[status] += 1
            print(f"[{index}/{len(jobs)}] {futs[fut].name} {status}", flush=True)

    if failures:
        log = DATA_DIR / "failures.txt"
        log.write_text("\n".join(failures) + "\n")
        print(f"{len(failures)} failures -> {log}; rerun to retry")
        return 1
    print(f"complete: {counts['ok']} fetched, {counts['skipped']} already held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
