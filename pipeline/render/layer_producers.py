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

import numpy as np

from pipeline import bodies, layers
from pipeline.render import lake_depth, seaice, snow


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


#: Every composite-tier producer that ships, by (body slug, layer name).
#:
#: Four entries and four MECHANISMS — a banded NetCDF warp, a vector rasterize, a banded GeoTIFF
#: warp and a nodata-masked bilinear warp — which is what gives the parameterisation real instances
#: on day one instead of one shape repeated with a different constant in it.
PRODUCER_BY_BODY_LAYER: dict[tuple[str, str], LayerProducer] = {
    ("earth", layers.LAKE_DEPTH.name): LayerProducer(
        sources=lambda: (lake_depth.LAKE_VRT,),
        build=_build_lake_depth, contribution=_earth_lake_depth),
    ("earth", layers.PERENNIAL_ICE.name): LayerProducer(
        sources=lambda: (snow.SP_NC,),
        build=_build_persistence, contribution=_earth_perennial_ice),
    ("earth", layers.GLACIERS.name): LayerProducer(
        sources=lambda: (snow.RGI_GPKG,),
        build=_build_glaciers, contribution=_earth_glaciers),
    ("earth", layers.SEA_ICE.name): LayerProducer(
        sources=lambda: (seaice.SEAICE_SRC,),
        build=_build_sea_ice, contribution=_earth_sea_ice),
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
