#!/usr/bin/env python3
"""Side-by-side crops of two region renders, for judging the lake-depth ramp.

Mirrors lake_depth_prototype.py's A/B output so the judgement ("gradients read at
hero scale, rejected as an artificial gradient") can be compared like-for-like against the
calibrated version -- same sites, same framing. Sized for a phone screen, not a workstation.

--left/--right take either a render DIRECTORY (dir/region_rgb.tif, the shade.py --cells shape) or a
raster FILE directly. The file form exists because the planet A/B is two files in ONE directory
(planet_rgb_v1.tif vs planet_rgb.tif) -- dir-only would have forced a second copy of this tool,
which is the exact duplication PLAN's commonification item is about.

Usage:
  python3 -m pipeline.experiments.lake_ab --left data/work/lakeproto_off \
      --right data/work/lakeproto_log1p --outdir data/work/lakeproto_ab
  python3 -m pipeline.experiments.lake_ab --left data/work/planet_tiles/planet_rgb_v1.tif \
      --right data/work/planet_tiles/planet_rgb.tif --outdir data/work/planet_tiles/_mosaic_check \
      --site caspian=51.0,40.0 --crop 3000
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform as warp_transform

# The prototype's own crop sites (Pangong at 78.9E is outside the e080/e090 cells).
SITES = {"namtso": (90.6, 30.7), "tibet_lakes": (88.0, 31.5)}
DIVIDER_PX = 6


def to_rowcol(dataset, lon, lat):
    xs, ys = warp_transform("EPSG:4326", dataset.crs, [lon], [lat])
    row, col = dataset.index(xs[0], ys[0])
    return int(row), int(col)


def resolve_render(path: Path) -> Path:
    """A render DIRECTORY (-> its region_rgb.tif) or a raster FILE, passed straight through."""
    return path / "region_rgb.tif" if path.is_dir() else path


def crop_at(dataset, lon, lat, size):
    row, col = to_rowcol(dataset, lon, lat)
    row0 = max(0, min(dataset.height - size, row - size // 2))
    col0 = max(0, min(dataset.width - size, col - size // 2))
    window = rasterio.windows.Window(col0, row0, size, size)
    return dataset.read([1, 2, 3], window=window)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--left", type=Path, required=True,
                        help="control: a render dir (dir/region_rgb.tif) or a raster file")
    parser.add_argument("--right", type=Path, required=True,
                        help="candidate: a render dir (dir/region_rgb.tif) or a raster file")
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--label", default="ab")
    parser.add_argument("--site", action="append", default=[], metavar="NAME=LON,LAT",
                        help="crop centre (repeatable); defaults to the prototype's sites")
    parser.add_argument("--crop", type=int, default=700,
                        help="source pixels per side, before the divider")
    args = parser.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    sites = dict(SITES)
    if args.site:
        sites = {}
        for entry in args.site:
            name, _, coords = entry.partition("=")
            lon, _, lat = coords.partition(",")
            sites[name] = (float(lon), float(lat))

    left_tif = resolve_render(args.left)
    right_tif = resolve_render(args.right)
    for path in (left_tif, right_tif):
        if not path.exists():
            sys.exit(f"missing {path} -- for a render dir, run shade.py --cells for that variant first")

    with rasterio.open(left_tif) as left_ds, rasterio.open(right_tif) as right_ds:
        if left_ds.shape != right_ds.shape:
            sys.exit(f"grids differ: {left_ds.shape} vs {right_ds.shape}")
        for name, (lon, lat) in sites.items():
            size = min(args.crop, left_ds.height, left_ds.width)
            left = crop_at(left_ds, lon, lat, size)
            right = crop_at(right_ds, lon, lat, size)
            changed = int((left != right).any(axis=0).sum())
            divider = np.full((3, size, DIVIDER_PX), 255, dtype="uint8")
            pair = np.concatenate([left, divider, right], axis=2)
            out = args.outdir / f"{args.label}_{name}.png"
            with rasterio.open(out, "w", driver="PNG", width=pair.shape[2], height=size,
                               count=3, dtype="uint8") as dst:
                dst.write(pair)
            print(f"wrote {out}  ({changed:,} px differ of {size * size:,})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
