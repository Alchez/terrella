"""Download GWL_FCS30, the 2020 global 30 m wetland map (Zenodo record 7340516).

Twelve archives of 5 degree GeoTIFFs, one per longitude band, kept as published. The record is
immutable, so each archive is pinned by size and md5, and the preflight reads the record again,
licence included, before anything downloads.

    python -m pipeline.acquire.earth.download_gwl
    python -m pipeline.acquire.earth.download_gwl --verify     # re-md5 what is on disk
"""

import argparse
import json
import sys

from pipeline import datasets, fetch
from pipeline.fetch import download_one

RECORD = "https://zenodo.org/api/records/7340516"
DOI = "https://doi.org/10.5281/zenodo.7340516"
LICENCE = "cc-by-4.0"

#: Every archive the record publishes, as its file list gives them: name, size in bytes, md5.
ARCHIVES = {
    "GWL_FCS30_2020_E0_E30.zip": (297427536, "85db57face8bb8bc977074fe13652eed"),
    "GWL_FCS30_2020_E35_E60.zip": (174267195, "957255549de05d6d4e94dba95ae8ad43"),
    "GWL_FCS30_2020_E65_E90.zip": (312683339, "9fa27ec7866b92625bd9d850727799b7"),
    "GWL_FCS30_2020_E95_E120.zip": (175836911, "54b93967ac0b953ea050bcd1ae3eed52"),
    "GWL_FCS30_2020_E125_E150.zip": (135637218, "5541663ed4683bbd69d8841bbd36c4be"),
    "GWL_FCS30_2020_E155_E175.zip": (36358060, "35649634f9729e8fd187c194fd9785e8"),
    "GWL_FCS30_2020_W5_W30.zip": (38025054, "0fd508ad3456e6da35678279ecd8dbcc"),
    "GWL_FCS30_2020_W35_W60.zip": (153693437, "8451a24f396334defdb825201185910b"),
    "GWL_FCS30_2020_W65_W90.zip": (506999863, "40a06a1be51714db4500798a74f877c1"),
    "GWL_FCS30_2020_W95_W120.zip": (469417446, "b6cf4ef0247be2446426d4be17e82d3e"),
    "GWL_FCS30_2020_W125_W150.zip": (89948407, "7c955c314f5d2debe4ffe1bc2ad65df9"),
    "GWL_FCS30_2020_W155_W175.zip": (29547733, "1c7e07eebe5e7bc063f4be6764ff7538"),
}


def content_url(name: str) -> str:
    return f"{RECORD}/files/{name}/content"


def record() -> dict:
    with fetch.open_url(RECORD, timeout=60) as response:
        return json.load(response)


def preflight(published: dict) -> None:
    """Exit unless the record lists exactly the pinned archives, at their pinned sizes and md5s,
    under `LICENCE`."""
    licence = ((published.get("metadata") or {}).get("license") or {}).get("id")
    if licence != LICENCE:
        sys.exit(f"{RECORD} is now licensed {licence!r}, not {LICENCE!r}: read the new terms "
                 f"before anything is fetched under them")
    listed = {item["key"]: (item["size"], item["checksum"].removeprefix("md5:"))
              for item in published.get("files", [])}
    unmatched = sorted(set(listed) ^ set(ARCHIVES))
    if unmatched:
        sys.exit(f"{RECORD} and the pin disagree on which archives exist: {unmatched}")
    drifted = sorted(name for name in ARCHIVES if listed[name] != ARCHIVES[name])
    if drifted:
        sys.exit(f"{RECORD} now lists other sizes or md5s for {drifted}: an immutable record has "
                 f"changed, so stop and check before re-pinning")


def fetch_archive(name: str, verify_existing: bool) -> str:
    """One archive, downloaded if absent, md5-checked when fresh or when asked, removed on a mismatch
    so the next run fetches it again rather than skipping it."""
    dest = datasets.gwl() / name
    status = download_one(content_url(name), dest)
    if status.startswith("failed") or (status == "skipped" and not verify_existing):
        return status
    pinned = ARCHIVES[name][1]
    actual = fetch.file_md5(dest)
    if actual != pinned:
        dest.unlink()
        return f"failed: md5 {actual} != {pinned} (removed; rerun to retry)"
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--verify", action="store_true", help="re-md5 archives already on disk")
    args = parser.parse_args()

    datasets.gwl().mkdir(parents=True, exist_ok=True)
    preflight(record())
    print(f"preflight ok: {len(ARCHIVES)} archives match the pin, {LICENCE} ({DOI})", flush=True)
    failures = []
    for name, (size, _md5) in ARCHIVES.items():
        print(f"{name} ({size / 1e6:.0f} MB) ...", flush=True)
        status = fetch_archive(name, args.verify)
        print(f"  {status}", flush=True)
        if status.startswith("failed"):
            failures.append(f"{name}: {status}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        print(f"{len(failures)} failed, rerun to retry", flush=True)
        return 1
    print(f"complete -> {datasets.gwl()}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
