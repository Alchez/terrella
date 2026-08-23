"""Fetch RGI 7.0 'G' glacier shapefiles (GTN-G regions) from the open UNESCO IHP-WINS mirror
and merge them into one EPSG:3857 GeoPackage for rasterizing into the tile snow layer.

RGI 7.0 (NSIDC-0770 v7) has no CMR granules and its NSIDC data pool needs interactive-OAuth
(a token-only session is bounced to the login page), so we take the open re-host: UNESCO's
IHP-WINS CKAN portal serves the identical regional shapefiles as direct downloads. ALL NINETEEN
REGIONS ARE TAKEN, and this file is where that is enforced rather than assumed — see `shp_urls`.
Idempotent at every step (download, unzip, merge).

    python -m pipeline.acquire.download_rgi
    -> data/raw/rgi/*.zip (+ unzipped) and data/raw/rgi/rgi7_g_3857.gpkg (layer 'glaciers')
"""

import json
import re
import subprocess
import sys
import zipfile

from pipeline import fetch, paths
from pipeline.fetch import download_one

CKAN = "https://ihp-wins.unesco.org/api/3/action/package_search?q=Randolph+Glacier+Inventory+7.0&rows=5"
DATASET = "randolph-glacier-inventory-rgi-7-0-glacier-product"
OUT = paths.DATA / "raw/rgi"
GPKG = OUT / "rgi7_g_3857.gpkg"

#: RGI 7.0's first-order regions, 01 to 19, and the merge wants every one of them.
REGION_COUNT = 19

#: The region number in a regional filename: `rgi2000-v7.0-g-07_svalbard_jan_mayen.zip` -> 7.
REGION_IN_NAME = re.compile(r"-g-(\d{2})_")


def shp_urls(resources):
    """Every regional shapefile in a CKAN resource list, sorted, or raise naming what is missing.

    A MISSING REGION IS SILENT EVERYWHERE DOWNSTREAM, which is why the check is here and loud: the
    burn just has no polygons there, the raster is a valid file of the right size, every freshness
    check passes, and the map draws glacierised land on the bare-ground ramp. Region 19 was dropped
    at this call and cost the Sub-Antarctic islands 482 km2 of white, so this is an anti-redo guard
    rather than a hypothetical.

    Checked against a DERIVED 1..REGION_COUNT rather than a listed set of names, so a portal rename
    and a portal outage are refused on the same path.
    """
    urls = sorted(r["url"] for r in resources if (r.get("format") or "").upper() == "SHP")
    found = {int(match.group(1)) for url in urls if (match := REGION_IN_NAME.search(url))}
    missing = sorted(set(range(1, REGION_COUNT + 1)) - found)
    if missing:
        raise RuntimeError(
            f"IHP-WINS listed {len(urls)} RGI shapefiles but no region {missing} among them; "
            "merging short would leave those regions as bare ground on the map with nothing "
            "downstream able to tell. Check the portal's filenames before rerunning.")
    return urls


def resource_urls():
    with fetch.open_url(CKAN, timeout=60) as response:
        data = json.load(response)
    pkg = next(p for p in data["result"]["results"] if p["name"] == DATASET)
    return shp_urls(pkg["resources"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    urls = resource_urls()
    print(f"{len(urls)} RGI 7.0 G regional shapefiles, every published region", flush=True)
    shapefiles = []
    for url in urls:
        name = url.split("/")[-1]
        zip_path = OUT / name
        if not zip_path.exists():
            print(f"downloading {name} ...", flush=True)
            # `download_one` rather than a direct fetch, and not only for the User-Agent: it
            # streams to `.part` and renames atomically, where the `urlretrieve` this replaced
            # wrote straight to the final name. An interrupted download therefore looked exactly
            # like a finished one to the `exists()` check above, and the truncation surfaced later
            # as a corrupt zip — one stage away from the thing that actually went wrong.
            status = download_one(url, zip_path)
            if status.startswith("failed"):
                sys.exit(f"{name}: {status}")
        unzip_dir = OUT / zip_path.stem
        if not unzip_dir.exists():
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(unzip_dir)
        shapefiles.append(next(unzip_dir.rglob("*.shp")))
        print(f"  {name}: {zip_path.stat().st_size / 1e6:.1f} MB", flush=True)

    if GPKG.exists():
        GPKG.unlink()
    print(f"merging {len(shapefiles)} regions -> {GPKG.name} (EPSG:3857) ...", flush=True)
    for index, shp in enumerate(shapefiles):
        cmd = ["ogr2ogr", "-f", "GPKG", "-t_srs", "EPSG:3857", "-nln", "glaciers", "-skipfailures"]
        cmd += (["-append"] if index else []) + [str(GPKG), str(shp)]
        subprocess.run(cmd, check=True, capture_output=True)
    print(f"done -> {GPKG}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
