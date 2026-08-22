"""Cut the country polygons into a VECTOR tile pyramid (PMTiles), so the globe addresses
country geometry by z/x/y instead of handing MapLibre a 9.4 MB parsed object.

Earth's declaration; `vector_cut` runs it. What is here is what is Earth's — the three layers, the
knobs, the two files this stage derives — and nothing about how a cut is performed.

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
(`inScopeFilter` in Globe.astro) applied to all four country layers, so a newly rendered hero does
not require re-cutting tiles, and "which countries are interactive" stays single-homed in the
manifest instead of being split across a build step and a filter.

    python -m pipeline.compose.countries_pmtiles           # writes if missing/stale
    python -m pipeline.compose.countries_pmtiles --force   # re-cut
"""

import json
import sys
from pathlib import Path
from typing import Any

from pipeline import bodies
from pipeline.compose import vector_layers
from pipeline.compose.vector_cut import VectorCut, run
from pipeline.compose.vector_layers import polygon_parts_of

#: What this cut carries into its derived layers. One key, and it is the join key: the frontend
#: matches it against countries.json by name. See `vector_layers.carried` for why the first is the
#: identity.
CARRIED = ("ADMIN",)


def borders_dir() -> Path:
    """What `borders_geojson` and `countries_geojson` write — the same directory, named the same
    way, so a writer and its reader cannot drift apart by one editing its own copy of the path.

    CALL TIME, WHICH IS THE RULE `paths.py` STATES FOR THE WHOLE PACKAGE and the reason every path
    on `VectorCut` is a callable: a module-level `BORDERS = work_dir(...)` freezes the data root at
    import, so a caller that redirects the store moves this stage's archive and not its sources.
    """
    return bodies.work_dir(bodies.EARTH, "borders")


def source_path() -> Path:
    """The countries GeoJSON this whole cut descends from."""
    return borders_dir() / "countries.geojson"


def outlines_path() -> Path:
    return borders_dir() / "country_outlines.geojson"


def hits_path() -> Path:
    return borders_dir() / "country_hits.geojson"


def outlines_recipe_path() -> Path:
    """What the two derived files were written UNDER. Beside them rather than beside the archive,
    because it answers for the derivation and the archive has a sidecar of its own."""
    return borders_dir() / "country_outlines_params.json"


# Layer names inside the archive. The frontend reads these as MapLibre `source-layer` values, and
# `tests/test_source_layers.py` compares them against web/src/lib/sourceLayers.ts on every suite.
FILL_LAYER = "country_fill"
OUTLINE_LAYER = "country_outline"
HIT_LAYER = "country_hit"

MIN_ZOOM = 0
#: READ FROM THE BODY, NEVER RESTATED. The relief pyramid's ceiling is what the outline is judged
#: against, so vector detail has to reach exactly where the raster does; a literal here would let the
#: two drift with nothing going red until someone compared tiles by eye.
MAX_ZOOM = bodies.EARTH.tile_max_zoom

# Tile-space units, of `vector_layers.EXTENT`. Chosen at the knee of the measured sweep: z0 gzip
# falls 246 -> 108 KB going from none to 2, and only 108 -> 86 going on to 4, while mid-zoom
# coastlines visibly coarsen. Re-cut and re-judge rather than guessing — the recipe sidecar records
# it. NOT SHARED WITH MARS: that body carries the same number for a reason of its own.
SIMPLIFICATION = 2.0
# Deliberately far below SIMPLIFICATION: the top zoom is the one the outline is judged at.
SIMPLIFICATION_MAX_ZOOM = 0.5

# `buffer: 0` is load-bearing and is the same decision the GeoJSON source made at runtime — the
# translucent fill wash double-paints in the default tile-buffer overlap, worst near the pole.
# Baked here because a vector source cannot set it at runtime.
BUFFER = 0


def sources() -> dict[str, Path]:
    """Each archive layer and the GeoJSON it is cut from, in staging order.

    Two of the three are DERIVED by this stage rather than acquired, which is why `country_fill`'s
    source is the only one a run can be missing.
    """
    return {FILL_LAYER: source_path(), OUTLINE_LAYER: outlines_path(),
            HIT_LAYER: hits_path()}


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


def derivation() -> dict[Path, dict[str, Any]]:
    """Both derived layers from one read of the source — ONE derivation, not two.

    They are written under a single stamp because they descend from the same file through the same
    seam settings, so a state where one is current and the other is not has no meaning.
    """
    countries = json.loads(source_path().read_text(encoding="utf-8"))
    return {outlines_path(): outlines_from(countries), hits_path(): hit_points_from(countries)}


CUT = VectorCut(
    body=bodies.EARTH,
    name="countries",
    sources=sources,
    derived_layers=(OUTLINE_LAYER, HIT_LAYER),
    derived_from=source_path,
    derivation=derivation,
    derivation_stamp=outlines_recipe_path,
    prerequisite="pipeline.compose.countries_geojson",
    min_zoom=MIN_ZOOM,
    max_zoom=MAX_ZOOM,
    simplification=SIMPLIFICATION,
    simplification_max_zoom=SIMPLIFICATION_MAX_ZOOM,
    buffer=BUFFER,
    # Earth's whole cut descends from one GeoJSON, so the sidecar names it. Mars has no such file and
    # records no such key — see `VectorCut.extra_recipe`.
    extra_recipe=lambda: {"source": source_path().name},
)


def main() -> int:
    return run(CUT, __doc__ or "")


if __name__ == "__main__":
    sys.exit(main())
