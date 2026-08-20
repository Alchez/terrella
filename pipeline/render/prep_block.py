"""Cut one Mercator block out of a body's warped rasters into the images the rig loads.

`render_prep`'s TWIN, and the second stage that fills a render directory. That one cuts a country
out of its own Albers fusion; this one cuts a square of the tile grid. Both hand `scene_build` the
same directory, which is why the framing maths is not repeated here — `render_prep.scene_numbers`
takes a grid size, a ground width and an exaggeration and returns every number the rig reads out of
frame.json.

WHICH BLOCK IS THE CALLER'S QUESTION. This takes an origin and a size and cuts exactly that; the
partition and the margin law are `block_plan`'s, and choosing an order over them is the runner's.

WHAT THIS BODY HAS IS READ FROM TWO DECLARATIONS AND NEVER FROM DISK. `planet_seam.declared` says
which planet rasters exist, so a body with no ocean mask is never asked for one; `Body.surface_layers`
and the producer registry say which cryosphere layers it paints, and `layer_producers.gather` runs
them. Neither is a `Path.exists()` sweep, because a missing file cannot tell "this planet has none"
from "the stage that makes it died".

THE ANTARCTIC WHITE IS THE REASON THE REGISTRY IS CALLED RATHER THAN THE RULES. Earth's white is a
union of three terms and only two have a raster; the third is a latitude-and-land patch that rides
`perennial_ice`'s declaration. Reaching for `snow.antarctic_snow_mask` directly would apply it on
every body, and Mars declares that same layer — so a verbatim port whitens Martian land below 60
degrees south. `_earth_perennial_ice` carries the patch and `_mars_perennial_ice` does not.

Usage:
  python3 -m pipeline.render.prep_block --body earth --col 39424 --row 24576 \
      --margin 256 --outdir data/work/earth/blocks/39424_24576
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.windows import Window

from pipeline import block_plan, bodies, freshness, layers, planet_seam
from pipeline.look import lake_depth, layer_producers, snow
from pipeline.raster_io import GTIFF_CREATE
from pipeline.render import render_prep, render_seam
from pipeline.tile import shade_planet

#: The recipe this stage bakes into its outputs, beside them, as every writer in the pipeline does.
RECIPE_NAME = "block_recipe.json"


def block_window(col: int, row: int, size: int, margin: int) -> Window:
    """The window actually rendered: the delivered block plus its margin on every side.

    The margin is rendered and thrown away, so that terrain just outside the block can still throw
    a shadow across the boundary — `block_plan`'s module docstring holds why.
    """
    return Window(col - margin, row - margin,  # pyright: ignore[reportCallIssue]
                  size + 2 * margin, size + 2 * margin)


def ground_width_m(window: Window, body: bodies.Body) -> float:
    """The block's true ground width at its mid-latitude, in metres.

    TWO CORRECTIONS TO THE MERCATOR WIDTH AND THE SECOND IS THE BODY'S. Mercator metres shrink
    toward the equator by `cos(latitude)`, which is the first; and a Mercator unit is not a ground
    metre on a body whose own radius differs from the projection sphere's, which is the second and
    is exactly 1.0 on Earth. `bodies.ground_metres_per_mercator_unit` owns that ratio — 1.878 on
    Mars — and a copy that dropped it would undersize the great majority of Martian blocks while
    being perfect on the only planet anyone tests against.
    """
    mid_row = window.row_off + window.height / 2.0
    mid_latitude = block_plan.row_latitude_deg(mid_row, body)
    mercator_width = window.width * body.map_units_per_pixel
    return (mercator_width * math.cos(math.radians(mid_latitude))
            * bodies.ground_metres_per_mercator_unit(body))


def _read(path: Path, window: Window) -> np.ndarray:
    with rasterio.open(path) as dataset:  # pyright: ignore[reportCallIssue]
        return dataset.read(1, window=window, boundless=True, fill_value=0)


def gated_sea_ice(contribution: "np.ndarray | None", ocean: np.ndarray) -> "np.ndarray | None":
    """The ice alpha confined to ocean pixels, or None when no pixel survives.

    THE GATE IS THE COASTAL-COLLAPSE GUARD, not bookkeeping: the same alpha damps displacement in
    the rig, and ungated it would drag shoreline LAND toward sea level at full exaggeration.
    `shade.composite` applies the identical gate for its own paint, and
    `layers.SEA_ICE.requires_raster` is why an ocean mask is guaranteed wherever this layer is.
    """
    if contribution is None:
        return None
    gated = np.where(ocean, contribution, 0.0)
    return gated if bool(gated.any()) else None


def _write_mask(out: Path, array: np.ndarray) -> None:
    """A 0..1 field as 8-bit grey, which the rig takes as a Mix FACTOR rather than a switch.

    Safe as grey because `scene_build.load_image` sets Non-Color, so 0..255 maps linearly with no
    sRGB transform — which a binary mask would not have noticed and a soft alpha very much would.
    """
    scaled = np.rint(np.clip(array, 0.0, 1.0) * 255.0).astype(np.uint8)
    with rasterio.open(out, "w", driver="PNG", width=scaled.shape[1],  # pyright: ignore[reportCallIssue]
                       height=scaled.shape[0], count=1, dtype="uint8") as png:
        png.write(scaled, 1)


def build(body: bodies.Body, window: Window, outdir: Path) -> list[str]:
    """Cut every image this body can produce for `window`, and return what was written."""
    work = bodies.work_dir(body, "planet_tiles")
    rasters = planet_seam.declared(body)
    outdir.mkdir(parents=True, exist_ok=True)
    written = [render_seam.HEIGHTFIELD]

    with rasterio.open(work / shade_planet.HEIGHT_3857) as height:  # pyright: ignore[reportCallIssue]
        elevation = height.read(1, window=window, boundless=True, fill_value=0)
        transform = height.window_transform(window)
    with rasterio.open(outdir / render_seam.HEIGHTFIELD, "w", driver="GTiff",  # pyright: ignore[reportCallIssue]
                       width=window.width, height=window.height, count=1, dtype="float32",
                       crs="EPSG:3857", transform=transform, **GTIFF_CREATE) as out:
        out.write(elevation.astype(np.float32), 1)

    shape = elevation.shape
    ocean = (_read(work / shade_planet.OCEAN_3857, window).astype(bool)
             if "oceanmask" in rasters else np.zeros(shape, bool))
    watercode = _read(work / shade_planet.WATER_3857, window) if "watermask" in rasters else None
    if "oceanmask" in rasters:
        _write_mask(outdir / render_seam.OCEANMASK, ocean.astype(float))
        written.append(render_seam.OCEANMASK)
    if watercode is not None:
        _write_mask(outdir / render_seam.INLANDLAKE, (watercode == 2).astype(float))
        _write_mask(outdir / render_seam.RIVER, (watercode == 3).astype(float))
        written += [render_seam.INLANDLAKE, render_seam.RIVER]

    top = block_plan.mercator.MERCATOR_HALF_M - window.row_off * body.map_units_per_pixel
    bottom = top - window.height * body.map_units_per_pixel
    inland = lake_depth.inland_water(watercode) if watercode is not None else np.zeros(shape, bool)
    seen = layer_producers.LayerWindow(
        raw=None, watercode=watercode, land=~(ocean | inland),
        latitude=snow.latitude_per_row(top, bottom, window.height), top=top, bottom=bottom)
    layer_raw = {layer.name: (_read(layer.warped_in(work), window)
                             if layer.name in body.surface_layers
                             and layer.warped_in(work).exists() else None)
                 for layer in layers.WARPED_LAYERS}
    contributions, _ = layer_producers.gather(body, layer_raw, seen, layers.BLOCK_LAYERS)

    # WRITTEN ONLY WHERE IT REACHES A PIXEL, AND DECLARED EITHER WAY. Skipping an all-zero mask is a
    # real saving across thousands of blocks; leaving the skip undeclared is what turned it into an
    # inference, since the rig then had to read meaning into an absent file.
    white, _ = layer_producers.fold_white(contributions, shape)
    if white.any():
        _write_mask(outdir / render_seam.SNOWMASK, white)
        written.append(render_seam.SNOWMASK)
    depth = contributions.get(layers.LAKE_DEPTH.name)
    if depth is not None and bool((depth > 0).any()):
        with rasterio.open(outdir / render_seam.LAKEDEPTH, "w", driver="GTiff",  # pyright: ignore[reportCallIssue]
                           width=window.width, height=window.height, count=1,
                           dtype="float32", **GTIFF_CREATE) as out:
            out.write(depth.astype(np.float32), 1)
        written.append(render_seam.LAKEDEPTH)
    ice = gated_sea_ice(contributions.get(layers.SEA_ICE.name), ocean)
    if ice is not None:
        _write_mask(outdir / render_seam.SEAICE, ice)
        written.append(render_seam.SEAICE)
    return written


def write_frame(body: bodies.Body, window: Window, outdir: Path) -> dict[str, Any]:
    """The rig's frame numbers for this block, through `render_prep`'s own seam.

    `hero_long_edge` is the window's own edge because a block renders 1:1 with its heightfield,
    where a hero renders 7680 from a 16384-wide grid.
    """
    extent_w_m = ground_width_m(window, body)
    numbers = render_prep.scene_numbers(
        window.width, window.height, extent_w_m,
        exaggeration=body.exaggeration, hero_long_edge=window.width)
    # The full FRAME_KEYS vocabulary, answered in a block's own terms: no padded lon/lat frame
    # exists (None is the vocabulary's value for a grid taken from elsewhere), the CRS is the
    # planet grid's, and the extents are ground metres at the block's mid-latitude — the same
    # meaning the hero's AEA metres carry.
    payload = dict(numbers, body=body.name, exaggeration=body.exaggeration,
                   width_px=window.width, height_px=window.height,
                   frame_lonlat=None, dst_crs="EPSG:3857",
                   xres_m=extent_w_m / window.width, extent_w_m=extent_w_m,
                   extent_h_m=extent_w_m * window.height / window.width)
    (outdir / "frame.json").write_text(render_prep.frame_json_text(payload))
    return payload


def write_recipe(body: bodies.Body, window: Window, outdir: Path, written: list[str]) -> None:
    """The constants this cut baked in, machine-readable and beside the output.

    A PROSE README WITH A GIT SHA IS NOT A RECIPE. Existence cannot see a settings change, so every
    writer in this pipeline records the values it used where a freshness check can compare them;
    a commit id names the whole tree and moves on every checkout that touches anything at all.
    """
    freshness.write_if_changed(outdir / RECIPE_NAME, json.dumps({
        "body": body.name,
        "col": window.col_off, "row": window.row_off,
        "width": window.width, "height": window.height,
        "exaggeration": body.exaggeration,
        "ground_scale": bodies.ground_metres_per_mercator_unit(body),
        "map_units_per_pixel": body.map_units_per_pixel,
        "layers_off": layers.layers_off(body, layers.BLOCK_LAYERS),
        "rasters_off": planet_seam.rasters_off(planet_seam.declared(body)),
        "images": sorted(written),
    }, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body", required=True, choices=sorted(bodies.BODIES),
                        help="which planet's grid and look to cut from; no default, because a "
                             "body that quietly inherited Earth's would prepare a plausible "
                             "wrong planet")
    parser.add_argument("--col", type=int, required=True, help="block origin column on the grid")
    parser.add_argument("--row", type=int, required=True, help="block origin row on the grid")
    parser.add_argument("--size", type=int, default=block_plan.RENDER_BLOCK_PX,
                        help="delivered edge of the block in pixels")
    parser.add_argument("--margin", type=int, required=True,
                        help="rendered-and-discarded halo, from block_plan.margin_for; required "
                             "because a zero margin loses every shadow crossing the boundary and "
                             "does it silently, on both sides, with no edge to notice")
    parser.add_argument("--outdir", type=Path, required=True, help="the render directory to fill")
    args = parser.parse_args()

    body = bodies.BODIES[args.body]
    window = block_window(args.col, args.row, args.size, args.margin)
    written = build(body, window, args.outdir)
    frame = write_frame(body, window, args.outdir)
    write_recipe(body, window, args.outdir, written)
    print(f"declared {render_seam.declare(args.outdir, render_seam.BLOCK, written)}", flush=True)
    print(f"{body.name} block col={args.col} row={args.row} {args.size}px "
          f"+{args.margin} margin -> {window.width}x{window.height}; "
          f"ground width {frame['extent_w_m'] / 1000:.1f} km; "
          f"images {', '.join(sorted(written))}", flush=True)


if __name__ == "__main__":
    main()
