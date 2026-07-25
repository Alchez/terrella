#!/usr/bin/env python3
"""Check GLOBathy's modelled cone against GEBCO's measured bathymetry.

GLOBathy models every lake as D = l x Dmax / L (depth grows linearly with distance from
shore), so its deepest point is wherever you are FARTHEST FROM ANY SHORE. That is a
geometric guess. The 2026-07-07 rejection of the uncalibrated prototype turned entirely on
epistemics -- "an artificial gradient... blind on deep lakes" -- and GLOBathy answers the
second half with a real published Dmax, but the SHAPE is still a cone.

The Caspian and the Great Lakes are the only waterbodies where we hold both the model and a
measurement (GEBCO probed 2026-07-15: every other major lake returns a flat surface), so they
are the only place the cone can be falsified. Whatever we learn here is the best evidence we
will ever have for how far to trust the cone on Baikal, where we can never check.

Depth is measured below each lake's own surface, which is why --surface-m is required: the
Caspian sits at -28 m but Superior at +183 m, and GEBCO reports absolute elevation.

Reads decimated (the Caspian raster is ~5 GB at full res) -- we are locating basins, not
counting pixels.

Usage:
  python3 -m pipeline.experiments.globathy_vs_gebco --lake-id 1 --surface-m -28 --label Caspian
  python3 -m pipeline.experiments.globathy_vs_gebco --lake-id 5 --surface-m 183 --label Superior
"""

import argparse
import sys

import numpy as np
import rasterio
from rasterio.enums import Resampling

from pipeline import paths

RASTER_DIR = paths.DATA / "work/globathy/rasters"
GEBCO = paths.DATA / "raw/gebco/gebco_2026_global.vrt"
DECIMATE_LONG_EDGE = 1600


def read_decimated(path, long_edge):
    """Read band 1 downsampled so the long edge is ~long_edge, with its scaled transform."""
    with rasterio.open(path) as dataset:
        scale = long_edge / max(dataset.width, dataset.height)
        out_h = max(1, round(dataset.height * scale))
        out_w = max(1, round(dataset.width * scale))
        data = dataset.read(1, out_shape=(out_h, out_w),
                            resampling=Resampling.average, masked=True)
        transform = dataset.transform * dataset.transform.scale(
            dataset.width / out_w, dataset.height / out_h)
        return data, transform


def lonlat_of(transform, row, col):
    return transform.c + (col + 0.5) * transform.a, transform.f + (row + 0.5) * transform.e


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--lake-id", type=int, required=True, help="Hylak_id")
    parser.add_argument("--surface-m", type=float, required=True,
                        help="the lake's surface elevation (Caspian -28, Superior +183)")
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    raster = RASTER_DIR / f"{args.lake_id}.tif"
    if not raster.exists():
        sys.exit(f"{raster} not extracted -- it may be below extract_globathy's MIN_BYTES")

    depth, depth_transform = read_decimated(raster, DECIMATE_LONG_EDGE)
    print(f"== {args.label or args.lake_id} (surface {args.surface_m:+.0f} m) ==")
    print(f"  decimated {depth.shape}, valid {depth.count():,} px, "
          f"max modelled depth {depth.max():.1f} m")

    row, col = np.unravel_index(np.argmax(depth.filled(-1)), depth.shape)
    cone_lon, cone_lat = lonlat_of(depth_transform, row, col)
    print(f"  cone deepest   : {depth[row, col]:7.1f} m  at {cone_lon:.2f}E {cone_lat:.2f}N")

    west, north = lonlat_of(depth_transform, 0, 0)
    east, south = lonlat_of(depth_transform, depth.shape[0] - 1, depth.shape[1] - 1)
    with rasterio.open(GEBCO) as gebco_ds:
        window = gebco_ds.window(west, south, east, north)
        gebco = gebco_ds.read(1, window=window, out_shape=depth.shape,
                              resampling=Resampling.average).astype("float32")
        gebco_transform = gebco_ds.window_transform(window) * rasterio.Affine.scale(
            window.width / depth.shape[1], window.height / depth.shape[0])

    # Compare only where GLOBathy claims lake AND GEBCO sits below the lake surface.
    measured_depth = np.where(~depth.mask & (gebco < args.surface_m),
                              args.surface_m - gebco, np.nan)
    if np.all(np.isnan(measured_depth)):
        sys.exit("no overlapping measured pixels -- GEBCO may hold only a flat surface here")

    row2, col2 = np.unravel_index(np.nanargmax(measured_depth), measured_depth.shape)
    meas_lon, meas_lat = lonlat_of(gebco_transform, row2, col2)
    print(f"  GEBCO deepest  : {measured_depth[row2, col2]:7.1f} m  "
          f"at {meas_lon:.2f}E {meas_lat:.2f}N")
    separation_km = np.hypot((cone_lon - meas_lon) * 111.32 * np.cos(np.radians(meas_lat)),
                             (cone_lat - meas_lat) * 111.32)
    print(f"  separation     : {separation_km:.0f} km between the two 'deepest points'")

    both = ~np.isnan(measured_depth) & ~depth.mask
    model = depth.filled(np.nan)[both]
    truth = measured_depth[both]
    error = model - truth
    print(f"  overlapping px : {both.sum():,}")
    print(f"  mean |error|   : {np.abs(error).mean():7.1f} m")
    print(f"  median |error| : {np.median(np.abs(error)):7.1f} m")
    print(f"  correlation    : {np.corrcoef(model, truth)[0, 1]:7.3f}")

    # The failure that matters for a log ramp: where truth is shallow, what does the cone say?
    shallow = truth < 20.0
    if shallow.any():
        print(f"  where truth < 20 m ({shallow.sum():,} px): "
              f"cone says {model[shallow].mean():.1f} m on average")
    return 0


if __name__ == "__main__":
    sys.exit(main())
