"""Cut the country polygons into a VECTOR tile pyramid (PMTiles), so the globe addresses
country geometry by z/x/y instead of handing MapLibre a 9.4 MB parsed object.

WHY THIS EXISTS — IT IS A MAIN-THREAD FIX, NOT A PAYLOAD ONE
------------------------------------------------------------
`GeoJSONSource._getLoadGeoJSONParameters` branches on the type of `data`. A URL becomes a worker
request and the worker does the fetch, the parse, the tiling and the tessellation. An OBJECT goes
through `Actor.sendAsync`, which deep-rebuilds it in `serialize()` and then structured-clones the
rebuilt copy — two full walks of 413,141 vertices, on the main thread. Measured A/B/A/B on the
live globe: the worst long task of the session, **358 ms, disappears** (max long task 358 -> 83 ms,
total blocking 421 -> 217 ms). Tessellation was the wrong suspect and never ran on the main thread
at all: `earcut` appears zero times in MapLibre's main bundle.

The payload win rides along: per-zoom simplification takes the cold window from 2.51 MB gzip — the
single largest item, bigger than all 36 relief tiles combined — to roughly 100-250 KB.

WHY THREE LAYERS AND NOT ONE
----------------------------
`country_outline` carries the rings as LINES rather than letting a `line` layer stroke the
polygons. Clipping a line trims it; clipping a polygon closes the ring along the cut and a `line`
layer strokes that phantom edge — the stray gold meridian this project already fixed once at
runtime. `country_hit` carries one fat invisible target per polygon part, because a 176-atoll
archipelago cannot be pointed at via its real geometry at any zoom.

THE SIMPLIFICATION KNOBS ARE TWO, AND THAT IS THE WHOLE POINT
------------------------------------------------------------
`countries.geojson` is 9.4 MB because its Douglas-Peucker budget is set by DISPLAY: the hover
outline is judged against the raster coastline at z8, so the error must stay sub-pixel there (see
countries_geojson.py). A single simplification factor would trade that fidelity away to make the
overview cheap. `SIMPLIFICATION` and `SIMPLIFICATION_MAX_ZOOM` are separate, and measured: z8 comes
out **byte-identical (395 B) at every setting** while z0 falls 246 -> 86 KB gzip across the range.
So overview weight is tunable without touching the thing the file exists to protect.

GDAL SIMPLIFIES NOTHING BY DEFAULT — that is not a safe default here, it is a 4.3x regression
against what a tolerance-3 tiler produces, and it is invisible unless the tiles are weighed.

The archive carries ALL countries, not just the rendered ones. Scope is a runtime layer filter
(`inScopeFilter` in earth.astro) applied to all four country layers, so a newly rendered hero does
not require re-cutting tiles, and "which countries are interactive" stays single-homed in the
manifest instead of being split across a build step and a filter.

    python -m pipeline.compose.countries_pmtiles           # writes if missing/stale
    python -m pipeline.compose.countries_pmtiles --force   # re-cut
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from pipeline import bodies, freshness, paths
from pipeline.compose import vector_layers
from pipeline.compose.vector_layers import polygon_parts_of

#: What this cut carries into its derived layers. One key, and it is the join key: the frontend
#: matches it against countries.json by name. See `vector_layers.carried` for why the first is the
#: identity.
CARRIED = ("ADMIN",)

#: The CHECKOUT, not the data store, and it is read for exactly one thing: the frontend constant
#: this module's max zoom is pinned against. Kept because `web/src/` follows the repo wherever the
#: data store goes — the two roots are different seams.
ROOT = paths.ROOT
#: What `borders_geojson` and `countries_geojson` write — the same directory, named the same way,
#: so a writer and its reader cannot drift apart by one editing its own copy of the path.
BORDERS = bodies.work_dir(bodies.EARTH, "borders")
#: One stage name per LAYER, under each body's own prefix — the convention `devStores.archivePath`
#: rests on, so Earth's vector cut and Mars's land in directories that differ only by planet.
OUT_DIR = bodies.work_dir(bodies.EARTH, "planet_vector")

SRC = BORDERS / "countries.geojson"
OUTLINES = BORDERS / "country_outlines.geojson"
HITS = BORDERS / "country_hits.geojson"
#: What the two files above were derived UNDER. Beside them rather than beside the archive, because
#: it answers for the derivation and the archive has its own.
OUTLINES_RECIPE = BORDERS / "country_outlines_params.json"
STAGED = OUT_DIR / "countries_staged.gpkg"
OUT = OUT_DIR / "vector.pmtiles"

# Layer names inside the archive. The frontend reads these as MapLibre `source-layer` values, and
# `tests/test_source_layers.py` compares them against web/src/lib/sourceLayers.ts on every suite.
FILL_LAYER = "country_fill"
OUTLINE_LAYER = "country_outline"
HIT_LAYER = "country_hit"

MIN_ZOOM = 0
# Matches the relief pyramid's ceiling. Not a coincidence and not free to lower: the hover outline
# is judged against z8 relief, so the vector detail has to reach where the raster does.
MAX_ZOOM = 8

# Tile-space units, of EXTENT below. Chosen at the knee of the measured sweep: z0 gzip falls
# 246 -> 108 KB going from none to 2, and only 108 -> 86 going on to 4, while mid-zoom coastlines
# visibly coarsen. Re-cut and re-judge rather than guessing — the recipe sidecar records it.
SIMPLIFICATION = 2.0
# Deliberately far below SIMPLIFICATION: the top zoom is the one the outline is judged at.
SIMPLIFICATION_MAX_ZOOM = 0.5

# `buffer: 0` is load-bearing and is the same decision the GeoJSON source made at runtime — the
# translucent fill wash double-paints in the default tile-buffer overlap, worst near the pole.
# Baked here because a vector source cannot set it at runtime.
BUFFER = 0
EXTENT = vector_layers.EXTENT


def outlines_from(countries: dict[str, Any]) -> dict[str, Any]:
    """Country rings re-expressed as boundary LINES — outer coasts and inner holes alike."""
    return vector_layers.outlines_from(countries, CARRIED)


def hit_points_from(countries: dict[str, Any]) -> dict[str, Any]:
    """One point per polygon PART, at its bounding-box centre.

    The bbox centre, not a centroid: this is a pointing target, not a label anchor, and the circle
    radius around it IS the hit tolerance. A centroid would cost a geometry library for a number
    that is then swallowed by a 12 px radius.
    """
    features: list[dict[str, Any]] = []
    for feature in countries["features"]:
        admin = feature["properties"].get("ADMIN")
        if not isinstance(admin, str):
            continue
        for part in polygon_parts_of(feature["geometry"]):
            outer_ring = part[0]
            longitudes = [point[0] for point in outer_ring]
            latitudes = [point[1] for point in outer_ring]
            features.append({
                "type": "Feature",
                "properties": {"ADMIN": admin},
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        (min(longitudes) + max(longitudes)) / 2,
                        (min(latitudes) + max(latitudes)) / 2,
                    ],
                },
            })
    return {"type": "FeatureCollection", "features": features}


def stage_command(source: Path, destination: Path, layer: str, update: bool) -> list[str]:
    """One layer into the staging GeoPackage. See `vector_layers.stage_command` for why it exists."""
    return vector_layers.stage_command(source, destination, layer, update)


def pmtiles_command(source: Path, destination: Path) -> list[str]:
    """The single conversion, exposed pure for tests. Argument order is [options] DEST SOURCE."""
    return vector_layers.pmtiles_command(
        source, destination,
        name="countries",
        min_zoom=MIN_ZOOM,
        max_zoom=MAX_ZOOM,
        buffer=BUFFER,
        simplification=SIMPLIFICATION,
        simplification_max_zoom=SIMPLIFICATION_MAX_ZOOM,
    )


def recipe() -> dict[str, Any]:
    """What this cut was made with, recorded beside it.

    The archive's own name carries none of this, so without a sidecar a SIMPLIFICATION change is
    invisible to every guard and to anyone reading the store — the same reason terrain_rgb.py
    writes `terrain_params.json`.
    """
    return {
        "source": SRC.name,
        "layers": [FILL_LAYER, OUTLINE_LAYER, HIT_LAYER],
        "min_zoom": MIN_ZOOM,
        "max_zoom": MAX_ZOOM,
        "simplification": SIMPLIFICATION,
        "simplification_max_zoom": SIMPLIFICATION_MAX_ZOOM,
        "buffer": BUFFER,
        "extent": EXTENT,
        **vector_layers.seam_recipe(),
    }


def recipe_path() -> Path:
    return OUT_DIR / "countries_tiles_params.json"


def derivation_is_stamped() -> bool:
    """True when the derived layers on disk were written under the seam settings in force now.

    Its own question, asked in two places: `derive` decides whether to rewrite the GeoJSON, and
    `is_fresh` decides whether the archive above it can still be believed. Answering it in only the
    first is what let a stale derivation hide behind a fresh archive — `main` returns on `is_fresh`
    and never reaches `derive` at all.
    """
    return freshness.recorded_json(OUTLINES_RECIPE) == vector_layers.seam_recipe()


def is_fresh() -> bool:
    """True when the live archive is current: present, non-empty, stamped newer than the source it
    descends from and the layers derived from it, and cut under both recipes on disk.

    The recipe comparison is the half that catches a settings change — a re-cut with a different
    SIMPLIFICATION leaves an archive that is newer than its source and would otherwise pass. THE
    DERIVATION'S RECIPE IS THE OTHER HALF, and it is not the same question: this module's knobs
    move the cut, `vector_layers`' knobs move the geometry that is cut, and an archive can be
    current under the first while its outlines were drawn under the second's previous answer.
    """
    if not OUT.exists() or OUT.stat().st_size == 0:
        return False
    for path in (SRC, OUTLINES, HITS):
        if not path.exists() or OUT.stat().st_mtime <= path.stat().st_mtime:
            return False
    if not derivation_is_stamped():
        return False
    return freshness.recorded_json(recipe_path()) == recipe()


def derive(force: bool) -> None:
    """Write the two derived layers beside their source, skipping when already current.

    THE RECIPE IS CHECKED HERE AND NOT ONLY AT THE CUT, because this is the stage `vector_layers`
    writes through. Gating only on the source's mtime made a change to shared code unobservable:
    the source does not move when that module's constants do, so the derivation skipped, the cut
    re-ran on the stale GeoJSON it had always had, produced a byte-identical archive, and stamped
    the NEW recipe over it — consuming the one signal that anything was out of date. A producer
    records its recipe beside its output; these two files had none.
    """
    fresh = (
        not force
        and OUTLINES.exists()
        and HITS.exists()
        and min(OUTLINES.stat().st_mtime, HITS.stat().st_mtime) > SRC.stat().st_mtime
        and derivation_is_stamped()
    )
    if fresh:
        print(f"{OUTLINES.name} + {HITS.name} current -> skip")
        return
    countries = json.loads(SRC.read_text())
    for path, collection in ((OUTLINES, outlines_from(countries)), (HITS, hit_points_from(countries))):
        temporary = path.with_suffix(".geojson.tmp")
        temporary.write_text(json.dumps(collection))
        temporary.replace(path)  # atomic promote
        print(f"wrote {path.name} ({len(collection['features'])} features, "
              f"{path.stat().st_size / 1e6:.2f} MB)")
    # Stamped AFTER both files exist, so a crash between them leaves the derivation stale rather
    # than vouched for — the same order every other stage in this pipeline writes its marker in.
    OUTLINES_RECIPE.write_text(json.dumps(vector_layers.seam_recipe(), indent=2) + "\n")


def stage() -> None:
    """All three layers into one GeoPackage — see stage_command for why this step exists."""
    STAGED.unlink(missing_ok=True)
    for index, (source, layer) in enumerate(
        ((SRC, FILL_LAYER), (OUTLINES, OUTLINE_LAYER), (HITS, HIT_LAYER))
    ):
        command = stage_command(source, STAGED, layer, update=index > 0)
        print(" ".join(command), flush=True)
        subprocess.run(command, check=True)


def cut() -> None:
    temporary = OUT.with_suffix(".pmtiles.tmp")
    temporary.unlink(missing_ok=True)
    command = pmtiles_command(STAGED, temporary)
    print(" ".join(command), flush=True)
    subprocess.run(command, check=True)
    temporary.replace(OUT)  # atomic promote
    recipe_path().write_text(json.dumps(recipe(), indent=2) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-cut even if current")
    args = parser.parse_args()

    if not SRC.exists():
        sys.exit(f"missing {SRC} — run pipeline.compose.countries_geojson first")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if is_fresh() and not args.force:
        print(f"{OUT.name} is current -> skip (use --force to re-cut)")
        return 0

    derive(args.force)
    stage()
    cut()
    STAGED.unlink(missing_ok=True)  # a 30 MB intermediate with no reader once the archive exists
    return 0


if __name__ == "__main__":
    sys.exit(main())
