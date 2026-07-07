#!/usr/bin/env bash
# Download Natural Earth 1:10m vectors: border overlays, camera-framing polygons,
# and the coastline used as the overlay-alignment oracle.
# Idempotent: a layer whose directory already exists is skipped; a failed download
# never leaves a directory behind (curl -f fails loudly, unzip validates the zip).
set -euo pipefail

BASE="https://naciscdn.org/naturalearth"
DEST="$(cd "$(dirname "$0")/.." && pwd)/data/raw/naturalearth"

LAYERS=(
  "10m/cultural/ne_10m_admin_0_boundary_lines_land"
  "10m/cultural/ne_10m_admin_0_boundary_lines_maritime_indicator"
  "10m/cultural/ne_10m_admin_0_countries"
  "10m/physical/ne_10m_coastline"
  "10m/physical/ne_10m_lakes"
  "10m/physical/ne_10m_rivers_lake_centerlines"
)

mkdir -p "$DEST"
for layer in "${LAYERS[@]}"; do
  name="$(basename "$layer")"
  dir="$DEST/$name"
  if [ -d "$dir" ]; then
    echo "skip $name (exists)"
    continue
  fi
  echo "fetch $name"
  curl -fsSL "$BASE/$layer.zip" -o "$dir.zip.part"
  mv "$dir.zip.part" "$dir.zip"
  unzip -q -o "$dir.zip" -d "$dir"
  rm "$dir.zip"
done
echo "done: $DEST"
