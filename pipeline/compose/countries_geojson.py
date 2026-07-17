#!/usr/bin/env python3
"""Simplify the Natural Earth admin-0 country POLYGONS -> one WGS84 GeoJSON for
the globe's click-to-fly-to hit layer (an invisible MapLibre fill the click
handler queries; also drives the hover tint).

This is *not* a display layer — the visible coastline is the baked raster tile.
The polygons exist only so a click on the sphere resolves to a country, so we
simplify hard (Douglas-Peucker at ~SIMPLIFY_DEG) to trade coastline fidelity for
a small file: the full shapefile is ~8.8 MB, useless to ship when a few hundred
KB hit-tests identically. We carry only ADMIN — the frontend joins it to
countries.json by name (gen_manifest sets name = resolve()["admin"]) and gates
interactivity to in-scope names with a layer filter.

Same format-translation shape as borders_geojson.py (a pure EPSG:4326 -> GeoJSON
pass, no reprojection); output is gitignored under data/, served at /borders/.

    python pipeline/compose/countries_geojson.py            # writes if missing
    python pipeline/compose/countries_geojson.py --force    # regenerate
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path.home() / "projects/maps"
NE = ROOT / "data/raw/naturalearth"
OUT_DIR = ROOT / "data/work/borders"

SRC = NE / "ne_10m_admin_0_countries" / "ne_10m_admin_0_countries.shp"
OUT = OUT_DIR / "countries.geojson"

# Douglas-Peucker tolerance in degrees (~1 km at the equator). Coarse enough to
# shrink the file an order of magnitude, fine enough that a click near a coast
# still lands in the right polygon. Neighbour gaps this introduces are invisible
# (the layer is transparent) and only ever cost a hover flicker at a border.
SIMPLIFY_DEG = 0.05


def translate(force: bool):
    if not SRC.exists():
        sys.exit(f"missing Natural Earth source: {SRC}")
    if OUT.exists() and not force:
        print(f"{OUT.name} exists -> skip (use --force to regenerate)")
        return
    tmp = OUT.with_suffix(".geojson.tmp")
    tmp.unlink(missing_ok=True)
    cmd = [
        "ogr2ogr", "-f", "GeoJSON",
        "-select", "ADMIN",  # only the join key — no CONTINENT/ISO/etc.
        "-simplify", str(SIMPLIFY_DEG),  # Douglas-Peucker; the whole point
        "-lco", "RFC7946=YES",  # standards-compliant WGS84 lon/lat GeoJSON
        "-lco", "COORDINATE_PRECISION=4",  # ~10 m; ample for a hit layer
        str(tmp), str(SRC),
    ]
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    tmp.replace(OUT)  # atomic promote
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="regenerate even if present")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    translate(args.force)


if __name__ == "__main__":
    sys.exit(main())
