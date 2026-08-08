"""Viking's colour mosaic as ONE band of brightness on a 4326 grid — the field both ice tiers read.

WHY THIS STAGE EXISTS AT ALL. The acquired mosaic cannot be handed to either ice tier as published,
for two independent reasons. It is SimpleCylindrical METRES on the Mars sphere where everything
downstream speaks EPSG:4326 degrees; and it is three colour bands where the grading needs one
number. `cap_render`'s warp takes a 4326 source and returns band 1, and the composite tier warps a
4326 source onto the 3857 grid — so both consumers want the same thing, and this builds it once.

WHOLE PLANET, DELIBERATELY, THOUGH ONLY THE POLES ARE EVER READ. A polar crop is about 240 MB
against this file's ~1 GB, and it would buy that back at the price of a crop latitude that must stay
looser than everything reading it — the cap frame's corners reach about 75.9 degrees and the tile
band starts at 76.5 — plus the guard that keeps it so. The failure mode of a crop set too tight is
ice that quietly stops appearing at the band edge, with no error anywhere. Against a project that
budgets tens of GB for a pyramid, the disk is the cheaper thing to spend.

THE CHAIN IS THE ONE THE LEVELS WERE MEASURED THROUGH, and that is a constraint rather than a
preference. `ALPHA_LEVELS` is four percentiles of this exact field; a render that resampled the
mosaic differently would grade against levels taken from a different set of numbers.
`scripts/measure_viking_levels.py --compare` re-measures them through whatever this produces, which
is what makes the equality checkable rather than asserted.

  THE METRES-TO-DEGREES STEP IS A WARP, NOT A RELABEL, and it looks like a relabel until measured.
  SimpleCylindrical is a linear function of latitude and longitude, so the conversion is a rescale
  of the geotransform and nothing else — except that the publisher rounded `PixelResolution` to
  925.406, and 23059 of those overshoot the sphere's circumference by about 860 m. Taking the
  transform at face value therefore puts the grid at -180.008 .. +180.008, not -180 .. +180. So the
  grid is stated here and warped onto, rather than declared and hoped for.

ZERO IS THE FILL AND IT SURVIVES THE COLLAPSE EXACTLY. Viking declares nodata 0 on each band and
means absent only where all three agree, which no scalar can express; `mars_ice.luma` is where the
argument lives, and the short version is that positive weights over non-negative channels vanish
only together. That is why the output can carry a scalar nodata of 0 and why it must be FLOAT and
not 8-bit: a pixel of (1, 0, 0) has luma 0.2126, and an integer round would file the darkest
measured ground on the planet under "never measured".

Output (data/work/mars/ice/):
  viking_luma_4326.tif      Float32 brightness, nodata 0, 23059 x 11530 over the whole sphere
  viking_luma_params.json   the recipe: source edition, weights, grid, and the measured valid share

Idempotency: the recipe sidecar is written LAST and compared on the next run, so a crash mid-pass
leaves the output stale rather than fresh. `--force` rebuilds regardless.

Usage:
  python3 -m pipeline.render.viking_luma            # build if stale, else report and stop
  python3 -m pipeline.render.viking_luma --force    # rebuild unconditionally
  python3 -m pipeline.render.viking_luma --check    # report freshness, write nothing
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.windows import Window

from pipeline import bodies
from pipeline.acquire import download_viking_mosaic
from pipeline.raster_io import row_bands
from pipeline.render import mars_ice

#: The mosaic's own sphere. Warping out of SimpleCylindrical metres has to stay on one celestial
#: body — PROJ refuses to cross — so this is the intermediate the EPSG:4326 relabel then renames.
MARS_LONGLAT = "+proj=longlat +R=3396190 +no_defs"

#: The output grid: the publisher's own pixel count over the exact sphere. Stated rather than
#: derived, per the module note on the rounded `PixelResolution`.
WIDTH = download_viking_mosaic.EXPECTED_WIDTH
HEIGHT = download_viking_mosaic.EXPECTED_HEIGHT

#: Absent, on both the source's terms and the output's. See the module note: this survives the RGB
#: collapse exactly, which is the only reason one number can stand for three bands agreeing.
NODATA = 0.0

#: Rows per pass. The luma promotes to float64 internally, so this many rows of three bands is about
#: 1.2 GB of working set — sized to stay well inside the one-heavy-job cap rather than to be fast.
BAND_ROWS = 1024


def work_dir() -> Path:
    """This stage's directory, resolved at call time so a redirected data root moves it."""
    return bodies.work_dir(bodies.get("mars"), "ice")


def luma_path() -> Path:
    """The brightness raster both ice tiers read."""
    return work_dir() / "viking_luma_4326.tif"


def recipe_path() -> Path:
    """The freshness sidecar, beside the output it describes."""
    return work_dir() / "viking_luma_params.json"


def _run(argv: list[str]) -> None:
    subprocess.run(argv, check=True)


def degrees_vrt(source: Path, out: Path) -> Path:
    """The mosaic on a clean global degree grid, labelled EPSG:4326, as a VRT that copies nothing.

    TWO STEPS AND ONLY THE FIRST MOVES A PIXEL. The warp lands SimpleCylindrical metres on lon/lat
    degrees of the SAME sphere, which PROJ will do; the translate then declares that grid to be
    EPSG:4326, which is an identity on the angles because the latitudes are planetocentric and a
    planetocentric latitude is the same angle on any figure. `fuse/relabel_mars` carries the full
    argument for the second step and cannot be reused for the first: its precondition is a source
    already in degrees, which this product fails.

    Both outputs are VRTs, so nothing here materialises 798 MB a second time.
    """
    warped = out.with_name(out.name.replace(".vrt", "_marsdeg.vrt"))
    _run(["gdalwarp", "-q", "-overwrite", "-of", "VRT", "-t_srs", MARS_LONGLAT,
          "-te", "-180", "-90", "180", "90", "-ts", str(WIDTH), str(HEIGHT),
          "-r", "bilinear", str(source), str(warped)])
    _run(["gdal_translate", "-q", "-of", "VRT", "-a_srs", "EPSG:4326", str(warped), str(out)])
    return out


def build(source: "Path | None" = None) -> tuple[Path, float]:
    """Write the brightness raster, returning it and the share of the sphere that is measured.

    STREAMED IN ROW BANDS BECAUSE THE ANSWER IS WHAT DOES NOT FIT, the same shape as the feather's
    banded pass one module over: the whole float64 luma of this grid is 2.1 GB before it is cast
    down. Each band is read, collapsed and written, and nothing holds the planet at once.

    The valid share is MEASURED HERE rather than assumed, and returned so the recipe can record it.
    A producer declares what it emitted; "how much of this file is data" is not knowable later from
    a file that stores absence as a legal value.
    """
    mosaic = source if source is not None else download_viking_mosaic.mosaic_path()
    work_dir().mkdir(parents=True, exist_ok=True)
    vrt = degrees_vrt(mosaic, work_dir() / "viking_4326.vrt")

    out = luma_path()
    part = out.with_suffix(".tif.part")
    measured = 0
    with rasterio.open(vrt) as reader:
        profile: dict[str, Any] = dict(
            driver="GTiff", width=reader.width, height=reader.height, count=1,
            dtype="float32", nodata=NODATA, crs=reader.crs, transform=reader.transform,
            tiled=True, compress="DEFLATE", bigtiff="YES")
        with rasterio.open(part, "w", **profile) as writer:  # pyright: ignore[reportCallIssue]
            for row0, row1 in row_bands(reader.height, BAND_ROWS):
                window = Window(0, row0, reader.width, row1 - row0)  # pyright: ignore[reportCallIssue]
                values = mars_ice.luma(reader.read(window=window))
                measured += int(np.count_nonzero(values))
                writer.write(values.astype(np.float32), 1, window=window)
    part.replace(out)
    return out, measured / float(WIDTH * HEIGHT)


def build_recipe(valid_fraction: float) -> str:
    """Everything the output depends on besides the code that wrote it.

    THE SOURCE EDITION IS KEYED BY THE PUBLISHER'S DIGEST, not by a path or an mtime. A republished
    mosaic under the same name is the failure the acquirer exists to catch, and this is what makes
    that catch reach the derived raster instead of stopping at the download.

    THE WEIGHTS ARE HERE BECAUSE THEY REACH A PIXEL. A luma rebuilt through different weights is a
    different field, and a field that changed without its recipe changing leaves a stale raster
    looking fresh — the same rule that put every look constant into the composite's recipe.
    """
    return json.dumps({
        "source": download_viking_mosaic.MOSAIC_NAME,
        "source_md5": download_viking_mosaic.EXPECTED_MD5,
        "luma_weights": list(mars_ice.LUMA_WEIGHTS),
        "grid": {"width": WIDTH, "height": HEIGHT, "crs": "EPSG:4326",
                 "bounds": [-180.0, -90.0, 180.0, 90.0]},
        "nodata": NODATA,
        "valid_fraction": round(valid_fraction, 6),
    }, indent=2, sort_keys=True) + "\n"


def recorded_recipe() -> "dict[str, Any] | None":
    """The recipe beside the output on disk, or None if there is none to read."""
    path = recipe_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def is_fresh() -> bool:
    """Whether the raster can be skipped: on disk, with a recipe matching everything but the count.

    `valid_fraction` is EXCLUDED from the comparison because it is an OUTPUT of the build and not an
    input to it — comparing it would ask the stage to predict its own result before running, and a
    recipe that can never match makes an idempotent stage rebuild forever.
    """
    recorded = recorded_recipe()
    if recorded is None or not luma_path().exists():
        return False
    expected = json.loads(build_recipe(0.0))
    return {key: value for key, value in recorded.items() if key != "valid_fraction"} == \
        {key: value for key, value in expected.items() if key != "valid_fraction"}


def build_parser() -> argparse.ArgumentParser:
    """The CLI, split out of `main` so its contract is testable without running a pass."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--force", action="store_true",
                        help="rebuild even if the recipe on disk already matches")
    parser.add_argument("--check", action="store_true",
                        help="report freshness and stop; writes nothing")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.check:
        print(f"{luma_path()}: {'fresh' if is_fresh() else 'STALE'}", flush=True)
        return 0

    if is_fresh() and not args.force:
        print(f"{luma_path()} fresh -> skip", flush=True)
        return 0

    mosaic = download_viking_mosaic.mosaic_path()
    if not mosaic.exists():
        sys.exit(f"{mosaic} is not on disk — run "
                 f"`python3 -m pipeline.acquire.download_viking_mosaic` first")

    print(f"collapsing {mosaic.name} -> Rec. 709 luma on a 4326 grid ...", flush=True)
    out, valid_fraction = build(mosaic)
    print(f"wrote {out} ({out.stat().st_size:,} bytes, "
          f"{100 * valid_fraction:.2f}% measured)", flush=True)
    recipe_path().write_text(build_recipe(valid_fraction), encoding="utf-8")  # LAST, so a crash
    print(f"wrote {recipe_path()}", flush=True)                               # leaves it stale
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
