"""Mars's ice EXTENT: which units are ice where, and a feather that is bounded rather than local.

Nothing here paints a pixel — the producers that will are L2c's, and the alpha they need is licence-
blocked. What is testable now is the part that has no body in it: the hemispheric rule, and the
distance transform, whose banded form is the only reason it can run on a 32768-square grid at all.

THE BANDED PASS IS THE INTERESTING ONE. A distance transform is non-local, and this project has
already recorded that as the reason it bought GLOBathy's pre-computed shore distances rather than
rolling its own. What rescues it here is that the answer is BOUNDED: past the feather every value is
clipped away, so a band padded wider than the feather is exact everywhere the result is read. That is
a claim with a control — a pad too small must break it — and both halves are asserted below.
"""

import numpy as np
import pytest
from scipy import ndimage

from pipeline import vector_raster
from pipeline.acquire import download_sim3292
from pipeline.raster_io import row_bands
from pipeline.render import mars_ice

#: 400 m/px against a 10 km feather puts the feather at exactly 25 pixels, so the band arithmetic
#: below is checkable by hand rather than by re-deriving it in the assertion.
SCALE_M = 400.0
FEATHER_PX = 25


def _blobby_mask() -> np.ndarray:
    """Ice-shaped rather than band-shaped: round edges at several distances from the band seams.

    A mask that is a single horizontal stripe would sit entirely inside one band, so a banded pass
    would agree with a whole-array one however wrong its padding was.
    """
    height, width = 600, 400
    rows, columns = np.mgrid[0:height, 0:width]
    mask = np.zeros((height, width), dtype=bool)
    mask |= (rows - 80) ** 2 + (columns - 150) ** 2 < 60 ** 2
    mask |= (rows - 40) ** 2 + (columns - 320) ** 2 < 30 ** 2
    mask[0:15, :] = True
    return mask


class TestTheExtentIsAsymmetricOnMeasurement:
    def test_apu_is_northern_only(self):
        """The whole asymmetry, in one assertion. Southern `Apu` is within ±0.04 of ordinary ground
        and covers 68.7% of that disc, so drawing it would whiten two thirds of the view."""
        assert set(mars_ice.NORTH_UNITS) - set(mars_ice.SOUTH_UNITS) == {"Apu"}
        assert set(mars_ice.SOUTH_UNITS) == {"lApc"}

    def test_every_unit_drawn_is_a_unit_the_acquirer_fetches(self, subtests):
        """The drift this closes is silent in both directions: a unit named here and not acquired is
        a missing file at render time, and one acquired and never named is 3.8 MB nothing reads."""
        acquired = set(download_sim3292.UNITS)
        for unit in set(mars_ice.NORTH_UNITS) | set(mars_ice.SOUTH_UNITS):
            with subtests.test(unit):
                assert unit in acquired

    def test_the_north_unions_and_the_south_does_not(self):
        lapc = np.array([[True, False, False]])
        apu = np.array([[False, True, False]])
        masks = {"lApc": lapc, "Apu": apu}
        assert mars_ice.extent_for(masks, True).tolist() == [[True, True, False]]
        assert mars_ice.extent_for(masks, False).tolist() == [[True, False, False]]

    def test_a_window_straddling_the_equator_takes_both_rules(self):
        """The Mercator tier's case, which the cap tier cannot produce: one array, two hemispheres.
        `Apu` must appear in the northern row and vanish in the southern one."""
        masks = {"lApc": np.array([[True, False], [True, False]]),
                 "Apu": np.array([[False, True], [False, True]])}
        northern = np.array([True, False]).reshape(-1, 1)
        assert mars_ice.extent_for(masks, northern).tolist() == [[True, True], [True, False]]

    def test_a_missing_unit_raises_rather_than_reading_as_no_ice(self):
        """The failure this refuses is a north extent quietly missing `Apu` — smaller ice, no error,
        and nothing downstream able to tell it from the map saying so."""
        with pytest.raises(KeyError):
            mars_ice.extent_for({"lApc": np.array([[True]])}, True)


class TestTheFeatherIsGroundDistanceAndNotPixels:
    def test_it_is_one_inside_and_zero_past_the_feather(self):
        mask = np.zeros((80, 4), dtype=bool)
        mask[0:50] = True
        alpha = mars_ice.feather_alpha(mask, SCALE_M)
        assert alpha[0:50].min() == 1.0
        assert alpha[50 + FEATHER_PX - 1].max() == 0.0
        assert alpha[79].max() == 0.0

    def test_the_midpoint_of_the_feather_is_the_smoothstep_midpoint(self):
        """Pins the curve, not just its endpoints — a linear ramp passes both assertions above."""
        mask = np.zeros((80, 4), dtype=bool)
        mask[0:50] = True
        alpha = mars_ice.feather_alpha(mask, SCALE_M)
        # distance 12.5 px is half the feather; row 62 is 13 px out, row 61 is 12.
        half = 1.0 - 12.5 * SCALE_M / (mars_ice.FEATHER_KM * 1000.0)
        assert half == pytest.approx(0.5)
        assert alpha[49 + 12, 0] > 0.5 > alpha[49 + 13, 0]

    def test_a_coarser_pixel_makes_a_narrower_feather_in_pixels(self):
        """The whole reason the scale is an argument: the same 10 ground kilometres reaches 24 lit
        pixels at 400 m and 12 at 800, the spread Mercator puts across the band Mars shows ice in.

        24 and not 25 because the far end is half-open — a pixel exactly `feather_km` out is already
        zero, so the lit run past the mask is `ceil(feather_px) - 1` either way.
        """
        mask = np.zeros((80, 4), dtype=bool)
        mask[0:50] = True
        fine = mars_ice.feather_alpha(mask, SCALE_M)
        coarse = mars_ice.feather_alpha(mask, SCALE_M * 2)
        assert (fine[:, 0] > 0).sum() == 50 + 24
        assert (coarse[:, 0] > 0).sum() == 50 + 12

    def test_a_per_row_scale_gives_each_row_its_own_width(self):
        """A 1-D scale is what the Mercator caller passes, one value per row of the window."""
        mask = np.zeros((2, 80), dtype=bool)
        mask[:, 0:50] = True
        alpha = mars_ice.feather_alpha(mask, np.array([SCALE_M, SCALE_M * 2]))
        assert (alpha[0] > 0).sum() == 50 + 24
        assert (alpha[1] > 0).sum() == 50 + 12

    def test_a_non_positive_scale_is_refused(self):
        """It divides the feather into pixels, so a zero is an infinite pad and a silent whole-array
        pass on a grid that cannot hold one."""
        with pytest.raises(ValueError):
            mars_ice.feather_alpha(np.zeros((4, 4), dtype=bool), 0.0)


def _alpha_with_pad(mask: np.ndarray, band_rows: int, pad: int) -> np.ndarray:
    """A banded feather with the pad chosen BY HAND — the shape the module must not be talked into.

    Written out here rather than reached for inside the module because the pad is derived there, and
    a control has to be able to get it wrong. The arithmetic mirrors `feather_alpha_bands`; if the
    two ever disagree for a reason other than the pad, the tests below stop meaning anything.
    """
    feather_m = mars_ice.FEATHER_KM * 1000.0
    outside = ~mask
    alpha = np.empty(mask.shape, dtype=float)
    for row0, row1 in row_bands(mask.shape[0], band_rows):
        top, bottom = max(0, row0 - pad), min(mask.shape[0], row1 + pad)
        distance = np.asarray(ndimage.distance_transform_edt(outside[top:bottom]))[
            row0 - top:row1 - top]
        fraction = np.clip(1.0 - distance * SCALE_M / feather_m, 0.0, 1.0)
        alpha[row0:row1] = fraction * fraction * (3.0 - 2.0 * fraction)
    return alpha


class TestTheBandedPassIsExactWhereItIsRead:
    def test_banding_does_not_change_the_alpha_at_all(self):
        """The property that matters, asserted as exact equality rather than a tolerance: the
        planet-grid pass and a whole-array one must be the same picture."""
        mask = _blobby_mask()
        whole = mars_ice.feather_alpha(mask, SCALE_M)
        bands = list(mars_ice.feather_alpha_bands(mask, SCALE_M, band_rows=90))
        assert np.array_equal(whole, np.vstack([alpha for _row0, _row1, alpha in bands]))

    def test_the_bands_cover_every_row_exactly_once(self):
        """A generator can be exact per band and still lose or double a row at the seams, which the
        equality above would only catch if the lost rows happened to differ."""
        mask = _blobby_mask()
        covered = [row for row0, row1, _ in mars_ice.feather_alpha_bands(mask, SCALE_M, band_rows=90)
                   for row in range(row0, row1)]
        assert covered == list(range(mask.shape[0]))

    def test_an_adequate_pad_is_what_makes_it_exact(self):
        mask = _blobby_mask()
        assert np.array_equal(mars_ice.feather_alpha(mask, SCALE_M),
                              _alpha_with_pad(mask, band_rows=90, pad=FEATHER_PX + 1))

    def test_a_pad_narrower_than_the_feather_breaks_it(self):
        """The control that makes the equality above mean something. Without it the test passes
        against a pad of zero, which is the bug the whole banded form risks."""
        mask = _blobby_mask()
        assert not np.array_equal(mars_ice.feather_alpha(mask, SCALE_M),
                                  _alpha_with_pad(mask, band_rows=90, pad=3))

    def test_no_band_rows_is_one_band(self):
        """`feather_alpha` is spelled as this case, so if it ever stops being one band that function
        silently returns the first slice of an answer instead of the answer."""
        mask = _blobby_mask()
        assert len(list(mars_ice.feather_alpha_bands(mask, SCALE_M))) == 1


class TestAUnitIsResolvedAtCallTime:
    def test_a_redirected_data_root_moves_the_source(self, monkeypatch, tmp_path):
        """The trap the cap registry's own sabotage case proved: a path captured at import answers
        with the location from before a redirect, so a run isolating its data store reads the real
        one. `unit_path` must be called inside `burn_unit`, not frozen beside it."""
        seen: list = []
        monkeypatch.setattr(vector_raster, "burn_onto_grid",
                            lambda source, *args, **kwargs: seen.append(source) or source)
        monkeypatch.setattr(download_sim3292, "DATA_DIR", tmp_path / "elsewhere")
        mars_ice.burn_unit("lApc", "EPSG:3857", (0.0, 0.0, 1.0, 1.0), 2, 2,
                           projected=tmp_path / "p.json", out=tmp_path / "o.tif")
        assert seen == [tmp_path / "elsewhere" / "lapc_sim3292.json"]
