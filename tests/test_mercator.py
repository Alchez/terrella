"""The inverse Web-Mercator conversion, which existed twice before it existed once.

The since-deleted `look/hillshade.py` and `look/snow.py` each carried their own `EARTH_RADIUS` AND
their own transcription of `degrees(2*atan(exp(y/R)) - pi/2)`. Two copies of a constant is the drift
this project has been bitten by; two copies of the FORMULA is the same hazard with more surface, and
nothing related them. A second body makes it worse than drift — the radius is what turns a northing
into a latitude, and a wrong one produces a hillshade that is plausible at every latitude and correct
at none.

The radius is an explicit argument rather than a module constant, because that is the whole point:
the conversion is not about Earth, it is about whichever sphere the raster was projected on.
"""

import math

import numpy as np
import pytest

from pipeline import bodies, mercator


def test_the_equator_is_the_origin() -> None:
    assert mercator.latitude_at(0.0, bodies.EARTH.mercator_radius_m) == pytest.approx(0.0)


def test_it_inverts_the_forward_projection() -> None:
    """An independent oracle: the FORWARD transform, written here and nowhere in the source.

    Checking the inverse against another call to itself would agree however wrong it was.
    """
    radius = bodies.EARTH.mercator_radius_m
    for latitude in (-85.0, -45.0, -1.0, 0.0, 1.0, 45.0, 85.0):
        forward = radius * math.log(math.tan(math.pi / 4 + math.radians(latitude) / 2))
        assert mercator.latitude_at(forward, radius) == pytest.approx(latitude, abs=1e-9)


def test_it_is_vectorised_and_keeps_its_shape() -> None:
    """The callers hand it whole row arrays; a scalar-only version would be silently reshaped."""
    northings = np.array([[0.0, 1.0e6], [-1.0e6, 2.0e6]])
    out = mercator.latitude_at(northings, bodies.EARTH.mercator_radius_m)
    assert out.shape == northings.shape


def test_a_smaller_sphere_reads_the_same_northing_as_a_higher_latitude() -> None:
    """The radius is load-bearing, and this is what a wrong one costs.

    One northing is not one latitude — it is one latitude PER SPHERE. Mars's radius is ~53% of
    Earth's, so the identical metre value lands far nearer the pole. Nothing about the output looks
    wrong; it is simply a different planet's answer.

    The two figures are COMPUTED, not estimated — the first draft of this test carried eyeballed
    numbers and failed against correct code, which is the right way round for that mistake to land.
    """
    northing = 5.0e6
    on_earth = mercator.latitude_at(northing, 6378137.0)
    on_mars = mercator.latitude_at(northing, 3396190.0)
    # 23 degrees apart, from one number read against two spheres.
    assert on_mars > on_earth
    assert on_earth == pytest.approx(40.9163, abs=1e-3)
    assert on_mars == pytest.approx(64.1585, abs=1e-3)


def test_a_pixel_covers_less_ground_the_further_from_the_equator_it_sits() -> None:
    """The cos(latitude) half of `ground_metres_per_pixel`, against a hand-computed value.

    Written as a ratio at one latitude and an absolute at another, because a formula that dropped
    the cosine entirely still satisfies any ratio taken against itself.
    """
    at_equator = mercator.ground_metres_per_pixel(0.0, 305.7483, 1.0)
    assert at_equator == pytest.approx(305.7483)
    assert mercator.ground_metres_per_pixel(60.0, 305.7483, 1.0) == pytest.approx(
        305.7483 * 0.5, abs=1e-6), "cos(60) is exactly one half, so this needs no second formula"
    assert mercator.ground_metres_per_pixel(79.5, 305.7483, 1.0) == pytest.approx(55.7182,
                                                                                  abs=1e-3)


def test_the_body_term_is_a_separate_factor_and_is_1_0_on_earth_alone() -> None:
    """The half that is inert on the only planet anyone tests against, which is why it is pinned.

    A caller that dropped `ground_scale` would be exactly right on Earth and would undersize every
    Martian distance by 1.878 — the failure the `ground_width_m` docstring records having already
    happened once in this tree.
    """
    earth_scale = bodies.ground_metres_per_mercator_unit(bodies.EARTH)
    mars_scale = bodies.ground_metres_per_mercator_unit(bodies.get("mars"))
    assert earth_scale == 1.0, "if Earth's term stops being exactly 1.0 this test is the wrong shape"
    assert mars_scale != 1.0

    on_earth = mercator.ground_metres_per_pixel(45.0, 100.0, earth_scale)
    on_mars = mercator.ground_metres_per_pixel(45.0, 100.0, mars_scale)
    assert on_mars == pytest.approx(on_earth * mars_scale)


def test_it_takes_a_row_of_latitudes_and_keeps_the_shape() -> None:
    """Its Mercator caller hands a whole window's rows at once; its AEQD caller hands one scalar."""
    latitudes = np.linspace(0.0, 84.0, 7)
    out = mercator.ground_metres_per_pixel(latitudes, 305.7483, 1.0)
    assert out.shape == latitudes.shape
    assert np.all(np.diff(out) < 0.0), "ground metres per pixel must fall monotonically northward"
    assert np.ndim(mercator.ground_metres_per_pixel(0.0, 305.7483, 1.0)) == 0
