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

from pipeline import datasets, fetch
from pipeline.fetch import download_one

CKAN = "https://ihp-wins.unesco.org/api/3/action/package_search?q=Randolph+Glacier+Inventory+7.0&rows=5"
DATASET = "randolph-glacier-inventory-rgi-7-0-glacier-product"
LAYER ="glaciers"     # the merged layer's name; every consumer reads it from here

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


def merge_to_gpkg(shapefiles, out=None):
    """Merge regional shapefiles into one EPSG:3857 GeoPackage, appearing only when complete.

    STAGED AND RENAMED, never written in place, for the reason the zips above are: a target written
    in place EXISTS and is short for the whole merge, and every consumer downstream keys on exactly
    that. `layer_producers` lists this path as a freshness mtime, so a merge that dies at region 12
    leaves a GeoPackage missing seven regions, newer than the warp that reads it, and therefore
    CURRENT — the planet is burnt with a third of its glaciers gone and nothing anywhere reports it.
    A rename is atomic within a filesystem, so the previous complete merge stands until this one is.

    NO `-skipfailures`, AND IT MUST NOT COME BACK. It sets the transaction size to 1, which is free
    while the table is empty and quadratic once it is not: measured on region 19 into a 75,613-row
    base, 51.8s with it against 1.3s without, byte-identical output. Over 19 appends that is the
    difference between ~40 minutes and ~1. `-gt` does not rescue it -- paired with `-skipfailures`
    the append silently writes nothing at all. It is also the wrong behaviour: it DROPS features
    quietly, which is the failure `shp_urls` refuses one tier up. A bad geometry should stop the
    merge, not thin it.
    DEFAULTED HERE AND NOT IN THE SIGNATURE, because a default argument is evaluated at import and
    would freeze the store exactly as the module-level constant it replaced did.
    """
    out = datasets.rgi_gpkg() if out is None else out
    staging = out.with_name(out.name + ".part")
    staging.unlink(missing_ok=True)
    try:
        for index, shp in enumerate(shapefiles):
            cmd = ["ogr2ogr", "-f", "GPKG", "-t_srs", "EPSG:3857", "-nln", LAYER]
            cmd += (["-append"] if index else []) + [str(staging), str(shp)]
            subprocess.run(cmd, check=True, capture_output=True)
    except BaseException:
        staging.unlink(missing_ok=True)  # a gigabyte of half-merged planet is not worth keeping
        raise
    staging.replace(out)
    return out


def main():
    out_dir, gpkg_path = datasets.rgi(), datasets.rgi_gpkg()
    out_dir.mkdir(parents=True, exist_ok=True)
    urls = resource_urls()
    print(f"{len(urls)} RGI 7.0 G regional shapefiles, every published region", flush=True)
    shapefiles = []
    for url in urls:
        name = url.split("/")[-1]
        zip_path = out_dir / name
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
        unzip_dir = out_dir / zip_path.stem
        if not unzip_dir.exists():
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(unzip_dir)
        shapefiles.append(next(unzip_dir.rglob("*.shp")))
        print(f"  {name}: {zip_path.stat().st_size / 1e6:.1f} MB", flush=True)

    print(f"merging {len(shapefiles)} regions -> {gpkg_path.name} (EPSG:3857) ...", flush=True)
    merge_to_gpkg(shapefiles)
    print(f"done -> {gpkg_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
