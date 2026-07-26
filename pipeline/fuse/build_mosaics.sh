#!/usr/bin/env bash
# Rebuild the GLO-30 mosaic VRTs over every downloaded tile.
#
# Run after each download_glo30.py extent expansion: the VRTs are the fixed
# entry points fuse_heightfield.py reads (data/work/{dem,wbm}_mosaic.vrt),
# and a VRT enumerates its source files at build time, so new tiles are
# invisible until rebuilt. A VRT is a small XML index — rebuilding touches
# no pixel data, and reruns are safe.
#
# Freshness skip: the batch runner invokes this once per country, but the
# tile store only changes when a download actually lands. The previous build
# is reused when (a) the current source list is byte-identical to the
# .sources sidecar written by the last build — catches added AND deleted
# tiles (a deletion leaves every remaining source older than the VRT, so
# mtime alone cannot see it) — and (b) no source is newer than the VRT —
# catches a re-downloaded tile (same name, same count). Either check failing
# rebuilds both VRTs (fuse_heightfield consumes them as a pair). To force a
# rebuild: rm the VRTs.
#
# Fill values must match fuse_heightfield.py's constants: gaps in tile
# coverage read as -9999 (DEM_NODATA) and 255 (WBM_NODATA, the "open ocean"
# signal in the fusion rule).
#
# Needs the GDAL CLI (gdalbuildvrt) — a system package, not part of the
# Python venv (rasterio's wheels bundle the GDAL library but not its tools).
set -euo pipefail

# MAPS_DATA overrides the data root (tests, alternate checkouts); the default
# is the repo's data/ next to this script.
DATA="${MAPS_DATA:-$(cd "$(dirname "$0")/../.." && pwd)/data}"

# Sources: the AWS GLO-30 tiles plus the OpenTopography 2023_1 void-fill tiles
# (download_cop30_void.py) and their WorldCover-derived WBM (build_void_wbm.py).
# nullglob keeps the void dirs optional — a machine without them builds the
# AWS-only mosaic. The two sets are spatially disjoint (void = the tiles AWS
# withholds), so there is no overlap to prioritise.
shopt -s nullglob
dem_src=("$DATA"/raw/glo30/dem/*.tif "$DATA"/raw/cop30_void/dem/*.tif)
wbm_src=("$DATA"/raw/glo30/wbm/*.tif "$DATA"/raw/cop30_void/wbm/*.tif)
shopt -u nullglob

# The source lists go via -input_file_list: 26k+ paths as argv overflow the
# kernel's ARG_MAX (first hit at the Antarctic extent expansion).
dem_list="$(mktemp)"
wbm_list="$(mktemp)"
trap 'rm -f "$dem_list" "$wbm_list"' EXIT
printf '%s\n' "${dem_src[@]}" > "$dem_list"
printf '%s\n' "${wbm_src[@]}" > "$wbm_list"

dem_vrt="$DATA/work/dem_mosaic.vrt"
wbm_vrt="$DATA/work/wbm_mosaic.vrt"

fresh() { # fresh <list> <vrt>: sources match the last build and none is newer
  local list="$1" vrt="$2" src
  [[ -f "$vrt" ]] || return 1
  cmp -s "$list" "$vrt.sources" || return 1
  while IFS= read -r src; do
    if [[ "$src" -nt "$vrt" ]]; then return 1; fi
  done < "$list"
}

if fresh "$dem_list" "$dem_vrt" && fresh "$wbm_list" "$wbm_vrt"; then
  echo "mosaics fresh: ${#dem_src[@]} DEM + ${#wbm_src[@]} WBM sources unchanged" \
       "— skipping rebuild (rm $dem_vrt to force)"
  exit 0
fi

# Build to .tmp then rename (the pipeline's atomic-replace convention): a crash
# mid-gdalbuildvrt must not leave a truncated VRT that the freshness check
# would then trust. Same-directory rename keeps any relative source paths valid.
gdalbuildvrt -overwrite -vrtnodata -9999 \
  -input_file_list "$dem_list" "$dem_vrt.tmp"
gdalbuildvrt -overwrite -vrtnodata 255 \
  -input_file_list "$wbm_list" "$wbm_vrt.tmp"
mv "$dem_vrt.tmp" "$dem_vrt"
mv "$wbm_vrt.tmp" "$wbm_vrt"
cp "$dem_list" "$dem_vrt.sources"
cp "$wbm_list" "$wbm_vrt.sources"

echo "done: $(grep -c '<SimpleSource' "$dem_vrt") DEM sources,"\
     "$(grep -c '<SimpleSource' "$wbm_vrt") WBM sources"
