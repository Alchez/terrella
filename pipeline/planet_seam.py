"""What a body's planet stage produced, declared by the stage that produced it.

THE SEAM EVERY BODY ENTERS THROUGH. Earth's planet rasters come out of a 648-cell fusion; Mars's
come out of a CRS relabel of one published file. Both write the same three-named set into
`data/work/<body>/planet/`, and everything downstream — the 3857 warps, the composite, both polar
caps — reads them from there without caring which producer ran.

WHY A DECLARATION AND NOT A DIRECTORY LISTING, which is the whole reason this module exists.
Downstream stages need to know whether this body HAS an ocean mask, and the tempting answer is
`(planet / "planet_oceanmask.vrt").exists()`. That answer is wrong in a way nothing reports:

  * ABSENCE IS NOT A STATEMENT. A missing mask cannot distinguish "this planet has no sea" from
    "the producer died two rasters in". The first is a fact to composite against; the second is a
    half-built planet that must never be shaded, and they look identical on disk.
  * ABSENCE IS ALSO INVISIBLE TO FRESHNESS. `freshness.newest_mtime` scores a missing path 0.0,
    so a raster that goes away stops being a dependency at the same moment it stops being an input.
    Turning a sea OFF therefore leaves the old sea-painted composite looking perfectly fresh —
    which is exactly the loop Phase 2 runs when it tries a shoreline contour, then another, then
    none.

So the producer states what it emitted, and it states it LAST. The declaration's PRESENCE is the
stage's completion stamp (the `.done` idiom one tier up, carrying content), and its CONTENT is the
body fact. A crashed producer writes none and every consumer refuses to run; a complete one is
trusted about what it does not have.

RASTERS, NEVER "LAYERS". `bodies.SURFACE_LAYERS` already owns that word for the optional things the
render paints OVER the heightfield — snow, glaciers, sea ice, lake depth, the coastline. These three
are the heightfield and the masks that classify it, produced by an entirely different tier and
answering an entirely different question. One word for both concepts is how a reader ends up
believing `layers_off` and this set are the same switch.

    from pipeline import planet_seam
    rasters = planet_seam.declared(body)     # raises if the producer never finished
    if "oceanmask" in rasters: ...
"""

import json
from collections.abc import Callable, Iterable
from pathlib import Path

from pipeline import bodies

#: The rasters a planet stage may emit, in the order a producer builds them.
#:
#: `heightfield` is the elevation the whole pipeline shades. `oceanmask` is the 0/1 land/sea split
#: that chooses between the land and sea ramps; `watermask` is the 4-class code (0 land, 1 ocean,
#: 2 inland lake, 3 inland river) that selects inland water and keys the lake bathymetry off it.
#:
#: A TUPLE, NOT A SET, because producers iterate it and the order they build in is the order they
#: report in. Membership tests take `KNOWN_RASTERS` below.
PLANET_RASTERS = ("heightfield", "oceanmask", "watermask")

KNOWN_RASTERS = frozenset(PLANET_RASTERS)

#: The file the producer writes last, beside the rasters it names.
DECLARATION_NAME = "planet_rasters.json"

#: Surface layers that cannot be computed without one of the masks, and the mask each one needs.
#:
#: These are real data dependencies, not bookkeeping. `lake_depth` is zeroed off watermask class 2
#: (`lake_depth.lakes_only`), so a body declaring that layer with no watermask has nothing to zero
#: against and the composite would read `None` as a class code. `sea_ice` is gated on the ocean mask
#: inside `shade.composite`, so ice on a body with no ocean mask is blended against an all-False
#: selector and paints nothing at all — a layer that is switched on, costs a warp, and cannot reach
#: a pixel. Both are incoherent rather than merely empty, so both are refused here where the two
#: facts first meet, rather than surfacing as a `TypeError` deep in a worker thread.
LAYER_REQUIRES_RASTER: dict[str, str] = {"lake_depth": "watermask", "sea_ice": "oceanmask"}

#: How to produce each body's planet rasters, keyed by body name — quoted verbatim when a consumer
#: finds no declaration.
#:
#: An error that says what is missing and not how to fix it costs the reader a search through two
#: tiers, and the answer differs per body precisely because the producers do: Earth fuses 648 cells
#: from Copernicus and GEBCO, Mars relabels one published file. `tests/test_planet_seam.py` pins
#: every registered body to an entry here, so adding a third planet cannot leave its error message
#: pointing at Earth's command.
PRODUCER_COMMANDS: dict[str, str] = {
    "earth": "python3 -m pipeline.fuse.fuse_planet --build-vrts",
    "mars": "python3 -m pipeline.fuse.relabel_mars",
}


def planet_dir(body: bodies.Body) -> Path:
    """This body's planet stage directory — where the rasters and the declaration live together."""
    return bodies.work_dir(body, "planet")


def vrt_path(body: bodies.Body, raster: str) -> Path:
    """The VRT for one of this body's planet rasters."""
    _require_known(raster)
    return planet_dir(body) / f"planet_{raster}.vrt"


def declaration_path(body: bodies.Body) -> Path:
    """Where this body's planet stage records what it emitted."""
    return planet_dir(body) / DECLARATION_NAME


def _require_known(raster: str) -> None:
    """A raster name outside the vocabulary is a typo, and a typo must not read as an absence."""
    if raster not in KNOWN_RASTERS:
        known = ", ".join(PLANET_RASTERS)
        raise ValueError(f"unknown planet raster {raster!r}; known rasters are: {known}")


def _require_coherent(body: bodies.Body, rasters: frozenset[str]) -> None:
    """Refuse a declaration this body's own layers cannot be computed against.

    Checked on BOTH sides of the file — when it is written and when it is read — because the two
    facts have different lifetimes. The producer knows what it emitted; the registry may gain a
    layer months later, and that edit must fail against a declaration that is already on disk
    rather than at the first pixel that needs it.
    """
    if "heightfield" not in rasters:
        raise ValueError(
            f"{body.name}: a planet stage must emit a heightfield — it is the elevation every "
            f"later stage shades, and a planet without one is not a partial planet but no planet")
    for layer, raster in sorted(LAYER_REQUIRES_RASTER.items()):
        if layer in body.surface_layers and raster not in rasters:
            raise ValueError(
                f"{body.name}: declares the {layer!r} surface layer but its planet stage emitted no "
                f"{raster!r} — see planet_seam.LAYER_REQUIRES_RASTER for why that layer cannot be "
                f"computed without it. Either the producer is incomplete or the body's "
                f"surface_layers are")


def write_vrt_if_changed(vrt: Path, build: Callable[[Path], None]) -> bool:
    """Have `build` write `vrt`, and replace the file on disk only when the XML actually differs.

    NOT AN OPTIMISATION — it is what makes a producer safe to re-run at all. Every 3857 warp
    downstream is gated on the VRT's mtime, so an unconditional overwrite restages the whole planet:
    on Earth that is a 44 GB re-warp, an 8:28 hillshade, a 53.8 min composite and a 3:44 cut, to
    reproduce pixels that were already correct. Re-indexing is the natural thing to do after touching
    a producer, so that cost sat one command away from anyone who tried.

    Byte-identity is what makes the comparison mean anything, and it was measured rather than
    assumed: rebuilding all three of Earth's planet VRTs from the same 648 chunks, into the same
    directory, reproduced the live files' SHA-256 exactly (GDAL 3.12.2).

    THE SCRATCH TARGET SHARES THE VRT'S DIRECTORY, and that is load-bearing rather than tidy: GDAL
    writes source paths RELATIVE to the VRT, so building somewhere else and moving the result
    rewrites every one of them and the comparison can never come out equal.

    SHARED BY BOTH PRODUCERS. Earth's builds a 648-source mosaic index with `gdalbuildvrt`; Mars's
    relabels one file's CRS with `gdal_translate`. The tool differs, the hazard does not, and a
    ten-line routine with a subtle directory constraint is exactly the shape that drifts when it is
    written out twice.

    Returns True when the file on disk changed, so a caller can report it.
    """
    scratch = vrt.with_suffix(".vrt.new")
    vrt.parent.mkdir(parents=True, exist_ok=True)
    build(scratch)
    if vrt.exists() and vrt.read_bytes() == scratch.read_bytes():
        scratch.unlink()
        return False
    scratch.replace(vrt)
    return True


def declare(body: bodies.Body, rasters: Iterable[str]) -> Path:
    """Record what this body's planet stage emitted. CALL LAST, after every raster is on disk.

    THE ORDERING IS THE CONTRACT, not a convention: this file's existence is what tells every
    consumer the stage finished. Written early, it promises rasters a crash may never deliver, and
    the guarantee it exists to give is gone.

    Each named raster is checked onto disk before the name is written. A declaration is only worth
    trusting about what is MISSING if it can be trusted about what is present, and a producer that
    reports a raster it failed to build turns this file from an oracle into a second opinion.
    """
    named = sorted(set(rasters))
    for raster in named:
        _require_known(raster)
    _require_coherent(body, frozenset(named))
    absent = [str(vrt_path(body, raster)) for raster in named
              if not vrt_path(body, raster).exists()]
    if absent:
        raise FileNotFoundError(
            f"{body.name}: refusing to declare rasters that are not on disk: {', '.join(absent)}")
    path = declaration_path(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rasters": named}, indent=2) + "\n")
    return path


def declared(body: bodies.Body) -> frozenset[str]:
    """Which planet rasters this body has, as its producer declared them. Raises if it never ran.

    RAISES RATHER THAN RETURNING AN EMPTY SET, and that is the point of the whole module: an empty
    answer would be a statement about the planet, and a missing file is a statement about the
    pipeline. The two must not share a return value.
    """
    path = declaration_path(body)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing: {body.name}'s planet stage has not finished. This file is written "
            f"last, so its absence means the producer never ran or died partway — the rasters "
            f"beside it, if any, cannot be trusted. Run this body's planet producer — "
            f"{PRODUCER_COMMANDS.get(body.name, 'this body has no producer registered')}")
    rasters = frozenset(json.loads(path.read_text())["rasters"])
    for raster in sorted(rasters):
        _require_known(raster)
    _require_coherent(body, rasters)
    return rasters


def rasters_off(rasters: frozenset[str]) -> list[str]:
    """Which of the vocabulary this planet stage did NOT emit, sorted — one stage's freshness record.

    THE ONES THAT ARE OFF, NEVER THE ONES THAT ARE ON, exactly as `bodies.layers_off` does it and
    for the same measured reason, which that function holds. Earth emits all three, so its list is
    empty and nothing enters its recipe.
    """
    return sorted(KNOWN_RASTERS - rasters)
