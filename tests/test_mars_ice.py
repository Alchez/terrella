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

import json

import numpy as np
import pytest
from scipy import ndimage

from pipeline import mercator, vector_raster
from pipeline.acquire import download_sim3292
from pipeline.look import mars_ice
from pipeline.raster_io import row_bands

#: A fill value for the alpha tests. LOCAL AND ARBITRARY ON PURPOSE, where it once came from the
#: extractor: the graded field is now an 8-bit colour mosaic whose invalidity is every channel at
#: zero rather than one distinguished number, so there is no producer constant left to borrow. What
#: `albedo_alpha` still owes is that whatever it is told is unmeasured becomes exactly zero.
NODATA = -9999.0

#: 200 m/px against the 5 km feather puts the feather at exactly 25 pixels, so the band arithmetic
#: below is checkable by hand rather than by re-deriving it in the assertion.
SCALE_M = 200.0   # ground metres per pixel; FEATHER_KM / this = FEATHER_PX exactly
FEATHER_PX = 25

#: The full EPSG:3857 square every planet's composite grid spans, as (left, bottom, right, top).
WHOLE_MERCATOR = (-20037508.342789244, -20037508.342789244,
                  20037508.342789244, 20037508.342789244)


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


class TestTheAlphaIsTheFieldBetweenTwoPinnedLevels:
    def test_the_two_levels_map_to_zero_and_one(self):
        """THE TWO ENDS ARE NOT EQUALLY EXACT AND ONLY ONE OF THEM CAN BE. The low end is exact
        because the CLAMP produces it: every literal here rounds slightly low in float32, so the
        ground level lands fractionally negative and clips to a true 0.0. The high end is reached by
        ARITHMETIC, so it carries the float32 error of the raster it came from.

        Exact equality passed here for years and was a coincidence of magnitude, not a property: on
        0..1 reflectance that error was 3e-9 and `smoothstep(1-e) ~ 1 - 3e**2` fell below float64's
        resolution, while on 0..255 luma the same relative error is 12x larger and 3e**2 does not.
        Asserting bit-equality again would re-pin the constants' size rather than the ramp's ends.
        """
        ground, cap = mars_ice.ALPHA_LEVELS["north"]
        alpha = mars_ice.albedo_alpha(np.array([[ground, cap]], dtype=np.float32),
                                      (ground, cap), NODATA)
        assert alpha[0, 0] == 0.0
        assert alpha[0, 1] == pytest.approx(1.0, abs=1e-9)

    def test_it_clamps_outside_the_levels_rather_than_extrapolating(self):
        """Albedo runs past both levels on the real disc — the cap median is a MEDIAN, so half the
        cap is brighter than it, and unclamped those pixels would exceed alpha 1."""
        ground, cap = mars_ice.ALPHA_LEVELS["south"]
        alpha = mars_ice.albedo_alpha(np.array([[ground - 0.2, cap + 0.2]], dtype=np.float32),
                                      (ground, cap), NODATA)
        assert alpha.tolist() == [[0.0, 1.0]]

    def test_it_eases_rather_than_ramping_linearly(self):
        """Pins the curve: a linear normalise passes both tests above and looks different."""
        ground, cap = 0.0, 1.0
        quarter = mars_ice.albedo_alpha(np.array([[0.25]], dtype=np.float32), (ground, cap), NODATA)
        assert quarter[0, 0] == pytest.approx(0.15625)   # smoothstep(0.25), not 0.25

    def test_the_fill_is_zero_even_when_it_would_land_INSIDE_the_range(self):
        """The reason the fill is compared on the RAW value. A fill inside the levels normalises to
        an ordinary alpha, and no downstream range check could tell it from measured albedo."""
        inside_fill = 120.0
        ground, cap = mars_ice.ALPHA_LEVELS["north"]
        assert ground < inside_fill < cap, "the fixture must actually sit inside the range"
        alpha = mars_ice.albedo_alpha(np.array([[inside_fill]], dtype=np.float32),
                                      (ground, cap), nodata=inside_fill)
        assert alpha[0, 0] == 0.0

    def test_the_alpha_is_float64_from_a_float32_raster(self):
        """The graded field lands as float32 and `snow.snow_alpha` returns float64; the composite
        blends whichever body's answer it is handed, so a narrower dtype here shifts the other's."""
        levels = mars_ice.ALPHA_LEVELS["north"]
        assert mars_ice.albedo_alpha(np.zeros((2, 2), dtype=np.float32), levels, NODATA).dtype == \
            np.float64

    def test_both_poles_are_registered_and_they_differ(self):
        """A shared pair would grade the south's brighter cap on the north's darker ground."""
        assert set(mars_ice.ALPHA_LEVELS) == {"north", "south"}
        assert mars_ice.ALPHA_LEVELS["north"] != mars_ice.ALPHA_LEVELS["south"]
        for ground, cap in mars_ice.ALPHA_LEVELS.values():
            assert 0.0 < ground < cap <= 255.0

    def test_the_levels_sit_in_the_eight_bit_luma_domain_and_not_a_reflectance_one(self):
        """THE BOUND ABOVE IS THE POINT, not a formality. These graded OMEGA reflectance on 0..1
        until the licence closed that source, and levels from one field silently grade a different
        one to alpha 0 everywhere — a bare cap with no exception raised anywhere. A pair that would
        pass as reflectance is the failure this refuses."""
        for ground, cap in mars_ice.ALPHA_LEVELS.values():
            assert cap > 1.0, "a cap level at or below 1.0 is a reflectance pair, not luma"


class TestTheLumaIsTheQuantityTheLevelsAreStatedIn:
    def test_it_is_rec_709_and_the_weights_are_a_partition_of_one(self):
        """Pins the standard rather than the arithmetic. Rec. 601 (0.299/0.587/0.114) is the
        plausible substitution — it is the other luma every codebase carries, it sums to one too,
        and swapping it re-grades every pixel against levels measured through these three."""
        assert mars_ice.LUMA_WEIGHTS == (0.2126, 0.7152, 0.0722)
        assert sum(mars_ice.LUMA_WEIGHTS) == pytest.approx(1.0, abs=1e-12)

    def test_it_matches_the_weighted_sum_taken_by_hand(self):
        red, green, blue = 200.0, 100.0, 50.0
        stack = np.array([[[red]], [[green]], [[blue]]], dtype=np.float32)
        weight_r, weight_g, weight_b = mars_ice.LUMA_WEIGHTS
        assert mars_ice.luma(stack)[0, 0] == pytest.approx(
            weight_r * red + weight_g * green + weight_b * blue)

    def test_zero_luma_means_every_channel_was_zero_and_nothing_else(self):
        """THE PROPERTY THE SCALAR SENTINEL RESTS ON. Viking's nodata is all three bands at zero,
        which no single value can express — so `albedo_alpha` may keep a scalar fill only while luma
        vanishes exactly there and nowhere else. Positive weights over non-negative channels is what
        makes that true, and a weight of 0 on any channel would quietly break it."""
        absent = np.zeros((3, 1, 1), dtype=np.float32)
        assert mars_ice.luma(absent)[0, 0] == 0.0
        for channel in range(3):
            single = np.zeros((3, 1, 1), dtype=np.float32)
            single[channel] = 1.0
            assert mars_ice.luma(single)[0, 0] > 0.0, (
                f"a pixel measured only in band {channel + 1} reads as NOT MEASURED, so the "
                f"darkest real ground would be dropped from the grading")

    def test_the_dimmest_measurable_pixel_survives_as_measured(self):
        """The case an integer round destroys. (1, 0, 0) has luma 0.2126, which rounds to 0 — and 0
        is the fill, so that pixel would arrive at the grader as absent rather than as the darkest
        ground there is. float64 out is what keeps it, and this is why."""
        dimmest = np.array([[[1.0]], [[0.0]], [[0.0]]], dtype=np.float32)
        value = mars_ice.luma(dimmest)[0, 0]
        assert value == pytest.approx(0.2126)
        assert round(value) == 0, "the fixture must be a pixel an integer round would zero"
        alpha = mars_ice.albedo_alpha(np.array([[value]]), mars_ice.ALPHA_LEVELS["north"], 0.0)
        assert alpha[0, 0] == 0.0  # graded as dark ground, not masked as absent

    def test_the_measuring_script_and_the_render_cannot_use_different_weights(self):
        """`ALPHA_LEVELS` is meaningless apart from the weights it was measured through, and the
        instrument that measured it lives outside the package under gitignored `data/`. This asserts
        the constant is importable as the one owner, so that script has something to import rather
        than a fourth copy to keep in step."""
        assert isinstance(mars_ice.LUMA_WEIGHTS, tuple)
        assert len(mars_ice.LUMA_WEIGHTS) == 3
        assert all(weight > 0.0 for weight in mars_ice.LUMA_WEIGHTS)


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
        """The whole reason the scale is an argument: the same 5 ground kilometres reaches 24 lit
        pixels at 200 m and 12 at 400. Mercator gives Mars's ice band 152 m/px down to 68, so a
        feather counted in pixels would be more than twice as wide at one end as the other.

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


def _units(tmp_path, monkeypatch, **spans) -> None:
    """Stand in for the acquired units with polygons at chosen latitudes.

    SYNTHETIC RATHER THAN THE ACQUIRED FILES, so these run on a clone with no data store — and so
    the latitudes under test are chosen rather than whatever the publisher currently draws.
    """
    def polygon(low, high):
        return {"type": "Feature", "properties": {},
                "geometry": {"type": "Polygon",
                             "coordinates": [[[0.0, low], [1.0, low], [1.0, high],
                                              [0.0, high], [0.0, low]]]}}

    # EVERY unit the module consults, not only the ones a case names: `ice_bands` reads both
    # tuples, so a unit left unwritten fails on a missing FILE and hides whatever the case meant
    # to assert. An empty collection is the honest stand-in for "this unit is not mapped here".
    for unit in set(mars_ice.NORTH_UNITS) | set(mars_ice.SOUTH_UNITS) | set(spans):
        path = tmp_path / f"{unit.lower()}.json"
        path.write_text(json.dumps(
            {"type": "FeatureCollection",
             "features": [polygon(low, high) for low, high in spans.get(unit, ())]}))
    monkeypatch.setattr(download_sim3292, "unit_path",
                        lambda unit: tmp_path / f"{unit.lower()}.json")


class TestTheBandIsDerivedFromTheUnitsAndNotFromALatitude:
    """Where the composite grades ice comes from the polygons, so a revised map moves it for free."""

    def test_a_span_is_taken_PER_HEMISPHERE(self, tmp_path, monkeypatch):
        """THE TRAP THIS ARGUMENT EXISTS FOR. `lApc` is mapped at BOTH poles, so one span over all
        its features runs pole to pole and describes a planet rather than an extent."""
        _units(tmp_path, monkeypatch, lApc=[(78.0, 85.0), (-85.0, -84.0)])
        assert mars_ice.unit_latitude_span("lApc", northern=True) == (78.0, 85.0)
        assert mars_ice.unit_latitude_span("lApc", northern=False) == (-85.0, -84.0)

    def test_a_unit_absent_from_a_hemisphere_answers_None_rather_than_zero(
            self, tmp_path, monkeypatch):
        """Zero would be the equator, which is the one answer that would widen a band to the whole
        grid. None is what lets `ice_bands` leave that hemisphere out entirely."""
        _units(tmp_path, monkeypatch, Apu=[(76.0, 80.0)])
        assert mars_ice.unit_latitude_span("Apu", northern=False) is None

    def test_both_poles_get_their_own_band_and_neither_reaches_the_equator(
            self, tmp_path, monkeypatch):
        """The whole point of the banded build: two narrow strips, not one grid.

        The equator assertion is the one that fails loudly if the hemispheric split above is lost —
        a single span over `lApc` would put row 0 through the last row in one band, which still
        renders correctly and costs a planet-sized warp to do it.
        """
        _units(tmp_path, monkeypatch,
               lApc=[(78.0, 85.0), (-85.0, -84.0)], Apu=[(76.0, 80.0)])
        height = 4096
        bands = mars_ice.ice_bands(WHOLE_MERCATOR, height, pad_rows=4)
        assert [northern for _row0, _row1, northern in bands] == [True, False]
        for row0, row1, northern in bands:
            latitudes = mercator.latitude_at(
                WHOLE_MERCATOR[3] - np.array([row0, row1]) * (2 * WHOLE_MERCATOR[3] / height),
                mercator.WEB_MERCATOR_RADIUS_M)
            assert min(abs(latitudes)) > 60.0, (
                f"the {'north' if northern else 'south'} band reaches {min(abs(latitudes)):.1f} "
                f"degrees — a hemisphere span has leaked across the equator")

    def test_the_pad_widens_the_band_on_both_sides(self, tmp_path, monkeypatch):
        """The feather reaches outside every polygon, so a band cut to the polygons alone would clip
        its own gradient at the band edge — a hard line parallel to no coastline."""
        _units(tmp_path, monkeypatch, lApc=[(78.0, 85.0)])
        narrow, = mars_ice.ice_bands(WHOLE_MERCATOR, 4096, pad_rows=0)
        padded, = mars_ice.ice_bands(WHOLE_MERCATOR, 4096, pad_rows=7)
        assert padded[0] == narrow[0] - 7 and padded[1] == narrow[1] + 7

    def test_a_grid_no_unit_reaches_yields_no_band_at_all(self, tmp_path, monkeypatch):
        """A body whose units sit off this grid builds nothing, rather than warping a planet to
        discover that every pixel is bare."""
        _units(tmp_path, monkeypatch, lApc=[(10.0, 12.0)])
        _left, _bottom, _right, top = WHOLE_MERCATOR
        polar_only = (_left, top * 0.95, _right, top)
        assert mars_ice.ice_bands(polar_only, 256, pad_rows=2) == []


class TestTheGradingFollowsTheHemisphere:
    def test_each_pole_is_graded_against_its_own_levels(self):
        """One pair applied to both poles would grade the south against the north's darker ground.

        Driven at each pole's own alpha-1 level, so the correct answer is 1.0 on both rows and a
        swapped pair cannot produce it: the levels differ by more than 30 DN at that end.
        """
        north_cap, south_cap = (mars_ice.ALPHA_LEVELS["north"][1],
                                mars_ice.ALPHA_LEVELS["south"][1])
        field = np.array([[north_cap, north_cap], [south_cap, south_cap]])
        northern = np.array([[True], [False]])
        graded = mars_ice.graded_alpha(field, northern, nodata=NODATA)
        assert graded == pytest.approx(np.ones((2, 2)))

    def test_a_scalar_hemisphere_grades_the_whole_slice(self):
        """A cap disc is all one hemisphere and passes a plain bool, the same broadcast `extent_for`
        already takes — so the two cannot disagree about which pole a pixel belongs to."""
        field = np.full((2, 2), mars_ice.ALPHA_LEVELS["south"][1])
        assert mars_ice.graded_alpha(field, False, NODATA) == pytest.approx(np.ones((2, 2)))
        assert mars_ice.graded_alpha(field, True, NODATA).max() < 1.0

    def test_the_fill_becomes_exactly_zero_in_both_hemispheres(self):
        """`albedo_alpha` masks before scaling; `np.where` must not reintroduce the other branch's
        answer over a pixel that was never measured."""
        field = np.full((2, 2), NODATA)
        for northern in (True, False):
            assert mars_ice.graded_alpha(field, northern, NODATA) == pytest.approx(np.zeros((2, 2)))
