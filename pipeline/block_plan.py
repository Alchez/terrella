"""How a body's Mercator grid is cut into raytraced render blocks, and how much terrain each block
must have around it so that nothing casting into it is missing.

A raytraced block is rendered as its own scene, so it can only be lit by geometry that is loaded
with it. Terrain just outside the block still throws shadows across the boundary, and a block whose
scene stops at its own footprint loses them silently: the shadow stops at the seam, on both sides,
with no edge to notice. Each block therefore carries terrain past its own edge, sized from the
tallest relief that can reach into it.

THREE WIDTHS, AND CONFLATING ANY PAIR OF THEM IS HOW THIS GOES WRONG. They used to be two, which is
why the outer ring was path-traced when its whole job is to exist:

    delivered   `RENDER_BLOCK_PX`. What reaches the mosaic.
    traced      delivered + 2 * `DENOISE_BAND_PX`. What Cycles path-traces, and the ONLY one that
                costs render time. The band is the denoiser's own context: OIDN sees the traced
                rectangle and nothing else, so its edge would otherwise be the delivered edge.
    plane       delivered + 2 * the context this module computes. The heightfield window cut and
                displaced. Off-camera, so it costs geometry and image memory and no render time.

The context is therefore free in the only currency a pass is measured in, which is what retired it
as a calibration problem: it is set to the shadow law's own undiscounted answer rather than to a
fraction of it. `CONTEXT_RATIO` holds why there is still a ratio at all.

The shadow law itself lives elsewhere. `cast_shadow.shadow_reach_px` owns how far exaggerated relief
throws a shadow, and `bodies` owns the exaggeration, the map-unit-to-ground ratio and the pixel size
it reads. What is added here is the per-axis `cos(45 deg)` component of a diagonal shadow, and the
ratio/quantum/ceiling policy.

`prep_block.row_scale` owns the per-row term. It scales the HEIGHT, which is what makes the applied
exaggeration uniform and puts shadow reach on the OCCLUDER's latitude rather than on the block's.

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
RENDER_BLOCK_PX = 4096

#: Cache cells along one block's delivered edge. Derived, never written down: the cache is finer
#: than the block ON PURPOSE, so that re-tuning the block edge re-folds an existing cache instead
#: of re-reading a 46 GB master, and a restated 8 would silently decouple the two.
CELLS_PER_BLOCK = RENDER_BLOCK_PX // CELL_PX

#: How far past the delivered block Cycles path-traces, and the only ring that costs render time.
#:
#: IT IS THE DENOISER'S CONTEXT AND NOTHING ELSE'S. Border-cropping with no band at all gives a
#: 1.89 DN join against full-trace's 0.92, because OIDN is handed the traced rectangle and its own
#: edge then falls exactly on the delivered edge. 128 px closes it: measured on `r07c26|r07c27`,
#: the pair every margin finding here was taken on, 0.93 DN against full-trace's 0.92 — the best of
#: any arm, in less time than the arrangement that produced the defect.
#:
#: Also what keeps the Cycles frame's own dark outermost pixels out of the mosaic, which used to be
#: `MARGIN_MINIMUM_PX`'s job and needed a floor because a margin could be zero. This cannot be:
#: every block gets the same band, so no block delivers its own frame edge.
DENOISE_BAND_PX = 128

#: Fraction of the longest possible shadow the context carries, and it is 1.0 because the context
#: stopped being paid for in pixels.
#:
#: IT WAS 0.39 WHILE THE CONTEXT WAS PATH-TRACED, on the reasoning that the tallest relief in a
#: block is not adjacent to every edge of it, so sizing for the worst case buys a shadow that cannot
#: occur. That trade was real when the ring cost render time and is worth nothing now: the plane is
#: off-camera, so widening it costs geometry and image memory alone. Measured at 79.7N, the
#: contamination reached ~256 px against an undiscounted derivation of 258 and a discounted 100 —
#: the discount was the entire error, and a discount that is not buying anything is just the error.
#:
#: KEPT AS A CONSTANT RATHER THAN DELETED because it is the knob a body with a different trade would
#: turn, and because a law with its ratio written into the arithmetic cannot be swept.
CONTEXT_RATIO = 1.0

#: Contexts round up to this, so that neighbouring blocks share plane sizes and the renderer's
#: allocations repeat instead of being unique per block.
#:
#: RAISING IT IS A REJECTED IDEA RATHER THAN AN OPEN ONE, and it has been rejected twice on two
#: different pairs. Neighbours whose rims disagree get different plane spans, and the standing
#: hypothesis was that this makes their shared edge a seam worth spending plane on. Measured on the
#: worst-disagreeing adjacent pair on Earth, the join sits INSIDE the distribution of the same
#: terrain's own adjacent-column steps: it is not a line, and matching the rims recovers a small
#: fraction of one DN. An earlier arm that forced every context equal had already found the same
#: thing, slightly worse rather than better.
#:
#: THE ASYMMETRY IS WHAT MAKES IT REJECTED RATHER THAN MERELY UNPROVEN. A coarser quantum can only
#: round contexts UP, so it always widens planes; the plane is off-camera and costs no render time,
#: but `render_block` runs `prep_block.cut` inside its own per-block clock and the cut scales
#: superlinearly with plane area. So every coarser value is a pass-time cost buying an invisible
#: improvement, and there is no value of this constant that is free. Reopening needs a join that
#: someone can see, not a smaller number.
CONTEXT_QUANTUM_PX = 64

#: The largest context any block may ask for, and on Earth it is headroom rather than a clamp.
#:
#: MEASURED ON THE REAL RELIEF CACHE rather than derived, because a clamped block keeps its defect
#: while looking fixed. Under the poleward rule at this block edge, Earth's widest ask is EXACTLY
#: 2,048 px, on the three blocks of row 0 at 84.5N holding 5,076 m of haloed relief; the next
#: widest is 1,984. So nothing clamps and there is no headroom left either — the two numbers meet.
#: The cost is borne only by the blocks that use it, since the plane is sized per block.
#:
#: RE-MEASURE THIS WHEN THE SIZING LATITUDE MOVES, NOT WHEN THE NUMBER LOOKS WRONG. The previous
#: figures here (widest ask 1,856 px, "1,792 clamps 3 and 1,024 clamps 74") were true of the
#: mid-latitude rule and went false the moment the occluder's own latitude became the subject; they
#: could not have gone false any other way, and no test noticed.
CONTEXT_CEILING_PX = 2048

#: The largest square frame renderable on this GPU. It bounds the TRACED size and not the plane:
#: the plane is off-camera geometry, where this is a limit on what Cycles allocates a frame buffer
#: for. Different from `CONTEXT_CEILING_PX`, which bounds the plane alone.
#:
#: THE TRACED EDGE NO LONGER VARIES PER BLOCK, so this checks the constants above rather than any
#: block's relief: `RENDER_BLOCK_PX + 2 * DENOISE_BAND_PX` is 4,352 for every block on every body,
#: and what it refuses is a block edge raised past what this GPU is proven at.
TRACED_CEILING_PX = 8192

#: Web Mercator's own cut-off, applied by `row_latitude_deg` below. Past it `1 / cos(lat)` runs
#: away, so a polar block would otherwise be sized from a latitude no stage shades at.
MERCATOR_LATITUDE_LIMIT_DEG = 85.05


@dataclass(frozen=True)
class Block:
    """One render block: where it sits on the grid, and how much terrain it must carry around it.

    THE THREE WIDTHS ARE PROPERTIES AND NONE OF THEM IS SPELLED `rendered`, which is the word this
    class used to carry. It meant the frame, and after the context stopped being traced there is no
    longer one thing that word picks out: the frame and the cut window are different sizes and
    swapping them writes a correctly-sized block of the wrong ground.
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

        May extend past the grid on any side. Columns beyond the edge wrap (the planet is cyclic in
        longitude) and rows beyond it clamp, exactly as `cast_shadow.shadow_mask` treats its own
        march - resolving that is the reader's job, not this module's.
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

    The sphere is the PROJECTION's and never the body's: every grid here is EPSG:3857 whatever
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
    `block_render` on the tile side and the rig's `SUN_ROTATION`, and a second copy of it here
    would be one more place to drift. Getting it wrong truncates shadows silently.

    SIZING BELOW THAT ALTITUDE IS A REJECTED IDEA RATHER THAN AN OPEN ONE. The sun is a disc
    `palette.SUN_ANGULAR_DIAMETER_DEG` wide, so the last ray a ridge can block leaves its lower
    limb and runs 1.2349x further than this altitude lays a shadow; a census says 315 of Earth's
    1,024 blocks have no slack absorbing that. It was implemented, rendered and refuted. A positive
    control widening one block's ring 832 to 2048 px — 2.46x, past the ceiling the limb would ask
    for — moves that block NO MORE than the limb's 1.15x does, over added terrain holding more
    relief than the ring already carries, and the join oracle puts both arms deep inside the
    distribution of the same terrain's own interior column steps. The mechanism is why the census
    was the wrong instrument: this law sizes from a block's relief RANGE, peak to trench, but only
    a single occluder's REACH can put a shadow anywhere, and no occluder embodies that range.

    `latitude_deg` IS THE OCCLUDER'S AND NOT THE BLOCK'S, which is `poleward_sizing_latitude`'s
    subject; this function only turns a latitude into a length.

    THE FLOOR IS `DENOISE_BAND_PX` AND IT IS A STRUCTURAL BOUND, NOT A LOOK ONE. The plane must
    cover the traced rectangle: a block whose law asks for less than the band would path-trace a
    ring of frame that has no heightfield under it at all, which renders as sky rather than as
    terrain. It replaces a floor that existed for a different reason — a zero-margin block used to
    deliver the Cycles frame's own dark border — and that reason is now covered unconditionally by
    the band itself. Inert on Earth, whose narrowest ask is exactly 128 px.
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

    THE LAW LIVES ON THE OCCLUDER, WHICH IS WHY THIS IS NOT THE BLOCK'S OWN MID-LATITUDE. Once
    `prep_block.row_scale` makes the applied exaggeration uniform, the pixels a shadow crosses no
    longer share one scale: a shadow cast from row r reaches `exaggeration * relief / (ground_scale
    * cos(lat_r) * tan(alt) * pixel)`, so it is the OCCLUDER's cosine that sets the length. Sizing
    at the block's centre row is right only while every row is displaced by the centre's number,
    which was true exactly because of the defect being removed.

    IT TAKES THE POLEWARD EDGE IN BOTH HEMISPHERES, AND "NORTH IN BOTH" IS A REJECTED IDEA RATHER
    THAN AN OPEN ONE. A 315-degree sun does put every occluder north-WEST, and that is true of the
    column component and silent about the binding latitude: the occluder set is the north ring plus
    the WEST ring, and the west ring spans the block's own rows. So in the north the north edge is
    the most poleward point of that set and in the south it is the least, and a north-edge rule
    narrows the margin on every southern block instead of widening it. Censused when it was
    proposed: it shrank 306 of Earth's 1,024 blocks, everything from 11S to the pole, and failed to
    settle on 7. Under-context is silent on both sides, by this module's own admission above.

    CONVERGENCE IS A PROPERTY OF THIS CHOICE AND NOT AN ACCIDENT. More context moves the sizing row
    further from the equator, which asks for more context again, so the iteration in `plan` is
    monotone increasing and bounded by `CONTEXT_CEILING_PX`. The north-edge rule is monotone in
    opposite directions in the two hemispheres, which is why it could 2-cycle at all.
    """
    north = row_latitude_deg(row0 - context_px, body)
    south = row_latitude_deg(row0 + RENDER_BLOCK_PX + context_px, body)
    return north if abs(north) >= abs(south) else south


def settled_context(max_relief_m: float, row0: int, body: Body, *,
                    ground_scale: float, altitude_deg: float) -> int:
    """`context_for` iterated to its fixed point, since the sizing latitude depends on the answer.

    THE ITERATION IS HERE AND NOT IN `context_for`, which is documented as a pure function of
    numbers and would have to grow `row0` and the block size to do this. Keeping the recursion out
    of it also keeps its tests able to ask "what length does this latitude imply" without also
    asking "which latitude does this block settle at" — two questions that fail for different
    reasons.

    PER COLUMN AND NOT PER ROW: the fixed point starts from the block's own relief, so two blocks
    in one row settle at different contexts and therefore at different sizing latitudes.

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

    A block is sized for what can cast INTO it, not for what stands in it, so a flat block beside a
    mountain still needs the mountain's context.

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
    a two-line `nan_to_num`. The prototype zeroed it, which reads as "flat here" and yields the
    narrowest context there is, so a block whose elevations merely failed to arrive renders with its
    neighbours' shadows truncated at the seam and nothing to notice. `context_for` would not catch
    it either: it takes the number it is handed. A body that genuinely has no-data blocks needs a decision recorded
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


def plan(relief: NDArray[np.float64], window: Window, body: Body, *,
         altitude_deg: float) -> list[Block]:
    """Every block covering `window`, each given the context the relief that can reach it needs.

    `relief` is the vertical RANGE within each block of `window`, highest minus lowest, in body
    metres, shaped (height // RENDER_BLOCK_PX, width // RENDER_BLOCK_PX). Not the greatest
    elevation, which is a different number and a smaller one wherever the sea floor is what a
    coast's shadow falls toward: the largest value in the rendered set is 13,940 m, off the Andes
    into the Peru-Chile trench, and no point on Earth stands 13,940 m above the datum. A producer
    that supplied elevations instead would under-context exactly the coastal blocks whose occluders
    are tallest, and every test here would still pass, because they hand `context_for` its number.

    EVERY BLOCK GOES THROUGH THE LAW, INCLUDING THE ALL-OCEAN ONES. There used to be an
    `ocean_share` shortcut here that gave a block which is >99.9% sea its margin for free, on the
    reasoning that a flat sea surface cannot receive a shadow. The reasoning was about shadows and
    the margin turned out not to be only about shadows: it is also what keeps the rendered frame's
    own dark border out of the delivered pixels, and that border reaches as far into the block as
    the surrounding relief is tall. So an all-ocean block beside a mountain range needed the
    mountain's margin all along. Measured at the Norwegian coast, where the shortcut gave 64 px and
    the law gives 320: the boundary step went from 43 DN to 1.2, against 1.2 in the composite.

    The shortcut would be a saving worth even less now than it was then, since what it would save is
    geometry rather than traced pixels; it stays deleted on the correctness argument above.

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
