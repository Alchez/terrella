"""Hero lake-depth stage: GLOBathy depth -> a log1p ramp-position raster for the scene.

The hero twin of the tile pipeline's lake-depth layer (`render/lake_depth.py` +
`shade.composite`'s lake branch), as `snow_mask.py` is the hero twin of `render/snow.py`.
Emits `lakedepth_aea.tif` on the exact `heightfield_aea.tif` grid: Float32 storing the
lake ramp POSITION 0..1 — `shade.lake_position`'s curve baked here, venv-side, where the
tile implementation lives — so the scene just samples it into a ColorRamp over
`palette.LAKE_STOPS`. Position 0 IS the flat `WATER_RGB` tint, so lakes without depth
data degrade to exactly the pre-lake-depth look.

Depth is TINT-ONLY and must never reach displacement: at 15x exaggeration a carved bed
makes Namtso a 1.5 km crater (2026-07-07). Absolute depth, never normalised per lake
(a pond would read like Baikal). Rivers (class 3) stay flat — no global bed data
exists — and the (class 1) Caspian keeps GEBCO's measured bathymetry: both enforced by
`lake_depth.lakes_only`, the one implementation of that decision. The epistemics of the
GLOBathy field itself (synthetic shape, surveyed scale for ~0.8% of lakes) live in
`lake_depth.py`'s docstring.

Runs once per country, after `snow_mask.py`, before the Blender scene build.

Usage: python -m pipeline.render.lake_mask --render-dir data/work/<slug>/render
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

from pipeline.render import lake_depth
from pipeline.tile import shade


def depth_to_position(depth: np.ndarray, watercode: np.ndarray) -> np.ndarray:
    """Depth metres + watermask codes -> lake ramp position 0..1 (the pure, testable core).

    `lakes_only` zeroes depth off watermask class 2 (rivers flat, ocean/Caspian keep
    their own bathymetry); `lake_position` applies the tile's own depth->position curve
    read from `shade.KNOBS["lake_curve"]` — hero and tile cannot disagree on it. "off"
    (the tile's flat-water A/B control) carries over as an all-zero field.
    """
    lakes = lake_depth.lakes_only(depth, watercode)
    if shade.KNOBS["lake_curve"] == "off":
        return np.zeros_like(lakes, dtype=np.float32)
    return np.asarray(shade.lake_position(lakes, shade.KNOBS["lake_curve"]),
                      dtype=np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-dir", type=Path, required=True,
                    help="existing render dir with heightfield_aea.tif + watermask_aea.tif")
    args = ap.parse_args()
    render_dir = args.render_dir.resolve()

    out_tif = render_dir / "lakedepth_aea.tif"
    if out_tif.exists():
        print(f"{out_tif} exists — skipping", flush=True)
        return

    # The VRT is a local build product (pipeline.acquire.extract_globathy), so its
    # absence is a config error, not a data gap: exit loudly rather than write an
    # all-flat raster that batch resume would trust as the prep-complete marker.
    if not lake_depth.LAKE_VRT.exists():
        sys.exit(f"{lake_depth.LAKE_VRT} missing — run pipeline.acquire.extract_globathy")

    # grid + CRS from the existing heightfield (the snow_mask/render_prep pattern):
    # the raster must land pixel-for-pixel on the grid the render was made from
    heightfield_path = render_dir / "heightfield_aea.tif"
    with rasterio.open(heightfield_path) as heightfield_dataset:
        dst_crs, transform = heightfield_dataset.crs, heightfield_dataset.transform
        width, height = heightfield_dataset.width, heightfield_dataset.height
        aea_bounds = heightfield_dataset.bounds
    xres = transform.a  # pyright: ignore[reportAttributeAccessIssue] — affine untyped
    print(f"grid from {heightfield_path.name}: {width} x {height}, {xres:.0f} m/px",
          flush=True)

    # Bilinear/Float32, the tile warp's own reasoning (lake_depth.warp_depth): depth is
    # continuous — halfway between 40 m and 0 m really is 20 m — and -srcnodata keeps
    # GLOBathy's -9999 out of the kernel so no false trench bleeds across a shoreline.
    # Streamed via gdalwarp -wm (the snow_mask russia lesson: an in-process warp of a
    # continent frame materialises the whole source window in one read and OOMs).
    left, bottom, right, top = aea_bounds
    tmp_depth = out_tif.with_name(out_tif.name + ".depth.tmp")
    subprocess.run(
        ["gdalwarp", "-overwrite", "-q", "-of", "GTiff",
         "-s_srs", "EPSG:4326", "-t_srs", dst_crs.to_wkt(),
         "-te", repr(left), repr(bottom), repr(right), repr(top),
         "-ts", str(width), str(height),
         "-r", "bilinear", "-ot", "Float32",
         "-srcnodata", str(lake_depth.GLOBATHY_NODATA), "-dstnodata", "0",
         "-wm", "512", "-multi", "-wo", "NUM_THREADS=ALL_CPUS",
         "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
         str(lake_depth.LAKE_VRT), str(tmp_depth)],
        check=True, capture_output=True)
    with rasterio.open(tmp_depth) as depth_dataset:
        depth_raw = depth_dataset.read(1)
    tmp_depth.unlink(missing_ok=True)
    depth = np.where(np.isfinite(depth_raw) & (depth_raw > 0.0),
                     depth_raw, 0.0).astype(np.float32)

    with rasterio.open(render_dir / "watermask_aea.tif") as watermask_dataset:
        watercode = watermask_dataset.read(1)

    position = depth_to_position(depth, watercode)

    profile: dict[str, Any] = dict(driver="GTiff", width=width, height=height,
                                   count=1, dtype="float32", crs=dst_crs,
                                   transform=transform, tiled=True,
                                   compress="deflate")
    # Crash-safety: .tmp + os.replace, so a kill mid-write never leaves a partial
    # raster that batch resume would trust as the prep-complete marker.
    tmp = out_tif.with_name(out_tif.name + ".tmp")
    with rasterio.open(tmp, "w", **profile) as out:
        out.write(position, 1)
    os.replace(tmp, out_tif)

    lake_px = int((position > 0).sum())
    km2 = lake_px * (xres * xres) / 1e6
    print(f"wrote {out_tif}", flush=True)
    print(f"lakes with depth: {lake_px:,} px = {km2:,.0f} km^2 "
          f"({100.0 * lake_px / (width * height):.2f}% of frame); "
          f"max depth {float(depth.max()):.0f} m", flush=True)


if __name__ == "__main__":
    main()
