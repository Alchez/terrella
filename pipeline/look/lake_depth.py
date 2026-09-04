"""Tile lake-depth layer: GLOBathy modelled depth -> a per-pixel depth field in metres.

Sits beside snow.py by design. Lake depth is a TINT-ONLY rendering input, never terrain: at
the locked 15x exaggeration a carved lake bed makes Namtso a 1.5 km crater and kills the flat
plate that catches the surrounding mountains' shadows. So, exactly like snow, it
is warped onto the render grid at composite time and never enters the fusion master -- which
is also why a future finer re-fuse would not have to redo any of this.

Epistemics, because they are unusually load-bearing here (measured):
  * The SHAPE is synthetic for every one of GLOBathy's 1,427,688 lakes -- D = l x Dmax / L, a
    cone off a shore-distance transform. No lake bed is ever observed. On the Caspian, the one
    lake with both a survey and trustworthy GEBCO soundings, it correlates just 0.53.
  * The SCALE is a real survey for only ~0.8% of the lakes we render (though 14 of the 15
    deepest), and a random-forest estimate for the rest.
Uniform modelled treatment is the deliberate choice: restricting to surveyed lakes was tested
and rejected because 84.7% of them are in the USA, which would render survey funding as
geology, with the discontinuity falling on the US/Canada border.

The DEM's own water mask defines the shoreline, never GLOBathy's: callers must zero this
field off watermask class 2, which both keeps rivers flat (river depth was rejected outright
-- no global bed data exists) and makes GLOBathy's HydroLAKES-registered polygons degrade
gracefully to today's flat tint wherever they disagree with the WBM.
"""

import math
import subprocess

import numpy as np
import rasterio

from pipeline.acquire.extract_globathy import lake_vrt
from pipeline.look import palette

GLOBATHY_NODATA = -9999.0

#: Depth-to-ramp-position mapping for inland water, and the one survivor of the deleted shader's
#: knobs. It outlived them because the HERO reads it: `render/lake_mask.py` bakes this curve into
#: the mask Blender displaces from, so hero and tile cannot disagree about it.
LAKE_CURVE = "log1p"


def _run(cmd):
    subprocess.run([str(part) for part in cmd], check=True, capture_output=True)


def lake_position(depth, curve):
    """Lake depth (m below surface) -> 0..1 along the lake ramp.

    This curve is the honesty/legibility dial, and the two pull against each other. The median
    lake is 11.2 m deep while Baikal is 1642 -- three orders of magnitude -- so a LINEAR axis
    parks 99% of lakes in the first 2% of the ramp and shows nothing. LOG1P spreads them
    (median -> 0.34) but hands most of the ramp to shallow water, which is exactly where
    GLOBathy's cone is least trustworthy (on the Caspian it claims 155 m where the truth is
    under 20 m, measured), so it also maximises the visibility of the layer's worst
    error. SQRT (median -> 0.08) is the conservative middle. Judge on renders, not in the
    abstract.
    """
    if curve == "log1p":
        # Clamped like the others: LAKE_MAX_M is Baikal, so nothing should exceed it today,
        # but an unclamped log1p returns >1 for anything that does -- one re-tune of
        # LAKE_MAX_M to a shallower cap away from indexing off the end of the ramp.
        return (np.log1p(np.clip(depth, 0.0, palette.LAKE_MAX_M))
                / math.log1p(palette.LAKE_MAX_M))
    if curve == "sqrt":
        return np.sqrt(np.clip(depth, 0.0, palette.LAKE_MAX_M) / palette.LAKE_MAX_M)
    if curve == "linear":
        return np.clip(depth, 0.0, palette.LAKE_MAX_M) / palette.LAKE_MAX_M
    raise ValueError(f"unknown LAKE_CURVE {curve!r} (log1p | sqrt | linear)")


def warp_depth(bounds, width, height, out_path, vrt=None):
    """Warp GLOBathy onto a Web-Mercator grid; return depth in metres, 0 where there is none.

    bounds = (left, bottom, right, top) in EPSG:3857. Bilinear, not nearest: depth is a
    continuous field, unlike the class codes beside it (a 2 next to a 0 is not a 1, but 40 m
    next to 0 m really is 20 m). `-srcnodata` keeps the -9999 fill out of the resampling
    kernel so it cannot bleed a false trench across a shoreline.

    Returns None when the VRT has not been built, so shading still runs flat-water-only --
    the same contract as snow.rasterize_glaciers when RGI is missing.
    """
    vrt = vrt or lake_vrt()
    if not vrt.exists():
        return None
    left, bottom, right, top = bounds
    _run(["gdalwarp", "-overwrite", "-q", "-s_srs", "EPSG:4326", "-t_srs", "EPSG:3857",
          "-srcnodata", str(GLOBATHY_NODATA), "-dstnodata", "0",
          "-te", repr(left), repr(bottom), repr(right), repr(top),
          "-ts", str(width), str(height), "-r", "bilinear", "-ot", "Float32",
          str(vrt), str(out_path)])
    with rasterio.open(out_path) as dataset:
        depth = dataset.read(1).astype("float32")
    return np.where(np.isfinite(depth) & (depth > 0.0), depth, 0.0).astype("float32")


def warp_depth_raster(bounds, width, height, out_path, vrt=None):
    """Warp GLOBathy onto a whole Web-Mercator grid, leaving the result on disk.

    The planet-tier twin of `warp_depth` above, which hands the array back for the region path.
    bounds = (left, bottom, right, top) in EPSG:3857. No `-s_srs`, unlike the NetCDF and GeoTIFF
    warps beside it: the VRT carries its own. Tiled/DEFLATE/BIGTIFF because the target is a global
    grid, which is the whole difference between the two.
    """
    vrt = vrt or lake_vrt()
    left, bottom, right, top = bounds
    _run(["gdalwarp", "-q", "-t_srs", "EPSG:3857",
          "-te", repr(left), repr(bottom), repr(right), repr(top),
          "-ts", str(width), str(height),
          "-srcnodata", str(GLOBATHY_NODATA), "-dstnodata", "0",
          "-r", "bilinear", "-ot", "Float32", "-co", "TILED=YES",
          "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=YES",
          "-co", "NUM_THREADS=ALL_CPUS", vrt, out_path])
    return out_path


def lakes_only(depth, watercode):
    """Zero the depth field off watermask class 2 (inland lake).

    Class 3 (river) stays flat by decision, and class 1 (ocean) must never be touched -- the
    Caspian is class 1 since the re-fuse precisely so GEBCO's measured bathymetry
    beats GLOBathy's cone there, and this is what enforces that.
    """
    if depth is None:
        return None
    return np.where(watercode == 2, depth, 0.0).astype("float32")


def inland_water(watercode):
    """Boolean mask of inland water -- watermask class 2 (lake) OR 3 (river) -- selecting the
    flat WATER_RGB / lake-ramp branch of the composite.

    Class 1 (ocean) is deliberately EXCLUDED: it is sea, coloured by the depth ramp, the mirror
    of lakes_only's rule above. This is THE one implementation of that decision, shared by both
    shade paths and the polar cap so a per-call-site copy cannot drift: `watercode.astype(bool)`
    is the tempting shortcut and is wrong -- it catches class 1 and paints the whole ocean flat
    WATER_RGB over the bathymetry (the cap's 'disc glow').
    """
    return (watercode == 2) | (watercode == 3)
