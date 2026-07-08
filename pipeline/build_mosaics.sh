#!/usr/bin/env bash
# Rebuild the GLO-30 mosaic VRTs over every downloaded tile.
#
# Run after each download_glo30.py extent expansion: the VRTs are the fixed
# entry points fuse_heightfield.py reads (data/work/{dem,wbm}_mosaic.vrt),
# and a VRT enumerates its source files at build time, so new tiles are
# invisible until rebuilt. A VRT is a small XML index — rebuilding is
# instant, touches no pixel data, and -overwrite makes reruns safe.
#
# Fill values must match fuse_heightfield.py's constants: gaps in tile
# coverage read as -9999 (DEM_NODATA) and 255 (WBM_NODATA, the "open ocean"
# signal in the fusion rule).
#
# Needs the GDAL CLI (gdalbuildvrt) — a system package, not part of the
# Python venv (rasterio's wheels bundle the GDAL library but not its tools).
set -euo pipefail

DATA="$(cd "$(dirname "$0")/.." && pwd)/data"

gdalbuildvrt -overwrite -vrtnodata -9999 \
  "$DATA/work/dem_mosaic.vrt" "$DATA"/raw/glo30/dem/*.tif
gdalbuildvrt -overwrite -vrtnodata 255 \
  "$DATA/work/wbm_mosaic.vrt" "$DATA"/raw/glo30/wbm/*.tif

echo "done: $(grep -c '<SimpleSource' "$DATA/work/dem_mosaic.vrt") DEM sources,"\
     "$(grep -c '<SimpleSource' "$DATA/work/wbm_mosaic.vrt") WBM sources"
