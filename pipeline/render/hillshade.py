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
`gdaldem hillshade` call there. `fill_strength` optionally mixes in the hero's fill sun and
**preserves that convention exactly** (see `fill_scale`), which is why the composite needs no
change to consume it.
"""

import math
from typing import Any

import numpy as np
import rasterio

from pipeline.raster_io import GTIFF_CREATE, band_window, row_bands
from pipeline.render import cast_shadow

EARTH_RADIUS = 6378137.0  # Web Mercator sphere radius

# The hero's fill sun, ported to the tiles (scene_build.FILL_ROTATION (30, 0, 135) -> 60 deg up
# from the SE; FILL_ANGLE 10; use_shadow off). "Shadowless" used to reproduce for free, because a
# hillshade has no cast shadows at all; since `cast_shadow` landed it is upheld deliberately --
# `per_row_zfactor_hillshade` attenuates the MAIN term only, never this one. That is what keeps a
# shadowed slope on the fill floor instead of dropping to black.
#
# WHY THE TILES NEED IT (measured): a single 45-deg sun on a 15x-exaggerated 305 m grid
# turns the slope term into arctan(15 * gradient), so a 4-deg real slope presents as 46 deg -- past
# the sun -- and the face goes to hillshade 0. That is 12.4% of Sri Lanka's land, 30.5% of the
# Himalaya and **43.7% of the Alps**: flat black slabs carrying no information, and the bimodality
# (p10 = 0, p25 = 85) that reads as harshness. Any fill >= 0.10 drives it to 0.00% everywhere.
# The hero has never had this problem because it has a fill sun, a 12-deg penumbra and a world
# ambient; the tiles copied its main sun and none of the three. See ART.md "Fill sun".
#
# GEOMETRY, NOT AN ART DIAL: the main sun's NW azimuth is a locked cartographic convention
# (ART.md:63) and the fill is its mirror. The STRENGTH is the art lever and lives in
# `shade.KNOBS["fill_strength"]`, beside `alt`, which is likewise consumed at this stage.
FILL_ALTITUDE = 60.0
FILL_AZIMUTH = 135.0


def fill_scale(strength: float, altitude: float, fill_altitude: float = FILL_ALTITUDE) -> float:
    """Factor returning main+fill light to the `flat ground = 255*sin(altitude)` contract.

    On flat ground the main sun reads 255*sin(altitude) and the fill reads 255*sin(fill_altitude),
    so their sum is 255*(sin(altitude) + strength*sin(fill_altitude)); dividing by that ratio lands
    flat ground back on 255*sin(altitude) exactly. That is the whole reason `shade.composite` needs
    no change: its `flat = 255*sin(KNOBS["alt"])` stays correct, and `ambient`/`hi`/`exposure` keep
    their meanings, because 1.0 still means "flat ground" after the port.

    Returns exactly 1.0 at strength 0 -- the bit-identical control, not an approximation of one.
    """
    if strength == 0.0:
        return 1.0
    return (math.sin(math.radians(altitude))
            / (math.sin(math.radians(altitude)) + strength * math.sin(math.radians(fill_altitude))))


def combine_fill(main: np.ndarray, fill: np.ndarray, strength: float, altitude: float,
                 fill_altitude: float = FILL_ALTITUDE) -> np.ndarray:
    """Blend a main and a fill hillshade into one light raster on the flat-ground contract.

    THE one implementation, called by both shade paths. `shade_planet` reaches it through
    `per_row_zfactor_hillshade`; `tile/shade.py`'s gdaldem branch calls it directly on a second
    gdaldem pass. A per-call-site copy of this arithmetic is exactly how the float32 window fix
    reached `composite` and never reached this module

    The fill COMPRESSES rather than brightens: it lifts faces the main sun cannot reach and, via the
    rescale, darkens the ones it can. Measured max output DN therefore FALLS with strength (255 ->
    226 at 0.15 -> 213 at 0.25 on real terrain).

    That is not luck, and it does not depend on the terrain sampled. Bounding both suns by their
    255 maximum simultaneously gives max = 255*(1+s)*sin(alt) / (sin(alt) + s*sin(fill_alt)), which
    is <= 255 exactly when sin(alt) <= sin(fill_alt) -- i.e. **whenever the fill sits at or above
    the main sun**. At 45 vs 60 it cannot overflow for ANY strength. The clip is therefore a
    backstop against one specific future change (dropping the fill BELOW the sun, which would wrap
    the uint8 silently); `tests/test_hillshade.py` pins both that it never engages at production
    geometry and that it does engage for a fill below the sun.
    """
    if strength == 0.0:
        return main
    return np.clip((main + strength * fill) * fill_scale(strength, altitude, fill_altitude),
                   0.0, 255.0)


def _latitude_of_rows(transform, row_indices: np.ndarray) -> np.ndarray:
    """Latitude (degrees) of pixel-row centres from an EPSG:3857 geotransform."""
    merc_y = transform.f + (row_indices + 0.5) * transform.e  # transform.e < 0 (north-up)
    return np.degrees(2.0 * np.arctan(np.exp(merc_y / EARTH_RADIUS)) - math.pi / 2.0)


def hillshade_array(heights: np.ndarray, cellsize: float, zfactor,
                    altitude: float = 45.0, azimuth: "float | np.ndarray" = 315.0) -> np.ndarray:
    """Horn hillshade of `heights` (float, one halo row already padded top+bottom).

    `zfactor` may be a scalar or a column vector broadcastable to the *output* rows
    (i.e. length heights.shape[0]-2). Columns wrap (planet is periodic in longitude).
    `azimuth` (the compass bearing the light comes FROM) may likewise be a scalar or a per-pixel
    array broadcastable to the output shape -- the array form is for non-Mercator grids where
    grid-north diverges from true-north, so holding a fixed TRUE light bearing needs the grid
    azimuth to rotate per pixel (the polar cap; the Mercator tiles pass a scalar).
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
    # A scalar azimuth stays on math.radians so every existing (Mercator) caller is byte-for-byte
    # unchanged; a per-pixel array takes np.radians, cast to heights' dtype first to avoid the same
    # float64-upcast trap the zfactor cast above guards against.
    if isinstance(azimuth, np.ndarray):
        azimuth_math = np.radians(360.0 - np.asarray(azimuth, dtype=heights.dtype) + 90.0)
    else:
        azimuth_math = math.radians(360.0 - azimuth + 90.0)
    slope = np.arctan(zfactor * np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(dz_dy, -dz_dx)
    shaded = 255.0 * (math.cos(zenith) * np.cos(slope)
                      + math.sin(zenith) * np.sin(slope) * np.cos(azimuth_math - aspect))
    return np.clip(shaded, 0.0, 255.0)


def per_row_zfactor_hillshade(height_path, out_path, exaggeration: float = 15.0,
                              altitude: float = 45.0, azimuth: float = 315.0,
                              window_rows: int = 256, fill_strength: float = 0.0,
                              shadow_strength: float = 0.0, shadow_reach_px: int = 0) -> None:
    """Stream a seamless, per-latitude-z hillshade over a whole EPSG:3857 height raster.

    `fill_strength` mixes in the hero's fill sun (see `combine_fill`); 0.0 skips the second
    hillshade entirely and is bit-identical to a no-fill pass. It defaults OFF so the fill is
    opt-in at the call site, matching how `exaggeration`/`altitude`/`azimuth` are already passed
    explicitly by `shade_planet` rather than inherited from a default here.

    The fill rides the SAME haloed block and z-factor as the main sun, so it costs a second
    `hillshade_array` (CPU) and no extra I/O, and window-invariance is unaffected -- both suns see
    identical neighbourhoods.

    `window_rows` is a hard RAM lever, exactly as it is for `shade.composite`: windows are the
    raster's FULL width (131072 px on the planet), so rows are the only dimension that shrinks.
    Measured on the planet: 1024 rows in float64 = 134 Mpx x 8 B = 1.07 GB per array
    before the gradient/slope/aspect temporaries stack on it -> anon peaked **11.6 GB** against a
    12 G cap and forced 122,501 cgroup reclaims. float32 @ 256 halves the dtype and quarters the
    rows (~8x less per array). The precision is free: the output is uint8, and float32 tracks
    float64 to <=1 DN (tests/test_hillshade.py), so the float64 was discarded on the last line.
    Window size does not affect the pixels -- the halo makes any size identical, which
    tests/test_hillshade.py pins at 256/97/1024/4096.

    `shadow_strength` mixes in `cast_shadow.shadow_mask`, attenuating the MAIN sun only (the fill
    stays shadowless, as in the hero) so a shadowed face lands on the fill floor rather than at
    zero. It defaults OFF and is bit-identical to a no-shadow pass at 0.0.

    A cast shadow is the one term here that is NOT local, so it widens the halo from 1 row to
    `shadow_reach_px`: a window's top rows must see the real terrain casting onto them, or every
    window boundary becomes a seam. That is the whole reason the halo was ever a concept, applied
    at the depth this term actually needs -- window-invariance still holds, at the cost of reading
    `shadow_reach_px` extra rows per window instead of 1.
    """
    with rasterio.open(height_path) as src:
        height, width = src.height, src.width
        cellsize = abs(src.transform.a)
        # dict[str, Any]: GDAL creation options are a heterogeneous bag, and `**profile`
        # otherwise hands rasterio.open's bool-typed `sharing`/`thread_safe` a `str | int | None`.
        profile: dict[str, Any] = dict(
            src.profile, driver="GTiff", count=1, dtype="uint8", nodata=None,
            BIGTIFF="YES", num_threads="ALL_CPUS", **GTIFF_CREATE)
        halo = max(1, shadow_reach_px) if shadow_strength != 0.0 else 1
        with rasterio.open(out_path, "w", **profile) as dst:
            for row0, row1 in row_bands(height, window_rows):
                read0, read1 = max(0, row0 - halo), min(height, row1 + halo)
                read_window = band_window(width, read0, read1)
                block = src.read(1, window=read_window).astype(np.float32)
                block = np.where(block < -1e4, 0.0, block)  # DEM/ocean nodata -> flat
                # edge-replicate the missing halo rows at the global top/bottom only
                block = np.pad(block, ((halo - (row0 - read0), halo - (read1 - row1)), (0, 0)),
                               mode="edge")
                out_rows = np.arange(row0, row1)
                latitude = np.clip(_latitude_of_rows(src.transform, out_rows), -85.05, 85.05)
                zfactor = (exaggeration / np.cos(np.radians(latitude))).reshape(-1, 1)
                # hillshade_array's contract is exactly ONE halo row; a deeper shadow halo is
                # trimmed back to it here rather than by widening that function's contract.
                local = block if halo == 1 else block[halo - 1:block.shape[0] - (halo - 1)]
                shaded = hillshade_array(local, cellsize, zfactor, altitude, azimuth)
                if shadow_strength != 0.0:
                    block_rows = np.arange(row0 - halo, row1 + halo)
                    block_latitude = np.clip(_latitude_of_rows(src.transform, block_rows),
                                             -85.05, 85.05)
                    block_zfactor = (exaggeration
                                     / np.cos(np.radians(block_latitude))).reshape(-1, 1)
                    shadow = cast_shadow.shadow_mask(block, block_zfactor, cellsize, altitude,
                                                     azimuth, shadow_reach_px)
                    shaded = shaded * (1.0 - shadow_strength * shadow[halo:halo + (row1 - row0)])
                if fill_strength != 0.0:
                    fill = hillshade_array(local, cellsize, zfactor, FILL_ALTITUDE, FILL_AZIMUTH)
                    shaded = combine_fill(shaded, fill, fill_strength, altitude)
                dst.write(np.rint(shaded).astype("uint8"), 1,
                          window=band_window(width, row0, row1))
