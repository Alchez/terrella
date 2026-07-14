#!/usr/bin/env python3
"""Tile snow layer: NSIDC-0791 snow persistence -> latitude-ramped soft alpha.

Replaces the WorldCover class-70 permanent-ice mask (permanent ice only -> bare mid/high-latitude
mountains). Persistence (observed MODIS climatology, water years 2001-2023, 0.01 deg) drives a
smoothstep alpha so snow margins fade and take the hillshade instead of a hard cartoon edge. The
persistence cutoff ramps with |latitude| (0.40 at 45 deg -> 0.60 at 63 deg) because high latitudes
are seasonally snow-covered over huge areas, and a fixed cutoff floods them. Validated on five
stress regions; see PLAN decision log 2026-07-13.
"""

import math
import subprocess
from pathlib import Path

import numpy as np
import rasterio

DATA = Path.home() / "projects/maps/data"
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


def warp_persistence(bounds, width, height, out_path, sp_nc=SP_NC):
    """Warp SP onto a Web-Mercator grid; return persistence as a float array in 0..1.

    bounds = (left, bottom, right, top) in EPSG:3857. -srcnodata excludes the 65535 fill from the
    bilinear kernel so it cannot bleed a white fringe onto coastlines where fill borders land.
    """
    left, bottom, right, top = bounds
    sub = f'NETCDF:"{sp_nc}":{SP_VAR}'
    _run(["gdalwarp", "-overwrite", "-q", "-s_srs", "EPSG:4326", "-t_srs", "EPSG:3857",
          "-srcnodata", str(SP_FILL), "-dstnodata", str(SP_FILL),
          "-te", repr(left), repr(bottom), repr(right), repr(top),
          "-ts", str(width), str(height), "-r", "bilinear", "-ot", "Float32",
          sub, str(out_path)])
    with rasterio.open(out_path) as dataset:
        packed = dataset.read(1).astype(float)
    valid = np.isfinite(packed) & (packed != SP_FILL)
    return np.clip(np.where(valid, packed, 0.0) * SP_SCALE, 0.0, 1.0)


def rasterize_glaciers(bounds, width, height, out_path, rgi=RGI_GPKG):
    """Burn RGI 7.0 glacier polygons onto the Web-Mercator grid -> 0/1 mask (None if RGI absent).

    Crisp permanent ice that a 1 km persistence field blurs (glacier tongues) or misses (small
    glaciers). Unioned into the snow alpha as full snow. Returns None when RGI isn't downloaded
    yet, so shading still works persistence-only.
    """
    if not rgi.exists():
        return None
    left, bottom, right, top = bounds
    _run(["gdal_rasterize", "-q", "-burn", "1", "-init", "0", "-ot", "Byte", "-of", "GTiff",
          "-l", "glaciers", "-te", repr(left), repr(bottom), repr(right), repr(top),
          "-ts", str(width), str(height), str(rgi), str(out_path)])
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
