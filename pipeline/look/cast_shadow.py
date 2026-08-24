"""Directional cast shadows — the one term a hillshade structurally cannot produce.

`gdaldem hillshade` (and our `hillshade.py`) is a purely LOCAL operator: it sees one pixel's
slope and aspect and nothing else, so it cannot know that a ridge 40 km upsun is blocking the
light. Cycles knows, because it traces the ray, and that occlusion is a large part of what reads
as "softness" in the hero renders. This module supplies the missing term for the raster path.

It is deliberately NOT the sky-view factor. `sky_view.horizon_svf` averages the horizon over 16
azimuths to model AMBIENT sky occlusion; this marches ONE azimuth — the sun's — and asks a
different question: is the sun itself blocked?

Two properties are load-bearing and both are inherited, not invented:

* **The shadow attenuates the MAIN sun only.** `hillshade.combine_fill` blends a main and a fill
  sun, and the fill is shadowless by construction (scene_build's FILL_ROTATION has `use_shadow`
  off). Multiplying the main term by `1 - shadow` before the blend therefore reproduces the hero's
  geometry exactly, and — the part that matters — a shadowed slope keeps the fill floor instead of
  going pure black. That is the same invariant the fill-sun port established, where a
  single unfilled sun turned 43.7% of the Alps into flat black slabs.

* **The penumbra is the sun's angular size, not a blur radius.** `palette.SUN_ANGULAR_DIAMETER_DEG`
  is the disc's angular DIAMETER, so the terrain horizon crossing it takes that many degrees to go
  from fully lit to fully occluded. Ramping over half of it either side of the sun altitude gives
  the soft edge for free, with no post-blur and no invented parameter.
"""

import math

import numpy as np

from pipeline.look import palette


def sun_offsets(azimuth: float) -> tuple[float, float]:
    """Per-step (row, column) offset of a march TOWARD the sun, in pixels.

    Compass convention, matching `gdaldem` and `hillshade.py`: azimuth 0 = north, increasing
    clockwise, and it names the direction the light comes FROM. North is -row on a north-up
    raster, east is +column. The production 315 (NW) therefore marches up and to the left.

    Note this is a different convention from `sky_view.horizon_svf`, which uses a mathematical
    azimuth. That is harmless there — it averages all 16 directions, so the convention cancels —
    and would be a silent 90-degree error here, which is why this is a named function with a test
    rather than two inline trig calls.
    """
    radians = math.radians(azimuth)
    return -math.cos(radians), math.sin(radians)


def shadow_mask(heights: np.ndarray, zfactor: float | np.ndarray, m_per_px: float,
                altitude: float = 45.0, azimuth: float = 315.0,
                reach_px: int = 200) -> np.ndarray:
    """Occluded fraction of the sun's disc, 0.0 (fully lit) .. 1.0 (fully shadowed).

    `heights` is metres on a north-up grid of `m_per_px` MAP units, and `zfactor` is what converts
    that mismatch away — it is the vertical exaggeration already divided by the map-unit-to-ground
    ratio, scalar or a column vector of shape (rows, 1) carrying the per-latitude Mercator term.
    Hand it exactly what the hillshade uses, because the two terms must exaggerate identically: a
    shadow cast by 15x relief onto terrain shaded at some other exaggeration is visibly wrong.

    THIS FUNCTION THEREFORE NEEDED NO CHANGE FOR A SECOND BODY, and that is worth stating rather
    than leaving to be rediscovered. The tangent it accumulates is `zfactor * dh / (d * m_per_px)`,
    so a body whose map units are not ground metres is corrected the moment its scale reaches the
    z-factor — the same one number fixing the shading also fixes the shadows, and a second
    correction applied here would double it.

    `reach_px` truncates the march. A shadow longer than this is silently cut short, so it is a
    real quality/cost lever and not a safety limit: cost is O(reach_px) full-array passes. At the
    z8 grid, exaggerated relief casts shadows of order 140 px, and the default leaves headroom.

    Nodata is the caller's job — pass heights with ocean/DEM nodata already flattened, exactly as
    `hillshade.per_row_zfactor_hillshade` does before it shades.

    **The two axes wrap differently, and deliberately.** Columns wrap: a Mercator planet is cyclic
    in longitude, so terrain marching off the western edge genuinely reappears at the eastern one
    (`hillshade_array` already relies on the same property). Rows do NOT wrap — the north pole does
    not shadow the south pole — so they edge-replicate instead. On a REGION rather than the planet
    the column wrap is wrong at the east/west margins, which contaminates a band `reach_px` wide
    there; region callers must crop it.
    """
    if reach_px < 1:
        return np.zeros_like(heights, dtype=np.float32)

    heights = np.asarray(heights, dtype=np.float32)
    exaggerated = heights * np.asarray(zfactor, dtype=np.float32)
    row_step, column_step = sun_offsets(azimuth)
    rows = exaggerated.shape[0]
    # Padded once, outside the loop: every row slice below is then a VIEW, not a copy, and the
    # vertical edge-replication that replaces a wrap costs one small allocation rather than one
    # per step.
    padded = np.pad(exaggerated, ((reach_px, reach_px), (0, 0)), mode="edge")

    # Steepest horizon angle seen so far, as a TANGENT (rise over run) to keep the inner loop free
    # of trig. Starts below any real terrain rather than at zero: a horizon below the marching
    # pixel is not an occluder, and clamping that to zero here would make flat ground look like a
    # horizon at exactly 0 degrees, which is indistinguishable from a sun at the horizon.
    steepest = np.full(exaggerated.shape, -np.inf, dtype=np.float32)
    for distance in range(1, reach_px + 1):
        row_offset = round(row_step * distance)
        column_offset = round(column_step * distance)
        upsun = padded[reach_px + row_offset:reach_px + row_offset + rows]
        if column_offset:
            # np.roll(a, s)[i] == a[i - s], so the shift is negated to sample TOWARD the sun.
            upsun = np.roll(upsun, -column_offset, axis=1)
        np.maximum(steepest, (upsun - exaggerated) / (distance * m_per_px), out=steepest)

    # The horizon crosses the sun's disc over its whole angular diameter: fully lit while it sits a
    # half-diameter below the sun's altitude, fully occluded a half-diameter above. Read from
    # `palette` at CALL time, so this module cannot hold a stale copy of a shared look constant.
    disc = palette.SUN_ANGULAR_DIAMETER_DEG
    horizon = np.degrees(np.arctan(np.clip(steepest, 0.0, None)))
    fraction = (horizon - (altitude - disc / 2.0)) / disc
    return np.clip(fraction, 0.0, 1.0).astype(np.float32)


def shadow_reach_px(max_relief_m: float, zfactor: float, m_per_px: float,
                    altitude: float = 45.0) -> float:
    """Longest shadow, in pixels, that `max_relief_m` of exaggerated relief can cast.

    The sizing oracle for `reach_px`: relief of h metres exaggerated by z stands z*h high and, at a
    sun altitude a, lays its shadow z*h/tan(a) metres along the ground. Kept here rather than done
    by hand at the call site because getting it wrong truncates shadows silently — they simply stop,
    with no error and no visible edge to notice.
    """
    return zfactor * max_relief_m / math.tan(math.radians(altitude)) / m_per_px
