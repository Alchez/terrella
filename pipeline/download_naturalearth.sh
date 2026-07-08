#!/usr/bin/env bash
# Download Natural Earth 1:10m vectors at a pinned release: border overlays,
# camera-framing polygons, disputed-area segments (worldview dashing), and the
# coastline used as the overlay-alignment oracle.
#
# Pinned to a release tag of the canonical repo (nvkelso/natural-earth-vector)
# because naturalearthdata.com / naciscdn serve only an unversioned "latest" —
# a fresh machine must reproduce this exact dataset, not whatever is current.
# Bumping TAG is a deliberate migration: bbox-diff the country frames and
# re-check disputed-segment styling before adopting.
#
# NB: each layer's VERSION.txt records when that layer itself last changed
# (e.g. the coastline says 5.0.0-pre9 inside the 5.1.2 release) — it is the
# layer version, not the release version.
#
# Idempotent: a layer whose directory already exists is skipped; a failed
# download never leaves a directory behind (components land in a .part
# directory that is moved into place only when the layer is complete).
set -euo pipefail

TAG="v5.1.2"
BASE="https://raw.githubusercontent.com/nvkelso/natural-earth-vector/$TAG"
DEST="$(cd "$(dirname "$0")/.." && pwd)/data/raw/naturalearth"

LAYERS=(
  "10m_cultural/ne_10m_admin_0_boundary_lines_land"
  "10m_cultural/ne_10m_admin_0_boundary_lines_maritime_indicator"
  "10m_cultural/ne_10m_admin_0_countries"
  "10m_cultural/ne_10m_admin_0_disputed_areas"
  "10m_physical/ne_10m_coastline"
  "10m_physical/ne_10m_lakes"
  "10m_physical/ne_10m_rivers_lake_centerlines"
)

REQUIRED=(shp shx dbf prj VERSION.txt)
OPTIONAL=(cpg README.html)  # not every layer ships these

mkdir -p "$DEST"
for layer in "${LAYERS[@]}"; do
  name="$(basename "$layer")"
  dir="$DEST/$name"
  if [ -d "$dir" ]; then
    echo "skip $name (exists)"
    continue
  fi
  echo "fetch $name @ $TAG"
  part="$dir.part"
  rm -rf "$part"
  mkdir -p "$part"
  for comp in "${REQUIRED[@]}"; do
    curl -fsSL --retry 5 "$BASE/$layer.$comp" -o "$part/$name.$comp"
  done
  for comp in "${OPTIONAL[@]}"; do
    code=$(curl -sSL --retry 5 -o "$part/$name.$comp" -w '%{http_code}' "$BASE/$layer.$comp")
    if [ "$code" = "404" ]; then
      rm -f "$part/$name.$comp"
    elif [ "$code" != "200" ]; then
      echo "error: HTTP $code on $name.$comp" >&2
      exit 1
    fi
  done
  mv "$part" "$dir"
done
echo "done: $DEST (pinned $TAG)"
