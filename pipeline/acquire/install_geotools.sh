#!/usr/bin/env bash
# Pinned install of the Phase 2 raster-tiling toolchain.
#
# Installs standalone binaries into ./tools and exposes them on PATH via
# ~/.local/bin wrappers. Deliberately does NOT use brew or touch the project
# .venv, so it runs identically on the dev desktop and inside the rohome
# container, and never perturbs a pipeline run that is using the venv.
#
# Idempotent: re-running skips work when the pinned version is already present.
#
#   Tools installed here:
#     pmtiles          package tiles into a single PMTiles v3 archive (serving);
#                      GDAL's PMTiles driver is vector-only, so this stays the one
#                      genuinely-mandatory new tool for raster tiles.
#
#   NOT vendored here:
#     GDAL 3.13.x      hillshade / color-relief / `gdal raster tile` — pinned via
#                      the official OSGeo GDAL container for the production run
#                      (apt on Ubuntu 26.04 tops out at 3.12.2).
#     sky-view factor  our own pipeline/render/sky_view.py — no external dep. WhiteboxTools
#                      was dropped (legacy); RVT (rvt-py) kept only as an optional
#                      one-off numeric oracle, never a pipeline dependency.
#     tippecanoe       Natural Earth borders -> vector tiles; a from-source build,
#                      added only when the vector-tile step lands.
set -euo pipefail

PMTILES_VERSION="1.31.0"   # protomaps/go-pmtiles — pinned versioned release asset

ARCH="$(uname -m)"
if [ "$ARCH" != "x86_64" ]; then
  echo "install_geotools.sh: only x86_64 is wired up (got $ARCH); edit the URLs." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TOOLS="$ROOT/tools"
BIN="$HOME/.local/bin"
mkdir -p "$TOOLS" "$BIN"

case ":$PATH:" in
  *":$BIN:"*) : ;;
  *) echo "note: $BIN is not on PATH — add it to your shell profile." >&2 ;;
esac

# ---- pmtiles (pinned github release) ----------------------------------------
if [ -x "$BIN/pmtiles" ] && pmtiles version 2>/dev/null | grep -q "$PMTILES_VERSION"; then
  echo "pmtiles $PMTILES_VERSION already installed"
else
  url="https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}/go-pmtiles_${PMTILES_VERSION}_Linux_x86_64.tar.gz"
  echo "downloading pmtiles $PMTILES_VERSION"
  curl -fsSL -o "$TOOLS/pmtiles.tar.gz" "$url"
  tar xzf "$TOOLS/pmtiles.tar.gz" -C "$TOOLS"
  install -m755 "$(find "$TOOLS" -maxdepth 2 -name pmtiles -type f | head -1)" "$BIN/pmtiles"
  rm -f "$TOOLS/pmtiles.tar.gz"
fi

# ---- verify -----------------------------------------------------------------
hash -r
echo "pmtiles: $(pmtiles version 2>/dev/null | head -1)"
