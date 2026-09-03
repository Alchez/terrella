"""Cut one Mercator block out of a body's warped rasters into the images the rig loads.

`render_prep`'s TWIN, and the second stage that fills a render directory. That one cuts a country
out of its own Albers fusion; this one cuts a square of the tile grid. Both hand `scene_build` the
same directory, which is why the framing maths is not repeated here — `render_prep.scene_numbers`
takes a grid size, a ground width and an exaggeration and returns every number the rig reads out of
frame.json.

WHICH BLOCK IS THE CALLER'S QUESTION. This takes a `Block` and cuts exactly its plane window; the
partition and the context law are `block_plan`'s, and choosing an order over them is the runner's.

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
  python3 -m pipeline.render.prep_block --body earth --col 40960 --row 24576 \
      --context 512 --outdir data/work/earth/blocks/40960_24576
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.transform import from_origin
from rasterio.windows import Window

from pipeline import block_plan, bodies, freshness, layers, planet_seam, planet_warp
from pipeline.block_plan import Block
from pipeline.look import lake_depth, layer_producers, snow
from pipeline.raster_io import GTIFF_CREATE
from pipeline.render import render_prep, render_seam
from pipeline.tile import relief_scan

#: The recipe this stage bakes into its outputs, beside them, as every writer in the pipeline does.
RECIPE_NAME = "block_recipe.json"

#: The integer range a 0..1 mask is written across, and it is a GEOMETRY constant. `write_mask`
#: holds why 8 bits terraced the sea floor; this is named rather than spelled inline so that
#: `block_render.params` can record it, since a depth change moves pixels and blocks are skipped by
#: marker existence alone.
MASK_FULL_SCALE = 65535.0

#: What a plane overhanging the grid at a POLE reads there, as a `numpy.pad` mode. Named for the
#: same reason as the depth above: `block_render.params` records it, and without that a change of
#: policy moves every edge block's pixels while every marker still says the block is rendered.
#: "edge" repeats the last real row. The alternative that shipped before it was a zero FILL, which
#: is not a neutral elevation anywhere — Mars's grid ends at -3,565 m north and Earth's at -2,732 —
#: so it stood a wall of invented geometry along each pole-side plane. `_read_cyclic` carries the
#: measurement; the columns take no mode at all, because longitude wraps instead.
ROW_EDGE_MODE = "edge"


def mid_latitude_deg(window: Window, body: bodies.Body) -> float:
    """The one latitude a plane's single ground width is true at: its centre row.

    ONE OWNER, AND THAT IS THE WHOLE REASON IT IS A FUNCTION. `ground_width_m` multiplies by this
    cosine and `row_scale` divides by it, so the two must agree on the same row or the plane comes
    out uniformly exaggerated at the wrong value. That failure has no symptom: the joins match, the
    within-block gradient is gone, and every seam measurement reads clean while the whole planet is
    scaled wrong. Two spellings of "the middle" is all it would take.
    """
    return block_plan.row_latitude_deg(window.row_off + window.height / 2.0, body)


def ground_width_m(window: Window, body: bodies.Body) -> float:
    """The block's true ground width at its mid-latitude, in metres.

    TWO CORRECTIONS TO THE MERCATOR WIDTH AND THE SECOND IS THE BODY'S. Mercator metres shrink
    toward the equator by `cos(latitude)`, which is the first; and a Mercator unit is not a ground
    metre on a body whose own radius differs from the projection sphere's, which is the second and
    is exactly 1.0 on Earth. `bodies.ground_metres_per_mercator_unit` owns that ratio — 1.878 on
    Mars — and a copy that dropped it would undersize the great majority of Martian blocks while
    being perfect on the only planet anyone tests against.

    ONE WIDTH IS ALL A PLANE CAN HAVE, and that is not the same as one width being right. The plane
    is a single rectangle, so the Blender-unit scale it is framed at has to be a single number;
    Mercator's ground scale is not. `row_scale` carries the difference on the displacement rather
    than here, which is why this function keeps its mid-latitude meaning unchanged.
    """
    mercator_width = window.width * body.map_units_per_pixel
    return (mercator_width * math.cos(math.radians(mid_latitude_deg(window, body)))
            * bodies.ground_metres_per_mercator_unit(body))


def row_scale(window: Window, body: bodies.Body) -> NDArray[np.float64]:
    """Per-row multiplier on the displacement that makes the applied exaggeration uniform.

    THE DEFECT IT EXISTS TO REMOVE. `displacement_scale` converts elevation metres into Blender
    units through `ground_width_m`, which is one number taken at the plane's centre row. Mercator's
    ground metres per pixel vary continuously with latitude, so that number is right on exactly one
    row, and neighbouring block rows disagree across their shared edge by the ratio of their two
    centre cosines. The measurements are in the tests and in the decision archive rather than here,
    on the rule that a comment may not carry a number that can go false behind its back.

    WHAT IT MULTIPLIES TO. `displacement_scale * row_scale(r) * (width / 2)` times the ground metres
    one pixel covers at row r is exactly `Body.exaggeration`, on every row, with the centre row's
    cosine cancelling completely.

    IT IS NOT THE COMPOSITE'S LAW, AND AN EARLIER VERSION OF THIS DOCSTRING CLAIMED IT WAS.
    The composited shading's z-factor scaled the GRADIENT per row; this scales the HEIGHT. A
    height field whose gradient is the composite's cannot exist: matching it needs
    `K'(row) * de/dcol == 0` everywhere, so no scalar displacement reproduces it and the difference
    is a spurious row-ward tilt of `K'(row) * elevation`. That term is proportional to ELEVATION and
    not to relief, so it is largest exactly where relief is smallest, which is the polar ice. What
    this buys is a continuous field in place of a discontinuous one at the block joins; what it
    costs is that tilt, and the caps keep the gradient law across the 81 to 84 blend either way.
    Which of the two is preferable is a look judgement made on rendered pixels, not on this algebra.

    CLIPPED AT MERCATOR'S LIMIT because `block_plan.row_latitude_deg` clips there, and a plane may
    extend past the grid on the pole side. Those rows now carry the CLAMPED edge elevation rather
    than a fill, so the value is felt and has to be right: what matters is that it stays finite and
    that this uses the same spelling of "the latitude of a row" the partition and the context law
    use. An earlier version of this paragraph said the rows were zero-filled and the value therefore
    unfelt, which was true of the reader at the time and was the defect.
    """
    rows = np.arange(window.row_off, window.row_off + window.height, dtype=np.float64)
    latitudes = np.array([block_plan.row_latitude_deg(float(row), body) for row in rows])
    return np.cos(np.radians(mid_latitude_deg(window, body))) / np.cos(np.radians(latitudes))


def _read_cyclic(dataset: Any, window: Window) -> np.ndarray:
    """`window` read from an open dataset: columns WRAP around longitude, rows CLAMP at the poles.

    THE TWO AXES ARE NOT SYMMETRIC, which is the same split `Block.plane_window` and
    `cast_shadow.shadow_mask` make: a Mercator planet joins itself at the antimeridian and does not
    join itself at the poles. Both halves are here because a plane may overhang either edge and
    neither overhang may invent geometry.

    NEITHER AXIS MAY BE FILLED, AND THE DATUM IS NOT A NEUTRAL VALUE. On the columns a fill puts a
    sea-level plateau where the far side of the antimeridian belongs, reads as LAND on the ocean
    mask, and the NW sun casts that wall east across block column 0. On the rows it does the same
    thing standing up: Mars's grid ends at -2,967 m, so filling with 0 raises a wall 2,967 m of real
    elevation proud of the ground it replaces, which at that body's exaggeration models as 59 km of
    cliff along the north edge of every row-0 plane. Clamping repeats the edge row, the one choice
    that adds nothing — and it is what `plane_window` has always documented.

    The rows are padded rather than read boundless because `boundless` has no edge mode: it fills,
    and the fill is the defect.
    """
    # `ROW_EDGE_MODE` rather than a literal here: `block_render.params` records it, so flipping the
    # policy restages every block instead of leaving a rendered planet reading fresh under it.
    height = dataset.height
    row_off, rows = int(window.row_off), int(window.height)
    above = max(0, -row_off)
    below = max(0, row_off + rows - height)
    inner_rows = rows - above - below
    if inner_rows <= 0:
        raise ValueError(f"a plane spanning rows {row_off} to {row_off + rows} lies entirely off a "
                         f"grid {height} rows tall, so there is no edge row to clamp to")
    inner = Window(window.col_off, row_off + above, window.width, inner_rows)  # pyright: ignore[reportCallIssue]

    width = dataset.width
    col_off, remaining = int(inner.col_off), int(inner.width)
    pieces = []
    while remaining > 0:
        start = col_off % width
        take = min(remaining, width - start)
        pieces.append(dataset.read(1, window=Window(start, inner.row_off,  # pyright: ignore[reportCallIssue]
                                                    take, inner.height)))
        col_off += take
        remaining -= take
    read = pieces[0] if len(pieces) == 1 else np.hstack(pieces)
    if not above and not below:
        return read
    return np.pad(read, ((above, below), (0, 0)), mode=ROW_EDGE_MODE)


def _read(path: Path, window: Window) -> np.ndarray:
    with rasterio.open(path) as dataset:  # pyright: ignore[reportCallIssue]
        return _read_cyclic(dataset, window)


def write_mask(out: Path, array: np.ndarray) -> None:
    """A 0..1 field as 16-bit grey, which the rig takes as a Mix FACTOR rather than a switch.

    PUBLIC BECAUSE TWO PREPS FILL A RENDER DIRECTORY. `prep_cap` writes the same masks for the same
    rig, so the depth below is one law with two readers and this is its owner. It stays here rather
    than moving somewhere neutral because the measurement that fixes the depth is a statement about
    what the rig does with these masks, which is this module's subject.

    Safe as grey because `scene_build.load_image` sets Non-Color, so the range maps linearly with no
    sRGB transform, which a binary mask would not have noticed and a soft alpha very much would.

    THE DEPTH IS A GEOMETRY CONSTRAINT AND NOT A COLOUR ONE, which is why 8 bits was not enough.
    `scene_build` wires the sea-ice alpha to two arms: an ice-white colour mix, and `Mix.005 Ice
    Flatten`, which pulls displacement toward sea level. So a quantised alpha terraces the sea
    floor rather than merely banding its colour, and each level boundary becomes a riser of
    `depth * quantum * exaggeration` metres. At 8 bits over abyssal water that is a step far taller
    than the ground one pixel covers, so it is a slope past 45 degrees against a 45-degree sun and
    every boundary self-shadows into a visible line.

    `test_a_quantised_alpha_does_not_terrace_the_sea_floor_past_one_ground_pixel` is the bound, and
    it is stated as that physical law rather than as a bit count so it cannot rot behind a retune.
    A binary mask is exact at any depth, so this costs the switch-shaped masks nothing but bytes.
    """
    scaled = np.rint(np.clip(array, 0.0, 1.0) * MASK_FULL_SCALE).astype(np.uint16)
    with rasterio.open(out, "w", driver="PNG", width=scaled.shape[1],  # pyright: ignore[reportCallIssue]
                       height=scaled.shape[0], count=1, dtype="uint16") as png:
        png.write(scaled, 1)


def _write_rowscale(out: Path, window: Window, body: bodies.Body) -> None:
    """`row_scale` as a one-pixel-wide column, as tall as the plane, for the rig to sample per row.

    ONE PIXEL WIDE, AND THAT IS THE POINT RATHER THAN A SAVING. The correction is constant along a
    row by construction, so a plane-sized field would carry no extra information; Blender expands a
    float image to RGBA float, which on the widest plane is about a gigabyte on top of a render
    already peaking near 7.5 GB, against 131 KB for the column.

    IT CALLS `row_scale` AND MUST GO ON DOING SO. A copy of the law here would be inert under every
    mutation `scripts/sabotage.py` makes, so all four of its cases would report CAUGHT while the
    raster the rig actually samples stayed unmutated — a harness lying in the direction that reads
    as safe.

    Written top-down like every other raster here, so row 0 is the northernmost, and GEOREFERENCED
    as the plane's westmost pixel column, which is what it is: the rig samples it by UV and never
    reads the transform, but writing one makes the file a legitimate crop rather than a bare array,
    lets a verifier check its rows against the heightfield's, and keeps `NotGeoreferencedWarning`
    meaning something the next time it fires.
    """
    column = row_scale(window, body).reshape(-1, 1).astype(np.float32)
    half = block_plan.mercator.MERCATOR_HALF_M
    transform = from_origin(
        -half + window.col_off * body.map_units_per_pixel,
        half - window.row_off * body.map_units_per_pixel,
        body.map_units_per_pixel, body.map_units_per_pixel)
    with rasterio.open(out, "w", driver="GTiff", width=1,  # pyright: ignore[reportCallIssue]
                       height=window.height, count=1, dtype="float32",
                       crs="EPSG:3857", transform=transform, **GTIFF_CREATE) as tif:
        tif.write(column, 1)


def one_colour(value: Any, what: str) -> render_seam.RGB8:
    """One RGB triple from a producer's paint, refusing anything that varies inside this window.

    A PAINT MAY LEGITIMATELY VARY AND A RIG SHADER SOCKET CANNOT, so the reduction has to be a
    check rather than an average. Mars answers `(3, H, 1)` because its two poles are different
    colours; that array is constant within any block, since it splits at the equator and Mars
    carries no ice within 76 degrees of it. A block that straddled the split would be a real
    conflict with no correct single answer, and averaging two measured whites into a third that
    neither pole has would render it as though it had been chosen.
    """
    array = np.asarray(value, dtype=np.float64).reshape(3, -1)
    if not np.allclose(array, array[:, :1]):
        raise ValueError(
            f"{what} varies within this window, and the rig paints one colour per mask. "
            f"Split the render so each side gets its own, or give this body a paint that is "
            f"constant over a block.")
    red, green, blue = (round(channel) for channel in array[:, 0])
    return red, green, blue


def merged_paint(paints: dict[str, tuple[Any, Any]], members: "tuple[layers.Layer, ...]",
                 what: str) -> "render_seam.Paint | None":
    """The one paint the layers folding into a single mask agree on, or None if none contributed.

    THE FOLD IS A MAXIMUM OVER ALPHAS AND CARRIES NO COLOUR, so several layers land in one image
    and the rig gets one socket for it. Earth's perennial ice and glaciers both answer `_earth_white`
    and agree trivially; a body whose two white layers disagreed would have no representable answer
    here, which is why this refuses rather than picking the first.
    """
    present = [paints[layer.name] for layer in members if layer.name in paints]
    if not present:
        return None
    resolved = [(one_colour(sunlit, f"{what} sunlit"), one_colour(shadowed, f"{what} shadowed"))
                for sunlit, shadowed in present]
    if len({pair for pair in resolved}) > 1:
        raise ValueError(f"{what}: layers folding into one mask declare different colours "
                         f"{resolved}; the rig has one socket for them.")
    return resolved[0]


def build(body: bodies.Body, window: Window, outdir: Path, *, work: Path) -> list[str]:
    """Cut every image this body can produce for `window`, and return what was written.

    THE PAINTS ARE DECLARED HERE AND USED TO BE DISCARDED ON ONE LINE. `gather` already resolves
    each layer's colour from this body's own registry for this window — `_earth_white` for Earth,
    `_mars_ice_white` per pole for Mars — and this stage kept the alphas and threw the colours away,
    because the rig held its own module-level white. That white is Earth's, so every body rendered
    in it and Earth was indistinguishable from correct. The registry answer now travels with the
    mask it belongs to; `render_seam.PAINTED_IMAGES` holds why it has to travel as data.

    `work` IS THE CALLER'S AND IS NEVER RE-DERIVED HERE, which is what makes `block_render --work` a
    seam rather than half of one: this used to resolve the body's default stage directory itself, so
    a run pointed at a second store checked that store's inputs and cut its pixels from the first.
    Keyword-only because it and `outdir` are both directories, and a swapped pair would read the
    render directory as a planet and write the block into the store.
    """
    rasters = planet_seam.declared(body)
    outdir.mkdir(parents=True, exist_ok=True)
    written = [render_seam.HEIGHTFIELD]

    with rasterio.open(work / planet_warp.HEIGHT_3857) as height:  # pyright: ignore[reportCallIssue]
        elevation = _read_cyclic(height, window)
        transform = height.window_transform(window)
    with rasterio.open(outdir / render_seam.HEIGHTFIELD, "w", driver="GTiff",  # pyright: ignore[reportCallIssue]
                       width=window.width, height=window.height, count=1, dtype="float32",
                       crs="EPSG:3857", transform=transform, **GTIFF_CREATE) as out:
        out.write(elevation.astype(np.float32), 1)

    # Unconditional, and unlike every other optional image below it that is not a measurement: the
    # correction is a property of the PROJECTION, so every block has one and no block declines.
    _write_rowscale(outdir / render_seam.ROWSCALE, window, body)
    written.append(render_seam.ROWSCALE)

    shape = elevation.shape
    ocean = (_read(work / planet_warp.OCEAN_3857, window).astype(bool)
             if "oceanmask" in rasters else np.zeros(shape, bool))
    watercode = _read(work / planet_warp.WATER_3857, window) if "watermask" in rasters else None
    if "oceanmask" in rasters:
        write_mask(outdir / render_seam.OCEANMASK, ocean.astype(float))
        written.append(render_seam.OCEANMASK)
    if watercode is not None:
        write_mask(outdir / render_seam.INLANDLAKE, (watercode == 2).astype(float))
        write_mask(outdir / render_seam.RIVER, (watercode == 3).astype(float))
        written += [render_seam.INLANDLAKE, render_seam.RIVER]

    top = block_plan.mercator.MERCATOR_HALF_M - window.row_off * body.map_units_per_pixel
    bottom = top - window.height * body.map_units_per_pixel
    inland = lake_depth.inland_water(watercode) if watercode is not None else np.zeros(shape, bool)
    latitude = snow.latitude_per_row(top, bottom, window.height)
    seen = layer_producers.LayerWindow(
        raw=None, watercode=watercode, land=~(ocean | inland), ocean=ocean, latitude=latitude,
        ground_metres_per_px=block_plan.mercator.ground_metres_per_pixel(
            latitude, body.map_units_per_pixel,
            bodies.ground_metres_per_mercator_unit(body)),
        top=top, bottom=bottom)
    layer_raw = {layer.name: (_read(layer.warped_in(work), window)
                             if layer.name in body.surface_layers
                             and layer.warped_in(work).exists() else None)
                 for layer in layers.warped_for(layers.BLOCK_LAYERS)}
    contributions, paints, exclusions = layer_producers.gather(body, layer_raw, seen,
                                                               layers.BLOCK_LAYERS)

    # WRITTEN ONLY WHERE IT REACHES A PIXEL, AND DECLARED EITHER WAY. Skipping an all-zero mask is a
    # real saving across thousands of blocks; leaving the skip undeclared is what turned it into an
    # inference, since the rig then had to read meaning into an absent file.
    white, _ = layer_producers.fold_white(contributions, shape, exclusions=exclusions)
    if white.any():
        write_mask(outdir / render_seam.SNOWMASK, white)
        written.append(render_seam.SNOWMASK)
        snow_paint = merged_paint(paints, layer_producers.WHITE_UNION, "the white union")
        if snow_paint is None:
            raise ValueError(
                f"{body.name} wrote a snow mask for this window but no producer declared what "
                f"colour it is. A mask the rig cannot paint is not a usable render input.")
        render_seam.declare_paint(outdir, render_seam.SNOWMASK, *snow_paint)
    depth = contributions.get(layers.LAKE_DEPTH.name)
    if depth is not None and bool((depth > 0).any()):
        with rasterio.open(outdir / render_seam.LAKEDEPTH, "w", driver="GTiff",  # pyright: ignore[reportCallIssue]
                           width=window.width, height=window.height, count=1,
                           dtype="float32", **GTIFF_CREATE) as out:
            out.write(depth.astype(np.float32), 1)
        written.append(render_seam.LAKEDEPTH)
    # ALREADY GATED ON OCEAN BY ITS PRODUCER, and None here means the layer reaches no pixel in this
    # window — `seaice.gated_alpha` collapses an all-zero result to None precisely so this stays the
    # question of whether to write a mask at all rather than a second place the law is applied.
    ice = contributions.get(layers.SEA_ICE.name)
    if ice is not None:
        write_mask(outdir / render_seam.SEAICE, ice)
        written.append(render_seam.SEAICE)
        # Its own image and so its own paint: `WHITE_UNION` deliberately excludes sea ice, because
        # its producer gates it on the ocean selector where the union paints land.
        ice_paint = merged_paint(paints, (layers.SEA_ICE,), "sea ice")
        if ice_paint is None:
            raise ValueError(
                f"{body.name} wrote a sea-ice mask for this window but its producer declared no "
                f"colour for it.")
        render_seam.declare_paint(outdir, render_seam.SEAICE, *ice_paint)
    return written


def write_frame(body: bodies.Body, block: Block, outdir: Path) -> dict[str, Any]:
    """The rig's frame numbers for this block, through `render_prep`'s own seam.

    WHERE THE THREE WIDTHS MEET, and each reaches the rig as a different number. The heightfield is
    the PLANE, so `width_px`/`height_px` and the ground extent are the plane's; the render
    resolution is the TRACED edge, because a block renders 1:1 with the grid and only that
    rectangle is photographed; and `camera_fraction` is the ratio between them, which is what
    narrows the camera inside its own plane. A hero has no such distinction, which is why the
    fraction defaults to the overshoot and the resolution to 7680 from a 16384-wide grid.
    """
    window = block.plane_window
    extent_w_m = ground_width_m(window, body)
    numbers = render_prep.scene_numbers(
        window.width, window.height, extent_w_m,
        exaggeration=body.exaggeration, hero_long_edge=block.traced_edge_px,
        camera_fraction=block.traced_edge_px / block.plane_edge_px)
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

    IT IS NOT WHAT MAKES A BLOCK RESTAGE. A pass deletes this directory and skips blocks by marker
    existence, so nothing compares two generations of it — `block_render.params` has the teeth.
    This is for the standalone cut, where the directory is kept.
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
        "mask_full_scale": MASK_FULL_SCALE,
        # `painted=False` because `build` above folds the alpha and drops `gather`'s paints, so no
        # white reaches an image this recipe describes.
        **layer_producers.constants_for(body, layers.BLOCK_LAYERS, painted=False),
        "images": sorted(written),
    }, indent=2, sort_keys=True) + "\n")


def cut(body: bodies.Body, block: Block, outdir: Path, *, work: Path) -> dict[str, Any]:
    """Fill `outdir` with everything the rig needs for one block, and return its frame numbers.

    THE FOUR CALLS ARE ONE STAGE AND THEIR ORDER IS THE CONTRACT: images, then the frame the rig
    reads them through, then the recipe that says what settings made them, and only then the
    declaration — which is what says the stage finished, so it goes last and after the files exist.
    Extracted from `main` so the block runner drives this in-process rather than restating the
    sequence; a second copy would be free to drop the declaration and look like it worked.

    IT TAKES A `Block` RATHER THAN FOUR NUMBERS because the window arithmetic used to live here as
    well as on `Block`, in two copies that nothing tied together: changing one moved no test.
    """
    window = block.plane_window
    written = build(body, window, outdir, work=work)
    frame = write_frame(body, block, outdir)
    write_recipe(body, window, outdir, written)
    render_seam.declare(outdir, render_seam.BLOCK, written)
    return frame


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
    parser.add_argument("--context", type=int, required=True,
                        help="off-camera terrain carried on every side, from "
                             "block_plan.context_for; required because too little of it loses "
                             "every shadow crossing the boundary and does it silently, on both "
                             "sides, with no edge to notice")
    parser.add_argument("--outdir", type=Path, required=True, help="the render directory to fill")
    parser.add_argument("--work", type=Path, default=None,
                        help="override the stage directory cut from; the same seam "
                             "block_render's own --work is, so an A/B cuts from the store it "
                             "names rather than from this body's default")
    args = parser.parse_args()

    body = bodies.BODIES[args.body]
    block = Block(col0=args.col, row0=args.row, size_px=args.size, context_px=args.context)
    work = args.work if args.work is not None else relief_scan.work_dir(body)
    frame = cut(body, block, args.outdir, work=work)
    written = sorted(render_seam.declared(args.outdir))
    print(f"declared {render_seam.declaration_path(args.outdir)}", flush=True)
    print(f"{body.name} block col={args.col} row={args.row} {args.size}px delivered, "
          f"traced {block.traced_edge_px}, plane {block.plane_edge_px} "
          f"(+{args.context} context); ground width {frame['extent_w_m'] / 1000:.1f} km; "
          f"images {', '.join(sorted(written))}", flush=True)


if __name__ == "__main__":
    main()
