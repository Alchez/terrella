"""Is this output still correct? Three separate questions, each with its own oracle.

  COMPLETED    a `.done` marker beside the output, never the output's own mtime. GDAL creates its
               target at the START of a run, so a crashed pass leaves a full-sized, freshly
               stamped, half-written raster that an mtime test would accept as current.
  NEWER THAN   `newest_mtime` over the SOURCES, recursing into directories, because a VRT's own
               mtime does not move when the chunks it points at are re-fused.
  SAME SHAPE   `grid_matches`, for warp targets only, because a re-fuse can grow the planet under
               a raster whose own source never moved.

`write_if_changed` is here because it is what lets a VALUE be a source. Tunables live in Python,
whose mtime moves on any `git checkout`; materialised into a sidecar, their mtime moves if and only
if a value actually changed, and the sidecar can then stand in as an input to `is_stale`.

These are general and belong to no stage. They lived in `tile/shade_planet.py`, which two sibling
stages already imported them from — do not fold them back into a stage.
"""

import math
from pathlib import Path

import rasterio


def done_marker(output: Path) -> Path:
    """The completion stamp beside `output` (height_3857.tif -> height_3857.done)."""
    return output.with_suffix(".done")


def mark_done(output: Path) -> None:
    """Stamp `output` complete. Call ONLY after its stage has returned successfully."""
    done_marker(output).touch()


def newest_mtime(*inputs: Path) -> float:
    """Newest mtime among `inputs`, recursing into directories. Missing paths score 0.0.

    Directories are walked rather than stat'ed because a VRT's own mtime does NOT move when
    the chunks it points at are re-fused -- which is exactly how the Caspian re-fuse stayed
    invisible to the old guard. The planet is 540 cells x 3 rasters, so this is ~1.6k stats.
    """
    newest = 0.0
    for path in inputs:
        if not path.exists():
            continue
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    newest = max(newest, child.stat().st_mtime)
        else:
            newest = max(newest, path.stat().st_mtime)
    return newest


def is_stale(output: Path, *inputs: Path) -> bool:
    """True if `output` must be rebuilt: never completed, or older than any of `inputs`.

    Freshness is read from the .done marker, never from `output` itself: GDAL creates its
    target at the START of a run, so a crashed pass leaves a full-sized, freshly-stamped,
    half-written raster that an mtime test on the raster would happily accept as current.
    """
    if not output.exists() or not done_marker(output).exists():
        return True
    return newest_mtime(*inputs) > done_marker(output).stat().st_mtime


def grid_matches(path: Path, width: int, height: int, bounds) -> bool:
    """True if `path` exists on exactly the reference grid (`width` x `height`, same `bounds`).

    Every 3857 raster below `height_3857` is warped to height's grid (via -te/-ts), but each one's
    freshness is gated on its own SOURCE, not on height. A re-fuse that GROWS the grid -- un-skipping
    Antarctica takes the planet from 93009 to 131072 rows -- re-warps height while these sit falsely
    fresh at the old dimensions, and the composite then reads window slices past their bottom (silent
    corruption). A dimension/bounds comparison catches exactly that, and is deliberately NOT an mtime
    dependency on height: that would re-warp all of them on a SAME-grid re-fuse (the Caspian
    rewrote 4 chunks without moving the grid), which is 30+ min of needless work.

    Bounds are compared with a 1 m tolerance -- far below the 305 m pixel, so a real grid shift always
    trips it, while the float noise of a -te repr round-trip never does.
    """
    if not path.exists():
        return False
    with rasterio.open(path) as dataset:
        return (dataset.width == width and dataset.height == height
                and all(math.isclose(actual, expected, abs_tol=1.0)
                        for actual, expected in zip(tuple(dataset.bounds), tuple(bounds))))


def warp_needs_rebuild(out: Path, grid, *inputs: Path) -> bool:
    """Whether a 3857 warp target must be rebuilt: `is_stale` (a source moved) OR off `grid`
    (a re-fuse resized the planet under it). `grid` is (width, height, bounds).

    Split out so the composed condition is testable on its own. The load-bearing case is the one
    `is_stale` alone cannot see: a raster whose SOURCE is unchanged but whose grid shrank beneath it.
    """
    return is_stale(out, *inputs) or not grid_matches(out, *grid)


def write_if_changed(path: Path, text: str) -> Path:
    """Write `text` to `path` only when it differs, and return `path`.

    The only-when-different part is load-bearing, not an optimisation: it lets a generated
    file stand in as a dependency for `is_stale`. Tunables like KNOBS and the ramp colours
    live in source, whose mtime moves on any `git checkout` and would force a full planet
    rebuild; materialised here, their mtime moves if and only if a VALUE actually changed.
    """
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
    return path
