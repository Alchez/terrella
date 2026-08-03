#!/usr/bin/env python3
"""`snow_curve` — the snow ramp's legibility dial, and the proof that promoting it tracks freshness.

Over full snow `base_rgb` is multiplied by (1 - alpha) = 0, so `snow_t` is the ONLY channel relief
has. That makes this knob unusually load-bearing: it is the whole contrast budget for every ice
sheet on the planet. Each claim here is paired with a companion that proves the check can fail.
"""
import json
from typing import Any, cast

import numpy as np
import pytest

from conftest import hillshade_for_light

from pipeline import bodies
from pipeline.render import palette
from pipeline.tile import shade
from pipeline.tile import shade_planet

CURVES = ["linear", "gamma4", "gamma8", "knee"]


@pytest.fixture(autouse=True)
def restore_knobs():
    """KNOBS is module-level mutable state; a test that sets it and walks away silently re-tunes
    every test that runs after it. Restore, or the suite's result depends on collection order."""
    saved = dict(shade.KNOBS)
    yield
    # same untyped view of KNOBS that shade_planet's variant loop and shade.py's --knob take
    cast(dict[str, Any], shade.KNOBS).update(saved)


def _light_grid():
    """Light spanning the whole reachable range: the ambient floor -> above snow_hi_pt."""
    return np.linspace(shade.KNOBS["ambient"], 1.16, 401).astype(np.float32)


def _inline_snow_t(light):
    """The expression composite() used before snow_position existed, retained as the oracle."""
    return np.clip((light - shade.KNOBS["snow_lo"])
                   / (shade.KNOBS["snow_hi_pt"] - shade.KNOBS["snow_lo"]), 0.0, 1.0)


class TestTheChosenDefault:
    def test_the_shipped_curve_is_gamma8(self):
        """Chosen off a rendered four-curve A/B. If this changes, the planet's ice
        changed, and planet_rgb must rebuild -- which the freshness tests below pin."""
        assert shade.KNOBS["snow_curve"] == "gamma8"

    def test_the_window_was_NOT_moved(self):
        """The curve is the lever; the window is not. A window narrow enough for Greenland is a
        threshold for the Alps -- measured, and the reason gamma8 exists at all."""
        assert (shade.KNOBS["snow_lo"], shade.KNOBS["snow_hi_pt"]) == (0.55, 1.05)


class TestLinearIsStillBitIdenticalToThePreRefactorExpression:
    def test_linear_matches_the_old_inline_oracle_exactly(self):
        light = _light_grid()
        assert np.array_equal(shade.snow_position(light, "linear"), _inline_snow_t(light))

    def test_the_oracle_can_disagree(self):
        """Companion: if every curve matched the oracle, the test above would prove nothing."""
        light = _light_grid()
        assert not np.array_equal(shade.snow_position(light, "gamma8"), _inline_snow_t(light))


class TestEveryCurveIsAWellFormedRamp:
    @pytest.mark.parametrize("curve", CURVES)
    def test_endpoints_are_pinned(self, curve):
        """A curve redistributes the ramp; it must not move its ends, or snow changes colour
        where the terrain did not change at all."""
        below = np.array([shade.KNOBS["snow_lo"] - 0.1], dtype=np.float32)
        above = np.array([shade.KNOBS["snow_hi_pt"] + 0.1], dtype=np.float32)
        assert shade.snow_position(below, curve)[0] == pytest.approx(0.0)
        assert shade.snow_position(above, curve)[0] == pytest.approx(1.0)

    @pytest.mark.parametrize("curve", CURVES)
    def test_monotone_non_decreasing(self, curve):
        """Brighter light must never render darker snow."""
        assert np.all(np.diff(shade.snow_position(_light_grid(), curve)) >= -1e-7)

    @pytest.mark.parametrize("curve", CURVES)
    def test_stays_inside_the_ramp(self, curve):
        values = shade.snow_position(_light_grid(), curve)
        assert values.min() >= 0.0 and values.max() <= 1.0

    def test_an_unknown_curve_fails_loudly(self):
        with pytest.raises(ValueError, match="unknown snow_curve"):
            shade.snow_position(_light_grid(), "gamma9")


class TestTheCurveDoesItsJob:
    """Greenland's measured band is light 1.017-1.052; rugged snow spans 0.50-1.11."""

    GREENLAND = np.array([1.017, 1.052], dtype=np.float32)
    ALPINE_MIDTONE = np.array([0.70, 0.90], dtype=np.float32)

    @pytest.mark.parametrize("curve", ["gamma4", "gamma8", "knee"])
    def test_every_candidate_widens_greenlands_band(self, curve):
        linear = float(np.diff(shade.snow_position(self.GREENLAND, "linear"))[0])
        assert float(np.diff(shade.snow_position(self.GREENLAND, curve))[0]) > linear

    def test_linear_hands_greenland_almost_none_of_the_ramp(self):
        """Companion: the control must FAIL the test its alternatives pass -- linear is why the
        interior is blank. The span is 0.066, not 0.035/0.50 = 0.070, because Greenland's p99
        light (1.052) sits ABOVE snow_hi_pt (1.05) and its top is already saturated to pure white.
        That clip is the measured 2.4% at Summit, not an artefact of this test."""
        assert float(np.diff(shade.snow_position(self.GREENLAND, "linear"))[0]) == pytest.approx(
            0.066, abs=1e-3)
        assert float(shade.snow_position(self.GREENLAND, "linear")[1]) == pytest.approx(1.0)

    @pytest.mark.parametrize("curve", ["gamma4", "gamma8", "knee"])
    def test_the_gain_is_paid_for_by_rugged_midtones(self, curve):
        """There is no free lunch in the arithmetic: the ramp is a fixed 43.9 DN budget, so
        widening Greenland's band MUST narrow something else. Pinned so nobody later claims the
        curve is free -- what makes it cheap is that rugged snow barely occupies this band, which
        is a fact about the terrain, not about the curve."""
        linear = float(np.diff(shade.snow_position(self.ALPINE_MIDTONE, "linear"))[0])
        assert float(np.diff(shade.snow_position(self.ALPINE_MIDTONE, curve))[0]) < linear


class TestFreshness:
    """The guard is blind to CODE by design, so a tunable that misses composite_params leaves
    planet_rgb falsely fresh. That is exactly how WATER_RGB drifted and what the guard
    exists to prevent."""

    def test_snow_curve_is_recorded_in_composite_params(self):
        params = json.loads(shade_planet.composite_params({}, bodies.EARTH))
        assert params["knobs"]["snow_curve"] == "gamma8"

    def test_changing_it_changes_the_params(self):
        """Companion: proves the assertion above is load-bearing rather than reading a constant."""
        before = shade_planet.composite_params({}, bodies.EARTH)
        shade.KNOBS["snow_curve"] = "linear"
        assert shade_planet.composite_params({}, bodies.EARTH) != before

    def test_snow_curve_is_NOT_hillshade_only(self):
        """It is consumed by composite(), not by the hillshade -- so it must NOT be filtered out.
        Being wrong here is silent: the composite would never restage on a re-tune."""
        assert "snow_curve" not in shade_planet.HILLSHADE_ONLY_KNOBS

    def test_it_does_not_reach_the_hillshade_params(self):
        """The other half: a composite knob must not restage an 11:48 hillshade that cannot see
        it. hs_params carries the sun geometry and fill only."""
        assert "snow_curve" not in json.dumps(shade_planet.hs_params(bodies.EARTH))


class TestCompositeHonoursTheKnob:
    def _composite(self, light_value):
        # Invert the land light chain -- exposure first, then the ambient floor -- so the pixel
        # lands on exactly `light_value`. The floor step is not optional: under the shipped
        # `ambient_knee` it lifts 1.035 clean out of the snow window, which reads as the curve
        # knob having stopped working when in fact the input was never in range.
        pre = ((light_value - shade.KNOBS["ambient"]) / shade.KNOBS["exposure"]
               + shade.KNOBS["ambient"])
        return self._composite_from_hillshade(hillshade_for_light(pre))

    def _composite_from_hillshade(self, hillshade_dn):
        """The same pixel, addressed by its raw hillshade DN rather than by the light it lands on.

        Needed for the darkest end: since the ambient floor became a softplus there is no DN that
        produces a light AT the floor, so a test aiming there has to come in from this side.
        """
        shape = (1, 1)
        return shade.composite(np.full(shape, 1500.0, dtype="float32"),
                               np.zeros(shape, dtype=bool), np.zeros(shape, dtype=bool),
                               np.ones(shape, dtype="float32"),
                               np.full(shape, hillshade_dn, dtype="float32"),
                               np.zeros((1, 1), dtype="float32"), (1, 1), shape)

    def test_the_knob_reaches_the_pixel(self):
        """Greenland's median light must render differently under linear than under the shipped
        gamma8 -- otherwise composite() is ignoring KNOBS and the A/B was theatre."""
        under_gamma8 = self._composite(1.035)
        shade.KNOBS["snow_curve"] = "linear"
        assert not np.array_equal(under_gamma8, self._composite(1.035))

    def test_gamma8_renders_greenlands_median_darker_than_linear(self):
        """Direction, not just difference: gamma8 pulls sub-peak light DOWN the ramp, which is
        what buys the gradient. A curve that brightened it would also 'differ'."""
        under_gamma8 = int(self._composite(1.035).sum())
        shade.KNOBS["snow_curve"] = "linear"
        assert under_gamma8 < int(self._composite(1.035).sum())

    def test_full_snow_ignores_the_hillshade_except_through_snow_t(self):
        """The mechanism itself: at alpha=1 the output is snow_shadow->snow_lit and nothing else,
        so the darkest fully-snow pixel IS snow_shadow exactly, under every curve.

        Addressed by the darkest hillshade DN rather than by a light below `snow_lo`, which the
        softplus floor no longer lets a test ask for -- see below.
        """
        rgb = self._composite_from_hillshade(0.0)
        assert tuple(int(band) for band in rgb[:, 0, 0]) == palette.SNOW_SHADOW_RGB

    def test_the_knee_does_not_lift_snow_off_its_bottom_stop(self):
        """`ambient_knee` 0.30 made the floor asymptotic, so the darkest land light (0.5519, or
        0.5545 after exposure) now sits ABOVE `snow_lo` and the ramp's bottom stop is no longer
        addressable by light. The pixel is unmoved anyway, and the margin is why: 0.9% up the
        ramp linearly = 0.50/0.38/0.24 DN, and the shipped gamma8 takes 0.009**8 to zero outright.

        Pinned because it is a floor with no headroom, not a comfortable one: this is the test
        that fails if a future knee raise starts bleaching shaded snow.
        """
        darkest_light = float(shade.apply_ambient_floor(np.zeros((1, 1), dtype="float32"),
                                                        shade.KNOBS["ambient"], shade.KNOBS["hi"],
                                                        shade.KNOBS["ambient_knee"])[0, 0])
        assert darkest_light > shade.KNOBS["snow_lo"], "the light itself is unreachable"
        for curve in CURVES:
            shade.KNOBS["snow_curve"] = curve
            assert tuple(int(band) for band in self._composite_from_hillshade(0.0)[:, 0, 0]) \
                == palette.SNOW_SHADOW_RGB, f"{curve} lifted shaded snow off its stop"

    def test_a_bigger_knee_would_lift_it(self):
        """Companion: proves the guard above tracks the knee rather than reading a constant."""
        shade.KNOBS["ambient_knee"] = 2.0
        shade.KNOBS["snow_curve"] = "linear"
        assert tuple(int(band) for band in self._composite_from_hillshade(0.0)[:, 0, 0]) \
            != palette.SNOW_SHADOW_RGB
