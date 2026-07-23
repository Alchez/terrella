#!/usr/bin/env python3
"""Convert the Natural Earth admin-0 land boundary LINES -> one WGS84 GeoJSON for
the globe's vector border overlay (solid international + dashed disputed/LoC, split
downstream by FEATURECLA).

The per-country border PNGs (compose/gen_borders.py) are baked into each hero's
Albers camera and cannot drape on the MapLibre globe, so the globe needs live vector
geometry MapLibre re-projects client-side. Natural Earth ships both layers as
EPSG:4326 shapefiles, so this is a pure *format* translation -- not a reprojection.

We carry only FEATURECLA (the frontend styles/splits on it), round coordinates to
~1 m, and let MapLibre thin further per-zoom via the source `tolerance`. Output is
gitignored (under data/); served at /borders/ the same way tiles and heroes are.

    python pipeline/compose/borders_geojson.py            # writes missing files
    python pipeline/compose/borders_geojson.py --force    # regenerate all
"""

import argparse
import subprocess
import sys
from pathlib import Path

from pipeline import paths

ROOT = paths.ROOT
NE = ROOT / "data/raw/naturalearth"
OUT_DIR = ROOT / "data/work/borders"

# Land classes the hero style renders (compose/overlay_borders.py); the rest is
# cartographic scaffolding we drop.
LAND_DROP = ("Overlay limit", "Lease limit", "Unrecognized")

LAYERS = [
    {
        "name": "boundary_lines.geojson",
        "src": NE / "ne_10m_admin_0_boundary_lines_land" / "ne_10m_admin_0_boundary_lines_land.shp",
        "where": "FEATURECLA NOT IN ('" + "', '".join(LAND_DROP) + "')",
    },
]


def translate(src: Path, out: Path, where, force: bool):
    if not src.exists():
        sys.exit(f"missing Natural Earth source: {src}")
    if out.exists() and not force:
        print(f"{out.name} exists -> skip (use --force to regenerate)")
        return
    tmp = out.with_suffix(".geojson.tmp")
    tmp.unlink(missing_ok=True)
    cmd = ["ogr2ogr", "-f", "GeoJSON"]
    if where:
        cmd += ["-where", where]  # drop non-rendered classes at the source
    cmd += [
        "-select", "FEATURECLA",  # carry only the class attribute (shrinks file)
        "-lco", "RFC7946=YES",  # standards-compliant WGS84 lon/lat GeoJSON
        "-lco", "COORDINATE_PRECISION=5",  # ~1 m; sub-pixel at our z8 ceiling
        str(tmp), str(src),
    ]
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    tmp.replace(out)  # atomic promote
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="regenerate even if present")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for layer in LAYERS:
        translate(layer["src"], OUT_DIR / layer["name"], layer["where"], args.force)


if __name__ == "__main__":
    sys.exit(main())
