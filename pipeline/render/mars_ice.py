"""Mars's polar ice: which mapped units are ice, how icy each pixel of them is, and how the edge
between that and bare ground is softened.

TWO FIELDS AND THEY COME FROM DIFFERENT PLACES. The extent says where white is drawn at all and comes
from a geologic map (`acquire/download_sim3292.py` holds why). The alpha says how white, and comes
from the Viking colour mosaic's luma (`ALPHA_LEVELS`). Keeping them separate is what lets the map
limit the CLAIM while the albedo supplies the VARIATION — the arm that let albedo do both was judged
and
rejected, roughly 45% of its ice falling outside the mapped unit and reading as seasonal frost caught
in a 6.5-year average.

THE EXTENTS ARE CORROBORATED BY PUBLISHED AREAS, which is worth stating because a geologic unit
chosen by us could otherwise be an arbitrary polygon. North `lApc | Apu` integrates to 1,095,880 km²
against a published Planum Boreum / NPLD area of about 1,000,000 km² — and `lApc` ALONE is 596,893,
which would be 40% short, so the published figure independently supports including `Apu` in the
north. South `lApc` is 103,642 km² against a south polar residual cap of about 87,000.

THE EXTENT IS ASYMMETRIC ON MEASUREMENT, NOT ON SYMMETRY. `lApc` is ice at both poles. `Apu` joins it
in the NORTH only, because the albedo puts northern `Apu` +0.13 to +0.16 above ordinary ground at
matched latitude — 55-80% of the way from bare ground to the residual cap — while southern `Apu` is
within
±0.04 of ordinary ground and covers 68.7% of that disc. Painting it south would whiten two thirds of
the view on no evidence. So a body's hemisphere is a real input here and not a tidy-up. Viking
reproduces that split independently at +4.47 scatters against OMEGA's +4.30, so the asymmetry does
not rest on the source that has since been withdrawn.

AND THE GEOLOGY SAYS THE SAME THING INDEPENDENTLY, which is why the asymmetry is not a fudge: the
southern `Apu` polygon is 1,495,810 km², the south polar LAYERED DEPOSITS, a dusty stack rather than
a residual ice cap — so a unit the albedo finds indistinguishable from ordinary ground is one the
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

#: Viking colour LUMA mapping to alpha 0 and 1, per pole: the median of ground that is neither mapped
#: unit, and the median of `lApc`. 8-bit Rec. 709 luma, so these live on 0..255 and not on 0..1.
#:
#: `lApc` ALONE SETS THE CAP LEVEL AT BOTH POLES, including the north where the extent also takes
#: `Apu`; and GROUND EXCLUDES BOTH UNITS AT BOTH POLES, including the south where `Apu` is not ice.
#: Neither is `extent` or `~extent`, and reading them as such moves the look.
#:
#: PINNED, NEVER RECOMPUTED, AND THAT IS CORRECTNESS RATHER THAN TIDINESS. The two tiers grade the
#: same ice over different pixel sets — an AEQD disc and a Mercator strip — so percentiles taken per
#: grid would disagree, and the cap and the tiles crossfade across 80-84 degrees where a disagreement
#: is visible as a step. That grid-dependence is measured, not feared: moving the cap edge 78 -> 80
#: moved the north's cap level 11.4% while leaving the south's at 0.03 DN.
#:
#: MEASURED OVER `viking_luma`'s SHIPPED RASTER, not over a band built to answer the question. That
#: distinction moved the north by 0.07 DN and is the rule demonstrating itself once more: the
#: prototype's two polar bands were anchored at their own latitudes with square degree pixels, while
#: the shipped grid covers the sphere exactly at the publisher's pixel count, so their rows drift
#: sub-pixel apart with distance from the north pole. The look does not move — `lApc` mean alpha is
#: 0.813 north and 0.756 south either way — but the levels must describe the field that renders.
#:
#: Re-measure with `_ice_ab/scripts/viking_levels.py`, which is the only reproducible owner of these
#: four numbers, and re-measure whenever the FIELD or the CAP GRID moves — both of which is what
#: retired the OMEGA pair that stood here. Its `--compare` mode is what refuses a drift between the
#: field the levels were taken from and the field the renderer reads.
ALPHA_LEVELS: dict[str, tuple[float, float]] = {
    "north": (60.99, 205.58),
    "south": (97.39, 174.01),
}

#: Rec. 709 luma weights — the QUANTITY the four numbers above are stated in.
#:
#: THEY LIVE HERE BECAUSE THE COUPLING IS TO THE LEVELS, not because luma needs a home. A field
#: graded with different weights from the ones the levels were measured through is a different
#: quantity wearing the same units, and `albedo_alpha` says in as many words that nothing can check
#: that pairing. `_ice_ab/scripts/viking_levels.py` re-measures the levels through `luma` below for
#: exactly this reason: the measuring instrument and the render must not be able to drift apart.
#:
#: The other Rec. 709 luma in this repo — `compose/gen_spotlight.py` and two tests — are independent
#: uses of a standard scalarisation, and are deliberately NOT routed through here. Nothing breaks if
#: one of them moves to Rec. 601; this one cannot move without re-measuring `ALPHA_LEVELS`.
LUMA_WEIGHTS: tuple[float, float, float] = (0.2126, 0.7152, 0.0722)


def _smoothstep(fraction: np.ndarray) -> np.ndarray:
    """Clamp to 0..1 and ease both ends. The module's one spelling of it, read by both alphas.

    Kept private and local rather than shared: the array-form smoothstep has several spellings across
    this package and giving it a single owner is its own change, not one to make while adding a
    seventh caller. float64 out, matching `snow.snow_alpha` — the composite blends whichever body's
    answer it is handed, and a narrower dtype from one of them shifts the other's blend sub-DN.
    """
    # The cast is load-bearing and not defensive: the graded field lands as float32, and float32 in
    # would give float32 out under numpy's promotion rules, silently breaking the dtype this promises.
    clipped = np.clip(np.asarray(fraction, dtype=float), 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def luma(rgb: np.ndarray) -> np.ndarray:
    """Rec. 709 luma of a `(3, ...)` RGB stack, as float64 — the field the ice is graded on.

    ZERO IS EXACT INVALIDITY, AND THAT IS A PROPERTY OF THE WEIGHTS RATHER THAN A CONVENTION. Every
    weight is positive and every channel is non-negative, so the sum vanishes only where all three
    channels do — which is precisely Viking's nodata, declared 0 on each band and meaning absent only
    when they agree. That property is what lets `albedo_alpha` keep a scalar sentinel against an RGB
    source: the three bands collapse to one BEFORE anything is graded, and the sentinel survives the
    collapse instead of having to be carried beside it.

    FLOAT64 OUT, AND THE DTYPE IS THE WHOLE POINT AT THE DARK END. A pixel of (1, 0, 0) has luma
    0.2126, which any integer round would flatten to 0 and hand to the grader as "not measured".
    Rounding here would therefore turn the darkest measured ground into nodata, in the one hemisphere
    whose ground level is the lower of the two.
    """
    stack = np.asarray(rgb, dtype=float)
    weights = np.asarray(LUMA_WEIGHTS, dtype=float).reshape(-1, *([1] * (stack.ndim - 1)))
    return (stack * weights).sum(axis=0)


def albedo_alpha(albedo: np.ndarray, levels: tuple[float, float], nodata: float) -> np.ndarray:
    """How icy each pixel is, from the graded field normalised between this pole's two pinned levels.

    `levels` is `(ground, cap)` from `ALPHA_LEVELS`, passed rather than looked up so the caller names
    the pole once and this stays a pure function of its arguments.

    THE FIELD AND THE LEVELS MUST BE THE SAME QUANTITY and nothing here can check that. Levels from
    one field applied to another normalise to zero everywhere, which renders a bare cap and raises
    nothing — so the pairing is the caller's obligation. `ALPHA_LEVELS` is 8-bit luma.

    UNMEASURED PIXELS BECOME ZERO AND ARE COMPARED BEFORE SCALING. A sentinel fill normalised becomes
    an ordinary out-of-range float that the clamp would quietly turn into 0.0 anyway — but only by
    arithmetic accident, and a fill that ever landed inside the range would paint as ice. Masking on
    the raw value makes it a decision.

    A SCALAR SENTINEL FITS THE RGB SOURCE ONLY BECAUSE `luma` COLLAPSES IT FIRST. Viking's invalidity
    is every channel at zero rather than one distinguished value, which no scalar could express — but
    Rec. 709 weights are all positive over non-negative channels, so luma is zero exactly where the
    three bands are. Pass this the luma and 0.0, never a single colour band and a guessed fill.

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
