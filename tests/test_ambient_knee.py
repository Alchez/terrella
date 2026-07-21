"""The ambient floor: a hard clip that destroys information, and the soft knee that doesn't.

`shade.composite` has always landed its light with `np.clip(hs/flat, ambient, hi)`. That makes
`ambient` a CLIFF: measured 2026-07-20 on Iran, 18.07% of land sits below it carrying no hillshade
information at all, and a cast shadow pushed 6.21% more under — pixels whose control spread was
36 DN, all collapsed onto one value.

These tests pin the property the knee exists for — that terrain below the floor still VARIES —
and, in the same breath, that the hard clip provably does not. A test showing only that the knee
works would not establish there was ever a problem.
"""

import math

import numpy as np
import pytest

from pipeline.tile import shade
from pipeline.tile.shade import apply_ambient_floor

AMBIENT, HI = 0.50, 1.12


class TestHardClipIsThePreExistingBehaviour:

    def test_knee_zero_is_exactly_np_clip(self):
        raw = np.linspace(-0.5, 2.0, 501, dtype=np.float32)
        assert np.array_equal(apply_ambient_floor(raw, AMBIENT, HI, 0.0),
                              np.clip(raw, AMBIENT, HI))

    def test_the_clip_destroys_information_below_the_floor(self):
        """The defect itself, pinned. Distinct inputs must come out indistinguishable."""
        below = np.array([0.05, 0.20, 0.35, 0.49], dtype=np.float32)
        clipped = apply_ambient_floor(below, AMBIENT, HI, 0.0)
        assert below.std() > 0.15          # the input genuinely carried form...
        assert clipped.std() == 0.0        # ...and all of it is gone
        assert np.all(clipped == AMBIENT)


class TestSoftKneePreservesFormBelowTheFloor:

    @pytest.mark.parametrize("knee", [0.05, 0.15, 0.30])
    def test_below_floor_values_stay_distinct(self, knee: float):
        below = np.array([0.05, 0.20, 0.35, 0.49], dtype=np.float32)
        softened = apply_ambient_floor(below, AMBIENT, HI, knee)
        assert np.all(np.diff(softened) > 0)   # strictly ordered: form survives
        assert softened.std() > 0.0

    @pytest.mark.parametrize("knee", [0.05, 0.15, 0.30])
    def test_never_darkens_below_the_floor(self, knee: float):
        """Softplus is >= max(raw, ambient): the floor is respected, never undercut."""
        raw = np.linspace(-1.0, 2.0, 601, dtype=np.float32)
        softened = apply_ambient_floor(raw, AMBIENT, HI, knee)
        assert np.all(softened >= AMBIENT)
        assert np.all(softened <= HI)

    def test_open_ground_is_untouched(self):
        """The knee must be local to the floor, or it is just a global brightening."""
        raw = np.array([0.9, 1.0, 1.05], dtype=np.float32)
        softened = apply_ambient_floor(raw, AMBIENT, HI, 0.05)
        assert np.allclose(softened, raw, atol=1e-4)

    def test_smaller_knee_converges_on_the_hard_clip(self):
        """The knob is continuous with today's behaviour, not a separate mode."""
        raw = np.linspace(-0.5, 2.0, 501, dtype=np.float32)
        hard = apply_ambient_floor(raw, AMBIENT, HI, 0.0)
        errors = [float(np.abs(apply_ambient_floor(raw, AMBIENT, HI, k) - hard).max())
                  for k in (0.30, 0.15, 0.05, 0.01)]
        assert errors == sorted(errors, reverse=True)
        assert errors[-1] < 0.01

    def test_no_overflow_on_realistic_light(self):
        """logaddexp, not log1p(exp(x)): the naive form overflows over most of the planet."""
        raw = np.array([0.0, 1.0, 50.0, 500.0], dtype=np.float32)
        softened = apply_ambient_floor(raw, AMBIENT, HI, 0.05)
        assert np.all(np.isfinite(softened))


class TestFreshnessRecordsTheOcclusionResolution:
    """Folded in 2026-07-20: the occlusion resolution changes planet_rgb but reached no record."""

    def test_composite_params_records_the_occlusion_target(self):
        import json

        from pipeline.render.sky_view import OCCLUSION_TARGET_M_PER_PX
        from pipeline.tile.shade_planet import composite_params

        recorded = json.loads(composite_params({}))
        assert recorded["occlusion_target_m_per_px"] == OCCLUSION_TARGET_M_PER_PX

    def test_the_knee_reaches_the_composite_record(self):
        """`ambient_knee` is a composite knob, so it must NOT be filtered as hillshade-only."""
        import json

        from pipeline.tile.shade_planet import composite_params

        assert "ambient_knee" in json.loads(composite_params({}))["knobs"]


class TestTheTestOracleInvertsTheFloor:
    """`conftest.hillshade_for_light` is the analytic inverse the composite tests aim with.

    Added 2026-07-21 with the knee: those tests used to construct a known light as `flat * light`,
    which was exact only while the floor was `np.clip`. An oracle that is quietly wrong makes every
    assertion it feeds quietly wrong, so it gets its own round trip.
    """

    def test_round_trip_lands_on_the_requested_light(self):
        from conftest import hillshade_for_light

        flat = 255.0 * math.sin(math.radians(shade.KNOBS["alt"]))
        for light in [0.56, 0.75, 1.0, 1.035, 1.10]:
            raw = np.array([[hillshade_for_light(light) / flat]], dtype=np.float32)
            landed = apply_ambient_floor(raw, shade.KNOBS["ambient"], 10.0,
                                         shade.KNOBS["ambient_knee"])
            assert landed[0, 0] == pytest.approx(light, abs=1e-5)

    def test_it_refuses_lights_the_floor_cannot_produce(self):
        """The softplus is strictly above `ambient`, so asking for the floor itself is a bug in
        the asking test, not a value to silently approximate."""
        from conftest import hillshade_for_light

        with pytest.raises(ValueError, match="ambient floor"):
            hillshade_for_light(shade.KNOBS["ambient"])
