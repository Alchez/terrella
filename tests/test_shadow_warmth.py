"""The warm shadow floor: the one hero term our light model structurally could not express.

`light` is a single scalar multiplying an RGB ramp, so `base * light` preserves R/B exactly —
our shadows have always been the same hue as our sunlight, only darker. The hero's are not:
measured on the raw Cycles frame for Switzerland, inside narrow elevation bands so
the ramp colour is constant, linear R/B is **1.61–1.98x higher** in the darkest quartile than
the brightest, monotonic across all ten luminance deciles.

These tests pin the three properties that make the term safe to ship: it is bit-identical when
off, it moves hue WITHOUT moving brightness (which is what stops it re-creating the twice-rejected
wash), and it leaves sea and snow alone.
"""

import itertools
import math
from typing import Any, cast

import numpy as np
import pytest
from conftest import hillshade_for_light

from pipeline import bodies, planet_seam
from pipeline.render import palette
from pipeline.tile import shade
from pipeline.tile.shade import SHADOW_TINT, shadow_tint

#: A planet whose seam emitted all three rasters — what Earth declares, and the only
#: shape these tests care about unless they say otherwise.
WHOLE_PLANET = planet_seam.KNOWN_RASTERS

LUMINANCE = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


@pytest.fixture(autouse=True)
def restore_knobs():
    # Save/restore is wholesale and key-agnostic, so it takes the same untyped view of the Knobs
    # TypedDict that shade.py's --knob override and the variant loop do.
    knobs = cast(dict[str, Any], shade.KNOBS)
    original = dict(knobs)
    yield
    knobs.clear()
    knobs.update(original)


def composite_at(light_value, *, ocean=False, water=False, snow=0.0):
    """One land pixel at a known light, straight through the production composite."""
    shape = (1, 1)
    pre = ((light_value - shade.KNOBS["ambient"]) / shade.KNOBS["exposure"]
           + shade.KNOBS["ambient"])
    return shade.composite(np.full(shape, 1500.0, dtype="float32"),
                           np.full(shape, ocean, dtype=bool), np.full(shape, water, dtype=bool),
                           np.full(shape, snow, dtype="float32"),
                           np.full(shape, hillshade_for_light(pre), dtype="float32"),
                           np.zeros((1, 1), dtype="float32"), (1, 1), shape, look=palette.EARTH_LOOK)[:, 0, 0].astype(float)


class TestOffIsExactlyToday:
    def test_zero_returns_a_true_scalar_one(self):
        assert shadow_tint(np.linspace(0.5, 1.1, 7, dtype=np.float32), 0.0, 0.5) == 1.0

    def test_zero_is_bit_identical_through_the_composite(self):
        shade.KNOBS["shadow_warmth"] = 0.0
        before = composite_at(0.62)
        shade.KNOBS["shadow_warmth"] = 0.8
        assert not np.array_equal(before, composite_at(0.62)), "the companion: 0.8 must differ"
        shade.KNOBS["shadow_warmth"] = 0.0
        assert np.array_equal(before, composite_at(0.62))


class TestItMovesHueNotBrightness:
    """The design property. A term that also brightened would be the rejected `ambient` raise
    wearing a different hat, and no A/B could tell the two effects apart."""

    def test_the_tint_constant_has_luminance_one(self):
        assert float(np.dot(LUMINANCE, SHADOW_TINT)) == pytest.approx(1.0, abs=1e-5)

    def test_it_reproduces_the_measured_hero_ratio_at_full_strength(self):
        """1.0 means "as warm as the hero measured", not "as warm as looks nice"."""
        assert SHADOW_TINT[0] / SHADOW_TINT[2] == pytest.approx(1.80, abs=0.01)

    def test_shadowed_land_gets_warmer(self):
        shade.KNOBS["shadow_warmth"] = 0.0
        cold = composite_at(0.60)
        shade.KNOBS["shadow_warmth"] = 1.0
        warm = composite_at(0.60)
        assert warm[0] / warm[2] > cold[0] / cold[2]

    def test_shadowed_land_keeps_its_brightness(self):
        shade.KNOBS["shadow_warmth"] = 0.0
        cold = composite_at(0.60)
        shade.KNOBS["shadow_warmth"] = 1.0
        warm = composite_at(0.60)
        assert float(np.dot(LUMINANCE, warm)) == pytest.approx(float(np.dot(LUMINANCE, cold)),
                                                               rel=0.02)

    def test_fully_lit_land_is_untouched(self):
        """`shadowness` is 0 at light 1.0, so flat ground must not move at all -- otherwise this
        is a global tint (which `KNOBS["warmth"]` already is) rather than a shadow term."""
        shade.KNOBS["shadow_warmth"] = 0.0
        cold = composite_at(1.0)
        shade.KNOBS["shadow_warmth"] = 1.0
        assert np.array_equal(cold, composite_at(1.0))

    def test_the_effect_grows_as_light_falls(self):
        shade.KNOBS["shadow_warmth"] = 1.0
        ratios = [composite_at(value)[0] / composite_at(value)[2]
                  for value in (0.95, 0.85, 0.75, 0.65, 0.56)]
        assert all(later > earlier for earlier, later in itertools.pairwise(ratios)), ratios


class TestItLeavesTheOtherSurfacesAlone:
    def test_ocean_is_untouched(self):
        shade.KNOBS["shadow_warmth"] = 0.0
        cold = composite_at(0.60, ocean=True)
        shade.KNOBS["shadow_warmth"] = 1.0
        assert np.array_equal(cold, composite_at(0.60, ocean=True))

    def test_inland_water_is_untouched(self):
        shade.KNOBS["shadow_warmth"] = 0.0
        cold = composite_at(0.60, water=True)
        shade.KNOBS["shadow_warmth"] = 1.0
        assert np.array_equal(cold, composite_at(0.60, water=True))

    def test_full_snow_keeps_its_blue_shadow(self):
        """Snow shadow is deliberately BLUE-white (`SNOW_SHADOW_RGB`, chosen) — warming
        it would overturn a decision made on its own evidence."""
        shade.KNOBS["shadow_warmth"] = 1.0
        assert tuple(int(band) for band in composite_at(0.56, snow=1.0)) \
            == palette.SNOW_SHADOW_RGB


class TestFreshness:
    def test_it_reaches_the_composite_record(self):
        import json

        from pipeline.tile.shade_planet import composite_params

        assert "shadow_warmth" in json.loads(composite_params({}, bodies.EARTH, WHOLE_PLANET))["knobs"]

    def test_it_is_not_hillshade_only(self):
        """It is consumed by composite(), so a re-tune must restage the composite (~19.6 min),
        not the 11:48 hillshade that cannot see it."""
        from pipeline.tile.shade_planet import HILLSHADE_ONLY_KNOBS, hs_params

        assert "shadow_warmth" not in HILLSHADE_ONLY_KNOBS
        assert "shadow_warmth" not in math.__name__ + str(hs_params(bodies.EARTH))
