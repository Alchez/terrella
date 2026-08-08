"""Reproject a vector onto a target grid and burn it — one owner for a two-step nobody may split.

`gdal_rasterize` DOES NOT REPROJECT, AND ITS FAILURE IS A FILE FULL OF ZEROS. Handed a vector in one
CRS and a `-te` extent in another, it finds every vertex outside the extent, burns nothing, exits 0,
and writes a raster whose header is exactly what was asked for. Downstream that output cannot be told
from "this body has nothing there" by any type, any test, or any eye — so the reprojection and the
burn are one function here rather than two lines a caller is trusted to keep in order.

`-a_srs` IS NOT THE REPROJECTION, which is the confusion this module exists to make unrepresentable.
`ogr2ogr -a_srs` ASSIGNS a label and moves no coordinate; used in place of `-t_srs` it produces
exactly the all-zero raster above. It is a cure in one situation only — stripping a celestial-body
label PROJ refuses to operate across — and that situation belongs to sources this pipeline does not
take: Natural Earth is 4326 outright, and the SIM 3292 GeoJSON already reads as 4326 unaided.

THE EMPTINESS GUARD IS THE CALLER'S CLAIM AND NOT THIS MODULE'S. Only the caller knows whether
nothing is a legitimate answer, so `must_draw` carries a sentence about what should have appeared and
None means an empty burn is fine. A windowed scan stops at the first non-zero pixel, so the whole
raster is read only in the case that is about to raise anyway.

MEASURED, so that a defensive unlink is not added here nor a flag dropped: given `-te` and `-ts`,
`gdal_rasterize` RECREATES an existing target at the new size rather than opening it in update mode,
creation options included. `snow.rasterize_glaciers_raster`'s unlink guards the call shape that omits
them, which this one cannot express.
"""

import subprocess
from pathlib import Path

import rasterio


class NothingBurnt(RuntimeError):
    """A burn the caller declared non-empty produced no pixels.

    Its own class rather than a bare `RuntimeError` so a caller can tell this apart from a GDAL
    failure: the subprocesses raise `CalledProcessError`, and the whole point of this exception is
    that both commands SUCCEEDED and the answer is still wrong.
    """


def reproject_argv(source: Path, target_srs: str, out: Path) -> list[str]:
    """`ogr2ogr` into the target CRS. Pure, so a test can pin the flags without a GDAL run.

    `-t_srs` and never `-a_srs`; the module note holds why that is the whole subject here. The output
    driver comes from `out`'s extension, which is `ogr2ogr`'s own convention rather than ours.
    """
    return ["ogr2ogr", "-overwrite", "-t_srs", target_srs, str(out), str(source)]


def rasterize_argv(vector: Path, bounds: tuple[float, float, float, float], width: int, height: int,
                   out: Path, creation_options: tuple[str, ...] = ()) -> list[str]:
    """`gdal_rasterize` of an ALREADY-PROJECTED vector onto this grid, as a 0/1 Byte mask.

    `creation_options` is empty for a cap-sized target and carries TILED/DEFLATE/BIGTIFF for a
    planet-sized one — the axis two shipping callers actually differ on, rather than a knob invented
    for a caller that does not exist. Each entry is one `-co` argument, e.g. `"TILED=YES"`.
    """
    left, bottom, right, top = bounds
    options: list[str] = []
    for option in creation_options:
        options += ["-co", option]
    return ["gdal_rasterize", "-q", "-burn", "1", "-init", "0", "-ot", "Byte", *options,
            "-te", str(left), str(bottom), str(right), str(top),
            "-ts", str(width), str(height), str(vector), str(out)]


def drew_nothing(raster: Path) -> bool:
    """Whether a burnt raster is entirely zero, read a block at a time and short-circuiting.

    Windowed rather than `read(1).any()` because the planet-grid caller's mask is 32768² Byte: a
    whole read is a gigabyte to answer a yes/no question, and the yes case exits on the first block
    holding anything.
    """
    with rasterio.open(raster) as dataset:
        for _index, window in dataset.block_windows(1):
            if dataset.read(1, window=window).any():
                return False
    return True


def burn_onto_grid(source: Path, target_srs: str, bounds: tuple[float, float, float, float],
                   width: int, height: int, projected: Path, out: Path,
                   creation_options: tuple[str, ...] = (),
                   must_draw: "str | None" = None) -> Path:
    """Reproject `source` into `target_srs`, burn it onto this grid, and return the raster.

    `projected` is the intermediate the caller names, on `perennial_ice.WarpToCap`'s rule: a helper
    inventing its own filename spells out a convention the caller already owns, and the caller is
    what has a work directory and a pole to name it after.

    `must_draw` names what the caller expects to see and raises `NothingBurnt` when nothing appears.
    Pass it wherever an empty answer would be a broken projection rather than an honest fact about the
    body — which is every caller whose geometry is known to intersect the grid.
    """
    subprocess.run(reproject_argv(source, target_srs, projected), check=True, capture_output=True)
    subprocess.run(rasterize_argv(projected, bounds, width, height, out, creation_options),
                   check=True, capture_output=True)
    if must_draw is not None and drew_nothing(out):
        raise NothingBurnt(
            f"{must_draw} rasterised to nothing. Both commands succeeded, so this is geometry that "
            f"missed the grid rather than a GDAL failure: check that {target_srs} is the CRS "
            f"{bounds} is measured in, and that the reprojection ran at all."
        )
    return out
