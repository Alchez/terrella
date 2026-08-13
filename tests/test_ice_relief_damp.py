"""`ice_relief_damp`: thick sea ice conceals the seafloor's SHADING, never its COLOUR.

The ice whites are light-keyed by `snow_t`, whose light over ocean is the seafloor's
hillshade — so before this knob, the perennial pack painted the floor's ridges into the
ice at full strength and read as terrain above the sea (seen at the north pole).
The damp pulls the ice's light-key toward its flat-ocean value in proportion to
`damp * ice_alpha`.

These tests pin the properties that make the term safe to ship: bit-identical when off,
proportional to ice cover (the marginal fringe keeps its relief — the design point that
separates this from a global contrast cut), fully concealing at the damp=1/alpha=1 corner,
and invisible to every non-ice surface. The colour glow-through (`1 - alpha` of shaded sea)
is a different channel and is asserted to survive.
"""

from typing import Any, cast

import numpy as np
import pytest
from conftest import hillshade_for_light

from pipeline import bodies, planet_seam
from pipeline.render import palette, seaice
from pipeline.tile import shade

#: A planet whose seam emitted all three rasters — what Earth declares, and the only
#: shape these tests care about unless they say otherwise.
WHOLE_PLANET = planet_seam.KNOWN_RASTERS


@pytest.fixture(autouse=True)
def restore_knobs():
    # Save/restore is wholesale and key-agnostic, same untyped view as shade.py's --knob loop.
    knobs = cast(dict[str, Any], shade.KNOBS)
    original = dict(knobs)
    yield
    knobs.clear()
    knobs.update(original)


def composite_pixel(light_value, *, ocean=True, water=False, snow=0.0, ice=0.0,
                    height=-3000.0):
    """One pixel through the production composite, `light_value` being the pre-sea-transform
    light (what `apply_ambient_floor` emits); ocean pixels then take sea_lift/sea_shade."""
    shape = (1, 1)
    return shade.composite(np.full(shape, height, dtype="float32"),
                           np.full(shape, ocean, dtype=bool), np.full(shape, water, dtype=bool),
                           np.full(shape, snow, dtype="float32"),
                           np.full(shape, hillshade_for_light(light_value), dtype="float32"),
                           np.zeros(shape, dtype="float32"), shape, shape,
                           ice_a=np.full(shape, ice, dtype="float32"), look=palette.EARTH_LOOK,
                           snow_paint=(palette.SNOW_RGB, palette.SNOW_SHADOW_RGB), ice_paint=seaice.ice_white())[:, 0, 0].astype(float)


def relief_spread(damp, ice):
    """How far an icy pixel's colour travels across the seafloor's light range."""
    shade.KNOBS["ice_relief_damp"] = damp
    sunny = composite_pixel(1.05, ice=ice)
    shadowed = composite_pixel(0.60, ice=ice)
    return float(np.max(np.abs(sunny - shadowed)))


class TestOffIsExactlyToday:
    def test_zero_is_bit_identical_through_the_composite(self):
        shade.KNOBS["ice_relief_damp"] = 0.0
        before = composite_pixel(0.60, ice=0.85)
        shade.KNOBS["ice_relief_damp"] = 1.0
        assert not np.array_equal(before, composite_pixel(0.60, ice=0.85)), \
            "the companion: 1.0 must differ"
        shade.KNOBS["ice_relief_damp"] = 0.0
        assert np.array_equal(before, composite_pixel(0.60, ice=0.85))


class TestItConcealsShadingProportionally:
    def test_full_damp_full_alpha_erases_the_floor_relief(self):
        """The corner case that defines the knob: at damp=1, alpha=1 the light-key IS the
        flat-ocean key, so two icy pixels over any two seafloor slopes render identically."""
        shade.KNOBS["ice_relief_damp"] = 1.0
        assert np.array_equal(composite_pixel(1.05, ice=1.0), composite_pixel(0.60, ice=1.0))

    def test_at_the_production_alpha_relief_shrinks_but_survives(self):
        """ICE_MAX_ALPHA is 0.85, so 15% of the shaded sea still carries the floor — damping
        must reduce the pack's relief, not sterilise it (the pole-taper disc lesson)."""
        undamped = relief_spread(0.0, ice=0.85)
        damped = relief_spread(1.0, ice=0.85)
        assert 0.0 < damped < undamped

    def test_the_marginal_fringe_keeps_more_relief_than_the_pack(self):
        """The design point: damping scales with ice cover, so thin edge ice stays textured
        while thick pack calms. A global contrast cut (option D) would fail this."""
        pack_change = relief_spread(0.0, ice=0.85) - relief_spread(1.0, ice=0.85)
        fringe_change = relief_spread(0.0, ice=0.30) - relief_spread(1.0, ice=0.30)
        assert pack_change > fringe_change > 0.0

    def test_the_colour_glow_through_survives_full_damp(self):
        """The other channel: a shallow shelf and a deep basin under identical full-damp pack
        must still differ — depth reads as COLOUR under the ice, per the decision."""
        shade.KNOBS["ice_relief_damp"] = 1.0
        shelf = composite_pixel(1.0, ice=0.85, height=-80.0)
        basin = composite_pixel(1.0, ice=0.85, height=-4000.0)
        assert not np.array_equal(shelf, basin)


class TestItLeavesTheOtherSurfacesAlone:
    def test_ice_free_ocean_is_untouched(self):
        shade.KNOBS["ice_relief_damp"] = 0.0
        bare = composite_pixel(0.60, ice=0.0)
        shade.KNOBS["ice_relief_damp"] = 1.0
        assert np.array_equal(bare, composite_pixel(0.60, ice=0.0))

    def test_land_and_snow_are_untouched(self):
        """Ice is gated on `ocean` before the damp sees it, so land — snowy or bare — cannot
        move even if the ice field claims coverage there."""
        shade.KNOBS["ice_relief_damp"] = 0.0
        bare_land = composite_pixel(0.60, ocean=False, height=1500.0, ice=0.85)
        snowy_land = composite_pixel(0.60, ocean=False, height=1500.0, snow=1.0, ice=0.85)
        shade.KNOBS["ice_relief_damp"] = 1.0
        assert np.array_equal(bare_land,
                              composite_pixel(0.60, ocean=False, height=1500.0, ice=0.85))
        assert np.array_equal(snowy_land,
                              composite_pixel(0.60, ocean=False, height=1500.0, snow=1.0,
                                              ice=0.85))

    def test_inland_water_is_untouched(self):
        shade.KNOBS["ice_relief_damp"] = 0.0
        lake = composite_pixel(0.60, ocean=False, water=True, ice=0.85)
        shade.KNOBS["ice_relief_damp"] = 1.0
        assert np.array_equal(lake, composite_pixel(0.60, ocean=False, water=True, ice=0.85))


class TestFreshness:
    def test_it_reaches_the_composite_record(self):
        import json

        from pipeline.tile.shade_planet import composite_params

        assert "ice_relief_damp" in json.loads(composite_params({}, bodies.EARTH, WHOLE_PLANET))["knobs"]

    def test_it_is_not_hillshade_only(self):
        """Consumed by composite(), so a re-tune must restage the composite, and — through
        `cap_recipe`'s use of composite_params — both cap PNGs."""
        from pipeline.tile.shade_planet import HILLSHADE_ONLY_KNOBS

        assert "ice_relief_damp" not in HILLSHADE_ONLY_KNOBS
