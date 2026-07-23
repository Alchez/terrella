#!/usr/bin/env python3
"""Tile sea-ice layer: OSI SAF ice-frequency climatology -> soft white alpha over the sea.

The sea-side mirror of pipeline/render/snow.py. Where snow drapes persistent white over LAND by a
persistence-driven alpha, sea ice drapes translucent white over the SEA (the bathymetry showing
through at the thinning edge) by a frequency-driven alpha. The two share the composite's blend; the
only structural difference downstream is the mask -- ice alpha is gated on `ocean`, snow on
`~(ocean|water)` -- applied in shade.composite, not here.

Source: `data/raw/seaice/seaice_frequency_1991-2020_4326.tif`, the annual frequency-of-occurrence
climatology built by pipeline/acquire/download_seaice.py (OSI SAF OSI-450-a, 1991-2020), packed
IDENTICALLY to snow persistence (0..10000 = 0..1, fill 65535) so this warp/unpack is a copy of
snow's. Two deliberate simplifications versus snow:
  - no latitude ramp: sea ice is intrinsically polar, so the field itself says where ice is -- there
    is no mid-latitude seasonal-snow flooding to suppress, so the threshold is a single constant;
  - the alpha is a plain smoothstep on frequency: perennial pack (frequency -> 1) reads opaque white,
    the seasonal fringe (low frequency) fades to translucent so the bathymetry shows through.
"""

import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from pipeline.raster_io import band_window, row_bands

DATA = Path.home() / "projects/maps/data"
SEAICE_SRC = DATA / "raw/seaice/seaice_frequency_1991-2020_4326.tif"
ICE_SCALE = 1e-4    # unpacked frequency = 0.0001 x packed (0..10000 -> 0..1); matches snow.SP_SCALE
ICE_FILL = 65535    # packed fill (land / no valid observation); matches snow.SP_FILL

# frequency -> alpha smoothstep: 0 below ICE_LO, ICE_MAX_ALPHA at ICE_LO + ICE_BAND. A pixel frozen
# for a small fraction of the record shows a faint ice edge; the perennial core saturates at
# ICE_MAX_ALPHA -- kept <1 so even the year-round pack stays a touch translucent and the deep
# bathymetry glows through (the "ocean floor under ice" reading, Rohan 2026-07-19). Art knobs --
# recorded in composite_params so a re-tune restages the composite.
ICE_LO = 0.55
ICE_BAND = 0.40
ICE_MAX_ALPHA = 0.85

# The Southern-Ocean toned fringe (the one home for it, tuned 2026-07-20 on the south cap). Antarctica
# is a continent RINGED by a mostly-seasonal ice belt, not an ice-filled basin, so at full strength the
# climatology reads as a bright halo around the coast. The SH pack is rendered fainter and pulled in: a
# higher lo trims the seasonal fringe, a lower max_alpha lets the bathymetry glow through. Applied south
# of the equator by BOTH the tile composite and the south cap, so the cap<->tile seam matches by
# construction; the Arctic pack keeps the globals above (it IS the subject there). Recorded in
# composite_params, like the globals -- a re-tune must restage the composite.
SH_ICE_LO = 0.62
SH_ICE_MAX_ALPHA = 0.55


def _run(cmd):
    subprocess.run([str(part) for part in cmd], check=True, capture_output=True)


def _warp_seaice_direct(bounds, width, height, out_path, src=SEAICE_SRC):
    """One gdalwarp of the ice-frequency source onto a Web-Mercator grid, storing RAW PACKED Float32.

    bounds = (left, bottom, right, top) in EPSG:3857. -srcnodata excludes the 65535 fill from the
    bilinear kernel so it cannot bleed a white fringe off the ice edge onto open water.
    """
    left, bottom, right, top = bounds
    _run(["gdalwarp", "-overwrite", "-q", "-s_srs", "EPSG:4326", "-t_srs", "EPSG:3857",
          "-srcnodata", str(ICE_FILL), "-dstnodata", str(ICE_FILL),
          "-te", repr(left), repr(bottom), repr(right), repr(top),
          "-ts", str(width), str(height), "-r", "bilinear", "-ot", "Float32",
          "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=YES",
          str(src), str(out_path)])
    return out_path


def warp_seaice_raster(bounds, width, height, out_path, src=SEAICE_SRC, band_rows=None):
    """Warp the ice-frequency source onto a Web-Mercator grid in latitude BANDS (RAW PACKED Float32).

    Stores the packed value (0..10000, fill 65535), NOT the 0..1 fraction, for the same reason as snow
    (`warp_persistence_raster`): the composite unpacks per window in float64, so a window slice of this
    raster must be bit-identical to warping that window alone.

    WHY BANDS: the source is COARSE (0.1 deg, ~11 km) relative to the fine Web-Mercator target
    (~305 m). A single whole-grid gdalwarp decimates the source read (the pole-inflated average scale
    picks a reduced resolution and applies it everywhere), smoothing the ice edge. A band whose
    latitude span is small keeps the local scale honest, so with band_rows == the composite window
    height each band IS the per-window warp it replaces -- byte-identical by construction. See the snow
    analog for the full argument. band_rows=None (region/cap grids) is a single direct warp.
    """
    left, bottom, right, top = bounds
    if band_rows is None or height <= band_rows:
        return _warp_seaice_direct(bounds, width, height, out_path, src=src)

    pixel = (top - bottom) / height  # metres/row; band bounds walk down from `top` by this
    profile: dict[str, Any] = dict(
        driver="GTiff", width=width, height=height, count=1, dtype="float32",
        crs="EPSG:3857", transform=from_bounds(left, bottom, right, top, width, height),
        nodata=ICE_FILL, tiled=True, blockxsize=256, blockysize=256, compress="deflate",
        BIGTIFF="YES")
    band_temp = Path(f"{out_path}.band.tmp.tif")
    with rasterio.open(out_path, "w", **profile) as dst:
        for row0, row1 in row_bands(height, band_rows):
            band_top = top - row0 * pixel
            band_bottom = top - row1 * pixel
            _warp_seaice_direct((left, band_bottom, right, band_top), width, row1 - row0,
                                band_temp, src=src)
            with rasterio.open(band_temp) as src_band:
                dst.write(src_band.read(1), 1, window=band_window(width, row0, row1))
    band_temp.unlink(missing_ok=True)
    return out_path


def unpack_seaice(packed):
    """Unpack raw packed ice frequency (Float32) to a float64 fraction in 0..1.

    Kept per-window and in float64 so `ice_alpha` and the final blend hold their precision. ICE_FILL
    (65535, land / no valid observation) maps to 0.0 via the valid mask -- NOT clip(65535 * 1e-4) = 1,
    which would paint solid ice over every land pixel before the ocean gate even runs.
    """
    packed = np.asarray(packed, dtype=float)
    valid = np.isfinite(packed) & (packed != ICE_FILL)
    return np.clip(np.where(valid, packed, 0.0) * ICE_SCALE, 0.0, 1.0)


def ice_alpha(frequency, ice_lo=None, ice_band=None, ice_max_alpha=None):
    """Soft sea-ice alpha (0..1): a smoothstep on frequency, ice_lo -> ice_lo + ice_band.

    No latitude term (the snow layer needs one; sea ice does not -- the frequency field is already
    zero wherever there is no ice, so there is no seasonal-snow flooding to hold back).

    ice_lo / ice_band / ice_max_alpha default (None) to the module globals -- the Arctic pack (Mercator
    tiles + north cap) uses those. South of the equator both the tile composite and the south cap pass
    the toned SH_ICE_* pair instead, for the reason those constants document.
    """
    ice_lo = ICE_LO if ice_lo is None else ice_lo
    ice_band = ICE_BAND if ice_band is None else ice_band
    ice_max_alpha = ICE_MAX_ALPHA if ice_max_alpha is None else ice_max_alpha
    fraction = np.clip((np.asarray(frequency) - ice_lo) / max(1e-6, ice_band), 0.0, 1.0)
    return ice_max_alpha * fraction * fraction * (3.0 - 2.0 * fraction)


def warp_seaice(bounds, width, height, out_path, src=SEAICE_SRC):
    """Warp ice frequency and return it as a float64 fraction in 0..1 (raster + unpack) -- thin wrapper.

    For whole-grid callers (the cap render, or a region path): delegates to the two halves so the
    stored raster stays identical to a windowed warp.
    """
    warp_seaice_raster(bounds, width, height, out_path, src=src)
    with rasterio.open(out_path) as dataset:
        return unpack_seaice(dataset.read(1))
