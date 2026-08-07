"""Turn the OMEGA PDS3 image into a float32 GeoTIFF the render tier can warp.

WHY A STAGE AND NOT A LOADER. The product is a headerless 207 MB block of LSB int16 beside a
detached label; every consumer would otherwise have to know its packing, its fill value and its
georeferencing, and each would be a place to get one of them subtly wrong. One conversion, one
recipe, and what lands is an ordinary raster with a CRS.

EVERY NUMBER COMES FROM THE LABEL, NEVER FROM THIS FILE. The scaling, the offset, the fill and the
grid are read at run time and cross-checked against each other, so a re-published product is an
error here rather than a silent rescale of an albedo that still looks like albedo. The prototype
this replaces transcribed `OFFSET`, `SCALING` and `from_origin(-180, 90, 0.025, 0.025)` as
constants; all four are derivable, and a transcribed constant cannot notice it has gone stale.

THE GEOREFERENCING IS DERIVED TWICE AND THE TWO MUST AGREE. The bounding box
(`WESTERNMOST_LONGITUDE`, `MAXIMUM_LATITUDE`, `MAP_RESOLUTION`) and the PDS projection offsets
(`SAMPLE_PROJECTION_OFFSET`, `LINE_PROJECTION_OFFSET`) describe the same grid by different routes.
Taking either alone risks a half-pixel shift from the pixel-centre convention — the classic silent
error in PDS georeferencing — and a shift of half of 0.025° is invisible in the image and wrong
everywhere it is sampled. Agreement between two derivations is what makes this checkable at all.

EPSG:4326 IS DECLARED, NOT PROJECTED TO, exactly as `fuse/relabel_mars` does for the DEM and for the
same reason: PROJ refuses to build an operation between two celestial bodies, so every Mars raster
in this pipeline is labelled with Earth's geographic CRS and keeps its own angles. That is an
identity ONLY for a true sphere in degrees, which `download_omega.assert_label` is what proves.

Output (data/work/mars/omega/):
  albedo_r1080_4326.tif   float32 albedo, nodata -9999, EPSG:4326
  omega_extract_params.json   the recipe: label-derived scaling, grid and fill

Idempotent: the raster is rebuilt only when it is missing or its recipe changed.

Usage:
  python3 -m pipeline.acquire.extract_omega
  python3 -m pipeline.acquire.extract_omega --force
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from pipeline import bodies, raster_io
from pipeline.acquire import download_omega

#: What an unmeasured pixel becomes. NOT the label's -32768: that is a value in PACKED counts, and
#: everything downstream reads unpacked albedo, where -32768 would be a plausible-looking float.
NODATA = -9999.0


def work_dir() -> Path:
    """Mars's OMEGA stage directory. `bodies.work_dir` owns the layout, including why the body is in
    the path rather than in any recipe."""
    return bodies.work_dir(bodies.MARS, "omega")


def albedo_path() -> Path:
    return work_dir() / "albedo_r1080_4326.tif"


def recipe_path() -> Path:
    return work_dir() / "omega_extract_params.json"


def grid_from_label(label: dict[str, str]) -> dict[str, float]:
    """The scaling and georeferencing, read from the label and cross-checked against themselves.

    Returns plain floats rather than a transform so the recipe can record exactly what was used —
    a recipe holding a rasterio object would record its repr, which is not a contract.

    THE CROSS-CHECKS ARE THE POINT. Each of the four says the same grid twice from different
    keywords, so a product whose bounding box and projection offsets disagree stops here instead of
    producing a raster that is half a pixel wrong in a way no image inspection reveals.
    """
    resolution = float(label["MAP_RESOLUTION"])           # pixels per degree
    lines, samples = int(label["LINES"]), int(label["LINE_SAMPLES"])
    north, south = float(label["MAXIMUM_LATITUDE"]), float(label["MINIMUM_LATITUDE"])
    west, east = float(label["WESTERNMOST_LONGITUDE"]), float(label["EASTERNMOST_LONGITUDE"])

    checks = [
        ("LINES", lines, (north - south) * resolution),
        ("LINE_SAMPLES", samples, (east - west) * resolution),
        # PDS counts from the pixel EDGE with a half-pixel offset to the first centre, so the
        # projection offset of the prime meridian / equator is span * resolution + 0.5.
        ("LINE_PROJECTION_OFFSET", float(label["LINE_PROJECTION_OFFSET"]), north * resolution + 0.5),
        ("SAMPLE_PROJECTION_OFFSET", float(label["SAMPLE_PROJECTION_OFFSET"]),
         -west * resolution + 0.5),
    ]
    for keyword, stated, derived in checks:
        if abs(float(stated) - derived) > 1e-6:
            sys.exit(f"label {keyword} is {stated}, but the rest of the label derives {derived} — "
                     f"the bounding box and the projection offsets describe different grids, and "
                     f"taking either alone would shift every sample")

    return {"scaling": float(label["SCALING_FACTOR"]), "offset": float(label["OFFSET"]),
            "missing": float(label["MISSING_CONSTANT"]), "resolution": resolution,
            "west": west, "north": north, "lines": float(lines), "samples": float(samples)}


def build_recipe(grid: dict[str, float]) -> str:
    """Everything that decides the output's pixels, so a changed label restages it."""
    return json.dumps({"grid": grid, "nodata": NODATA, "crs": "EPSG:4326",
                       "source_md5": download_omega.MD5}, indent=2, sort_keys=True) + "\n"


def unpack(raw: np.ndarray, grid: dict[str, float]) -> np.ndarray:
    """Packed counts -> albedo as float32, with the label's fill turned into `NODATA`.

    The fill is compared on the RAW counts before scaling, because scaling it produces an ordinary
    negative float that no downstream range check would question.
    """
    albedo = raw.astype(np.float32) * grid["scaling"] + grid["offset"]
    albedo[raw == grid["missing"]] = NODATA
    return albedo


def extract(force: bool = False) -> Path:
    """Read the PDS3 image and write the GeoTIFF. Returns the raster's path."""
    label_text = download_omega.product_path("albedo_r1080_equ_map.lbl")
    image = download_omega.product_path("albedo_r1080_equ_map.img")
    if not image.exists() or not label_text.exists():
        sys.exit(f"{image.name} or its label is not on disk — run "
                 f"`python3 -m pipeline.acquire.download_omega` first (~207 MB)")

    label = download_omega.assert_label(label_text.read_text(encoding="utf-8"))
    grid = grid_from_label(label)
    recipe = build_recipe(grid)

    out = albedo_path()
    sidecar = recipe_path()
    if not force and out.exists() and sidecar.exists() and sidecar.read_text() == recipe:
        print(f"{out.name} fresh -> skip", flush=True)
        return out

    lines, samples = int(grid["lines"]), int(grid["samples"])
    raw = np.fromfile(image, dtype="<i2")
    if raw.size != lines * samples:
        sys.exit(f"{image.name} holds {raw.size} values, but the label says "
                 f"{lines} x {samples} = {lines * samples}")

    albedo = unpack(raw.reshape(lines, samples), grid)
    pixel = 1.0 / grid["resolution"]
    work_dir().mkdir(parents=True, exist_ok=True)
    profile: dict = dict(
        driver="GTiff", width=samples, height=lines, count=1, dtype="float32",
        crs="EPSG:4326", transform=from_origin(grid["west"], grid["north"], pixel, pixel),
        nodata=NODATA, **raster_io.GTIFF_CREATE)
    with rasterio.open(out, "w", **profile) as dataset:  # pyright: ignore[reportCallIssue]
        dataset.write(albedo, 1)

    valid = albedo[albedo != NODATA]
    print(f"wrote {out} — {samples}x{lines}, valid {valid.size / albedo.size:.3%}, "
          f"albedo {valid.min():.4f}..{valid.max():.4f}", flush=True)
    sidecar.write_text(recipe, encoding="utf-8")  # AFTER the raster, so a crash leaves it stale
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--force", action="store_true", help="rebuild even when the recipe matches")
    return parser


def main() -> int:
    extract(force=build_parser().parse_args().force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
