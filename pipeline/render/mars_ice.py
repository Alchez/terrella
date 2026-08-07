"""Mars's polar ice: which mapped units are ice, how icy each pixel of them is, and how the edge
between that and bare ground is softened.

TWO FIELDS AND THEY COME FROM DIFFERENT PLACES. The extent says where white is drawn at all and comes
from a geologic map (`acquire/download_sim3292.py` holds why). The alpha says how white, and comes
from OMEGA albedo (`acquire/extract_omega.py`). Keeping them separate is what lets the map limit the
CLAIM while the albedo supplies the VARIATION — the arm that let albedo do both was judged and
rejected, roughly 45% of its ice falling outside the mapped unit and reading as seasonal frost caught
in a 6.5-year average.

THE EXTENTS ARE CORROBORATED BY PUBLISHED AREAS, which is worth stating because a geologic unit
chosen by us could otherwise be an arbitrary polygon. North `lApc | Apu` integrates to 1,095,880 km²
against a published Planum Boreum / NPLD area of about 1,000,000 km² — and `lApc` ALONE is 596,893,
which would be 40% short, so the published figure independently supports including `Apu` in the
north. South `lApc` is 103,642 km² against a south polar residual cap of about 87,000.

THE EXTENT IS ASYMMETRIC ON MEASUREMENT, NOT ON SYMMETRY. `lApc` is ice at both poles. `Apu` joins it
in the NORTH only, because OMEGA puts northern `Apu` +0.13 to +0.16 above ordinary ground at matched
latitude — 55-80% of the way from bare ground to the residual cap — while southern `Apu` sits within
±0.04 of ordinary ground and covers 68.7% of that disc. Painting it south would whiten two thirds of
the view on no evidence. So a body's hemisphere is a real input here and not a tidy-up.

AND THE GEOLOGY SAYS THE SAME THING INDEPENDENTLY, which is why the asymmetry is not a fudge: the
southern `Apu` polygon is 1,495,810 km², the south polar LAYERED DEPOSITS, a dusty stack rather than
a residual ice cap — so a unit OMEGA finds indistinguishable from ordinary ground is one the
stratigraphy also says is not surface ice. Two lines of evidence, neither derived from the other.

THE FEATHER IS DRAWN AND MUST NEVER BE DESCRIBED AS OBSERVED. The published linework was drawn while
viewing at 1:5,000,000 with 5 km vertex spacing, so against the tiles' polar pixels it is roughly
eight pixels per vertex and a hard edge reads as faceted. `FEATHER_KM` softens that and nothing
measured it — a distance transform wearing a measurement's clothes is the `antarctic_snow_mask`
mistake, one module over.

THE ICE EDGE HAS SINCE BEEN MEASURED AND THAT IS A DIFFERENT QUANTITY — do not let the number migrate
into `FEATHER_KM`. OMEGA against signed distance to the south's mapped contact puts real ice fading
over about 12 ground km outside it, and the north has no albedo edge at all across 130 km. That
validates the EXTENT; the feather still anti-aliases a drawn boundary, so its anchor is the linework
and not the ice. `data/work/mars/_ice_ab/scripts/ice_edge_profile.py` reproduces the profile.

THE FEATHER IS THE ONE THING THAT CANNOT BE COMPUTED PER WINDOW. A distance transform is non-local:
a pixel's distance to the nearest ice can be owned by a pixel outside whatever slice is in hand, and
this project has already paid for that lesson on GLOBathy's shore distances. It is bounded here,
which is what rescues it — nothing past `FEATHER_KM` changes the answer — so a banded pass with a pad
wider than the feather is exact where the result is used, and only there.
"""

from collections.abc import Iterator
from functools import reduce
from pathlib import Path

import numpy as np
from scipy import ndimage

from pipeline import vector_raster
from pipeline.acquire import download_sim3292
from pipeline.raster_io import row_bands

#: The mapped units drawn as ice, per hemisphere. Both tuples are read by `extent_for`, and the
#: difference between them is the measurement in the module note rather than a spelling choice.
NORTH_UNITS: tuple[str, ...] = ("lApc", "Apu")
SOUTH_UNITS: tuple[str, ...] = ("lApc",)

#: How far outside the mapped contact the ice fades to nothing, in GROUND kilometres.
#:
#: DRAWN, NOT MEASURED, AND IT IS ONE VERTEX SPACING — the only anchor this constant has ever had.
#: Its whole job is to stop a 5 km-vertex boundary stair-stepping, so it is anti-aliasing over a
#: contact the publisher mapped, not a gradient standing in for one nobody observed.
#:
#: THREE WRONG VALUES PRECEDED IT AND EACH LOOKED SETTLED. 25 km came from a superseded arm where the
#: feather WAS the gradient. 10 km replaced it and was then divided by AEQD MAP metres, which on Mars
#: are Earth metres, so what actually rendered was 5.33 km of ground under a label saying 10. The
#: scale a caller passes must therefore be GROUND metres per pixel — see `feather_alpha_bands`.
#:
#: Do not re-anchor it to the measured 12 km ice edge; that is the width of ice this design
#: deliberately does not paint, and the module note above holds why the two are different quantities.
FEATHER_KM = 5.0

#: OMEGA albedo mapping to alpha 0 and 1, per pole: the median of ground that is neither mapped unit,
#: and the median of the residual cap.
#:
#: PINNED, NEVER RECOMPUTED, AND THAT IS CORRECTNESS RATHER THAN TIDINESS. The two tiers grade the
#: same ice over different pixel sets — an AEQD disc and a Mercator strip — so percentiles taken per
#: grid would disagree, and the cap and the tiles crossfade across 80-84 degrees where a disagreement
#: is visible as a step. Measured once, on the cap grids, by the arm that was ratified.
ALPHA_LEVELS: dict[str, tuple[float, float]] = {
    "north": (0.1880, 0.4533),
    "south": (0.2930, 0.6501),
}


def _smoothstep(fraction: np.ndarray) -> np.ndarray:
    """Clamp to 0..1 and ease both ends. The module's one spelling of it, read by both alphas.

    Kept private and local rather than shared: the array-form smoothstep has several spellings across
    this package and giving it a single owner is its own change, not one to make while adding a
    seventh caller. float64 out, matching `snow.snow_alpha` — the composite blends whichever body's
    answer it is handed, and a narrower dtype from one of them shifts the other's blend sub-DN.
    """
    # The cast is load-bearing and not defensive: OMEGA lands as float32, and float32 in would give
    # float32 out under numpy's promotion rules, silently breaking the dtype this promises.
    clipped = np.clip(np.asarray(fraction, dtype=float), 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def albedo_alpha(albedo: np.ndarray, levels: tuple[float, float], nodata: float) -> np.ndarray:
    """How icy each pixel is, from OMEGA albedo normalised between this pole's two pinned levels.

    `levels` is `(ground, cap)` from `ALPHA_LEVELS`, passed rather than looked up so the caller names
    the pole once and this stays a pure function of its arguments.

    UNMEASURED PIXELS BECOME ZERO AND ARE COMPARED BEFORE SCALING. OMEGA's fill is a large negative
    number; normalised it becomes an ordinary out-of-range float that the clamp would quietly turn
    into 0.0 anyway — but only by arithmetic accident, and a fill that ever landed inside the range
    would paint as ice. Masking on the raw value makes it a decision.

    This is the ratified arm's arithmetic (`_ice_ab/scripts/ice_ab_hybrid.py`), which is the authority
    for the look. It differs there in two ways that are both intended: the levels were recomputed per
    run and are pinned here, and its alpha was float32 where this is float64.
    """
    ground, cap = levels
    alpha = _smoothstep((albedo - ground) / (cap - ground))
    alpha[albedo == nodata] = 0.0
    return alpha


def burn_unit(unit: str, target_srs: str, bounds: tuple[float, float, float, float],
              width: int, height: int, projected: Path, out: Path,
              creation_options: tuple[str, ...] = (),
              must_draw: "str | None" = None) -> Path:
    """Land one acquired unit on a grid as a 0/1 Byte mask.

    Thin over `vector_raster.burn_onto_grid`, whose module note holds the reprojection trap this
    whole stage is shaped around. The source is resolved through `download_sim3292.unit_path` AT CALL
    TIME so a redirected data root moves it, per `paths`.

    `must_draw` IS THE CALLER'S CLAIM AND IS DELIBERATELY NOT DEFAULTED. On a planet grid an empty
    burn is always breakage, because the grid spans the planet and the polygons exist. On a cap grid
    it depends on the disc's edge latitude against that unit's own reach, so a default here would
    either miss the trap on one caller or cry wolf on the other.
    """
    return vector_raster.burn_onto_grid(
        download_sim3292.unit_path(unit), target_srs, bounds, width, height,
        projected=projected, out=out, creation_options=creation_options, must_draw=must_draw)


def extent_for(unit_masks: dict[str, np.ndarray], northern) -> np.ndarray:
    """The ice extent from the burnt unit masks, taking each hemisphere's own union.

    `northern` is anything broadcastable against the masks — a plain bool for a cap disc, which is
    all one hemisphere, or a per-row column for a Mercator window, which may straddle the equator.
    A missing unit raises `KeyError` rather than reading as absent ice, since the caller not burning
    a unit this hemisphere needs is a bug and not an extent.
    """
    return np.where(northern,
                    _union(unit_masks, NORTH_UNITS),
                    _union(unit_masks, SOUTH_UNITS))


def _union(unit_masks: dict[str, np.ndarray], units: tuple[str, ...]) -> np.ndarray:
    """Boolean OR of the named units' masks."""
    return reduce(np.logical_or, (np.asarray(unit_masks[unit], dtype=bool) for unit in units))


def feather_alpha_bands(mask: np.ndarray, ground_metres_per_px, feather_km: float = FEATHER_KM,
                        band_rows: "int | None" = None) -> "Iterator[tuple[int, int, np.ndarray]]":
    """Yield `(row0, row1, alpha)` for each band: 1.0 inside the extent, smoothstepping to 0.0
    `feather_km` GROUND kilometres outside it.

    A GENERATOR BECAUSE THE RESULT IS THE THING THAT DOES NOT FIT, which is a different problem from
    the transform's own peak and was briefly confused with it. Mars's planet grid is 32768 square, so
    one float64 alpha for it is 8.6 GB — bounding the distance transform to a band and then
    materialising the whole answer would still not run. Handing back one band at a time lets the
    caller write it and drop it, and it is what makes `band_rows` worth having at all.

    `ground_metres_per_px` converts the transform's pixels into ground metres, as a scalar or a value
    per row of the WHOLE mask. It has to be either, because a Mercator pixel is not a fixed ground
    distance: across the band where Mars's tiles show ice it runs about 152 m down to 68, so a
    feather counted in pixels would be more than twice as wide at one end as the other. A cap's AEQD
    grid has no such term and passes one number. The ratio behind it belongs to
    `bodies.ground_metres_per_mercator_unit` / `..._aeqd_unit`; only the composition is here.

    Bands are EXACT WHERE THEY ARE READ AND WRONG BEYOND, which is the whole bargain. Each is
    transformed with `pad` extra rows on both sides, so any nearest-ice within `pad` pixels is inside
    the slice that computed it; a cell whose nearest ice lies further away gets a number too large,
    and every such cell is already past the feather and clipped to zero.

    Alpha is float64, matching `snow.snow_alpha` — the composite blends whichever body's answer it is
    handed, and a narrower dtype from one of them would shift the other's blend sub-DN.
    """
    outside = ~np.asarray(mask, dtype=bool)
    feather_m = feather_km * 1000.0
    scale = np.asarray(ground_metres_per_px, dtype=float)
    if scale.size == 0 or float(scale.min()) <= 0.0:
        raise ValueError("ground_metres_per_px must be positive everywhere — it divides the feather "
                         f"into pixels; got {'an empty array' if not scale.size else scale.min()}")
    # The pad is DERIVED from the feather rather than pinned beside it, so the two cannot drift into
    # a banded pass that is quietly wrong at every band edge. The finest pixel needs the most of it.
    pad = int(np.ceil(feather_m / float(scale.min()))) + 1
    height = outside.shape[0]
    for row0, row1 in row_bands(height, band_rows if band_rows else height):
        top, bottom = max(0, row0 - pad), min(height, row1 + pad)
        distance = np.asarray(ndimage.distance_transform_edt(outside[top:bottom]), dtype=float)
        distance = distance[row0 - top:row1 - top]
        rows = scale[row0:row1].reshape(-1, 1) if scale.ndim == 1 else scale
        yield row0, row1, _smoothstep(1.0 - distance * rows / feather_m)


def feather_alpha(mask: np.ndarray, ground_metres_per_px,
                  feather_km: float = FEATHER_KM) -> np.ndarray:
    """The whole feathered alpha at once, for a grid that fits — a cap disc, or one window.

    Spelled as the single-band case of the generator rather than as its own transform, so there is
    one arithmetic here and no second copy to drift. `band_rows=None` is that single band.
    """
    (_row0, _row1, alpha), = feather_alpha_bands(mask, ground_metres_per_px, feather_km)
    return alpha
