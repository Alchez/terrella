"""How a body's Mercator grid is cut into raytraced render blocks, and how wide each block's margin
must be so that nothing casting into it is missing.

A raytraced block is rendered as its own scene, so it can only be lit by geometry inside its own
frame. Terrain just outside the block still throws shadows across the boundary, and a block rendered
to its exact footprint loses them silently: the shadow stops at the seam, on both sides, with no
edge to notice. Each block is therefore rendered wider than it is delivered, by a margin sized from
the tallest relief that can reach into it, and the delivered tile is cropped back out of the middle.

The shadow law itself lives elsewhere. `cast_shadow.shadow_reach_px` owns how far exaggerated relief
throws a shadow, `hillshade.per_row_zfactor_hillshade` owns how the z-factor is built from a body's
exaggeration, its map-unit-to-ground ratio and the row's latitude, and `bodies` owns all three
inputs. What is added here is the per-axis `cos(45 deg)` component of a diagonal shadow, and the
ratio/quantum/ceiling policy.

Pure by construction: a relief grid as an array, a window as numbers, no raster and no open file.
It sits at the root of `pipeline/` rather than in `tile/` because it is a law the block runner and
the cost model both read, in the sense the package note sets out, not a stage that runs.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from rasterio.windows import Window

from pipeline import bodies, mercator
from pipeline.bodies import Body
from pipeline.look import cast_shadow

#: The tile grid's own quantum. Every window this module accepts starts on a whole cell, so a plan
#: can be expressed in the same units as the relief cache that feeds it.
CELL_PX = 512

#: The delivered edge of one render block. NOT named `BLOCK`: `fuse_heightfield` and `render_prep`
#: each already define `BLOCK = 8192` meaning a streaming window, which is a different concept that
#: happens to be measured in the same units.
RENDER_BLOCK_PX = 2048

#: Cache cells along one block's delivered edge. Derived, never written down: the cache is finer
#: than the block ON PURPOSE, so that re-tuning the block edge re-folds an existing cache instead
#: of re-reading a 46 GB master, and a restated 4 would silently decouple the two.
CELLS_PER_BLOCK = RENDER_BLOCK_PX // CELL_PX

#: Fraction of the longest possible shadow a margin has to carry. The tallest relief in a block is
#: not adjacent to every edge of it, so a margin sized for the worst case pays for a shadow that
#: cannot occur. Calibrated, not derived.
MARGIN_RATIO = 0.39

#: Margins round up to this, so that neighbouring blocks share frame sizes and the renderer's
#: allocations repeat instead of being unique per block.
MARGIN_QUANTUM_PX = 64

#: The largest margin any block may ask for. At `MARGIN_RATIO` it is headroom rather than a clamp;
#: it starts binding only as the ratio approaches 1.0, which couples it to `RENDERED_CEILING_PX`.
MARGIN_CEILING_PX = 768

#: The largest square frame renderable on this GPU. A block whose delivered edge plus both margins
#: exceeds it cannot be rendered at all - a different limit from `MARGIN_CEILING_PX`, which bounds
#: the margin alone.
RENDERED_CEILING_PX = 8192

#: Web Mercator's own cut-off. Matches the clip `hillshade.per_row_zfactor_hillshade` applies before
#: it builds a z-factor, so a polar block is sized from the same latitude the shading will use.
MERCATOR_LATITUDE_LIMIT_DEG = 85.05


@dataclass(frozen=True)
class Block:
    """One render block: where it sits on the grid, and how much extra it must render."""

    col0: int
    row0: int
    size_px: int
    margin_px: int

    @property
    def rendered_edge_px(self) -> int:
        """The square frame the renderer actually allocates, margins included."""
        return self.size_px + 2 * self.margin_px

    @property
    def delivered_window(self) -> Window:
        """The pixels this block is responsible for, which is what gets cropped back out."""
        return Window(self.col0, self.row0, self.size_px, self.size_px)  # pyright: ignore[reportCallIssue]

    @property
    def render_window(self) -> Window:
        """The pixels that must be read to render it.

        May extend past the grid on any side. Columns beyond the edge wrap (the planet is cyclic in
        longitude) and rows beyond it clamp, exactly as `cast_shadow.shadow_mask` treats its own
        march - resolving that is the reader's job, not this module's.
        """
        return Window(self.col0 - self.margin_px, self.row0 - self.margin_px,  # pyright: ignore[reportCallIssue]
                      self.rendered_edge_px, self.rendered_edge_px)

    @property
    def fits(self) -> bool:
        """Whether this block can be rendered at all on the proven frame envelope."""
        return self.rendered_edge_px <= RENDERED_CEILING_PX


def grid_px(body: Body) -> int:
    """The edge of this body's full Mercator grid in pixels, at its own maximum tile zoom."""
    return CELL_PX << body.tile_max_zoom


def row_latitude_deg(row: float, body: Body) -> float:
    """Latitude of a pixel row centre on this body's grid, clipped to Mercator's limit.

    The sphere is the PROJECTION's and never the body's: every grid here is EPSG:3857 whatever
    planet supplied the elevations, so reading the radius off the body registry would put Mars's
    rows tens of degrees out. `hillshade._latitude_of_rows` states the same thing at more length.
    """
    northing = mercator.MERCATOR_HALF_M - (row + 0.5) * body.map_units_per_pixel
    latitude = float(mercator.latitude_at(northing, mercator.WEB_MERCATOR_RADIUS_M))
    return float(np.clip(latitude, -MERCATOR_LATITUDE_LIMIT_DEG, MERCATOR_LATITUDE_LIMIT_DEG))


def margin_for(max_relief_m: float, latitude_deg: float, *, exaggeration: float,
               ground_scale: float, map_units_per_pixel: float, altitude_deg: float) -> int:
    """Margin in pixels for a block holding `max_relief_m` of relief at `latitude_deg`.

    Every argument is explicit and keyword-only, so this stays a pure function of numbers. `plan`
    below derives them all from a `Body` and is what production calls.

    `altitude_deg` has no default: the sun altitude belongs to `tile.shade.KNOBS`, which a root
    module must not import, and a second copy of it here would be one more place to drift. Getting
    it wrong truncates shadows silently.
    """
    zfactor = exaggeration / (ground_scale * math.cos(math.radians(latitude_deg)))
    reach_px = cast_shadow.shadow_reach_px(max_relief_m, zfactor, map_units_per_pixel,
                                           altitude_deg)
    # `shadow_reach_px` returns the length along the sun's own bearing. A 315-degree sun lays that
    # diagonally, so the component reaching across either axis is shorter by cos(45).
    per_axis_px = reach_px * math.cos(math.radians(45.0))
    quantised = math.ceil(MARGIN_RATIO * per_axis_px / MARGIN_QUANTUM_PX) * MARGIN_QUANTUM_PX
    return min(quantised, MARGIN_CEILING_PX)


def haloed(relief: NDArray[np.float64]) -> NDArray[np.float64]:
    """Per-block relief widened to the greatest relief in its 3x3 neighbourhood.

    A block is sized for what can cast INTO it, not for what stands in it, so a flat block beside a
    mountain still needs the mountain's margin.

    The two axes are not symmetric. Columns wrap, because a Mercator planet is cyclic in longitude;
    rows edge-replicate, because the north pole does not shadow the south. `cast_shadow.shadow_mask`
    makes the same distinction for the same reason.
    """
    padded = np.pad(relief, ((1, 1), (0, 0)), mode="edge")
    padded = np.pad(padded, ((0, 0), (1, 1)), mode="wrap")
    out = relief.astype(np.float64, copy=True)
    rows, columns = relief.shape
    for row_offset in range(3):
        for column_offset in range(3):
            np.maximum(out,
                       padded[row_offset:row_offset + rows,
                              column_offset:column_offset + columns],
                       out=out)
    return out


def check_alignment(window: Window, body: Body) -> None:
    """Raise unless `window` is a legal plan target on this body's grid.

    The origin sits on a whole CELL so a plan indexes the relief cache directly; the extent is a
    whole number of blocks so no block is ever partly outside the thing being planned. Both are
    cheap to satisfy and expensive to discover later, when a half block has already been rendered.
    """
    col0, row0 = int(window.col_off), int(window.row_off)
    width, height = int(window.width), int(window.height)
    edge = grid_px(body)

    if col0 % CELL_PX or row0 % CELL_PX:
        raise ValueError(f"window origin ({col0}, {row0}) is not on a {CELL_PX} px cell boundary")
    if width % RENDER_BLOCK_PX or height % RENDER_BLOCK_PX:
        raise ValueError(f"window extent {width}x{height} is not a whole number of "
                         f"{RENDER_BLOCK_PX} px blocks")
    if width <= 0 or height <= 0:
        raise ValueError(f"window extent {width}x{height} is empty")
    if col0 < 0 or row0 < 0 or col0 + width > edge or row0 + height > edge:
        raise ValueError(f"window {col0},{row0} {width}x{height} leaves {body.name}'s "
                         f"{edge}x{edge} grid")


def whole_grid(body: Body) -> Window:
    """The window covering this body's entire grid, which is what a planet render plans over."""
    edge = grid_px(body)
    return Window(0, 0, edge, edge)  # pyright: ignore[reportCallIssue]


def _folded(cells: NDArray[np.float64]) -> NDArray[np.float64]:
    """A cell grid reshaped so a block's own cells sit on axes 1 and 3, ready to reduce."""
    rows, columns = cells.shape
    if rows % CELLS_PER_BLOCK or columns % CELLS_PER_BLOCK:
        raise ValueError(f"cell grid {rows}x{columns} is not a whole number of "
                         f"{CELLS_PER_BLOCK}x{CELLS_PER_BLOCK} blocks")
    return cells.reshape(rows // CELLS_PER_BLOCK, CELLS_PER_BLOCK,
                         columns // CELLS_PER_BLOCK, CELLS_PER_BLOCK)


def relief_from_cells(high: NDArray[np.float64],
                      low: NDArray[np.float64]) -> NDArray[np.float64]:
    """Fold a per-cell high/low pair up to the per-block vertical range `plan` consumes.

    The reduce is max-of-maxima and min-of-minima, never a mean: a block is sized for the tallest
    thing that can cast into it, and averaging four cells would hide a single steep one.

    AN ALL-NO-DATA BLOCK RAISES RATHER THAN SCORING ZERO, and that is the whole reason this is not
    a two-line `nan_to_num`. The prototype zeroed it, which reads as "flat here" and yields margin
    0, so a block whose elevations merely failed to arrive renders with its neighbours' shadows
    truncated at the seam and nothing to notice. `margin_for` would not catch it either: it takes
    the number it is handed. A body that genuinely has no-data blocks needs a decision recorded
    here, not a default chosen by whichever value numpy happens to produce.
    """
    if high.shape != low.shape:
        raise ValueError(f"high {high.shape} and low {low.shape} are different cell grids")
    # An all-NaN block is the case handled three lines below, so numpy's warning about it is not
    # news; left unsuppressed it prints once per empty block on the way to the exception.
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        relief = np.nanmax(_folded(high), axis=(1, 3)) - np.nanmin(_folded(low), axis=(1, 3))
    empty = np.nonzero(np.isnan(relief))
    if empty[0].size:
        first = (int(empty[0][0]), int(empty[1][0]))
        raise ValueError(f"{empty[0].size} block(s) hold no elevation data at all, the first at "
                         f"block row/column {first} — every cell in them is no-data, so their "
                         f"relief is unknown rather than zero")
    return relief


def share_from_cells(share: NDArray[np.float64]) -> NDArray[np.float64]:
    """Fold a per-cell fraction up to the per-block fraction `plan` takes as `ocean_share`.

    A mean of means is the whole-block fraction only because every cell covers the same pixel
    count, which `check_alignment` is what guarantees.
    """
    return _folded(share).mean(axis=(1, 3))


def plan(relief: NDArray[np.float64], window: Window, body: Body, *, altitude_deg: float,
         ocean_share: NDArray[np.float64] | None = None) -> list[Block]:
    """Every block covering `window`, each sized for the relief that can reach it.

    `relief` is the vertical RANGE within each block of `window`, highest minus lowest, in body
    metres, shaped (height // RENDER_BLOCK_PX, width // RENDER_BLOCK_PX). Not the greatest
    elevation, which is a different number and a smaller one wherever the sea floor is what a
    coast's shadow falls toward: the largest value in the rendered set is 13,940 m, off the Andes
    into the Peru-Chile trench, and no point on Earth stands 13,940 m above the datum. A producer
    that supplied elevations instead would under-margin exactly the coastal blocks whose occluders
    are tallest, and every test here would still pass, because they hand `margin_for` its number.

    `ocean_share`, if given, is the fraction
    of each block that is open sea on the same grid: a block that is entirely ocean is flat at the
    surface whatever the bathymetry beneath it does, so it needs no margin at all.

    The body supplies exaggeration, ground scale and pixel size together, so they cannot disagree
    with each other. `hillshade` requires `ground_scale` as an argument instead only because it is
    handed a path and cannot know its body.
    """
    check_alignment(window, body)
    rows = int(window.height) // RENDER_BLOCK_PX
    columns = int(window.width) // RENDER_BLOCK_PX
    if relief.shape != (rows, columns):
        raise ValueError(f"relief grid {relief.shape} does not match the {rows}x{columns} blocks "
                         f"of a {int(window.width)}x{int(window.height)} window")
    if ocean_share is not None and ocean_share.shape != relief.shape:
        raise ValueError(f"ocean_share {ocean_share.shape} does not match relief {relief.shape}")

    reach = haloed(relief)
    ground_scale = bodies.ground_metres_per_mercator_unit(body)
    col_origin, row_origin = int(window.col_off), int(window.row_off)

    blocks: list[Block] = []
    for row_index in range(rows):
        row0 = row_origin + row_index * RENDER_BLOCK_PX
        latitude = row_latitude_deg(row0 + RENDER_BLOCK_PX / 2.0, body)
        for column_index in range(columns):
            if ocean_share is not None and ocean_share[row_index, column_index] > 0.999:
                margin = 0
            else:
                margin = margin_for(float(reach[row_index, column_index]), latitude,
                                    exaggeration=body.exaggeration,
                                    ground_scale=ground_scale,
                                    map_units_per_pixel=body.map_units_per_pixel,
                                    altitude_deg=altitude_deg)
            blocks.append(Block(col0=col_origin + column_index * RENDER_BLOCK_PX, row0=row0,
                                size_px=RENDER_BLOCK_PX, margin_px=margin))
    return blocks
