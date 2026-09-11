#!/usr/bin/env bash
# Pinned download of the raster-tiling toolchain.
#
# NOTHING HERE IS VENDORED. `tools/` is gitignored, so this fetches a pinned
# upstream release at setup time rather than checking a binary into the repo.
# Deliberately does NOT use brew or touch the project .venv, so it runs
# identically on any machine or container that runs the pipeline, and never
# perturbs a pipeline run that is using the venv.
#
# Idempotent: re-running skips work when the pinned version is already present.
#
#   Downloaded here:
#     pmtiles          package tiles into a single PMTiles v3 archive (serving);
#                      GDAL's PMTiles driver is vector-only, so this stays the one
#                      genuinely-mandatory new tool for raster tiles.
#
#   NOT downloaded here:
#     GDAL 3.13.x      hillshade / color-relief / `gdal raster tile` — pinned via
#                      the official OSGeo GDAL container for the production run
#                      (apt on Ubuntu 26.04 tops out at 3.12.2).
#     sky-view factor  our own pipeline/look/sky_view.py — no external dep. WhiteboxTools
#                      was dropped (legacy); RVT (rvt-py) kept only as an optional
#                      one-off numeric oracle, never a pipeline dependency.
#     tippecanoe       Natural Earth borders -> vector tiles; a from-source build,
#                      added only when the vector-tile step lands.
set -euo pipefail

PMTILES_VERSION="1.31.0"   # protomaps/go-pmtiles — pinned versioned release asset

# Upstream publishes no checksum file with the release, so the digest is pinned here: recorded
# once from the asset we accepted, and checked on every download after. Bumping the version means
# recording the new one, which is the point at which someone looks at what changed.
PMTILES_SHA256="e80bf5716f45b5330bc1e3037e12f254da89fce23c58b611897fe4a413aee635"

ARCH="$(uname -m)"
if [ "$ARCH" != "x86_64" ]; then
  echo "install_geotools.sh: only x86_64 is wired up (got $ARCH); upstream also ships Linux_arm64." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TOOLS="$ROOT/tools"
mkdir -p "$TOOLS"

# ---- pmtiles (pinned github release) ----------------------------------------
# One copy, under `tools/`, which is where `paths.PMTILES` looks and the only place any consumer
# reads it from. An earlier version also copied it onto PATH, leaving two 57 MB binaries of which
# only this one was ever used.
if [ -x "$TOOLS/pmtiles" ] && "$TOOLS/pmtiles" version 2>/dev/null | grep -q "$PMTILES_VERSION"; then
  echo "pmtiles $PMTILES_VERSION already installed"
else
  url="https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}/go-pmtiles_${PMTILES_VERSION}_Linux_x86_64.tar.gz"
  echo "downloading pmtiles $PMTILES_VERSION"
  tarball="$TOOLS/pmtiles.tar.gz"
  # The identity every acquisition sends, spelled here because bash cannot import `pipeline.fetch`
  # and curl's default agent is as anonymous as urllib's. `test_fetch.py` reads the constant and
  # this file, so a bump there goes red rather than leaving one requester behind.
  curl -fsSL -A "terrella-pipeline/1.0" -o "$tarball" "$url"

  got="$(sha256sum "$tarball" | cut -d' ' -f1)"
  if [ "$got" != "$PMTILES_SHA256" ]; then
    rm -f "$tarball"
    echo "install_geotools.sh: checksum mismatch for $url" >&2
    echo "  expected $PMTILES_SHA256" >&2
    echo "  got      $got" >&2
    exit 1
  fi

  # Unpacked into a temp dir rather than straight into tools/, because the tarball also carries a
  # LICENSE and a README and this directory holds exactly what a consumer resolves.
  unpack="$(mktemp -d "$TOOLS/.unpack.XXXXXX")"
  trap 'rm -rf "$unpack" "$tarball"' EXIT
  tar xzf "$tarball" -C "$unpack"
  install -m755 "$(find "$unpack" -maxdepth 2 -name pmtiles -type f | head -1)" "$TOOLS/pmtiles.new"
  mv -f "$TOOLS/pmtiles.new" "$TOOLS/pmtiles"
fi

# ---- verify -----------------------------------------------------------------
echo "pmtiles: $("$TOOLS/pmtiles" version 2>/dev/null | head -1)"
