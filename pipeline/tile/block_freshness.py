"""What one raytraced block's pixels depend on, as a value its marker can carry.

`block_render`'s marker answers "did this block finish"; this answers "is this block still correct",
which is a different question and the only one that can make a pass partial. A block's pixels are a
function of its plane window of each input raster, the recipe, and the code with its graphics stack.
The first two are here. Nothing in a file can see the third, which is why `block_render` renders a
sample of what it skipped.

The window is the PLANE and never the delivered block. Ground just outside a block casts shadows
into it, so a digest over the delivered window calls a block fresh whose light has moved, and
nothing about the frame says so.

Rasters are digested in cells rather than per block, because plane windows overlap: a cell is read
once where a per-block read would read the same ground once for every block whose ring reaches it.
A cell that a window only partly covers is still counted whole, so the cover can ask for a render
nobody needed and can never skip one that was owed.
"""

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

from pipeline import bodies, layers, planet_warp
from pipeline.block_plan import Block
from pipeline.raster_io import GTIFF_CREATE

#: The square of pixels one digest covers, taken from the rasters' own internal tiling so that a
#: cell read is one tile read rather than four partial ones. Read inside the functions below and
#: never as a default argument, which would bind at import and leave a test's override unseen.
CELL_PX = GTIFF_CREATE["blockxsize"]

#: The marker line this module owns, the rest of the marker being `block_render`'s.
DIGEST_KEY = "inputs"

#: Where the per-raster digests are cached, keyed on what would make them move.
INDEX_NAME = "index.json"


@dataclass(frozen=True)
class InputCells:
    """One input raster's digests, and whether each cell holds anything at all.

    `nonzero` is not a freshness term. It is how a sample is stratified by what a block holds, and
    it is here because the read that fills `digests` is the only full pass over the raster anyone
    makes.
    """

    name: str
    width: int
    height: int
    cell_px: int
    digests: np.ndarray
    nonzero: np.ndarray


def inputs_for(work: Path, body: bodies.Body, rasters: frozenset[str]) -> dict[str, Path]:
    """Every raster `prep_block.build` reads for a block of this body, present or not.

    Declared rather than discovered, and the two differ in the case that matters: a layer this body
    paints whose raster is missing has to be a digest that moved, not a raster nobody asked about.
    """
    paths = {planet_warp.HEIGHT_3857: work / planet_warp.HEIGHT_3857}
    if "oceanmask" in rasters:
        paths[planet_warp.OCEAN_3857] = work / planet_warp.OCEAN_3857
    if "watermask" in rasters:
        paths[planet_warp.WATER_3857] = work / planet_warp.WATER_3857
    for layer in layers.warped_for(layers.BLOCK_LAYERS):
        if layer.name in body.surface_layers:
            paths[layer.warped_in(work).name] = layer.warped_in(work)
    return paths


def cell_grid(width: int, height: int, cell_px: int) -> tuple[int, int]:
    """How many cells of `cell_px` cover a raster, as (rows, columns)."""
    return math.ceil(height / cell_px), math.ceil(width / cell_px)


def _row_cells(window: Window, height: int, cell_px: int) -> range:
    """The cell rows a window reads, clamped at both poles.

    Clamped and not wrapped: a plane may overhang the grid pole-side and `prep_block._read_cyclic`
    pads those rows by repeating the edge row, so the ground involved is the edge cell's.
    """
    first = min(max(int(window.row_off), 0), height - 1)
    last = min(max(int(window.row_off) + int(window.height) - 1, 0), height - 1)
    return range(first // cell_px, last // cell_px + 1)


def _column_cells(window: Window, width: int, cell_px: int) -> list[int]:
    """The cell columns a window reads, wrapping around the antimeridian.

    Wrapped and not clamped, the opposite of the rows above and for the reason `_read_cyclic` gives:
    a Mercator planet joins itself in longitude and does not join itself at the poles. A cover that
    clipped here would call the first and last block columns fresh for ground they do render.
    """
    count = cell_grid(width, width, cell_px)[1]
    span = int(window.width)
    if span >= width:
        return list(range(count))
    start = int(window.col_off) % width
    end = start + span
    if end <= width:
        return list(range(start // cell_px, (end - 1) // cell_px + 1))
    return sorted({*range(start // cell_px, count),
                   *range((end - width - 1) // cell_px + 1)})


def covered_cells(window: Window, width: int, height: int,
                  cell_px: int) -> tuple[tuple[int, int], ...]:
    """Every cell a window reads, in one fixed order so two runs digest it the same way."""
    columns = _column_cells(window, width, cell_px)
    return tuple((row, column)
                 for row in _row_cells(window, height, cell_px)
                 for column in columns)


def read_cells(path: Path) -> InputCells:
    """Digest a raster cell by cell, in one pass over it.

    Whole cells are read rather than each block's window, so the cost is the raster's size however
    many blocks overlap it. The caller decides whether this is owed at all; here it always runs.
    """
    cell_px = CELL_PX
    with rasterio.open(path) as dataset:  # pyright: ignore[reportCallIssue]
        width, height = dataset.width, dataset.height
        rows, columns = cell_grid(width, height, cell_px)
        digests = np.zeros((rows, columns), dtype=np.uint64)
        nonzero = np.zeros((rows, columns), dtype=bool)
        for row in range(rows):
            for column in range(columns):
                window = Window(column * cell_px, row * cell_px,  # pyright: ignore[reportCallIssue]
                                min(cell_px, width - column * cell_px),
                                min(cell_px, height - row * cell_px))
                cell = dataset.read(1, window=window)
                digests[row, column] = int.from_bytes(
                    hashlib.blake2b(cell.tobytes(), digest_size=8).digest(), "big")
                nonzero[row, column] = bool(cell.any())
    return InputCells(path.name, width, height, cell_px, digests, nonzero)


def refresh(cells_dir: Path, inputs: dict[str, Path]) -> dict[str, InputCells | None]:
    """Each input's cells, read again only where the file itself moved.

    This is what keeps the scheme affordable: an input whose mtime and size are unchanged is not
    opened, so a change to one small layer costs that layer's pass rather than the planet's. It is
    the one place an mtime is still trusted, and it is trusted about the FILE rather than about the
    pixels any block reads, which is the comparison that was wrong.
    """
    cell_px = CELL_PX
    cells_dir.mkdir(parents=True, exist_ok=True)
    index_path = cells_dir / INDEX_NAME
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    cells: dict[str, InputCells | None] = {}
    recorded: dict[str, dict[str, float | int]] = {}
    for name, path in sorted(inputs.items()):
        if not path.exists():
            cells[name] = None
            continue
        stat = path.stat()
        cached, record = cells_dir / f"{name}.npz", index.get(name)
        if (record is not None and cached.exists() and record["cell_px"] == cell_px
                and record["mtime"] == stat.st_mtime and record["size"] == stat.st_size):
            stored = np.load(cached)
            read = InputCells(name, int(record["width"]), int(record["height"]), cell_px,
                              stored["digests"], stored["nonzero"])
        else:
            read = read_cells(path)
            np.savez(cached, digests=read.digests, nonzero=read.nonzero)
        cells[name] = read
        recorded[name] = {"mtime": stat.st_mtime, "size": stat.st_size, "cell_px": cell_px,
                          "width": read.width, "height": read.height}
    index_path.write_text(json.dumps(recorded, indent=2, sort_keys=True) + "\n")
    return cells


def block_digest(block: Block, recipe_text: str, cells: dict[str, InputCells | None]) -> str:
    """One value covering everything about this block a file can see.

    The recipe goes in whole rather than per key. Narrowing a setting to the blocks it reaches is a
    separate act with its own evidence, and a digest that guessed at the reach would skip blocks on
    a guess.
    """
    hasher = hashlib.blake2b(digest_size=16)
    hasher.update(recipe_text.encode())
    hasher.update(f"context {block.context_px} plane {block.plane_edge_px} "
                  f"traced {block.traced_edge_px}".encode())
    for name in sorted(cells):
        # The name goes in whichever way this resolves, so a raster the body declares and the store
        # has lost digests differently from the same raster present. `refresh` is what keeps it in
        # the mapping at all; dropped there instead, a deleted layer would be invisible.
        hasher.update(name.encode())
        grid = cells[name]
        if grid is None:
            continue
        hasher.update(f"{grid.width}x{grid.height}/{grid.cell_px}".encode())
        for row, column in covered_cells(block.plane_window, grid.width, grid.height, grid.cell_px):
            hasher.update(int(grid.digests[row, column]).to_bytes(8, "big"))
    return hasher.hexdigest()


def holds(block: Block, cells: dict[str, InputCells | None]) -> tuple[str, ...]:
    """Which inputs reach any pixel of this block's plane window.

    What a sample is stratified by, and a coarse answer on purpose: a cell counts as reached when
    any pixel of it is non-zero, so a block beside ice reads as holding ice. For choosing which
    blocks to re-render that errs toward covering a class rather than missing one.
    """
    reached = []
    for name in sorted(cells):
        grid = cells[name]
        if grid is not None and any(
                grid.nonzero[row, column] for row, column in
                covered_cells(block.plane_window, grid.width, grid.height, grid.cell_px)):
            reached.append(name)
    return tuple(reached)


def marker_digest(path: Path) -> str | None:
    """The digest a marker vouches for, or None for a marker that carries none.

    None for a marker written before this module existed as well as for a missing one, and both
    have to re-render: a marker that cannot say what it was rendered from cannot be trusted to skip.
    """
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if line.startswith(f"{DIGEST_KEY} "):
            return line.split(" ", 1)[1].strip()
    return None
