"""The per-body, per-pole seam that decides what a cap's perennial ice IS and what it reads.

The gap this closes was not a hardcoded PATH, which is what a grep of the old code showed. Both
poles were already body-gated; what was hardcoded was the MECHANISM. `render_cap_north` warped
NSIDC-0791 and smoothstepped it inline, so any second body declaring the layer would have had
Earth's northern-hemisphere terrestrial snow persistence warped onto its own pole and painted as
that world's ice — at the same latitudes, with no missing file and no error.

So the tests here are about the seam rather than about the arithmetic: which producer a body gets,
whether it can get the wrong one, whether it declares what it reads, and whether the two halves of
that declaration can drift apart.
"""

import dataclasses

import numpy as np
import pytest

from pipeline import bodies, layers, mercator
from pipeline.render import perennial_ice, snow
from pipeline.tile import cap_render


class TestTheRegistryRefusesRatherThanFallingBack:
    def test_a_body_with_no_producer_raises_and_names_itself(self, subtests):
        """A fallback here is worse than the ramp fallback `look_for` refuses. A wrong ramp renders
        a plausible planet in the wrong colours; a wrong ice producer renders a plausible planet
        wearing another world's measured cryosphere, which reads as an observation."""
        stranger = dataclasses.replace(bodies.EARTH, name="stranger", path_prefix="stranger")
        for pole in ("north", "south"):
            with subtests.test(pole):
                with pytest.raises(KeyError) as raised:
                    perennial_ice.cap_ice(stranger, pole)
                assert "stranger" in str(raised.value) and pole in str(raised.value)

    def test_earth_resolves_at_both_poles(self):
        """The anti-vacuity: without it the test above passes against a registry that is empty."""
        for pole in ("north", "south"):
            assert perennial_ice.cap_ice(bodies.EARTH, pole) is not None


class TestThePoleIsPartOfTheKey:
    def test_earths_two_poles_get_DIFFERENT_producers(self):
        """The seam's second instance, and the reason the pole is in the key rather than resolved
        inside one per-body function. Keyed by body alone Earth would be a single entry branching
        on the pole internally — one instance, exercised by construction, proving nothing about the
        parameterisation until a second planet arrived to test it in production."""
        north = perennial_ice.cap_ice(bodies.EARTH, "north")
        south = perennial_ice.cap_ice(bodies.EARTH, "south")
        assert north.alpha is not south.alpha
        assert north.sources() and not south.sources()

    def test_the_two_producers_differ_in_MECHANISM_not_in_a_constant(self, ice_inputs):
        """Stated as behaviour rather than as identity, because two distinct functions could still
        be one function copied. The north reads a raster and the south refuses to: driven over the
        same inputs, only one of them touches the warp."""
        warped: list[str] = []
        inputs = dataclasses.replace(ice_inputs, warp=_recording_warp(warped, ice_inputs.land.shape))
        perennial_ice.cap_ice(bodies.EARTH, "north").alpha(inputs)
        assert warped == ["sp"]
        warped.clear()
        perennial_ice.cap_ice(bodies.EARTH, "south").alpha(inputs)
        assert warped == []


class TestAProducerDeclaresItsOwnInputs:
    def test_the_sources_are_read_at_CALL_time_so_a_redirect_reaches_them(self, monkeypatch,
                                                                         tmp_path):
        """Written because the first version of this registry got it wrong, and every gate stayed
        green: a tuple literal in the registry evaluates `snow.SP_NC` once, at import, so a caller
        that moves the data store is answered with the path from before the move. The code this
        seam replaced read the constant at its call site, so freezing it would have been a silent
        narrowing introduced by the extraction rather than a property of the seam."""
        moved = tmp_path / "somewhere-else.nc"
        monkeypatch.setattr(snow, "SP_NC", moved)
        assert perennial_ice.cap_ice(bodies.EARTH, "north").sources() == (moved,)

    def test_a_producer_that_reads_nothing_declares_an_empty_tuple(self):
        """An empty tuple is a statement, not an omission. Earth's south is latitude and land and
        nothing else, so no file on disk could make its cap stale and none should be listed —
        `cap_is_fresh` requires every listed source to EXIST, so a courtesy entry would leave that
        cap permanently stale."""
        assert perennial_ice.cap_ice(bodies.EARTH, "south").sources() == ()


class TestTheRegistryAndTheLayerDeclarationsAgree:
    """Both directions, because each is silent on its own. A body declaring the layer with no
    producer raises at render time — loud, but only for whoever runs the pass. A producer
    registered for a body that declares no layer is never called at all, so it looks like working
    code and describes a cap that will never be painted."""

    def test_every_body_declaring_the_layer_has_a_producer_at_both_poles(self, subtests):
        declaring = [body for body in bodies.BODIES.values()
                     if layers.PERENNIAL_ICE.name in body.surface_layers]
        assert declaring, "no body declares perennial ice — this sweep would pass vacuously"
        for body in declaring:
            for pole in ("north", "south"):
                with subtests.test(f"{body.name} {pole}"):
                    assert perennial_ice.cap_ice(body, pole)

    def test_no_producer_is_registered_for_a_body_that_declares_no_such_layer(self, subtests):
        silent = [body for body in bodies.BODIES.values()
                  if layers.PERENNIAL_ICE.name not in body.surface_layers]
        assert silent, "every body declares perennial ice — this sweep would pass vacuously"
        for body in silent:
            with subtests.test(body.name):
                assert not [key for key in perennial_ice.CAP_ICE_BY_BODY if key[0] == body.name]


class TestEarthsProducersComputeWhatTheyComputedInline:
    """The extraction's own claim: the arithmetic that used to sit in the two renderers is the
    arithmetic that runs now. Both oracles are functions this file did not write."""

    def test_the_north_reproduces_the_TILE_paths_alpha_at_saturating_latitude(self):
        """The cap comment's load-bearing sentence, made executable. The whole disc is north of 78,
        and `snow_alpha`'s threshold ramp saturates at `RAMP_LAT_HI` (63) — so above that band the
        cap's fixed-threshold reproduction and the tile path's per-row function must agree exactly.
        That equality is why the cap is allowed to skip `snow_alpha`, whose per-row latitude is
        Mercator-specific and simply wrong on an AEQD grid.

        `snow.snow_alpha` is the oracle rather than a smoothstep written out here: a second copy of
        the formula would prove the two copies agree, not that either matches what ships."""
        packed = (np.arange(16, dtype=np.float32) * 700.0).reshape(4, 4)  # 0.00 .. 1.05 unpacked
        log: list[str] = []
        inputs = perennial_ice.CapIceInputs(
            land=np.ones((4, 4), dtype=bool),
            latitude=np.full((4, 4), 82.0, dtype=np.float32),
            warp=_fixed_warp(log, packed), burn=_refusing_burn,
            ground_metres_per_px=EARTH_CAP_GROUND_M_PER_PX)
        alpha = perennial_ice.cap_ice(bodies.EARTH, "north").alpha(inputs)

        top, bottom = (float(mercator.northing_at(lat, mercator.WEB_MERCATOR_RADIUS_M))
                       for lat in (84.0, 78.0))
        expected = snow.snow_alpha(snow.unpack_persistence(packed), top, bottom)
        assert alpha == pytest.approx(expected)
        assert alpha.max() > 0.9 and alpha.min() == 0.0, "a saturated or dead ramp proves nothing"

    def test_the_south_is_the_ONE_HOME_the_tile_composite_also_calls(self, ice_inputs):
        """Identity against `snow.antarctic_snow_mask` rather than a re-derived latitude rule: the
        two sides of the −84 crossfade agree because they call the same function, and a copy here
        would let this test keep passing while they stopped."""
        alpha = perennial_ice.cap_ice(bodies.EARTH, "south").alpha(ice_inputs)
        assert alpha == pytest.approx(
            snow.antarctic_snow_mask(ice_inputs.land, ice_inputs.latitude))
        assert alpha[0].max() == 0.0, "the −58 row is north of the threshold and must stay bare"
        assert alpha[3].min() == 1.0, "the −89 row is all land and must be forced white"


@pytest.fixture
def ice_inputs() -> perennial_ice.CapIceInputs:
    """A 4x4 cap: land everywhere except one ocean pixel, latitudes straddling the −60 threshold.

    Small and hand-checkable on purpose — these producers are arithmetic, and an oracle written as
    a second implementation over a big array proves the two implementations agree rather than that
    either is right.
    """
    land = np.ones((4, 4), dtype=bool)
    land[0, 0] = False
    latitude = np.array([[-58.0] * 4, [-62.0] * 4, [-70.0] * 4, [-89.0] * 4], dtype=np.float32)
    return perennial_ice.CapIceInputs(land=land, latitude=latitude,
                                      warp=_recording_warp([], (4, 4)), burn=_refusing_burn,
                                      ground_metres_per_px=EARTH_CAP_GROUND_M_PER_PX)


#: Earth's real cap scale, so a producer that started reading it would be handed a truthful number
#: rather than a placeholder that makes a units bug look like a fixture artifact.
EARTH_CAP_GROUND_M_PER_PX = cap_render.cap_ground_metres_per_px(cap_render.north_grid(bodies.EARTH))


def _refusing_burn(source, name, must_draw) -> np.ndarray:
    """A `BurnToCap` that fails if it is ever called.

    THE ABSENCE IS THE ASSERTION. Earth's two producers read a NetCDF and a latitude rule; neither
    rasterizes a vector, and neither should start. Passing a working burn here would let one acquire
    a vector dependency that no test could see, which is the same silence `_fixed_warp` exists to
    break on the warp side.
    """
    raise AssertionError(
        f"Earth's cap ice must not rasterize a vector, but {name} asked to burn {source}")


def _fixed_warp(log: list[str], packed: np.ndarray):
    """A `WarpToCap` that records what it was asked for and hands back `packed`.

    RECORDING IS THE ASSERTION, the same way `_drive_cap` uses it in the cap tests: a producer that
    is off must never reach the warp, and a test reading only the returned alpha would pass against
    one that warped Earth's climatology and then discarded it.
    """
    def warp(source: str, name: str, resampling: str, dtype: str,
             srcnodata: "float | None" = None) -> np.ndarray:
        log.append(name)
        return packed
    return warp


def _recording_warp(log: list[str], shape: tuple[int, int]):
    """`_fixed_warp` over a bland packed field, for tests that care only about what was asked."""
    rows, cols = shape
    return _fixed_warp(log, (np.arange(rows * cols, dtype=np.float32) * 100.0).reshape(shape))
