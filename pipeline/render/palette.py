"""Shared hypsometric palette — the single source of truth for the land/sea color
ramps, snow, and inland-water tints that define Terrella's look.

Used by the raster tile shading (venv) AND the Cycles hero scene (`scene_build`
imports this module directly since the sea-sync — its constants were
copies before that, which is how three divergences accumulated). Kept deliberately
dependency-light (numpy only, which Blender bundles) so it imports from either
interpreter — Blender's bundled Python cannot see the venv's packages, so any
constant shared with `scene_build` must live in a module like this one.

Colors are LINEAR RGB (the ramp stops), matching the hero's ColorRamp nodes under the
Standard view transform, where linear→sRGB is the only encode on the way to an 8-bit
image. `color_relief_rows` densely samples each ramp and sRGB-encodes it into the rows
`gdaldem color-relief` consumes. Land and sea are separate ramps chosen later by the
ocean mask (not the elevation sign), which keeps the coastline crisp.

EVERY RAMP CONSTANT HERE IS ONE BODY'S, and the module holds more than one body's. Earth's land
runs 0/6000 m and its sea 85B9B7/3A6E7D over 0/-6000 m, both frozen and guarded against drift by
`test_palette.py`. Mars answers `MARS_LAND_STOPS` over its own domain and shares no colour object
with Earth, so a re-tune of one planet cannot reach the other — which is the whole reason the ramps
are assembled into a named `Look` rather than read as globals. Nothing outside this module may read
an authored ramp by name; a source scan enforces it, because a module that does renders Earth
perfectly and is wrong only on the planet nobody has looked at.
"""

import itertools
from dataclasses import dataclass
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
# read a touch calmer/lighter (the lake convention). Re-synced to the sea
# rework, which had deepened the sea surface and left this stranded ~15% brighter.
# EARTH'S ice white, and it is Earth's rather than the project's — a second body measured a
# different one. `shade.composite` no longer reads these directly; the producer that computed the
# alpha declares which white paints it, so a body's ice cannot inherit another body's colour by
# omission. The hero rig still reads them, and the rig is Earth's by decision.
#
# The blue is not decoration: thick clean glacial ice absorbs red, so terrestrial snow really does
# go blue in shadow. That is Earth physics and does not travel — see MARS_ICE_WHITE.
SNOW_RGB: RGB8 = (232, 241, 246)         # E8F1F6 — sunlit snow (bright glacial white)
SNOW_SHADOW_RGB: RGB8 = (176, 199, 219)  # B0C7DB — shaded snow (cool blue-white, not grey)

# MARS, PER POLE, because the two deposits are measurably different colours: north 1.053 and south
# 1.291 in red:violet against their own ground at 1.231 and 1.807. Normalising each cap by its own
# surroundings leaves most of that gap standing, so the difference belongs to the ice rather than to
# what surrounds it or to how it was imaged.
#
# RED AND BLUE ARE MEASURED; GREEN IS NOT AND CANNOT BE. The Viking mosaic's green band is a fixed
# linear combination of its red and violet (R^2 0.9998), so only the red:violet ratio is evidence
# and green is a stated design rule: hold Earth's luminance, and keep the pair on one locus. The
# south could not hold both — sRGB cannot reach Earth's brightness at that warmth with red pinned at
# 255 — so its green is lifted to buy the luminance back, which is the choice that was ratified by
# eye rather than derived.
#
# The derivation is checkable and `scripts/measure_mars_ice_white.py` is the check: it reproduces
# Earth's own shipped pair exactly from Earth's ratio and luminance before it will report anything,
# which is what makes it trustworthy on a pair nobody had seen. Its `--compare` mode re-measures the
# ice and refuses a white that has stopped describing it — re-run it after any change to the alpha
# levels or to the cap grid, both of which have moved once already.
MARS_ICE_WHITE: dict[str, tuple[RGB8, RGB8]] = {   # pole -> (sunlit, shadowed)
    "north": ((243, 239, 231), (198, 195, 188)),   # F3EFE7 / C6C3BC
    "south": ((255, 239, 198), (207, 196, 160)),   # FFEFC6 / CFC4A0
}
# Sea ice: the same light-keyed white family but a subtle notch COOLER and dimmer than land snow,
# so the poles read floating-thin-ice vs thick-ice-sheet without a hard colour split (the coastline
# and relief carry the rest). Physically honest: thin sea ice over dark ocean reads less bright than
# thick snow. Blended over the sea by seaice.ice_alpha, gated on `ocean`, in shade.composite.
ICE_RGB: RGB8 = (212, 228, 240)          # D4E4F0 — sunlit sea ice (cool white, dimmer than snow)
ICE_SHADOW_RGB: RGB8 = (156, 184, 210)   # 9CB8D2 — shaded sea ice (deeper cool blue)

LAND_MAX_M = 6000.0
SEA_MIN_M = -6000.0  # extended from -3000 (the sea rework) so the deep sea varies tonally
LAKE_MAX_M = 1642.0  # Baikal — the deepest lake GLOBathy carries; the lake ramp's far end
SUN_ALT_DEG = 45.0   # the shared sun altitude: tile KNOBS["alt"] and the hero SUN_ROTATION
# X-tilt (90 - alt) both derive from this (the sea-sync — the cure for the 46/45
# split). Azimuth stays per-side: both are NW by their own conventions (tile 315, hero -45).
EXAGGERATION = 15.0  # the HERO's vertical exaggeration: render_prep.scene_numbers derives
# displacement_scale from it, and the region preview shades at it. The tile and cap path reads
# Body.exaggeration instead — relief is a different fraction of the radius on every planet, so it
# cannot be one number — and tests/test_bodies.py holds Earth's field equal to this. Pinned rather
# than shared: shared would be wrong for the second body, and unpinned would let the tiles drift
# away from the heroes they must match.


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


# Lake ramp, keyed on depth BELOW EACH LAKE'S OWN SURFACE -- never on elevation. Lakes sit at
# any altitude (Titicaca +3812 m, Baikal +456), so the sea ramp, which reads absolute
# elevation, physically cannot see them.
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


@dataclass(frozen=True)
class Surface:
    """One ramp, and the two elevations it runs BETWEEN: `origin_m` at position 0.0, `extreme_m`
    at position 1.0.

    `extreme_m` carries the DIRECTION in its sign, which is what lets land and sea share every
    formula below instead of each carrying its own transcription: Earth's land runs 0 -> +6000 and
    its sea runs 0 -> -6000 with no branch. Position is `(elevation - origin_m) /
    (extreme_m - origin_m)`, and the elevation a ramp's first LUT index sits at is
    `min(origin_m, extreme_m)` — the abyss for sea, the origin for land.

    ORIGIN EXISTS BECAUSE ZERO WAS AN EARTH FACT WEARING A CONSTANT'S CLOTHES. This class used to
    hardcode 0 as one end, in `min(0, extreme_m)` and in dividing by `extreme_m` alone, and on Earth
    that is right for a reason: 0 m is the shoreline, a real boundary where the ramp genuinely
    should hinge. On a body with no sea it is nothing of the kind. Mars's 0 m is the areoid — an
    equipotential reference with no expression on the ground, sitting at the MEDIAN of the planet's
    elevations — so hinging there put 51.6% of Mars below the ramp entirely, clamped to one colour.
    A body that declares no sea should not have its ramp shaped as though it did.

    `origin_m` HAS NO DEFAULT. A default of 0.0 would be correct at both of today's construction
    sites and silently wrong at the first one that needed otherwise, which is the whole failure this
    field exists to end; the type checker naming every site is worth more than the two words saved.
    Earth reduces to the old expressions exactly rather than approximately — with `origin_m = 0.0`,
    `(e - 0) / (x - 0)` IS `e / x` — so its ramps cannot move, by algebra and not only by test.
    """

    stops: list[Stop]
    origin_m: float
    extreme_m: float

    def __post_init__(self):
        # A zero-width ramp divides by zero. numpy would hand back nan, `np.rint(nan)` is nan, and
        # the cast to int32 makes it an arbitrary index — a planet rendered in one wrong colour with
        # no exception anywhere. Loud here, where the ramp is declared, is the only cheap place.
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


@dataclass(frozen=True)
class Look:
    """Everything the ramps need to draw one planet.

    A LOOK IS NOT A BODY. The body registry owns geometry — how big the sphere is, how deep its
    pyramid cuts. A look owns colour, and the two are independent: one planet could carry several
    looks (the parked seasonal/preset idea), and a look says nothing about a radius.

    Frozen and whole, so a second look is a second instance rather than a second module. That is the
    entire reason this type exists: today every ramp is a module-level global, and a second planet
    with globals means either copied constants or mutation — and copied look constants have already
    cost this project one overnight re-render of all 203 heroes.

    `sea` IS OPTIONAL, AND `None` IS A STATEMENT RATHER THAN A GAP. It says this planet draws no
    sea. The alternative — a sea ramp written out for a body that declares no oceanmask, so no pixel
    could ever select it — puts a colour nobody chose into the freshness recipe, where it is
    indistinguishable from one that was deliberated over. That is the fabricated-fact trap the
    planet seam already refuses one tier up, where an all-zero ocean raster would have been unable
    to say whether a planet has no sea or its fusion died halfway. Same refusal, same reason.
    """

    land: Surface
    sea: Surface | None


#: Terrella's look, assembled from the constants above rather than restating them — those remain
#: the authored values, and every consumer still reads them directly. This is the seam a second
#: look plugs into, not a second copy of the first.
EARTH_LOOK = Look(
    land=Surface(stops=LAND_STOPS, origin_m=0.0, extreme_m=LAND_MAX_M),
    sea=Surface(stops=SEA_STOPS, origin_m=0.0, extreme_m=SEA_MIN_M),
)

#: Mars's land ramp, hand-authored against measurements of the planet's own colour.
#:
#: A HYPSOMETRIC RAMP IS A FICTION ON MARS, AND THIS ONE KNOWS IT. Earth's ramp works because
#: elevation predicts colour there, through climate and vegetation. Mars's albedo is set by
#: WIND-BLOWN DUST, which does not care about height. Measured by joining the global Viking colour
#: mosaic (`Mars_Viking_ClrMosaic_global_925m.tif`, USGS) to the shipped heightfield at 6.48 M
#: co-registered lon/lat samples, area-weighted: across the elevations holding 64% of the surface
#: (-3000..+3000 m) mean colour moves 7.1 luma against a within-place scatter of 17.9 — a ratio of
#: 0.40. Widened to 92% of the surface it is 1.03. The named albedo features are off any such trend
#: by more than the trend's whole range: Syrtis Major sits at +1,369 m and luma 41.5 where its
#: elevation band averages 84.
#:
#: SO THESE COLOURS ARE CARTOGRAPHIC CONVENTION, NOT A PICTURE OF MARS, and the About page says so
#: to visitors. What was taken from the measurement and what was not:
#:   - HUE, taken in full. Channel ratios survive an uncalibrated tone curve where an absolute level
#:     does not. The mosaic puts Mars at G/R 0.654; Earth's borrowed ramp was shipping 0.780.
#:   - LEVEL, taken in part. The mosaic reads 2.07x darker than the borrowed ramp shipped, which
#:     would put Mars at 0.45x Earth's shipped land. Most of that is the product's own tone curve
#:     and an uncorrected atmospheric haze floor, not the planet: real land albedo is broadly
#:     comparable between the two bodies (Earth's deserts 0.30-0.40 and forests 0.10-0.15 against
#:     Mars's bright regions ~0.30 and dark ~0.10), so pinning Mars to the mosaic while Earth stays
#:     stylised would make the two planets disagree about what a map is. This ships at 0.71x.
#:   - SHAPE, deliberately refused. Mars is genuinely brightest at BOTH ends — Hellas is a dust trap
#:     and Tharsis is dust-mantled — so a faithful ramp would give the deepest basin and the highest
#:     summit the same colour, which is exactly the defect inherited from Earth's shoreline hinge.
#:     Rising monotonically with elevation is what makes height readable at all.
#:
#: THE AUTHORED VALUES ARE NOT WHAT SHIPS. `shade.composite` resaturates by `saturation` 1.18, warms
#: by `warmth` 0.06 and multiplies by a light term at ~1.025 on flat ground, so a stop picked to hit
#: a hue target overshoots it. These were specified as the intended SHIPPED colour and inverted
#: through that chain — a first pass authored directly by eye landed at B/R 0.35 against a 0.55
#: intent. Anything re-tuning them should invert the same way rather than nudging the hex.
MARS_LAND_STOPS: list[Stop] = [
    (0.000, (0.187821, 0.078187, 0.045186)),  # -6000 m  deepest basin floor, ships #804d35
    (0.150, (0.274677, 0.114435, 0.066626)),  # -4185 m  lowland plains
    (0.350, (0.412543, 0.171441, 0.082283)),  # -1765 m  the northern lowlands' own tone
    (0.550, (0.514918, 0.246201, 0.111932)),  #  +655 m  just above the areoid, the modal elevation
    (0.780, (0.597202, 0.366253, 0.187821)),  # +3438 m  southern highlands
    (1.000, (0.658375, 0.520996, 0.337164)),  # +6100 m  Tharsis and the volcanic summits
]

#: Mars. Everything here is decided except whether it ever draws a sea.
#:
#: `sea` is None, and that half is a FACT rather than a placeholder: `fuse/relabel_mars.py` declares
#: a heightfield and no oceanmask, so no pixel can select a sea ramp however carefully one is
#: written. Whether Mars ever draws a sea — none, one chosen shoreline contour, or the family of
#: candidates — is a look decision made on the sphere, and this is the seam it lands on.
#:
#: THE DOMAIN IS MARS'S OWN AND IT IS DERIVED, NOT PREFERRED. Measured over the shipped heightfield,
#: area-weighted on the sphere (cos(lat)-corrected, ~1.05M samples): p1 -5,990 m, p50 -260 m,
#: p99 +6,098 m, true range -7,882 .. +21,014 m. The two below are p1 and p99 rounded, so the ramp
#: does real work across 98% of the surface. The extremes were rejected on the same measurement:
#: only 1.1% of Mars sits above +6,000 m, so keying the ceiling to Olympus Mons would spend most of
#: the ramp on almost nothing — and Olympus still reads, because it reads through the HILLSHADE,
#: which no ramp touches.
#:
#: THE DOMAIN NUMBERS SIT IN THE CONSTRUCTOR, not in named module constants, and the asymmetry with
#: `MARS_LAND_STOPS` above is the naming rule working rather than an inconsistency in it. That list
#: has two readers besides the constructor — `RAMP_GLOBALS` and the tests that compare the assembled
#: `Surface` against it — exactly as `LAND_STOPS` does. These two numbers have none: read once, on
#: the line below, by nothing else. A name for them would be two names for one number, which is the
#: drift this file exists to refuse. The dataclass IS the representation; a constant earns its own
#: name only when something other than the constructor needs it.
MARS_LOOK = Look(
    land=Surface(stops=MARS_LAND_STOPS, origin_m=-6000.0, extreme_m=6100.0),
    sea=None,
)

#: The look each body draws with today.
#:
#: Keyed by SLUG rather than held as a `Body` field, because `pipeline/bodies.py` opens by saying
#: what a body is — "Not a look and not a dataset" — and geometry and colour are separate axes on
#: purpose. Welding a Look into the descriptor would also foreclose the parked idea of one planet
#: carrying several looks. The cost of the separation is that two modules now know the set of
#: planets, so `tests/test_palette.py` holds this dict to the body registry: a planet registered
#: there with no entry here is the failure that renders rather than raises.
LOOK_BY_BODY: dict[str, Look] = {"earth": EARTH_LOOK, "mars": MARS_LOOK}


def look_for(body: str) -> Look:
    """The look a body draws with. Raises on an unknown body and never falls back to Earth's.

    The fallback is the whole point of raising. A body that quietly inherited Earth's ramp would
    render a complete, plausible, internally consistent pyramid in another planet's colours, and
    every gate in the pipeline would pass — the same failure shape `bodies.get` refuses for
    geometry, where the wrong sphere is plausible everywhere and true nowhere.

    CALLED WHERE THE BODY IS KNOWN, NEVER THREADED IN BESIDE IT, and that is a decision rather than
    an omission. The planet seam's rule is the opposite — its rasters are passed as required
    parameters and never looked up — because a raster set is a RUNTIME declaration that varies per
    run and cannot be derived from the body. A look can be, and there is exactly one right answer.
    So a `look` parameter sitting next to a `body` parameter would add nothing but a way for the
    two to disagree: `composite_params(body=MARS, look=EARTH_LOOK)` is a sentence the type checker
    accepts and no reviewer would notice. The cost is that a synthetic body in a test needs a look
    registered, exactly as it needs a radius, and `tests/test_cap_render.py` pays it in a fixture.
    """
    try:
        return LOOK_BY_BODY[body]
    except KeyError:
        raise KeyError(
            f"no look registered for body {body!r}; known: {sorted(LOOK_BY_BODY)}"
        ) from None


def surface(kind: str, *, look: Look) -> Surface:
    """Resolve `'land'`/`'sea'` to its ramp.

    THE ONE PLACE THAT DISPATCH LIVES. It used to be transcribed in four functions —
    `color_relief_rows`, `relief_lut`, `lut_index` and the LUT's own bounds — each independently
    re-deriving which stops and which range a kind meant. Four copies of one mapping is the shape
    of drift this file exists to prevent, and it was sitting inside the file itself.

    `look` IS KEYWORD-ONLY AND REQUIRED, and removing its default was the first move rather than the
    last. With a default, adding `MARS_LOOK` would have left every call site below still drawing
    Earth and nothing would have named one of them; without it, the type checker names all of them
    at once. That is the same reason no field on `Body` may carry a default.
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


def lake_lut(size: int = 256) -> list[RGB8]:
    """`size` sRGB colours sampled uniformly along the lake ramp's 0..1 POSITION axis.

    Uniform in ramp position, not in depth: the caller applies the depth->position curve in
    numpy and indexes this table, which keeps this module numpy-free so Blender's bundled
    interpreter can still import it.
    """
    return [_srgb8(ramp_color(index / (size - 1), LAKE_STOPS)) for index in range(size)]


def color_relief_rows(kind: str, *, look: Look, step: float = 25.0) -> list[tuple[float, RGB8]]:
    """(elevation, sRGB) rows for one surface, densely sampled so `gdaldem`'s linear
    interpolation between rows reproduces the EASE ramp.

    On Earth 'land' maps elevation 0..6000 m and 'sea' maps depth -6000..0 m (deepest first); on
    another body the ends are that body's, and the ramp only has to be correct on its own side —
    the ocean mask selects between them where there are two."""
    ramp = surface(kind, look=look)
    count = round(abs(ramp.span_m) / step)
    # Earth's land starts at 0 and climbs; its sea starts at the abyss and rises to 0; Mars's land
    # starts below the areoid. One expression, because the ramp carries both its ends — see Surface.
    rows = []
    for i in range(count + 1):
        elev = ramp.lowest_m + i * step
        rows.append((elev, _srgb8(ramp_color((elev - ramp.origin_m) / ramp.span_m, ramp.stops))))
    return rows


# LUT resolution in metres. A surface costs `3 * (|span_m| / step + 1)` bytes, so the table is tens
# of KB for any ramp a body could want and the step is chosen for fidelity alone -- no entry count
# is quoted here, because a body-dependent one would be stale the day a second body disagreed.
LUT_STEP_M = 1.0


def relief_lut(kind: str, *, look: Look, step: float = LUT_STEP_M) -> np.ndarray:
    """Elevation -> sRGB LUT for one surface, as a (3, N) uint8 array.

    This is what lets `gdaldem color-relief` be deleted rather than tuned. Measured:
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
    ramp = surface(kind, look=look)
    count = round(abs(ramp.span_m) / step)
    # index 0 is the deepest end for sea and the origin for land, matching color_relief_rows'
    # ordering — both fall out of `Surface.lowest_m` rather than being restated per kind.
    colors = [_srgb8(ramp_color((ramp.lowest_m + index * step - ramp.origin_m) / ramp.span_m,
                                ramp.stops))
              for index in range(count + 1)]
    return np.asarray(colors, dtype=np.uint8).T  # (3, N)


def lut_index(kind: str, elevation, *, look: Look, step: float = LUT_STEP_M) -> np.ndarray:
    """Elevation -> clamped LUT index. The whole optimisation: a divide, not a search.

    Clamping is load-bearing, not defensive: Earth's height raster spans -10,728 m to +7,281 m
    (measured) and Mars's -7,882 m to +21,014 m, i.e. both run past BOTH of their ramp's ends, and
    `gdaldem` clamps to its first/last row. Earth's land-classed pixels can also be negative (Dead
    Sea, -430 m) -- the ocean MASK picks the ramp, never the sign -- so Earth's land ramp must clamp
    those to its 0 m colour. On a body whose ramp starts below the datum there is nothing special
    about a negative pixel at all, which is the point of `origin_m`.
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
    """The exact `gdaldem color-relief` file contents for one surface, incl. the `nv` row.

    Split out from `write_color_relief` so a caller can compare the ramp a run WOULD use
    against the one already on disk without touching the file. The tile pipeline gates its
    color-relief stages on that comparison, which only works if an unchanged palette leaves
    the ramp's mtime alone.
    """
    rows = [f"{elev:.2f} {red} {green} {blue}"
            for elev, (red, green, blue) in color_relief_rows(kind, look=look, step=step)]
    return "\n".join(rows + ["nv 0 0 0", ""])


def write_color_relief(path: Path, kind: str, *, look: Look, step: float = 25.0) -> None:
    """Write a `gdaldem color-relief` file for one surface, with an `nv` nodata row."""
    with open(path, "w") as handle:
        handle.write(color_relief_text(kind, look=look, step=step))
