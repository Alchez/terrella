"""Fold the IAU gazetteer's outlines into canonical WGS84 GeoJSON — the named things on Mars.

The coordinates are DECLARED rather than transformed, for the reason `bodies.py` states once for the
whole pipeline — every projection here is Earth-sphered whatever planet it describes, and PROJ will
not build an operation between two celestial bodies.

WHAT IS SPECIFIC TO THIS FILE IS THAT DECLARING IS ONLY THE CURE WHILE THE SOURCE IS GEOGRAPHIC.
`download_sim3292` records the other half: `-a_srs`/`-s_srs` used INSTEAD of reprojecting is the
classic bug, and its failure is silent — a projected source read as degrees collapses to garbage
rather than raising. The gazetteer ships `ESRI:104905`, which is a GEOGCS, so its numbers are
already lon/lat and relabelling them is an identity. `assert_geographic_source` is what tells the
two apart, because nothing else here would: the flags look identical in both cases.

THE FOLD IS `-wrapdateline`, AND `RFC7946=YES` IS NOT A SUBSTITUTE EVEN THOUGH IT LOOKS LIKE ONE.
The source draws a feature crossing the prime meridian by continuing past the seam instead of
wrapping, so its outlines span -180..+360.34 while its centres are uniformly east-positive 0-360 —
the 540 degrees `download_nomenclature` pins. Both flags fold that onto one window and both keep all
1,717 features, but they do not agree: measured, `RFC7946=YES` alone emits **two
GeometryCollections**, which is precisely the container that cost Greenland its hover outline on
Earth, while `-wrapdateline` emits only Polygon and MultiPolygon. Both are passed — the second for
spec-compliant output — and `assert_folded` pins the result, so a GDAL release that reorders them
fails here rather than in a browser.

NO DOUGLAS-PEUCKER RUNS HERE, WHICH IS WHERE THIS PARTS COMPANY WITH ITS EARTH SIBLING.
`countries_geojson` simplifies because its output is a DISPLAY artifact the frontend fetches and
strokes directly, so its tolerance is argued against z8 relief. Nothing fetches this file: the
geometry a visitor sees arrives as vector tiles, and the names arrive as a search index. Its only
readers are `features_pmtiles` and this project. Simplifying here would permanently discard detail
the tile cut's own per-zoom knobs can spend or keep reversibly, so the only reduction applied is
coordinate QUANTISATION, which is not a vertex decision.

Outputs (data/work/mars/features/):
  features.geojson        1,717 named areal features, folded
  feature_lines.geojson   203 named linear features, folded
  feature_labels.geojson  1,920 label anchors at the IAU's own centres, folded
  features_params.json    the recipe: flags, precision, per-layer counts

    python -m pipeline.compose.features_geojson           # writes if missing
    python -m pipeline.compose.features_geojson --force   # regenerate
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from pipeline import bodies, freshness
from pipeline.acquire import download_nomenclature

OUT_DIR = bodies.work_dir(bodies.MARS, "features")

POLYGONS = OUT_DIR / "features.geojson"
LINES = OUT_DIR / "feature_lines.geojson"
LABELS = OUT_DIR / "feature_labels.geojson"

#: Which gazetteer layer lands in which file. `labels` is derived from both and has no source of
#: its own, so it is deliberately absent here.
GEOMETRY_OUTPUTS = {"poly": POLYGONS, "line": LINES}

#: What every layer carries into the tiles. `name` first, because it is the identity every derived
#: layer is keyed on — see `vector_layers.carried`.
#:
#: `origin` is the IAU's etymology and it is the whole content of Mars's detail card, so it rides
#: into the tiles rather than being looked up: measured, the full catalogue WITH origin cuts a 71.8
#: KB z0 tile, under Earth's own 86 KB, and a tap that needs no second fetch is worth more than the
#: bytes. THE CENTRES ARE NOT HERE ON PURPOSE — they are east-positive 0-360 in the source, and a
#: folded geometry carrying an unfolded longitude property is the mixed-convention bug this module
#: exists to end. They reach `feature_labels.geojson` as geometry, folded, and nothing else.
CARRIED_FIELDS = ("name", "clean_name", "type", "origin", "diameter")

#: Decimal places of longitude/latitude in the written GeoJSON. 1e-4 deg is 5.9 m on Mars, against
#: a z7 tile pixel of 325.6 ground m — 55x finer than the sharpest pixel the pyramid will ever
#: address, so this cannot be seen. It is a quantisation and not a simplification: it moves vertices
#: without deciding which ones survive, which is the distinction the module note draws.
COORDINATE_PRECISION = 4


def fold_longitude(east_positive: float) -> float:
    """An east-positive 0-360 longitude onto the -180..180 window the geometry is folded into.

    The source's centres are uniformly east-positive while its outlines are not, so this is applied
    to the CENTRES alone; the geometry's fold is `-wrapdateline`'s job and is a different operation
    — it must also SPLIT the features that straddle the seam, which a scalar cannot.
    """
    return east_positive - 360.0 if east_positive > 180.0 else east_positive


def assert_geographic_source(layer: str) -> None:
    """Refuse a source whose `.prj` is PROJECTED, because relabelling one is not the same operation.

    THE FLAGS CANNOT TELL THE TWO APART AND NEITHER CAN A REVIEWER. `-s_srs EPSG:4326` over a
    geographic Mars CRS is an identity on the numbers — the cure. The same flag over a PROJECTED
    Mars CRS reads metres as degrees, which does not raise: it produces coordinates a few hundred
    metres from the prime meridian and a tiler that quietly emits almost nothing. SIM 3292 ships
    exactly that shape, Robinson on the Mars sphere in metres, so the hazard is not hypothetical —
    it is one directory away, and this module would accept it in silence.
    """
    projection = download_nomenclature.layer_path(layer, "prj")
    if not projection.exists():
        sys.exit(f"{projection.name} is missing — without it nothing here can tell a geographic "
                 f"source from a projected one, and the two need opposite treatment.")
    declared = projection.read_text(encoding="utf-8", errors="replace").lstrip()
    if not declared.startswith("GEOGCS"):
        sys.exit(f"{projection.name} does not declare a GEOGCS — this module DECLARES its source's "
                 f"angles as EPSG:4326, which is an identity only while they are already lon/lat. "
                 f"A projected source has to be reprojected to longlat FIRST; declaring it instead "
                 f"reads metres as degrees and fails silently. Got: {declared[:80]!r}")


def ogr_command(source: Path, destination: Path) -> list[str]:
    """The translation, exposed pure for tests. Argument order is [options] DESTINATION SOURCE."""
    return [
        "ogr2ogr", "-f", "GeoJSON",
        "-select", ",".join(CARRIED_FIELDS),
        # Declare, never transform — the module note holds the celestial-body refusal this avoids.
        "-s_srs", "EPSG:4326", "-t_srs", "EPSG:4326",
        "-wrapdateline",
        "-lco", "RFC7946=YES",
        "-lco", f"COORDINATE_PRECISION={COORDINATE_PRECISION}",
        str(destination), str(source),
    ]


def vertices_of(geometry: dict[str, Any]) -> list[list[float]]:
    """Every coordinate pair in a geometry, at whatever nesting depth its type implies."""
    found: list[list[float]] = []
    pending: list[Any] = [geometry["coordinates"]]
    while pending:
        item = pending.pop()
        if item and isinstance(item[0], (int, float)):
            found.append(item)
        else:
            pending.extend(item)
    return found


def assert_folded(path: Path, expected: int) -> None:
    """Assert a written layer is folded, whole, and free of the container that hides polygons.

    THREE THINGS THAT FAIL SEPARATELY. A short count means the translation dropped features; a
    vertex outside the window means the fold did not run, and every feature crossing the seam will
    be clipped away by the tiler without an error; a GeometryCollection means GDAL folded via
    RFC 7946 rather than `-wrapdateline`, and `polygon_parts_of` is the only thing standing between
    that and a layer of invisible features — which on Earth it once was not.
    """
    collection = json.loads(path.read_text(encoding="utf-8"))
    features = collection["features"]
    if len(features) != expected:
        sys.exit(f"{path.name}: {len(features)} features, expected {expected} — the translation "
                 f"dropped some. Every coverage figure on record describes the whole catalogue.")

    containers = sorted({feature["geometry"]["type"] for feature in features
                         if feature.get("geometry")})
    if "GeometryCollection" in containers:
        sys.exit(f"{path.name}: GDAL emitted GeometryCollection geometries. That is the RFC 7946 "
                 f"fold rather than -wrapdateline's, and it is the exact shape that left Greenland "
                 f"with no outline on Earth. Check the flag order in `ogr_command`.")

    for feature in features:
        if not feature.get("geometry"):
            continue
        for longitude, latitude in (point[:2] for point in vertices_of(feature["geometry"])):
            if not (-180.0001 <= longitude <= 180.0001 and -90.0001 <= latitude <= 90.0001):
                sys.exit(f"{path.name}: {feature['properties'].get('name')!r} has a vertex at "
                         f"{longitude}, {latitude} — outside the tile grid's window, so the fold "
                         f"did not run and the tiler will silently clip this feature away.")


def label_points() -> dict[str, Any]:
    """One point per named feature, at the IAU's own centre, from BOTH layers.

    THE PUBLISHER'S ANCHOR RATHER THAN A COMPUTED CENTROID. A centroid falls outside a crescent and
    has to be bought with a geometry library; more to the point, the gazetteer's centre is the
    position the IAU adopted the name AT, which is what a label should sit on. It also gives the
    203 linear features an anchor they have no interior to supply.

    Read through `download_nomenclature.read_attributes`, so "how this DBF is decoded" keeps one
    owner — the encoding it fixes is the whole reason that function refuses to use `text=True`.
    """
    features: list[dict[str, Any]] = []
    for layer in download_nomenclature.LAYERS:
        for row in download_nomenclature.read_attributes(layer):
            properties = {key: row[key] for key in CARRIED_FIELDS if row.get(key)}
            if "name" not in properties:
                continue
            features.append({
                "type": "Feature",
                "properties": properties,
                "geometry": {"type": "Point", "coordinates": [
                    round(fold_longitude(float(row["center_lon"])), COORDINATE_PRECISION),
                    round(float(row["center_lat"]), COORDINATE_PRECISION),
                ]},
            })
    return {"type": "FeatureCollection", "features": features}


def recipe() -> dict[str, Any]:
    """What this fold was made with, recorded beside it — the flags leave no trace in the output."""
    return {
        "source": {layer: download_nomenclature.layer_path(layer).name
                   for layer in download_nomenclature.LAYERS},
        "carried_fields": list(CARRIED_FIELDS),
        "coordinate_precision": COORDINATE_PRECISION,
        "fold": "-wrapdateline",
        "srs": "declared EPSG:4326, not transformed from ESRI:104905",
        "features": dict(download_nomenclature.FEATURE_COUNTS),
        "simplified": False,
    }


def recipe_path() -> Path:
    return OUT_DIR / "features_params.json"


def is_fresh() -> bool:
    """True when every output is present, newer than its source, and cut under the recipe on disk.

    The recipe half is what catches a flag change, which moves no mtime and leaves no mark on the
    geometry a reader would notice.

    THE SOURCE MTIME COMES FROM `freshness.newest_mtime`, which scores a missing path 0.0. The
    hand-rolled `max(... if ... .exists())` it replaces raised `ValueError` on an empty sequence
    instead — so on a machine where the gazetteer is not acquired, asking whether the outputs could
    be skipped crashed rather than answering.
    """
    newest_source = freshness.newest_mtime(
        *(download_nomenclature.layer_path(layer) for layer in download_nomenclature.LAYERS))
    for path in (*GEOMETRY_OUTPUTS.values(), LABELS):
        if not path.exists() or path.stat().st_size == 0:
            return False
        if path.stat().st_mtime <= newest_source:
            return False
    return freshness.recorded_json(recipe_path()) == recipe()


def translate(force: bool) -> None:
    """Fold each gazetteer layer, then derive the label anchors from both."""
    if is_fresh() and not force:
        print("features are current -> skip (use --force to regenerate)")
        return

    for layer, destination in GEOMETRY_OUTPUTS.items():
        source = download_nomenclature.layer_path(layer)
        if not source.exists():
            sys.exit(f"missing {source} — run pipeline.acquire.download_nomenclature first")
        assert_geographic_source(layer)
        temporary = destination.with_suffix(".geojson.tmp")
        temporary.unlink(missing_ok=True)
        command = ogr_command(source, temporary)
        print(" ".join(command), flush=True)
        subprocess.run(command, check=True)
        assert_folded(temporary, download_nomenclature.FEATURE_COUNTS[layer])
        temporary.replace(destination)  # atomic promote, and only after the assertions
        print(f"wrote {destination} ({destination.stat().st_size / 1e6:.2f} MB)")

    anchors = label_points()
    temporary = LABELS.with_suffix(".geojson.tmp")
    temporary.write_text(json.dumps(anchors), encoding="utf-8")
    temporary.replace(LABELS)
    print(f"wrote {LABELS} ({len(anchors['features'])} anchors, "
          f"{LABELS.stat().st_size / 1e6:.2f} MB)")

    recipe_path().write_text(json.dumps(recipe(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {recipe_path()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--force", action="store_true", help="regenerate even if present")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    translate(args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
