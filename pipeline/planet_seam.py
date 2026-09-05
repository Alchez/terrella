"""What a body's planet stage produced, declared by the stage that produced it.

The seam every body enters through. Earth's planet rasters come out of a 648-cell fusion, Mars's out
of a CRS relabel of one published file, and both write the same three-named set into
`data/work/<body>/planet/`, where everything downstream reads them without caring which producer
ran: the 3857 warps, the block raytrace, both polar caps.

A declaration and not a directory listing, which is the whole reason this module exists. Downstream
stages need to know whether this body has an ocean mask, and the tempting answer,
`(planet / "planet_oceanmask.vrt").exists()`, is wrong in a way nothing reports:

  * Absence is not a statement. A missing mask cannot distinguish "this planet has no sea" from
    "the producer died two rasters in". The first is a fact to render against; the second is a
    half-built planet that must never be shaded, and they look identical on disk.
  * Absence is also invisible to freshness. `freshness.newest_mtime` scores a missing path 0.0, so
    a raster that goes away stops being a dependency at the same moment it stops being an input,
    and turning a sea off leaves the old sea-painted raster looking perfectly fresh.

So the producer states what it emitted, and it states it last. The declaration's presence is the
stage's completion stamp, carrying content where the `.done` idiom one tier up carries none, and its
content is the body fact. A crashed producer writes none and every consumer refuses to run; a
complete one is trusted about what it does not have.

Rasters, never "layers": `layers.py` owns that word for the optional things the render paints over
the heightfield, where these three are the heightfield and the masks that classify it. The rule
beside this file holds the two vocabularies apart and says what each costs to add.

    from pipeline import planet_seam
    rasters = planet_seam.declared(body)     # raises if the producer never finished
    if "oceanmask" in rasters: ...
"""

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from xml.etree import ElementTree

from pipeline import bodies, layers

#: The rasters a planet stage may emit, in the order a producer builds them.
#:
#: `heightfield` is the elevation the whole pipeline shades. `oceanmask` is the 0/1 land/sea split
#: that chooses between the land and sea ramps; `watermask` is the 4-class code (0 land, 1 ocean,
#: 2 inland lake, 3 inland river) that selects inland water and keys the lake bathymetry off it.
#:
#: A tuple and not a set, because producers iterate it and the order they build in is the order
#: they report in. Membership tests take `KNOWN_RASTERS` below.
PLANET_RASTERS = ("heightfield", "oceanmask", "watermask")

KNOWN_RASTERS = frozenset(PLANET_RASTERS)

#: The file the producer writes last, beside the rasters it names.
DECLARATION_NAME = "planet_rasters.json"

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
    for layer, raster in sorted(layers.LAYER_REQUIRES_RASTER.items()):
        if layer in body.surface_layers and raster not in rasters:
            raise ValueError(
                f"{body.name}: declares the {layer!r} surface layer but its planet stage emitted no "
                f"{raster!r} — see layers.LAYER_REQUIRES_RASTER for why that layer cannot be "
                f"computed without it. Either the producer is incomplete or the body's "
                f"surface_layers are")


#: How far two planet rasters' bounds may differ and still count as the same ground, in degrees.
#: Set by what is INVISIBLE rather than by float noise: 1e-7 degrees is about 1 cm, four orders
#: below the 10-arcsec pixel this seam's coarsest raster uses, so a real shift always trips it while
#: the round-trip through a VRT's decimal GeoTransform never does. Same reasoning as
#: `freshness.grid_matches`' 1 m tolerance under a 305 m pixel.
GRID_TOLERANCE_DEG = 1e-7


def _grid_of(path: Path) -> tuple[int, int, tuple[float, float, float, float]]:
    """`(width, height, bounds)` read out of a VRT's own XML.

    Parsed rather than opened, so this module stays stdlib-only. `pipeline/render/prep_block.py`
    imports it and runs inside Blender's interpreter, which has no rasterio, and a GDAL dependency
    here would be discovered at the first block of a production pass rather than at import.

    A VRT with no `GeoTransform` RAISES rather than being skipped. Skipping would make a malformed
    file the one input that disarms the check that exists to read it.
    """
    root = ElementTree.parse(path).getroot()
    width = int(root.get("rasterXSize", 0))
    height = int(root.get("rasterYSize", 0))
    element = root.find("GeoTransform")
    if not width or not height or element is None or not element.text:
        raise ValueError(
            f"{path} carries no usable grid (size {width}x{height}, "
            f"GeoTransform {'absent' if element is None else 'empty'}) — a planet raster must "
            f"state the ground it covers, and one that cannot is not a raster this seam can declare")
    origin_x, pixel_w, _, origin_y, _, pixel_h = (float(v) for v in element.text.split(","))
    return width, height, (origin_x, origin_y + height * pixel_h,
                           origin_x + width * pixel_w, origin_y)


def _require_nested_grids(body: bodies.Body, rasters: Iterable[str]) -> None:
    """Refuse a set whose rasters do not sit on nested grids — same bounds, whole-number size ratio.

    Not "all three must match", and the difference is deliberate: `prep_block` reads the heightfield
    and the ocean mask independently, the mask picking the material and the heightfield driving
    displacement, so they are allowed to carry different detail, and the masks are refined in
    latitude alone to take the high-latitude coastline lattice out of the delivered pixels. What
    they may not do is straddle: pixel edges that fall between each other put the mask's coast a
    fraction of a pixel off the terrain it classifies, on every warp, systematically and silently.

    Identical bounds plus a whole-number ratio per axis is exactly the condition that every coarse
    edge lands on a fine one. Either direction passes, because which raster is finer is a producer's
    choice and only the alignment is a correctness claim.

    The heightfield is the reference because `_require_coherent` has already refused a set without
    one, and because it is what `planet_warp` measures the 3857 reference grid from.

    Write-side only, unlike `_require_coherent` next door, and the asymmetry is the point: that one
    is re-checked on read because the layer registry can gain an entry months after a declaration is
    written, so the same file becomes incoherent without anything touching it. A grid cannot, moving
    only when a producer re-runs, and a producer that re-runs writes this file again.
    """
    named = sorted(set(rasters))
    if "heightfield" not in named:
        return
    reference = _grid_of(vrt_path(body, "heightfield"))
    ref_width, ref_height, ref_bounds = reference
    for raster in named:
        if raster == "heightfield":
            continue
        width, height, bounds = _grid_of(vrt_path(body, raster))
        if any(abs(a - b) > GRID_TOLERANCE_DEG for a, b in zip(bounds, ref_bounds)):
            raise ValueError(
                f"{body.name}: {raster!r} covers different ground from the heightfield — bounds "
                f"{bounds} against {ref_bounds}. Every 3857 warp reads them onto one grid, so a "
                f"planet declared like this classifies terrain it is not sitting on")
        for axis, (size, ref_size) in (("width", (width, ref_width)),
                                       ("height", (height, ref_height))):
            larger, smaller = max(size, ref_size), min(size, ref_size)
            if smaller == 0 or larger % smaller:
                raise ValueError(
                    f"{body.name}: {raster!r} does not nest inside the heightfield's grid — "
                    f"{axis} {size} against {ref_size}, a ratio of {larger / smaller:.4g} rather "
                    f"than a whole number. A mask may be finer than the terrain it classifies, but "
                    f"its pixel edges must fall on the terrain's or its coast lands a fraction of "
                    f"a pixel off, on every warp and with nothing to report it")


def write_vrt_if_changed(vrt: Path, build: Callable[[Path], None]) -> bool:
    """Have `build` write `vrt`, and replace the file on disk only when the XML actually differs.

    Not an optimisation: it is what makes a producer safe to re-run at all. Every 3857 warp
    downstream is gated on the VRT's mtime, so an unconditional overwrite restages the whole planet:
    on Earth that is a 44 GB re-warp and then every block back through Cycles, to reproduce pixels
    that were already correct. Re-indexing is the natural thing to do after touching a producer, so
    that cost sat one command away from anyone who tried. PROCESS.md holds the figure.

    Byte-identity is what makes the comparison mean anything, and it was measured rather than
    assumed: rebuilding all three of Earth's planet VRTs from the same 648 chunks, into the same
    directory, reproduced the live files' SHA-256 exactly (GDAL 3.12.2).

    The scratch target shares the VRT's directory, and that is load-bearing rather than tidy: GDAL
    writes source paths relative to the VRT, so building somewhere else and moving the result
    rewrites every one of them and the comparison can never come out equal.

    Shared by both producers: Earth's builds a 648-source mosaic index with `gdalbuildvrt`; Mars's
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
    """Record what this body's planet stage emitted. Call last, after every raster is on disk.

    The ordering is the contract rather than a convention: this file's existence is what tells every
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
    _require_nested_grids(body, named)
    path = declaration_path(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rasters": named}, indent=2) + "\n")
    return path


def declared(body: bodies.Body) -> frozenset[str]:
    """Which planet rasters this body has, as its producer declared them. Raises if it never ran.

    Raises rather than returning an empty set, and that is the point of the whole module: an empty
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

    The ones that are off and never the ones that are on, exactly as `bodies.layers_off` does it and
    for the same measured reason, which that function holds. Earth emits all three, so its list is
    empty and nothing enters its recipe.
    """
    return sorted(KNOWN_RASTERS - rasters)
