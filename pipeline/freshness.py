"""Is this output still correct? Three separate questions, each with its own oracle.

  COMPLETED    `is_stale`, reading a `.done` marker rather than the output's own mtime
  NEWER THAN   `newest_mtime` over the sources, recursing into directories
  SAME SHAPE   `grid_matches`, for warp targets warped ONTO the reference grid
  SAME SCALE   `resolution_matches`, for the reference raster that DEFINES that grid

Each names a failure the others cannot see, and each function carries the case for its own — the
point of listing them together is that they are separate questions, not one. They compose:
`warp_needs_rebuild` is the second and third at once, `reference_needs_rebuild` the second and
fourth. `write_if_changed` is here because it is what lets a VALUE be a source at all, so a tunable
can be an input to `is_stale` without every `git checkout` restaging the planet.

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
    """True if `output` must be rebuilt: never completed, REWRITTEN since it was completed, or
    older than any of `inputs`.

    Freshness is read from the .done marker, never from `output` itself: GDAL creates its
    target at the START of a run, so a crashed pass leaves a full-sized, freshly-stamped,
    half-written raster that an mtime test on the raster would happily accept as current.

    A MARKER MUST ALSO BE NEWER THAN THE BYTES IT VOUCHES FOR, which is a different claim from
    either of the others and the one that was missing. A marker written by an EARLIER successful
    run keeps vouching after a later run overwrites the output and dies before finishing: Mars's
    ice alpha was rebuilt onto a new grid, crashed in its first unit burn, and was then skipped by
    the next pass because the marker from the run before it was still sitting there. Both other
    guards passed, `grid_matches` precisely BECAUSE the crash had created a full-size target on the
    new grid — and a planet shipped with an all-zero ice layer and nothing to read.

    COMPARING THE TWO MTIMES IS DERIVED, WHICH IS WHY IT LIVES HERE. The alternative is a rule that
    every stage unlinks its own marker before writing, which is a thing to remember at each of them
    and to notice missing at none. Equal stamps are fresh: a stage marks done after it writes, so
    only a STRICTLY newer output means bytes arrived after the promise.
    """
    marker = done_marker(output)
    if not output.exists() or not marker.exists():
        return True
    stamped = marker.stat().st_mtime
    if output.stat().st_mtime > stamped:
        return True
    return newest_mtime(*inputs) > stamped


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


def resolution_matches(path: Path, map_units_per_pixel: float) -> bool:
    """True if `path` is on exactly the pixel size the registry asks for.

    THE RASTER THAT DEFINES THE GRID HAD NO CHECK THE ONES BELOW IT ALL HAD. `grid_matches` re-warps
    every 3857 raster when the reference grid moves beneath it, but the reference itself was gated on
    `is_stale` alone — the mtimes of a VRT and a chunk directory, neither of which moves when a body's
    tile ceiling does. Raising Mars from z6 to z7 therefore left a 32768 square grid reading FRESH:
    the pass composited it and began cutting a z7 pyramid out of z6 pixels, which is the exact
    upsample the ceiling was chosen to avoid, arriving with no error anywhere.

    DERIVED, NOT RECORDED, which is why this takes no sidecar. A raster's transform IS its
    resolution, so there is no second copy to drift — the same reason `grid_matches` reads dimensions
    off the file rather than trusting a recipe. A recipe is what a NON-geometric setting needs,
    because nothing in the output can be asked; geometry answers for itself.

    Both axes, because a target built with one `-tr` value is square only if it was built correctly,
    and half of a resolution change is not a state worth accepting.
    """
    if not path.exists():
        return False
    with rasterio.open(path) as dataset:
        return all(math.isclose(abs(actual), map_units_per_pixel, rel_tol=1e-9)
                   for actual in (dataset.transform.a, dataset.transform.e))


def reference_needs_rebuild(out: Path, map_units_per_pixel: float, *inputs: Path) -> bool:
    """Whether the reference raster must be rebuilt: `is_stale` (a source moved) OR off the
    registry's pixel size (the body's ceiling moved).

    Split out so the composed condition is testable on its own, exactly as `warp_needs_rebuild` is.
    The load-bearing case is the one `is_stale` cannot see, and it is the mirror of that function's:
    there, a raster whose source is unchanged while the grid moved under it; here, the raster the
    others take their grid FROM, unchanged at the wrong scale.
    """
    return is_stale(out, *inputs) or not resolution_matches(out, map_units_per_pixel)


def write_if_changed(path: Path, text: str) -> Path:
    """Write `text` to `path` only when it differs, and return `path`.

    The only-when-different part is load-bearing, not an optimisation: it lets a generated
    file stand in as a dependency for `is_stale`. Tunables like KNOBS and the ramp colours
    live in source, whose mtime moves on any `git checkout` and would force a full planet
    rebuild; materialised here, their mtime moves if and only if a VALUE actually changed.

    THE ORDER EVERY STAGE WITH A RECIPE FOLLOWS: write the recipe, THEN ask the freshness question.
    That is what makes changing a setting trigger its own restage, and it is only safe because of
    the paragraph above — an unchanged recipe never moves an mtime, so writing first cannot restage
    an output that is still correct. A stage that asked first would answer against the old recipe.
    """
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
    return path
