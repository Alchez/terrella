"""Which producer paints a body's perennial ice on a polar cap, and what that producer reads.

The layer is one name and the producers are not one function. `perennial_ice` states a claim, the
white that is there all year, and each body answers it with different machinery: Earth's north warps
a hemispheric NetCDF climatology and smoothsteps its persistence fraction, where Earth's south has
no dataset in this pipeline at all and forces the answer out of latitude-and-land arithmetic. So
this is a registry of functions where `palette.LOOK_BY_BODY` is a registry of values, and the
difference is not stylistic: "make X body-derived" is honest only while the instances differ in
their constants, and when they differ in mechanism a swapped constant is a rewrite wearing a seam's
clothes.

Keyed by (body, pole), and the pole is not padding: it is what gives the seam two real, dissimilar,
shipping instances the day it lands instead of one plus a promise. Keyed by body alone, Earth would
be a single entry re-dispatching on the pole internally, so the parameterisation would be exercised
by exactly one instance, which is the shape that passes by construction and proves nothing until a
second body arrives. Both bodies genuinely differ per pole, so the pole is a real axis rather than a
device.

A producer declares its own inputs. `sources` rides in the same record as `alpha` because the two
answer one question asked by two callers: the renderer asks what to paint, `cap_render.cap_sources`
asks what would make that paint stale. Split apart, a body can register a producer and leave its
caps frozen against the files that producer reads, `cap_is_fresh` comparing mtimes so a cap whose
source is not listed never notices the source changing. It is the same argument that makes
`bakes_coastline` one predicate read by both the render and the source list. An empty tuple is a
statement and not an omission: Earth's south reads no file, so nothing on disk could make its cap
stale, and nothing should be listed.

The warp is injected rather than imported. A producer that reads a raster has to land it on the
cap's AEQD grid, and that grid, with its sphere, its extent and its pixel count, belongs to
`cap_render`, which imports this package; reaching back for it would close that cycle. Taking a
`WarpToCap` instead keeps the dependency pointing one way and makes a producer drivable in a test
with no GDAL behind it, which is how the alpha arithmetic gets an oracle at all.

Not in `bodies.py`, which opens by saying it is not a look and not a dataset; a producer is both.
The precedent followed here is `palette.look_for`: the consumer's own tier owns the mapping, keyed
by the body's slug, and refuses an unregistered body rather than falling back to Earth's.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from pipeline import bodies, datasets, layers
from pipeline.acquire import download_sim3292
from pipeline.look import mars_ice, palette, snow, viking_luma


class WarpToCap(Protocol):
    """Land one 4326 source on the calling cap's AEQD grid and hand back band 1.

    `name` is the warp's label, not a path: the caller turns it into a file under that body's cap
    work directory, prefixed for the pole it belongs to. A producer naming its own output path
    would be spelling out a convention that `cap_render.cap_warp` already owns, and a half-labelled
    warp set is exactly what that helper exists to prevent.
    """

    def __call__(self, source: str, name: str, resampling: str, dtype: str,
                 srcnodata: "float | None" = None) -> np.ndarray: ...


class BurnToCap(Protocol):
    """Land one vector source on the calling cap's AEQD grid and hand back a boolean mask.

    The twin of `WarpToCap` and injected for its reason rather than for symmetry: the grid belongs
    to `cap_render`, and a producer reaching back for it would close the import cycle that docstring
    describes. `cap_render._bake_coastline` already burns vectors onto this exact grid, so what this
    exposes is a capability the module has rather than one invented for a body.

    A separate protocol from the warp because the trap is different: `vector_raster` exists because
    `gdal_rasterize` does not reproject and, handed a mismatched CRS, burns nothing while exiting 0
    and writing a well-formed raster. `must_draw` is the caller's claim that an empty result is
    breakage, and it has no default here for the reason `mars_ice.burn_unit` records, depending on
    the disc's edge latitude against that unit's own reach.
    """

    def __call__(self, source: Path, name: str, must_draw: "str | None") -> np.ndarray: ...


@dataclass(frozen=True)
class CapIceInputs:
    """Everything a cap ice producer is allowed to see.

    Every field is passed to every producer whether or not it reads them, and that is deliberate: a
    struct whose fields depend on which producer is registered would have to be built differently per
    body, which puts a body branch back in the renderer this seam exists to remove. All are cheap —
    the renderer computes the lon/lat grid for the light azimuth regardless, and the masks for the
    fold.
    """

    #: `~(ocean | water)` on the cap grid — the tile tier's definition of land, so the two agree
    #: across the crossfade rather than by coincidence.
    land: np.ndarray
    #: True latitude in degrees at each AEQD pixel centre. Per-PIXEL, not per-row: an AEQD disc has
    #: no rows of constant latitude, so the Mercator path's 1-D form is wrong here.
    latitude: np.ndarray
    warp: WarpToCap
    burn: BurnToCap
    #: GROUND metres per pixel, never AEQD map metres. The two differ by `ground_metres_per_aeqd_unit`
    #: — 0.533 on Mars — and a producer converting a ground distance into pixels with the map figure
    #: draws it at roughly half the width its own constant claims. That has already happened once,
    #: which is why this is supplied rather than left for each producer to derive.
    ground_metres_per_px: float


@dataclass(frozen=True)
class CapIce:
    """One body's perennial-ice answer for one pole: what it reads, and how it paints."""

    #: Files whose change must restage this cap. Declared here rather than at the gate because only
    #: the producer knows them, and `cap_is_fresh` requires every listed source to exist, so a
    #: source named for a body that never opens it leaves that body's caps permanently stale.
    #:
    #: A callable and not a tuple: a tuple literal in the registry below evaluates the path once, at
    #: import, so a caller that redirects the store is answered with the path from before the
    #: redirect and the gate reports the wrong file's existence. Every path in this pipeline hangs
    #: off `paths.DATA`, which a relocated store moves, and a zero-argument callable reads it late.
    sources: Callable[[], tuple[Path, ...]]
    alpha: Callable[[CapIceInputs], np.ndarray]
    #: The `(sunlit, shadowed)` white the cap painter paints this cap's alpha with.
    #:
    #: Per pole for free here, the pole being half of this registry's key, where the Mercator tier
    #: keys on the layer and has to vary its paint within a window. That asymmetry is why the two
    #: tiers declare the same thing by different means, and both must land on the same value at the
    #: same pole or the 80–84 crossfade changes colour across the seam.
    #:
    #: A callable for the reason `sources` is one: a tuple literal in the registry freezes whatever
    #: `palette` held at import, so a test that swings a body's white is answered with the value
    #: from before the swing.
    paint: Callable[[], tuple[Any, Any]]
    #: The `layer_producers.WHITE_EXCLUSIONS` members this pole takes back out of its folded white.
    #:
    #: Declared here because the pole is half this registry's key, which is what keeps "only
    #: Antarctica has Antarctic rock" a fact of the key rather than a `grid.name == "south"` written
    #: into the renderer. It also keeps the burn where it belongs: an undeclared pole never opens the
    #: file, so no disc pays a reprojection of the whole GeoPackage for a mask that would come back
    #: empty and raise on `must_draw`.
    #:
    #: Not `sources`, and that is a correctness boundary rather than a placement. Those are this
    #: producer's mandatory inputs and `cap_render._cap_perennial_ice` refuses the whole layer unless
    #: every one exists, so a rock entry there would let an undownloaded GeoPackage switch off the
    #: forced Antarctic white and render the continent on the tan land ramp. An exclusion is optional
    #: by construction: absent, the fold simply removes nothing.
    #:
    #: Required with no default, on `bodies.Body`'s rule. Forgetting it fails toward "this pole
    #: excludes nothing", which renders as a plausible ice sheet rather than as an error.
    exclusions: Callable[[], tuple[layers.Layer, ...]]


def _earth_north(inputs: CapIceInputs) -> np.ndarray:
    """NSIDC-0791 snow persistence, smoothstepped — Earth's Arctic land ice and perennial snow.

    The whole cap is north of `cap_render.CAP_EDGE_LAT` and therefore of `snow.RAMP_LAT_HI`, so
    `snow_alpha`'s latitude ramp is CONSTANT across every pixel of it. Reproduced here with the
    fixed high-latitude thresholds rather than by calling `snow_alpha`, whose per-row latitude is
    Mercator-specific and would be wrong on an AEQD grid.

    The feather is shared though, and has to be: only the ramp is Mercator-specific, the staircase
    it softens is the source's own 0.01 degree cell, which this grid resolves exactly as the tiles
    do — and the cap meets those tiles across the 80..84 crossfade, at the latitudes where the cell
    is 20 to 35 render pixels tall and the staircase is at its worst. Feathering one side of that
    seam and not the other would swap one visible discontinuity for another. The disc has a single
    ground resolution, so `feather` takes the scalar branch here and the per-row branch there.
    """
    sp_raw = inputs.warp(f'NETCDF:"{datasets.snow_persistence()}":{snow.SP_VAR}', "sp", "bilinear", "Float32",
                         srcnodata=snow.SP_FILL)
    persistence = snow.unpack_persistence(sp_raw)
    low = snow.RAMP_LOW_MAX
    high = low + snow.RAMP_BAND
    fraction = np.clip((persistence - low) / (high - low), 0.0, 1.0)
    alpha = fraction * fraction * (3.0 - 2.0 * fraction)  # float64, as before the N/S refactor
    return snow.soften_source_cells(alpha, inputs.ground_metres_per_px)


def _earth_south(inputs: CapIceInputs) -> np.ndarray:
    """Antarctic land forced white, less its exposed rock — the one producer with no MANDATORY file.

    NSIDC-0791 saturates over the whole continent and RGI region 19 reaches only its periphery, so
    the white comes from latitude and land rather than from a measurement. Nothing on disk can switch that off,
    which is why it rides the body's layer declaration and why its `sources` tuple stays empty.
    `pipeline/acquire/download_add_rock.py` holds the measurement behind the saturation claim.

    The outcrop is not this producer's business, and that is the point rather than an omission. It
    is declared in `exclusions` and removed by `layer_producers.fold_white` after this answer folds,
    so a rock mask cannot be re-claimed by anything else that paints this disc white. `CapIce
    .exclusions` holds the argument, and this function answers only where Antarctic ice IS.

    `snow.antarctic_snow_mask` is the one home for the rule and the tile tier calls the same
    function through the same fold, so the two sides of the −84 crossfade agree by construction,
    which is a property of sharing the code rather than a claim this docstring makes.
    """
    return snow.antarctic_snow_mask(inputs.land, inputs.latitude)


def _mars_sources() -> tuple[Path, ...]:
    """The brightness field and both mapped units — every file either Mars pole opens.

    One list for both poles because both poles burn both units; see `_mars_cap_ice`. Listing a unit
    a pole never opens would be the failure `CapIce.sources` warns about in reverse — here the risk
    is the other direction, and every path named is genuinely read.
    """
    return (viking_luma.luma_path(),
            *(download_sim3292.unit_path(unit) for unit in mars_ice.NORTH_UNITS))


def _mars_cap_ice(inputs: CapIceInputs, pole: str) -> np.ndarray:
    """Viking luma graded between this pole's pinned levels, inside the mapped units, feathered.

    One function for both poles, where Earth needs two. Earth's poles differ in mechanism, a NetCDF
    warp against a latitude rule, and Mars's differ only in which constants they read, which is the
    case the registry's own note says a parameterisation is honest for.

    The levels and the field are one pairing and nothing here can check it, as `albedo_alpha` says in
    as many words. What makes it safe is that both come from the same two modules: the field is
    `viking_luma`'s shipped raster, and `ALPHA_LEVELS` was measured over that raster and nothing
    else. `scripts/measure_viking_levels.py --compare` is what refuses a drift between them.

    Both units are burnt at both poles, which looks wasteful at the south and is not optional:
    `extent_for` is one function serving this tier and the Mercator tier's straddling windows, so its
    `np.where` evaluates both hemispheres' unions and a missing mask raises. The south's `Apu` is
    computed and then discarded by that `where`, which is the correct extent — southern `Apu` is
    layered deposits, not surface ice, and it covers 72% of that disc.

    The feather takes ground metres, never AEQD map metres. `inputs.ground_metres_per_px` is
    supplied for exactly this call; deriving it here from the grid is the bug that already shipped
    once, drawing roughly half the ground distance `FEATHER_KM` names. Nothing about the result looks
    wrong — it is a plausible ice edge at any width — so the guard measures the drawn feather back
    into kilometres rather than trying to see it.
    """
    field = inputs.warp(str(viking_luma.luma_path()), "viking_luma", "bilinear", "Float32",
                        srcnodata=viking_luma.NODATA)
    graded = mars_ice.albedo_alpha(field, mars_ice.ALPHA_LEVELS[pole], viking_luma.NODATA)
    masks = {
        unit: inputs.burn(download_sim3292.unit_path(unit), unit.lower(),
                          f"{unit} must reach the {pole} cap disc")
        for unit in mars_ice.NORTH_UNITS
    }
    extent = mars_ice.extent_for(masks, pole == "north")
    return graded * mars_ice.feather_alpha(extent, inputs.ground_metres_per_px)


#: Every producer that ships, by (body slug, pole). Earth's two entries are the seam's two real
#: instances — a NetCDF warp and a latitude rule, sharing nothing but their signature.
#:
#: A producer cannot declare a path nothing acquired, which is the ordering a new body follows:
#: acquisition first, then the entry here. OMEGA has no entry because its licence blocks the source
#: rather than because the seam cannot hold one.
def _earth_cap_paint() -> tuple[Any, Any]:
    """Earth's one white at both poles, and the same pair its Mercator-tier producers declare.

    Read through `palette` rather than restated, so the cap and the tiles it feathers into cannot
    disagree about the colour of the same ice sheet.
    """
    return palette.SNOW_RGB, palette.SNOW_SHADOW_RGB


CAP_ICE_BY_BODY: dict[tuple[str, str], CapIce] = {
    ("earth", "north"): CapIce(sources=lambda: (Path(datasets.snow_persistence()),), alpha=_earth_north,
                               paint=_earth_cap_paint, exclusions=lambda: ()),
    ("earth", "south"): CapIce(sources=lambda: (), alpha=_earth_south, paint=_earth_cap_paint,
                               exclusions=lambda: (layers.ANTARCTIC_ROCK,)),
    ("mars", "north"): CapIce(sources=_mars_sources,
                              alpha=lambda inputs: _mars_cap_ice(inputs, "north"),
                              paint=lambda: palette.MARS_ICE_WHITE["north"],
                              exclusions=lambda: ()),
    ("mars", "south"): CapIce(sources=_mars_sources,
                              alpha=lambda inputs: _mars_cap_ice(inputs, "south"),
                              paint=lambda: palette.MARS_ICE_WHITE["south"],
                              exclusions=lambda: ()),
}


def cap_ice(body: bodies.Body, pole: str) -> CapIce:
    """The producer this body paints its perennial ice with at this pole.

    Raises rather than falling back, on `palette.look_for`'s rule and for a sharper version of its
    reason. A body inheriting Earth's ramp by omission renders a plausible planet in the wrong
    colours; a body inheriting Earth's north producer by omission warps a NetCDF of northern-
    hemisphere terrestrial snow persistence onto another world's pole and paints the result as that
    world's ice — same latitudes, no missing file, no error, and a cap that looks like an
    observation. Only asked of a body that declares the layer, so the raise is unreachable in a
    correct configuration and is precisely a report that the two declarations disagree.
    """
    try:
        return CAP_ICE_BY_BODY[(body.name, pole)]
    except KeyError:
        raise KeyError(
            f"{body.name} declares the {layers.PERENNIAL_ICE.name} layer but registers no "
            f"{pole} cap producer; "
            f"known: {sorted(CAP_ICE_BY_BODY)}"
        ) from None
