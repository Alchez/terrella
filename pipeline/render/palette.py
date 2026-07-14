"""Shared hypsometric palette — the single source of truth for the land/sea color
ramps, snow, and inland-water tints that define Terrella's look.

Used by the raster tile shading (venv) and, in time, the Cycles hero scene. Kept
deliberately dependency-free (pure Python, no numpy/bpy) so it can be imported from
either interpreter — Blender's bundled Python cannot see the venv's packages, so any
constant shared with `scene_build` must live in a module like this one.

Colors are LINEAR RGB (the ramp stops), matching the hero's ColorRamp nodes under the
Standard view transform, where linear→sRGB is the only encode on the way to an 8-bit
image. `color_relief_rows` densely samples each ramp and sRGB-encodes it into the rows
`gdaldem color-relief` consumes. Land and sea are separate ramps chosen later by the
ocean mask (not the elevation sign), which keeps the coastline crisp.

The frozen endpoints (CLAUDE.md → Locked global constants → Color) are E9D9C0/E9DCC8
for land at 0/6000 m and 8FC7C5/3A6E7D for sea at 0/-3000 m; `test_palette.py` guards
against drift off those values.
"""

from pathlib import Path

RGB = tuple[float, float, float]
RGB8 = tuple[int, int, int]
Stop = tuple[float, RGB]

# Land 0..6000 m, sea -3000..0 m. Linear RGB, EASE-interpolated between stops.
LAND_STOPS: list[Stop] = [
    (0.000, (0.814847, 0.693872, 0.527115)),
    (0.083, (0.679543, 0.412543, 0.270498)),
    (0.250, (0.617207, 0.313989, 0.215861)),
    (0.500, (0.584079, 0.417885, 0.309469)),
    (0.750, (0.715694, 0.584078, 0.445201)),
    (1.000, (0.814847, 0.715694, 0.577580)),
]
SEA_STOPS: list[Stop] = [
    (0.000, (0.274677, 0.571125, 0.558340)),
    (0.100, (0.201556, 0.479320, 0.479320)),
    (0.220, (0.138432, 0.381326, 0.412543)),
    (0.380, (0.093059, 0.291771, 0.341914)),
    (0.620, (0.063010, 0.215861, 0.274677)),
    (1.000, (0.042311, 0.155926, 0.205079)),
]
WATER_RGB: RGB8 = (152, 197, 200)  # 98C5C8 — flat inland lake/river teal
SNOW_RGB: RGB8 = (232, 241, 246)         # E8F1F6 — sunlit snow (bright glacial white)
SNOW_SHADOW_RGB: RGB8 = (176, 199, 219)  # B0C7DB — shaded snow (cool blue-white, not grey)

LAND_MAX_M = 6000.0
SEA_MIN_M = -3000.0


def smoothstep(t: float) -> float:
    """Blender's EASE (ease-in-out) blend, matching the hero ColorRamp interpolation."""
    return t * t * (3.0 - 2.0 * t)


def lin2srgb(c: float) -> float:
    """Encode one linear-RGB channel to sRGB, clamped to [0, 1]."""
    c = min(1.0, max(0.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def ramp_color(pos: float, stops: list[Stop]) -> RGB:
    """EASE-interpolated linear RGB at pos in [0, 1] (clamped)."""
    pos = min(1.0, max(0.0, pos))
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if pos <= p1:
            t = 0.0 if p1 == p0 else (pos - p0) / (p1 - p0)
            blend = smoothstep(min(1.0, max(0.0, t)))
            return (c0[0] + (c1[0] - c0[0]) * blend,
                    c0[1] + (c1[1] - c0[1]) * blend,
                    c0[2] + (c1[2] - c0[2]) * blend)
    return stops[-1][1]


def _srgb8(color: RGB) -> RGB8:
    return (round(lin2srgb(color[0]) * 255),
            round(lin2srgb(color[1]) * 255),
            round(lin2srgb(color[2]) * 255))


def color_relief_rows(kind: str, step: float = 25.0) -> list[tuple[float, RGB8]]:
    """(elevation, sRGB) rows for one surface, densely sampled so `gdaldem`'s linear
    interpolation between rows reproduces the EASE ramp.

    'land' maps elevation 0..6000 m; 'sea' maps depth -3000..0 m (deepest first). Each
    ramp only has to be correct on its own side — the ocean mask selects between them."""
    if kind == "land":
        count = round(LAND_MAX_M / step)
        return [(i * step, _srgb8(ramp_color(i * step / LAND_MAX_M, LAND_STOPS)))
                for i in range(count + 1)]
    if kind == "sea":
        count = round(-SEA_MIN_M / step)
        rows = []
        for i in range(count + 1):
            elev = SEA_MIN_M + i * step
            rows.append((elev, _srgb8(ramp_color(-elev / -SEA_MIN_M, SEA_STOPS))))
        return rows
    raise ValueError(f"kind must be 'land' or 'sea', got {kind!r}")


def write_color_relief(path: Path, kind: str, step: float = 25.0) -> None:
    """Write a `gdaldem color-relief` file for one surface, with an `nv` nodata row."""
    with open(path, "w") as handle:
        for elev, (red, green, blue) in color_relief_rows(kind, step):
            handle.write(f"{elev:.2f} {red} {green} {blue}\n")
        handle.write("nv 0 0 0\n")
