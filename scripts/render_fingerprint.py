"""Every recipe this pipeline records, computed from the code and nothing else.

`block_render.params` opens with the definition of a recipe: "everything that can move a raytraced
pixel and is not a file with an mtime". A warped source moves an mtime and the freshness machinery
tracks it; a constant moves nothing at all, so only a recipe can see it.

Most stages that write an output write one beside it, and two lanes do not. `pipeline/fuse/` records
nothing and resumes on file existence, so a moved constant there leaves the heightfield every pixel
derives from reading fresh; the 203-country hero lane records nothing either, for the same reason.
Neither can appear below, and their absence is not visible from what does.

Collecting the rest answers, without the 1.1 TB store and without a GPU, whether a change moved a
recorded constant. A changed fingerprint names the stages and fields, and the cost of the pass that
owes is in PROCESS.md § The planet tile pipeline.

Read in one direction only, which is the limit of the instrument. A moved fingerprint proves a
re-render is owed. An unmoved fingerprint proves only that no recorded constant moved, and not that
the output is unchanged, because a recipe is the constants and never the arithmetic consuming them.
Measured rather than reasoned: changing `seaice.ice_alpha` from its smoothstep to a linear ramp
moves every sea-ice pixel on Earth by up to 0.0797 alpha, 20.3 DN of white coverage at the worst
frequency, and leaves this fingerprint byte-identical. `ICE_LO`, `ICE_BAND` and `ICE_MAX_ALPHA` are
all faithfully recorded; the curve they are fed into is not a constant and reaches no recipe.

The arithmetic is `scripts/pixel_baseline`'s, which runs the shipped look producers on a fixture and
digests what they compute, so the sea-ice change above arrives there as a red. It reaches the look
layers and neither the fuse lane, the warp, nor the Blender rig. An earlier instrument for the same
question was built and deleted the same day, its samples having called the transforms differently
from production in eight confirmed places, so a row recorded a law nobody ships; what makes the
replacement a different thing is that production makes the call, from its own dispatch.
→ HISTORY, *the curve fingerprint is deleted the day it landed*.

Run it as a module, from the repo root. A script under `scripts/` that imports `pipeline` cannot be
run by path: Python puts the script's own directory on `sys.path`, not the root, so `pipeline` is
not importable and the failure is an ImportError at line one.

    uv run python -m scripts.render_fingerprint            # print it
    uv run python -m scripts.render_fingerprint --write    # regenerate the committed baseline

Two inputs are held fixed because they come from data rather than from code, and each is a stated
limit rather than an oversight:

  * `blocks`. `block_plan.plan` sizes every block's context from the real relief, so the block list
    is a fact about the terrain. Held empty, and the gap that leaves is that a change that alters only
    terrain-derived block geometry moves no field here. Nothing in this repo currently does that
    without also moving a constant, but the day one does, this will read green.
  * `rasters`. Production passes `planet_seam.declared(body)`, which reads what a producer wrote and
    raises on a clone. Held at `layers.PLANET_LAYERS`, the full code-side vocabulary, which is the
    deterministic stand-in AND the useful one: `layers_off` then reflects what the BODY refuses,
    which is a code fact, so a body that stops declaring a layer still shows up.

`scene_build.rig_recipe` is not called here and is not missing. It cannot be imported outside
Blender (`import bpy`), and `block_render.rig_recipe` is its one venv-side caller, stubbing bpy
itself and returning the same dict. Calling that reaches both, which is why the stub has one owner
and this file does not become a second.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pipeline import bodies, layers
from pipeline.acquire.mars import download_nomenclature, download_sim3292
from pipeline.compose import (
    countries_pmtiles,
    features_geojson,
    features_pmtiles,
    vector_cut,
)
from pipeline.look import palette, viking_luma
from pipeline.tile import block_render, cap_raytrace, cap_render, relief_scan

BASELINE = Path(__file__).resolve().parents[1] / "tests" / "render_fingerprint.json"

#: The one spelling of how to regenerate, because the test's failure message ends with it and a
#: second copy would be the one that goes stale. Module form, for the reason in the docstring.
REGENERATE = "uv run python -m scripts.render_fingerprint --write"

#: Where the measured cost of a moved recipe lives, cited by heading and never by copying a
#: duration: PROCESS.md is the authority. It lives here rather than in the test that prints it,
#: because `test_doc_pointers` scans `pipeline`, `scripts` and `web/scripts` and not `tests` — so
#: stated there, a heading that got renamed would go unnoticed by the guard built to catch exactly
#: that.
OWED_PASS = "PROCESS.md § The planet tile pipeline"

#: See the module docstring. Empty rather than a synthetic list, so the recorded value is visibly
#: "no blocks" instead of a plausible number nobody derived.
FIXED_BLOCKS: list[Any] = []

#: The full code-side vocabulary, standing in for what a producer declares at run time.
FIXED_RASTERS = layers.PLANET_LAYERS

#: `viking_luma`'s recipe records the fraction of valid pixels in the Viking mosaic, which is
#: measured off the raster. Pinned so this file stays a function of the code; a change to the
#: RECIPE's shape still shows, a change to the measurement is not this instrument's subject.
FIXED_VALID_FRACTION = 1.0


def _as_dict(recipe: str | dict[str, Any]) -> dict[str, Any]:
    """Recipes are written as JSON text by some stages and as dicts by others."""
    return json.loads(recipe) if isinstance(recipe, str) else recipe


def fingerprint() -> dict[str, dict[str, Any]]:
    """Every recipe, keyed by the stage that writes it, ordered for a readable diff.

    Round-tripped through JSON before it is returned, which is not tidiness. `rig_recipe` holds
    tuples for the rotations and colour stops, and JSON has no tuple: the committed file reads them
    back as lists, so a raw comparison against a freshly built dict disagrees on every rig field
    forever while nothing has moved. Normalising here means the caller compares what would actually
    be written.
    """
    recorded: dict[str, dict[str, Any]] = {
        "acquire/mars/download_nomenclature": _as_dict(download_nomenclature.build_recipe()),
        "acquire/mars/download_sim3292": _as_dict(download_sim3292.build_recipe()),
        "compose/features_geojson": _as_dict(features_geojson.recipe()),
        "compose/vector_cut:countries": _as_dict(vector_cut.recipe(countries_pmtiles.CUT)),
        "compose/vector_cut:features": _as_dict(vector_cut.recipe(features_pmtiles.CUT)),
        "look/viking_luma": _as_dict(viking_luma.build_recipe(FIXED_VALID_FRACTION)),
    }
    # Per body, because a look constant reaches one body's tiles and not the other's, and a
    # fingerprint over Earth alone would go green on every Mars-only move.
    # The rig gets NO entry of its own. `block_render.params` embeds it and so does
    # `cap_raytrace.params`, and those two are its only callers in the pipeline, so a third copy
    # here would report one moved field three times and add nothing a reader could act on.
    for body in (bodies.EARTH, bodies.MARS):
        recorded[f"tile/block_render:{body.name}"] = _as_dict(
            block_render.params(body, FIXED_RASTERS, palette.look_for(body.name),
                                block_render.rig_recipe(body), FIXED_BLOCKS))
        recorded[f"tile/relief_scan:{body.name}"] = _as_dict(
            relief_scan.params(body, FIXED_RASTERS))
        for grid in (cap_render.north_grid(body), cap_render.south_grid(body)):
            recorded[f"tile/cap_raytrace:{body.name}:{grid.name}"] = _as_dict(
                cap_raytrace.params(grid, FIXED_RASTERS))
    return json.loads(json.dumps(dict(sorted(recorded.items()))))


#: What `fingerprint()` must return, so a producer silently dropping out is a red test rather than
#: a stage that agrees with its baseline forever. 6 body-independent, plus per body the block
#: recipe, the relief scan and the two caps.
STAGE_COUNT = 6 + 2 * 4


def serialise(recorded: dict[str, dict[str, Any]]) -> str:
    """Stable bytes: sorted keys and a trailing newline, so a diff shows only real movement."""
    return json.dumps(recorded, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true",
                        help=f"regenerate tests/{BASELINE.name} instead of printing")
    args = parser.parse_args(argv)
    text = serialise(fingerprint())
    if not args.write:
        print(text, end="")
        return 0
    unchanged = BASELINE.exists() and BASELINE.read_text(encoding="utf-8") == text
    BASELINE.write_text(text, encoding="utf-8")
    print(f"{BASELINE.relative_to(BASELINE.parents[1])}: "
          f"{'unchanged' if unchanged else 'REWRITTEN — commit it with this change'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
