"""How a body's Mercator grid is cut into raytraced render blocks, and how much terrain each block
must have around it so that nothing casting into it is missing.

A raytraced block is rendered as its own scene, so it can only be lit by geometry that is loaded
with it. Terrain just outside the block still throws shadows across the boundary, and a block whose
scene stops at its own footprint loses them silently: the shadow stops at the seam, on both sides,
with no edge to notice. Each block therefore carries terrain past its own edge, sized from the
tallest relief that can reach into it.

Three widths, and conflating any pair of them is how this goes wrong:

    delivered   `RENDER_BLOCK_PX`. What reaches the mosaic.
    traced      delivered + 2 * `DENOISE_BAND_PX`. What Cycles path-traces, and the only one that
                costs render time. The band is the denoiser's own context: it sees the traced
                rectangle and nothing else, so its edge would otherwise be the delivered edge.
    plane       delivered + 2 * the context this module computes. The heightfield window cut and
                displaced. Off-camera, so it costs geometry and image memory and no render time.

The context is therefore free in the only currency a pass is measured in, so it is set to the shadow
law's own undiscounted answer rather than to a fraction of it. `CONTEXT_RATIO` holds why there is
still a ratio at all.

The shadow law itself lives elsewhere. `cast_shadow.shadow_reach_px` owns how far exaggerated relief
throws a shadow, and `bodies` owns the exaggeration, the map-unit-to-ground ratio and the pixel size
it reads. What is added here is the per-axis `cos(45 deg)` component of a diagonal shadow, and the
ratio/quantum/ceiling policy. `prep_block.row_scale` owns the per-row term: it scales the height,
which is what puts shadow reach on the occluder's latitude rather than on the block's.

Pure by construction: a relief grid as an array, a window as numbers, no raster and no open file.
It sits at the root of `pipeline/` rather than in `tile/` because it is a law the block runner and
the cost model both read, in the sense the package note sets out, not a stage that runs.
"""

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

#: The delivered edge of one render block. Not named `BLOCK`: `fuse_heightfield` and `render_prep`
#: each already define `BLOCK = 8192` meaning a streaming window, which is a different concept that
#: happens to be measured in the same units.
RENDER_BLOCK_PX = 4096

#: Cache cells along one block's delivered edge. Derived, never written down: the cache is finer
#: than the block on purpose, so that re-tuning the block edge re-folds an existing cache instead
#: of re-reading the master, and a restated 8 would silently decouple the two.
CELLS_PER_BLOCK = RENDER_BLOCK_PX // CELL_PX

#: How far past the delivered block Cycles path-traces, and the only ring that costs render time.
#:
#: It is the denoiser's context and nothing else's: the denoiser is handed the traced rectangle, so
#: without a band its own edge falls exactly on the delivered edge and roughly doubles the join.
#: It also keeps the Cycles frame's own dark outermost pixels out of the mosaic, unconditionally,
#: since every block gets the same band and so no block delivers its own frame edge.
DENOISE_BAND_PX = 128

#: Fraction of the longest possible shadow the context carries, and it is 1.0 because the context
#: is not paid for in pixels: the plane is off-camera, so widening it costs geometry and image
#: memory alone, and a discount that buys nothing is just an error in the sizing.
#:
#: Kept as a constant rather than folded into the arithmetic, because it is the knob a body with a
#: different trade would turn and a law with its ratio inlined cannot be swept.
CONTEXT_RATIO = 1.0

#: Contexts round up to this, so that neighbouring blocks share plane sizes and the renderer's
#: allocations repeat instead of being unique per block.
#:
#: Raising it is a rejected idea rather than an open one, twice over and on two different pairs, and
#: the rule beside this file owns both the measurement and the asymmetry that closes it. Reopening
#: needs a join that someone can see, not a smaller number.
CONTEXT_QUANTUM_PX = 64

#: The largest context any block may ask for, and on Earth it is headroom rather than a clamp.
#:
#: Measured on the real relief cache rather than derived, because a clamped block keeps its defect
#: while looking fixed. Under the poleward rule at this block edge, Earth's widest ask is exactly
#: this, on the three blocks of row 0, so nothing clamps and no headroom is left either. The cost is
#: borne only by the blocks that use it, the plane being sized per block.
#:
#: Re-measure when the sizing latitude moves, not when the number looks wrong: the figures here went
#: false the moment the occluder's own latitude became the subject, they could not have gone false
#: any other way, and no test noticed.
CONTEXT_CEILING_PX = 2048

#: The largest square frame renderable on this GPU. It bounds the traced size and not the plane,
#: which is off-camera geometry, where this is a limit on what Cycles allocates a frame buffer for.
#: Different from `CONTEXT_CEILING_PX`, which bounds the plane alone. The traced edge is the same
#: for every block on every body, so what this refuses is a block edge raised past what this GPU is
#: proven at.
TRACED_CEILING_PX = 8192

#: Web Mercator's own cut-off, applied by `row_latitude_deg` below. Past it `1 / cos(lat)` runs
#: away, so a polar block would otherwise be sized from a latitude no stage shades at.
MERCATOR_LATITUDE_LIMIT_DEG = 85.05


@dataclass(frozen=True)
class Block:
    """One render block: where it sits on the grid, and how much terrain it must carry around it.

    The three widths are properties, and none of them is spelled `rendered`: there is no one thing
    that word picks out, the frame and the cut window being different sizes, and swapping them
    writes a correctly-sized block of the wrong ground.
    """

    col0: int
    row0: int
    size_px: int
    context_px: int

    @property
    def traced_edge_px(self) -> int:
        """The square frame Cycles path-traces, which is the delivered block plus the band."""
        return self.size_px + 2 * DENOISE_BAND_PX

    @property
    def plane_edge_px(self) -> int:
        """The square heightfield window cut and displaced, most of it outside the camera."""
        return self.size_px + 2 * self.context_px

    @property
    def delivered_window(self) -> Window:
        """The pixels this block is responsible for, which is what gets cropped back out."""
        return Window(self.col0, self.row0, self.size_px, self.size_px)  # pyright: ignore[reportCallIssue]

    @property
    def plane_window(self) -> Window:
        """The pixels that must be read to render it.

        May extend past the grid on any side: columns beyond the edge wrap, the planet being cyclic
        in longitude, and rows beyond it clamp. Resolving that is the reader's job, not this
        module's.
        """
        return Window(self.col0 - self.context_px, self.row0 - self.context_px,  # pyright: ignore[reportCallIssue]
                      self.plane_edge_px, self.plane_edge_px)

    @property
    def fits(self) -> bool:
        """Whether this block can be rendered at all on the proven frame envelope."""
        return self.traced_edge_px <= TRACED_CEILING_PX


def grid_px(body: Body) -> int:
    """The edge of this body's full Mercator grid in pixels, at its own maximum tile zoom."""
    return CELL_PX << body.tile_max_zoom


def row_latitude_deg(row: float, body: Body) -> float:
    """Latitude of a pixel row centre on this body's grid, clipped to Mercator's limit.

    The sphere is the projection's and never the body's: every grid here is EPSG:3857 whatever
    planet supplied the elevations, so reading the radius off the body registry would put Mars's
    rows tens of degrees out.
    """
    northing = mercator.MERCATOR_HALF_M - (row + 0.5) * body.map_units_per_pixel
    latitude = float(mercator.latitude_at(northing, mercator.WEB_MERCATOR_RADIUS_M))
    return float(np.clip(latitude, -MERCATOR_LATITUDE_LIMIT_DEG, MERCATOR_LATITUDE_LIMIT_DEG))


def context_for(max_relief_m: float, latitude_deg: float, *, exaggeration: float,
                ground_scale: float, map_units_per_pixel: float, altitude_deg: float) -> int:
    """Context in pixels for a block holding `max_relief_m` of relief at `latitude_deg`.

    Every argument is explicit and keyword-only, so this stays a pure function of numbers. `plan`
    below derives them all from a `Body` and is what production calls.

    `altitude_deg` has no default: the sun altitude is `palette.SUN_ALT_DEG`, read by both
    `block_render` on the tile side and the rig's `sun_rotation`, and a second copy of it here would
    be one more place to drift. Getting it wrong truncates shadows silently.

    Sizing below that altitude for the sun's lower limb is a rejected idea rather than an open one.
    It was implemented, rendered and refuted: widening one block's ring further than the limb would
    ever ask moves that block no more than the limb does, and the join oracle puts both arms deep
    inside the distribution of the same terrain's own interior column steps. The mechanism is why a
    census of blocks with no slack was the wrong instrument: this law sizes from a block's relief
    range, peak to trench, where only a single occluder's reach can put a shadow anywhere, and no
    occluder embodies that range.

    `latitude_deg` is the occluder's and not the block's, which is `poleward_sizing_latitude`'s
    subject; this function only turns a latitude into a length.

    The floor is `DENOISE_BAND_PX` and it is a structural bound rather than a look one: the plane
    must cover the traced rectangle, and a block whose law asks for less than the band would
    path-trace a ring of frame with no heightfield under it at all, which renders as sky rather than
    as terrain. Inert on Earth, whose narrowest ask is exactly the band.
    """
    zfactor = exaggeration / (ground_scale * math.cos(math.radians(latitude_deg)))
    reach_px = cast_shadow.shadow_reach_px(max_relief_m, zfactor, map_units_per_pixel,
                                           altitude_deg)
    # `shadow_reach_px` returns the length along the sun's own bearing. A 315-degree sun lays that
    # diagonally, so the component reaching across either axis is shorter by cos(45).
    per_axis_px = reach_px * math.cos(math.radians(45.0))
    quantised = math.ceil(CONTEXT_RATIO * per_axis_px / CONTEXT_QUANTUM_PX) * CONTEXT_QUANTUM_PX
    return min(max(quantised, DENOISE_BAND_PX), CONTEXT_CEILING_PX)


def poleward_sizing_latitude(row0: int, context_px: int, body: Body) -> float:
    """The latitude a block's context must be sized at: whichever plane edge is further from 0.

    The law lives on the occluder, which is why this is not the block's own mid-latitude: a shadow
    cast from row r reaches `exaggeration * relief / (ground_scale * cos(lat_r) * tan(alt) * pixel)`,
    so it is the occluder's cosine that sets the length, and sizing at the block's centre row is
    right only while every row is displaced by the centre's number.

    It takes the poleward edge in both hemispheres, and "north in both" is a rejected idea rather
    than an open one: a 315-degree sun does put every occluder north-west, which is true of the
    column component and silent about the binding latitude, the occluder set being the north ring
    plus the west ring and the west ring spanning the block's own rows. The rule beside this file
    owns the census that closed it.

    Convergence is a property of that choice and not an accident: more context moves the sizing row
    further from the equator, which asks for more context again, so the iteration in `plan` is
    monotone increasing and bounded by `CONTEXT_CEILING_PX`. A north-edge rule is monotone in
    opposite directions in the two hemispheres, which is why it could 2-cycle at all.
    """
    north = row_latitude_deg(row0 - context_px, body)
    south = row_latitude_deg(row0 + RENDER_BLOCK_PX + context_px, body)
    return north if abs(north) >= abs(south) else south


def settled_context(max_relief_m: float, row0: int, body: Body, *,
                    ground_scale: float, altitude_deg: float) -> int:
    """`context_for` iterated to its fixed point, since the sizing latitude depends on the answer.

    The iteration is here and not in `context_for`, which is a pure function of numbers and would
    have to grow `row0` and the block size to do this. Keeping the recursion out of it also lets its
    tests ask "what length does this latitude imply" without also asking "which latitude does this
    block settle at", two questions that fail for different reasons.

    Per column and not per row: the fixed point starts from the block's own relief, so two blocks in
    one row settle at different contexts and therefore at different sizing latitudes.

    Terminates because `poleward_sizing_latitude` makes the map monotone increasing and
    `CONTEXT_CEILING_PX` bounds it; the loop is over quantised values, so it reaches equality rather
    than approaching it. The bound is `grid_px` quanta, which no real block comes close to, and it
    raises rather than returning a wrong number if the monotonicity argument above ever stops
    holding.
    """
    context = context_for(max_relief_m, row_latitude_deg(row0 + RENDER_BLOCK_PX / 2.0, body),
                          exaggeration=body.exaggeration, ground_scale=ground_scale,
                          map_units_per_pixel=body.map_units_per_pixel, altitude_deg=altitude_deg)
    for _ in range(CONTEXT_CEILING_PX // CONTEXT_QUANTUM_PX + 1):
        nxt = context_for(max_relief_m, poleward_sizing_latitude(row0, context, body),
                          exaggeration=body.exaggeration, ground_scale=ground_scale,
                          map_units_per_pixel=body.map_units_per_pixel, altitude_deg=altitude_deg)
        if nxt == context:
            return context
        context = nxt
    raise RuntimeError(f"context for the block at row {row0} did not settle; the poleward rule is "
                       f"supposed to be monotone increasing and this says it is not")


def haloed(relief: NDArray[np.float64]) -> NDArray[np.float64]:
    """Per-block relief widened to the greatest relief in its 3x3 neighbourhood.

    A block is sized for what can cast into it, not for what stands in it, so a flat block beside a
    mountain still needs the mountain's context.

    The two axes are not symmetric. Columns wrap, because a Mercator planet is cyclic in longitude;
    rows edge-replicate, because the north pole does not shadow the south.
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

    The origin sits on a whole cell so a plan indexes the relief cache directly; the extent is a
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

    An all-no-data block raises rather than scoring zero, which is the whole reason this is not a
    two-line `nan_to_num`: zero reads as "flat here" and yields the narrowest context there is, so a
    block whose elevations merely failed to arrive renders with its neighbours' shadows truncated at
    the seam and nothing to notice. `context_for` would not catch it either, taking the number it is
    handed. A body that genuinely has no-data blocks needs a decision recorded here, not a default
    chosen by whichever value numpy happens to produce.
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


def plan(relief: NDArray[np.float64], window: Window, body: Body, *,
         altitude_deg: float) -> list[Block]:
    """Every block covering `window`, each given the context the relief that can reach it needs.

    `relief` is the vertical range within each block of `window`, highest minus lowest, in body
    metres, shaped (height // RENDER_BLOCK_PX, width // RENDER_BLOCK_PX). Not the greatest
    elevation, which is a different number and a smaller one wherever the sea floor is what a
    coast's shadow falls toward: the largest value in the rendered set is 13,940 m, off the Andes
    into the Peru-Chile trench, and no point on Earth stands 13,940 m above the datum. A producer
    that supplied elevations instead would under-context exactly the coastal blocks whose occluders
    are tallest, and every test here would still pass, because they hand `context_for` its number.

    Every block goes through the law, including the all-ocean ones, and a shortcut giving a block
    that is almost entirely sea its margin for free is a rejected idea rather than an open one. The
    reasoning for it is about shadows, and the margin is not only about shadows: it is also what
    keeps the rendered frame's own dark border out of the delivered pixels, and that border reaches
    as far into the block as the surrounding relief is tall, so an all-ocean block beside a mountain
    range needs the mountain's margin. What such a shortcut would save now is geometry rather than
    traced pixels, which is less than it ever was.

    The body supplies exaggeration, ground scale and pixel size together, so they cannot disagree
    with each other.
    """
    check_alignment(window, body)
    rows = int(window.height) // RENDER_BLOCK_PX
    columns = int(window.width) // RENDER_BLOCK_PX
    if relief.shape != (rows, columns):
        raise ValueError(f"relief grid {relief.shape} does not match the {rows}x{columns} blocks "
                         f"of a {int(window.width)}x{int(window.height)} window")
    reach = haloed(relief)
    ground_scale = bodies.ground_metres_per_mercator_unit(body)
    col_origin, row_origin = int(window.col_off), int(window.row_off)

    blocks: list[Block] = []
    for row_index in range(rows):
        row0 = row_origin + row_index * RENDER_BLOCK_PX
        for column_index in range(columns):
            relief_m = float(reach[row_index, column_index])
            context = settled_context(relief_m, row0, body,
                                      ground_scale=ground_scale, altitude_deg=altitude_deg)
            blocks.append(Block(col0=col_origin + column_index * RENDER_BLOCK_PX, row0=row0,
                                size_px=RENDER_BLOCK_PX, context_px=context))
    return blocks
