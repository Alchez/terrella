"""Tile snow layer: NSIDC-0791 snow persistence -> latitude-ramped soft alpha.

Replaces the WorldCover class-70 permanent-ice mask (permanent ice only -> bare mid/high-latitude
mountains). Persistence (observed MODIS climatology, water years 2001-2023, 0.01 deg) drives a
smoothstep alpha so snow margins fade and take the hillshade instead of a hard cartoon edge. The
persistence cutoff ramps with |latitude| (0.40 at 45 deg -> 0.60 at 63 deg) because high latitudes
are seasonally snow-covered over huge areas, and a fixed cutoff floods them. Validated on five
stress regions;
"""

import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from scipy import ndimage

from pipeline import datasets, mercator, vector_raster
from pipeline.raster_io import band_window, row_bands


def persistence_nc(sp_nc: Path | None = None) -> Path:
    """The NSIDC-0791 persistence NetCDF, or the override a caller passed.

    RESOLVED HERE RATHER THAN IN A DEFAULT ARGUMENT, which is evaluated at import and froze the
    store exactly as the module-level constant it replaced did.
    """
    return datasets.snow_persistence() if sp_nc is None else sp_nc
SP_VAR = "snow_persistence_climatology"  # continuous (9999 levels); the day-quantized sibling is snow_persistence
SP_SCALE = 1e-4     # unpacked persistence = 0.0001 x packed (valid 0..10000 -> 0..1 fraction)
SP_FILL = 65535     # packed fill (ocean / no valid MODIS observation)
# The RGI path and its layer name live in `acquire.download_rgi`, which writes them; the two burns
# below take them as arguments. A second spelling here agreed with the acquirer until one moved.

# persistence cutoff ramps with |latitude|, anchored to the two validated endpoints
RAMP_LAT_LO, RAMP_LAT_HI = 45.0, 63.0
RAMP_LOW_MIN, RAMP_LOW_MAX = 0.40, 0.60
RAMP_BAND = 0.32          # high = low + band (soft-alpha width)


def _run(cmd):
    subprocess.run([str(part) for part in cmd], check=True, capture_output=True)


def _warp_persistence_direct(bounds, width, height, out_path, sp_nc=None):
    """One gdalwarp of SP onto a Web-Mercator grid, storing the RAW PACKED Float32.

    bounds = (left, bottom, right, top) in EPSG:3857. -srcnodata excludes the 65535 fill from the
    bilinear kernel so it cannot bleed a white fringe onto coastlines where fill borders land.
    """
    left, bottom, right, top = bounds
    sub = f'NETCDF:"{persistence_nc(sp_nc)}":{SP_VAR}'
    _run(["gdalwarp", "-overwrite", "-q", "-s_srs", "EPSG:4326", "-t_srs", "EPSG:3857",
          "-srcnodata", str(SP_FILL), "-dstnodata", str(SP_FILL),
          "-te", repr(left), repr(bottom), repr(right), repr(top),
          "-ts", str(width), str(height), "-r", "bilinear", "-ot", "Float32",
          "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=YES",
          sub, str(out_path)])
    return out_path


def warp_persistence_raster(bounds, width, height, out_path, sp_nc=None, band_rows=None):
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


def warp_persistence(bounds, width, height, out_path, sp_nc=None):
    """Warp SP and return persistence as a float64 array in 0..1 (raster + unpack) -- thin wrapper.

    The region path (shade.py) calls this; kept byte-for-byte by delegating to the two halves it
    was split into, so its output is unchanged.
    """
    warp_persistence_raster(bounds, width, height, out_path, sp_nc=sp_nc)
    with rasterio.open(out_path) as dataset:
        return unpack_persistence(dataset.read(1))


def rasterize_glaciers_raster(bounds, width, height, out_path, gpkg, layer):
    """Burn RGI 7.0 glacier polygons to a Web-Mercator 0/1 Byte raster (None if RGI absent).

    Crisp permanent ice that a 1 km persistence field blurs (glacier tongues) or misses (small
    glaciers). Does NOT read the result back -- a whole-planet Byte read would be ~12 GB; the
    composite reads window slices. TILED/DEFLATE keep the mostly-empty planet mask tiny on disk and
    cheap to read windowed. Unlinks first because gdal_rasterize opens an existing target in UPDATE
    mode and would burn onto its old contents. Returns out_path, or None when RGI isn't downloaded
    yet (persistence-only fallback).

    `gpkg` and `layer` are REQUIRED and come from `download_rgi`, exactly as the rock burn below
    takes its pair from `download_add_rock`. They were a module constant and a literal here, and a
    DEFAULT is the half that bites: it binds the value at def time, so redirecting the data store
    afterwards leaves this burn reading the path from before the redirect.
    """
    gpkg = Path(gpkg)
    if not gpkg.exists():
        return None
    left, bottom, right, top = bounds
    Path(out_path).unlink(missing_ok=True)
    _run(["gdal_rasterize", "-q", "-burn", "1", "-init", "0", "-ot", "Byte", "-of", "GTiff",
          "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=YES",
          "-l", layer, "-te", repr(left), repr(bottom), repr(right), repr(top),
          "-ts", str(width), str(height), str(gpkg), str(out_path)])
    return out_path


def rasterize_antarctic_rock(bounds, width, height, out_path, gpkg, layer):
    """Burn SCAR ADD's outcrop polygons to a Web-Mercator 0/1 Byte raster, refusing an empty result.

    The mask `antarctic_snow_mask` subtracts. `gpkg` and `layer` are REQUIRED rather than defaulted
    to the acquirer's constants: a default binds at import, so a caller that redirects the data root
    would be answered with the path from before the redirect -- `perennial_ice.CapIce.sources`
    records that trap at length, and the fix there was the same one.

    AN EMPTY BURN RAISES HERE, WHERE THE GLACIER BURN BESIDE IT LETS ONE THROUGH, and the asymmetry
    is about what an empty answer LOOKS like downstream rather than about being stricter. A missing
    glacier mask shows: the union loses its crisp tongues and the composite prints a skip line. A
    rock mask of zeros subtracts nothing from a rule that already covers the whole continent, which
    is exactly the look that shipped before this layer existed -- no missing file, no changed
    consumer, and no eye that can tell it from "there is no exposed rock in Antarctica".

    `vector_raster` owns the argv and the emptiness scan, but not the reprojection: the acquirer
    reprojects 147 MB of polygons ONCE, so `burn_onto_grid`'s ogr2ogr step would be a no-op pass over
    the whole file on every build.
    """
    out_path = Path(out_path)
    out_path.unlink(missing_ok=True)
    _run(vector_raster.rasterize_argv(
        Path(gpkg), bounds, width, height, out_path,
        creation_options=("TILED=YES", "COMPRESS=DEFLATE", "BIGTIFF=YES"), layer=layer))
    if vector_raster.drew_nothing(out_path):
        raise vector_raster.NothingBurnt(
            f"Antarctic rock outcrop rasterised to nothing over {bounds}. gdal_rasterize succeeded, "
            f"so this is geometry that missed the grid rather than a GDAL failure: check that "
            f"{gpkg} is in EPSG:3857 and that {layer!r} is the layer holding the polygons."
        )
    return out_path


def rasterize_glaciers(bounds, width, height, out_path, gpkg, layer):
    """Burn RGI glaciers and return the 0/1 mask array (None if RGI absent) -- thin wrapper.

    The region path (shade.py) calls this; kept byte-for-byte by delegating to
    rasterize_glaciers_raster and reading the (region-sized) result back.
    """
    if rasterize_glaciers_raster(bounds, width, height, out_path, gpkg, layer) is None:
        return None
    with rasterio.open(out_path) as dataset:
        return dataset.read(1)


def latitude_per_row(top, bottom, height):
    """Latitude of each pixel-row centre for a Web-Mercator grid spanning [bottom, top] metres."""
    rows = np.arange(height)
    merc_y = top - (rows + 0.5) * (top - bottom) / height
    # The second of the two copies this module and hillshade.py each used to carry, constant and
    # formula alike. One home now, and it is the PROJECTION's sphere rather than a body's: the
    # grid is EPSG:3857 for every planet, so this number is the same on all of them.
    return mercator.latitude_at(merc_y, mercator.WEB_MERCATOR_RADIUS_M)


def ramp_thresholds(latitude):
    """Per-row (low, high) persistence thresholds ramped by |latitude|."""
    frac = np.clip((np.abs(latitude) - RAMP_LAT_LO) / (RAMP_LAT_HI - RAMP_LAT_LO), 0.0, 1.0)
    low = RAMP_LOW_MIN + frac * (RAMP_LOW_MAX - RAMP_LOW_MIN)
    return low, low + RAMP_BAND


def snow_alpha(persistence, top, bottom):
    """Soft snow alpha (0..1) from persistence, with the latitude-ramped threshold per row.

    SOFT IN PERSISTENCE, WHICH IS NOT THE AXIS THE STAIRCASE IS ON. `feather` is the companion that
    softens it in PIXELS, and every caller of this wants both: a value ramp can only spread an edge
    as far as the field's own gradient carries it, and between two 0.01 degree cells that is one
    cell, hard-cornered at the cell boundary. The two are separate functions because they need
    different things — this one the window's latitude span, that one the grid's ground resolution —
    and because the cap tier reproduces this ramp on an AEQD grid where the per-row latitude here
    would be wrong, while sharing `feather` unchanged.
    """
    height = persistence.shape[0]
    low, high = ramp_thresholds(latitude_per_row(top, bottom, height))
    low = low.reshape(-1, 1)
    high = high.reshape(-1, 1)
    fraction = np.clip((persistence - low) / np.maximum(1e-6, high - low), 0.0, 1.0)
    return fraction * fraction * (3.0 - 2.0 * fraction)


#: Ground size of one NSIDC-0791 cell ALONG LATITUDE, in metres: 0.01 degree of arc on the source's
#: own sphere. Constant at every latitude, which is the half that matters — the cell's WIDTH shrinks
#: with cos(latitude) and its height does not, so on a render grid whose pixel is square in ground
#: metres the cell grows steadily taller than it is wide as you go north. That anisotropy is the
#: staircase: 3.6 render px wide at every latitude, but 5.5 px tall at 49N and 20 px at 79.5N.
SOURCE_CELL_M = 1113.2

#: Blur radius as a fraction of that cell, so the feather scales with the artefact instead of with
#: a pixel count. RATIFIED on a polar A/B against the unfeathered arm; the number is a look
#: judgement and re-tuning it is the maintainer's call, not a free parameter.
SOFTEN_FRACTION = 0.35

#: How far sigma may drift inside one filtered band, as a fraction of the band's own sigma.
#: SET BY WHAT IS INVISIBLE, NOT BY WHAT IS CHEAP: sigma varies down a Mercator window because the
#: ground metre does, and filtering a whole window at one sigma puts a STEP in the blur radius at
#: every window join — 17.5% across a 4096-row block join at 79.5N, which is the shape and roughly
#: the size of the relief-scaling seam this project is already fighting. Banding at 2% turns that
#: step into a ladder of steps too small to find.
SOFTEN_BAND_TOLERANCE = 0.02

#: How many sigmas of real data each band is filtered with above and below it, so a band's result is
#: the same as if the whole array had been filtered at that sigma. Beyond 3 sigma a Gaussian holds
#: under 1.2% of its mass, which is below the tolerance above.
SOFTEN_HALO_SIGMAS = 3


def source_cell_sigma_px(ground_metres_per_px):
    """Blur radius in pixels that spreads an edge over `SOFTEN_FRACTION` of one source cell.

    Takes GROUND metres per pixel, never map metres, and takes it rather than deriving it: the two
    grids that call this are a Web-Mercator window (per row, varying) and an AEQD cap (one scalar
    for the disc), and only the caller knows which it is holding. `CapIceInputs.ground_metres_per_px`
    carries the same quantity for the same reason, and records what a producer that derived it from
    map units got wrong.

    Scalar in, scalar out; array in, array out.
    """
    return SOFTEN_FRACTION * SOURCE_CELL_M / np.maximum(ground_metres_per_px, 1e-6)


def _bands(sigma: np.ndarray) -> list[tuple[int, int]]:
    """Row ranges over which `sigma` is constant to within `SOFTEN_BAND_TOLERANCE`.

    Greedy from the top: a band extends while every row in it stays inside the tolerance of the
    band's first row, which bounds the error against the band's own filter sigma rather than
    against a neighbour's. Returns whole-array coverage with no gaps, so the caller never has to
    check that it filtered every row.
    """
    bands: list[tuple[int, int]] = []
    start = 0
    while start < sigma.size:
        reference = sigma[start]
        end = start + 1
        while (end < sigma.size
               and abs(sigma[end] - reference) <= SOFTEN_BAND_TOLERANCE * reference):
            end += 1
        bands.append((start, end))
        start = end
    return bands


def soften_source_cells(alpha, ground_metres_per_px):
    """Blur a snow alpha at the source's own cell scale, so its edge stops reading as a staircase.

    NOT `mars_ice.feather_alpha`, WHICH IS A DIFFERENT LAW AND WAS NEARLY GIVEN THIS NAME. That one
    spreads a DRAWN polygon boundary a fixed 10 ground km outward to anti-alias linework that has no
    raster behind it; this one softens a RASTER's own cell quantisation by a fraction of that cell,
    so its distance is the source's and not a chosen one. Same argument, adjacent call sites in
    `perennial_ice`, opposite questions — which is exactly when one word for two concepts starts
    costing decisions.

    APPLIED AFTER THE THRESHOLD, NOT BEFORE. Blurring persistence and then thresholding would move
    the edge as well as soften it, because the threshold is non-linear in the field; blurring the
    alpha moves nothing and only softens. It is also what the ratified arm did, and the ratified
    thing is an image.

    `ground_metres_per_px` is a scalar for a grid of uniform resolution (an AEQD cap) or one value
    per ROW for a Mercator window, where the ground metre shrinks with cos(latitude) and sigma
    therefore grows northward. A per-row sigma has no single-call form in `ndimage`, so the array
    is filtered in latitude bands narrow enough that one sigma serves the whole band; each band is
    filtered with a halo of real rows above and below it, so the result inside the band is what a
    whole-array filter at that sigma would have produced and the band edges leave no seam of their
    own.

    NO SMALL-SIGMA SHORTCUT, deliberately. An `if sigma > 0.5` guard never fires on Earth's planet
    grid — sigma is 1.27 px at the equator and rises — so it would be inert on the only body that
    has this dataset, while putting a discontinuity in the one place a coarser grid would meet it.
    `gaussian_filter` at sigma 0 is the identity, which is the behaviour the guard was reaching for.
    """
    sigma = source_cell_sigma_px(np.asarray(ground_metres_per_px, dtype=float))
    if sigma.ndim == 0:
        return ndimage.gaussian_filter(alpha, sigma=float(sigma), mode="nearest")
    if sigma.shape != (alpha.shape[0],):
        raise ValueError(f"per-row ground resolution has {sigma.shape} rows for an alpha of "
                         f"{alpha.shape} — one value per row, or a scalar for a uniform grid")

    out = np.empty_like(alpha)
    for start, end in _bands(sigma):
        band_sigma = float(sigma[start])
        halo = int(np.ceil(SOFTEN_HALO_SIGMAS * band_sigma))
        read_start = max(0, start - halo)
        read_end = min(alpha.shape[0], end + halo)
        filtered = ndimage.gaussian_filter(alpha[read_start:read_end], sigma=band_sigma,
                                           mode="nearest")
        out[start:end] = filtered[start - read_start:end - read_start]
    return out


def antarctic_snow_mask(land, latitude, lat_max=-60.0):
    """1.0 where Antarctic land must be forced permanent-ice white, else 0.0 (float32).

    ANTARCTICA'S SNOW DATASET HAS HOLES RATHER THAN BEING ABSENT, and the difference is measured.
    NSIDC-0791 does cover the continent and saturates over it: every band 60-90S reads a median
    persistence of 1.000, with 98-100% of it full white. What it does NOT cover is 9-14% of Antarctic
    land that arrives as CLUSTERED fill, one component alone running to 101,088 px, which
    `unpack_persistence` maps to 0.0. RGI does not answer there either: region 19 is peripheral,
    covering 0.99% of Antarctic land and closing 0.44% of the fill. Left alone those patches render
    as tan blotches inside the ice sheet.

    So the rule closes holes; it does not stand in for a missing measurement. Over the saturating
    86-91% it agrees with the data rather than overriding it. The tile composite and the south cap
    both apply it, and this is the one home so the two agree across the seam.

    `land` is a 2-D boolean. `latitude` is either per-row (1-D, the Mercator tile path) or per-pixel
    (2-D, the AEQD cap); a 1-D array is broadcast down `land`'s columns. The whole Antarctic Peninsula
    is south of -60, so lat_max=-60 covers the continent; the sub-Antarctic islands north of it are
    whitened by RGI region 19 instead, the only dataset that reaches them — South Sandwich is 100%
    SP_FILL, so persistence cannot.

    A PURE RULE, AND THE EXPOSED ROCK IS DELIBERATELY NOT ITS BUSINESS. SCAR ADD's outcrop is a
    `layer_producers.WHITE_EXCLUSIONS` member removed after the whole white union folds, in both
    tiers. It briefly took a `rock` argument here instead, and that placement put a negative inside
    one positive claim: every other white source re-claimed the pixel in the next operation, which
    cost the outcrop 63% of its subtraction against saturated NSIDC persistence.

    The direction is still the design though, and belongs with the data rather than with the fold.
    A union of "where a dataset says ice" needs a data-availability branch, and the boundary between
    "the dataset answers here" and "the rule answers here" is a hard edge across the ice shelves --
    which is what the superseded MODIS arm drew, as thin tan outlines. Removing rock from a rule that
    already covers the whole continent has no such boundary anywhere.
    """
    cold = np.asarray(latitude) < lat_max
    if cold.ndim == 1:
        cold = cold[:, None]
    return (np.asarray(land) & cold).astype(np.float32)
