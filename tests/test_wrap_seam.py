"""The antimeridian fill, and the two refusals that keep it from becoming a general hole-filler.

The load-bearing test here is `test_the_fill_is_the_midpoint_of_BOTH_neighbours`. Every other
property in this file would survive a fill that quietly copied the western neighbour — which is the
tempting simplification, is wrong by half a pixel everywhere, and on real terrain would be within
noise of correct, so nothing but a fixture built to separate them can see it.
"""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from pipeline import mercator, wrap_seam

MISSING = -32768.0


def _write(path, array, *, nodata: float | None = MISSING,
           span: float = 2.0 * mercator.MERCATOR_HALF_M):
    """A global float32 raster with `nodata` declared. `span` shrinks it to make it non-global."""
    height, width = array.shape
    half = span / 2.0
    with rasterio.open(
            path, "w", driver="GTiff", height=height, width=width, count=1, dtype="float32",
            crs="EPSG:3857", nodata=nodata,
            transform=from_bounds(-half, -mercator.MERCATOR_HALF_M,
                                  half, mercator.MERCATOR_HALF_M, width, height)) as sink:
        sink.write(array.astype(np.float32), 1)
    return path


def _read(path):
    with rasterio.open(path) as dataset:
        return dataset.read(1), dataset.nodata


def _seamed(rows=8, cols=6, missing_rows=None):
    """A raster whose last column is nodata on `missing_rows`, with west != east everywhere.

    The two neighbours are deliberately far apart and asymmetric about zero, so a fill that used
    either one alone, or that averaged the wrong pair, lands somewhere this file can name.
    """
    array = np.zeros((rows, cols), dtype=np.float32)
    array[:, 0] = np.arange(rows) * 100.0 + 1000.0        # column 0 — the EASTERN neighbour
    array[:, -2] = np.arange(rows) * 10.0 - 4000.0        # the WESTERN neighbour
    array[:, -1] = 7.0                                    # the seam, before any hole is punched
    for row in (range(rows) if missing_rows is None else missing_rows):
        array[row, -1] = MISSING
    return array


# --- The fill -------------------------------------------------------------------------


def test_the_fill_is_the_midpoint_of_BOTH_neighbours(tmp_path):
    """THE GUARD THAT SEPARATES THE FILL FROM ITS TEMPTING SIMPLIFICATION.

    The seam column sits one pixel from column 0 and one from the second-to-last, so the midpoint of
    the two is a linear interpolation evaluated where the missing sample belongs. A copy of either
    neighbour is a half-pixel shift — invisible on real terrain, which is exactly why it needs a
    fixture where the two neighbours are thousands apart and the three candidate answers cannot
    coincide.
    """
    array = _seamed()
    raster = _write(tmp_path / "seam.tif", array)
    filled = wrap_seam.close_wrap_seam(raster)

    assert filled == array.shape[0]
    result, _ = _read(raster)
    expected = 0.5 * (array[:, -2].astype(np.float64) + array[:, 0].astype(np.float64))
    np.testing.assert_allclose(result[:, -1], expected, rtol=0, atol=1e-3)

    # The controls that make the assertion above mean what it says: neither neighbour alone, and
    # not the far side of the raster, produces these numbers.
    assert not np.allclose(result[:, -1], array[:, -2]), "this is a copy of the western neighbour"
    assert not np.allclose(result[:, -1], array[:, 0]), "this is a copy of the eastern neighbour"


def test_pixels_the_warp_did_fill_are_left_alone(tmp_path):
    """Mars's seam is 79% holes, so the 21% that survived are real ground and must not be averaged.

    A fill written as "recompute the whole column" passes every other test in this file.
    """
    array = _seamed(missing_rows=[0, 1, 5])
    raster = _write(tmp_path / "partial.tif", array)
    filled = wrap_seam.close_wrap_seam(raster)

    assert filled == 3
    result, _ = _read(raster)
    kept = [row for row in range(array.shape[0]) if row not in (0, 1, 5)]
    np.testing.assert_array_equal(result[kept, -1], np.full(len(kept), 7.0, dtype=np.float32))


def test_no_column_but_the_seam_is_touched(tmp_path):
    array = _seamed()
    raster = _write(tmp_path / "seam.tif", array)
    wrap_seam.close_wrap_seam(raster)
    result, _ = _read(raster)
    np.testing.assert_array_equal(result[:, :-1], array[:, :-1])


@pytest.mark.parametrize("band_rows", [1, 3, 7, 64])
def test_the_scan_band_cannot_change_the_answer(tmp_path, band_rows):
    """The band split is a MEMORY decision, as it is in `terrain_rgb.encode_raster`.

    Holes are counted per column across bands, so a seam split unevenly across two reads is the
    shape that would produce a different verdict from the same bytes.
    """
    array = _seamed(rows=8, missing_rows=[0, 3, 4, 7])
    raster = _write(tmp_path / f"band{band_rows}.tif", array)
    assert wrap_seam.close_wrap_seam(raster, band_rows=band_rows) == 4


# --- The refusals ---------------------------------------------------------------------


def test_a_hole_off_the_seam_raises_rather_than_being_filled(tmp_path):
    """The refusal that stops this becoming a general hole-filler.

    Earth's land DEM has real gaps — a missing Copernicus tile fuses as ocean — so a rule that
    smoothed every hole would invent ground on the body with the most to invent.
    """
    array = _seamed()
    array[2, 2] = MISSING
    raster = _write(tmp_path / "interior.tif", array)
    with pytest.raises(SystemExit, match="other than its wrap seam"):
        wrap_seam.close_wrap_seam(raster)


def test_the_interior_hole_is_reported_with_its_column_and_count(tmp_path):
    """A refusal that does not say WHERE sends the reader back to the raster to re-find it."""
    array = _seamed(rows=8, cols=6)
    array[:, 3] = MISSING
    raster = _write(tmp_path / "column.tif", array)
    with pytest.raises(SystemExit, match=r"column 3 \(8 px\)"):
        wrap_seam.close_wrap_seam(raster)


def test_a_raster_that_is_not_global_raises(tmp_path):
    """Its edges are not neighbours, so there is nothing to interpolate ACROSS.

    The failure this catches is the fill being pointed at a regional raster, where averaging column
    0 into the last column joins two places that are a hemisphere apart.
    """
    array = _seamed()
    raster = _write(tmp_path / "regional.tif", array, span=mercator.MERCATOR_HALF_M)
    with pytest.raises(SystemExit, match="edges are not neighbours"):
        wrap_seam.close_wrap_seam(raster)


def test_globalness_is_judged_to_within_a_pixel_not_to_the_decimal(tmp_path):
    """Earth's heightfield overshoots the half-extent by 12.25 m and is global; Mars lands on it.

    A check written against the digits would accept one body and reject the other while describing
    itself as a test of the projection.
    """
    array = _seamed()
    overshoot = _write(tmp_path / "earthlike.tif", array,
                       span=2.0 * mercator.MERCATOR_HALF_M + 24.5)
    assert wrap_seam.close_wrap_seam(overshoot) == array.shape[0]


# --- The declaration ------------------------------------------------------------------


def test_a_closed_raster_declares_no_nodata_and_a_second_call_is_free(tmp_path):
    """The postcondition is a claim the FILE makes, which is what makes this idempotent.

    A resumable pipeline re-enters this; without the declaration it would re-scan a 17 GB raster
    every time, and worse, it would have no way to say it was already closed.
    """
    raster = _write(tmp_path / "seam.tif", _seamed())
    assert wrap_seam.close_wrap_seam(raster) > 0
    _, nodata = _read(raster)
    assert nodata is None, "the raster still claims to have missing data it no longer has"
    assert wrap_seam.close_wrap_seam(raster) == 0


def test_a_raster_with_no_nodata_declared_is_left_untouched(tmp_path):
    """Earth's heightfield declares none, so this is the path Earth takes through the warp."""
    array = _seamed()
    raster = _write(tmp_path / "undeclared.tif", array, nodata=None)
    assert wrap_seam.close_wrap_seam(raster) == 0
    result, _ = _read(raster)
    np.testing.assert_array_equal(result, array)
