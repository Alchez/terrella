"""Render one polar cap through Cycles: a ring of rigidly rotated passes, blended by longitude.

WHY A RING AT ALL. The cap's light turns per pixel — `cap_render.azimuth_delta` added to both the
key and the fill — so the disc stays lit north-west of LOCAL north as the meridians converge on the
pole. Cycles takes one sun direction per frame and cannot do that, so the disc is rendered at
`CAP_AZIMUTH_PASSES` fixed bearings and every pixel is cross-faded between the two that bracket the
one it wants. Same law, read from its owner rather than imitated at one remove.

WHY EACH PASS IS FOUR FRAMES. `CAP_PX` in a single frame is OOM-killed at the heavy-job cap, so the plane
is photographed `CAP_QUADRANT_SPLIT` squared times. The neighbours are literally the same plane, so
terrain outside a quadrant still casts into it and there is no context margin to buy.
The stitch was controlled: geometry correlation 0.99327 against a full-disc render, and a join at
the 89.4th percentile of the image's own column means.

WHY 28 FRAMES A POLE AND NOT 96. A quadrant spans a quarter of the longitude circle, so seventeen of
the twenty-four contain no pixel it will ever sample. Which seven is DERIVED off the same grid the
blend reads: getting it wrong does not crash, it leaves those pixels unlit in a disc that stitches.

    python -m pipeline.tile.cap_pass --body earth --north
"""
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

from pipeline import bodies, freshness, layers, paths, planet_seam, progress
from pipeline.look import layer_producers
from pipeline.render import blender_proc, prep_block, prep_cap, render_seam
from pipeline.tile import block_render, cap_render

#: Bearings the ring is rendered at, evenly spaced. RATIFIED AT 24 on both poles against 12 and 1:
#: the blend's worst case is a pixel at the midpoint between two passes, and that error falls with
#: the step. → HISTORY, *both caps raytraced at edge 84*, which carries the measurement.
CAP_AZIMUTH_PASSES = 24

#: Where OIDN runs for a cap, which is the HERO lane's answer and not the block lane's. A quadrant
#: frame is 4096 squared against a block's 2048, and the 12 GB card faults when render and denoise
#: contend at that size — the rule CLAUDE.md states for 8K heroes, reaching the cap for the same
#: reason. The judged discs were rendered this way.
CAP_DENOISE_DEVICE = "cpu"

#: A cap's plane is 8192 px photographed at 4096, so `base_patches` asks for 2 and adaptive
#: subdivision reaches one micropolygon per pixel. Unlike a hero's, this plane is mostly off-camera
#: in every frame, so it sits with the blocks rather than past the OptiX wall heroes fail at.
CAP_BASE_GRID = "fitted"

#: The recipe that decides whether frames already on disk describe the disc being rendered now.
#: Beside the frames rather than beside the disc, because it answers a question about THEM.
FRAMES_RECIPE_NAME = "cap_frames_params.json"


def azimuth_step() -> float:
    """Degrees between neighbouring passes on the ring."""
    return 360.0 / CAP_AZIMUTH_PASSES


def frames_dir(grid: cap_render.CapGrid) -> Path:
    """Where this pole's rendered ring lives. Kept across a run, which is what makes it resumable.

    NAMED FOR THE POLE ALONE, WHICH IS WHAT MAKES A REDUCED-`px` PREVIEW UNSAFE IN THE LIVE STORE.
    `grid.px` is a field, so a disc renders at any side and a 1024 px one costs about a minute
    against the shipped disc's twenty. But this path does not vary with it while `params` DOES
    record it, so a preview writes its frames over the shipped disc's own and then moves the recipe
    that declares them stale. Give a preview its own `MAPS_DATA`, and its own checkout too, since
    `cap_render.caps_public_dir` follows `paths.ROOT` rather than the store.
    """
    return cap_render.cap_work_dir(grid.body) / f"frames_{grid.name}"


def frame_path(grid: cap_render.CapGrid, quadrant: tuple[int, int], index: int) -> Path:
    """One rendered frame: this quadrant of the plane, lit at this pass's bearing.

    NAMED BY PASS INDEX RATHER THAN BY DEGREES, because the index is what the blend looks a pixel up
    by. A degree spelling would also have to decide what to do when the step stops being a whole
    number, and the step is free to move -- it rides in the recipe, so it takes every frame with it.
    """
    row, col = quadrant
    return frames_dir(grid) / f"cap_{grid.name}_r{row}c{col}_a{index:02d}.png"


def bracketing_pass(grid: cap_render.CapGrid,
                    longitude: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per pixel: the pass below the bearing it wants, and how far it is toward the next one.

    The wanted bearing is the law's own expression. `cap_render.azimuth_delta` is what the rig adds
    to both azimuths; our frames sit at `AZ + index * step`, so the delta a pixel wants is exactly
    that same value. No fitting and no lookup: it falls out of the one law rather than imitating it.

    THE MODULO ON `lower` IS AN IEEE GUARD AND NOT THE RING'S. Wrapping the ring is the callers' —
    both spell `(lower + 1) % CAP_AZIMUTH_PASSES` for the upper neighbour. What this one catches is
    narrower and would otherwise be unreachable-looking: a delta infinitesimally below zero comes
    back from `%` as exactly 360.0 rather than 0.0, because the true remainder is too small to
    represent and rounds up. That divides to 24.0 and floors to 24, an index no frame carries.
    """
    wanted = np.asarray(cap_render.azimuth_delta(grid, longitude), dtype=np.float64) % 360.0
    position = wanted / azimuth_step()
    lower = np.floor(position).astype(int) % CAP_AZIMUTH_PASSES
    return lower, position - np.floor(position)


def quadrants() -> list[tuple[int, int]]:
    """Every (row, col) the plane is photographed as, in render order."""
    split = cap_render.CAP_QUADRANT_SPLIT
    return [(row, col) for row in range(split) for col in range(split)]


def frame_plan(grid: cap_render.CapGrid) -> dict[tuple[int, int], list[int]]:
    """Which passes each quadrant of this disc actually needs, derived from its own longitudes.

    DERIVED AND NEVER ASSUMED. Which quarter of the ring a given (row, col) holds depends on the
    AEQD convention and on the pole's `az_sign`, and the two poles disagree about the second. A plan
    written from the north's convention renders 28 correct frames for the north and 28 wrong ones
    for the south, and neither run fails.

    THE BRACKET IS INCLUSIVE AT BOTH ENDS. A pixel at the quadrant's own edge blends between the
    pass below it and the pass above, so the neighbour outside its span is needed too.

    A statement about LONGITUDES, so it does not move with the disc's resolution -- which is what
    lets `tests/test_cap_raytrace.py` plan a 256 px stand-in for an 8192 px disc.
    """
    longitude, _latitude = cap_render._lonlat_grid(grid)
    longitude = np.asarray(longitude, dtype=np.float64)
    half = grid.px // cap_render.CAP_QUADRANT_SPLIT
    plan: dict[tuple[int, int], list[int]] = {}
    for row, col in quadrants():
        lower, _frac = bracketing_pass(
            grid, longitude[row * half:(row + 1) * half, col * half:(col + 1) * half])
        present = {int(index) for index in np.unique(lower)}
        plan[(row, col)] = sorted(present | {(index + 1) % CAP_AZIMUTH_PASSES
                                             for index in present})
    return plan


def blender_command(grid: cap_render.CapGrid, render_dir: Path, blend: Path, png: Path,
                    quadrant: tuple[int, int], index: int) -> list[str]:
    """The one Blender invocation a frame needs, built rather than spelled at the call site.

    NO SYSTEMD SCOPE OF ITS OWN. `run_pass.sh` wraps the whole pass in one, and this renders inside
    the cap pass it spawns, so a scope here would nest inside the cap the operator already set.
    """
    row, col = quadrant
    return [str(paths.BLENDER), "-b", "--python",
            str(paths.ROOT / "pipeline" / "render" / "scene_build.py"), "--",
            "--body", grid.body.name, "--render-dir", str(render_dir),
            "--out", str(blend), "--render", str(png),
            "--sun-azimuth-delta", str(index * azimuth_step()),
            "--tile", f"{row},{col}",
            "--denoise-device", CAP_DENOISE_DEVICE,
            "--base-grid", CAP_BASE_GRID]


def check_echoes(stdout: str, quadrant: tuple[int, int], index: int) -> None:
    """Refuse a render that did not report doing what it was asked, naming what is missing.

    THE RECIPE BELOW WILL CLAIM ALL FOUR OF THESE, SO THE RENDER HAS TO CONFIRM THEM. Each is a flag
    whose loss is invisible on disk: a dropped sun delta renders the base bearing, a dropped tile
    photographs the whole plane at a quadrant's resolution, a dropped denoise device or base grid
    renders a frame that merely looks a little different. All four succeed, and the only surviving
    trace would be a recipe asserting settings this disc was not rendered with.

    THE VALUES ARE COMPARED, NOT MERELY THE FLAG NAMES. `--tile` arriving as a different pair is the
    failure a presence check cannot see: the frame renders, stitches, and lands under the name of
    the quadrant that was asked for.
    """
    row, col = quadrant
    wanted = (f"DENOISE_DEVICE {CAP_DENOISE_DEVICE}",
              f"SUN_AZIMUTH_DELTA {index * azimuth_step():.4f}",
              f"TILE {row},{col} ",
              f"BASE_GRID {CAP_BASE_GRID}")
    missing = [echo for echo in wanted if echo not in stdout]
    if missing:
        raise RuntimeError(
            f"r{row}c{col} pass {index}: Blender did not report back {', '.join(missing)} — the "
            f"recipe would record a frame this disc was not rendered with. Reported:\n"
            + "\n".join(line for line in stdout.splitlines()
                        if line.split(" ")[0] in {"DENOISE_DEVICE", "SUN_AZIMUTH_DELTA", "TILE",
                                                  "BASE_GRID"}))


def render_frame(grid: cap_render.CapGrid, render_dir: Path, quadrant: tuple[int, int],
                 index: int) -> Path:
    """Render one frame of the ring, and only call it rendered once it is whole.

    WRITTEN UNDER A PART NAME AND RENAMED, so that a frame's EXISTENCE is the completeness claim the
    resume reads. A killed Blender leaves a non-empty partial PNG, which is what the arm's
    `[ -s "$OUT" ]` accepted — and a partial frame blends garbage into the disc rather than failing.
    """
    png = frame_path(grid, quadrant, index)
    part = png.with_suffix(".part.png")
    part.unlink(missing_ok=True)
    blend = frames_dir(grid) / f"cap_{grid.name}.blend"
    result = blender_proc.run(
        blender_command(grid, render_dir, blend, part, quadrant, index))
    if result.returncode != 0 or not part.exists():
        raise RuntimeError(f"blender exited {result.returncode} for {png.name}: "
                           f"{result.stdout[-1500:]}{result.stderr[-1500:]}")
    check_echoes(result.stdout, quadrant, index)
    os.replace(part, png)
    return png


def blend_disc(grid: cap_render.CapGrid) -> np.ndarray:
    """Stitch the ring into one disc: every pixel cross-faded between its two bracketing passes.

    LINEAR BETWEEN THE TWO NEIGHBOURS. A pixel landing on a rendered bearing takes that frame whole;
    the worst case is the midpoint at 50/50, which is the error `CAP_AZIMUTH_PASSES` was ratified
    against.

    EVERY PIXEL'S PAIR IS CHECKED BEFORE ANY OF IT IS TRUSTED. A quadrant is rendered at only the
    bearings its own longitudes need, so a missing frame does not raise on its own — it silently
    leaves those pixels black, which reads as a rendering artefact rather than as a missing file.
    """
    longitude, _latitude = cap_render._lonlat_grid(grid)
    longitude = np.asarray(longitude, dtype=np.float64)
    half = grid.px // cap_render.CAP_QUADRANT_SPLIT
    out = np.zeros((3, grid.px, grid.px), dtype=np.uint8)
    for (row, col), passes in frame_plan(grid).items():
        rows, cols = slice(row * half, (row + 1) * half), slice(col * half, (col + 1) * half)
        lower, frac = bracketing_pass(grid, longitude[rows, cols])
        present = {index: frame_path(grid, (row, col), index) for index in passes}
        present = {index: path for index, path in present.items() if path.exists()}
        have = np.array(sorted(present)) if present else np.zeros(0, dtype=int)
        # THE PAIR IS `lower` AND `lower + 1`. The weight expression below reads `lower == index - 1`
        # to decide which pixels take a frame as their UPPER neighbour, and copying that `- 1` into
        # this check asks for the frame below each pixel's bracket instead of above.
        covered = ((lower[..., None] == have).any(axis=-1)
                   & (((lower + 1) % CAP_AZIMUTH_PASSES)[..., None] == have).any(axis=-1))
        if not covered.all():
            raise RuntimeError(
                f"{grid.name} r{row}c{col}: {int((~covered).sum()):,} px have no bracketing pair; "
                f"frames present {sorted(present)} of the {passes} this quadrant needs")
        quadrant = np.zeros((3, half, half), dtype=np.float64)
        for index, path in sorted(present.items()):
            weight = (np.where(lower == index, 1.0 - frac, 0.0)
                      + np.where(lower == (index - 1) % CAP_AZIMUTH_PASSES, frac, 0.0))
            if not weight.any():
                continue          # rendered for a neighbouring pixel's bracket, sampled by none here
            with rasterio.open(path) as src:  # pyright: ignore[reportCallIssue]
                quadrant += src.read((1, 2, 3)).astype(np.float64) * weight[None]
        out[:, rows, cols] = np.clip(quadrant, 0, 255).astype(np.uint8)
    return out


def params(grid: cap_render.CapGrid, rasters: frozenset[str]) -> str:
    """Everything that can move a raytraced cap pixel and is not a file with an mtime.

    `block_render.params`' SPLIT RATHER THAN A NEW IDEA. The composite cap's recipe described a
    numpy shading pass that never ran here; recorded, it would have put a 41-minute render behind
    knobs no raytraced pixel reads. What this carries instead is the three tiers a rendered frame
    actually passes through: this module's geometry, the rig's constants through `rig_recipe`, and
    the producers' through `constants_for` and `white_law`.

    `"producer"` IS A LITERAL HERE AND NOT READ FROM A REGISTRY. No body chooses a cap producer any
    more, so the key does not exist to make a switch visible; it exists so a sidecar written by this
    module can never be mistaken for one written by anything else.

    `mask_full_scale` IS `prep_block`'s AND NOT THIS MODULE'S, and nothing else can carry it: the
    render directory is not an mtime dependency of the disc, so a re-cut mask would otherwise reach
    only a disc that was going to re-render anyway.
    """
    body = grid.body
    absent = layers.layers_off(body, layers.CAP_LAYERS)
    recipe: dict[str, Any] = {
        "producer": "raytrace",
        "grid": cap_render.grid_recipe_fields(grid),
        "azimuth_passes": CAP_AZIMUTH_PASSES,
        "quadrant_split": cap_render.CAP_QUADRANT_SPLIT,
        "exaggeration": body.exaggeration,
        "ground_scale": bodies.ground_metres_per_aeqd_unit(body),
        "rasters_off": planet_seam.rasters_off(rasters),
        # This caller's choices rather than look constants, recorded for `block_render.params`'
        # reason: a disc resumed across a change of either would blend both regimes into one image
        # with nothing saying which frame came from which.
        "denoise_device": CAP_DENOISE_DEVICE,
        "base_grid": CAP_BASE_GRID,
        "mask_full_scale": prep_block.MASK_FULL_SCALE,
        # `painted=True` because `prep_cap` declares each cryosphere mask's colour beside it, so a
        # body's white reaches a raytraced cap pixel through the render directory and nothing else.
        **layer_producers.constants_for(body, layers.CAP_LAYERS, painted=True),
        **layer_producers.white_law(body, layers.CAP_LAYERS),
        "coast_rgb": list(cap_render.COAST_RGB),
        "asset": {"format": "webp", "quality": cap_render.CAP_WEBP_QUALITY,
                  "rungs": list(cap_render.CAP_RUNGS)},
        "rig": block_render.rig_recipe(body),
    }
    if absent:
        # The conditional-record idiom: turning a layer off REMOVES its file from `cap_sources`, so
        # the dependency disappears along with the layer and the absence has nowhere else to show.
        recipe["layers_off"] = absent
    return json.dumps(recipe, indent=2, sort_keys=True) + "\n"


def render(grid: cap_render.CapGrid, rasters: frozenset[str]) -> Path:
    """One raytraced disc, end to end. Resumable: stopping costs the frame that was in flight.

    THE PREP IS GATED ON THE SAME RECIPE THE FRAMES ARE. A disc is prepped once and photographed
    `CAP_QUADRANT_SPLIT` squared times per pass, so re-cutting it on every resume would re-warp the
    planet for frames that already exist.

    FRAMES GO STALE AGAINST THE RECIPE AND THE SOURCES BOTH, which is one comparison rather than a
    generation concept: `write_if_changed` moves the recipe's mtime if and only if a value actually
    moved, and `cap_sources` is what a re-fused planet moves. Either one leaves every frame older
    than its inputs, and every frame re-renders.
    """
    render_dir = cap_render.cap_render_dir(grid)
    frames_dir(grid).mkdir(parents=True, exist_ok=True)
    recipe = freshness.write_if_changed(frames_dir(grid) / FRAMES_RECIPE_NAME,
                                        params(grid, rasters))
    fresh_after = freshness.newest_mtime(recipe, *cap_render.cap_sources(grid, rasters))

    heightfield = render_dir / render_seam.HEIGHTFIELD
    if not (heightfield.exists() and heightfield.stat().st_mtime > fresh_after):
        progress.stage(f"cap {grid.name}: cutting the rig's inputs")
        prep_cap.cut(grid, rasters, render_dir)

    plan = frame_plan(grid)
    todo = [(quadrant, index) for quadrant, passes in plan.items() for index in passes
            if not (frame_path(grid, quadrant, index).exists()
                    and frame_path(grid, quadrant, index).stat().st_mtime > fresh_after)]
    total = sum(len(passes) for passes in plan.values())
    progress.stage(f"cap {grid.name}: {total - len(todo)}/{total} frames already rendered, "
                   f"{len(todo)} to go")
    for number, (quadrant, index) in enumerate(todo, 1):
        render_frame(grid, render_dir, quadrant, index)
        progress.stage(f"cap {grid.name}: [{number}/{len(todo)}] "
                       f"r{quadrant[0]}c{quadrant[1]} pass {index}")

    return cap_render.finish_disc(grid, blend_disc(grid))
