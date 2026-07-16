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
from typing import Any

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
    Returns float DN in [0, 255], flat ground = 255*sin(altitude), in `heights`' own dtype.
    """
    # Match zfactor to heights' dtype BEFORE it touches the arrays. Callers naturally build it
    # from np.cos(latitude), which is float64, and under NEP 50 a float64 array silently
    # promotes a float32 computation back to float64 -- restoring every byte a float32 caller
    # meant to save, while every colour assertion still passes. Latitude itself must stay
    # float64 upstream (merc_y ~2e7 needs the mantissa); only this ratio comes down.
    zfactor = np.asarray(zfactor, dtype=heights.dtype)
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
                              window_rows: int = 256) -> None:
    """Stream a seamless, per-latitude-z hillshade over a whole EPSG:3857 height raster.

    `window_rows` is a hard RAM lever, exactly as it is for `shade.composite`: windows are the
    raster's FULL width (131072 px on the planet), so rows are the only dimension that shrinks.
    Measured 2026-07-16 on the planet: 1024 rows in float64 = 134 Mpx x 8 B = 1.07 GB per array
    before the gradient/slope/aspect temporaries stack on it -> anon peaked **11.6 GB** against a
    12 G cap and forced 122,501 cgroup reclaims. float32 @ 256 halves the dtype and quarters the
    rows (~8x less per array). The precision is free: the output is uint8, and float32 tracks
    float64 to <=1 DN (tests/test_hillshade.py), so the float64 was discarded on the last line.
    Window size does not affect the pixels -- the 1-row halo makes any size identical, which
    tests/test_hillshade.py pins at 256/97/1024/4096.
    """
    with rasterio.open(height_path) as src:
        height, width = src.height, src.width
        cellsize = abs(src.transform.a)
        # dict[str, Any]: GDAL creation options are a heterogeneous bag, and `**profile`
        # otherwise hands rasterio.open's bool-typed `sharing`/`thread_safe` a `str | int | None`.
        profile: dict[str, Any] = dict(
            src.profile, driver="GTiff", count=1, dtype="uint8", nodata=None,
            compress="deflate", tiled=True, blockxsize=512, blockysize=512, BIGTIFF="YES",
            num_threads="ALL_CPUS")
        with rasterio.open(out_path, "w", **profile) as dst:
            for row0 in range(0, height, window_rows):
                row1 = min(height, row0 + window_rows)
                read0, read1 = max(0, row0 - 1), min(height, row1 + 1)
                read_window = Window(0, read0, width,  # pyright: ignore[reportCallIssue] — rasterio untyped, attrs init invisible
                                     read1 - read0)
                block = src.read(1, window=read_window).astype(np.float32)
                block = np.where(block < -1e4, 0.0, block)  # DEM/ocean nodata -> flat
                # edge-replicate the missing halo row at the global top/bottom only
                block = np.pad(block, ((1 if read0 == row0 else 0, 1 if read1 == row1 else 0),
                                       (0, 0)), mode="edge")
                out_rows = np.arange(row0, row1)
                latitude = np.clip(_latitude_of_rows(src.transform, out_rows), -85.05, 85.05)
                zfactor = (exaggeration / np.cos(np.radians(latitude))).reshape(-1, 1)
                shaded = hillshade_array(block, cellsize, zfactor, altitude, azimuth)
                write_window = Window(0, row0, width,  # pyright: ignore[reportCallIssue] — rasterio untyped, attrs init invisible
                                      row1 - row0)
                dst.write(np.rint(shaded).astype("uint8"), 1, window=write_window)
