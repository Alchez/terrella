"""Which producer builds a body's surface layer for the tile composite, and what that one reads.

ONE ANSWER TO "HOW DOES THIS BODY MAKE THAT LAYER" at the Mercator tier. `layers.py` says what a
layer is and which stages read it; `Body.surface_layers` says which ones a planet has; this says who
builds each one, out of what, and how the result becomes a number the composite can blend.

THE CAP TIER'S REGISTRY IS `look/perennial_ice.py`, whose docstring holds the argument this module
inherits rather than restates: a producer is CODE, so bodies differ in machinery and not in
constants. Two registries and not one because the tiers key differently — that one by
`(body, pole)`, this one by `(body, layer)` — and a cap producer paints an AEQD disc where these
paint one window of a Mercator strip. Merging them is a separate claim.

THE HOLE THIS CLOSES, AND THE TIDY THAT REOPENS IT. Every source below used to be a module constant
at a fixed global path, asked `source.exists()` at the warp gate. That question reads "have we
downloaded Earth's data" whatever body is being built, so a second planet declaring one of these
layers passed the gate on Earth's file and had Earth's cryosphere warped onto its own grid — same
latitudes, no missing file, no error, a plausible planet. Asked of the body's own producer, the disk
question is about the body's own files. Collapsing it back to a bare `.exists()` looks like removing
a redundant check and is silent on the only body anyone builds.

A PRODUCER OWNS THE WHOLE ACT — the sources, the build, and the per-window arithmetic — because a
body that registers one half inherits Earth's other half in silence. A Martian raster built by a
Martian producer and then run through Earth's `unpack_persistence` and Earth's latitude ramp is ice
graded by NSIDC's packing convention, which no type and no test could notice.

`contribution` RUNS ON A WORKER THREAD AND MUST TOUCH NO FILESYSTEM. `shade_planet` gathers every
read on the main thread precisely so the compute stays pure; a producer opening a file here would
put GDAL back where rasterio is not thread-safe.

    from pipeline.look import layer_producers
    producer = layer_producers.producer_for(body, layers.SEA_ICE)
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pipeline import bodies, layers, progress
from pipeline.acquire import download_add_rock, download_rgi, download_sim3292
from pipeline.look import lake_depth, mars_ice, palette, seaice, snow, viking_luma


@dataclass(frozen=True)
class LayerBuild:
    """The 3857 grid a producer must land its sources on, and where to leave the result.

    Every field is passed to every producer whether or not it reads it — `band_rows` means nothing
    to a rasterize — on `perennial_ice.CapIceInputs`' rule: a request whose shape depended on which
    producer was registered would have to be built per body, which puts a body branch back into the
    caller this seam exists to remove.
    """

    #: (left, bottom, right, top) in EPSG:3857, the height raster's own bounds.
    bounds: tuple[float, float, float, float]
    width: int
    height: int
    #: The file to write, already named from `Layer.warped_basename` under this body's work dir.
    out: Path
    #: The band height for a producer that warps a coarse source in latitude strips. It equals the
    #: composite's window height, which is what makes a banded mosaic byte-identical to the
    #: per-window warps it replaced (`snow.warp_persistence_raster`).
    band_rows: int


@dataclass(frozen=True)
class LayerWindow:
    """One window of the composite, as a producer is allowed to see it.

    `raw` is this producer's OWN slice and None when its raster was never built; the masks and the
    geometry are shared, and are here for the producers that grade against them rather than against
    a file. Same all-fields-always rule as `LayerBuild` above.
    """

    raw: np.ndarray | None
    #: The planet seam's water classes, or None on a body whose seam emitted no water mask.
    watercode: np.ndarray | None
    #: `~(ocean | water)` for this window — the composite's own definition of land.
    land: np.ndarray
    #: True latitude in degrees per ROW (1-D). A Mercator window has rows of constant latitude,
    #: which is what separates this from the cap tier's per-pixel field.
    latitude: np.ndarray
    #: GROUND metres per pixel, per ROW (1-D) — never Mercator map metres. Carried for the same
    #: reason `perennial_ice.CapIceInputs` carries its scalar twin, and named the same thing: a
    #: producer turning a ground distance into pixels needs both the cos(latitude) stretch and the
    #: body's own `ground_metres_per_mercator_unit`, and this window knows neither on its own. It is
    #: per row here and scalar there because a Mercator row has one resolution and an AEQD disc has
    #: one for the whole disc.
    ground_metres_per_px: np.ndarray
    #: The window's latitude span in 3857 metres, for a producer whose ramp needs the extent rather
    #: than the per-row value.
    top: float
    bottom: float


@dataclass(frozen=True)
class LayerProducer:
    """One body's answer for one layer at the composite tier: what it reads, builds and contributes.

    `sources` is a CALLABLE and never a tuple literal, for the reason `perennial_ice.CapIce` records
    at length: a literal evaluates its paths once, at import, so a caller that redirects the data
    root is answered with the path from before the redirect. Every path here hangs off `paths.DATA`.
    """

    sources: Callable[[], tuple[Path, ...]]
    #: Land the sources on the grid and leave the file at `LayerBuild.out`. Prints its own line, so
    #: the pass says "rasterize" where it rasterizes and "warp" where it warps.
    build: Callable[[LayerBuild], None]
    #: This layer's number for one window, or None when it has nothing to add. Returning None rather
    #: than zeros keeps a layer that contributes nothing out of the union entirely.
    contribution: Callable[[LayerWindow], "np.ndarray | None"]
    #: The `(sunlit, shadowed)` white `shade.composite` paints this producer's alpha with, or None
    #: where the layer's number is not painted as a white at all (lake depth, which takes a ramp).
    #:
    #: Each end may be a bare RGB triple or an array shaped per row, so a producer whose material
    #: changes across the window says so itself. Mars's does: its two poles measure as different
    #: colours, 1.053 against 1.291 in red:violet, and one producer covers both hemispheres.
    #:
    #: WHY THIS IS THE PRODUCER'S AND NOT THE COMPOSITOR'S. It used to be a module global read
    #: inside `shade.composite`, on the argument that one white serves every body's perennial ice.
    #: That was true while Earth was the only body painting any, and it stopped being true twice
    #: over — once when a second planet arrived and inherited Earth's white by omission, and again
    #: when that planet turned out to need two of its own. A global read cannot show a reader that
    #: either fact exists, which is the whole failure: the code that decided to paint a pixel is the
    #: only code that knows what the pixel is made of.
    paint: Callable[[LayerWindow], "tuple[Any, Any] | None"]
    #: The constants `contribution` reads, for the freshness recipe of every stage that grades.
    #:
    #: A tunable reaching a pixel and reaching no recipe leaves a stale output looking fresh; one
    #: recorded by a body that cannot evaluate it restages that body for output it could not have
    #: changed. Both are silent, and a single gate cannot separate them once two bodies paint the
    #: same layer by different arithmetic — the gate asks whether the body paints ice, which is
    #: right, and the values behind it answered for Earth, which stopped being right. So the code
    #: that READS a constant is the code that declares it.
    #:
    #: Still not here: `palette.LAKE_*`. Lake depth really is one ramp on every body that has lakes,
    #: it is not a white, and no second instance has contradicted it — so it stays in
    #: `composite_params` until one does.
    contribution_recipe: Callable[[], dict[str, Any]]
    #: The constants `paint` reads, for the freshness recipe of every stage that paints.
    #:
    #: NOT A RETREAT FROM RECORDING THE WHITES — they are still the producer's and still restage
    #: the composite and both caps. The split exists because `prep_block` grades without painting:
    #: it folds the alpha and lets Blender colour it, so recording the whites there would put a
    #: night of GPU behind a colour tweak that cannot reach one raytraced pixel.
    #:
    #: Empty where the number is not a white at all, exactly as `paint` returns None.
    paint_recipe: Callable[[], dict[str, Any]]
    #: The constants `build` bakes INTO the raster, which is a different set from `recipe` above and
    #: cannot share its machinery.
    #:
    #: WHY THE SPLIT IS NOT TIDINESS. `recipe` reaches `composite_params`, so changing one of its
    #: values restages the composite — which is exactly right for a constant read per window, because
    #: the rerun re-reads it. A constant consumed at BUILD time is already frozen into the file on
    #: disk, and `warp_needs_rebuild` is closed over PATHS: no Python value can reach it. Recording a
    #: build-time constant in `recipe` alone therefore produces the worst available outcome — a full
    #: composite restage that repaints from the unchanged raster and lands the same wrong pixels,
    #: looking for all the world like the change applied.
    #:
    #: Materialised by `warp_inputs` through `freshness.write_if_changed`, whose whole purpose is to
    #: let a constant stand in as an mtime dependency: the file moves if and only if a value moved.
    #:
    #: EMPTY IS THE ANSWER FOR EVERY EARTH PRODUCER and that is a property of them rather than an
    #: omission — all four are pure transport, landing a source on the grid and storing it raw, with
    #: every grading constant read later in `contribution`. An empty dict writes no file and adds no
    #: source, so Earth's gate stays byte-for-byte what it was and the optional-layer warps do not
    #: restage. Mars's ice is the first build to grade before it writes.
    build_recipe: Callable[[], dict[str, Any]]


def _build_lake_depth(request: LayerBuild) -> None:
    """GLOBathy onto the grid, warped ONCE here rather than per window.

    It is an 83k-source VRT and a many-source VRT re-reads every source on each touch, the same
    reason the tiler materialises before cutting.
    """
    progress.stage("warp lake depth -> 3857 ...")
    request.out.unlink(missing_ok=True)
    lake_depth.warp_depth_raster(request.bounds, request.width, request.height, request.out)


def _build_persistence(request: LayerBuild) -> None:
    """NSIDC-0791 onto the grid, storing the RAW PACKED Float32 and banded at the window height.

    Banded so each strip is exactly the per-window warp it replaced; `snow.warp_persistence_raster`
    holds why a single whole-grid warp decimates a source this coarse.
    """
    progress.stage("warp snow persistence -> 3857 (banded) ...")
    request.out.unlink(missing_ok=True)
    snow.warp_persistence_raster(request.bounds, request.width, request.height, request.out,
                                 band_rows=request.band_rows)


def _build_glaciers(request: LayerBuild) -> None:
    """RGI 7.0 burnt onto the grid as a 0/1 Byte mask — the one build here that is not a warp.

    Reads the source path and the layer name off the acquirer that writes them, at call time, for
    the reason `_build_antarctic_rock` states beside the same pattern.
    """
    progress.stage("rasterize RGI glaciers -> 3857 ...")
    snow.rasterize_glaciers_raster(request.bounds, request.width, request.height, request.out,
                                   gpkg=download_rgi.GPKG, layer=download_rgi.LAYER)


def _build_sea_ice(request: LayerBuild) -> None:
    """The 1991-2020 frequency climatology onto the grid, banded like persistence and for its
    reason: a single whole-grid warp of a 0.1 degree source decimates the ice edge."""
    progress.stage("warp sea-ice frequency -> 3857 (banded) ...")
    request.out.unlink(missing_ok=True)
    seaice.warp_seaice_raster(request.bounds, request.width, request.height, request.out,
                              band_rows=request.band_rows)


def _build_antarctic_rock(request: LayerBuild) -> None:
    """SCAR ADD's outcrop burnt onto the grid as a 0/1 Byte mask — the glacier burn's twin.

    Reads the source path and the layer name off the acquirer that writes them, at call time. The
    acquirer is the one home for both: it chose the filename and it chose `-nln rock`, so a second
    spelling here would agree with it until one of them moved, and the failure is an absent file
    read as "this body has no exposed rock".
    """
    progress.stage("rasterize ADD Antarctic rock -> 3857 ...")
    snow.rasterize_antarctic_rock(request.bounds, request.width, request.height, request.out,
                                  gpkg=download_add_rock.GPKG, layer=download_add_rock.LAYER)


def _earth_antarctic_rock(_window: LayerWindow) -> "np.ndarray | None":
    """None on every window, and that is this layer's whole answer at this tier.

    THE ONE PRODUCER THAT BUILDS A RASTER AND CONTRIBUTES NOTHING. What consumes the raster is
    `fold_white`, which takes it back OUT of the finished union as a `WHITE_EXCLUSIONS` member;
    `gather` reads the slice straight off `layer_raw` and returns it beside the contributions, so it
    reaches no producer at all. Returning an array here instead would put the rock into
    `fold_white`'s maximum and paint the outcrop the very white this layer exists to remove — an
    inversion that renders as a perfectly plausible ice sheet.
    """
    return None


def _earth_lake_depth(window: LayerWindow) -> "np.ndarray | None":
    """Depth in metres, zeroed off watermask class 2 — the one contribution that is not an alpha.

    The watercode cannot be None while the depth raster is not: `planet_seam` refuses a body that
    declares this layer with no water mask, which is what `Layer.requires_raster` records.
    """
    if window.raw is None or window.watercode is None:
        return None
    return lake_depth.lakes_only(window.raw, window.watercode)


def _earth_perennial_ice(window: LayerWindow) -> "np.ndarray | None":
    """NSIDC-0791 persistence, plus the forced Antarctic patch that has no dataset behind it.

    BOTH HALVES ARE THIS LAYER'S ANSWER, exactly as the cap tier's two poles are. NSIDC-0791 covers
    Antarctica and saturates over it (median 1.000 per band 60-90S), but 9-14% of the continent's
    land arrives as clustered fill that unpacks to 0.0, which RGI's peripheral region 19 does not
    reach either — so the patch exists to close those holes rather than to substitute for an absent
    dataset. The holes are IN
    the file, which is what makes the patch ride the layer's DECLARATION and not its raster: no
    file could ever switch a latitude-and-land rule off, and this returns an array even when `raw`
    is None.

    float64 in both branches. `snow_alpha` returns float64 and `antarctic_snow_mask` float32, so the
    zeros base is what keeps the two paths feeding `shade.composite` the same dtype.

    NO ROCK REACHES THIS PRODUCER, and that is a correctness boundary rather than a tidy. The
    outcrop used to be subtracted from the patch here, inside ONE TERM of the maximum below, where
    `persistence_alpha` re-claimed 63% of it — a negative has no home in a positive claim. It is now
    a `WHITE_EXCLUSIONS` member applied after the whole union folds, so this producer answers only
    the question it can answer: where Earth's perennial ice IS.
    """
    if window.raw is None:
        persistence_alpha = np.zeros(window.land.shape, dtype=float)
    else:
        persistence_alpha = snow.soften_source_cells(
            snow.snow_alpha(snow.unpack_persistence(window.raw), window.top, window.bottom),
            window.ground_metres_per_px)
    return np.maximum(persistence_alpha,
                      snow.antarctic_snow_mask(window.land, window.latitude))


def _earth_glaciers(window: LayerWindow) -> "np.ndarray | None":
    """RGI's 0/1 mask as float, to be maxed into the same union perennial ice feeds."""
    return None if window.raw is None else window.raw.astype(float)


def _earth_sea_ice(window: LayerWindow) -> "np.ndarray | None":
    """Frequency -> smoothstep, toned in the southern hemisphere.

    South of the equator the pack takes the cap's fainter, pulled-in fringe (`seaice.SH_ICE_*`), or
    the full-strength Antarctic belt reads as a bright halo — proven on the cap. No window straddles
    both hemispheres' ice and the equator is ice-free, so the per-row split is exact.
    """
    if window.raw is None:
        return None
    frequency = seaice.unpack_seaice(window.raw)
    ice_alpha = seaice.ice_alpha(frequency)
    southern = window.latitude < 0.0
    if southern.any():
        toned = seaice.ice_alpha(frequency, ice_lo=seaice.SH_ICE_LO,
                                 ice_max_alpha=seaice.SH_ICE_MAX_ALPHA)
        ice_alpha = np.where(southern[:, None], toned, ice_alpha)
    return ice_alpha


def _no_tunables() -> dict[str, Any]:
    """A producer whose arithmetic has no constants of its own.

    Empty is a statement and not an omission, on `CapIce.sources`' rule. Lake depth is a warp and
    the glacier mask a rasterize: both land a source on the grid and hand the number through
    unmodified, so there is nothing here to re-tune. What paints them — the lake ramp, the whites —
    belongs to the compositor. A producer that grows a constant declares it here, and the bodies
    that read it restage; that is the field working, not a change of policy.
    """
    return {}


def _earth_paint(_window: "LayerWindow | None" = None) -> tuple[Any, Any]:
    """Earth's one ice white, shared by its perennial ice, its glaciers and its cap producers.

    ONE HOME, DECLARED BY EACH READER RATHER THAN COPIED INTO IT. Earth's two composite-tier ice
    layers feed a single union and must agree, and the caps must agree with both or the crossfade
    changes colour across the seam. Reading `palette` from one function keeps that a fact rather
    than a coincidence between four registry entries.
    """
    return palette.SNOW_RGB, palette.SNOW_SHADOW_RGB


def _earth_perennial_ice_recipe() -> dict[str, Any]:
    """What `_earth_perennial_ice` GRADES with: `snow_alpha`'s latitude ramp and the softening.

    THE SOFTENING'S TWO CONSTANTS ARE HERE FOR THE REASON `snow`'s RAMP_* ARE, and the arithmetic
    they key is spatial rather than tonal, which is what makes leaving them out so quiet: a
    re-tuned edge width changes no colour, no threshold and no file, so a stale output painted
    with the old sigma reads exactly as fresh as a new one. `SOFTEN_BAND_TOLERANCE` is deliberately
    NOT recorded: it bounds the banding's own approximation error rather than choosing an answer,
    so moving it can only make the same intended output more or less exactly computed.
    """
    return {"snow_ramp_lat_lo": snow.RAMP_LAT_LO,
            "snow_ramp_lat_hi": snow.RAMP_LAT_HI,
            "snow_ramp_low_min": snow.RAMP_LOW_MIN,
            "snow_ramp_low_max": snow.RAMP_LOW_MAX,
            "snow_ramp_band": snow.RAMP_BAND,
            "snow_soften_fraction": snow.SOFTEN_FRACTION,
            "snow_source_cell_m": snow.SOURCE_CELL_M}


def _earth_paint_recipe() -> dict[str, Any]:
    """Earth's one ice white as a recipe, declared by BOTH producers that paint in it.

    From `_earth_paint`, the same function their `paint` returns, so the recipe cannot record a
    colour the producer does not use. Both declare it and the merge is by key, so the duplicate is
    one value seen twice rather than two free to drift.
    """
    lit, shadow = _earth_paint()
    return {"snow_rgb": lit, "snow_shadow_rgb": shadow}


def _earth_sea_ice_recipe() -> dict[str, Any]:
    """`ice_alpha`'s frequency ramp, in both hemispheres' tunings — what `_earth_sea_ice` grades by.

    The southern pair is here rather than under a hemisphere gate because one producer evaluates
    both: `_earth_sea_ice` calls `ice_alpha` twice and selects per row, so a window that straddles
    no southern ice still ran on a body whose producer can reach them.
    """
    return {"ice_lo": seaice.ICE_LO, "ice_band": seaice.ICE_BAND,
            "ice_max_alpha": seaice.ICE_MAX_ALPHA,
            "sh_ice_lo": seaice.SH_ICE_LO,
            "sh_ice_max_alpha": seaice.SH_ICE_MAX_ALPHA}


def _earth_sea_ice_paint_recipe() -> dict[str, Any]:
    """The pair `seaice.ice_paint` hands both this tier and the caps, so one re-tune moves both."""
    lit, shadow = seaice.ice_paint()
    return {"ice_rgb": lit, "ice_shadow_rgb": shadow}


def _mars_ice_sources() -> tuple[Path, ...]:
    """The brightness field and both mapped units — every file the Mars build opens."""
    return (viking_luma.luma_path(),
            *(download_sim3292.unit_path(unit) for unit in mars_ice.NORTH_UNITS))


def _build_mars_ice(request: LayerBuild) -> None:
    """Viking luma graded, cut to the mapped units and feathered — the one build that is not a warp.

    THE ONLY BUILD HERE THAT GRADES BEFORE IT WRITES. Its siblings land a source on the grid and
    store it raw, leaving every constant to `contribution`; this one bakes `FEATHER_KM` and
    `ALPHA_LEVELS` into the file, because the feather is a distance transform and a distance
    transform cannot be computed from one window — a pixel's nearest ice can lie outside whatever
    slice is in hand. That asymmetry is what `build_recipe` exists for, and why this producer's
    `recipe` is empty rather than carrying those two.
    """
    progress.stage("grade Viking luma -> Mars ice alpha (polar bands) ...")
    request.out.unlink(missing_ok=True)
    mars_ice.build_alpha_raster(
        field=viking_luma.luma_path(), field_nodata=viking_luma.NODATA,
        bounds=request.bounds, width=request.width, height=request.height, out=request.out,
        ground_metres_per_map_unit=bodies.ground_metres_per_mercator_unit(bodies.get("mars")))


def _mars_perennial_ice(window: LayerWindow) -> "np.ndarray | None":
    """The alpha the build already computed, as float64 — this window and nothing else.

    NOTHING IS GRADED HERE, the mirror image of Earth's producer, and it follows from where the
    feather has to run rather than from taste. None when the raster was never built, per the
    contract: no file, no ice, and no zeros pushed into the union to be blended against.

    float64 because `shade.composite` blends whichever body's answer it is handed alongside Earth's,
    and a narrower dtype from one of them shifts the other's blend sub-DN.
    """
    if window.raw is None:
        return None
    return np.asarray(window.raw, dtype=float)


def _mars_ice_paint(window: LayerWindow) -> tuple[Any, Any]:
    """Mars's white, chosen PER ROW, because its two poles are not the same colour.

    Measured off the Viking mosaic over each pole's own painted extent, weighted by the alpha this
    producer hands over: red:violet 1.053 north against 1.291 south. Their own surrounding ground
    reads 1.231 and 1.807, and normalising each cap by its own ground leaves most of the gap intact
    — so the difference belongs to the ice, not to what surrounds it or to how it was imaged.

    ONE PRODUCER SPANS BOTH HEMISPHERES HERE, unlike the cap tier where the pole is the registry
    key, which is exactly why the paint has to be able to vary within a window rather than being one
    constant per producer. Returned as `(3, H, 1)`, which the blend broadcasts for free.

    The equator is a hemisphere boundary and never an ice boundary: Mars carries no ice within 76
    degrees of it, so the row this splits on is one no alpha reaches.
    """
    northern = np.asarray(window.latitude) >= 0.0
    def per_row(north: Any, south: Any) -> np.ndarray:
        return np.where(northern[None, :, None],
                        np.asarray(north, dtype=np.float32).reshape(3, 1, 1),
                        np.asarray(south, dtype=np.float32).reshape(3, 1, 1))
    return (per_row(palette.MARS_ICE_WHITE["north"][0], palette.MARS_ICE_WHITE["south"][0]),
            per_row(palette.MARS_ICE_WHITE["north"][1], palette.MARS_ICE_WHITE["south"][1]))


def _mars_ice_paint_recipe() -> dict[str, Any]:
    """Both whites, flat and per pole, so a re-tune of either one restages the composite.

    FOUR KEYS RATHER THAN EARTH'S TWO, and the asymmetry is the point: a recipe records what its own
    body evaluates, and Mars evaluates two pairs where Earth evaluates one. Recording Earth's shape
    here would have to invent a single Martian white that no pixel is painted with.

    Flat keys rather than a nested dict so a `git log -S "snow_rgb_south"` finds the value's history
    the same way it finds Earth's.
    """
    return {f"snow_{end}_{pole}": list(value)
            for pole, pair in sorted(palette.MARS_ICE_WHITE.items())
            for end, value in (("rgb", pair[0]), ("shadow_rgb", pair[1]))}


def _mars_ice_build_recipe() -> dict[str, Any]:
    """The two constants `_build_mars_ice` freezes into its raster.

    The luma WEIGHTS are deliberately absent, and covered rather than forgotten: `look/viking_luma`
    records them in its own recipe, so a weight change restages that stage, moves the field's mtime,
    and reaches this raster as a moved SOURCE. Recording them here as well would rebuild correctly
    and claim the coupling lives in two places.
    """
    return {"mars_feather_km": mars_ice.FEATHER_KM,
            "mars_alpha_levels": {pole: list(levels)
                                  for pole, levels in sorted(mars_ice.ALPHA_LEVELS.items())}}


#: Every composite-tier producer that ships, by (body slug, layer name).
#:
#: Six entries and six MECHANISMS — a banded NetCDF warp, a vector rasterize, a banded GeoTIFF warp,
#: a nodata-masked bilinear warp, Mars's graded-and-feathered polar bands, and a vector rasterize
#: whose result no pixel of its own is painted from — which is what gives the parameterisation real
#: instances instead of one shape repeated with a different constant.
PRODUCER_BY_BODY_LAYER: dict[tuple[str, str], LayerProducer] = {
    ("earth", layers.LAKE_DEPTH.name): LayerProducer(
        sources=lambda: (lake_depth.LAKE_VRT,),
        # None, not a white: this producer's number is a DEPTH, graded by the lake ramp. The field
        # existing and being answered "not applicable" is what keeps that visible.
        build=_build_lake_depth, contribution=_earth_lake_depth, paint=lambda _window: None,
        contribution_recipe=_no_tunables, paint_recipe=_no_tunables,
        build_recipe=_no_tunables),
    ("earth", layers.PERENNIAL_ICE.name): LayerProducer(
        sources=lambda: (snow.SP_NC,),
        build=_build_persistence, contribution=_earth_perennial_ice, paint=_earth_paint,
        contribution_recipe=_earth_perennial_ice_recipe, paint_recipe=_earth_paint_recipe,
        build_recipe=_no_tunables),
    ("earth", layers.GLACIERS.name): LayerProducer(
        sources=lambda: (download_rgi.GPKG,),
        # Pure transport: the mask is rasterized and handed through, so there is nothing to grade
        # and the white is the whole of what this producer reads.
        build=_build_glaciers, contribution=_earth_glaciers, paint=_earth_paint,
        contribution_recipe=_no_tunables, paint_recipe=_earth_paint_recipe,
        build_recipe=_no_tunables),
    ("earth", layers.SEA_ICE.name): LayerProducer(
        sources=lambda: (seaice.SEAICE_SRC,),
        # `seaice.ice_paint`, not a literal: the cap tier reads that same function directly, so the
        # sentence "sea ice is painted in this pair" has one home across both tiers.
        build=_build_sea_ice, contribution=_earth_sea_ice,
        paint=lambda _window: seaice.ice_paint(),
        contribution_recipe=_earth_sea_ice_recipe, paint_recipe=_earth_sea_ice_paint_recipe,
        build_recipe=_no_tunables),
    ("earth", layers.ANTARCTIC_ROCK.name): LayerProducer(
        sources=lambda: (download_add_rock.GPKG,),
        # None for both, and neither is a gap. The number this layer builds is consumed by the
        # perennial-ice producer rather than blended, so there is no contribution to paint and no
        # white to name — the two fields existing and being answered "not applicable" is what keeps
        # that visible, exactly as lake depth's `paint` does for a number that is a depth.
        build=_build_antarctic_rock, contribution=_earth_antarctic_rock,
        paint=lambda _window: None,
        contribution_recipe=_no_tunables, paint_recipe=_no_tunables,
        build_recipe=_no_tunables),
    ("mars", layers.PERENNIAL_ICE.name): LayerProducer(
        sources=_mars_ice_sources,
        build=_build_mars_ice, contribution=_mars_perennial_ice, paint=_mars_ice_paint,
        # THE ONLY PRODUCER THAT ANSWERS ALL THREE FIELDS DIFFERENTLY, which is what keeps the
        # split honest: it grades nothing per window, declares two whites per pole, and bakes a
        # feather and its alpha levels into the raster. One field could not carry that.
        contribution_recipe=_no_tunables, paint_recipe=_mars_ice_paint_recipe,
        build_recipe=_mars_ice_build_recipe),
}


def producer_for(body: bodies.Body, layer: layers.Layer) -> LayerProducer:
    """The producer this body builds `layer` with, at the composite tier.

    RAISES RATHER THAN FALLING BACK, on `perennial_ice.cap_ice`'s rule and for its sharper reason: a
    body inheriting Earth's producer by omission warps Earth's data onto another world and paints it
    as that world's, with nothing missing and nothing to report. Only asked of a body that declares
    the layer, so the raise is unreachable in a correct configuration and is exactly a statement that
    the two declarations disagree.
    """
    try:
        return PRODUCER_BY_BODY_LAYER[(body.name, layer.name)]
    except KeyError:
        raise KeyError(
            f"{body.name} declares the {layer.name} layer but registers no composite producer; "
            f"known: {sorted(PRODUCER_BY_BODY_LAYER)}"
        ) from None


def producers_for(body: bodies.Body, vocabulary: frozenset[str]
                  ) -> list[tuple[layers.Layer, LayerProducer]]:
    """The producers a stage with this vocabulary runs on this body, in `LAYERS` order.

    ONE ANSWER, because `gather` runs them and `constants_for` records what they read: a layer one
    saw and the other did not is a constant reaching a pixel with no recipe behind it.

    ASKED OF THE BODY, NEVER OF THE RASTER ON DISK. A producer runs because the planet DECLARED the
    layer, which is what lets Earth's perennial ice carry the forced Antarctic patch — a rule with
    no file behind it, so no missing raster could switch it off.
    """
    return [(layer, producer_for(body, layer)) for layer in layers.WARPED_LAYERS
            if layer.name in vocabulary and layer.name in body.surface_layers]


def constants_for(body: bodies.Body, vocabulary: frozenset[str], *,
                  painted: bool) -> dict[str, Any]:
    """Every constant this body's producers read for `vocabulary`, as one stage's freshness record.

    `vocabulary` IS THE SAME ARGUMENT THE CALLER HANDS `gather`, so a stage cannot run a producer
    without passing the set that decides whether its constants are recorded.

    `painted` is what the stage DOES with the answer, derivable from no layer or body: the
    composite blends contribution and white together, `prep_block` folds the alpha alone.

    ONE PARAMETER RATHER THAN TWO FUNCTIONS: a caller that must merge two calls can forget the
    second and get a plausible, shorter recipe, which is the failure being closed here.
    """
    recorded: dict[str, Any] = {}
    for _layer, producer in producers_for(body, vocabulary):
        recorded.update(producer.contribution_recipe())
        if painted:
            recorded.update(producer.paint_recipe())
    return recorded


#: The layers whose contributions merge into ONE white, in the order they fold.
#:
#: SEA ICE IS ABSENT AND THAT IS THE POINT. `shade.composite` gates it on the ocean selector where
#: this union paints land, so folding it in here would paint pack ice onto the shore it borders.
#: Lake depth is absent for a different reason: it is a ramp position and not a white at all.
WHITE_UNION: tuple[layers.Layer, ...] = (layers.PERENNIAL_ICE, layers.GLACIERS)

#: The layers that REMOVE white, applied after that union and never folded into it.
#:
#: THE NEGATIVE HALF OF THE SAME LAW, and it exists because `fold_white` is a maximum over POSITIVE
#: claims. Every member of `WHITE_UNION` says "this pixel is ice"; "this pixel is definitively NOT
#: ice" has no representation in a maximum of non-negative arrays at all. Before this tuple the only
#: way to say it was to subtract inside one union member's own contribution — where every OTHER
#: member independently outvotes it. Measured, that cost the Antarctic outcrop 63% of its
#: subtraction, because NSIDC-0791 persistence reads a median 1.0000 on the very rock SCAR ADD maps.
#:
#: BESIDE THE UNION AND NOT IN `layers`, because the two are one law and a reader who finds either
#: half needs the other: what makes a new white source safe to add is that this half lands after all
#: of them. A layer belongs here rather than in the union when its answer is about a pixel NOT being
#: white, which is a different question from how strongly something else claims it.
WHITE_EXCLUSIONS: tuple[layers.Layer, ...] = (layers.ANTARCTIC_ROCK,)


def white_law(body: bodies.Body, vocabulary: frozenset[str]) -> dict[str, list[str]]:
    """Which of `vocabulary` this body folds INTO the white and which it takes back OUT.

    A LAW RATHER THAN A CONSTANT, which is why it is not `constants_for`'s: a producer's recipe says
    how it grades its own claim, and no producer can see whether that claim is added or subtracted.
    Nothing else in a recipe stands in for this. `producers_for` walks `WARPED_LAYERS`, so a layer's
    producer is recorded whichever tuple it sits in, and `glaciers` and `antarctic_rock` both grade
    nothing per window — a layer changing side moves no other entry anywhere.

    Filtered as `gather` filters, so a stage records the law it runs and no other.

    LISTS AND NOT SETS: order is part of the law, since `fold_white`'s `merge` caller is not
    commutative, and these are recipe values a set could not serialise in a stable order anyway.

    NARROWED BY `producers_for` RATHER THAN BY ITS OWN COPY OF THAT FILTER, so the law recorded is
    the law the stage runs by construction: a fourth spelling of "this body, this vocabulary" is a
    fourth thing to keep in step, and this one has to agree with `gather` or the record is fiction.
    """
    runs = {layer.name for layer, _ in producers_for(body, vocabulary)}

    def folded(law: tuple[layers.Layer, ...]) -> list[str]:
        return [layer.name for layer in law if layer.name in runs]

    return {"white_union": folded(WHITE_UNION),
            "white_exclusions": folded(WHITE_EXCLUSIONS)}


def gather(body: bodies.Body, layer_raw: dict[str, "np.ndarray | None"], window: LayerWindow,
           vocabulary: frozenset[str]) -> tuple[dict[str, np.ndarray],
                                                dict[str, tuple[Any, Any]],
                                                dict[str, np.ndarray]]:
    """Every layer `vocabulary` reads, as this body's producers answer for one window.

    WHICH PRODUCERS RUN IS `producers_for`'S ANSWER and not a condition restated here, so that this
    and `constants_for` cannot disagree about the set — see there for why the declaration is asked
    of the body rather than of the rasters on disk.

    `vocabulary` IS THE CALLER'S STAGE VIEW, on `layers.layers_off`'s rule: the composite reads
    `COMPOSITE_LAYERS` and the block render `BLOCK_LAYERS`, and the two genuinely disagree.

    A paint is asked ONLY of a layer that contributed, so a producer that paints nothing this window
    never has to answer what colour it would have used.

    THE EXCLUSIONS ARE READ HERE, ONCE, because this is the only place holding both `layer_raw` and
    the body's declarations. They are the third return rather than a shared field on the window: no
    producer is allowed to see them, since the whole point of `WHITE_EXCLUSIONS` is that a negative
    is applied to the FOLD and not inside any one producer's positive answer.

    ASKED OF THE BODY AND OF THE VOCABULARY, NEVER OF THE DICT. One supplier keys `layer_raw` on
    `path.exists()` alone, so a slice can arrive for a body that declares no such layer, and a stage
    that does not read the layer must get the un-excluded answer exactly.
    """
    exclusions = {layer.name: raw for layer in WHITE_EXCLUSIONS
                  if layer.name in vocabulary and layer.name in body.surface_layers
                  and (raw := layer_raw.get(layer.name)) is not None}
    contributions: dict[str, np.ndarray] = {}
    paints: dict[str, tuple[Any, Any]] = {}
    for layer, producer in producers_for(body, vocabulary):
        seen = dataclasses.replace(window, raw=layer_raw[layer.name])
        value = producer.contribution(seen)
        if value is None:
            continue
        contributions[layer.name] = value
        paint = producer.paint(seen)
        if paint is not None:
            paints[layer.name] = paint
    return contributions, paints, exclusions


def fold_white(contributions: dict[str, np.ndarray], shape: tuple[int, ...], *,
               exclusions: dict[str, np.ndarray],
               merge: "Callable[[Any, np.ndarray, str, np.ndarray], Any] | None" = None
               ) -> tuple[np.ndarray, Any]:
    """Fold `WHITE_UNION`'s contributions into the one alpha `shade.composite` paints as snow,
    then take `WHITE_EXCLUSIONS` back out of the result.

    float64 base because that is what `snow_alpha` returns and what the maxima promote to; a float32
    base would narrow every pixel the compositor blends. `np.maximum` reorders freely and every
    contribution is non-negative, so which layer lands first cannot move a bit — the fixed order is
    for the caller that folds something ALONGSIDE the alpha and is not commutative.

    `merge` is that caller. It receives the value carried so far, the alpha BEFORE this layer folds
    in, and this layer's name and contribution, and it exists so the compositor's paint merge reads
    the same running alpha this fold produces rather than recomputing a second one beside it. Left
    None by a caller that wants the alpha alone, which is every caller that does not paint.

    THE EXCLUSIONS LAND AFTER THE MAXIMUM AND THAT ORDER IS THE WHOLE POINT. Subtracting inside any
    one contribution leaves every other union member free to re-claim the pixel, which is what a
    maximum of positives does by construction — so an exclusion applied earlier is not a weaker fix,
    it is a fix that a second white source silently undoes. `WHITE_EXCLUSIONS` holds the argument.

    REQUIRED RATHER THAN DEFAULTED, because a caller that skips the negative gets a plausible white
    rather than an error, and a plausible white is precisely the failure this parameter exists to
    end. Pass an empty dict to mean "this window excludes nothing" and say so deliberately.

    `merge` still sees pre-exclusion alphas, and that is correct rather than tolerated: it decides
    which layer's COLOUR wins a pixel, and `shade.composite` multiplies that colour by the alpha
    returned here — which is zero on every excluded pixel, so the colour there reaches nothing.
    """
    alpha = np.zeros(shape, dtype=float)
    carried = None
    for layer in WHITE_UNION:
        contribution = contributions.get(layer.name)
        if contribution is None:
            continue
        if merge is not None:
            carried = merge(carried, alpha, layer.name, contribution)
        alpha = np.maximum(alpha, contribution)
    for layer in WHITE_EXCLUSIONS:
        removed = exclusions.get(layer.name)
        if removed is None:
            continue
        alpha = np.where(np.asarray(removed).astype(bool), 0.0, alpha)
    return alpha, carried
