"""Which producer builds a body's surface layer on the Mercator grid, and what that one reads.

`layers.py` says what a layer is; `Body.surface_layers` says which ones a planet has; this says who
builds each one, out of what, and how the result becomes a number `prep_block` can fold. The cap
tier has its own registry in `look/perennial_ice.py`, keyed by `(body, pole)` where this is keyed by
`(body, layer)`, and its docstring holds the argument both inherit.

Asking a producer for its sources is what makes the warp gate's disk question about the body's own
files. Collapsing it back to a bare `source.exists()` on a module constant looks like dropping a
redundant check, and that question reads "have we downloaded Earth's data" whatever body is being
built: a second planet passes the gate on Earth's file and has Earth's cryosphere warped onto its
own grid, at the same latitudes, with no missing file and no error.

A producer owns the whole act, sources through per-window arithmetic, because a body that registers
one half inherits Earth's other half in silence. A Martian raster run through Earth's
`unpack_persistence` is ice graded by NSIDC's packing convention, which no type could notice.

`contribution` runs on a worker thread and must touch no filesystem. `planet_warp` gathers every
read on the main thread precisely so the compute stays pure, and rasterio is not thread-safe.
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pipeline import bodies, datasets, layers, progress
from pipeline.acquire import (
    download_add_rock,
    download_rgi,
    download_sim3292,
    extract_globathy,
)
from pipeline.look import lake_depth, mars_ice, palette, seaice, snow, viking_luma


@dataclass(frozen=True)
class LayerBuild:
    """The 3857 grid a producer must land its sources on, and where to leave the result.

    Every field goes to every producer whether or not it reads it, on `perennial_ice.CapIceInputs`'
    rule: a request shaped by which producer was registered has to be built per body, which puts the
    body branch back into the caller this seam removes.
    """

    #: (left, bottom, right, top) in EPSG:3857, the height raster's own bounds.
    bounds: tuple[float, float, float, float]
    width: int
    height: int
    #: The file to write, already named from `Layer.warped_basename` under this body's work dir.
    out: Path
    #: The band height for a producer that warps a coarse source in latitude strips. It is
    #: `planet_warp.WINDOW_ROWS`, so a banded mosaic is byte-identical to per-window warps
    #: (`snow.warp_persistence_raster`).
    band_rows: int


@dataclass(frozen=True)
class LayerWindow:
    """One window of the planet grid, as a producer is allowed to see it.

    `raw` is this producer's own slice and None when its raster was never built; the masks and the
    geometry are shared, for the producers that grade against them rather than against a file. Same
    all-fields-always rule as `LayerBuild`.
    """

    raw: np.ndarray | None
    #: The planet seam's water classes, or None on a body whose seam emitted no water mask.
    watercode: np.ndarray | None
    #: `~(ocean | water)` for this window — the tile tier's definition of land, which the cap tier
    #: spells the same way on its own grid.
    land: np.ndarray
    #: Open sea alone, without inland water, and not `land`'s complement: `~land` is
    #: `ocean | water`, so a sea-ice producer gating on that paints a white disc on every lake. Not
    #: derivable from `watercode` either, the ocean mask being its own planet raster.
    ocean: np.ndarray
    #: True latitude in degrees per row (1-D). A Mercator window has rows of constant latitude,
    #: where the cap tier's twin is a per-pixel field.
    latitude: np.ndarray
    #: Ground metres per pixel, per row (1-D), never Mercator map metres. A producer turning a
    #: ground distance into pixels needs the cos(latitude) stretch and the body's own
    #: `ground_metres_per_mercator_unit`, and knows neither on its own.
    ground_metres_per_px: np.ndarray
    #: The window's latitude span in 3857 metres, for a producer whose ramp needs the extent rather
    #: than the per-row value.
    top: float
    bottom: float


@dataclass(frozen=True)
class LayerProducer:
    """One body's answer for one layer at the Mercator tier: what it reads, builds and contributes.

    `sources` is a callable and never a tuple literal, on `perennial_ice.CapIce`'s rule: a literal
    evaluates its paths at import, so a caller that redirects the data root is answered with the
    path from before the redirect. Every path here hangs off `paths.DATA`.
    """

    sources: Callable[[], tuple[Path, ...]]
    #: Land the sources on the grid and leave the file at `LayerBuild.out`. Prints its own line, so
    #: the pass says "rasterize" where it rasterizes and "warp" where it warps.
    build: Callable[[LayerBuild], None]
    #: This layer's number for one window, or None when it has nothing to add. Returning None rather
    #: than zeros keeps a layer that contributes nothing out of the union entirely.
    contribution: Callable[[LayerWindow], "np.ndarray | None"]
    #: The `(sunlit, shadowed)` white the cap painter paints this producer's alpha with, or None
    #: where the layer's number is not a white at all (lake depth, which takes a ramp). `cap_render`
    #: is its only consumer: on the planet, `prep_block` folds the alpha and Blender colours it.
    #:
    #: Each end may be a bare RGB triple or an array shaped per row, so a producer whose material
    #: changes across the window says so itself.
    #:
    #: It belongs to the producer because the code that decides to paint a pixel is the only code
    #: that knows what the pixel is made of. Read as a module global instead, a second planet
    #: inherits Earth's white by omission and nothing can show a reader that a second planet exists.
    paint: Callable[[LayerWindow], "tuple[Any, Any] | None"]
    #: The constants `contribution` reads, for the freshness recipe of every stage that grades.
    #:
    #: A tunable reaching a pixel and no recipe leaves a stale output looking fresh; one recorded by
    #: a body that cannot evaluate it restages that body for output it could not have changed. Both
    #: are silent, and one gate cannot separate them once two bodies paint a layer by different
    #: arithmetic. So the code that reads a constant is the code that declares it.
    #:
    #: `palette.LAKE_*` is deliberately still not here: lake depth is one ramp on every body that
    #: has lakes and is not a white, so it stays in the rig's constants until something contradicts
    #: that.
    contribution_recipe: Callable[[], dict[str, Any]]
    #: The constants `paint` reads, for the freshness recipe of every stage that paints.
    #:
    #: Split from the above because `prep_block` grades without painting, so recording the whites
    #: there would put a night of GPU behind a colour tweak that cannot reach one raytraced pixel.
    #: Empty where the number is not a white, exactly as `paint` returns None.
    paint_recipe: Callable[[], dict[str, Any]]
    #: The constants `build` bakes into the raster, which cannot share the machinery above.
    #:
    #: A constant read per window is re-read when its stage reruns, so recording it there is enough.
    #: A build-time constant is frozen into the file, and `warp_needs_rebuild` is closed over paths
    #: that no Python value can reach: recorded in `contribution_recipe` alone it buys a full
    #: restage that repaints from the unchanged raster and lands the same wrong pixels.
    #:
    #: Materialised by `warp_inputs` through `freshness.write_if_changed`, so the file moves if and
    #: only if a value moved.
    #:
    #: Empty on every Earth producer, which is a property of them rather than an omission: all four
    #: are pure transport. An empty dict writes no file and adds no source, so those warps do not
    #: restage.
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
    """NSIDC-0791 onto the grid, storing the raw packed Float32 and banded at the window height.

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
                                   gpkg=datasets.rgi_gpkg(), layer=download_rgi.LAYER)


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
                                  gpkg=datasets.addrock_gpkg(), layer=download_add_rock.LAYER)


def _earth_antarctic_rock(_window: LayerWindow) -> "np.ndarray | None":
    """None on every window: the one producer that builds a raster and contributes nothing.

    `gather` reads the slice straight off `layer_raw` and `fold_white` takes it back out of the
    finished union as a `WHITE_EXCLUSIONS` member, so it reaches no producer. Returning an array
    here instead puts the rock into the maximum and paints the outcrop the very white this layer
    exists to remove, which renders as a perfectly plausible ice sheet.
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

    Both halves are this layer's answer. NSIDC-0791 covers Antarctica and saturates over it, but
    9-14% of the continent's land arrives as clustered fill unpacking to 0.0, which RGI's peripheral
    region 19 does not reach either, so the patch closes holes rather than standing in for a missing
    dataset. The holes being in the file is what makes the patch ride the layer's declaration: no
    file can switch a latitude-and-land rule off, so this returns an array even when `raw` is None.

    float64 in both branches, since `snow_alpha` returns float64 and `antarctic_snow_mask` float32.

    No rock reaches this producer, which is a correctness boundary rather than a tidy: a negative
    has no home in a positive claim, and subtracted here it sits inside one term of the maximum
    where `persistence_alpha` re-claims 63% of it. It is a `WHITE_EXCLUSIONS` member instead, so
    this answers only where Earth's perennial ice is.
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
    the full-strength Antarctic belt reads as a bright halo. No window straddles both hemispheres'
    ice and the equator is ice-free, so the per-row split is exact.

    Gated here rather than by a consumer: the frequency field is nonzero over land near the coast
    and the alpha is spent on displacement as well as colour, so an ungated return hands out
    something that flattens shorelines. `tests/test_sea_ice_gate.py` guards it.
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
    return seaice.gated_alpha(ice_alpha, window.ocean)


def _no_tunables() -> dict[str, Any]:
    """A producer whose arithmetic has no constants of its own.

    Empty is a statement and not an omission, on `CapIce.sources`' rule: lake depth is a warp and
    the glacier mask a rasterize, both handing their number through unmodified. What paints them is
    declared by `paint_recipe` instead.
    """
    return {}


def _earth_paint(_window: "LayerWindow | None" = None) -> tuple[Any, Any]:
    """Earth's one ice white, shared by its perennial ice, its glaciers and its cap producers.

    Its two Mercator-tier ice layers feed a single union and must agree, and the caps must agree
    with both or the crossfade changes colour across the seam. One function rather than four
    registry entries transcribing `palette` is what makes that a fact instead of a coincidence.
    """
    return palette.SNOW_RGB, palette.SNOW_SHADOW_RGB


def _earth_perennial_ice_recipe() -> dict[str, Any]:
    """What `_earth_perennial_ice` grades with: `snow_alpha`'s latitude ramp and the softening.

    The softening's two constants are spatial rather than tonal, which is what would make leaving
    them out quiet: a re-tuned edge width changes no colour, no threshold and no file, so a stale
    output reads exactly as fresh as a new one. `SOFTEN_BAND_TOLERANCE` is deliberately absent,
    bounding the banding's approximation error rather than choosing an answer.
    """
    return {"snow_ramp_lat_lo": snow.RAMP_LAT_LO,
            "snow_ramp_lat_hi": snow.RAMP_LAT_HI,
            "snow_ramp_low_min": snow.RAMP_LOW_MIN,
            "snow_ramp_low_max": snow.RAMP_LOW_MAX,
            "snow_ramp_band": snow.RAMP_BAND,
            "snow_soften_fraction": snow.SOFTEN_FRACTION,
            "snow_source_cell_m": snow.SOURCE_CELL_M}


def _earth_paint_recipe() -> dict[str, Any]:
    """Earth's one ice white as a recipe, declared by both producers that paint in it.

    From `_earth_paint`, the same function their `paint` returns, so the recipe cannot record a
    colour the producer does not use. The merge is by key, so the duplicate is one value seen twice
    rather than two free to drift.
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
    """Viking luma graded, cut to the mapped units and feathered: the only build that grades.

    Its siblings store their source raw and leave every constant to `contribution`. This one bakes
    `FEATHER_KM` and `ALPHA_LEVELS` into the file, because a distance transform cannot be computed
    from one window: a pixel's nearest ice can lie outside whatever slice is in hand. That is what
    `build_recipe` exists for, and why this producer's `contribution_recipe` is empty.
    """
    progress.stage("grade Viking luma -> Mars ice alpha (polar bands) ...")
    request.out.unlink(missing_ok=True)
    mars_ice.build_alpha_raster(
        field=viking_luma.luma_path(), field_nodata=viking_luma.NODATA,
        bounds=request.bounds, width=request.width, height=request.height, out=request.out,
        ground_metres_per_map_unit=bodies.ground_metres_per_mercator_unit(bodies.get("mars")))


def _mars_perennial_ice(window: LayerWindow) -> "np.ndarray | None":
    """The alpha the build already computed, as float64: this window and nothing else.

    Nothing is graded here, the mirror image of Earth's producer, which follows from where the
    feather has to run. None when the raster was never built: no file, no ice, and no zeros pushed
    into the union to be blended against. float64 to match what the fold promotes to.
    """
    if window.raw is None:
        return None
    return np.asarray(window.raw, dtype=float)


def _mars_ice_paint(window: LayerWindow) -> tuple[Any, Any]:
    """Mars's white, resolved per row against `MARS_ICE_WHITE`'s two poles.

    Both entries carry one authored white today, so this resolves twice to the same answer. The
    lookup stays because one producer spans both hemispheres here, where the cap tier keys on the
    pole: a re-split has nowhere else to reach the pixels, and a producer that stopped asking would
    look identical until then. `test_mars_still_resolves_its_white_PER_POLE_though_both_poles_now_
    carry_one` makes the pole matter synthetically, which is the only arm that can tell the two
    apart.

    Returned as `(3, H, 1)`, which the blend broadcasts for free. The equator is a hemisphere
    boundary and never an ice boundary, Mars carrying no ice within 76 degrees of it, so the row
    this splits on is one no alpha reaches.
    """
    northern = np.asarray(window.latitude) >= 0.0
    def per_row(north: Any, south: Any) -> np.ndarray:
        return np.where(northern[None, :, None],
                        np.asarray(north, dtype=np.float32).reshape(3, 1, 1),
                        np.asarray(south, dtype=np.float32).reshape(3, 1, 1))
    return (per_row(palette.MARS_ICE_WHITE["north"][0], palette.MARS_ICE_WHITE["south"][0]),
            per_row(palette.MARS_ICE_WHITE["north"][1], palette.MARS_ICE_WHITE["south"][1]))


def _mars_ice_paint_recipe() -> dict[str, Any]:
    """Both whites, flat and per pole, so a re-tune of either restages the block render and caps.

    Four keys rather than Earth's two: a recipe records what its own body evaluates, and Mars
    evaluates two pairs. Both stay required even now the values agree, since collapsing to one key
    would record today's pixels correctly and leave half of any future re-split untracked.

    Flat keys rather than a nested dict, so `git log -S "snow_rgb_south"` finds the value's history
    the way it finds Earth's.
    """
    return {f"snow_{end}_{pole}": list(value)
            for pole, pair in sorted(palette.MARS_ICE_WHITE.items())
            for end, value in (("rgb", pair[0]), ("shadow_rgb", pair[1]))}


def _mars_ice_build_recipe() -> dict[str, Any]:
    """The two constants `_build_mars_ice` freezes into its raster.

    The luma weights are deliberately absent, and covered rather than forgotten: `look/viking_luma`
    records them in its own recipe, so a weight change moves the field's mtime and reaches this
    raster as a moved source. Recording them here too would claim the coupling lives in two places.
    """
    return {"mars_feather_km": mars_ice.FEATHER_KM,
            "mars_alpha_levels": {pole: list(levels)
                                  for pole, levels in sorted(mars_ice.ALPHA_LEVELS.items())}}


#: Every Mercator-tier producer that ships, by (body slug, layer name).
#:
#: Six entries and six mechanisms: a banded NetCDF warp, a vector rasterize, a banded GeoTIFF warp,
#: a nodata-masked bilinear warp, Mars's graded-and-feathered polar bands, and a vector rasterize
#: whose result no pixel of its own is painted from.
PRODUCER_BY_BODY_LAYER: dict[tuple[str, str], LayerProducer] = {
    ("earth", layers.LAKE_DEPTH.name): LayerProducer(
        sources=lambda: (extract_globathy.lake_vrt(),),
        # None, not a white: this producer's number is a DEPTH, graded by the lake ramp. The field
        # existing and being answered "not applicable" is what keeps that visible.
        build=_build_lake_depth, contribution=_earth_lake_depth, paint=lambda _window: None,
        contribution_recipe=_no_tunables, paint_recipe=_no_tunables,
        build_recipe=_no_tunables),
    ("earth", layers.PERENNIAL_ICE.name): LayerProducer(
        sources=lambda: (datasets.snow_persistence(),),
        build=_build_persistence, contribution=_earth_perennial_ice, paint=_earth_paint,
        contribution_recipe=_earth_perennial_ice_recipe, paint_recipe=_earth_paint_recipe,
        build_recipe=_no_tunables),
    ("earth", layers.GLACIERS.name): LayerProducer(
        sources=lambda: (datasets.rgi_gpkg(),),
        # Pure transport: the mask is rasterized and handed through, so there is nothing to grade
        # and the white is the whole of what this producer reads.
        build=_build_glaciers, contribution=_earth_glaciers, paint=_earth_paint,
        contribution_recipe=_no_tunables, paint_recipe=_earth_paint_recipe,
        build_recipe=_no_tunables),
    ("earth", layers.SEA_ICE.name): LayerProducer(
        sources=lambda: (datasets.seaice_frequency(),),
        # `seaice.ice_paint`, not a literal: the cap tier reads that same function directly, so the
        # sentence "sea ice is painted in this pair" has one home across both tiers.
        build=_build_sea_ice, contribution=_earth_sea_ice,
        paint=lambda _window: seaice.ice_paint(),
        contribution_recipe=_earth_sea_ice_recipe, paint_recipe=_earth_sea_ice_paint_recipe,
        build_recipe=_no_tunables),
    ("earth", layers.ANTARCTIC_ROCK.name): LayerProducer(
        sources=lambda: (datasets.addrock_gpkg(),),
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
        # The only producer that answers all three fields differently, which is what keeps the
        # split honest: it grades nothing per window, declares two whites per pole, and bakes a
        # feather and its alpha levels into the raster. One field could not carry that.
        contribution_recipe=_no_tunables, paint_recipe=_mars_ice_paint_recipe,
        build_recipe=_mars_ice_build_recipe),
}


def producer_for(body: bodies.Body, layer: layers.Layer) -> LayerProducer:
    """The producer this body builds `layer` with, at the Mercator tier.

    Raises rather than falling back, on `perennial_ice.cap_ice`'s rule: a body inheriting Earth's
    producer by omission warps Earth's data onto another world and paints it as that world's, with
    nothing missing and nothing to report. Only asked of a body that declares the layer, so the
    raise says the two declarations disagree.
    """
    try:
        return PRODUCER_BY_BODY_LAYER[(body.name, layer.name)]
    except KeyError:
        raise KeyError(
            f"{body.name} declares the {layer.name} layer but registers no Mercator producer; "
            f"known: {sorted(PRODUCER_BY_BODY_LAYER)}"
        ) from None


def producers_for(body: bodies.Body, vocabulary: frozenset[str]
                  ) -> list[tuple[layers.Layer, LayerProducer]]:
    """The producers a stage with this vocabulary runs on this body, in `LAYERS` order.

    One answer, because `gather` runs them and `constants_for` records what they read: a layer one
    saw and the other did not is a constant reaching a pixel with no recipe behind it.

    Asked of the body, never of the raster on disk. A producer runs because the planet declared the
    layer, which is what lets Earth's perennial ice carry the forced Antarctic patch: a rule with no
    file behind it, so no missing raster can switch it off.
    """
    return [(layer, producer_for(body, layer)) for layer in layers.warped_for(vocabulary)
            if layer.name in body.surface_layers]


def constants_for(body: bodies.Body, vocabulary: frozenset[str], *,
                  painted: bool) -> dict[str, Any]:
    """Every constant this body's producers read for `vocabulary`, as one stage's freshness record.

    `vocabulary` is the same argument its caller hands `gather`, so a stage cannot run a producer
    without passing the set that decides whether its constants are recorded.

    `painted` is what the stage does with the answer, derivable from no layer or body. True where a
    white reaches a pixel, which is `block_render` (the prep resolves each producer's colour) and
    the two cap stages; False for `prep_block.params`, whose `build` drops `gather`'s paints.

    One parameter rather than two functions: a caller that must merge two calls can forget the
    second and get a plausible, shorter recipe.
    """
    recorded: dict[str, Any] = {}
    for _layer, producer in producers_for(body, vocabulary):
        recorded.update(producer.contribution_recipe())
        if painted:
            recorded.update(producer.paint_recipe())
    return recorded


#: The layers whose contributions merge into one white, in the order they fold.
#:
#: Sea ice is absent deliberately: it is gated on the ocean selector where this union paints land,
#: so folding it in would paint pack ice onto the shore it borders. Lake depth is absent for a
#: different reason, being a ramp position and not a white at all.
WHITE_UNION: tuple[layers.Layer, ...] = (layers.PERENNIAL_ICE, layers.GLACIERS)

#: The layers that remove white, applied after that union and never folded into it: `fold_white` is
#: a maximum over positive claims, so "this pixel is definitively not ice" has no representation in
#: it and saying so inside one union member leaves every other member free to outvote it. The rule
#: beside this file owns what that costs.
#:
#: Here beside the union rather than in `layers`, because a reader who finds either half needs the
#: other: what makes a new white source safe to add is that this half lands after all of them.
WHITE_EXCLUSIONS: tuple[layers.Layer, ...] = (layers.ANTARCTIC_ROCK,)


def white_law(body: bodies.Body, vocabulary: frozenset[str]) -> dict[str, list[str]]:
    """Which of `vocabulary` this body folds into the white and which it takes back out.

    A law rather than a constant, which is why it is not `constants_for`'s: a producer's recipe says
    how it grades its own claim, and no producer can see whether that claim is added or subtracted.
    The rule beside this file owns why nothing else in a recipe stands in for it.

    Lists rather than sets, because a set has no stable serialisation order. Narrowed by
    `producers_for` rather than by its own copy of that filter, so the law recorded is the law the
    stage runs; a fourth spelling of "this body, this vocabulary" would have to agree with `gather`
    or the record is fiction.
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

    Which producers run is `producers_for`'s answer rather than a condition restated here, so this
    and `constants_for` cannot disagree about the set.

    `vocabulary` is the caller's stage view, on `layers.layers_off`'s rule: `prep_block` reads
    `BLOCK_LAYERS` and `cap_render` `CAP_LAYERS`, and the two genuinely disagree.

    A paint is asked only of a layer that contributed, so a producer that paints nothing this window
    never has to answer what colour it would have used.

    The exclusions are read here because this is the only place holding both `layer_raw` and the
    body's declarations, and they are a third return rather than a field on the window because no
    producer may see them: a negative applies to the fold, never inside one positive answer.

    Asked of the body and the vocabulary, never of the dict. One supplier keys `layer_raw` on
    `path.exists()` alone, so a slice can arrive for a body that declares no such layer.
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
    """Fold `WHITE_UNION`'s contributions into the one alpha the painter takes as snow, then take
    `WHITE_EXCLUSIONS` back out of the result.

    float64 base because that is what `snow_alpha` returns and what the maxima promote to; a float32
    base would narrow every pixel the blend touches.

    The exclusions land after the maximum and that order is the whole point. Subtracting inside one
    contribution leaves every other union member free to re-claim the pixel, which is what a maximum
    of positives does by construction, so an exclusion applied earlier is not a weaker fix but one a
    second white source silently undoes. `WHITE_EXCLUSIONS` holds the argument.

    `exclusions` is required rather than defaulted, because a caller that skips the negative gets a
    plausible white rather than an error. Pass an empty dict to say a window excludes nothing.

    `merge` sees each layer's name, its contribution and the running alpha before it folds, so a
    caller can fold something alongside the alpha that is not commutative. No shipped caller passes
    one: both discard the second return, and it is exercised only by `test_prep_block`.
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
