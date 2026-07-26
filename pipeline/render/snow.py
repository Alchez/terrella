#!/usr/bin/env python3
"""Tile snow layer: NSIDC-0791 snow persistence -> latitude-ramped soft alpha.

Replaces the WorldCover class-70 permanent-ice mask (permanent ice only -> bare mid/high-latitude
mountains). Persistence (observed MODIS climatology, water years 2001-2023, 0.01 deg) drives a
smoothstep alpha so snow margins fade and take the hillshade instead of a hard cartoon edge. The
persistence cutoff ramps with |latitude| (0.40 at 45 deg -> 0.60 at 63 deg) because high latitudes
are seasonally snow-covered over huge areas, and a fixed cutoff floods them. Validated on five
stress regions; -> HISTORY § Snow source reworked.
"""

import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from pipeline import paths
from pipeline.raster_io import band_window, row_bands

DATA = paths.DATA
SP_NC = DATA / "raw/snow/NSIDC-0791_SP_0.01Deg_WY2001-2023_V01.0.nc"
SP_VAR = "snow_persistence_climatology"  # continuous (9999 levels); the day-quantized sibling is snow_persistence
SP_SCALE = 1e-4     # unpacked persistence = 0.0001 x packed (valid 0..10000 -> 0..1 fraction)
SP_FILL = 65535     # packed fill (ocean / no valid MODIS observation)
RGI_GPKG = DATA / "raw/rgi/rgi7_g_3857.gpkg"  # RGI 7.0 glaciers merged to EPSG:3857 (layer 'glaciers')

# persistence cutoff ramps with |latitude|, anchored to the two validated endpoints
RAMP_LAT_LO, RAMP_LAT_HI = 45.0, 63.0
RAMP_LOW_MIN, RAMP_LOW_MAX = 0.40, 0.60
RAMP_BAND = 0.32          # high = low + band (soft-alpha width)
EARTH_RADIUS = 6378137.0  # Web Mercator sphere radius


def _run(cmd):
    subprocess.run([str(part) for part in cmd], check=True, capture_output=True)


def _warp_persistence_direct(bounds, width, height, out_path, sp_nc=SP_NC):
    """One gdalwarp of SP onto a Web-Mercator grid, storing the RAW PACKED Float32.

    bounds = (left, bottom, right, top) in EPSG:3857. -srcnodata excludes the 65535 fill from the
    bilinear kernel so it cannot bleed a white fringe onto coastlines where fill borders land.
    """
    left, bottom, right, top = bounds
    sub = f'NETCDF:"{sp_nc}":{SP_VAR}'
    _run(["gdalwarp", "-overwrite", "-q", "-s_srs", "EPSG:4326", "-t_srs", "EPSG:3857",
          "-srcnodata", str(SP_FILL), "-dstnodata", str(SP_FILL),
          "-te", repr(left), repr(bottom), repr(right), repr(top),
          "-ts", str(width), str(height), "-r", "bilinear", "-ot", "Float32",
          "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=YES",
          sub, str(out_path)])
    return out_path


def warp_persistence_raster(bounds, width, height, out_path, sp_nc=SP_NC, band_rows=None):
    """Warp SP onto a Web-Mercator grid in latitude BANDS, storing the RAW PACKED Float32.

    Stores the packed value (0..10000, fill 65535), NOT the 0..1 fraction, on purpose: the composite
    unpacks per window in float64 (`unpack_persistence`) exactly as the old per-window path did, so a
    window slice of this raster is bit-identical to warping that window alone -- storing the unpacked
    Float32 instead would narrow snow_alpha's precision to float32 and break that.

    WHY BANDS, not one whole-grid warp: SP is a COARSE source (~1.1 km / 0.01 deg). A single gdalwarp
    of it to the fine global Web-Mercator target (~305 m) makes gdalwarp DECIMATE the source read --
    the pole-inflated average scale picks a reduced source resolution and applies it everywhere,
    smoothing real snow structure off mountains (measured: Ruapehu 0.756 -> 0.409, snow -> bare land;
    4096-row bands still decimate; -et 0 and -ovr NONE do NOT fix it). A band whose latitude span is
    small keeps the local scale honest, so it reads the source at full resolution -- exactly why the
    old per-window strips were faithful. With band_rows == the composite window height and bands
    aligned to it, each band IS the per-window warp it replaces, so the mosaic is byte-identical to
    the old path by construction. band_rows=None (region path, small grids) is a single direct warp.
    -> HISTORY 2026-07-18.
    """
    left, bottom, right, top = bounds
    if band_rows is None or height <= band_rows:
        return _warp_persistence_direct(bounds, width, height, out_path, sp_nc=sp_nc)

    pixel = (top - bottom) / height  # metres/row; the band bounds walk down from `top` by this
    profile: dict[str, Any] = dict(
        driver="GTiff", width=width, height=height, count=1, dtype="float32",
        crs="EPSG:3857", transform=from_bounds(left, bottom, right, top, width, height),
        nodata=SP_FILL, tiled=True, blockxsize=256, blockysize=256, compress="deflate",
        BIGTIFF="YES")
    band_temp = Path(f"{out_path}.band.tmp.tif")
    with rasterio.open(out_path, "w", **profile) as dst:
        for row0, row1 in row_bands(height, band_rows):
            band_top = top - row0 * pixel
            band_bottom = top - row1 * pixel
            _warp_persistence_direct((left, band_bottom, right, band_top), width, row1 - row0,
                                     band_temp, sp_nc=sp_nc)
            with rasterio.open(band_temp) as src:
                dst.write(src.read(1), 1, window=band_window(width, row0, row1))
    band_temp.unlink(missing_ok=True)
    return out_path


def unpack_persistence(packed):
    """Unpack raw packed persistence (Float32) to a float64 fraction in 0..1.

    Split out of warp_persistence and kept per-window: the composite's snow_alpha runs on this in
    float64, so the unpack MUST return float64 or the final blend shifts sub-DN. SP_FILL (65535,
    ocean / no valid MODIS) maps to 0.0 via the valid mask -- NOT clip(65535 * 1e-4) = 1.0, which
    would paint full snow over every ocean pixel. That masking is exactly what -srcnodata and this
    guard exist to prevent.
    """
    packed = np.asarray(packed, dtype=float)
    valid = np.isfinite(packed) & (packed != SP_FILL)
    return np.clip(np.where(valid, packed, 0.0) * SP_SCALE, 0.0, 1.0)


def warp_persistence(bounds, width, height, out_path, sp_nc=SP_NC):
    """Warp SP and return persistence as a float64 array in 0..1 (raster + unpack) -- thin wrapper.

    The region path (shade.py) calls this; kept byte-for-byte by delegating to the two halves it
    was split into, so its output is unchanged.
    """
    warp_persistence_raster(bounds, width, height, out_path, sp_nc=sp_nc)
    with rasterio.open(out_path) as dataset:
        return unpack_persistence(dataset.read(1))


def rasterize_glaciers_raster(bounds, width, height, out_path, rgi=RGI_GPKG):
    """Burn RGI 7.0 glacier polygons to a Web-Mercator 0/1 Byte raster (None if RGI absent).

    Crisp permanent ice that a 1 km persistence field blurs (glacier tongues) or misses (small
    glaciers). Does NOT read the result back -- a whole-planet Byte read would be ~12 GB; the
    composite reads window slices. TILED/DEFLATE keep the mostly-empty planet mask tiny on disk and
    cheap to read windowed. Unlinks first because gdal_rasterize opens an existing target in UPDATE
    mode and would burn onto its old contents. Returns out_path, or None when RGI isn't downloaded
    yet (persistence-only fallback).
    """
    if not rgi.exists():
        return None
    left, bottom, right, top = bounds
    Path(out_path).unlink(missing_ok=True)
    _run(["gdal_rasterize", "-q", "-burn", "1", "-init", "0", "-ot", "Byte", "-of", "GTiff",
          "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=YES",
          "-l", "glaciers", "-te", repr(left), repr(bottom), repr(right), repr(top),
          "-ts", str(width), str(height), str(rgi), str(out_path)])
    return out_path


def rasterize_glaciers(bounds, width, height, out_path, rgi=RGI_GPKG):
    """Burn RGI glaciers and return the 0/1 mask array (None if RGI absent) -- thin wrapper.

    The region path (shade.py) calls this; kept byte-for-byte by delegating to
    rasterize_glaciers_raster and reading the (region-sized) result back.
    """
    if rasterize_glaciers_raster(bounds, width, height, out_path, rgi=rgi) is None:
        return None
    with rasterio.open(out_path) as dataset:
        return dataset.read(1)


def latitude_per_row(top, bottom, height):
    """Latitude of each pixel-row centre for a Web-Mercator grid spanning [bottom, top] metres."""
    rows = np.arange(height)
    merc_y = top - (rows + 0.5) * (top - bottom) / height
    return np.degrees(2.0 * np.arctan(np.exp(merc_y / EARTH_RADIUS)) - math.pi / 2.0)


def ramp_thresholds(latitude):
    """Per-row (low, high) persistence thresholds ramped by |latitude|."""
    frac = np.clip((np.abs(latitude) - RAMP_LAT_LO) / (RAMP_LAT_HI - RAMP_LAT_LO), 0.0, 1.0)
    low = RAMP_LOW_MIN + frac * (RAMP_LOW_MAX - RAMP_LOW_MIN)
    return low, low + RAMP_BAND


def snow_alpha(persistence, top, bottom):
    """Soft snow alpha (0..1) from persistence, with the latitude-ramped threshold per row."""
    height = persistence.shape[0]
    low, high = ramp_thresholds(latitude_per_row(top, bottom, height))
    low = low.reshape(-1, 1)
    high = high.reshape(-1, 1)
    fraction = np.clip((persistence - low) / np.maximum(1e-6, high - low), 0.0, 1.0)
    return fraction * fraction * (3.0 - 2.0 * fraction)


def antarctic_snow_mask(land, latitude, lat_max=-60.0):
    """1.0 where Antarctic land must be forced permanent-ice white, else 0.0 (float32).

    Antarctica has no snow dataset in this pipeline: NSIDC-0791 persistence is NH-only and RGI region
    19 is excluded, so `snow_alpha` and the glacier union are both zero over the continent -- left alone
    it would render on the tan LAND ramp. The tile composite and the south cap both force it white by a
    latitude+land rule instead, and this is the one home for that rule so the two agree across the seam.

    `land` is a 2-D boolean. `latitude` is either per-row (1-D, the Mercator tile path) or per-pixel
    (2-D, the AEQD cap); a 1-D array is broadcast down `land`'s columns. The whole Antarctic Peninsula
    is south of -60, so lat_max=-60 covers the continent; only tiny sub-Antarctic islands north of it
    stay bare (deferred RGI-19 polish).
    """
    cold = np.asarray(latitude) < lat_max
    if cold.ndim == 1:
        cold = cold[:, None]
    return (np.asarray(land) & cold).astype(np.float32)
