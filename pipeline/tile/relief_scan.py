"""Per-cell relief for a body's Mercator grid, so the block partition never re-reads the master.

`block_plan` sizes every render block's margin from the vertical range standing in and around it,
and the only place that number lives is the heightfield: 46 GB on Earth. Reading it once per
planning run would dominate a stage that is otherwise arithmetic, so one streaming pass records
max, min and ocean share per cell, and every later question is asked of the cache.

THE CACHE IS DELIBERATELY FINER THAN THE BLOCK. `block_plan.CELL_PX` is the tile grid's own
quantum and a render block is `CELLS_PER_BLOCK` of them across, so re-tuning the block edge, or
trying the parked quadtree, re-folds this cache instead of re-reading the master. That is the
whole reason the fold lives in `block_plan` rather than here: this module owns what a cell holds,
and the module that owns what a block is owns how cells become one.

NO PLAUSIBILITY CLAMP IS APPLIED, and the prototype's `-12000 < h < 9500` is deliberately not
ported. It was written against Earth, where it never fires. Mars reaches 21,202 m, so the same
line would silently turn its tallest cells into no-data and hand those blocks a margin of zero,
which truncates exactly the shadows the margin exists to carry. A corrupt master instead
over-margins, which costs render pixels and loses nothing.

WHAT IS MASKED IS THE RASTER'S OWN DECLARED NODATA, ALONGSIDE NAN. A declared sentinel is not
missing to anything that does not ask: `height_3857.tif` declares -32768.0, and a consumer
guarding only NaN once packed that as a real elevation and drew a line from pole to pole on the
live site. See HISTORY, *the column the warp could not fill*.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.transform import from_bounds

from pipeline import block_plan, bodies, freshness, mercator, planet_seam, raster_io

#: Rows read per pass. Must be a whole number of cells, because the reduce reshapes the strip by
#: cell; one cell's worth is 268 MB of float32 on Earth, which is what sizes this rather than speed.
BAND_ROWS = block_plan.CELL_PX

#: The tile stage's directory name, and this module is its one owner.
#:
#: It is declared in the relief cache rather than somewhere neutral because this is the module that
#: names the stage's own contents; the alternative was a module existing only to hold a string.
#: `tests/test_paths.py` refuses a second spelling, so a stage that moves moves here.
STAGE = "planet_tiles"


def work_dir(body: bodies.Body) -> Path:
    """Where this body's planet-tier intermediates live, the same directory as its master.

    THE ONE ANSWER TO "WHERE DOES THIS BODY'S TILE STAGE LIVE", and its readers are the whole tier
    rather than this cache: the block prep's CLI default, the pack, the terrain cut, the planet
    pass and the block runner. Five of them spelled the stage themselves, which is how the runner
    came to validate one directory and cut its pixels from another.
    """
    return bodies.work_dir(body, STAGE)


def master_path(work: Path) -> Path:
    """The heightfield this cache summarises."""
    return work / "height_3857.tif"


def ocean_master_path(work: Path) -> Path:
    """The ocean mask, for bodies whose seam declares one.

    The basename is spelled at two more sites in `shade_planet` and has no owner; when unit 6
    moves the warp set to the planet tier, that owner is what the three should import.
    """
    return work / "ocean_3857.tif"


def relief_path(work: Path) -> Path:
    """Where the per-cell high/low pair is recorded, beside the master it describes."""
    return work / "relief_cells.tif"


def ocean_path(work: Path) -> Path:
    """Where the per-cell ocean fraction is recorded. Absent for a body that declares no mask."""
    return work / "ocean_cells.tif"


def params_path(work: Path) -> Path:
    """Where the scan's recipe is recorded, beside the cache it describes."""
    return work / "relief_params.json"


def params(body: bodies.Body, rasters: frozenset[str]) -> str:
    """The recipe: everything that can move a number in this cache, and nothing else.

    The body itself is NOT in here. It is in the path, which is `bodies.work_dir`'s rule, so a
    recipe carrying it would restage every body the moment the spelling changed.

    `rasters_off` follows the conditional-record idiom: Earth omits nothing, so its list is empty
    and never enters, while a body that stops declaring an ocean mask restages this cache rather
    than keeping a share grid nothing produces any more.
    """
    recipe: dict[str, Any] = {
        "cell_px": block_plan.CELL_PX,
        "grid_px": block_plan.grid_px(body),
    }
    off = planet_seam.rasters_off(rasters)
    if off:
        recipe["rasters_off"] = off
    return json.dumps(recipe, sort_keys=True, indent=2)


def _write_cells(out: Path, bands: NDArray[np.float64]) -> None:
    """Write one cell-grid raster and stamp it, via `.part` so a file at its final path is whole.

    There is no finer resume than this and that is the repo's settled position, not an omission:
    `terrain_rgb` deletes a partial rather than resuming over it, and `shade_planet` removed its
    `--resume` because existence cannot tell a complete tile from a truncated one. A whole-planet
    scan is minutes, so a crash costs minutes.
    """
    count, cells = bands.shape[0], bands.shape[1]
    half = mercator.MERCATOR_HALF_M
    profile: dict[str, Any] = dict(
        driver="GTiff", width=cells, height=cells, count=count, dtype="float32",
        crs="EPSG:3857", nodata=float("nan"),
        transform=from_bounds(-half, -half, half, half, cells, cells),
        **raster_io.GTIFF_CREATE)
    part = out.with_suffix(".part")
    with rasterio.open(part, "w", **profile) as writer:  # pyright: ignore[reportCallIssue]
        writer.write(bands.astype(np.float32))
    part.replace(out)
    freshness.mark_done(out)


def _accumulate(master: Path, ocean: Path | None, high: NDArray[np.float64],
                low: NDArray[np.float64], share: NDArray[np.float64] | None,
                band_rows: int) -> None:
    """Fill the cell grids from one streaming pass over the master.

    Reading in strips rather than whole is not an optimisation on a 46 GB raster, it is the only
    way it fits; `band_rows` exists so a test can prove the strip walk and the whole-raster answer
    agree, since production only ever runs one of the two.
    """
    cell_px = block_plan.CELL_PX
    if band_rows % cell_px or band_rows <= 0:
        raise ValueError(f"band_rows {band_rows} is not a positive multiple of {cell_px}, so a "
                         "strip cannot be reshaped by cell")
    cells = high.shape[0]
    edge = cells * cell_px

    with contextlib.ExitStack() as stack:
        height_ds = stack.enter_context(rasterio.open(master))
        ocean_ds = stack.enter_context(rasterio.open(ocean)) if ocean is not None else None
        if (height_ds.width, height_ds.height) != (edge, edge):
            raise ValueError(f"{master} is {height_ds.width}x{height_ds.height}, not the "
                             f"{edge}x{edge} grid this body's zoom declares")
        nodata = height_ds.nodata

        for row0, row1 in raster_io.row_bands(edge, band_rows):
            window = raster_io.band_window(edge, row0, row1)
            strip = height_ds.read(1, window=window).astype(np.float32)  # pyright: ignore[reportCallIssue]
            if nodata is not None:
                strip[strip == nodata] = np.nan
            strip[~np.isfinite(strip)] = np.nan
            rows = (row1 - row0) // cell_px
            band = slice(row0 // cell_px, row1 // cell_px)
            tiled = strip.reshape(rows, cell_px, cells, cell_px)
            # A cell with no data at all records NaN, which is the intended value and what
            # `block_plan.relief_from_cells` raises on later, so numpy's warning is not news here.
            with np.errstate(invalid="ignore"), warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                high[band] = np.nanmax(tiled, axis=(1, 3))
                low[band] = np.nanmin(tiled, axis=(1, 3))
            if ocean_ds is not None and share is not None:
                sea = ocean_ds.read(1, window=window)  # pyright: ignore[reportCallIssue]
                share[band] = (sea > 0).reshape(rows, cell_px, cells, cell_px).mean(axis=(1, 3))


def scan(body: bodies.Body, *, work: Path | None = None,
         band_rows: int = BAND_ROWS) -> tuple[Path, Path | None]:
    """Record this body's per-cell relief, and its ocean share where the seam declares a mask.

    Returns the paths written, the second being None for a body with no ocean mask. That is the
    shape `block_plan.plan` already takes, whose `ocean_share` is optional for the same reason.

    The ocean arm is gated on `planet_seam.declared`, never on the file being present: a missing
    raster cannot tell "this body has none" from "the producer crashed", and only the declaration
    separates them.
    """
    work = work_dir(body) if work is None else work
    rasters = planet_seam.declared(body)
    master = master_path(work)
    recipe = freshness.write_if_changed(params_path(work), params(body, rasters))

    relief_out = relief_path(work)
    ocean_out = ocean_path(work) if "oceanmask" in rasters else None
    inputs = [master, recipe]
    if ocean_out is not None:
        inputs.append(ocean_master_path(work))

    fresh = not freshness.is_stale(relief_out, *inputs) and (
        ocean_out is None or not freshness.is_stale(ocean_out, *inputs))
    if fresh:
        return relief_out, ocean_out

    cells = block_plan.grid_px(body) // block_plan.CELL_PX
    high = np.full((cells, cells), np.nan)
    low = np.full((cells, cells), np.nan)
    share = np.zeros((cells, cells)) if ocean_out is not None else None
    _accumulate(master, ocean_master_path(work) if ocean_out is not None else None,
                high, low, share, band_rows)

    _write_cells(relief_out, np.stack([high, low]))
    if ocean_out is not None and share is not None:
        _write_cells(ocean_out, share[np.newaxis])
    return relief_out, ocean_out


def read_relief(work: Path) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """The recorded per-cell high and low grids, as `block_plan.relief_from_cells` wants them."""
    with rasterio.open(relief_path(work)) as dataset:
        return dataset.read(1).astype(np.float64), dataset.read(2).astype(np.float64)


def read_ocean(work: Path) -> NDArray[np.float64]:
    """The recorded per-cell ocean fraction, as `block_plan.share_from_cells` wants it."""
    with rasterio.open(ocean_path(work)) as dataset:
        return dataset.read(1).astype(np.float64)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--body", required=True, choices=sorted(bodies.BODIES),
                    help="which planet to scan; its master is found from the body's own work dir")
    ap.add_argument("--work", type=Path, default=None,
                    help="override the stage directory, for a scan outside the live store")
    ap.add_argument("--band-rows", type=int, default=BAND_ROWS,
                    help=f"rows per read, a multiple of {block_plan.CELL_PX}")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    body = bodies.BODIES[args.body]
    relief_out, ocean_out = scan(body, work=args.work, band_rows=args.band_rows)
    print(f"[relief_scan] {relief_out}")
    print(f"[relief_scan] {ocean_out}" if ocean_out is not None
          else f"[relief_scan] no ocean mask declared for {body.name}")


if __name__ == "__main__":
    main()
