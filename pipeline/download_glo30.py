#!/usr/bin/env python3
"""Download Copernicus GLO-30 elevation tiles for one lat/lon extent.

For every 1x1 degree land tile intersecting --extent (per the bucket's
tileList.txt index), fetches two files from the public AWS bucket over
plain HTTPS, WORKERS files at a time, into DATA_DIR:

  dem/<tile>_DEM.tif   elevation, 1 arc-second, Float32 COG
  wbm/<tile>_WBM.tif   water-body mask (distinguishes sea/lake/river from land at 0m)

Resumable by construction: each file streams to a .part name, is size-checked
against the server's Content-Length, then atomically renamed. A file existing
under its final name is therefore always complete: re-runs skip finished files
and retry only what is missing. Failures never abort the run; they are listed
in failures.txt and retried on the next run.

Before downloading, a preflight proves the bucket hasn't changed editions
under us (the standing oracle from PLAN.md 2026-07-08): the bucket carries no
edition in any path, so mixing tiles fetched years apart could silently mix
Copernicus DEM editions. Local md5 of a few held tiles must equal their S3
ETag (a plain md5 for these single-part objects); any mismatch aborts.

Usage: python3 download_glo30.py --extent 60 0 100 40   # the Phase 0 window
"""

import argparse
import concurrent.futures as cf
import hashlib
import os
import shutil
import sys
import urllib.request
from pathlib import Path

BUCKET_URL = "https://copernicus-dem-30m.s3.amazonaws.com"
DATA_DIR = Path.home() / "projects/maps/data/raw/glo30"
TILE_LIST = DATA_DIR / "tileList.txt"
WORKERS = 6


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


def bucket_preflight():
    """Abort if the bucket changed under us: md5 of held tiles vs S3 ETag."""
    held = sorted((DATA_DIR / "dem").glob("*.tif")) if (DATA_DIR / "dem").exists() else []
    sample = [held[0], held[len(held) // 2], held[-1]] if held else []
    for path in dict.fromkeys(sample):
        name = path.stem
        req = urllib.request.Request(f"{BUCKET_URL}/{name}/{name}.tif",
                                     method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as resp:
            etag = resp.headers["ETag"].strip('"')
        local = hashlib.md5(path.read_bytes()).hexdigest()
        if local != etag:
            sys.exit(f"bucket preflight FAILED: {name} local md5 {local} != "
                     f"ETag {etag} — the bucket may have moved to a new "
                     f"Copernicus edition; stop and decide (PLAN.md 2026-07-08)")
    print(f"bucket preflight: {len(set(sample))} held tiles match their ETags"
          if sample else "bucket preflight: no held tiles yet — nothing to check",
          flush=True)


def download_one(url: str, dest: Path) -> str:
    """Download url to dest. Returns 'ok', 'skipped', or 'failed: <reason>'."""
    if dest.exists():
        return "skipped"
    part = dest.with_suffix(".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            expected = int(resp.headers.get("Content-Length", -1))
            with open(part, "wb") as out:
                shutil.copyfileobj(resp, out)
        actual = part.stat().st_size
        if expected != -1 and actual != expected:
            part.unlink()
            return f"failed: size mismatch ({actual} of {expected} bytes)"
        os.replace(part, dest)
        return "ok"
    except Exception as exc:
        part.unlink(missing_ok=True)
        return f"failed: {exc}"


def tile_files(name: str) -> list[tuple[str, Path]]:
    """(url, local destination) pairs for one tile: the DEM and its water-body mask."""
    wbm = name.replace("_DEM", "_WBM") + ".tif"
    return [
        (f"{BUCKET_URL}/{name}/{name}.tif", DATA_DIR / "dem" / f"{name}.tif"),
        (f"{BUCKET_URL}/{name}/AUXFILES/{wbm}", DATA_DIR / "wbm" / wbm),
    ]


def fetch_tile_list() -> list[str]:
    """Fetch (or reuse) the bucket's index of all existing land tiles."""
    status = download_one(f"{BUCKET_URL}/tileList.txt", TILE_LIST)
    if status.startswith("failed"):
        sys.exit(f"could not fetch tile list: {status}")
    return TILE_LIST.read_text().split()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extent", nargs=4, type=float, required=True,
                    metavar=("W", "S", "E", "N"),
                    help="lon/lat window; overlapping 1x1 degree land tiles "
                         "are fetched (Phase 0 window was 60 0 100 40)")
    args = ap.parse_args()

    bucket_preflight()
    for sub in ("dem", "wbm"):
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)

    names = [n for n in fetch_tile_list()
             if in_extent(*parse_tile_name(n), args.extent)]
    jobs = [pair for n in names for pair in tile_files(n)]
    print(f"{len(names)} tiles in extent -> {len(jobs)} files")

    counts = {"ok": 0, "skipped": 0}
    failures: list[str] = []
    with cf.ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(download_one, url, dest): url for url, dest in jobs}
        for i, fut in enumerate(cf.as_completed(futures), 1):
            status = fut.result()
            if status.startswith("failed"):
                failures.append(f"{futures[fut]}  {status}")
            else:
                counts[status] += 1
            if i % 25 == 0 or i == len(jobs):
                print(f"[{i}/{len(jobs)}] ok={counts['ok']} "
                      f"skipped={counts['skipped']} failed={len(failures)}",
                      flush=True)

    if failures:
        log = DATA_DIR / "failures.txt"
        log.write_text("\n".join(failures) + "\n")
        print(f"{len(failures)} failures written to {log} — rerun to retry")
        return 1
    print("complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
