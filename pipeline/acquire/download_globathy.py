#!/usr/bin/env python3
"""Download the GLOBathy lake-bathymetry dataset (Khazaei 2022, CC0).

The general answer to lake depth: every lake except the Caspian and the Great Lakes fuses
as a flat slab because GEBCO carries real bathymetry for those two only. GLOBathy models
the rest as a calibrated cone D = l x Dmax / L over 1,427,688 waterbodies at 1 arc-second,
using published maximum depths (Baikal 1642 m, Tanganyika 1470, Ladoga 230, Titicaca 281).

Depth here is TINT-ONLY and never enters the heightfield
exaggeration a carved Namtso becomes a 1.5 km crater and the shadow-catching plate dies),
so this feeds the render layer beside snow -- not fusion. That also means we need no
HydroLAKES join: it exists only to place basins vertically, and nothing is placed.
GLOBathy alone is CC0, so the whole layer carries no attribution obligation.

Two archives:
  GLOBathy_basic_parameters.zip  115 MB  CSVs: Dmax, area, elevation per waterbody
  Bathymetry_Rasters.zip          16.7 GB  1,427,688 per-lake 1" GeoTIFFs

Fetch the CSVs first (--only csv) -- their areas decide which rasters are worth extracting
at all (at 306 m/px only lakes more than a few km across show any gradient), so there is no
point pulling 16.7 GB before that threshold is picked.

Edition oracle: figshare's /versions/1 endpoint is immutable, so the pin is the versioned
API URL (the self-pinning download_gebco.py model) cross-checked against the size + md5
baked in below. If figshare ever serves different bytes under v1, preflight aborts loudly
rather than silently swapping the dataset underneath us. Downloads reuse
download_glo30.download_one (.part -> Content-Length check -> atomic rename), so a file
under its final name is always complete and re-runs skip it; md5 is verified on fresh
downloads only, so an idempotent re-run stays instant instead of re-hashing 16.7 GB.

Usage:
  python3 -m pipeline.acquire.download_globathy --only csv   # 115 MB, do this first
  python3 -m pipeline.acquire.download_globathy              # both archives
  python3 -m pipeline.acquire.download_globathy --verify     # re-md5 what is on disk
"""

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

from pipeline import paths
from pipeline.acquire.download_glo30 import download_one

DATA_DIR = paths.DATA / "raw/globathy"
API = "https://api.figshare.com/v2/articles/{article}/versions/1"
DOWNLOAD = "https://ndownloader.figshare.com/files/{file_id}"
MD5_CHUNK = 1 << 20

# Pinned against figshare v1, read from the API. Both articles are CC0.
FILES = {
    "csv": dict(
        name="GLOBathy_basic_parameters.zip", article=13402070, file_id=28919991,
        size=115568963, md5="0d4af9b1a394e37ebe29058bfd3c8d69",
    ),
    "rasters": dict(
        name="Bathymetry_Rasters.zip", article=13404635, file_id=28919850,
        size=16727583261, md5="d848696696b5187541a7b572a9871cbe",
    ),
}


def file_md5(path: Path) -> str:
    """md5 of a file, read in chunks (these archives do not fit in RAM)."""
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        while chunk := handle.read(MD5_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def preflight(entry: dict) -> None:
    """Assert figshare still serves the exact bytes this script is pinned to.

    Version 1 of a figshare article is immutable by contract, so any drift here means the
    contract broke -- abort rather than download a silently different edition.
    """
    url = API.format(article=entry["article"])
    with urllib.request.urlopen(url, timeout=60) as response:
        article = json.load(response)
    served = {item["name"]: item for item in article.get("files", [])}
    if entry["name"] not in served:
        sys.exit(f"{entry['name']} is gone from figshare article {entry['article']} v1 "
                 f"(serves: {sorted(served)}) -- edition drift, stop and check")
    listed = served[entry["name"]]
    for field, expected in (("size", entry["size"]), ("supplied_md5", entry["md5"])):
        if listed.get(field) != expected:
            sys.exit(f"{entry['name']}: figshare v1 now reports {field}={listed.get(field)!r}, "
                     f"pinned to {expected!r} -- edition drift, stop and check")
    license_name = (article.get("license") or {}).get("name")
    if license_name != "CC0":
        sys.exit(f"{entry['name']}: license is now {license_name!r}, not CC0 -- the "
                 f"no-attribution assumption in ATTRIBUTIONS.md no longer holds")


def fetch(entry: dict, verify_existing: bool) -> str:
    """Download one archive if absent; md5-check whatever is new (or --verify)."""
    dest = DATA_DIR / entry["name"]
    gigabytes = entry["size"] / 1e9
    print(f"{entry['name']} ({gigabytes:.2f} GB) ...", flush=True)
    status = download_one(DOWNLOAD.format(file_id=entry["file_id"]), dest)
    if status.startswith("failed"):
        return status
    if status == "skipped" and not verify_existing:
        print("  already complete -> skipped", flush=True)
        return status
    print("  verifying md5 ...", flush=True)
    actual = file_md5(dest)
    if actual != entry["md5"]:
        dest.unlink()
        return f"failed: md5 {actual} != {entry['md5']} (removed; rerun to retry)"
    print(f"  md5 ok ({entry['md5']})", flush=True)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--only", choices=sorted(FILES),
                        help="fetch just one archive ('csv' is the 115 MB parameters table)")
    parser.add_argument("--verify", action="store_true",
                        help="re-md5 archives already on disk (slow: 16.7 GB)")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="skip the figshare edition check (offline reruns)")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    wanted = [FILES[args.only]] if args.only else [FILES[key] for key in ("csv", "rasters")]

    if not args.skip_preflight:
        for entry in wanted:
            preflight(entry)
        print(f"preflight ok: figshare v1 matches the pin for {len(wanted)} archive(s), CC0",
              flush=True)

    failures = []
    for entry in wanted:
        status = fetch(entry, args.verify)
        if status.startswith("failed"):
            failures.append(f"{entry['name']}  {status}")

    if failures:
        log = DATA_DIR / "failures.txt"
        log.write_text("\n".join(failures) + "\n")
        print("\n".join(failures), file=sys.stderr)
        print(f"{len(failures)} failure(s) written to {log} -- rerun to retry", flush=True)
        return 1
    print(f"complete -> {DATA_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
