"""What images a render directory holds, declared by the stage that filled it.

`planet_seam` ONE TIER DOWN, AND FOR THE SAME REASON. That module exists because
`(planet / "planet_oceanmask.vrt").exists()` cannot tell "this planet has no sea" from "the
producer died two rasters in". A render directory has the identical problem one step later: the rig
loads six images out of it, two of which its producers legitimately skip, and `Path.exists()` is the
only thing that has ever decided which. Skipped and crashed look the same on disk.

STDLIB ONLY, AND THAT IS A HARD CONSTRAINT RATHER THAN A PREFERENCE. `scene_build` runs inside
Blender's interpreter, which cannot import this project's virtual environment — that is why the rig
takes a body SLUG and not a `Body`. So this module may not import `bodies`, `layers` or
`planet_seam`, and cannot answer any question that needs them. It records filenames, which is
exactly what both interpreters can agree about.

WHICH IS ALSO WHY THE PRODUCER DECLARES RATHER THAN THE RIG DERIVING. Whether a planet has inland
water is `planet_seam.declared(body)`, one tier down and out of Blender's reach; whether this
particular block happened to contain any snow is a measurement only the prep made. Both facts reach
the rig the same way: whoever filled the directory writes down what it put there.

    from pipeline.render import render_seam
    present = render_seam.declared(render_dir)      # raises if the prep never finished
    if render_seam.SNOWMASK in present: ...
"""

import json
from collections.abc import Iterable
from pathlib import Path

#: The rig's four mandatory images. A directory missing one of these is not a partial scene.
HEIGHTFIELD = "heightfield_aea.tif"
OCEANMASK = "oceanmask_aea.png"
INLANDLAKE = "inlandlake_aea.png"
RIVER = "river_aea.png"

#: The two a prep may legitimately not write, being a measurement of the region rather than of the
#: planet: a block with no snow in it and a block with no lake bed in it.
SNOWMASK = "snowmask_aea.png"
LAKEDEPTH = "lakedepth_aea.tif"

#: Every image a render directory may hold, and the whole vocabulary a declaration may name.
#:
#: THE ONE OWNER FOR THESE SPELLINGS, which is what makes the `_aea` suffix a single edit rather
#: than the nine-file sweep it is today. `scene_build.IMAGES` reads them from here rather than
#: restating them, on the rule that a second reader with no owner is the defect.
KNOWN_IMAGES = frozenset({HEIGHTFIELD, OCEANMASK, INLANDLAKE, RIVER, SNOWMASK, LAKEDEPTH})

#: The file every stage that fills a render directory records itself in.
DECLARATION_NAME = "render_inputs.json"

#: The stages that fill a render directory, as they name themselves in the declaration.
#:
#: ONE RECORD PER STAGE AND NOT ONE PER DIRECTORY, because the two paths into this directory have
#: different shapes. A block is filled by ONE producer in one pass, which could simply write last.
#: A country is filled by THREE — `render_prep`, then `snow_mask`, then `lake_mask` — and no one of
#: them knows what the others did, so a single sealing write would have to end with the last stage
#: guessing at the first two's output. Per stage, each says only what it emitted, and an EMPTY list
#: is the statement that matters: "I ran over this region and produced nothing" is exactly the fact
#: a missing file cannot carry.
PREP, SNOW, LAKE, BLOCK = "prep", "snow", "lake", "block"
KNOWN_STAGES = frozenset({PREP, SNOW, LAKE, BLOCK})


def declaration_path(render_dir: Path) -> Path:
    """Where a render directory records what its stages put in it."""
    return render_dir / DECLARATION_NAME


def _require_known(image: str) -> None:
    """A filename outside the vocabulary is a typo, and a typo must not read as an absence."""
    if image not in KNOWN_IMAGES:
        known = ", ".join(sorted(KNOWN_IMAGES))
        raise ValueError(f"unknown render input {image!r}; known images are: {known}")


def _records(render_dir: Path) -> dict[str, list[str]]:
    """Every stage's record for this directory, or an empty mapping if none has written yet."""
    path = declaration_path(render_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text())["stages"]


def declare(render_dir: Path, stage: str, images: Iterable[str]) -> Path:
    """Record what `stage` emitted here. CALL LAST within that stage, once its images are on disk.

    THE ORDERING IS THE CONTRACT, exactly as `planet_seam.declare` holds it: a stage's record is
    what says that stage finished. Written before its images, it promises files a crash may never
    deliver, and the guarantee it exists to give is gone.

    Each named image is checked onto disk before the name is written, because a declaration is only
    worth trusting about what is MISSING if it can be trusted about what is present. Re-running one
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
    stages = _records(render_dir)
    stages[stage] = named
    path = declaration_path(render_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"stages": dict(sorted(stages.items()))}, indent=2) + "\n")
    return path


def declared(render_dir: Path) -> frozenset[str]:
    """Every image this directory holds, unioned over the stages that filled it. Raises if none did.

    RAISES RATHER THAN FALLING BACK TO A DIRECTORY LISTING, which is the point of the module: a
    listing is a statement about the filesystem where this is a statement about the stages. The two
    agree right up until the run that matters.

    THE HEIGHTFIELD IS THE COMPLETION TEST because only a first stage writes one — `render_prep` for
    a country, `prep_block` for a block — so its presence in the union means some stage filled this
    directory rather than merely touching it. WHETHER THE WHOLE CHAIN RAN IS NOT ASKED HERE: that is
    `batch.py`'s question, which sequences the stages and stops on the first one that fails, and a
    rig that re-litigated it would need to know which chain was supposed to run.
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
            f"fills this directory (`render_prep.py` for a country, `prep_block.py` for a block); "
            f"stages that have spoken: {sorted(stages) or 'none'}")
    return images
