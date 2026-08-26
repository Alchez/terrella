"""Fill a render directory for one polar cap, so the rig can photograph it. `prep_block`'s sibling.

WHY THIS REUSES `cap_render`'S OWN FUNCTIONS RATHER THAN WARPING AGAIN. The raytraced cap must
describe the SAME surface the composited one does, or the two producers of a disc disagree about
geology as well as about light. Heights come through `cap_heights` (nodata flattened, pole smoothed)
and the two cryosphere alphas through `_cap_perennial_ice` / `_cap_sea_ice`, which is where the
south's ice overrides and the forced Antarctic patch live. Nothing about the surface is re-decided
here, and that is the whole design: this module chooses no look constant at all.

THE THREE WIDTHS ARE TWO HERE, AND THE PAIR IS STILL THE TRAP. A block has a plane, a traced
rectangle and a delivered square; a cap has a plane and a photographed QUADRANT. The heightfield is
the plane at `grid.px`, the camera resolution is `grid.px // CAP_QUADRANT_SPLIT`, and swapping them
renders successfully at the wrong scale. `write_frame` holds which number is which.

NO `rowscale`, AND THE ABSENCE IS DECLARED. It is the one texture a block always writes, because
Mercator stretches with latitude and the exaggeration has to be corrected per row. AEQD is
equidistant from its centre by construction, and the parallel distortion across the disc peaks at
theta/sin(theta) = 1.005, so there is nothing to correct. A column of ones would be a fabricated
dataset; a missing file with a stage record beside it is the honest statement, and `render_seam` is
what carries it.

NO CONTEXT MARGIN. The camera photographs a quadrant of a plane that spans the whole disc, so the
terrain outside any one quadrant is already in the scene and casts into it for free — which is the
same trick `block_plan`'s context buys, arriving here without a margin because the neighbours are
literally the same plane.

    python -m pipeline.render.prep_cap --body earth --pole north
"""
import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

from pipeline import bodies, freshness, layers, planet_seam
from pipeline.look import layer_producers, seaice
from pipeline.raster_io import GTIFF_CREATE
from pipeline.render import prep_block, render_prep, render_seam
from pipeline.tile import cap_render

#: The recipe this stage bakes into its outputs, beside them, as every writer in the pipeline does.
RECIPE_NAME = "cap_recipe.json"


def build(grid: cap_render.CapGrid, rasters: frozenset[str], outdir: Path) -> list[str]:
    """Write every image the rig reads for this disc, and return what was written.

    THE RETURN IS THE DECLARATION'S CONTENT, so a layer that produced nothing is absent from it
    rather than written as zeros. `render_seam` exists to make that absence readable, and an
    all-zero mask would instead tell the rig to mix in nothing at full confidence.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    cap_render.cap_work_dir(grid.body).mkdir(parents=True, exist_ok=True)

    raw = cap_render._warp(grid, planet_seam.vrt_path(grid.body, "heightfield"),
                           cap_render.cap_height_warp(grid), "bilinear", "Float32")
    heights = cap_render.cap_heights(grid, raw)
    ocean, water = cap_render._cap_masks(grid, rasters, heights.shape)
    _, latitude = cap_render._lonlat_grid(grid)

    written = [render_seam.HEIGHTFIELD]
    with rasterio.open(outdir / render_seam.HEIGHTFIELD, "w", driver="GTiff",  # pyright: ignore[reportCallIssue]
                       width=grid.px, height=grid.px, count=1, dtype="float32",
                       **GTIFF_CREATE) as out:
        out.write(heights.astype(np.float32), 1)

    prep_block.write_mask(outdir / render_seam.OCEANMASK, ocean.astype(float))
    # The cap tier collapses watercode 2 and 3 into one boolean, so lake and river cannot be told
    # apart on this grid. The river mask is written EMPTY rather than skipped: the rig reads both,
    # and an absent one would be the statement "this body has no rivers" instead of "this tier
    # cannot separate them", which is a different fact about a different subject.
    prep_block.write_mask(outdir / render_seam.INLANDLAKE, water.astype(float))
    prep_block.write_mask(outdir / render_seam.RIVER, np.zeros(heights.shape))
    written += [render_seam.OCEANMASK, render_seam.INLANDLAKE, render_seam.RIVER]

    snow_a, snow_paint = cap_render._cap_perennial_ice(
        grid, ocean, water, latitude, f"the raytraced {grid.name} cap paints no ice")
    if snow_a is not None and snow_a.any() and snow_paint is not None:
        prep_block.write_mask(outdir / render_seam.SNOWMASK, snow_a)
        render_seam.declare_paint(outdir, render_seam.SNOWMASK, *snow_paint)
        written.append(render_seam.SNOWMASK)

    # ARRIVES GATED FROM ITS PRODUCER, and this prep has no option to forget. The first version of
    # this file, as an arm, applied the gate itself and an earlier draft omitted it: 99.92% of the
    # north disc's land painted ice-white and flattened to 0.46x relief, with nothing red anywhere.
    # → HISTORY, *the sea-ice ocean gate moves to its producers*.
    ice_a = cap_render._cap_sea_ice(grid, ocean, f"the raytraced {grid.name} cap paints no pack ice")
    if ice_a is not None and ice_a.any():
        prep_block.write_mask(outdir / render_seam.SEAICE, ice_a)
        render_seam.declare_paint(outdir, render_seam.SEAICE, *seaice.ice_paint())
        written.append(render_seam.SEAICE)
    return written


def write_frame(grid: cap_render.CapGrid, outdir: Path) -> dict[str, Any]:
    """The rig's frame numbers for this disc, through `render_prep`'s own seam. Reads no raster.

    WHICH NUMBER IS THE PLANE AND WHICH IS THE PHOTOGRAPH. `width_px`/`height_px` and the ground
    extent are the PLANE's, because the heightfield covers the whole disc; `hero_long_edge` is one
    QUADRANT, because that is the rectangle Cycles actually traces. Swapping them renders happily at
    the wrong scale, which is why `tests/test_prep_cap.py` pins both against `CAP_QUADRANT_SPLIT`
    rather than against each other.

    `camera_fraction` IS WHAT MAKES THE QUADRANT CAMERA POSSIBLE. The plane is 2.0 Blender units
    across, so seeing `1 / SPLIT` of it puts `ortho_scale` at `2.0 / SPLIT`, and the camera then
    offsets by half an `ortho_scale` to centre on its own quarter. At any other fraction the frames
    overlap or leave a gap, and a stitched disc with a one-pixel gap reads as a render artefact
    rather than as a wrong argument.
    """
    extent_m = 2.0 * grid.edge_m
    numbers = render_prep.scene_numbers(
        grid.px, grid.px, extent_m, exaggeration=grid.body.exaggeration,
        hero_long_edge=grid.px // cap_render.CAP_QUADRANT_SPLIT,
        camera_fraction=1.0 / cap_render.CAP_QUADRANT_SPLIT)
    # The full FRAME_KEYS vocabulary in a cap's own terms: no padded lon/lat frame exists, the CRS
    # is the grid's OWN projection string rather than a second spelling of it, and the extents are
    # AEQD map units — which `cap_recipe` converts to ground metres separately, since the rig wants
    # the grid it was warped on and the recipe wants what a metre is worth on this planet.
    payload = dict(numbers, body=grid.body.name, exaggeration=grid.body.exaggeration,
                   width_px=grid.px, height_px=grid.px, frame_lonlat=None, dst_crs=grid.aeqd,
                   xres_m=extent_m / grid.px, extent_w_m=extent_m, extent_h_m=extent_m)
    (outdir / "frame.json").write_text(render_prep.frame_json_text(payload))
    return payload


def write_recipe(grid: cap_render.CapGrid, rasters: frozenset[str], outdir: Path,
                 written: list[str]) -> None:
    """The constants this cut baked in, machine-readable and beside the output.

    NOT WHAT MAKES A DISC RESTAGE, exactly as `prep_block.write_recipe` is not. The cap's freshness
    lives in `cap_render.cap_recipe`, which is compared against the served rungs; this is for the
    standalone cut, where the directory is kept and someone has to be able to ask what made it.
    """
    freshness.write_if_changed(outdir / RECIPE_NAME, json.dumps({
        "body": grid.body.name,
        "pole": grid.name,
        "grid": cap_render.grid_recipe_fields(grid),
        "quadrant_split": cap_render.CAP_QUADRANT_SPLIT,
        "exaggeration": grid.body.exaggeration,
        "ground_scale": bodies.ground_metres_per_aeqd_unit(grid.body),
        "layers_off": layers.layers_off(grid.body, layers.CAP_LAYERS),
        "rasters_off": planet_seam.rasters_off(rasters),
        "mask_full_scale": prep_block.MASK_FULL_SCALE,
        # `painted=True` because the two cryosphere masks are declared with their colours above, so
        # a body's white reaches a raytraced cap pixel through this directory and nothing else.
        **layer_producers.constants_for(grid.body, layers.CAP_LAYERS, painted=True),
        "images": sorted(written),
    }, indent=2, sort_keys=True) + "\n")


def cut(grid: cap_render.CapGrid, rasters: frozenset[str], outdir: Path) -> dict[str, Any]:
    """Fill `outdir` with everything the rig needs for one cap, and return its frame numbers.

    THE FOUR CALLS ARE ONE STAGE AND THEIR ORDER IS THE CONTRACT, as `prep_block.cut` states it:
    images, then the frame the rig reads them through, then the recipe that says what settings made
    them, and only then the declaration — which is what says the stage finished, so it goes last and
    after the files exist.
    """
    written = build(grid, rasters, outdir)
    frame = write_frame(grid, outdir)
    write_recipe(grid, rasters, outdir, written)
    render_seam.declare(outdir, render_seam.CAP, written)
    return frame


def grid_for(body: bodies.Body, pole: str) -> cap_render.CapGrid:
    """This body's grid for one pole, named the way the CLI names it.

    NO DEFAULT POLE ANYWHERE ABOVE THIS. The south is 100% land with real relief where the north is
    mostly flat pack ice, so the two are not one measurement wearing two names, and a prep that
    guessed would fill a directory that renders perfectly and shows the wrong hemisphere.
    """
    return cap_render.north_grid(body) if pole == "north" else cap_render.south_grid(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--body", required=True, choices=sorted(bodies.BODIES),
                        help="which planet this cap belongs to; no default, for the reason "
                             "`Body` fields have none")
    parser.add_argument("--pole", required=True, choices=("north", "south"))
    parser.add_argument("--out", type=Path, default=None,
                        help="where to write; defaults to this pole's own cap render directory")
    args = parser.parse_args()

    body = bodies.get(args.body)
    grid = grid_for(body, args.pole)
    outdir = args.out if args.out is not None else cap_render.cap_render_dir(grid)
    # Read once and threaded, exactly as the cap and planet passes do it. This raises when the
    # planet stage never finished, so a cap can never be prepped from half a fusion.
    frame = cut(grid, planet_seam.declared(body), outdir)
    print(f"{outdir}: plane {grid.px}px photographed at {frame['res_x']}x{frame['res_y']} "
          f"per quadrant, ortho {frame['ortho_scale']:.4f}, "
          f"{cap_render.cap_ground_metres_per_px(grid):.1f} m/px")


if __name__ == "__main__":
    main()
