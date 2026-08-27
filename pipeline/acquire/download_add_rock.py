"""Fetch SCAR ADD's automatically-extracted Antarctic rock outcrop and reproject it to EPSG:3857.

Antarctic land is forced permanent-ice white by a latitude rule, and this is the dataset that takes
exposed rock back out from under it; `snow.antarctic_snow_mask` subtracts it.

WHY A SEPARATE DATASET RATHER THAN A THRESHOLD ON THE SNOW WE ALREADY HAVE. Measured on NSIDC-0791's
own 0.01 degree grid over these very polygons: persistence reads a median 0.9999 ON exposed rock
against 1.0000 off it, and only 0.23% of rock cells score below the tile ramp's 0.60 cutoff. The
signal exists and sits three orders of magnitude away from any threshold that could act on it, so
99.77% of the outcrop would render as ice however the ramp were tuned. RGI 7.0 cannot help either:
it is an inventory of GLACIERS, so an absent polygon is not a claim that the ground is bare, and its
region 19 maps 0.99% of Antarctic land.

THE PRODUCT MATTERS AND THERE ARE THREE OF THEM UNDER NEARLY THE SAME NAME. This is the LANDSAT
auto-extraction (Burton-Johnson et al. 2016, Gerrish 2020), not the high-resolution compilation and
not the medium-resolution polygon layer. Measured on our own z8 grid the Landsat layer reads
26,340 km2 against the paper's published 21,745 +/- 5,654; the medium-resolution v7.11 layer reads
61,414 km2, 2.8x the published figure, which is the 1993 1:250k digitisation showing through. The
three sit at three DOIs with three citations, so a swap here is a licence and attribution question
as much as a look one.

Source is EPSG:3031 (Antarctic Polar Stereographic) and is reprojected once, here, because every
consumer wants Mercator and a per-run reprojection of 147 MB of polygons is not free.

    python -m pipeline.acquire.download_add_rock
    -> data/raw/addrock/add_rockoutcrop_landsat_v7.3.zip (+ unzipped)
    -> data/raw/addrock/add_rock_3857.gpkg (layer 'rock')
"""

import subprocess
import sys
import zipfile

from pipeline import datasets
from pipeline.fetch import download_one

#: The dataset landing page, which is where the licence and citation below come from. Recorded
#: because the archive carries neither: no licence file travels inside the zip, so a copy of it
#: sitting on disk is indistinguishable from one with no terms at all.
LANDING = "https://data.bas.ac.uk/items/178ec50d-1ffb-42a4-a4a3-1145419da2bb/"
DOI = "https://doi.org/10.5285/178ec50d-1ffb-42a4-a4a3-1145419da2bb"
LICENCE = "CC BY 4.0"
CITATION = ("Gerrish, L. (2020). Automatically extracted rock outcrop dataset for Antarctica (7.3) "
            "[Data set]. UK Polar Data Centre, Natural Environment Research Council, "
            f"UK Research & Innovation. {DOI}")

ARCHIVE = "add_rockoutcrop_landsat_v7.3.zip"
URL = ("https://ramadda.data.bas.ac.uk/repository/entry/get/" + ARCHIVE +
       "?entryid=synth%3A178ec50d-1ffb-42a4-a4a3-1145419da2bb"
       "%3AL2FkZF9yb2Nrb3V0Y3JvcF9sYW5kc2F0X3Y3LjMuemlw")

LAYER = "rock"


def main():
    out_dir, gpkg_path = datasets.addrock(), datasets.addrock_gpkg()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"{CITATION}\nLicence: {LICENCE} ({LANDING})", flush=True)

    zip_path = out_dir / ARCHIVE
    if not zip_path.exists():
        print(f"downloading {ARCHIVE} (~41 MB) ...", flush=True)
        # `download_one` streams to `.part` and renames atomically, so an interrupted download
        # cannot leave a truncated file that the `exists()` check above reads as finished.
        status = download_one(URL, zip_path, timeout=300)
        if status.startswith("failed"):
            sys.exit(f"{ARCHIVE}: {status}")
    print(f"  {ARCHIVE}: {zip_path.stat().st_size / 1e6:.1f} MB", flush=True)

    unzip_dir = out_dir / zip_path.stem
    if not unzip_dir.exists():
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(unzip_dir)
    shapefile = next(unzip_dir.rglob("*.shp"))

    if not gpkg_path.exists():
        print(f"reprojecting {shapefile.name} -> {gpkg_path.name} (EPSG:3031 -> EPSG:3857) ...",
              flush=True)
        subprocess.run(["ogr2ogr", "-f", "GPKG", "-t_srs", "EPSG:3857", "-nln", LAYER,
                        "-skipfailures", str(gpkg_path), str(shapefile)],
                       check=True, capture_output=True)
    print(f"done -> {gpkg_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
