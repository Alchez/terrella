"""`snow.soften_source_cells` — the softening that stops the ice edge reading as a staircase.

The artefact it exists for is geometric, not tonal: NSIDC-0791 is a 0.01 degree grid, so one source
cell is a fixed 1113.2 m tall at every latitude while the render grid's pixel shrinks with
cos(latitude). The cell is therefore 3.6 render px tall at the equator and 20 at 79.5N, and only the
tall one shows as steps. Every claim here is paired with a companion that proves the check can fail,
because a blur is the kind of operation whose tests pass whether or not it ran.

The resolutions below are Earth's real z8 planet grid, not a fixture's convenience. A blur test
written at a fixture's 125 km/px would find sigma near zero and pass against a feather that was
never wired up, which is the shape this suite has been bitten by before.
"""

import itertools

import numpy as np
import pytest
from scipy import ndimage

from pipeline import bodies, layers, mercator
from pipeline.look import layer_producers, perennial_ice, snow

#: Earth's z8 planet grid, the one every shipped tile and every raytraced block is cut from.
EARTH = bodies.get("earth")
GROUND_SCALE = bodies.ground_metres_per_mercator_unit(EARTH)

#: Latitudes worth naming: the equator where the cell is square, 49N where the staircase is first
#: measurable, and 79.5N where it was first spotted on the live globe.
EQUATOR, MID, POLAR = 0.0, 49.0, 79.5


def ground_metres_per_px(latitude_deg):
    """Earth's z8 ground resolution at a latitude, scalar or array."""
    return mercator.ground_metres_per_pixel(latitude_deg, EARTH.map_units_per_pixel, GROUND_SCALE)


def polar_window(rows, cols=64, latitude=POLAR):
    """A synthetic alpha with one vertical edge, on the real grid's per-row resolution."""
    alpha = np.zeros((rows, cols), dtype=float)
    alpha[:, cols // 2:] = 1.0
    return alpha, ground_metres_per_px(np.full(rows, latitude))


class TestTheSigmaIsTheSourceCellAndNotAPixelCount:
    """The whole design claim: the blur scales with the artefact. If sigma were a constant pixel
    count it would over-blur the equator or under-blur the pole, and nothing else here would say
    which."""

    def test_sigma_rises_with_latitude_exactly_as_one_over_cosine(self):
        equator = snow.source_cell_sigma_px(ground_metres_per_px(EQUATOR))
        for latitude in (MID, POLAR, 84.0):
            expected = equator / np.cos(np.radians(latitude))
            got = snow.source_cell_sigma_px(ground_metres_per_px(latitude))
            assert got == pytest.approx(expected, rel=1e-12), (
                f"sigma at {latitude}N is {got:.3f} px, not the {expected:.3f} px that one source "
                f"cell subtends there")

    def test_the_equator_value_is_the_cell_over_the_pixel(self):
        """An independent oracle for the one latitude where the arithmetic has no cosine in it, so
        a sign or a reciprocal error in the general formula cannot hide behind a ratio test."""
        assert snow.source_cell_sigma_px(ground_metres_per_px(EQUATOR)) == pytest.approx(
            snow.SOFTEN_FRACTION * snow.SOURCE_CELL_M / EARTH.map_units_per_pixel)

    def test_the_polar_sigma_is_several_pixels_and_the_equatorial_one_is_about_one(self):
        """The magnitudes the whole design rests on, pinned so a unit slip in the cell constant is
        visible as an absurd number rather than as a ratio that still holds."""
        assert 1.0 < snow.source_cell_sigma_px(ground_metres_per_px(EQUATOR)) < 1.5
        assert 6.0 < snow.source_cell_sigma_px(ground_metres_per_px(POLAR)) < 8.0


class TestItActuallySoftensAndTheTestCouldSayOtherwise:

    def test_a_polar_edge_gains_a_gradient(self):
        alpha, resolution = polar_window(64)
        softened = snow.soften_source_cells(alpha, resolution)
        assert (softened != alpha).any(), "the feather returned its input unchanged"
        # A hard step has exactly one row-position where the value is strictly between 0 and 1
        # (none, in fact); a softened one has several columns of partial coverage per row.
        partial = ((softened > 0.01) & (softened < 0.99)).sum(axis=1)
        assert partial.min() >= 8, (
            f"only {partial.min()} columns of transition at {POLAR}N — a sigma near 7 px should "
            f"spread the edge across roughly six sigma")

    def test_the_same_edge_on_a_coarse_grid_is_left_alone(self):
        """The companion. At a resolution where one source cell is well under a pixel there is no
        staircase to remove, and a feather that fired anyway would be blurring real data."""
        alpha = np.zeros((64, 64), dtype=float)
        alpha[:, 32:] = 1.0
        coarse = np.full(64, 125_000.0)  # a fixture-scale grid, ~400x Earth's z8
        softened = snow.soften_source_cells(alpha, coarse)
        assert np.abs(softened - alpha).max() < 1e-6, (
            "the feather moved pixels on a grid whose source cell is sub-pixel")

    def test_it_softens_without_moving_the_edge(self):
        """A blur must not shift the coastline of the ice. Symmetric kernel on a symmetric step, so
        the half-coverage column stays where it was."""
        alpha, resolution = polar_window(64)
        softened = snow.soften_source_cells(alpha, resolution)
        crossing = np.argmax(softened >= 0.5, axis=1)
        assert (crossing == 32).all(), f"the 0.5 crossing moved to {set(crossing.tolist())}"


class TestTheBandedPathIsTheWholeArrayFilter:
    """Per-row sigma has no single call in `ndimage`, so `feather` bands the array. That is an
    implementation choice, and it owes proof that it changed no answer."""

    def test_a_constant_resolution_matches_one_filter_call(self):
        alpha, resolution = polar_window(200)
        expected = ndimage.gaussian_filter(
            alpha, sigma=float(snow.source_cell_sigma_px(resolution[0])), mode="nearest")
        assert np.abs(snow.soften_source_cells(alpha, resolution) - expected).max() < 1e-9

    def test_a_varying_resolution_matches_a_per_row_reference(self):
        """The brute-force oracle: filter the WHOLE array at row r's sigma and keep row r. Far too
        slow to ship and exactly right, which is what an oracle is for."""
        rows = 256
        rng = np.random.default_rng(20260822)
        alpha = rng.random((rows, 48))
        latitude = np.linspace(60.0, 84.0, rows)
        resolution = ground_metres_per_px(latitude)
        sigma = snow.source_cell_sigma_px(resolution)

        reference = np.empty_like(alpha)
        for row in range(rows):
            reference[row] = ndimage.gaussian_filter(
                alpha, sigma=float(sigma[row]), mode="nearest")[row]

        got = snow.soften_source_cells(alpha, resolution)
        # The band tolerance is on SIGMA; the error it admits in the output is smaller still,
        # because a Gaussian's response to a 2% change in sigma is far under 2% of its amplitude.
        assert np.abs(got - reference).max() < snow.SOFTEN_BAND_TOLERANCE

    def test_the_reference_can_disagree(self):
        """A comparison that cannot fail proves nothing. Same call with the sigma law inverted, so
        the pole gets the equator's blur, must miss the reference by far more than the tolerance."""
        rows = 256
        rng = np.random.default_rng(20260822)
        alpha = rng.random((rows, 48))
        latitude = np.linspace(60.0, 84.0, rows)
        sigma = snow.source_cell_sigma_px(ground_metres_per_px(latitude))

        reference = np.empty_like(alpha)
        for row in range(rows):
            reference[row] = ndimage.gaussian_filter(
                alpha, sigma=float(sigma[row]), mode="nearest")[row]

        wrong = snow.soften_source_cells(alpha, ground_metres_per_px(latitude[::-1]))
        assert np.abs(wrong - reference).max() > snow.SOFTEN_BAND_TOLERANCE

    def test_no_band_is_wider_in_sigma_than_the_tolerance_allows(self):
        """What the banding promises: the step between neighbouring rows' effective sigma is under
        `SOFTEN_BAND_TOLERANCE`, so the ladder of steps has no rung big enough to draw a line."""
        latitude = np.linspace(0.0, 84.0, 4096)
        sigma = snow.source_cell_sigma_px(ground_metres_per_px(latitude))
        for start, end in snow._bands(sigma):
            band = sigma[start:end]
            assert np.abs(band - band[0]).max() <= snow.SOFTEN_BAND_TOLERANCE * band[0]

    def test_the_bands_cover_every_row_exactly_once(self):
        latitude = np.linspace(0.0, 84.0, 4096)
        bands = snow._bands(snow.source_cell_sigma_px(ground_metres_per_px(latitude)))
        assert bands[0][0] == 0 and bands[-1][1] == latitude.size
        assert all(previous[1] == following[0]
                   for previous, following in itertools.pairwise(bands))

    def test_a_uniform_grid_needs_one_band(self):
        """The degenerate case, which is also the AEQD cap's: nothing varies, so nothing is banded
        and the halo work is not paid for."""
        assert snow._bands(np.full(4096, 7.0)) == [(0, 4096)]


class TestBothProducersFeatherOrTheCrossfadeShowsTheSeam:
    """The tiles and the north cap paint the same ice from the same dataset and meet across the
    80..84 crossfade. Softening one side only would swap one visible discontinuity for another,
    which is why this asserts on both rather than on the module in isolation."""

    def _polar_tile_window(self, rows=64, cols=64):
        top = float(mercator.northing_at(80.5, mercator.WEB_MERCATOR_RADIUS_M))
        bottom = float(mercator.northing_at(79.5, mercator.WEB_MERCATOR_RADIUS_M))
        latitude = snow.latitude_per_row(top, bottom, rows)
        packed = np.zeros((rows, cols), dtype="float32")
        packed[:, cols // 2:] = 10_000.0  # full persistence on half the window
        return packed, layer_producers.LayerWindow(
            raw=packed, watercode=None, land=np.ones((rows, cols), dtype=bool),
            ocean=np.zeros((rows, cols), dtype=bool), latitude=latitude,
            ground_metres_per_px=mercator.ground_metres_per_pixel(
                latitude, EARTH.map_units_per_pixel, GROUND_SCALE),
            top=top, bottom=bottom)

    def test_the_tile_producer_feathers(self):
        packed, window = self._polar_tile_window()
        unfeathered = snow.snow_alpha(snow.unpack_persistence(packed), window.top, window.bottom)
        got = layer_producers.producer_for(EARTH, layers.PERENNIAL_ICE).contribution(window)
        assert got is not None
        assert np.abs(got - unfeathered).max() > 0.1, (
            "the perennial-ice producer returned the raw ramp — the feather is not wired into it")

    def test_the_cap_producer_feathers(self):
        """The AEQD side, driven through the same scalar branch the cap renderer uses."""
        rows = cols = 64
        packed = np.zeros((rows, cols), dtype="float32")
        packed[:, cols // 2:] = 10_000.0
        cap_resolution = float(ground_metres_per_px(POLAR))

        def warp(source: str, name: str, resampling: str, dtype: str,
                 srcnodata: "float | None" = None) -> np.ndarray:
            """`WarpToCap`'s shape, parameter names included — pyright checks those by name."""
            del source, name, resampling, dtype, srcnodata
            return packed

        inputs = perennial_ice.CapIceInputs(
            land=np.ones((rows, cols), dtype=bool),
            latitude=np.full((rows, cols), 85.0),
            warp=warp, burn=lambda *a, **k: np.zeros((rows, cols)),
            # The NORTH producer, which has no outcrop to subtract and never asks for one.
            ground_metres_per_px=cap_resolution)

        persistence = snow.unpack_persistence(packed)
        low = snow.RAMP_LOW_MAX
        fraction = np.clip((persistence - low) / snow.RAMP_BAND, 0.0, 1.0)
        unfeathered = fraction * fraction * (3.0 - 2.0 * fraction)

        got = perennial_ice.cap_ice(EARTH, "north").alpha(inputs)
        assert np.abs(got - unfeathered).max() > 0.1, (
            "the north cap returned the raw ramp — the crossfade would meet a feathered tile with "
            "an unfeathered cap")

    def test_both_sides_use_the_same_sigma_at_the_same_latitude(self):
        """One home for the number, reached by two different grid descriptions. The tile side hands
        a per-row array and the cap side a scalar; at the same ground resolution they must agree."""
        resolution = float(ground_metres_per_px(POLAR))
        per_row = snow.source_cell_sigma_px(np.full(4, resolution))
        assert per_row == pytest.approx(snow.source_cell_sigma_px(resolution))


class TestTheAntarcticPatchIsNotFeathered:
    """It is a land-and-latitude rule, not a source raster, so it has no cell edge to soften — and
    blurring it would bleed white off the coastline into the sea, which is a different defect
    entirely (and one the sea-ice gate exists to prevent on the other side)."""

    def test_a_southern_window_with_no_persistence_keeps_a_hard_coast(self):
        rows = cols = 64
        top = float(mercator.northing_at(-70.0, mercator.WEB_MERCATOR_RADIUS_M))
        bottom = float(mercator.northing_at(-71.0, mercator.WEB_MERCATOR_RADIUS_M))
        latitude = snow.latitude_per_row(top, bottom, rows)
        land = np.zeros((rows, cols), dtype=bool)
        land[:, cols // 2:] = True
        window = layer_producers.LayerWindow(
            raw=None, watercode=None, land=land, ocean=~land, latitude=latitude,
            ground_metres_per_px=mercator.ground_metres_per_pixel(
                latitude, EARTH.map_units_per_pixel, GROUND_SCALE),
            top=top, bottom=bottom)
        got = layer_producers.producer_for(EARTH, layers.PERENNIAL_ICE).contribution(window)
        assert got is not None
        assert set(np.unique(got).tolist()) == {0.0, 1.0}, (
            "the Antarctic patch picked up intermediate values — it has been blurred")
