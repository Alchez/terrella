#!/usr/bin/env python3
"""Custom hillshade with a per-row (latitude-varying) z-factor for Web Mercator grids.

`gdaldem hillshade` takes a single scalar z-factor. A Web-Mercator planet needs the
z-factor to vary by latitude — `relief.mercator_zfactor(lat, EXAG) = EXAG / cos(lat)` —
so the physical vertical exaggeration (the hero's 15x) is constant on the ground at every
latitude rather than over-exaggerated at the equator and flat at the poles. Using one
global z (the old planet path) blew out the tropics; shading in latitude *bands* would fix
the exaggeration but reintroduce a seam at every band edge.

This reproduces the Horn (1981) hillshade `gdaldem` uses, but with the z-factor as a
per-row vector, and streams it over the whole raster in full-width horizontal windows with
a one-row halo. Full width => no longitude seams; the halo => each output row is computed
from its true vertical neighbours, so the result is bit-identical to a single in-RAM pass
=> no latitude seams either. Validated to match `gdaldem hillshade` (max |diff| <= 1 DN)
when the z-factor is held constant.

Output is a uint8 hillshade on the same grid, where flat ground = 255*sin(altitude) — the
exact convention `tile/shade.py`'s composite already divides by, so it is a drop-in for the
`gdaldem hillshade` call there.
"""

import math

import numpy as np
import rasterio
from rasterio.windows import Window

EARTH_RADIUS = 6378137.0  # Web Mercator sphere radius


def _latitude_of_rows(transform, row_indices: np.ndarray) -> np.ndarray:
    """Latitude (degrees) of pixel-row centres from an EPSG:3857 geotransform."""
    merc_y = transform.f + (row_indices + 0.5) * transform.e  # transform.e < 0 (north-up)
    return np.degrees(2.0 * np.arctan(np.exp(merc_y / EARTH_RADIUS)) - math.pi / 2.0)


def hillshade_array(heights: np.ndarray, cellsize: float, zfactor,
                    altitude: float = 45.0, azimuth: float = 315.0) -> np.ndarray:
    """Horn hillshade of `heights` (float, one halo row already padded top+bottom).

    `zfactor` may be a scalar or a column vector broadcastable to the *output* rows
    (i.e. length heights.shape[0]-2). Columns wrap (planet is periodic in longitude).
    Returns float DN in [0, 255], flat ground = 255*sin(altitude).
    """
    padded = np.pad(heights, ((0, 0), (1, 1)), mode="wrap")
    a, b, c = padded[:-2, :-2], padded[:-2, 1:-1], padded[:-2, 2:]
    d, f = padded[1:-1, :-2], padded[1:-1, 2:]
    g, h, i = padded[2:, :-2], padded[2:, 1:-1], padded[2:, 2:]
    dz_dx = ((c + 2.0 * f + i) - (a + 2.0 * d + g)) / (8.0 * cellsize)
    dz_dy = ((g + 2.0 * h + i) - (a + 2.0 * b + c)) / (8.0 * cellsize)

    zenith = math.radians(90.0 - altitude)
    azimuth_math = math.radians(360.0 - azimuth + 90.0)
    slope = np.arctan(zfactor * np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(dz_dy, -dz_dx)
    shaded = 255.0 * (math.cos(zenith) * np.cos(slope)
                      + math.sin(zenith) * np.sin(slope) * np.cos(azimuth_math - aspect))
    return np.clip(shaded, 0.0, 255.0)


def per_row_zfactor_hillshade(height_path, out_path, exaggeration: float = 15.0,
                              altitude: float = 45.0, azimuth: float = 315.0,
                              window_rows: int = 1024) -> None:
    """Stream a seamless, per-latitude-z hillshade over a whole EPSG:3857 height raster."""
    with rasterio.open(height_path) as src:
        height, width = src.height, src.width
        cellsize = abs(src.transform.a)
        profile = dict(src.profile, driver="GTiff", count=1, dtype="uint8", nodata=None,
                       compress="deflate", tiled=True, blockxsize=512, blockysize=512,
                       BIGTIFF="YES")
        with rasterio.open(out_path, "w", **profile) as dst:
            for row0 in range(0, height, window_rows):
                row1 = min(height, row0 + window_rows)
                read0, read1 = max(0, row0 - 1), min(height, row1 + 1)
                block = src.read(1, window=Window(0, read0, width, read1 - read0)).astype(np.float64)
                block = np.where(block < -1e4, 0.0, block)  # DEM/ocean nodata -> flat
                # edge-replicate the missing halo row at the global top/bottom only
                block = np.pad(block, ((1 if read0 == row0 else 0, 1 if read1 == row1 else 0),
                                       (0, 0)), mode="edge")
                out_rows = np.arange(row0, row1)
                latitude = np.clip(_latitude_of_rows(src.transform, out_rows), -85.05, 85.05)
                zfactor = (exaggeration / np.cos(np.radians(latitude))).reshape(-1, 1)
                shaded = hillshade_array(block, cellsize, zfactor, altitude, azimuth)
                dst.write(np.rint(shaded).astype("uint8"), 1,
                          window=Window(0, row0, width, row1 - row0))
