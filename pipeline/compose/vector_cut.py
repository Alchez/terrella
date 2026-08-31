"""One body's vector tile cut: what it is made of, what it is made with, and how it is run.

THE DRIVER, NOT A STAGE. `countries_pmtiles` and `features_pmtiles` are the stages and stay the
entry points; each declares a `VectorCut` and hands it here. What lives in this module is everything
those two were saying twice — the freshness question, the derivation gate, the staging loop, the
conversion, and the CLI around them.

WHY A DECLARATION AND NOT A BASE CLASS. `Body`, `perennial_ice.CapIce` and
`layer_producers.LayerProducer` are all frozen dataclasses of callables, and the alternative here
was a duck-typed `run(countries_pmtiles)` reading module attributes. That contract is invisible: a
declaration that forgets a field fails at runtime inside a subprocess call, where this one fails at
construction and pyright sees the whole shape.

EVERY PATH IS A CALLABLE, on `CapIce.sources`' argument, which `paths.py` states as a rule for the
whole package: a module-level `SOMEWHERE = DATA / "x"` freezes the root at import, so a caller that
redirects the data store moves some of a stage's paths and not others. It has a second payoff here —
a test builds a `VectorCut` pointing wherever it likes instead of monkeypatching the six module
globals its predecessor had to, and a fixture that half-redirects is no longer expressible.

THE KNOBS ARE PER BODY AND LOOK LIKE THEY SHOULD NOT BE. Both bodies presently carry the same five
values, and each module's docstring argues for its own: Mars keeps Earth's simplification because no
Mars measurement argues for another, which is a statement about a measurement and not an inheritance.
Hoisting them here would delete the difference between those two things.
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline import bodies, freshness
from pipeline.compose import vector_layers


@dataclass(frozen=True)
class VectorCut:
    """One body's answer for the vector tile archive: its layers, its knobs and its derivation."""

    body: bodies.Body
    #: Names the archive to `ogr2ogr` and both intermediates beside it. The PRODUCT, not the role —
    #: `LayerId` is `vector` on every planet while the bytes are countries on one and named features
    #: on another, and the file on disk is a permanent statement about which of those it holds.
    name: str
    #: Each archive layer and the GeoJSON it is cut from, IN STAGING ORDER — the dict is ordered and
    #: `stage` walks it, so the first entry is the one that creates the GeoPackage.
    sources: Callable[[], dict[str, Path]]
    #: The layers this stage DERIVES; every other source must already exist when a run starts.
    derived_layers: tuple[str, ...]
    #: The GeoJSON the derivation reads. Its mtime is what the derived files are compared against.
    derived_from: Callable[[], Path]
    #: What the derivation writes, as `{destination: collection}`. A body deriving two files from one
    #: source says so here and the driver writes both under one stamp — Earth's outlines and hit
    #: points are a single derivation, not two.
    derivation: Callable[[], dict[Path, dict[str, Any]]]
    #: Where the derivation's seam stamp lives — beside the files it describes, never beside the
    #: archive, because it answers for the derivation and the archive has a sidecar of its own.
    derivation_stamp: Callable[[], Path]
    #: The stage to run first, named in the message when a source is missing.
    prerequisite: str
    min_zoom: int
    max_zoom: int
    simplification: float
    simplification_max_zoom: float
    buffer: int
    #: Recipe keys this body records beyond the shared set. Earth names the single GeoJSON its whole
    #: cut descends from; Mars has no such file, so its extra set is empty rather than nulled — a
    #: recorded key with no meaning would be a value every future comparison has to keep matching.
    extra_recipe: Callable[[], dict[str, Any]]


#: This module's stage directory under a body's work tree, the same role `relief_scan.STAGE` plays
#: for the colour pyramid. Declared here because this is the module that names the stage's contents,
#: and read across the language boundary by `devStores.ts`, which resolves the dev server's archive
#: under its own copy of the string. `tests/test_paths.py` refuses a second spelling on either side.
STAGE = "planet_vector"


def out_dir(cut: VectorCut) -> Path:
    """This body's vector stage directory.

    One stage name per LAYER under each body's own prefix — the convention `devStores.archivePath`
    rests on, so two bodies' vector cuts land in directories that differ only by planet.
    """
    return bodies.work_dir(cut.body, STAGE)


def out(cut: VectorCut) -> Path:
    """The archive itself. Named for the ROLE, since the frontend addresses it by role."""
    return out_dir(cut) / "vector.pmtiles"


def staged(cut: VectorCut) -> Path:
    """The staging GeoPackage — see `vector_layers.stage_command` for why the step exists at all."""
    return out_dir(cut) / f"{cut.name}_staged.gpkg"


def recipe_path(cut: VectorCut) -> Path:
    """The cut's sidecar. Keeps its PRODUCER's name where the archive takes the role's."""
    return out_dir(cut) / f"{cut.name}_tiles_params.json"


def pmtiles_command(cut: VectorCut, source: Path, destination: Path) -> list[str]:
    """The single conversion, exposed pure for tests. Argument order is [options] DEST SOURCE."""
    return vector_layers.pmtiles_command(
        source, destination,
        name=cut.name,
        min_zoom=cut.min_zoom,
        max_zoom=cut.max_zoom,
        buffer=cut.buffer,
        simplification=cut.simplification,
        simplification_max_zoom=cut.simplification_max_zoom,
    )


def recipe(cut: VectorCut) -> dict[str, Any]:
    """What this cut was made with, recorded beside it.

    The archive's own name carries none of this, so without a sidecar a simplification change is
    invisible to every guard and to anyone reading the store — the same reason `terrain_rgb` writes
    `terrain_params.json`.

    KEY ORDER IS NOT PART OF THE CONTRACT and the key SET is: freshness compares parsed objects, so
    a reordered sidecar is still fresh while an added or dropped key re-cuts a live archive. That is
    what `extra_recipe` exists to keep exact.
    """
    return {
        **cut.extra_recipe(),
        "layers": list(cut.sources()),
        "min_zoom": cut.min_zoom,
        "max_zoom": cut.max_zoom,
        "simplification": cut.simplification,
        "simplification_max_zoom": cut.simplification_max_zoom,
        "buffer": cut.buffer,
        "extent": vector_layers.EXTENT,
        **vector_layers.seam_recipe(),
    }


def derivation_is_stamped(cut: VectorCut) -> bool:
    """True when the derived layers on disk were written under the seam settings in force now.

    Its own question, asked in two places: `derive` decides whether to rewrite the GeoJSON, and
    `is_fresh` decides whether the archive above it can still be believed. Answering it in only the
    first is what let a stale derivation hide behind a fresh archive — `run` returns on `is_fresh`
    and never reaches `derive` at all.
    """
    return freshness.recorded_json(cut.derivation_stamp()) == vector_layers.seam_recipe()


def is_fresh(cut: VectorCut) -> bool:
    """True when the live archive is current: present, non-empty, stamped newer than every layer it
    was cut from, and cut under both recipes on disk.

    THE TWO RECIPES ANSWER FOR DIFFERENT STAGES and neither substitutes for the other. This cut's
    knobs move the tiles, `vector_layers`' knobs move the geometry handed to the cut, and an archive
    can be current under the first while its outlines were drawn under the second's previous answer.
    """
    archive = out(cut)
    if not archive.exists() or archive.stat().st_size == 0:
        return False
    for source in cut.sources().values():
        if not source.exists() or archive.stat().st_mtime <= source.stat().st_mtime:
            return False
    if not derivation_is_stamped(cut):
        return False
    return freshness.recorded_json(recipe_path(cut)) == recipe(cut)


def derive(cut: VectorCut, force: bool) -> None:
    """Write the derived layers beside their source, skipping when already current.

    THE SEAM RECIPE IS CHECKED HERE AND NOT ONLY AT THE CUT, because this is the stage
    `vector_layers` writes through. Gating on the source's mtime alone made a change to the shared
    geometry unobservable: the source does not move when that module's constants do, so the
    derivation skipped, the cut re-ran on the stale GeoJSON it had always had, produced a
    byte-identical archive, and stamped the NEW recipe over it — consuming the one signal that
    anything was out of date.
    """
    destinations = tuple(cut.derivation())
    current = (
        not force
        and all(destination.exists() for destination in destinations)
        and min(destination.stat().st_mtime for destination in destinations)
        > cut.derived_from().stat().st_mtime
        and derivation_is_stamped(cut)
    )
    if current:
        print(f"{' + '.join(d.name for d in destinations)} current -> skip")
        return
    for destination, collection in cut.derivation().items():
        temporary = destination.with_suffix(".geojson.tmp")
        temporary.write_text(json.dumps(collection), encoding="utf-8")
        temporary.replace(destination)  # atomic promote
        print(f"wrote {destination.name} ({len(collection['features'])} features, "
              f"{destination.stat().st_size / 1e6:.2f} MB)")
    # Stamped AFTER every file exists, so a crash between them leaves the derivation stale rather
    # than vouched for — the same order every other stage in this pipeline writes its marker in.
    cut.derivation_stamp().write_text(
        json.dumps(vector_layers.seam_recipe(), indent=2) + "\n", encoding="utf-8")


def stage(cut: VectorCut) -> None:
    """Every layer into one GeoPackage — see `vector_layers.stage_command` for why this exists."""
    staging = staged(cut)
    staging.unlink(missing_ok=True)
    for index, (layer, source) in enumerate(cut.sources().items()):
        command = vector_layers.stage_command(source, staging, layer, update=index > 0)
        print(" ".join(command), flush=True)
        subprocess.run(command, check=True)


def cut_archive(cut: VectorCut) -> None:
    """The conversion, promoted atomically, with its recipe stamped beside it."""
    archive = out(cut)
    temporary = archive.with_suffix(".pmtiles.tmp")
    temporary.unlink(missing_ok=True)
    command = pmtiles_command(cut, staged(cut), temporary)
    print(" ".join(command), flush=True)
    subprocess.run(command, check=True)
    temporary.replace(archive)  # atomic promote
    recipe_path(cut).write_text(json.dumps(recipe(cut), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {archive} ({archive.stat().st_size / 1e6:.1f} MB)")


def missing_sources(cut: VectorCut) -> list[Path]:
    """Acquired sources that are not on disk. The derived ones are excluded because this stage is
    what writes them, so their absence is work to do rather than a missing prerequisite."""
    return [source for layer, source in cut.sources().items()
            if layer not in cut.derived_layers and not source.exists()]


def build_parser(description: str) -> argparse.ArgumentParser:
    """The CLI, split out so its contract is testable without running a cut."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--force", action="store_true", help="re-cut even if current")
    return parser


def run(cut: VectorCut, description: str, argv: list[str] | None = None) -> int:
    """Derive, stage and cut, unless the archive on disk already answers for all three."""
    options = build_parser(description).parse_args(argv)

    absent = missing_sources(cut)
    if absent:
        sys.exit(f"missing {', '.join(source.name for source in absent)} — "
                 f"run {cut.prerequisite} first")
    out_dir(cut).mkdir(parents=True, exist_ok=True)

    archive = out(cut)
    if is_fresh(cut) and not options.force:
        print(f"{archive.name} is current -> skip (use --force to re-cut)")
        return 0

    derive(cut, options.force)
    stage(cut)
    cut_archive(cut)
    staged(cut).unlink(missing_ok=True)  # a large intermediate with no reader once the archive exists
    return 0
