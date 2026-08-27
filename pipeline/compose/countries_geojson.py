"""Simplify the Natural Earth admin-0 country POLYGONS -> one WGS84 GeoJSON
shared by ALL of the globe's country layers: the click-to-fly hit fill, the
hover wash, and the hover outline that strokes these very rings as the visible
gold line (web/src/lib/countryHighlight.ts).

That last consumer makes this a DISPLAY layer, and it sets the simplification
budget: the outline is judged against the raster coastline it traces, so the
Douglas-Peucker error must stay under one pixel of the sharpest tiles (z8) —
not merely "small enough to hit-test". The file began life as a pure hit layer
at 0.05 deg (~5.5 km) on the premise the geometry would never be seen; the
hover outline invalidated that silently, and at z8 the chords cut ~18 px
straight across bays (the blocky-coast report). Fidelity costs real
bytes — 9.2 MB raw / 2.5 MB gzipped vs 1.5 / 0.4 at the old tolerance, measured —
but the fetch is async behind first paint and cached, so the
display requirement wins. We carry only ADMIN — the frontend joins it to
countries.json by name (gen_manifest sets name = resolve()["admin"]) and gates
interactivity to in-scope names with a layer filter.

Same format-translation shape as borders_geojson.py (a pure EPSG:4326 -> GeoJSON
pass, no reprojection); output is gitignored under data/, served at /borders/.

    python -m pipeline.compose.countries_geojson            # writes if missing
    python -m pipeline.compose.countries_geojson --force    # regenerate
"""

import argparse
import subprocess
import sys
from pathlib import Path

from pipeline import naturalearth
from pipeline.compose import countries_pmtiles

SRC = naturalearth.layer("ne_10m_admin_0_countries")

# Douglas-Peucker tolerance in degrees. 0.002 deg ~= 220 m ~= 0.7 px at z8 on
# the equator (Earth's grid pixel, ~305.75 m/px) — sub-pixel where the raster
# is sharpest, so the hover outline tracks the coast it traces. N-S error grows
# toward the poles in Mercator pixels (~3 px at 75N: latitude degrees don't
# shrink with cos(lat) but Mercator pixels do) — accepted; buying it back costs
# ~1 MB more gzip for fjord vertices only a Svalbard hover would notice.
# Pinned relationally in tests/test_countries_geojson.py against EARTH's grid pixel — Earth's
# specifically, because this pyramid is Earth-only and the tolerance is justified against the
# raster it overlays, not against whatever the sharpest body in the registry cuts to.
SIMPLIFY_DEG = 0.002


def ogr_command(source: Path, destination: Path) -> list[str]:
    """The ogr2ogr invocation, exposed pure for tests. Argument order is
    [options] DESTINATION SOURCE — ogr2ogr's convention, pinned by test."""
    return [
        "ogr2ogr", "-f", "GeoJSON",
        "-select", "ADMIN",  # only the join key — no CONTINENT/ISO/etc.
        "-simplify", str(SIMPLIFY_DEG),  # Douglas-Peucker; budget above
        "-lco", "RFC7946=YES",  # standards-compliant WGS84 lon/lat GeoJSON
        "-lco", "COORDINATE_PRECISION=4",  # ~11 m; an order under the simplify floor
        str(destination), str(source),
    ]


def translate(force: bool):
    """THE DESTINATION IS ASKED FOR RATHER THAN SPELLED, and it is `countries_pmtiles`' own
    `source_path` because the reader of this file is the one stage that must never disagree with
    the writer about where it is."""
    out = countries_pmtiles.source_path()
    if not SRC.exists():
        sys.exit(f"missing Natural Earth source: {SRC}")
    if out.exists() and not force:
        print(f"{out.name} exists -> skip (use --force to regenerate)")
        return
    tmp = out.with_suffix(".geojson.tmp")
    tmp.unlink(missing_ok=True)
    cmd = ogr_command(SRC, tmp)
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    tmp.replace(out)  # atomic promote
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="regenerate even if present")
    args = parser.parse_args()
    countries_pmtiles.borders_dir().mkdir(parents=True, exist_ok=True)
    translate(args.force)


if __name__ == "__main__":
    sys.exit(main())
