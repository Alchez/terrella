"""Convert the plate-boundary lines to one WGS84 GeoJSON for the globe's tectonics overlay.

A pure format translation, as the border lines are: the source ships EPSG:4326, so nothing is
reprojected and nothing is simplified. The source is already schematic at plate scale, and the
globe's own source `tolerance` thins it per zoom.

One file carrying `type` and `level`. The globe styles on `level` alone, fading minor boundaries in
on zoom; `type` is carried for what reads it next.

Segments typed `inferred` are excluded here rather than hidden in the style, so the served file
holds only boundaries the source states as observed.

`check_vocabulary` is why this cannot fail quietly. A source that respells `inferred` would leave
the `-where` below excluding nothing, and 19 unconstrained segments would reach a visitor as
ordinary boundaries, with no error and no failed request. Reading the values back and refusing an
unknown or an absent one turns that into a stopped pipeline.

    python -m pipeline.compose.tectonics_geojson            # writes if missing
    python -m pipeline.compose.tectonics_geojson --force    # regenerate
"""

import argparse
import subprocess
import sys
from pathlib import Path

import shapefile

from pipeline import datasets
from pipeline.compose import countries_pmtiles

OUTPUT_NAME = "tectonic_boundaries.geojson"

#: A segment's behaviour, which also says how well constrained it is, and whether it is a major or a
#: minor boundary, which the globe styles on.
TYPE_FIELD = "type"
LEVEL_FIELD = "level"

#: The source's own value for a segment believed to be a boundary without being well constrained.
#: `ogr_command` excludes it, so this spelling decides what the served file holds.
INFERRED = "inferred"

#: Every value the source carries in `type`. The only copy: nothing downstream declares this vocabulary, and
#: a second list is what `check_vocabulary` exists to make unnecessary.
TYPES = (
    "collision zone",
    "dextral transform",
    "extension zone",
    "inferred",
    "sinistral transform",
    "spreading center",
    "subduction zone",
)

#: Every value the source carries in `level`. The globe fades a minor boundary in on zoom, and a
#: test holds its copy of `MINOR_LEVEL` equal to this one.
MAJOR_LEVEL = 1
MINOR_LEVEL = 2
LEVELS = (MAJOR_LEVEL, MINOR_LEVEL)

#: ~11 m, which is sub-pixel against the ground a pixel covers at the deepest zoom the relief is cut
#: to. Held relationally by a test rather than as a number anyone can nudge.
COORDINATE_PRECISION = 4

#: What reaches the browser. Everything else the source carries, the plate names and the segment
#: length, describes features the globe does not yet draw or label.
CARRIED = (TYPE_FIELD, LEVEL_FIELD)


def ogr_command(src: Path, out: Path) -> list[str]:
    """The translation, as a list for a test to read back.

    Destination before source is ogr2ogr's own argument order. Swapped, it writes over the source
    shapefile, which is the kind of mistake that is only visible on the next run.
    """
    return [
        "ogr2ogr", "-f", "GeoJSON",
        "-select", ",".join(CARRIED),
        "-where", f"{TYPE_FIELD} != '{INFERRED}'",
        "-lco", "RFC7946=YES",
        "-lco", f"COORDINATE_PRECISION={COORDINATE_PRECISION}",
        str(out), str(src),
    ]


def check_vocabulary(src: Path) -> dict[str, int]:
    """The source's `type` values against `TYPES` and its `level` values against `LEVELS`, or exit.

    Both directions are checked. An unknown `type` may be a respelt `inferred` that the `-where`
    no longer excludes, and a changed `level` moves what the globe's zoom fade selects. Neither
    raises anywhere downstream, so both are refused here.
    """
    reader = shapefile.Reader(str(src))
    try:
        names = [field[0] for field in reader.fields[1:]]
        missing = [wanted for wanted in CARRIED if wanted not in names]
        if missing:
            sys.exit(f"{src.name} has no {missing} field, carrying {names}: the layer's schema has "
                     f"moved, and the globe styles on `{LEVEL_FIELD}`")
        type_index = names.index(TYPE_FIELD)
        level_index = names.index(LEVEL_FIELD)
        counts: dict[str, int] = {}
        levels: set[object] = set()
        for number, record in enumerate(reader.records()):
            # A row the reader could not parse is refused rather than skipped: skipping would take
            # it out of the counts below, which is the population the vocabulary is checked against.
            if record is None:
                sys.exit(f"{src.name} record {number} did not parse, so the vocabulary below would "
                         f"be checked against a population missing a row")
            value = str(record[type_index]).strip()
            counts[value] = counts.get(value, 0) + 1
            levels.add(record[level_index])
    finally:
        reader.close()

    unknown = sorted(set(counts) - set(TYPES))
    absent = sorted(set(TYPES) - set(counts))
    if unknown or absent:
        sys.exit(f"the source's `{TYPE_FIELD}` vocabulary has moved. Unknown here: {unknown}. "
                 f"Declared but absent from the data: {absent}. A respelt `{INFERRED}` would reach a "
                 f"visitor as ordinary boundaries rather than as an error.")
    if levels != set(LEVELS):
        sys.exit(f"the source's `{LEVEL_FIELD}` values are {sorted(map(repr, levels))}, not "
                 f"{list(LEVELS)}. The globe fades level {MINOR_LEVEL} in on zoom and draws any "
                 f"other value as major, so the zoom fade would silently mean something else.")
    return counts


def translate(src: Path, out: Path, force: bool) -> None:
    if not src.exists():
        sys.exit(f"missing plate-boundary source: {src}. "
                 f"Run `python -m pipeline.acquire.earth.download_global_tectonics` first.")
    if out.exists() and not force:
        print(f"{out.name} exists -> skip (use --force to regenerate)")
        return
    counts = check_vocabulary(src)
    print(f"vocabulary ok: {sum(counts.values())} features, "
          + ", ".join(f"{value} {counts[value]}" for value in TYPES), flush=True)
    tmp = out.with_suffix(".geojson.tmp")
    tmp.unlink(missing_ok=True)
    command = ogr_command(src, tmp)
    print(" ".join(command), flush=True)
    subprocess.run(command, check=True)
    tmp.replace(out)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="regenerate even if present")
    args = parser.parse_args()
    out_dir = countries_pmtiles.borders_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    translate(datasets.global_tectonics_boundaries(), out_dir / OUTPUT_NAME, args.force)


if __name__ == "__main__":
    sys.exit(main())
