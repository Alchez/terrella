"""Mars's polar ice EXTENT: which mapped units are ice, and how their edge is softened.

WHAT THIS IS AND IS NOT. The white on Mars's poles is two fields — an extent (where white is drawn
at all) and an alpha (how white each pixel inside it is). Everything here is the extent.
`acquire/download_sim3292.py` holds why the extent comes from a geologic map rather than from a
measured field, and the alpha it would be graded by is licence-blocked; the two are independent,
which is why one being stuck does not stop the other.

THE EXTENT IS ASYMMETRIC ON MEASUREMENT, NOT ON SYMMETRY. `lApc` is ice at both poles. `Apu` joins it
in the NORTH only, because OMEGA puts northern `Apu` +0.13 to +0.16 above ordinary ground at matched
latitude — 55-80% of the way from bare ground to the residual cap — while southern `Apu` sits within
±0.04 of ordinary ground and covers 68.7% of that disc. Painting it south would whiten two thirds of
the view on no evidence. So a body's hemisphere is a real input here and not a tidy-up.

THE FEATHER IS DRAWN AND MUST NEVER BE DESCRIBED AS OBSERVED. The published linework was drawn while
viewing at 1:5,000,000 with 5 km vertex spacing, so against the tiles' polar pixels it is roughly
eight pixels per vertex and a hard edge reads as faceted. `FEATHER_KM` softens that and nothing
measured it — a distance transform wearing a measurement's clothes is the `antarctic_snow_mask`
mistake, one module over.

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
#: DRAWN, NOT MEASURED, and the number is small on purpose. Its whole job is to stop a 5 km-vertex
#: boundary stair-stepping, so it is anti-aliasing over a contact the publisher mapped — not a
#: gradient standing in for one nobody observed. An earlier arm used 25 km because the feather WAS
#: the gradient there; that arm is not the one that ships, and its width does not transfer.
FEATHER_KM = 10.0


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
        fraction = np.clip(1.0 - distance * rows / feather_m, 0.0, 1.0)
        yield row0, row1, fraction * fraction * (3.0 - 2.0 * fraction)


def feather_alpha(mask: np.ndarray, ground_metres_per_px,
                  feather_km: float = FEATHER_KM) -> np.ndarray:
    """The whole feathered alpha at once, for a grid that fits — a cap disc, or one window.

    Spelled as the single-band case of the generator rather than as its own transform, so there is
    one arithmetic here and no second copy to drift. `band_rows=None` is that single band.
    """
    (_row0, _row1, alpha), = feather_alpha_bands(mask, ground_metres_per_px, feather_km)
    return alpha
