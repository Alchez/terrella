"""Shared hypsometric palette — the single source of truth for the land/sea color
ramps, snow, and inland-water tints that define Terrella's look.

Used by the raster tile shading (venv) AND the Cycles hero scene (`scene_build`
imports this module directly since the 2026-07-23 sea-sync — its constants were
copies before that, which is how three divergences accumulated). Kept deliberately
dependency-light (numpy only, which Blender bundles) so it imports from either
interpreter — Blender's bundled Python cannot see the venv's packages, so any
constant shared with `scene_build` must live in a module like this one.

Colors are LINEAR RGB (the ramp stops), matching the hero's ColorRamp nodes under the
Standard view transform, where linear→sRGB is the only encode on the way to an 8-bit
image. `color_relief_rows` densely samples each ramp and sRGB-encodes it into the rows
`gdaldem color-relief` consumes. Land and sea are separate ramps chosen later by the
ocean mask (not the elevation sign), which keeps the coastline crisp.

The frozen endpoints (PLAN.md → Locked global constants → Color) are E9D9C0/E9DCC8
for land at 0/6000 m and 85B9B7/3A6E7D for sea at 0/-6000 m; `test_palette.py` guards
against drift off those values.
"""

from pathlib import Path

import numpy as np

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
# Positions redistributed by depth (SEA_MIN_M = -6000): the two brightest bands sit
# in the top 800 m so continental SHELVES read as a bright->mid gradient (the "shelf
# seas" signature), while the deeper stops spread across 0.8..6 km so abyssal plains
# and trenches vary tonally instead of clamping to one slab. Same committed colours.
SEA_STOPS: list[Stop] = [
    (0.0000, (0.233475, 0.485456, 0.474589)),  #     0 m  surface teal (deepened ~15% from 8FC7C5)
    (0.0333, (0.171323, 0.407422, 0.407422)),  #  -200 m  shelf break (deepened ~15%)
    (0.1333, (0.138432, 0.381326, 0.412543)),  #  -800 m  upper slope
    (0.3333, (0.093059, 0.291771, 0.341914)),  # -2000 m  lower slope / basin
    (0.6333, (0.063010, 0.215861, 0.274677)),  # -3800 m  abyssal plain
    (1.0000, (0.042311, 0.155926, 0.205079)),  # -6000 m  deepest / trench
]
WATER_RGB: RGB8 = (142, 198, 196)  # 8EC6C4 — flat inland lake/river teal: the sea
# surface tone (85B9B7) lightened ~7%, so lakes stay in the sea's green-teal family but
# read a touch calmer/lighter (the lake convention). Re-synced to the 2026-07-14 sea
# rework, which had deepened the sea surface and left this stranded ~15% brighter.
SNOW_RGB: RGB8 = (232, 241, 246)         # E8F1F6 — sunlit snow (bright glacial white)
SNOW_SHADOW_RGB: RGB8 = (176, 199, 219)  # B0C7DB — shaded snow (cool blue-white, not grey)
# Sea ice: the same light-keyed white family but a subtle notch COOLER and dimmer than land snow,
# so the poles read floating-thin-ice vs thick-ice-sheet without a hard colour split (the coastline
# and relief carry the rest). Physically honest: thin sea ice over dark ocean reads less bright than
# thick snow. Blended over the sea by seaice.ice_alpha, gated on `ocean`, in shade.composite.
ICE_RGB: RGB8 = (212, 228, 240)          # D4E4F0 — sunlit sea ice (cool white, dimmer than snow)
ICE_SHADOW_RGB: RGB8 = (156, 184, 210)   # 9CB8D2 — shaded sea ice (deeper cool blue)

LAND_MAX_M = 6000.0
SEA_MIN_M = -6000.0  # extended from -3000 (2026-07-14 sea rework) so the deep sea varies tonally
LAKE_MAX_M = 1642.0  # Baikal — the deepest lake GLOBathy carries; the lake ramp's far end
SUN_ALT_DEG = 45.0   # the shared sun altitude: tile KNOBS["alt"] and the hero SUN_ROTATION
# X-tilt (90 - alt) both derive from this (2026-07-23 sea-sync — the cure for the 46/45
# split). Azimuth stays per-side: both are NW by their own conventions (tile 315, hero -45).


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


def srgb8_to_linear(color: RGB8) -> RGB:
    """8-bit sRGB -> linear RGB (the space the ramp stops live in). Inverse of `_srgb8`.

    Public: `scene_build` derives its flat RGBA tints (water, snow) through this."""
    def channel(value: int) -> float:
        unit = value / 255.0
        return unit / 12.92 if unit <= 0.04045 else ((unit + 0.055) / 1.055) ** 2.4
    return (channel(color[0]), channel(color[1]), channel(color[2]))


# Lake ramp, keyed on depth BELOW EACH LAKE'S OWN SURFACE -- never on elevation. Lakes sit at
# any altitude (Titicaca +3812 m, Baikal +456), so the sea ramp, which reads absolute
# elevation, physically cannot see them (2026-07-07).
#
# Stop 0 IS `WATER_RGB`, derived rather than copied: a lake's gradient therefore begins at
# exactly the flat tint its own shallows and its rivers already use, and the two can never
# drift apart -- which is precisely how WATER_RGB itself went stale against SEA_STOPS[0].
# Anchoring the shore at the flat tone is also a rendering decision the prototype settled:
# a lighter rim was tried and rejected because it dissolves the shoreline against pale
# high-plateau land.
LAKE_STOPS: list[Stop] = [
    (0.0, srgb8_to_linear(WATER_RGB)),        # 8EC6C4 — shore, == the flat inland tint
    (0.5, srgb8_to_linear((100, 155, 164))),  # 649BA4 — the prototype's proven deep tone
    (1.0, srgb8_to_linear((71, 128, 143))),   # 47808F — deep lakes (Tanganyika, Baikal)
]


def lake_lut(size: int = 256) -> list[RGB8]:
    """`size` sRGB colours sampled uniformly along the lake ramp's 0..1 POSITION axis.

    Uniform in ramp position, not in depth: the caller applies the depth->position curve in
    numpy and indexes this table, which keeps this module numpy-free so Blender's bundled
    interpreter can still import it.
    """
    return [_srgb8(ramp_color(index / (size - 1), LAKE_STOPS)) for index in range(size)]


def color_relief_rows(kind: str, step: float = 25.0) -> list[tuple[float, RGB8]]:
    """(elevation, sRGB) rows for one surface, densely sampled so `gdaldem`'s linear
    interpolation between rows reproduces the EASE ramp.

    'land' maps elevation 0..6000 m; 'sea' maps depth -6000..0 m (deepest first). Each
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


LUT_STEP_M = 1.0  # LUT resolution in metres. 6001 entries x 3 B = 18 KB per surface.


def relief_lut(kind: str, step: float = LUT_STEP_M) -> np.ndarray:
    """Elevation -> sRGB LUT for one surface, as a (3, N) uint8 array.

    This is what lets `gdaldem color-relief` be deleted rather than tuned. Measured 2026-07-16:
    color-relief is 24.4% of all pass CPU (28:19, single-threaded) and the profile is
    `libgdal 19.37%` (interpolation) vs `libdeflate 4.33%` -- so no `-co NUM_THREADS` can touch
    it. That 19.37% is a per-pixel SEARCH over the 241 rows `color_relief_rows` emits, because
    gdaldem's format allows arbitrary stop positions. Ours are uniform, so the index is just
    `elevation / step` -- a divide and a gather, no search. See `lut_lookup`.

    Sampled from the same `ramp_color` the gdaldem rows come from, so the two agree by
    construction at every row and to <=1 DN between them (tests/test_relief_lut.py). At 1 m this
    is strictly FINER than the 25 m rows gdaldem interpolates across, so it is if anything the
    more faithful rendering of the authored ramp -- and it is 18 KB.
    """
    if kind == "land":
        count = round(LAND_MAX_M / step)
        colors = [_srgb8(ramp_color(index * step / LAND_MAX_M, LAND_STOPS))
                  for index in range(count + 1)]
    elif kind == "sea":
        count = round(-SEA_MIN_M / step)
        # index 0 == SEA_MIN_M (deepest), matching color_relief_rows' ordering.
        colors = [_srgb8(ramp_color(-(SEA_MIN_M + index * step) / -SEA_MIN_M, SEA_STOPS))
                  for index in range(count + 1)]
    else:
        raise ValueError(f"kind must be 'land' or 'sea', got {kind!r}")
    return np.asarray(colors, dtype=np.uint8).T  # (3, N)


def lut_index(kind: str, elevation, step: float = LUT_STEP_M) -> np.ndarray:
    """Elevation -> clamped LUT index. The whole optimisation: a divide, not a search.

    Clamping is load-bearing, not defensive: the planet height raster spans -10,728 m to
    +7,281 m (measured), i.e. past BOTH ramp ends, and `gdaldem` clamps to its first/last row.
    Land-classed pixels can also be negative (Dead Sea, -430 m) -- the ocean MASK picks the
    ramp, never the sign -- so the land ramp must clamp those to its 0 m colour.
    """
    elevation = np.asarray(elevation, dtype=np.float32)
    if kind == "land":
        raw = elevation / np.float32(step)
        limit = round(LAND_MAX_M / step)
    elif kind == "sea":
        raw = (elevation - np.float32(SEA_MIN_M)) / np.float32(step)
        limit = round(-SEA_MIN_M / step)
    else:
        raise ValueError(f"kind must be 'land' or 'sea', got {kind!r}")
    return np.clip(np.rint(raw), 0, limit).astype(np.int32)


def lut_lookup(lut: np.ndarray, kind: str, elevation, step: float = LUT_STEP_M) -> np.ndarray:
    """(3, ...) uint8 colours for `elevation`, shaped like `elevation`."""
    return lut[:, lut_index(kind, elevation, step)]


def color_relief_text(kind: str, step: float = 25.0) -> str:
    """The exact `gdaldem color-relief` file contents for one surface, incl. the `nv` row.

    Split out from `write_color_relief` so a caller can compare the ramp a run WOULD use
    against the one already on disk without touching the file. The tile pipeline gates its
    color-relief stages on that comparison, which only works if an unchanged palette leaves
    the ramp's mtime alone.
    """
    rows = [f"{elev:.2f} {red} {green} {blue}"
            for elev, (red, green, blue) in color_relief_rows(kind, step)]
    return "\n".join(rows + ["nv 0 0 0", ""])


def write_color_relief(path: Path, kind: str, step: float = 25.0) -> None:
    """Write a `gdaldem color-relief` file for one surface, with an `nv` nodata row."""
    with open(path, "w") as handle:
        handle.write(color_relief_text(kind, step))
