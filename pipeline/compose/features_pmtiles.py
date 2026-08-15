"""Cut Mars's named features into a VECTOR tile pyramid (PMTiles) — four layers, one archive.

Mars's declaration; `vector_cut` runs it. What is here is what is Mars's — the four layers, the
knobs, the one file this stage derives — and nothing about how a cut is performed.

WHY ALL 1,717 AND NOT A CUTOFF. The scout measured that the ~200 largest features carry 99.2% of
the union coverage, and that number is real but it answers only "if a pin lands at a uniformly
random point, is something under it". It is AREA-WEIGHTED, so it is decided entirely by a handful of
enormous terrae, and rank 200 turns out to be a **394 km diameter floor** — which deletes Gale (154
km) and Jezero (47.5 km), the two most recognisable place names on the planet, because between them
they are a hundredth of a percent of the sphere. The deeper mismatch is that a whole-sphere
statistic was being aimed at a ZOOM-ADDRESSED layer: 1,198 of 1,717 features fall between 5 km and
one z7 tile, which is precisely what fills the screen once a visitor is zoomed in and precisely what
the metric cannot weigh. Measured, the cutoff buys 54 KB on the cold window (z0: 71.8 KB whole
against 17.9 KB cut) — and the whole catalogue is already lighter at z0 than Earth's countries are.
So the archive carries everything and declutter is a runtime filter on `diameter`, which is also the
reversible direction: a style filter can always narrow, an archive cannot widen without a re-cut.

SIMPLIFICATION IS LOAD-BEARING HERE IN A WAY IT IS NOT ON EARTH — IT IS THE DIFFERENCE BETWEEN AN
ARCHIVE AND A CRASH. GDAL 3.12.2's MVT writer **segfaults** on the gazetteer polygons when no
simplification is applied, whether the option is omitted or set to 0. Isolated: it is not the driver
(Earth's countries cut clean through the same code path with none), not this pipeline's coordinate
quantisation (the unquantised geometry crashes identically), not the five circumpolar features (they
crash alone, and so does everything with them removed), and not the linear features (they cut fine).
`vector_layers.pmtiles_command` therefore takes both knobs as required keyword arguments — a caller
that forgets one fails to construct rather than dying at 139 with no output.

WHY FOUR LAYERS. `feature_outline` carries the polygon rings as LINES rather than letting a `line`
layer stroke the polygons, for the phantom-edge reason `vector_layers.outlines_from` holds.
`feature_line` is the 203 valles, rupes and fossae, which have no interior to fill and so cannot ride
in `feature_fill`. `feature_label` is the IAU's own centres for BOTH source layers — an anchor a
polygon centroid cannot supply for a crescent and a line cannot supply at all.

A HANDFUL OF POLAR ANCHORS DO NOT REACH THE GRID, AND THAT IS THE PROJECTION RATHER THAN A FAULT.
Web Mercator stops at ±85.0511°, and the northernmost features' adopted centres lie past it, so
their label anchors are clipped away while their geometry still arrives clipped at the limit. Those
features stay tappable and go unlabelled, which is the right way round — and the polar caps are
drawn over that band regardless.

    python -m pipeline.compose.features_pmtiles           # writes if missing/stale
    python -m pipeline.compose.features_pmtiles --force   # re-cut
"""

import json
import sys
from pathlib import Path
from typing import Any

from pipeline import bodies
from pipeline.compose import features_geojson, vector_layers
from pipeline.compose.vector_cut import VectorCut, run


def outlines_path() -> Path:
    """Derived, not acquired, so it lands beside the polygons it is derived FROM rather than beside
    the archive it feeds — the geojsons are one stage's output and belong together.

    Call time for `countries_pmtiles.borders_dir`'s reason. It still resolves through
    `features_geojson.OUT_DIR`, which is bound at import, so the remaining freeze has ONE owner
    rather than a copy here as well.
    """
    return features_geojson.OUT_DIR / "feature_outlines.geojson"


def outlines_recipe_path() -> Path:
    """What the file above was derived UNDER — see `countries_pmtiles.outlines_recipe_path`."""
    return features_geojson.OUT_DIR / "feature_outlines_params.json"


# Layer names inside the archive. The frontend reads these as MapLibre `source-layer` values, and a
# mismatch renders the layer empty with no error — so both ends are pinned by test.
FILL_LAYER = "feature_fill"
OUTLINE_LAYER = "feature_outline"
LINE_LAYER = "feature_line"
LABEL_LAYER = "feature_label"

MIN_ZOOM = 0
#: READ FROM THE BODY, NEVER RESTATED. The relief pyramid's ceiling is what the outline is judged
#: against, so vector detail has to reach exactly where the raster does; a literal here would let
#: the two drift with nothing going red until someone compared tiles by eye.
MAX_ZOOM = bodies.MARS.tile_max_zoom

#: Tile-space units, of `vector_layers.EXTENT`. MEASURED ON THIS CATALOGUE AND FOUND NEARLY INERT:
#: z0 moves 81.6 -> 75.7 -> 70.3 KB across 1 / 2 / 4, an 11 KB spread where Earth's coastlines moved
#: 160 KB. Craters are convex and short-perimeter, so Douglas-Peucker has little to take. Earth's
#: value is kept because no Mars measurement argues for another, not because it was inherited — and
#: the sidecar records it, so a re-judge costs one re-cut.
SIMPLIFICATION = 2.0
#: Deliberately far below SIMPLIFICATION, and vindicated by the same sweep: z7 came out
#: BYTE-IDENTICAL at 4157.2 KB across every arm, so overview weight is tunable without touching the
#: zoom the outline is actually judged at. That is the entire reason there are two knobs.
SIMPLIFICATION_MAX_ZOOM = 0.5

#: The translucent hover wash double-paints in the default tile-buffer overlap. A vector source
#: cannot set this at runtime, so losing it here is unrecoverable in the browser.
BUFFER = 0


def sources() -> dict[str, Path]:
    """Each archive layer and the GeoJSON it is cut from, in staging order.

    `feature_outline` is derived rather than acquired, which is why it is the one entry whose path
    this module owns instead of reading from `features_geojson`.
    """
    return {
        FILL_LAYER: features_geojson.POLYGONS,
        OUTLINE_LAYER: outlines_path(),
        LINE_LAYER: features_geojson.LINES,
        LABEL_LAYER: features_geojson.LABELS,
    }


def derivation() -> dict[Path, dict[str, Any]]:
    """The outline layer, from the polygons it strokes."""
    collection = json.loads(features_geojson.POLYGONS.read_text(encoding="utf-8"))
    return {outlines_path():
            vector_layers.outlines_from(collection, features_geojson.CARRIED_FIELDS)}


CUT = VectorCut(
    body=bodies.MARS,
    name="features",
    sources=sources,
    derived_layers=(OUTLINE_LAYER,),
    derived_from=lambda: features_geojson.POLYGONS,
    derivation=derivation,
    derivation_stamp=outlines_recipe_path,
    prerequisite="pipeline.compose.features_geojson",
    min_zoom=MIN_ZOOM,
    max_zoom=MAX_ZOOM,
    simplification=SIMPLIFICATION,
    simplification_max_zoom=SIMPLIFICATION_MAX_ZOOM,
    buffer=BUFFER,
    # EMPTY, NOT NULLED. Mars's four layers descend from four separate gazetteer files, so there is
    # no single source to name the way Earth names one — and a key recorded with no meaning is a
    # value every future comparison would have to keep matching.
    extra_recipe=dict,
)


def main() -> int:
    return run(CUT, (__doc__ or "").split("\n")[0])


if __name__ == "__main__":
    sys.exit(main())
