"""Cut Mars's named features into a VECTOR tile pyramid (PMTiles) — four layers, one archive.

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

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from pipeline import bodies
from pipeline.compose import features_geojson, vector_layers

#: One stage name per LAYER, under each body's own prefix — the convention `devStores.archivePath`
#: rests on, so Mars's vector cut and Earth's land in directories that differ only by planet.
OUT_DIR = bodies.work_dir(bodies.MARS, "planet_vector")

#: Derived, not acquired, so it lands beside the polygons it is derived FROM rather than beside the
#: archive it feeds — `derive` compares the two mtimes and a split across directories would not
#: change that, but the geojsons are one stage's output and belong together.
OUTLINES = features_geojson.OUT_DIR / "feature_outlines.geojson"
STAGED = OUT_DIR / "features_staged.gpkg"
OUT = OUT_DIR / "vector.pmtiles"

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
        OUTLINE_LAYER: OUTLINES,
        LINE_LAYER: features_geojson.LINES,
        LABEL_LAYER: features_geojson.LABELS,
    }


def pmtiles_command(source: Path, destination: Path) -> list[str]:
    """The single conversion. Argument order is [options] DESTINATION SOURCE."""
    return vector_layers.pmtiles_command(
        source, destination,
        name="features",
        min_zoom=MIN_ZOOM,
        max_zoom=MAX_ZOOM,
        buffer=BUFFER,
        simplification=SIMPLIFICATION,
        simplification_max_zoom=SIMPLIFICATION_MAX_ZOOM,
    )


def recipe() -> dict[str, Any]:
    """What this cut was made with, recorded beside it — the archive's name carries none of it."""
    return {
        "layers": list(sources()),
        "min_zoom": MIN_ZOOM,
        "max_zoom": MAX_ZOOM,
        "simplification": SIMPLIFICATION,
        "simplification_max_zoom": SIMPLIFICATION_MAX_ZOOM,
        "buffer": BUFFER,
        "extent": vector_layers.EXTENT,
    }


def recipe_path() -> Path:
    return OUT_DIR / "features_tiles_params.json"


def is_fresh() -> bool:
    """True when the archive is present, newer than every layer it was cut from, and stamped with
    the recipe on disk — the half that catches a knob change, which moves no mtime."""
    if not OUT.exists() or OUT.stat().st_size == 0:
        return False
    for path in sources().values():
        if not path.exists() or OUT.stat().st_mtime <= path.stat().st_mtime:
            return False
    stamped = recipe_path()
    return stamped.exists() and json.loads(stamped.read_text()) == recipe()


def derive(force: bool) -> None:
    """Write the outline layer beside its source, skipping when already current."""
    polygons = features_geojson.POLYGONS
    if not force and OUTLINES.exists() and OUTLINES.stat().st_mtime > polygons.stat().st_mtime:
        print(f"{OUTLINES.name} current -> skip")
        return
    collection = json.loads(polygons.read_text(encoding="utf-8"))
    outlines = vector_layers.outlines_from(collection, features_geojson.CARRIED_FIELDS)
    temporary = OUTLINES.with_suffix(".geojson.tmp")
    temporary.write_text(json.dumps(outlines), encoding="utf-8")
    temporary.replace(OUTLINES)  # atomic promote
    print(f"wrote {OUTLINES.name} ({len(outlines['features'])} features, "
          f"{OUTLINES.stat().st_size / 1e6:.2f} MB)")


def stage() -> None:
    """Every layer into one GeoPackage — see `vector_layers.stage_command` for why this exists."""
    STAGED.unlink(missing_ok=True)
    for index, (layer, source) in enumerate(sources().items()):
        command = vector_layers.stage_command(source, STAGED, layer, update=index > 0)
        print(" ".join(command), flush=True)
        subprocess.run(command, check=True)


def cut() -> None:
    temporary = OUT.with_suffix(".pmtiles.tmp")
    temporary.unlink(missing_ok=True)
    command = pmtiles_command(STAGED, temporary)
    print(" ".join(command), flush=True)
    subprocess.run(command, check=True)
    temporary.replace(OUT)  # atomic promote
    recipe_path().write_text(json.dumps(recipe(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--force", action="store_true", help="re-cut even if current")
    args = parser.parse_args()

    missing = [path for layer, path in sources().items()
               if layer != OUTLINE_LAYER and not path.exists()]
    if missing:
        sys.exit(f"missing {', '.join(path.name for path in missing)} — "
                 f"run pipeline.compose.features_geojson first")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if is_fresh() and not args.force:
        print(f"{OUT.name} is current -> skip (use --force to re-cut)")
        return 0

    derive(args.force)
    stage()
    cut()
    STAGED.unlink(missing_ok=True)  # a large intermediate with no reader once the archive exists
    return 0


if __name__ == "__main__":
    sys.exit(main())
