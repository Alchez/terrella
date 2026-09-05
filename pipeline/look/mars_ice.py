"""Mars's polar ice: which mapped units are ice, how icy each pixel of them is, and how the edge
between that and bare ground is softened.

Two fields, and they come from different places. The extent says where white is drawn at all and
comes from a geologic map (`acquire/download_sim3292.py` holds why); the alpha says how white, and
comes from the Viking colour mosaic's luma (`ALPHA_LEVELS`). Keeping them separate is what lets the
map limit the claim while the albedo supplies the variation, and the arm that let albedo do both was
judged and rejected, roughly 45% of its ice falling outside the mapped unit and reading as seasonal
frost caught in a multi-year average.

The extents are corroborated by published areas, which is worth stating because a geologic unit
chosen by us could otherwise be an arbitrary polygon. North `lApc | Apu` integrates to 1,095,880 km²
against a published Planum Boreum area of about 1,000,000, where `lApc` alone is 596,893 and would
be 40% short, so the published figure independently supports including `Apu` in the north. South
`lApc` is 103,642 km² against a south polar residual cap of about 87,000.

The extent is asymmetric on measurement and not on symmetry. `lApc` is ice at both poles; `Apu`
joins it in the north only, because the albedo puts northern `Apu` well above ordinary ground at
matched latitude while southern `Apu` is indistinguishable from it and covers 68.7% of that disc,
so painting it south would whiten two thirds of the view on no evidence. A body's hemisphere is a
real input here rather than a tidy-up, and two sources reproduce the split independently.

The geology says the same thing on its own, which is why the asymmetry is not a fudge: the southern
`Apu` polygon is the south polar layered deposits, a dusty stack rather than a residual ice cap, so
a unit the albedo finds indistinguishable from ordinary ground is one the stratigraphy also says is
not surface ice. Two lines of evidence, neither derived from the other.

The feather is drawn and must never be described as observed. The published linework was drawn while
viewing at 1:5,000,000 with 5 km vertex spacing, so a hard edge between two of those vertices reads
as faceted; `FEATHER_KM` softens that and nothing measured it. A distance transform wearing a
measurement's clothes is the `antarctic_snow_mask` mistake, one module over.

How wide that is on screen is not a constant and must not be written down as one: a pixel count
belongs to a tile ceiling and a latitude, neither of which this module owns. A figure like "~8
pixels per vertex" is arithmetic at the equator wearing a polar label, and the ice sits at 76-85
degrees where a Mercator pixel is a fraction of its equatorial ground size, so the real count is
many times that and doubles with every rung the ceiling gains. Derive it from
`bodies.ground_metres_per_mercator_unit` against the latitude in hand.

The ice edge has been measured and that is a different quantity: do not let the number migrate into
`FEATHER_KM`. Signed distance to the south's mapped contact puts real ice fading over about 12
ground km outside it, and the north has no albedo edge at all across 130 km. That validates the
extent, where the feather anti-aliases a drawn boundary, so its anchor is the linework and not the
ice. The profile is not re-runnable, having been taken against a source this project no longer
acquires, so those two figures are the record rather than something to re-derive.

The feather is the one thing that cannot be computed per window. A distance transform is non-local:
a pixel's distance to the nearest ice can be owned by a pixel outside whatever slice is in hand, and
this project has already paid for that lesson on GLOBathy's shore distances. It is bounded here,
which is what rescues it, nothing past `FEATHER_KM` changing the answer, so a banded pass with a pad
wider than the feather is exact where the result is used and only there.
"""

import json
import subprocess
from collections.abc import Iterator
from functools import reduce
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import rasterio.transform
from rasterio.windows import Window
from scipy import ndimage

from pipeline import mercator, vector_raster
from pipeline.acquire import download_sim3292
from pipeline.raster_io import row_bands

#: The mapped units drawn as ice, per hemisphere. Both tuples are read by `extent_for`, and the
#: difference between them is the measurement in the module note rather than a spelling choice.
NORTH_UNITS: tuple[str, ...] = ("lApc", "Apu")
SOUTH_UNITS: tuple[str, ...] = ("lApc",)

#: How far outside the mapped contact the ice fades to nothing, in ground kilometres.
#:
#: Drawn and not measured, and it is one vertex spacing, the only anchor this constant has ever had:
#: its whole job is to stop a 5 km-vertex boundary stair-stepping, so it anti-aliases a contact the
#: publisher mapped rather than standing in for a gradient nobody observed.
#:
#: Two traps have caught it. A feather anchored to a gradient is a different constant answering a
#: different question; and dividing this by AEQD map metres, which on Mars are Earth metres, renders
#: roughly half the ground distance under a label saying the full one, so the scale a caller passes
#: must be ground metres per pixel: see `feather_alpha_bands`.
#:
#: Do not re-anchor it to the measured 12 km ice edge; that is the width of ice this design
#: deliberately does not paint, and the module note above holds why the two are different quantities.
FEATHER_KM = 5.0

#: Viking colour LUMA mapping to alpha 0 and 1, per pole: the median of ground that is neither mapped
#: unit, and the median of `lApc`. 8-bit Rec. 709 luma, so these live on 0..255 and not on 0..1.
#:
#: `lApc` alone sets the cap level at both poles, including the north where the extent also takes
#: `Apu`; and ground excludes both units at both poles, including the south where `Apu` is not ice.
#: Neither is `extent` or `~extent`, and reading them as such moves the look.
#:
#: Pinned and never recomputed, which is correctness rather than tidiness: the two tiers grade the
#: same ice over different pixel sets, an AEQD disc and a Mercator strip, so percentiles taken per
#: grid would disagree, and the cap and the tiles crossfade across 80-84 degrees where a
#: disagreement is visible as a step. That grid-dependence is measured rather than feared: moving
#: the cap edge two degrees moved the north's cap level 11.4% and left the south's within 0.03 DN.
#:
#: Measured over `viking_luma`'s shipped raster and not over a band built to answer the question,
#: because a band anchored at its own latitudes drifts sub-pixel from the shipped grid with distance
#: from the pole. The look does not move either way; the levels must describe the field that renders.
#:
#: Re-measure with `scripts/measure_viking_levels.py`, the only reproducer of these four numbers,
#: whenever the field or the cap grid moves. Its `--compare` mode is what refuses a drift between
#: the field the levels were taken from and the field the renderer reads.
ALPHA_LEVELS: dict[str, tuple[float, float]] = {
    "north": (60.99, 205.58),
    "south": (97.39, 174.01),
}

#: Rec. 709 luma weights: the quantity the four numbers above are stated in.
#:
#: They live here because the coupling is to the levels, not because luma needs a home. A field
#: graded with different weights from the ones the levels were measured through is a different
#: quantity wearing the same units, and `albedo_alpha` says in as many words that nothing can check
#: that pairing. `scripts/measure_viking_levels.py` re-measures the levels through `luma` below for
#: exactly this reason: the measuring instrument and the render must not be able to drift apart.
#:
#: The other Rec. 709 luma in this repo, in `compose/gen_spotlight.py` and two tests, are
#: independent uses of a standard scalarisation and deliberately not routed through here. Nothing
#: breaks if one moves to Rec. 601; this one cannot move without re-measuring `ALPHA_LEVELS`.
LUMA_WEIGHTS: tuple[float, float, float] = (0.2126, 0.7152, 0.0722)


def _smoothstep(fraction: np.ndarray) -> np.ndarray:
    """Clamp to 0..1 and ease both ends. The module's one spelling of it, read by both alphas.

    Kept private and local rather than shared: the array-form smoothstep has several spellings across
    this package and giving it a single owner is its own change, not one to make while adding a
    seventh caller. float64 out, matching `snow.snow_alpha` — the fold blends whichever body's
    answer it is handed, and a narrower dtype from one of them shifts the other's blend sub-DN.
    """
    # The cast is load-bearing and not defensive: the graded field lands as float32, and float32 in
    # would give float32 out under numpy's promotion rules, silently breaking the dtype this promises.
    clipped = np.clip(np.asarray(fraction, dtype=float), 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def luma(rgb: np.ndarray) -> np.ndarray:
    """Rec. 709 luma of a `(3, ...)` RGB stack, as float64: the field the ice is graded on.

    Zero is exact invalidity, and that is a property of the weights rather than a convention. Every
    weight is positive and every channel is non-negative, so the sum vanishes only where all three
    channels do, which is precisely Viking's nodata, declared 0 on each band and meaning absent only
    when they agree. That is what lets `albedo_alpha` keep a scalar sentinel against an RGB source:
    the three bands collapse to one before anything is graded, so the sentinel survives the collapse
    instead of having to be carried beside it.

    Float64 out, and the dtype is the whole point at the dark end: a pixel of (1, 0, 0) has luma
    0.2126, which any integer round would flatten to 0 and hand to the grader as "not measured",
    turning the darkest measured ground into nodata in the hemisphere whose ground level is lower.
    """
    stack = np.asarray(rgb, dtype=float)
    weights = np.asarray(LUMA_WEIGHTS, dtype=float).reshape(-1, *([1] * (stack.ndim - 1)))
    return (stack * weights).sum(axis=0)


def albedo_alpha(albedo: np.ndarray, levels: tuple[float, float], nodata: float) -> np.ndarray:
    """How icy each pixel is, from the graded field normalised between this pole's two pinned levels.

    `levels` is `(ground, cap)` from `ALPHA_LEVELS`, passed rather than looked up so the caller names
    the pole once and this stays a pure function of its arguments.

    The field and the levels must be the same quantity and nothing here can check that: levels from
    one field applied to another normalise to zero everywhere, which renders a bare cap and raises
    nothing, so the pairing is the caller's obligation. `ALPHA_LEVELS` is 8-bit luma.

    Unmeasured pixels become zero and are compared before scaling. A sentinel fill normalised becomes
    an ordinary out-of-range float the clamp would turn into 0.0 anyway, but only by arithmetic
    accident, and a fill that ever landed inside the range would paint as ice. Masking on the raw
    value makes it a decision.

    A scalar sentinel fits the RGB source only because `luma` collapses it first: Viking's invalidity
    is every channel at zero rather than one distinguished value, which no scalar could express,
    where luma is zero exactly when the three bands are. Pass this the luma and 0.0, never a single
    colour band and a guessed fill.

    This is the owner of the ratified arithmetic, and the shape is what was ratified rather than any
    of its inputs: a field normalised between two levels and eased. Pinned levels, Viking luma and
    float64 all arrived under that shape without the look moving.
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
    whole stage is shaped around. The source is resolved through `download_sim3292.unit_path` at call
    time so a redirected data root moves it, per `paths`.

    `must_draw` is the caller's claim and is deliberately not defaulted. On a planet grid an empty
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
    `feather_km` ground kilometres outside it.

    A generator because the result is the thing that does not fit, which is a different problem from
    the transform's own peak. Mars's planet grid is 32768 square, so
    one float64 alpha for it is 8.6 GB — bounding the distance transform to a band and then
    materialising the whole answer would still not run. Handing back one band at a time lets the
    caller write it and drop it, and it is what makes `band_rows` worth having at all.

    `ground_metres_per_px` converts the transform's pixels into ground metres, as a scalar or a value
    per row of the whole mask. It has to be either, because a Mercator pixel is not a fixed ground
    distance: across the band where Mars's tiles show ice it runs about 152 m down to 68, so a
    feather counted in pixels would be more than twice as wide at one end as the other. A cap's AEQD
    grid has no such term and passes one number. The ratio behind it belongs to
    `bodies.ground_metres_per_mercator_unit` / `..._aeqd_unit`; only the composition is here.

    Bands are exact where they are read and wrong beyond, which is the whole bargain. Each is
    transformed with `pad` extra rows on both sides, so any nearest-ice within `pad` pixels is inside
    the slice that computed it; a cell whose nearest ice lies further away gets a number too large,
    and every such cell is already past the feather and clipped to zero.

    Alpha is float64, matching `snow.snow_alpha` — the fold blends whichever body's answer it is
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


def graded_alpha(field: np.ndarray, northern, nodata: float) -> np.ndarray:
    """The field graded between the pinned levels of whichever pole each row belongs to.

    The twin of `extent_for` and broadcast the same way: a plain bool for a cap disc, a per-row
    column for a Mercator strip that may straddle the equator. `np.where` evaluates both branches,
    which is why this is cheap only on a slice: hand it a whole planet and it grades one twice.

    The two poles are different quantities sharing a scale. A single pair of levels applied to both
    would grade the south against the north's darker ground and paint its cap several tenths too
    white, which is precisely the disagreement the pinning note on `ALPHA_LEVELS` exists to prevent.
    """
    return np.where(northern,
                    albedo_alpha(field, ALPHA_LEVELS["north"], nodata),
                    albedo_alpha(field, ALPHA_LEVELS["south"], nodata))


def unit_latitude_span(unit: str, northern: bool) -> "tuple[float, float] | None":
    """How far one unit's polygons reach in one hemisphere, in degrees, or None if it has none there.

    Per hemisphere, and that is the whole point of the argument: `lApc` is mapped at both poles, so
    a single span over its features runs -90 to +90 and describes a planet rather than an extent,
    which would quietly turn the banded build below back into the whole-grid one it exists to avoid.

    Read from the geometry and never pinned. The published reaches are recorded in this project's notes
    and would serve as constants right up until the publisher revises a polygon, at which point a
    hard-coded band clips real ice with nothing raising. The acquirer guarantees the file's edition;
    the extent is then the file's own business.

    The GeoJSON carries no `bbox`, so the coordinates are walked — a few MB of parse against a stage
    measured in minutes.
    """
    def latitudes(node) -> "Iterator[float]":
        # A position is [lon, lat, ...]; anything else is a nest of them. Testing the FIRST element
        # for a scalar distinguishes the two without assuming a geometry type.
        if node and isinstance(node[0], (int, float)):
            yield float(node[1])
            return
        for child in node:
            yield from latitudes(child)

    document = json.loads(download_sim3292.unit_path(unit).read_text(encoding="utf-8"))
    values = [value
              for feature in document["features"]
              for value in latitudes(feature["geometry"]["coordinates"])
              if (value >= 0.0) == northern]
    return (min(values), max(values)) if values else None


def ice_bands(bounds: tuple[float, float, float, float], height: int,
              pad_rows: int) -> list[tuple[int, int, bool]]:
    """Each `(row0, row1, northern)` of a 3857 grid a mapped unit can reach. Empty if none can.

    Why the build is bands and not a planet: this layer is only ever painted where a unit reaches,
    which on Mars is a few degrees at each pole; the rest of a 32768-row grid is ice-free by
    construction. Deriving the rows from the units rather than from a latitude constant keeps that an
    observation about the data instead of a number someone has to maintain.

    One band per hemisphere, each carrying which one it is, because the levels and the unit union
    both differ per pole and a single band spanning the equator could answer for neither.

    `pad_rows` must cover the feather: a pixel outside every unit still takes alpha from one within
    `FEATHER_KM` of it, so a band cut to the polygons alone would clip the feather at its own edge.
    """
    _left, bottom, _right, top = bounds
    pixel = (top - bottom) / height
    bands: list[tuple[int, int, bool]] = []
    for northern, units in ((True, NORTH_UNITS), (False, SOUTH_UNITS)):
        spans = [span for span in (unit_latitude_span(unit, northern) for unit in units) if span]
        if not spans:
            continue
        rows = [round((top - float(mercator.northing_at(
                    np.array([latitude]), mercator.WEB_MERCATOR_RADIUS_M)[0])) / pixel)
                for span in spans for latitude in span]
        row0, row1 = max(0, min(rows) - pad_rows), min(height, max(rows) + pad_rows)
        if row1 > row0:
            bands.append((row0, row1, northern))
    return bands


#: Rows graded at once. `graded_alpha` evaluates both poles in float64, so a slice costs several
#: times its float32 footprint while it is in hand — sized to stay inside the one-heavy-job cap.
GRADE_ROWS = 512


def _warp_band(field: Path, bounds: tuple[float, float, float, float], width: int, height: int,
               out: Path) -> Path:
    """The 4326 field on one band of the 3857 grid, in one gdalwarp.

    Direct rather than the sub-banded mosaic the two Earth cryosphere warps use, and the difference
    is the extent being warped rather than a preference. That mosaic exists because a whole-grid
    warp's pole-inflated average scale makes gdalwarp read the source decimated — the failure has no
    error and no symptom beyond structure quietly going missing. A band spans a narrow enough range
    of scales that the average is honest, which was measured on this grid against a sub-banded
    reference and against a deliberately decimated control; `scripts/` has no home for that probe, so
    the numbers live in PROCESS.md.

    Do not "fix" this by adding banding: it would cost a subprocess per sub-band for output already
    shown identical, and it would read as though the decimation question here were open.
    """
    left, bottom, right, top = bounds
    subprocess.run(
        ["gdalwarp", "-q", "-overwrite", "-t_srs", "EPSG:3857",
         "-te", repr(left), repr(bottom), repr(right), repr(top),
         "-ts", str(width), str(height), "-r", "bilinear", "-ot", "Float32",
         "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=YES",
         str(field), str(out)], check=True)
    return out


def build_alpha_raster(field: Path, field_nodata: float,
                       bounds: tuple[float, float, float, float], width: int, height: int,
                       out: Path, ground_metres_per_map_unit: float) -> Path:
    """This body's ice alpha on the 3857 grid: graded between the pinned levels, cut to the mapped
    units, feathered outward — and computed only where a unit can reach.

    Zero is a value here and not an absence, which is why the output declares no nodata. Every row
    outside a band is ice-free by construction, so the blocks that are never written read back as
    alpha 0 and mean it. A nodata of 0 would say "unmeasured" about pixels this stage measured and
    found bare.

    The feather is why the bands are padded: a pixel outside every polygon still takes alpha from
    one within `FEATHER_KM` of it, so a band cut to the polygons alone clips its own feather at the
    band edge, visible as a hard line parallel to no coastline.

    The scale passed down is ground metres per pixel and it varies per row. A Mercator pixel is not a
    fixed ground distance; across the latitudes this layer occupies it changes by more than half, so
    a feather counted in pixels would be markedly wider at one end of the band than the other.
    `feather_alpha_bands` holds the argument, and `ground_metres_per_map_unit` is the body's own
    conversion rather than anything derivable here.
    """
    left, bottom, right, top = bounds
    pixel = (top - bottom) / height
    map_units_per_px = (right - left) / width
    edge_latitude = float(mercator.latitude_at(np.array([top]), mercator.WEB_MERCATOR_RADIUS_M)[0])
    # The finest ground pixel the grid can hold sits at its top row, so a pad derived from it covers
    # the feather at every latitude a band could occupy. Derived, never a constant: the grid's own
    # edge latitude is what sets it.
    finest = map_units_per_px * ground_metres_per_map_unit * float(
        np.cos(np.radians(edge_latitude)))
    pad_rows = int(np.ceil(FEATHER_KM * 1000.0 / finest)) + 1

    profile: dict[str, Any] = dict(
        driver="GTiff", width=width, height=height, count=1, dtype="float32", crs="EPSG:3857",
        transform=rasterio.transform.from_bounds(left, bottom, right, top, width, height),
        tiled=True, compress="DEFLATE", bigtiff="YES")
    work = out.parent
    with rasterio.open(out, "w", **profile) as writer:  # pyright: ignore[reportCallIssue]
        for row0, row1, northern in ice_bands(bounds, height, pad_rows):
            pole = "north" if northern else "south"
            band_bounds = (left, top - row1 * pixel, right, top - row0 * pixel)
            band_height = row1 - row0
            drawn = NORTH_UNITS if northern else SOUTH_UNITS
            masks = {
                unit: _read_mask(burn_unit(
                    unit, "EPSG:3857", band_bounds, width, band_height,
                    projected=work / f"ice_{pole}_{unit.lower()}_3857.geojson",
                    out=work / f"ice_{pole}_{unit.lower()}.tif",
                    # Only the units this hemisphere PAINTS are guaranteed to land: the band was
                    # derived from their own reach. The other is burnt because `extent_for`
                    # evaluates both unions, and it may legitimately be empty here.
                    must_draw=(f"{unit} must reach the {pole} band it defines"
                               if unit in drawn else None)))
                for unit in NORTH_UNITS
            }
            latitude = mercator.latitude_at(
                top - (np.arange(row0, row1) + 0.5) * pixel, mercator.WEB_MERCATOR_RADIUS_M)
            scale = map_units_per_px * ground_metres_per_map_unit * np.cos(np.radians(latitude))
            warped = _warp_band(field, band_bounds, width, band_height,
                                work / f"ice_{pole}_field.tif")
            extent = extent_for(masks, northern)
            with rasterio.open(warped) as reader:
                for sub0, sub1, feather in feather_alpha_bands(extent, scale,
                                                               band_rows=GRADE_ROWS):
                    window = Window(0, sub0, width, sub1 - sub0)  # pyright: ignore[reportCallIssue]
                    graded = graded_alpha(reader.read(1, window=window), northern, field_nodata)
                    writer.write((graded * feather).astype(np.float32), 1,
                                 window=Window(0, row0 + sub0, width,  # pyright: ignore[reportCallIssue]
                                               sub1 - sub0))
    return out


def _read_mask(path: Path) -> np.ndarray:
    """A burnt 0/1 raster as a boolean array."""
    with rasterio.open(path) as dataset:
        return dataset.read(1) != 0
