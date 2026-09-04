"""Tests for the shadow-reach oracle, against geometry computable by hand.

MOST OF THIS FILE WENT WITH `shadow_mask`, AND WHAT IT COVERED IS WORTH NAMING so nobody reads the
survivor as the whole subject. Four classes tested the deleted numpy shadow renderer: the sun's
direction convention, an analytic wall's shadow length and penumbra, the levers that must actually
move it (altitude, exaggeration, per-row z-factor, reach truncation), and its output contract. All
of them drove `shadow_mask`, whose only caller was the compositor's hillshade, and none of them can
be repointed at anything: Cycles computes its own shadows and exposes no equivalent to assert on.

`TestTheDiscsWidthHasOneOwner` went too, and that one was half of a live law. The penumbra had to
read `palette.SUN_ANGULAR_DIAMETER_DEG` rather than hold a local copy, which is the 46-vs-45
altitude split's exact shape. The rig is the other reader and keeps its own guard and its own
mutation case, so the law survives with one arm.

What is left is the oracle `block_plan` actually calls. It is not a shading term: it sizes every
block's context ring, so an error in it narrows what Cycles can see, silently and with no edge.
"""

import math

import pytest

from pipeline.look.cast_shadow import shadow_reach_px

M_PER_PX = 305.7483   # the z8 grid, so the numbers here are production-scale
ZFACTOR = 15.0        # the locked hero exaggeration
WALL_HEIGHT = 2000.0  # casts ~98 px at a 45-degree sun


def oracle_shadow_px(altitude_deg: float, zfactor: float = ZFACTOR) -> float:
    """Ground distance, in pixels, at which the wall's horizon sits exactly at `altitude_deg`."""
    return zfactor * WALL_HEIGHT / math.tan(math.radians(altitude_deg)) / M_PER_PX


class TestTheSizingOracle:
    """The formula `block_plan` sizes every block's context from.

    Written against an independent transcription of the geometry rather than against the function's
    own arithmetic, so a sign or a reciprocal flipping in the source goes red here.
    """

    def test_default_reach_covers_the_production_case(self):
        """The tallest terrain the planet actually contains, so no block is silently narrowed."""
        everest_exaggerated = shadow_reach_px(8849.0, ZFACTOR, M_PER_PX, altitude=45.0)
        assert everest_exaggerated == pytest.approx(434.0, abs=1.0)
        assert shadow_reach_px(WALL_HEIGHT, ZFACTOR, M_PER_PX, 45.0) == pytest.approx(
            oracle_shadow_px(45.0), rel=1e-6)

    def test_a_lower_sun_throws_a_longer_shadow(self):
        """The direction, so the equality above cannot pass on a constant."""
        assert (shadow_reach_px(WALL_HEIGHT, ZFACTOR, M_PER_PX, altitude=30.0)
                > shadow_reach_px(WALL_HEIGHT, ZFACTOR, M_PER_PX, altitude=60.0))

    def test_exaggeration_scales_it_linearly(self):
        """`zfactor` is the term a second body corrects through, so it must not be inert here."""
        assert shadow_reach_px(WALL_HEIGHT, ZFACTOR * 2.0, M_PER_PX, 45.0) == pytest.approx(
            2.0 * shadow_reach_px(WALL_HEIGHT, ZFACTOR, M_PER_PX, 45.0), rel=1e-9)
