"""Which producer builds a body's surface layer for the tile composite, and what that one reads.

ONE ANSWER TO "HOW DOES THIS BODY MAKE THAT LAYER" at the Mercator tier. `layers.py` says what a
layer is and which stages read it; `Body.surface_layers` says which ones a planet has; this says who
builds each one, out of what, and how the result becomes a number the composite can blend.

THE CAP TIER'S REGISTRY IS `render/perennial_ice.py`, whose docstring holds the argument this module
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

    from pipeline.render import layer_producers
    producer = layer_producers.producer_for(body, layers.SEA_ICE)
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pipeline import bodies, layers
from pipeline.acquire import download_sim3292
from pipeline.render import lake_depth, mars_ice, seaice, snow, viking_luma


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
    #: The constants THIS producer's own arithmetic reads, for the composite's freshness recipe.
    #:
    #: A tunable reaching a pixel and reaching no recipe leaves a stale composite looking fresh; one
    #: recorded by a body that cannot evaluate it restages that body for output it could not have
    #: changed. Both are silent, and a single gate cannot separate them once two bodies paint the
    #: same layer by different arithmetic — the gate asks whether the body paints ice, which is
    #: right, and the values behind it answered for Earth, which stopped being right. So the code
    #: that READS a constant is the code that declares it.
    #:
    #: THE COMPOSITOR'S OWN CONSTANTS ARE NOT HERE and must not be moved here. `shade.composite`
    #: paints whatever alpha it is handed with `palette.SNOW_RGB`, and grades lake depth with
    #: `palette.LAKE_*`, on every body alike; those are live per LAYER rather than per producer, so
    #: `composite_params` keeps them and gates them on the layer that makes them reachable.
    recipe: Callable[[], dict[str, Any]]
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
    print("warp lake depth -> 3857 ...", flush=True)
    request.out.unlink(missing_ok=True)
    lake_depth.warp_depth_raster(request.bounds, request.width, request.height, request.out)


def _build_persistence(request: LayerBuild) -> None:
    """NSIDC-0791 onto the grid, storing the RAW PACKED Float32 and banded at the window height.

    Banded so each strip is exactly the per-window warp it replaced; `snow.warp_persistence_raster`
    holds why a single whole-grid warp decimates a source this coarse.
    """
    print("warp snow persistence -> 3857 (banded) ...", flush=True)
    request.out.unlink(missing_ok=True)
    snow.warp_persistence_raster(request.bounds, request.width, request.height, request.out,
                                 band_rows=request.band_rows)


def _build_glaciers(request: LayerBuild) -> None:
    """RGI 7.0 burnt onto the grid as a 0/1 Byte mask — the one build here that is not a warp."""
    print("rasterize RGI glaciers -> 3857 ...", flush=True)
    snow.rasterize_glaciers_raster(request.bounds, request.width, request.height, request.out)


def _build_sea_ice(request: LayerBuild) -> None:
    """The 1991-2020 frequency climatology onto the grid, banded like persistence and for its
    reason: a single whole-grid warp of a 0.1 degree source decimates the ice edge."""
    print("warp sea-ice frequency -> 3857 (banded) ...", flush=True)
    request.out.unlink(missing_ok=True)
    seaice.warp_seaice_raster(request.bounds, request.width, request.height, request.out,
                              band_rows=request.band_rows)


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

    BOTH HALVES ARE THIS LAYER'S ANSWER, exactly as the cap tier's two poles are: NSIDC-0791 is
    NH-only and RGI region 19 is excluded, so persistence and glaciers are both zero over the
    continent and it would render on the tan LAND ramp. The patch therefore rides the layer's
    DECLARATION and not its raster — no file could ever switch a latitude-and-land rule off — which
    is why this returns an array even when `raw` is None.

    float64 in both branches. `snow_alpha` returns float64 and `antarctic_snow_mask` float32, so the
    zeros base is what keeps the two paths feeding `shade.composite` the same dtype.
    """
    if window.raw is None:
        persistence_alpha = np.zeros(window.land.shape, dtype=float)
    else:
        persistence_alpha = snow.snow_alpha(snow.unpack_persistence(window.raw),
                                            window.top, window.bottom)
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


def _earth_perennial_ice_recipe() -> dict[str, Any]:
    """`snow_alpha`'s latitude ramp — what `_earth_perennial_ice` grades NSIDC persistence with.

    NOT the whites. `palette.SNOW_RGB` is read by `shade.composite`, which paints whatever alpha the
    union hands it, so it is live on any body that feeds white into that union and belongs to the
    compositor's block rather than to this producer. The split is the difference between computing
    an alpha and painting with one, and it is what lets a second body grade ice its own way while
    both share one white.
    """
    return {"snow_ramp_lat_lo": snow.RAMP_LAT_LO,
            "snow_ramp_lat_hi": snow.RAMP_LAT_HI,
            "snow_ramp_low_min": snow.RAMP_LOW_MIN,
            "snow_ramp_low_max": snow.RAMP_LOW_MAX,
            "snow_ramp_band": snow.RAMP_BAND}


def _earth_sea_ice_recipe() -> dict[str, Any]:
    """`ice_alpha`'s frequency ramp, in both hemispheres' tunings — what `_earth_sea_ice` reads.

    The southern pair is here rather than under a hemisphere gate because one producer evaluates
    both: `_earth_sea_ice` calls `ice_alpha` twice and selects per row, so a window that straddles
    no southern ice still ran on a body whose producer can reach them.
    """
    return {"ice_lo": seaice.ICE_LO, "ice_band": seaice.ICE_BAND,
            "ice_max_alpha": seaice.ICE_MAX_ALPHA,
            "sh_ice_lo": seaice.SH_ICE_LO,
            "sh_ice_max_alpha": seaice.SH_ICE_MAX_ALPHA}


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
    print("grade Viking luma -> Mars ice alpha (polar bands) ...", flush=True)
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


def _mars_ice_build_recipe() -> dict[str, Any]:
    """The two constants `_build_mars_ice` freezes into its raster.

    The luma WEIGHTS are deliberately absent, and covered rather than forgotten: `render/viking_luma`
    records them in its own recipe, so a weight change restages that stage, moves the field's mtime,
    and reaches this raster as a moved SOURCE. Recording them here as well would rebuild correctly
    and claim the coupling lives in two places.
    """
    return {"mars_feather_km": mars_ice.FEATHER_KM,
            "mars_alpha_levels": {pole: list(levels)
                                  for pole, levels in sorted(mars_ice.ALPHA_LEVELS.items())}}


#: Every composite-tier producer that ships, by (body slug, layer name).
#:
#: Five entries and five MECHANISMS — a banded NetCDF warp, a vector rasterize, a banded GeoTIFF
#: warp, a nodata-masked bilinear warp, and Mars's graded-and-feathered polar bands — which is what
#: gives the parameterisation real instances instead of one shape repeated with a different constant.
PRODUCER_BY_BODY_LAYER: dict[tuple[str, str], LayerProducer] = {
    ("earth", layers.LAKE_DEPTH.name): LayerProducer(
        sources=lambda: (lake_depth.LAKE_VRT,),
        build=_build_lake_depth, contribution=_earth_lake_depth, recipe=_no_tunables,
        build_recipe=_no_tunables),
    ("earth", layers.PERENNIAL_ICE.name): LayerProducer(
        sources=lambda: (snow.SP_NC,),
        build=_build_persistence, contribution=_earth_perennial_ice,
        recipe=_earth_perennial_ice_recipe, build_recipe=_no_tunables),
    ("earth", layers.GLACIERS.name): LayerProducer(
        sources=lambda: (snow.RGI_GPKG,),
        build=_build_glaciers, contribution=_earth_glaciers, recipe=_no_tunables,
        build_recipe=_no_tunables),
    ("earth", layers.SEA_ICE.name): LayerProducer(
        sources=lambda: (seaice.SEAICE_SRC,),
        build=_build_sea_ice, contribution=_earth_sea_ice, recipe=_earth_sea_ice_recipe,
        build_recipe=_no_tunables),
    ("mars", layers.PERENNIAL_ICE.name): LayerProducer(
        sources=_mars_ice_sources,
        build=_build_mars_ice, contribution=_mars_perennial_ice,
        # EMPTY, and that is the split working rather than an oversight: `_mars_perennial_ice`
        # reads no constant at all, so there is nothing for the composite to restage on. What this
        # producer can re-tune is frozen into the raster, and `build_recipe` is what tracks it.
        recipe=_no_tunables, build_recipe=_mars_ice_build_recipe),
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
