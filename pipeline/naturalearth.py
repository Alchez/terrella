"""The one home for Natural Earth's vectors: where they live, and how a layer is addressed in them.

WHY THIS MODULE EXISTS, since a directory and a two-line join look like they need no home at all.
Natural Earth is the most widely shared input in this pipeline — one acquirer writes it and seven
readers across three tiers consume it — and before this module the directory was spelled **eight**
times and the layer join **five**, in modules that never import each other. Two of those readers had
independently invented the identical helper (`NE / name / f"{name}.shp"`) and kept it local, which
is the tell: the abstraction was found twice and promoted zero times.

The pattern behind it is worth naming, because it will recur. Every dataset with ONE owning module
is already single-homed here — gebco, rgi, seaice, glo30, globathy, worldcover, mars each have
exactly one constant. Duplication appeared precisely where a dataset became SHARED, because
`paths.py` hands out a machine root and `bodies.work_dir` hands out a per-body stage directory, and
nothing owned a shared *dataset*. So the second module to want one copied the first. When the next
raw source gains a second reader, it wants a module like this one rather than a second constant.

WHAT IS DELIBERATELY NOT HERE: which layer a caller wants. `layer("ne_10m_coastline")` at the call
site is that module choosing its own dataset, not a fact shared with anyone — collapsing those into
constants would move a local decision somewhere it cannot be read alongside the code that makes it.
The shared facts are the directory and the naming rule. Those are here; the choices stay out there.

THE VOCABULARY IS SPELLED TWICE AND CANNOT BE SPELLED ONCE. `download_naturalearth.sh` is the
writer, and shell cannot import Python, so `LAYERS` below is a second copy of the list in that
script by necessity. `tests/test_naturalearth.py` holds the two together, in the same shape the body
registry uses across the Python/TypeScript boundary — a reader asking for a layer nobody downloads
is otherwise a `shapefile.Reader` error about a missing file, which reads like a failed download
rather than like a name that was never going to exist.
"""

from pathlib import Path

from pipeline import paths

#: Every layer the acquirer fetches, by its own name — which is also its directory name and the
#: stem of every component file inside it. Pinned against `download_naturalearth.sh` by a test.
LAYERS = frozenset({
    "ne_10m_admin_0_boundary_lines_land",
    "ne_10m_admin_0_boundary_lines_maritime_indicator",
    "ne_10m_admin_0_countries",
    "ne_10m_admin_0_disputed_areas",
    "ne_10m_coastline",
    "ne_10m_lakes",
    "ne_10m_rivers_lake_centerlines",
})

#: The unpacked vectors, in the data store. `MAPS_DATA` relocates them, and the acquirer honours the
#: same variable — writer and readers move together or the store is only half real.
DIR = paths.DATA / "raw/naturalearth"


def layer(name: str, directory: Path | None = None) -> Path:
    """The shapefile for one Natural Earth layer.

    Natural Earth nests each layer in a directory of its own name, so the name appears twice in
    every path: `<dir>/ne_10m_coastline/ne_10m_coastline.shp`. That doubling is the whole reason
    this is a function — written by hand it is two chances to typo, and a typo in the second half
    fails at read time with a missing-file error that reads like a failed download.

    `directory` exists for the two entry points that expose `--ne-dir`, and is read at CALL time so
    the default follows a relocated store rather than freezing at import.
    """
    if name not in LAYERS:
        known = ", ".join(sorted(LAYERS))
        raise ValueError(f"unknown Natural Earth layer {name!r}; the acquirer fetches: {known}")
    return (DIR if directory is None else directory) / name / f"{name}.shp"
