"""The land, sea, snow and inland-water ramps, read by both producers of a Terrella pixel.

Imported by the tile shading in the venv and by `scene_build` inside Blender, whose bundled Python
cannot see the venv's packages. Anything shared with the rig has to live in a module like this one,
which is why numpy is the only dependency here.

Stops are linear RGB, matching the hero's ColorRamp nodes; `color_relief_rows` samples a ramp
densely and sRGB-encodes it for `gdaldem color-relief`. Land and sea are separate ramps, selected by
the ocean mask rather than by the elevation's sign, which keeps the coastline crisp.

Nothing here renders a shipped pixel. Blender does, reading these stops as ColorRamps through
`scene_build`, and it reaches 8-bit through `RIG.view_transform`, a tone map that rolls highlights
off and darkens mid-tones, where `_srgb8` below is a plain sRGB transfer. So a hex sampled from a
tile will not equal one computed here, and no gate can see the difference.

Every authored ramp constant below belongs to one body. Read them through a `Look` and never by
name: `test_palette.py` scans `pipeline/` for the bypass, because a module that reads Earth's
globals renders Earth correctly and is wrong only on the planet nobody has looked at.
"""

import itertools
from dataclasses import dataclass

import numpy as np

RGB = tuple[float, float, float]
RGB8 = tuple[int, int, int]
Stop = tuple[float, RGB]

# Linear RGB, EASE-interpolated between stops. A position is a fraction of the ramp's own domain,
# which `EARTH_LOOK` below declares.
LAND_STOPS: list[Stop] = [
    (0.000, (0.814847, 0.693872, 0.527115)),
    (0.083, (0.679543, 0.412543, 0.270498)),
    (0.250, (0.617207, 0.313989, 0.215861)),
    (0.500, (0.584079, 0.417885, 0.309469)),
    (0.750, (0.715694, 0.584078, 0.445201)),
    (1.000, (0.814847, 0.715694, 0.577580)),
]
# Positions are uneven on purpose: the two brightest bands sit in the top 800 m so continental
# shelves read as a bright-to-mid gradient, and the rest spread so the abyss varies tonally instead
# of clamping to one slab.
SEA_STOPS: list[Stop] = [
    (0.0000, (0.233475, 0.485456, 0.474589)),  #     0 m  surface teal (deepened ~15% from 8FC7C5)
    (0.0333, (0.171323, 0.407422, 0.407422)),  #  -200 m  shelf break (deepened ~15%)
    (0.1333, (0.138432, 0.381326, 0.412543)),  #  -800 m  upper slope
    (0.3333, (0.093059, 0.291771, 0.341914)),  # -2000 m  lower slope / basin
    (0.6333, (0.063010, 0.215861, 0.274677)),  # -3800 m  abyssal plain
    (1.0000, (0.042311, 0.155926, 0.205079)),  # -6000 m  deepest / trench
]
# Flat inland lake and river teal: the sea surface tone lightened ~7%, so lakes stay in the sea's
# family and read a touch calmer. `test_water_rgb_is_sea_surface_lightened` holds the relation.
WATER_RGB: RGB8 = (142, 198, 196)  # 8EC6C4

# Earth's ice white rather than the project's: a producer declares which white paints its alpha, so
# no body inherits another's by omission. The blue is physics and not decoration — thick clean
# glacial ice absorbs red — and it does not travel; see MARS_ICE_WHITE.
SNOW_RGB: RGB8 = (232, 241, 246)         # E8F1F6 — sunlit snow (bright glacial white)
SNOW_SHADOW_RGB: RGB8 = (176, 199, 219)  # B0C7DB — shaded snow (cool blue-white, not grey)

# Mars, one authored white for both poles, ratified on a rendered frame.
#
# Per-pole whites are the temptation, and the two deposits really are different colours. One white
# is what looked right on both; the measured difference stays in the ice, where it belongs. Do not
# derive a candidate back from that difference either: what ships is warmer than the hex, since the
# render adds twenty-odd DN, so a white is chosen by naming a RENDERED target and inverting.
#
# `scripts/measure_mars_ice_white.py` owns the arithmetic, the tolerance and the ice as ratified.
# Its `--compare` asks whether the ICE has moved since, which is what expires a look decision.
MARS_ICE_WHITE: dict[str, tuple[RGB8, RGB8]] = {   # pole -> (sunlit, shadowed)
    "north": ((226, 242, 253), (185, 198, 207)),   # E2F2FD / B9C6CF
    "south": ((226, 242, 253), (185, 198, 207)),   # E2F2FD / B9C6CF
}
# Sea ice: the snow family a notch cooler and dimmer, so the poles read floating-thin-ice against
# thick-ice-sheet without a hard colour split. Thin ice over dark ocean really is the darker of the
# two. Blended over the sea by the painter, from `seaice.ice_alpha` gated on `ocean`.
ICE_RGB: RGB8 = (212, 228, 240)          # D4E4F0 — sunlit sea ice (cool white, dimmer than snow)
ICE_SHADOW_RGB: RGB8 = (156, 184, 210)   # 9CB8D2 — shaded sea ice (deeper cool blue)

LAND_MAX_M = 6000.0
SEA_MIN_M = -6000.0
LAKE_MAX_M = 1642.0  # Baikal — the deepest lake GLOBathy carries; the lake ramp's far end

# The shared sun altitude. The tiles' `block_render` and the hero's `RIG.sun_rotation` X-tilt both
# derive from this one number as `90 - alt`. Both sides light from 315, and only the spelling
# differs: a tile names the compass bearing, a hero names the euler that produces it, which
# `scene_build.arrival_azimuth_deg` converts between and is the only place that conversion lives.
SUN_ALT_DEG = 45.0

# The fill, in the compass convention: altitude, and the main sun's mirror azimuth. Geometry rather
# than an art dial, the NW bearing being a locked cartographic convention (ART.md § Sun altitude &
# azimuth), which is why they sit here rather than among the tunables. `RIG.fill_rotation` derives
# its euler from both, so editing one here moves the rendered fill.
FILL_ALTITUDE = 60.0
FILL_AZIMUTH = 135.0

# How wide the sun's disc is, which is why shadow edges are soft. Three readers, and the third is
# what makes a second copy more than cosmetic: `block_plan` sizes every block's context from the
# half-diameter, so a disagreement silently mis-sizes the whole planet.
SUN_ANGULAR_DIAMETER_DEG = 12.0

# Earth's vertical exaggeration, and only Earth's: relief is a different fraction of the radius on
# every planet. Every path that draws more than one body reads `Body.exaggeration`, and
# `tests/test_bodies.py` holds Earth's field equal to this. Importing it into a shared path instead
# is the mistake to avoid — it gives a Mars block two thirds of its displacement — and pinning
# rather than sharing is what keeps the tiles matching the heroes.
EXAGGERATION = 15.0


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
    for (p0, c0), (p1, c1) in itertools.pairwise(stops):
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


# Lake ramp, keyed on depth below each lake's own surface and never on elevation: lakes sit at any
# altitude (Titicaca +3812 m, Baikal +456), so the sea ramp, which reads absolute elevation, cannot
# see them at all.
#
# Stop 0 is derived from `WATER_RGB` rather than transcribed, so a lake's gradient begins at exactly
# the flat tint its own shallows and rivers use. A lighter rim was tried and rejected: it dissolves
# the shoreline against pale high-plateau land.
LAKE_STOPS: list[Stop] = [
    (0.0, srgb8_to_linear(WATER_RGB)),        # 8EC6C4 — shore, == the flat inland tint
    (0.5, srgb8_to_linear((100, 155, 164))),  # 649BA4 — the prototype's proven deep tone
    (1.0, srgb8_to_linear((71, 128, 143))),   # 47808F — deep lakes (Tanganyika, Baikal)
]


@dataclass(frozen=True)
class Surface:
    """One ramp and the two elevations it runs between: `origin_m` at position 0.0, `extreme_m` at
    position 1.0.

    `extreme_m` carries the direction in its sign, which lets land and sea share every formula below
    with no branch: Earth's land runs 0 -> +6000 and its sea 0 -> -6000. Position is
    `(elevation - origin_m) / span_m`, and index 0 of a LUT sits at `lowest_m`.

    Hinging a ramp at zero is the Earth fact wearing a constant's clothes, and `origin_m` is what
    refuses it. On Earth 0 m is the shoreline, a real boundary. Mars's 0 m is the areoid, an
    equipotential with no expression on the ground sitting at the median of the planet's elevations,
    so hinging there puts half of Mars below the ramp, clamped to one colour.

    `origin_m` has no default on purpose: 0.0 would be right at both of today's construction sites
    and silently wrong at the first one that is not.
    """

    stops: list[Stop]
    origin_m: float
    extreme_m: float

    def __post_init__(self):
        # A zero-width ramp divides by zero, and numpy carries the nan through `rint` into an
        # arbitrary int32 index: a planet in one wrong colour with no exception anywhere. Declaration
        # is the only cheap place to be loud about it.
        if self.origin_m == self.extreme_m:
            raise ValueError(
                f"a ramp needs two distinct ends; got origin_m == extreme_m == {self.origin_m}"
            )

    @property
    def span_m(self) -> float:
        """Signed distance from position 0.0 to 1.0. Negative for a ramp that runs downward."""
        return self.extreme_m - self.origin_m

    @property
    def lowest_m(self) -> float:
        """The elevation at LUT index 0, which is the lower end whichever way the ramp runs."""
        return min(self.origin_m, self.extreme_m)

    def stop_at(self, metres: float) -> tuple[float, float, float]:
        """The authored stop sitting at `metres`, found by the domain law rather than by index.

        Indexing is the temptation, since the elevations live only in the comments beside each stop,
        and it breaks silently: widening a domain prepends a stop and slides every index, so the one
        that answered for +655 m answers for -1765 m instead, a real colour, in range, wrong.

        A position is derived from the domain rather than chosen, so a stop that keeps its elevation
        keeps answering here and one that genuinely moved raises instead of returning a neighbour.
        """
        wanted = (metres - self.origin_m) / self.span_m
        for position, linear in self.stops:
            if abs(position - wanted) <= 1e-6:
                return linear
        raise ValueError(
            f"no stop at {metres:g} m (position {wanted:.6f}); this ramp has "
            f"{[round(position, 6) for position, _ in self.stops]}. A stop that moved is a look "
            f"change and wants judging, not a tolerance.")


@dataclass(frozen=True)
class Look:
    """Everything the ramps need to draw one planet.

    A look is not a body: `bodies.py` owns geometry, this owns colour, and the two are independent
    axes. One planet could carry several looks, and a look says nothing about a radius.

    Frozen and whole, so a second look is a second instance rather than a second module.

    `sea = None` is a statement rather than a gap. It says this planet draws no sea. Writing one out
    anyway for a body that declares no oceanmask puts a colour nobody chose into the freshness
    recipe, indistinguishable from one that was deliberated over.
    """

    land: Surface
    sea: Surface | None


#: Earth's look, assembled from the authored constants above rather than restating them.
EARTH_LOOK = Look(
    land=Surface(stops=LAND_STOPS, origin_m=0.0, extreme_m=LAND_MAX_M),
    sea=Surface(stops=SEA_STOPS, origin_m=0.0, extreme_m=SEA_MIN_M),
)

#: Mars's land ramp: cartographic convention, not a picture of the planet, and the About page says
#: so to visitors. Elevation predicts colour on Earth through climate and vegetation; Mars's albedo
#: is set by wind-blown dust, which does not care about height. ART § Land color ramp holds what the
#: measurement gave and what it did not.
#:
#: Rising monotonically is the one property chosen over fidelity. Mars is genuinely brightest at
#: both ends, Hellas being a dust trap and Tharsis dust-mantled, so a faithful ramp would paint the
#: deepest basin and the highest summit the same colour and height would stop being readable.
#:
#: Do not re-tune these by inverting through the composite's shader, which is how they were first
#: derived. That shader is deleted and reached no pixel on this body; what ships is the pre-inverted
#: value, cooler and less saturated than the colour the list was written to hit, and that was
#: ratified on a rendered block. Judge a re-tune the same way.
#
# The domain reaches below the planet's floor deliberately, so nothing clips at either end.
# Narrowing it back to -6000 is the tidy that looks right, and it clamps every pixel below that to
# one colour. "Naturalized -7000" is a different proposal, restretching the whole ramp rather than
# adding a tail, and it is unrendered.
MARS_LAND_STOPS: list[Stop] = [
    (0.00000000, (0.108487, 0.045162, 0.026101)),  # -8600 m  below the measured floor
    (0.17687075, (0.187821, 0.078187, 0.045186)),  # -6000 m  p1, ships #804d35
    (0.30034014, (0.274677, 0.114435, 0.066626)),  # -4185 m  lowland plains
    (0.46496599, (0.412543, 0.171441, 0.082283)),  # -1765 m  the northern lowlands' own tone
    (0.62959184, (0.514918, 0.246201, 0.111932)),  #  +655 m  just above the areoid, modal elevation
    (0.81891156, (0.597202, 0.366253, 0.187821)),  # +3438 m  southern highlands
    (1.000, (0.658375, 0.520996, 0.337164)),  # +6100 m  Tharsis and the volcanic summits
]

#: Mars. Everything here is decided except whether it ever draws a sea, and `sea=None` says it does
#: not: `fuse/relabel_mars.py` declares a heightfield and no oceanmask, so no pixel could select a
#: sea ramp however carefully one were written.
#:
#: The domain is derived rather than preferred. The top end is p99 of the shipped heightfield,
#: area-weighted on the sphere, rounded; keying it to Olympus Mons instead spends most of the ramp
#: on the 1.1% of the planet above +6,000 m, and Olympus reads through its relief anyway, which no
#: ramp touches. The bottom end sits below the measured floor rather than on a percentile, so the
#: deepest pixel keeps a colour of its own — see `MARS_LAND_STOPS`.
MARS_LOOK = Look(
    land=Surface(stops=MARS_LAND_STOPS, origin_m=-8600.0, extreme_m=6100.0),
    sea=None,
)

#: The look each body draws with today, keyed by slug rather than held as a `Body` field, since
#: geometry and colour are separate axes. The cost is that two modules know the set of planets, so
#: `tests/test_palette.py` holds this dict to the body registry: a body registered there with no
#: entry here is the failure that renders rather than raises.
LOOK_BY_BODY: dict[str, Look] = {"earth": EARTH_LOOK, "mars": MARS_LOOK}


def look_for(body: str) -> Look:
    """The look a body draws with. Raises on an unknown body and never falls back to Earth's.

    A fallback is the tempting kindness here, and it renders a complete, plausible, internally
    consistent pyramid in another planet's colours with every gate passing.

    Called where the body is known rather than threaded in beside it, since a `look` parameter next
    to a `body` parameter adds only a way for the two to disagree: `params(body=MARS,
    look=EARTH_LOOK)` type-checks.
    """
    try:
        return LOOK_BY_BODY[body]
    except KeyError:
        raise KeyError(
            f"no look registered for body {body!r}; known: {sorted(LOOK_BY_BODY)}"
        ) from None


def surface(kind: str, *, look: Look) -> Surface:
    """Resolve `'land'`/`'sea'` to its ramp: the one place that dispatch lives.

    `look` is required and keyword-only. With a default, a second look would leave every call site
    below still drawing Earth and nothing would name one of them; without it the type checker names
    them all at once. Same reason no field on `Body` may carry a default.
    """
    if kind == "land":
        return look.land
    if kind == "sea":
        if look.sea is None:
            raise ValueError(
                "this look draws no sea, so there is no sea ramp to resolve. A body whose planet "
                "seam declares an oceanmask needs one; a body that declares none never asks."
            )
        return look.sea
    raise ValueError(f"kind must be 'land' or 'sea', got {kind!r}")


# Everything below samples the ramps into a table or a gdaldem file, and no stage calls any of it,
# both consumers having gone with the raytrace. It is kept as the ramps' executable statement,
# hashed by `test_palette.TestTheLookIsByteStable` so a colour cannot move unnoticed, and read when
# a look question needs the authored ramp rather than a rendered frame. Do not price a ramp change
# from these numbers: the light is the missing stage, so measure one on a rendered block.


def lake_lut(size: int = 256) -> list[RGB8]:
    """`size` sRGB colours sampled uniformly along the lake ramp's 0..1 position axis.

    Uniform in position rather than in depth: the caller applies the depth-to-position curve in
    numpy and indexes this table.
    """
    return [_srgb8(ramp_color(index / (size - 1), LAKE_STOPS)) for index in range(size)]


def color_relief_rows(kind: str, *, look: Look, step: float = 25.0) -> list[tuple[float, RGB8]]:
    """(elevation, sRGB) rows for one surface, densely sampled so `gdaldem`'s linear interpolation
    between rows reproduces the EASE ramp. Deepest row first, whichever way the ramp runs."""
    ramp = surface(kind, look=look)
    count = round(abs(ramp.span_m) / step)
    rows = []
    for i in range(count + 1):
        elev = ramp.lowest_m + i * step
        rows.append((elev, _srgb8(ramp_color((elev - ramp.origin_m) / ramp.span_m, ramp.stops))))
    return rows


# LUT resolution in metres. A surface costs `3 * (|span_m| / step + 1)` bytes, tens of KB for any
# ramp a body could want, so the step is chosen for fidelity alone.
LUT_STEP_M = 1.0


def relief_lut(kind: str, *, look: Look, step: float = LUT_STEP_M) -> np.ndarray:
    """Elevation -> sRGB LUT for one surface, as a (3, N) uint8 array.

    Uniform positions, so an index is `elevation / step`: a divide and a gather rather than the
    per-pixel search gdaldem's arbitrary-position format forced. See `lut_lookup`.

    Sampled from the same `ramp_color` the gdaldem rows come from, so the two agree by construction
    and to <=1 DN between them (tests/test_relief_lut.py). That agreement is the point: two
    independent renderings of one authored ramp, which is what makes either usable as an oracle.
    """
    ramp = surface(kind, look=look)
    count = round(abs(ramp.span_m) / step)
    colors = [_srgb8(ramp_color((ramp.lowest_m + index * step - ramp.origin_m) / ramp.span_m,
                                ramp.stops))
              for index in range(count + 1)]
    return np.asarray(colors, dtype=np.uint8).T  # (3, N)


def lut_index(kind: str, elevation, *, look: Look, step: float = LUT_STEP_M) -> np.ndarray:
    """Elevation -> clamped LUT index. The whole optimisation: a divide, not a search.

    Clamping is load-bearing rather than defensive. Every body's height raster runs past both of its
    ramp's ends, and Earth's land-classed pixels can be negative (the Dead Sea at -430 m) because
    the ocean mask picks the ramp and never the sign, so the land ramp must clamp those to its 0 m
    colour. `gdaldem` clamped to its first and last row the same way.
    """
    elevation = np.asarray(elevation, dtype=np.float32)
    ramp = surface(kind, look=look)
    raw = (elevation - np.float32(ramp.lowest_m)) / np.float32(step)
    limit = round(abs(ramp.span_m) / step)
    return np.clip(np.rint(raw), 0, limit).astype(np.int32)


def lut_lookup(lut: np.ndarray, kind: str, elevation, *, look: Look,
               step: float = LUT_STEP_M) -> np.ndarray:
    """(3, ...) uint8 colours for `elevation`, shaped like `elevation`."""
    return lut[:, lut_index(kind, elevation, look=look, step=step)]


def color_relief_text(kind: str, *, look: Look, step: float = 25.0) -> str:
    """The exact `gdaldem color-relief` file contents for one surface, incl. the `nv` row."""
    rows = [f"{elev:.2f} {red} {green} {blue}"
            for elev, (red, green, blue) in color_relief_rows(kind, look=look, step=step)]
    return "\n".join(rows + ["nv 0 0 0", ""])


