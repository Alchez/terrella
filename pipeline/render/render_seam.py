"""What images a render directory holds, declared by the stage that filled it.

`planet_seam` one tier down, and for the same reason: the rig loads several images out of a render
directory, some of which its producers legitimately skip, and `Path.exists()` is the only thing that
has ever decided which. Skipped and crashed look the same on disk. The standing brief owns the rule
and names both tiers.

No counts in that sentence, deliberately: a total is a fact about `KNOWN_IMAGES` below, and nothing
goes red when the set and the prose disagree.

Stdlib only, and that is a hard constraint rather than a preference. `scene_build` runs inside
Blender's interpreter, which cannot import this project's virtual environment, which is also why the
rig takes a body slug and not a `Body`. So this module may not import `bodies`, `layers` or
`planet_seam`, and cannot answer any question that needs them. It records filenames, which is
exactly what both interpreters can agree about.

    from pipeline.render import render_seam
    present = render_seam.declared(render_dir)      # raises if the prep never finished
    if render_seam.SNOWMASK in present: ...
"""

import json
from collections.abc import Iterable
from pathlib import Path

#: The rig's four mandatory images. A directory missing one of these is not a partial scene.
HEIGHTFIELD = "heightfield.tif"
OCEANMASK = "oceanmask.png"
INLANDLAKE = "inlandlake.png"
RIVER = "river.png"

#: The three a prep may legitimately not write, being measurements of the region rather than of
#: the planet: a block with no snow in it, no lake bed in it, or no sea ice on its ocean. The ice
#: image is a continuous 0..1 alpha, already confined to ocean pixels by the prep that cut it.
SNOWMASK = "snowmask.png"
LAKEDEPTH = "lakedepth.tif"
SEAICE = "seaice.png"

#: The per-row Mercator correction, one pixel wide and as tall as the plane. Named beside the three
#: optional images above but unlike them in kind: those are absent when a region has no snow or no
#: lake bed to measure, where this is a property of the projection. So the block path always writes
#: one and the hero path, which is not in Mercator at all, never does.
ROWSCALE = "rowscale.tif"

#: Prep byproducts on the hero path: analytical masks the post stages read and the rig never
#: loads, which is why they are named here but stay outside the declaration vocabulary below.
OCEANMASK_TIF = "oceanmask.tif"
WATERMASK = "watermask.tif"

#: The whole vocabulary a declaration may name.
#:
#: The one owner for these spellings, on the rule that a second reader with no owner is the defect.
#: No projection suffix: the hero path writes Albers cuts and the block path writes EPSG:3857 ones
#: under these same names, so no such suffix can be true for both writers.
KNOWN_IMAGES = frozenset({HEIGHTFIELD, OCEANMASK, INLANDLAKE, RIVER, SNOWMASK, LAKEDEPTH, SEAICE,
                          ROWSCALE})

#: The file every stage that fills a render directory records itself in.
DECLARATION_NAME = "render_inputs.json"

#: The stages that fill a render directory, as they name themselves in the declaration.
#:
#: One record per stage and not one per directory, because the two paths into this directory have
#: different shapes: a block is filled by one producer in one pass, and a country by three that do
#: not know each other's output, so a single sealing write would end with the last stage guessing at
#: the first two's. Each stage says only what it emitted, and an empty list is the statement that
#: matters, being the one fact a missing file cannot carry.
PREP, SNOW, LAKE, BLOCK, CAP = "prep", "snow", "lake", "block", "cap"

#: Which tool fills a directory under each stage, so a message telling someone to re-run the prep
#: can name it. A mapping rather than the preps enumerated in prose inside each error message, which
#: goes quietly incomplete the moment a stage is added and then tells the reader to re-run a tool
#: that cannot fill their directory. Derived, a stage without an owner is a failing test instead.
STAGE_TOOL: dict[str, str] = {PREP: "render_prep.py", SNOW: "snow_mask.py",
                              LAKE: "lake_mask.py", BLOCK: "prep_block.py", CAP: "prep_cap.py"}

KNOWN_STAGES = frozenset(STAGE_TOOL)


def first_stage_tools() -> str:
    """The tools that WRITE A HEIGHTFIELD, named for a reader who has to re-run one.

    Only a first stage writes one — the other stages add masks to a directory that already exists —
    so this is the answer to "the prep never ran", which is the only question the message asks.
    """
    return ", ".join(f"`{STAGE_TOOL[stage]}`" for stage in (PREP, BLOCK, CAP))


def declaration_path(render_dir: Path) -> Path:
    """Where a render directory records what its stages put in it."""
    return render_dir / DECLARATION_NAME


def _require_known(image: str) -> None:
    """A filename outside the vocabulary is a typo, and a typo must not read as an absence."""
    if image not in KNOWN_IMAGES:
        known = ", ".join(sorted(KNOWN_IMAGES))
        raise ValueError(f"unknown render input {image!r}; known images are: {known}")


#: The images that are a mask rather than a picture, so something has to say what colour they are
#: painted. The paint is the BODY's, and the rig cannot ask for it: `layer_producers` holds each
#: body's answer and pulls in rasterio and GDAL, where `scene_build` runs in Blender's interpreter.
#: So the prep, which has both the registry and the window, resolves it and writes it here.
PAINTED_IMAGES = frozenset({SNOWMASK, SEAICE})

#: One 8-bit sRGB colour on the wire. Spelled here rather than imported from `palette`, which owns
#: the identical alias: `palette` is Blender-shared, and that set is exactly three files, pinned by
#: `scripts/check_blender_drift.sh`. Borrowing a type name is not worth widening it to four.
RGB8 = tuple[int, int, int]

#: The `(sunlit, shadowed)` pair a mask is painted in.
#:
#: `LayerProducer.paint` answers `tuple[Any, Any]` and must keep doing so: a body may vary its
#: colour across a window, as Mars does per pole. This is what survives the reduction to a value a
#: shader socket can hold, so `prep_block.one_colour` between them is a check and never a cast.
Paint = tuple[RGB8, RGB8]


def _document(render_dir: Path) -> dict:
    """The whole declaration for this directory, or an empty one if no stage has written yet."""
    path = declaration_path(render_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _write(render_dir: Path, document: dict) -> Path:
    """Persist a declaration, keeping its two halves in one file and one existence question."""
    path = declaration_path(render_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return path


def _records(render_dir: Path) -> dict[str, list[str]]:
    """Every stage's record for this directory, or an empty mapping if none has written yet."""
    return _document(render_dir).get("stages", {})


def declare(render_dir: Path, stage: str, images: Iterable[str]) -> Path:
    """Record what `stage` emitted here. Call last within that stage, once its images are on disk.

    The ordering is the contract, exactly as `planet_seam.declare` holds it: a stage's record is
    what says that stage finished. Written before its images, it promises files a crash may never
    deliver, and the guarantee it exists to give is gone.

    Each named image is checked onto disk before the name is written, because a declaration is only
    worth trusting about what is missing if it can be trusted about what is present. Re-running one
    stage rewrites only its own record, so a resumed chain does not erase the stages behind it.
    """
    if stage not in KNOWN_STAGES:
        raise ValueError(f"unknown stage {stage!r}; known stages are: {', '.join(KNOWN_STAGES)}")
    named = sorted(set(images))
    for image in named:
        _require_known(image)
    absent = [image for image in named if not (render_dir / image).exists()]
    if absent:
        raise FileNotFoundError(
            f"{render_dir}: {stage} is declaring images that are not on disk: {', '.join(absent)}")
    document = _document(render_dir)
    stages = document.get("stages", {})
    stages[stage] = named
    document["stages"] = dict(sorted(stages.items()))
    return _write(render_dir, document)


def declare_paint(render_dir: Path, image: str, sunlit: RGB8, shadowed: RGB8) -> Path:
    """Record the colour pair `image`'s mask is painted in, as the stage that resolved it.

    The pair travels whole though today's rig reads only `sunlit`: the rig lets Cycles produce the
    shaded end from light, which is how a body's authored shadow hue stopped reaching a raytraced
    pixel, and dropping the half in question here would make it unrecoverable.

    Order against `declare` does not matter — both halves live in one document and each writer
    preserves the other's.
    """
    _require_known(image)
    if image not in PAINTED_IMAGES:
        painted = ", ".join(sorted(PAINTED_IMAGES))
        raise ValueError(f"{image!r} is not a painted mask; paintable images are: {painted}")
    document = _document(render_dir)
    paints = document.get("paints", {})
    paints[image] = {"sunlit": [int(channel) for channel in sunlit],
                     "shadowed": [int(channel) for channel in shadowed]}
    document["paints"] = dict(sorted(paints.items()))
    return _write(render_dir, document)


def paint_for(render_dir: Path, image: str) -> Paint:
    """The `(sunlit, shadowed)` colours `image` is painted in here. Raises if nothing declared one.

    Never add a default. A rig that fell back to a constant would render one body in another's
    white with no missing file, no failed stage and every gate green — the failure this seam exists
    to make impossible.
    """
    _require_known(image)
    paint = _document(render_dir).get("paints", {}).get(image)
    if paint is None:
        raise FileNotFoundError(
            f"{declaration_path(render_dir)}: no stage declared what {image} is painted in. "
            f"The colour is the BODY's, resolved from its producer registry by the prep that cut "
            f"this directory — re-run that prep ({first_stage_tools()}, plus "
            f"`{STAGE_TOOL[SNOW]}`/`{STAGE_TOOL[LAKE]}` for a country's optional masks). Rendering "
            f"without it would paint this body in whichever white was authored first.")
    def triple(end: str) -> RGB8:
        red, green, blue = paint[end]
        return red, green, blue
    return triple("sunlit"), triple("shadowed")


def declared(render_dir: Path) -> frozenset[str]:
    """Every image this directory holds, unioned over the stages that filled it. Raises if none did.

    Raises rather than falling back to a directory listing, which is the point of the module: a
    listing is a statement about the filesystem where this is a statement about the stages, and the
    two agree right up until the run that matters.

    The heightfield is the completion test, because only a first stage writes one, so its presence
    in the union means some stage filled this directory rather than merely touching it. Whether the
    whole chain ran is `batch.py`'s question, which sequences the stages and stops on the first
    failure; a rig re-litigating it would need to know which chain was supposed to run.
    """
    stages = _records(render_dir)
    for stage in sorted(stages):
        if stage not in KNOWN_STAGES:
            raise ValueError(f"{declaration_path(render_dir)} names unknown stage {stage!r}")
    images = frozenset(image for named in stages.values() for image in named)
    for image in sorted(images):
        _require_known(image)
    if HEIGHTFIELD not in images:
        raise FileNotFoundError(
            f"{declaration_path(render_dir)}: no stage has declared {HEIGHTFIELD} in {render_dir}. "
            f"A stage's record is written after its images, so this means the prep never ran or "
            f"died partway — the images beside it, if any, cannot be trusted. Re-run the prep that "
            f"fills this directory ({first_stage_tools()}); "
            f"stages that have spoken: {sorted(stages) or 'none'}")
    return images
