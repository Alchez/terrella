"""Render a body's whole Mercator grid as Cycles blocks, into the one raster the tile cut reads.

`composite_planet`'s SIBLING AND ITS ALTERNATIVE. That one shades `planet_rgb.tif` window by
window out of numpy; this one renders it block by block out of Blender, and everything downstream —
the pyramid, the freshness marker, the publish — cannot tell which produced it. Only the recipe
beside it can, which is why this writes its own rather than borrowing the composite's: a raytraced
planet reads none of the composite's knobs and none of its hillshade, and gains the rig, the look
and the margin law instead. A body switched between producers against one shared dependency list
would leave the old pixels looking perfectly fresh.

It sits in `tile/` beside the producer it replaces rather than in `render/` beside the rig it
drives, because what it emits is a planet raster the pyramid is cut from — `render/` is one scene
at a time, and `scene_build` is the shared part of it this shells into.

RESUME IS THE WHOLE DESIGN, not a convenience. A planet is a full night of GPU at best, so the unit
of work has to be the block: prep, render, crop, write into the mosaic, mark — strictly in that
order, because a marker written before the bytes it vouches for is how a crash leaves a state that
reads as complete. Stopping this at any instant costs the one block in flight.

THE MARKER IS AN EXISTENCE TEST AND NOT AN MTIME ONE, and that is forced rather than chosen. Every
block lands in ONE shared raster whose mtime advances with every later block, so the first block's
marker is older than the mosaic the moment the second one writes — the repo's ordinary rule, that a
marker must be newer than the bytes it vouches for, cannot hold here. What replaces it is one
generation stamp for the whole run: the recipe and the warped inputs are compared against it ONCE
at pass start, and if anything moved, the entire marker set is cleared and the planet re-renders.
Per-block freshness answers "did this block finish", never "is this block still correct".

    python -m pipeline.tile.block_render --body earth              # the planet, resumable
    python -m pipeline.tile.block_render --body earth --only r00c00,r31c40   # named blocks
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from pipeline import (
    block_plan,
    bodies,
    freshness,
    layers,
    mercator,
    paths,
    planet_seam,
    progress,
)
from pipeline.block_plan import Block
from pipeline.look import palette
from pipeline.raster_io import GTIFF_CREATE
from pipeline.render import prep_block, render_seam
from pipeline.tile import producer_seam, relief_scan, shade_planet

#: Consecutive block failures that stop the run. A single block can fail for its own reasons — a
#: transient OptiX fault, a bad frame — and throwing away the hours still queued behind it would be
#: the wrong trade. A RUN this long is not a block, it is the GPU being gone. Carried unchanged from
#: the probe's night runner, where it was calibrated across 1,358 blocks.
CONSECUTIVE_ABORT = 8

#: Total failures, as a fraction of the planned blocks, that stop the run.
#:
#: THE PROBE'S PER-REGION FRACTION HAS NO ANALOGUE HERE and this is not it renamed: a planet pass
#: has no regions to abandon and move on from, so the only question a total can answer is whether
#: to keep spending GPU on a planet that will come out holed. Scattered failures below this are
#: recorded and stepped over; nothing is lost by stopping, because every finished block is on disk
#: and marked.
FAILURE_CEILING_FRACTION = 0.01

#: The recipe this producer bakes into the mosaic, beside it, as every writer in the pipeline does.
PARAMS_NAME = "raytrace_params.json"

#: A fixed-size progress document, rewritten after every block. THE POINT OF CONTACT FOR A WATCHER:
#: checking on a run that lasts a night must not mean reading a log that grew all night.
STATUS_NAME = "raytrace_status.json"

#: The file whose mtime dates the current generation of block markers beside it.
GENERATION_NAME = "generation.stamp"


def mosaic_in(work: Path) -> Path:
    """The colour raster this producer fills, which is the one the tile cut reads."""
    return work / shade_planet.PLANET_RGB


def markers_in(mosaic: Path) -> Path:
    """Where per-block completion is recorded, named after the mosaic it describes.

    Derived from the mosaic rather than from the work directory so that a run pointed at a second
    raster — an A/B, or a first pass that must not overwrite the shipping one — keeps its own
    markers. Sharing them would let one run resume over the other's blocks.
    """
    return mosaic.with_name(f"{mosaic.stem}_blocks")


def generation_stamp(markers: Path) -> Path:
    """The stamp dating this generation of markers."""
    return markers / GENERATION_NAME


def status_in(work: Path) -> Path:
    """Where the run reports its own progress."""
    return work / STATUS_NAME


def block_name(block: Block) -> str:
    """This block's name on the grid, which is also its marker's filename."""
    return f"r{block.row0 // block.size_px:02d}c{block.col0 // block.size_px:02d}"


def context_census(blocks: list[Block]) -> dict[str, int]:
    """How many blocks this plan renders at each context width, which is the context law's OUTPUT.

    RECORDED INSTEAD OF THE LAW'S CONSTANTS, and the difference is the whole point. A hand-written
    list of the law's constants failed three times in one session, in both directions: twice it went
    SHORT — a floor added to the law and not to the list, then a shortcut deleted from the law and
    not reflected anywhere — which left the recipe text unmoved, the generation reading as current,
    and a resume about to keep blocks rendered under the old rule; and once it went LONG, recording
    a ceiling no block on this body reaches, so raising it for another planet would restage this one
    for identical pixels.

    A census cannot go short, because it is measured from the plan rather than described: any change
    to the law that moves a context moves this, and any change that moves none does not. It is exact
    enough on the ordering question too — a context is a pure function of relief and latitude, so
    widths cannot permute between blocks without the relief moving, and the relief derives from
    `height_3857`, which is a dependency by mtime.

    IT COVERS ONE OF THE THREE WIDTHS AND ONLY ONE. The delivered and traced edges are the same for
    every block on a body, so they are recorded as the plain constants they are; the context is the
    one the law computes per block, so it is the one that needs measuring rather than describing.
    """
    census: dict[str, int] = {}
    for block in blocks:
        key = str(block.context_px)
        census[key] = census.get(key, 0) + 1
    return dict(sorted(census.items(), key=lambda item: int(item[0])))


def params(body: bodies.Body, rasters: frozenset[str], look: palette.Look,
           rig: dict[str, Any], blocks: list[Block]) -> str:
    """Everything that can move a raytraced pixel and is not a file with an mtime.

    THE SPLIT IS `composite_params`', for the same reason stated there: a warped source moves an
    mtime and `raytrace_deps` tracks it; a constant moves nothing at all and only a recipe can see
    it. A look constant that reaches neither leaves a stale planet reading fresh forever.

    `layers_off` and `rasters_off` follow the conditional-record idiom: they are what tracks a layer
    going OFF, which the dependency mtimes structurally cannot — a path that is not there scores
    0.0 and is invisible, so switching sea ice off would otherwise leave a planet painted with it
    looking current.

    The rig arrives as an argument because `scene_build` owns its own constants; see `rig_recipe`.
    """
    recipe: dict[str, Any] = {
        "producer": "raytrace",
        "grid_px": block_plan.grid_px(body),
        "block_px": block_plan.RENDER_BLOCK_PX,
        # The two widths that are the same for every block, recorded as the constants they are.
        "denoise_band_px": block_plan.DENOISE_BAND_PX,
        "traced_px": block_plan.RENDER_BLOCK_PX + 2 * block_plan.DENOISE_BAND_PX,
        # The third is per block, so the context law's OUTPUT and not its constants — see
        # `context_census` for why a described law went wrong three times and a measured one cannot.
        "contexts": context_census(blocks),
        "exaggeration": body.exaggeration,
        "ground_scale": bodies.ground_metres_per_mercator_unit(body),
        "map_units_per_pixel": body.map_units_per_pixel,
        "layers_off": layers.layers_off(body, layers.BLOCK_LAYERS),
        "rasters_off": planet_seam.rasters_off(rasters),
        # Not a look constant, so not `rig`'s: it is this caller's choice, and the two denoisers do
        # not agree to the last DN. Recorded because a pass resumed across a change of it would
        # otherwise write both into one mosaic with nothing saying which made which block.
        "denoise_device": BLOCK_DENOISE_DEVICE,
        # This caller's too, and recorded for a sharper reason than the denoiser's: the two grids
        # differ by 1.4 DN mean and up to 75, which is a look difference rather than a rounding one.
        # A pass resumed across a change of it would write both dicings into one mosaic.
        "base_grid": BLOCK_BASE_GRID,
        # The mask writer's depth, which is `prep_block`'s constant and not this module's. It is
        # here because nothing else can carry it: a re-cut mask does not restage a rendered block,
        # since blocks are skipped by marker existence and `raytrace_deps` tracks planet rasters
        # rather than the per-block prep directory. Left out, a depth change would reach only the
        # blocks that were going to render anyway and leave every finished one terraced.
        "mask_full_scale": prep_block.MASK_FULL_SCALE,
        "rig": rig,
    }
    if look.sea is None:
        recipe["sea"] = None
    return json.dumps(recipe, indent=2, sort_keys=True) + "\n"


def rig_recipe(body: bodies.Body) -> dict[str, Any]:
    """`scene_build`'s own account of the constants it will apply to this body's look.

    IMPORTED WITH `bpy` STUBBED, which is not a trick invented here: `scene_build` touches bpy only
    at render time and `tests/test_scene_build_sync` has imported it this way since the hero
    sea-sync, precisely so that its constants can be read without Blender. The alternative is
    restating them, which is the copy that drifted three times before that test existed.

    The stub is left in place only if this module put it there, so a caller that genuinely runs
    inside Blender keeps the real module.
    """
    stubbed = "bpy" not in sys.modules
    if stubbed:
        sys.modules["bpy"] = types.ModuleType("bpy")
    try:
        from pipeline.render import scene_build
        return scene_build.rig_recipe(palette.look_for(body.name))
    finally:
        if stubbed:
            del sys.modules["bpy"]


def raytrace_deps(work: Path, recipe: Path) -> tuple[Path, ...]:
    """Everything the raytraced mosaic must be newer than.

    DELIBERATELY NOT `composite_deps`, and the difference is exactly the switch: no hillshade, since
    Cycles computes its own light, and no composite recipe. What stays is the warped input set the
    block prep actually cuts from — the heightfield, the two masks, and every optional surface layer
    — plus this producer's own recipe.

    Over-inclusive in the same way and for the same reason: `is_stale` takes the newest mtime, so
    naming a raster this body does not have costs nothing, while missing one is silent.

    THE PRODUCER STAMP IS SHARED WITH `composite_deps` AND IS THE ONLY ENTRY THAT IS. It is what
    makes a producer switch visible from this side: the mosaic left by the composite is newer than
    every warp and newer than this recipe, so without the stamp this producer would report it fresh
    and skip the render, publishing composited pixels under a raytrace recipe.
    """
    return (work / shade_planet.HEIGHT_3857, work / shade_planet.OCEAN_3857,
            work / shade_planet.WATER_3857,
            *(layer.warped_in(work) for layer in layers.WARPED_LAYERS), recipe,
            producer_seam.stamp_path(work))


def generation_is_current(markers: Path, deps: tuple[Path, ...]) -> bool:
    """Whether the markers on disk describe the planet being rendered now.

    NOT `freshness.is_stale`, AND THE DIFFERENCE IS STRUCTURAL RATHER THAN STYLISTIC. That predicate
    calls an output stale when it was REWRITTEN since it was stamped, which is what catches a
    crashed half-written raster. Here the output GROWS after its stamp by design — every block
    lands in the same directory the stamp sits in — so that clause would call a healthy resume
    stale on its second block and re-render the planet from scratch every time.

    What is asked instead is only the other half: did any input move since this generation began.
    """
    stamp = generation_stamp(markers)
    return stamp.exists() and freshness.newest_mtime(*deps) <= stamp.stat().st_mtime


def start_generation(markers: Path, mosaic: Path) -> None:
    """Begin a new generation: no block on disk is trusted, and the mosaic stops being complete.

    THE MOSAIC'S OWN MARKER GOES FIRST AND THAT ORDER MATTERS. `tiles_are_fresh` keys on it, so a
    mosaic left stamped while it is being rewritten block by block is a pyramid cut from a planet
    that is half one producer and half the other — and every gate would pass.
    """
    freshness.done_marker(mosaic).unlink(missing_ok=True)
    shutil.rmtree(markers, ignore_errors=True)
    markers.mkdir(parents=True, exist_ok=True)
    generation_stamp(markers).touch()


def unsuppliable_rig_images(rasters: frozenset[str]) -> list[str]:
    """The rig's mandatory images no block on this planet seam can carry.

    A DECLARATION QUESTION AND NOT A DISK ONE, asked before any block is prepped: `prep_block.build`
    writes `inlandlake.png` and `river.png` only when the seam declared a `watermask`, and the rig
    loads both for every look. So on a body with no watermask the images are not missing from one
    block, they are unproduceable for all of them.

    THE OCEANMASK IS DELIBERATELY NOT CHECKED, and that is the one asymmetry. It is the single
    mandatory image a look can answer for — `scene_build.images_for` drops it when `Look.sea is
    None` — and that rule lives in a module this interpreter cannot import, since `scene_build`
    imports `bpy`. Lake and river carry no such escape: whether a planet has inland water is its
    planet seam's answer rather than a colour, which is what makes them decidable from here.
    """
    return [] if "watermask" in rasters else [render_seam.INLANDLAKE, render_seam.RIVER]


def rig_seam_refusals(rasters: frozenset[str]) -> list[str]:
    """The same gap as a reason a caller can print, or `[]`.

    TWO CALLERS AND ONE WORDING. The pass asks this before the shared warp so a wrongly-declared
    body does not pay 6:49 to hear no; `check_inputs` asks it again below because `main` is a second
    door into this producer that never passes through the pass. Neither can be dropped, and the
    explanation is written once so the two answers cannot drift into disagreeing about why.
    """
    unsuppliable = unsuppliable_rig_images(rasters)
    if not unsuppliable:
        return []
    return [(f"its planet stage declared no watermask, so no block carries "
             f"{' or '.join(unsuppliable)}, which the rig loads for every look. This is a body-seam "
             f"gap rather than a missing file — either its planet producer must emit one, or the "
             f"rig must learn to render without it")]


def check_inputs(work: Path, body: bodies.Body, rasters: frozenset[str]) -> None:
    """Refuse to start when this body cannot feed the rig, or its warped rasters are not on disk.

    THE ALTERNATIVE IS A SLOW FAILURE THAT BLAMES THE WRONG THING. Without this the first block
    raises on a missing heightfield, and so does the next, and the run stops eight blocks later on
    the consecutive-failure counter — whose message says the GPU is gone, about a stage that never
    ran. On an unattended night that reads as a hardware fault until someone opens the log.

    THE SEAM CHECK IS THE SAME FAILURE ONE TIER UP, and it is the one a body switched to this
    producer hits. A planet declaring no watermask passes every raster check below — it is not asked
    for a file it never had — and then fails inside Blender on an image the rig loads
    unconditionally, eight times, under the message about the GPU.

    WHICH RASTERS ARE REQUIRED COMES FROM THE DECLARATION AND NEVER FROM THE DISK, because those are
    different questions: a body that emits no inland water must not be asked for a watermask, and a
    body that does must not be allowed to start without one.

    The warp itself is still the pass's, which is the seam this names rather than papers over.
    """
    refusals = rig_seam_refusals(rasters)
    if refusals:
        raise SystemExit(f"{body.name} cannot be rendered by this producer: "
                         + "; ".join(refusals))
    required = [work / shade_planet.HEIGHT_3857]
    if "oceanmask" in rasters:
        required.append(work / shade_planet.OCEAN_3857)
    if "watermask" in rasters:
        required.append(work / shade_planet.WATER_3857)
    missing = [path.name for path in required if not path.exists()]
    if missing:
        raise SystemExit(
            f"{work} is missing the warped input(s) this producer cuts from: {', '.join(missing)}. "
            f"They are the pass's to build — run `python -m pipeline.tile.planet_pass "
            f"--body {body.name}` first, which warps them onto the grid this renders on")


def check_fits(blocks: list[Block], body: bodies.Body) -> list[Block]:
    """The plan, unchanged, unless some block cannot be rendered at all — then stop.

    A BLOCK THAT DOES NOT FIT STOPS THE RUN RATHER THAN BEING SKIPPED, and the asymmetry is the
    reason: a skipped block is a hole in a planet that the mosaic cannot show, because an unwritten
    block reads as black rather than as missing. Failing before the first render costs seconds;
    discovering it from the pixels costs the pass and the look decision taken off them.

    Separated from the plan it checks so that the refusal is provable without a planet on disk.

    IT NOW CHECKS THE CONSTANTS RATHER THAN THE RELIEF, and that is a real narrowing worth saying
    out loud. The traced edge is `RENDER_BLOCK_PX + 2 * DENOISE_BAND_PX` for every block on every
    body, so this can no longer refuse one block and pass its neighbour: what it catches is a block
    edge raised past what the GPU is proven at. The width that still varies per block is the
    context, and it is bounded by `CONTEXT_CEILING_PX` inside the law instead of here, because a
    plane is geometry rather than a frame.
    """
    oversized = [block_name(block) for block in blocks if not block.fits]
    if oversized:
        raise SystemExit(
            f"{len(oversized)} block(s) exceed the {block_plan.TRACED_CEILING_PX} px frame this "
            f"GPU is proven at, the first at {oversized[0]}; the block edge or the denoise band "
            f"has to change before {body.name} can render")
    return blocks


def plan_blocks(body: bodies.Body, work: Path) -> list[Block]:
    """Every block of this body's grid, each sized by the relief that can cast into it.

    The relief cache is refreshed first and is idempotent: on a resume it is already current and
    the call costs a stat, where re-reading the master would cost minutes of a night.
    """
    relief_scan.scan(body)
    high, low = relief_scan.read_relief(work)
    return check_fits(block_plan.plan(block_plan.relief_from_cells(high, low),
                                      block_plan.whole_grid(body), body,
                                      altitude_deg=palette.SUN_ALT_DEG), body)


def ensure_mosaic(mosaic: Path, body: bodies.Body) -> None:
    """Create the full-grid raster once, so blocks may land in any order and a resume can skip.

    THE INTERNAL TILING IS `raster_io.GTIFF_CREATE`'s AND NOT A NUMBER WRITTEN HERE, which is what
    keeps a render block a whole number of internal tiles. Straddling them would make every block
    write decompress, modify and recompress its neighbours' pixels — and a rewritten tile that grows
    cannot go back in place, so a random-order pass would fragment the file. `test_block_render`
    pins the divisibility rather than leaving it a coincidence of two 512s.

    A raster on the wrong grid is replaced rather than written into: a body whose zoom ceiling moved
    has a differently sized planet, and `rasterio` would otherwise refuse each write one block at a
    time, deep into a night.
    """
    edge = block_plan.grid_px(body)
    if mosaic.exists():
        with rasterio.open(mosaic) as existing:  # pyright: ignore[reportCallIssue]
            if (existing.width, existing.height, existing.count) == (edge, edge, 3):
                return
        progress.stage(f"{mosaic.name} is not this body's {edge}x{edge} 3-band grid -> recreating")
        mosaic.unlink()
    half = mercator.MERCATOR_HALF_M
    mosaic.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(  # pyright: ignore[reportCallIssue]
            mosaic, "w", driver="GTiff", width=edge, height=edge, count=3, dtype="uint8",
            crs="EPSG:3857", transform=from_bounds(-half, -half, half, half, edge, edge),
            BIGTIFF="YES", SPARSE_OK="TRUE", **GTIFF_CREATE):
        pass
    progress.stage(f"created {mosaic} ({edge} x {edge})")


#: Where OIDN runs for BLOCKS, which is not where it runs for heroes and is the only Cycles setting
#: that differs between the two callers of `scene_build`. Everything else that separates a hero from
#: a block happens before Blender starts: a different prep module, a different framing law, a
#: different snow source. Measured on r07c26 and r26c46 at both block edges: 5.07 s and 4.69 s saved
#: per 2048 block, 20.11 s and 19.82 s per 4096 block, no fault, and a delivered-pixel difference of
#: at most 1 DN with 88-91% of channels bit-identical. `scene_build.configure_render` holds why this
#: cannot be derived from the frame size instead.
BLOCK_DENOISE_DEVICE = "gpu"

#: Whether a block's plane starts as a base grid, which is the SECOND setting that differs between
#: the two callers of `scene_build` and differs for a harder reason than the first. `base_patches`
#: holds the measurement; the short of it is that a block's plane is mostly off-camera and lands
#: near 21M micropolygons, while a hero's is entirely in frame and reaches 41.8M to 67M — past the
#: 12 GB card, where OptiX fails to build at all. Blocks can afford one micropolygon per pixel and
#: heroes currently cannot, so this is the caller's to state and not a constant to flip.
BLOCK_BASE_GRID = "fitted"


def blender_command(body: bodies.Body, render_dir: Path, blend: Path, png: Path) -> list[str]:
    """The one Blender invocation a block needs, built rather than spelled at the call site.

    The binary is `paths.BLENDER`'s — it is not on PATH on this machine and `MAPS_BLENDER`
    overrides it, both of which are that module's to know rather than this one's.
    """
    return [str(paths.BLENDER), "-b", "--python",
            str(paths.ROOT / "pipeline" / "render" / "scene_build.py"), "--",
            "--body", body.name, "--render-dir", str(render_dir),
            "--out", str(blend), "--render", str(png),
            "--denoise-device", BLOCK_DENOISE_DEVICE,
            "--base-grid", BLOCK_BASE_GRID]


def cropped(png: Path, block: Block) -> np.ndarray:
    """The delivered pixels of a rendered frame: the denoise band cut back off, alpha dropped.

    THE BAND, NEVER THE CONTEXT, AND THE TWO ARE DIFFERENT NUMBERS. The frame Cycles produced is
    the TRACED rectangle, which overhangs the delivered block by `DENOISE_BAND_PX` so that OIDN's
    own edge falls outside the pixels that ship. The context is far wider and never reaches a
    frame at all: it is off-camera geometry, there so that terrain outside the block can still
    throw a shadow across the boundary.

    Cropping by the context instead would take a correctly SHAPED square out of the wrong place —
    on Earth's widest blocks, 1,856 px off true — and the mosaic would record it as done. The shape
    check below cannot see that on its own, which is why `test_block_render` asserts the offset
    against the band in both directions.
    """
    with rasterio.open(png) as src:  # pyright: ignore[reportCallIssue]
        frame = src.read()
    band, edge, traced = block_plan.DENOISE_BAND_PX, block.size_px, block.traced_edge_px
    # THE FRAME IS CHECKED, NOT THE CROP, and the difference is a hole this had while the outer
    # ring was the margin. A frame LARGER than asked for — a rig that photographed its whole plane
    # — still yields a crop of exactly the right shape, so a shape assertion on the result passes
    # and the mosaic takes the wrong ground. Only the frame's own size can tell the two apart.
    if frame.shape[1:] != (traced, traced):
        raise RuntimeError(f"{png.name}: rendered {frame.shape[1]}x{frame.shape[2]}, expected the "
                           f"{traced} px traced frame — the frame numbers and the rig disagree, "
                           f"and this block's plane is {block.plane_edge_px} px, which is what a "
                           f"camera that was never narrowed would have produced")
    return frame[:3, band:band + edge, band:band + edge]


def render_block(body: bodies.Body, block: Block, mosaic: Path, scratch: Path,
                 markers: Path) -> None:
    """One block, end to end: prep, render, crop, write into the mosaic, mark.

    THE MARKER IS LAST AND THE MOSAIC IS CLOSED BEFORE IT. Only a flushed write is a block that
    exists, and this is the ordering the resume depends on being right.
    """
    name = block_name(block)
    render_dir = scratch / name
    png = scratch / f"{name}.png"
    # A previous attempt on this block died somewhere: its half-filled directory would otherwise
    # let the prep's declaration name images an earlier run wrote under a different margin.
    shutil.rmtree(render_dir, ignore_errors=True)
    png.unlink(missing_ok=True)

    prep_block.cut(body, block, render_dir)
    result = subprocess.run(blender_command(body, render_dir, scratch / f"{name}.blend", png),
                            cwd=paths.ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not png.exists():
        raise RuntimeError(f"blender exited {result.returncode} for {name}: "
                           f"{result.stdout[-1500:]}{result.stderr[-1500:]}")
    # THE RECIPE BELOW WILL CLAIM A DENOISE DEVICE, SO THE RENDER HAS TO CONFIRM IT USED ONE. A
    # dropped or renamed flag renders on the CPU and succeeds, and the only surviving trace would be
    # a recipe asserting something that never happened — stale-looking-fresh in the one direction a
    # freshness check cannot see, because the recipe would be self-consistent.
    if f"DENOISE_DEVICE {BLOCK_DENOISE_DEVICE}" not in result.stdout:
        raise RuntimeError(f"{name}: asked Blender for --denoise-device "
                           f"{BLOCK_DENOISE_DEVICE} and it did not report back; the recipe would "
                           f"record a device this block was not rendered with")
    # THE SAME CHECK FOR THE SAME REASON, and the count below cannot stand in for it: `fitted` on a
    # plane under the cap yields one patch, which is byte-identical to the flag never arriving. Only
    # the POLICY discriminates, so only the policy can confirm the recipe's claim.
    if f"BASE_GRID {BLOCK_BASE_GRID}" not in result.stdout:
        raise RuntimeError(f"{name}: asked Blender for --base-grid {BLOCK_BASE_GRID} and it did "
                           f"not report back; the recipe would record a dicing this block was not "
                           f"rendered with, and an under-diced block is not identifiable from its "
                           f"pixels")

    crop = cropped(png, block)
    with rasterio.open(mosaic, "r+") as dst:  # pyright: ignore[reportCallIssue]
        dst.write(crop, window=block.delivered_window)
    # The base grid is READ BACK rather than recomputed here. It is a pure function of the frame and
    # `scene_build` owns it; a second evaluation on this side would be a copy free to disagree,
    # which is the failure it is meant to catch. Recorded so an under-diced block is identifiable
    # afterwards, since it is not identifiable from its pixels.
    reported = next((line for line in result.stdout.splitlines()
                     if line.startswith("BASE_GRID ")), "BASE_GRID ? BASE_PATCHES ?")
    (markers / name).write_text(
        f"context {block.context_px} traced {block.traced_edge_px} "
        f"plane {block.plane_edge_px} {reported}\n")
    shutil.rmtree(render_dir, ignore_errors=True)
    png.unlink(missing_ok=True)
    (scratch / f"{name}.blend").unlink(missing_ok=True)


def disk_floor_bytes(body: bodies.Body, remaining: int, total: int) -> float:
    """Free space this run refuses to go below, sized for what it may still have to write.

    THE COMPRESSION RATIO IS NOT KNOWABLE IN ADVANCE, so the floor assumes DEFLATE buys nothing and
    the raster grows to its uncompressed size. Scaled by the blocks still to do, so it relaxes as
    the run progresses: a fixed planet-sized floor would abort a nearly finished pass that needs a
    few hundred megabytes, which costs a night in the other direction.

    It watches the WORK directory rather than `$HOME`. Those are the same filesystem on the machine
    this was written on and nothing records that coincidence, so a contributor with the store on a
    second disk would otherwise have a floor measuring the wrong volume.
    """
    uncompressed = block_plan.grid_px(body) ** 2 * 3
    return uncompressed * (remaining / total) if total else 0.0


def free_bytes(path: Path) -> int:
    """Free space on the filesystem holding `path`."""
    return shutil.disk_usage(path).free


class Status:
    """A fixed-size progress document, rewritten in full after every block."""

    def __init__(self, body: bodies.Body, mosaic: Path, path: Path, total: int, already: int):
        self.body, self.mosaic, self.path = body, mosaic, path
        self.total, self.done, self.already = total, already, already
        self.started = time.monotonic()
        self.state = "starting"
        self.failures: list[str] = []
        self.last = ""

    def write(self) -> None:
        elapsed = (time.monotonic() - self.started) / 60
        rendered = self.done - self.already
        rate = rendered / elapsed if elapsed > 0 and rendered else 0.0
        remaining = self.total - self.done
        self.path.write_text(json.dumps({
            "updated": datetime.now(UTC).isoformat(timespec="seconds"),
            "state": self.state,
            "body": self.body.name,
            "mosaic": str(self.mosaic),
            "progress": f"{self.done}/{self.total}",
            "percent": round(100 * self.done / self.total, 2) if self.total else 0.0,
            "rendered_this_run": rendered,
            "resumed_from": self.already,
            "elapsed_min": round(elapsed, 1),
            "blocks_per_min": round(rate, 2),
            "eta_min": round(remaining / rate, 1) if rate else None,
            "failures": len(self.failures),
            "failed_blocks": self.failures[-6:],
            "last_block": self.last,
            "free_gb": round(free_bytes(self.mosaic.parent) / 1e9, 1),
        }, indent=2) + "\n")


def log(message: str, *, stage: bool = False) -> None:
    """One progress line, stamped in LOCAL time because a night run is read against a wall clock.

    `astimezone()` on a UTC now, rather than a naive one: the reader wants their own hours and the
    project's other timestamps are UTC by rule, so the conversion is stated rather than implied.

    `stage=True` marks the line as a boundary a watcher should wake for, and the default is what
    makes this producer readable at all: it runs 1,024 blocks on Earth at today's block size and
    the watchdog EXITS on every marker it matches, so marking the per-block line would be one
    wake-up per block in a night, and the figure grows as the block shrinks. The
    per-block story is read from `raytrace_status.json`, which is rewritten in place and can be
    sampled at whatever interval the reader wants; only the boundaries of the run are stages.
    """
    if stage:
        message = progress.marked(message)
    print(f"{datetime.now(UTC).astimezone():%H:%M:%S}  {message}", flush=True)


def run(body: bodies.Body, work: Path, mosaic: Path, *, limit: int | None = None,
        only: frozenset[str] | None = None) -> int:
    """Render every block this body still owes, and stamp the mosaic when none are left.

    Returns the number of blocks rendered by this call. `only` renders a named subset and, like
    `limit`, therefore never completes the planet — neither stamps the mosaic, because a marker on
    a partly rendered raster is exactly the state the whole freshness scheme exists to refuse.
    """
    # THE PLAN COMES BEFORE THE RECIPE, because the recipe records what the plan produced. The
    # repo's ordering rule — write the recipe, THEN ask the freshness question — is unchanged and
    # is what still makes a settings change restage itself; planning first only supplies the
    # recipe's content. Inputs are checked first of all, so a missing warp fails in a second
    # rather than after a whole-grid plan.
    # THIS PRODUCER NAMES ITSELF, before the freshness question below that depends on it and before
    # any block is prepped. It names the RAYTRACE rather than `body.planet_producer`, and the
    # difference is the whole point: this module is a shipped entry point of its own (`--only` is
    # how one block is re-rendered for judging), so it can put raytraced bytes into the raster of a
    # body the registry still calls `"composite"`. Recording the body's answer here would leave the
    # stamp agreeing with a registry the pixels disagree with, and the composite would then find
    # nothing moved and republish them under its own recipe.
    rasters = planet_seam.declared(body)
    look = palette.look_for(body.name)
    check_inputs(work, body, rasters)
    producer_seam.declare(work, "raytrace")
    blocks = plan_blocks(body, work)
    recipe = freshness.write_if_changed(work / PARAMS_NAME,
                                        params(body, rasters, look, rig_recipe(body), blocks))
    deps = raytrace_deps(work, recipe)
    markers = markers_in(mosaic)

    if not freshness.is_stale(mosaic, *deps):
        log(f"{mosaic.name} fresh -> skip render", stage=True)
        return 0
    if not generation_is_current(markers, deps):
        log("inputs or recipe moved since the last generation -> every block re-renders",
            stage=True)
        start_generation(markers, mosaic)
    freshness.done_marker(mosaic).unlink(missing_ok=True)

    ensure_mosaic(mosaic, body)
    scratch = work / f"{mosaic.stem}_scratch"
    scratch.mkdir(parents=True, exist_ok=True)

    selected = [block for block in blocks if only is None or block_name(block) in only]
    if only is not None:
        missing = only - {block_name(block) for block in blocks}
        if missing:
            raise SystemExit(f"no such block(s) on {body.name}'s grid: {', '.join(sorted(missing))}")
    todo = [block for block in selected if not (markers / block_name(block)).exists()]
    already = sum(1 for block in blocks if (markers / block_name(block)).exists())

    status = Status(body, mosaic, status_in(work), len(blocks), already)
    status.state = "rendering"
    status.write()
    log(f"{body.name}: {already}/{len(blocks)} blocks already done, {len(todo)} to render"
        f"{'' if only is None else f' (of {len(selected)} selected)'}, "
        f"{free_bytes(mosaic.parent) / 1e9:.0f} GB free", stage=True)

    consecutive = 0
    ceiling = max(CONSECUTIVE_ABORT, int(FAILURE_CEILING_FRACTION * len(blocks)))
    rendered = 0
    for index, block in enumerate(todo, 1):
        if limit is not None and rendered >= limit:
            log(f"--limit {limit} reached", stage=True)
            status.state = "limited"
            status.write()
            break
        floor = disk_floor_bytes(body, len(todo) - index + 1, len(blocks))
        if free_bytes(mosaic.parent) < floor:
            log(f"ABORT: {free_bytes(mosaic.parent) / 1e9:.1f} GB free is below the "
                f"{floor / 1e9:.1f} GB this run may still need", stage=True)
            status.state = "aborted-disk"
            status.write()
            break
        name = block_name(block)
        started = time.monotonic()
        try:
            render_block(body, block, mosaic, scratch, markers)
        except Exception as failure:            # noqa: BLE001 — one block must not end the night
            consecutive += 1
            status.failures.append(name)
            status.last = f"{name} FAILED"
            status.write()
            log(f"[{index}/{len(todo)}] {name} FAILED ({consecutive} in a row): "
                f"{str(failure)[:300]}")
            if consecutive >= CONSECUTIVE_ABORT:
                log(f"ABORT: {consecutive} consecutive failures — this is the GPU, not a block",
                    stage=True)
                status.state = "aborted-failures"
                status.write()
                break
            if len(status.failures) >= ceiling:
                log(f"ABORT: {len(status.failures)} failures against a ceiling of {ceiling}",
                    stage=True)
                status.state = "aborted-failures"
                status.write()
                break
            continue
        consecutive = 0
        rendered += 1
        status.done += 1
        elapsed = time.monotonic() - started
        status.last = f"{name} {elapsed:.1f}s"
        status.write()
        log(f"[{index}/{len(todo)}] {name} context {block.context_px:4d} "
            f"plane {block.plane_edge_px:4d} {elapsed:5.1f}s | "
            f"{status.done}/{status.total} ({100 * status.done / status.total:.1f}%)")

    complete = all((markers / block_name(block)).exists() for block in blocks)
    if complete and status.state == "rendering":
        freshness.mark_done(mosaic)
        shutil.rmtree(scratch, ignore_errors=True)
        status.state = "complete"
        log(f"PLANET COMPLETE: {len(blocks)} blocks, {len(status.failures)} failures -> {mosaic}",
            stage=True)
    elif status.state == "rendering":
        status.state = "incomplete"
        log(f"stopped with {status.total - status.done} block(s) still to render; "
            f"re-run to resume", stage=True)
    status.write()
    return rendered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    # REQUIRED, WITH NO DEFAULT, exactly as the planet pass's is: a producer that assumes Earth
    # because nobody said otherwise does not fail, it spends a night rendering the wrong planet.
    parser.add_argument("--body", required=True, choices=sorted(bodies.BODIES),
                        help="which planet's grid, look and margin law to render")
    parser.add_argument("--work", type=Path, default=None,
                        help="override the stage directory holding the warped inputs")
    parser.add_argument("--mosaic", type=Path, default=None,
                        help="override the raster written, the seam `--out` gives the planet pass: "
                             "an A/B, or a first pass that must not overwrite a shipping planet. "
                             "Its markers and scratch follow the name, so two runs never resume "
                             "over each other")
    # `default=None` and tested against None, never for truthiness: `--limit 0` has to mean render
    # nothing at all, and a falsy test would read it as no limit and start the whole planet.
    parser.add_argument("--limit", type=int, default=None,
                        help="render at most N blocks this run, then stop (a proving pass)")
    parser.add_argument("--only", default=None,
                        help="comma-separated block names (rNNcNN) to render instead of the whole "
                             "grid; never stamps the mosaic complete")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    body = bodies.BODIES[args.body]
    work = args.work if args.work is not None else bodies.work_dir(body, relief_scan.STAGE)
    mosaic = args.mosaic if args.mosaic is not None else mosaic_in(work)
    only = frozenset(name.strip() for name in args.only.split(",")) if args.only else None
    run(body, work, mosaic, limit=args.limit, only=only)


if __name__ == "__main__":
    main()
