"""Fetch RGI 7.0 'G' glacier shapefiles (GTN-G regions) from the open UNESCO IHP-WINS mirror
and merge them into one EPSG:3857 GeoPackage for rasterizing into the tile snow layer.

RGI 7.0 (NSIDC-0770 v7) has no CMR granules and its NSIDC data pool needs interactive-OAuth
(a token-only session is bounced to the login page), so we take the open re-host: UNESCO's
IHP-WINS CKAN portal serves the identical regional shapefiles as direct downloads. Region 19
(Antarctic/Subantarctic) is skipped — the tiles are non-Antarctic and its polygons fall outside
the Web-Mercator latitude range. Idempotent at every step (download, unzip, merge).

    python -m pipeline.acquire.download_rgi
    -> data/raw/rgi/*.zip (+ unzipped) and data/raw/rgi/rgi7_g_3857.gpkg (layer 'glaciers')
"""

import json
import subprocess
import urllib.request
import zipfile

from pipeline import paths

CKAN = "https://ihp-wins.unesco.org/api/3/action/package_search?q=Randolph+Glacier+Inventory+7.0&rows=5"
DATASET = "randolph-glacier-inventory-rgi-7-0-glacier-product"
OUT = paths.DATA / "raw/rgi"
GPKG = OUT / "rgi7_g_3857.gpkg"


def resource_urls():
    with urllib.request.urlopen(CKAN, timeout=60) as response:
        data = json.load(response)
    pkg = next(p for p in data["result"]["results"] if p["name"] == DATASET)
    urls = [r["url"] for r in pkg["resources"] if (r.get("format") or "").upper() == "SHP"]
    return sorted(u for u in urls if "-19_" not in u.lower())  # skip Antarctic/Subantarctic


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    urls = resource_urls()
    print(f"{len(urls)} RGI 7.0 G regional shapefiles (region 19 excluded)", flush=True)
    shapefiles = []
    for url in urls:
        name = url.split("/")[-1]
        zip_path = OUT / name
        if not zip_path.exists():
            print(f"downloading {name} ...", flush=True)
            urllib.request.urlretrieve(url, zip_path)
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
