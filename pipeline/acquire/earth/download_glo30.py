"""Download Copernicus GLO-30 elevation tiles for one lat/lon extent.

For every 1x1 degree land tile intersecting --extent (per the bucket's
tileList.txt index), fetches two files from the public AWS bucket over
plain HTTPS, WORKERS files at a time, into the GLO-30 raw directory:

  dem/<tile>_DEM.tif   elevation, 1 arc-second, Float32 COG
  wbm/<tile>_WBM.tif   water-body mask (distinguishes sea/lake/river from land at 0m)

Resumable by construction: each file streams to a .part name, is size-checked
against the server's Content-Length, then atomically renamed. A file existing
under its final name is therefore always complete: re-runs skip finished files
and retry only what is missing. Failures never abort the run; they are listed
in failures.txt and retried on the next run.

Before downloading, a preflight proves the bucket hasn't changed editions
under us: the bucket carries no edition in any path, so mixing tiles fetched
years apart could silently mix Copernicus DEM editions. Local md5 of a few
held tiles must equal their S3 ETag (a plain md5 for these single-part
objects); any mismatch aborts.

Usage: python3 download_glo30.py --extent 60 0 100 40   # the Phase 0 window
"""

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from pipeline import datasets, fetch
from pipeline.fetch import download_one

BUCKET_URL = "https://copernicus-dem-30m.s3.amazonaws.com"
WORKERS = 6
# A passing preflight is stamped and reused this long. The check exists to catch
# bucket *edition swaps* — month-scale events — while the batch runner invokes
# this script once per country, so a daily check loses nothing and saves three
# HEADs + three full-tile md5s per country. rm the stamp to force a re-check.
PREFLIGHT_TTL_HOURS = 24.0


def parse_tile_name(name: str) -> tuple[int, int]:
    """SW corner of a tile named like 'Copernicus_DSM_COG_10_N28_00_E077_00_DEM'."""
    parts = name.split("_")
    lat = int(parts[4][1:]) * (1 if parts[4][0] == "N" else -1)
    lon = int(parts[6][1:]) * (1 if parts[6][0] == "E" else -1)
    return lat, lon


def in_extent(lat: int, lon: int, extent) -> bool:
    """True if the 1x1 degree tile with this SW corner overlaps the extent.

    Strict inequalities exclude tiles that only touch the boundary line,
    so an extent ending at 100E takes E099 (99..100) but not E100 (100..101).
    """
    west, south, east, north = extent
    return lon < east and lon + 1 > west and lat < north and lat + 1 > south


def preflight_stamp_path() -> Path:
    return datasets.glo30() / "preflight_ok.json"


def preflight_cached_age_hours() -> float | None:
    """Hours since the last successful preflight, or None if that result is
    unusable — stamp absent, unreadable, expired, or dated in the future
    (clock skew / a restored backup is not evidence the bucket is unchanged)."""
    try:
        stamp = json.loads(preflight_stamp_path().read_text())
        checked = datetime.fromisoformat(stamp["checked_utc"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    age_hours = (datetime.now(UTC) - checked).total_seconds() / 3600.0
    if not 0.0 <= age_hours < PREFLIGHT_TTL_HOURS:
        return None
    return age_hours


def bucket_preflight():
    """Abort if the bucket changed under us: md5 of held tiles vs S3 ETag."""
    age_hours = preflight_cached_age_hours()
    if age_hours is not None:
        print(f"bucket preflight: cached ok ({age_hours:.1f} h old) — "
              f"rm {preflight_stamp_path()} to re-verify", flush=True)
        return
    held = sorted((datasets.glo30() / "dem").glob("*.tif")) if (datasets.glo30() / "dem").exists() else []
    sample = [held[0], held[len(held) // 2], held[-1]] if held else []
    for path in dict.fromkeys(sample):
        name = path.stem
        with fetch.open_url(f"{BUCKET_URL}/{name}/{name}.tif",
                            method="HEAD", timeout=30) as resp:
            etag = resp.headers["ETag"].strip('"')
        local = hashlib.md5(path.read_bytes()).hexdigest()
        if local != etag:
            sys.exit(f"bucket preflight FAILED: {name} local md5 {local} != "
                     f"ETag {etag} — the bucket may have moved to a new "
                     f"Copernicus edition; stop and decide")
    if sample:
        # Stamp only what was actually verified — no held tiles means nothing
        # was checked, so there is nothing to cache. Atomic write (.tmp +
        # replace): the stamp's existence must mean a completed pass.
        stamp_tmp = preflight_stamp_path().with_suffix(".json.tmp")
        stamp_tmp.write_text(json.dumps({
            "checked_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "tiles": [path.stem for path in dict.fromkeys(sample)],
        }, indent=1) + "\n")
        os.replace(stamp_tmp, preflight_stamp_path())
    print(f"bucket preflight: {len(set(sample))} held tiles match their ETags"
          if sample else "bucket preflight: no held tiles yet — nothing to check",
          flush=True)


def tile_files(name: str) -> list[tuple[str, Path]]:
    """(url, local destination) pairs for one tile: the DEM and its water-body mask."""
    wbm = name.replace("_DEM", "_WBM") + ".tif"
    return [
        (f"{BUCKET_URL}/{name}/{name}.tif", datasets.glo30() / "dem" / f"{name}.tif"),
        (f"{BUCKET_URL}/{name}/AUXFILES/{wbm}", datasets.glo30() / "wbm" / wbm),
    ]


def fetch_tile_list() -> list[str]:
    """Fetch (or reuse) the bucket's index of all existing land tiles."""
    status = download_one(f"{BUCKET_URL}/tileList.txt", datasets.glo30_tile_list())
    if status.startswith("failed"):
        sys.exit(f"could not fetch tile list: {status}")
    return datasets.glo30_tile_list().read_text().split()


def main() -> int:
    ap = argparse.ArgumentParser()
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--extent", nargs=4, type=float,
                        metavar=("W", "S", "E", "N"),
                        help="lon/lat window; overlapping 1x1 degree land tiles "
                             "are fetched (Phase 0 window was 60 0 100 40)")
    source.add_argument("--tiles", type=Path,
                        help="file of explicit tile names, one per line (e.g. from "
                             "`fuse_planet --emit-missing`) — fetches exactly those, for "
                             "the scattered planet-coverage gap or a targeted re-download")
    args = ap.parse_args()

    bucket_preflight()
    for sub in ("dem", "wbm"):
        (datasets.glo30() / sub).mkdir(parents=True, exist_ok=True)

    if args.tiles:
        names = args.tiles.read_text().split()
    else:
        names = [tile_name for tile_name in fetch_tile_list()
                 if in_extent(*parse_tile_name(tile_name), args.extent)]
    jobs = [pair for tile_name in names for pair in tile_files(tile_name)]
    print(f"{len(names)} tiles in extent -> {len(jobs)} files")

    counts = {"ok": 0, "skipped": 0}
    failures: list[str] = []
    with cf.ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(download_one, url, dest): url for url, dest in jobs}
        for index, fut in enumerate(cf.as_completed(futures), 1):
            status = fut.result()
            if status.startswith("failed"):
                failures.append(f"{futures[fut]}  {status}")
            else:
                counts[status] += 1
            if index % 25 == 0 or index == len(jobs):
                print(f"[{index}/{len(jobs)}] ok={counts['ok']} "
                      f"skipped={counts['skipped']} failed={len(failures)}",
                      flush=True)

    if failures:
        log = datasets.glo30() / "failures.txt"
        log.write_text("\n".join(failures) + "\n")
        print(f"{len(failures)} failures written to {log} — rerun to retry")
        return 1
    print("complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
