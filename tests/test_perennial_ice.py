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
from typing import ClassVar

import numpy as np
import pytest
from conftest import cap_ground_metres_per_px_from_ground_radius

from pipeline import bodies, datasets, layers, mercator
from pipeline.look import layer_producers, mars_ice, perennial_ice, snow
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
        monkeypatch.setattr(datasets, "snow_persistence", lambda: moved)
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

    def test_every_registered_producer_belongs_to_a_body_that_declares_the_layer(self, subtests):
        """The agreement read from the REGISTRY rather than from the bodies, which is the direction
        that still has instances.

        It used to sweep the bodies that declare nothing and assert they hold no producer. Both
        registered planets now declare this layer, so that sweep found nothing to check and its own
        anti-vacuity assertion said so — the guard reporting that its subject had moved rather than
        passing on an empty list. Same claim, asked of a set that cannot empty while a producer
        exists to be wrong about.
        """
        assert perennial_ice.CAP_ICE_BY_BODY, "no producers at all — this sweep would be vacuous"
        for body_name, pole in perennial_ice.CAP_ICE_BY_BODY:
            with subtests.test(f"{body_name} {pole}"):
                assert layers.PERENNIAL_ICE.name in bodies.get(body_name).surface_layers, (
                    f"{body_name} registers a {pole} cap producer for a layer it does not declare — "
                    f"the cap would paint ice the composite knows nothing about")


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
        the formula would prove the two copies agree, not that either matches what ships.

        THE SOFTENING RIDES ON BOTH SIDES AND AGREES IN GROUND METRES, NOT IN PIXELS, which is why
        it is applied here at the CAP's resolution rather than at the Mercator window's. The two
        grids resolve the same 0.01 degree source cell at different pixel counts — a Mercator pixel
        at 82N is ~43 ground metres and the cap disc's is its own fixed figure — so a sigma equal on
        both sides in pixels would be unequal in the world, which is the axis the crossfade is
        judged on. `soften_source_cells` takes ground metres for exactly this reason, and pinning
        the equality here is what stops that seam being re-decided in pixels later."""
        # A 4x4 FIXTURE CANNOT CARRY THIS CLAIM ANY MORE, and the "saturated or dead" guard below is
        # what said so: the softening is a spatial operator with a ~1.4 px sigma on this grid, so a
        # 4-wide ramp comes out smeared to 0.72 at both ends and the test would be comparing two
        # mushes. The field is constant DOWN each column, which makes the vertical pass an exact
        # identity under `mode="nearest"`, and it over- and under-shoots the ramp by ten columns at
        # each end, which is past three sigma — so the extremes survive and the interior is the
        # gradient the comparison is about.
        profile = np.clip(np.linspace(-0.8, 1.8, 32), 0.0, 1.05) * 10_000.0
        packed = np.tile(profile.astype(np.float32), (32, 1))
        log: list[str] = []
        inputs = perennial_ice.CapIceInputs(
            land=np.ones((32, 32), dtype=bool),
            latitude=np.full((32, 32), 82.0, dtype=np.float32),
            warp=_fixed_warp(log, packed), burn=_refusing_burn,
            ground_metres_per_px=EARTH_CAP_GROUND_M_PER_PX)
        alpha = perennial_ice.cap_ice(bodies.EARTH, "north").alpha(inputs)

        top, bottom = (float(mercator.northing_at(lat, mercator.WEB_MERCATOR_RADIUS_M))
                       for lat in (84.0, 78.0))
        expected = snow.soften_source_cells(
            snow.snow_alpha(snow.unpack_persistence(packed), top, bottom),
            EARTH_CAP_GROUND_M_PER_PX)
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


class TestOnlyEarthsSouthDeclaresTheOutcropAsAnExclusion:
    """SCAR ADD's rock at the cap tier, where the producer now has nothing to do with it.

    `_earth_south` answers only where Antarctic ice IS. The outcrop is a `CapIce.exclusions` member
    that `cap_render` burns and `layer_producers.fold_white` removes after the union folds, which is
    the same law the tiles run and is what makes the two sides of the −84 crossfade agree by
    construction rather than by a docstring saying so.

    THE DECLARATION IS WHAT KEEPS THE POLE A FACT OF THE REGISTRY KEY, rather than a
    `grid.name == "south"` written into the renderer — the shape `cap_sources`' own docstring
    records as the mistake it was extracted to remove. It is also what keeps the burn off every
    other disc: an ogr2ogr of the whole ADD GeoPackage onto an Arctic or Martian grid comes back
    empty, and `must_draw` turns that into a raised exception on a shipping pass.
    """

    def test_only_earths_south_declares_an_exclusion(self, subtests):
        """Asserted HERE and never in `test_cap_render.py`, whose autouse fixture aliases every
        ("mars", pole) key to Earth's producer — `mars` is an Earth-shaped stand-in there, so a
        registry-wide claim written in that file reads a registry doctored for another question."""
        for key, expected in ((("earth", "south"), (layers.ANTARCTIC_ROCK,)),
                              (("earth", "north"), ()),
                              (("mars", "north"), ()),
                              (("mars", "south"), ())):
            with subtests.test(str(key)):
                got = perennial_ice.CAP_ICE_BY_BODY[key].exclusions()
                assert got == expected, (
                    f"{key} declares {[layer.name for layer in got]}, "
                    f"expected {[layer.name for layer in expected]}")

    def test_every_declared_exclusion_is_one_the_fold_actually_applies(self, subtests):
        """`fold_white` iterates `WHITE_EXCLUSIONS`, so a layer declared here and absent from that
        tuple is handed over and silently ignored: white a reader believes is being removed, with
        nothing going red. The two declarations are kept in step here."""
        for key, producer in perennial_ice.CAP_ICE_BY_BODY.items():
            with subtests.test(str(key)):
                for layer in producer.exclusions():
                    assert layer in layer_producers.WHITE_EXCLUSIONS

    def test_the_producer_is_rock_blind_and_is_the_bare_rule(self, ice_inputs):
        """The inversion guard, and the reason the declaration is the whole of the cap's
        involvement. A producer that could still see a rock mask could still subtract it inside its
        own answer, which is the placement that discarded 63% of the subtraction one tier up."""
        assert perennial_ice.cap_ice(bodies.EARTH, "south").alpha(ice_inputs) == pytest.approx(
            snow.antarctic_snow_mask(ice_inputs.land, ice_inputs.latitude))

    def test_no_cap_producer_can_be_handed_a_rock_at_all(self):
        """The field is GONE from `CapIceInputs` rather than passed as None, exactly as
        `LayerWindow.rock` is — which is what makes the old placement unwritable here too."""
        assert "rock" not in {field.name
                              for field in dataclasses.fields(perennial_ice.CapIceInputs)}


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

#: The cap grid the feather guard measures on — the shipped one, not a convenient one. A grid built
#: at a test's own span would let the feather be checked against a scale Mars never renders at.
MARS_NORTH = cap_render.north_grid(bodies.MARS)


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


def _field_warp(log: list[str], values: np.ndarray):
    """A `WarpToCap` handing back a chosen luma field and recording what was asked for."""
    def warp(source, name, resampling, dtype, srcnodata=None):
        log.append(name)
        return values
    return warp


def _unit_burn(log: list[str], masks: "dict[str, np.ndarray]"):
    """A `BurnToCap` over pre-decided unit masks, recording which units were asked for."""
    def burn(source, name, must_draw) -> np.ndarray:
        log.append(name)
        return masks[name]
    return burn


class TestMarsGradesTheFieldInsideTheMappedUnits:
    """Mars's two producers, driven with no GDAL behind them — which is what the injected warp and
    burn are for. The arithmetic they compose is tested next door; what is asserted here is that
    this producer composes it with THIS pole's constants and this pole's units."""

    #: A 4x4 disc: the left half inside `lApc`, one column of `Apu` beside it, the rest bare.
    LAPC = np.array([[True, True, False, False]] * 4)
    APU = np.array([[False, False, True, False]] * 4)

    def _inputs(self, field, warped, burnt):
        return perennial_ice.CapIceInputs(
            land=np.ones((4, 4), dtype=bool),
            latitude=np.full((4, 4), 85.0, dtype=np.float32),
            warp=_field_warp(warped, field), burn=_unit_burn(burnt, {"lapc": self.LAPC,
                                                                     "apu": self.APU}),
            ground_metres_per_px=cap_render.cap_ground_metres_per_px(
                cap_render.north_grid(bodies.MARS)))

    def _alpha(self, pole, field):
        warped, burnt = [], []
        alpha = perennial_ice.cap_ice(bodies.MARS, pole).alpha(
            self._inputs(field, warped, burnt))
        return alpha, warped, burnt

    def test_it_reads_the_brightness_field_and_both_units(self):
        """Both units at BOTH poles, which looks wasteful at the south and is not: `extent_for`
        evaluates each hemisphere's union, so a missing mask raises rather than reading as no ice."""
        for pole in ("north", "south"):
            _alpha, warped, burnt = self._alpha(pole, np.full((4, 4), 200.0))
            assert warped == ["viking_luma"]
            assert sorted(burnt) == ["apu", "lapc"]

    def test_the_north_paints_lApc_and_Apu_where_the_south_paints_lApc_alone(self):
        """The hemispheric extent rule, reaching the cap tier. Southern `Apu` is layered deposits
        that the albedo cannot tell from ordinary ground, so painting it would whiten most of that
        disc on no evidence."""
        bright = np.full((4, 4), 250.0)
        north, _, _ = self._alpha("north", bright)
        south, _, _ = self._alpha("south", bright)
        assert north[:, 2].min() > 0.9, "the north must paint Apu at full strength"
        # STRICTLY DIMMER RATHER THAN ZERO, and the difference is the feather doing its job: on a
        # disc this small every pixel is within one feather of `lApc`, so the south's `Apu` column
        # carries bleed from the unit next to it. Being OUTSIDE the extent is what the comparison
        # tests; demanding an exact zero would be asserting that the feather does not exist.
        assert south[:, 2].max() < north[:, 2].min(), "the south must not paint Apu as ice"
        assert min(north[:, 0].min(), south[:, 0].min()) > 0.9, "both poles paint lApc"

    def test_each_pole_grades_against_its_OWN_levels(self):
        """The pinning that lets the cap and the tiles crossfade without a step. Driven at the
        south's alpha-1 level: the north's is 30 DN higher, so a shared pair cannot give 1.0 here."""
        field = np.full((4, 4), mars_ice.ALPHA_LEVELS["south"][1])
        south, _, _ = self._alpha("south", field)
        north, _, _ = self._alpha("north", field)
        assert south[:, 0].min() == pytest.approx(1.0)
        assert north[:, 0].max() < 1.0

    def test_bare_ground_outside_every_unit_stays_exactly_zero(self):
        """The extent limits the CLAIM: however bright a pixel is, white is only drawn where the
        published map says there is ice. A feather softens the boundary and nothing beyond it."""
        alpha, _, _ = self._alpha("north", np.full((4, 4), 255.0))
        assert alpha[:, 3].max() < 1.0

    def test_an_unmeasured_pixel_is_never_ice(self):
        """Viking's fill is every channel at zero, which `mars_ice.luma` collapses to exactly zero;
        a fill that graded as ordinary brightness would paint the hole white."""
        alpha, _, _ = self._alpha("north", np.zeros((4, 4)))
        assert alpha == pytest.approx(np.zeros((4, 4)))

    def test_both_poles_declare_the_same_three_files_and_all_of_them_are_read(self):
        """`cap_is_fresh` requires every declared source to EXIST, so a path named here that the
        producer never opens pins the cap permanently stale."""
        for pole in ("north", "south"):
            declared = perennial_ice.cap_ice(bodies.MARS, pole).sources()
            assert [path.name for path in declared] == [
                "viking_luma_4326.tif", "lapc_sim3292.json", "apu_sim3292.json"]


class TestTheFeatherReachesItsGroundWidthOnTheRealCapScale:
    """The composition, which is the half neither neighbour can see. `mars_ice` pins that a feather
    of N ground metres is drawn N ground metres wide once it is told the scale, and `test_cap_render`
    pins what a cap pixel actually spans — between them sits this producer, whose only job here is to
    hand the second to the first, and which shipped once handing the AEQD map figure instead.

    THAT FAILURE HAS NO OTHER WITNESS. It leaves both neighbours green, raises nothing, and paints an
    ice edge that is a perfectly plausible ice edge; the only thing that changes is how far the fade
    reaches, and no one can see a fade width and name it in kilometres. So the assertion is made in
    the units the constant is written in — the drawn feather, converted back to Martian ground, is
    `FEATHER_KM` — with the pixel grid's own quantisation as the tolerance and nothing looser.

    Aimed with `conftest.cap_ground_metres_per_px_from_ground_radius` rather than with the production
    scale, and that is the whole design: a test that measured the feather against the same function
    the producer divided by would find them consistent no matter how wrong both were.
    """

    #: Wide enough to hold the extent plus a whole feather, and only four rows because the feather
    #: is measured across columns. Rows and columns both, so a transposed distance is not silent.
    SHAPE: ClassVar[tuple[int, int]] = (4, 96)
    INSIDE: ClassVar[int] = 50

    def _alpha(self, ground_metres_per_px: float) -> np.ndarray:
        """Mars's real north producer over a half-covered disc, driven at a chosen cap scale."""
        lapc = np.zeros(self.SHAPE, dtype=bool)
        lapc[:, :self.INSIDE] = True
        inputs = perennial_ice.CapIceInputs(
            land=np.ones(self.SHAPE, dtype=bool),
            latitude=np.full(self.SHAPE, 85.0, dtype=np.float32),
            # Saturating luma, so the grading is 1 wherever the extent is and the alpha that comes
            # back is the feather alone rather than the feather times an albedo shape.
            warp=_field_warp([], np.full(self.SHAPE, 255.0, dtype=np.float32)),
            burn=_unit_burn([], {"lapc": lapc, "apu": np.zeros(self.SHAPE, dtype=bool)}),
            ground_metres_per_px=ground_metres_per_px)
        return perennial_ice.cap_ice(bodies.MARS, "north").alpha(inputs)

    def _drawn_feather_m(self, alpha: np.ndarray) -> float:
        """How far past the extent the alpha is still lit, in TRUE Martian ground metres."""
        lit = int((alpha[0] > 0).sum()) - self.INSIDE
        return lit * cap_ground_metres_per_px_from_ground_radius(MARS_NORTH)

    def test_the_producer_draws_the_feather_its_constant_claims(self):
        """The claim in full: on the cap Mars actually ships, the fade reaches `FEATHER_KM` of that
        planet's own ground. The tolerance is one pixel because the lit run is a whole number of
        them, and a feather that missed by more than the grid can express is not rounding."""
        one_pixel = cap_ground_metres_per_px_from_ground_radius(MARS_NORTH)
        drawn = self._drawn_feather_m(self._alpha(
            cap_render.cap_ground_metres_per_px(MARS_NORTH)))
        assert drawn == pytest.approx(mars_ice.FEATHER_KM * 1000.0, abs=one_pixel)

    def test_the_map_figure_draws_a_feather_that_misses_by_far_more_than_a_pixel(self):
        """The positive control, and it is the shipped bug run on purpose. Mars's cap is drawn on a
        sphere near twice its size, so dividing by AEQD map metres reaches roughly half the ground
        distance — which the assertion above must be able to tell apart from rounding, or it is
        measuring nothing. Deliberately not pinned to a ratio: what is claimed is the direction and
        that the miss clears the tolerance, and the magnitude belongs to `bodies`."""
        one_pixel = cap_ground_metres_per_px_from_ground_radius(MARS_NORTH)
        drawn = self._drawn_feather_m(self._alpha(
            2.0 * MARS_NORTH.edge_m / MARS_NORTH.px))
        assert drawn < mars_ice.FEATHER_KM * 1000.0 - one_pixel


class TestTheTwoTiersAgreeOnTheColourOfTheSameIce:
    """The cap and the tiles crossfade over 80-84 degrees, so a body whose two tiers resolved
    different whites at one pole would change colour across that seam.

    The tiers reach the answer by different means on purpose — the cap registry keys on the pole, the
    composite registry keys on the layer and varies within a window — which is exactly why the
    agreement has to be asserted rather than assumed from a shared constant.
    """

    #: 3857 metres well inside each pole's ice band, so the composite producer's per-row choice is
    #: evaluated where ice is actually painted rather than at an arbitrary latitude.
    BANDS: ClassVar[dict[str, tuple[float, float]]] = {
        "north": (18_000_000.0, 17_000_000.0), "south": (-17_000_000.0, -18_000_000.0)}

    def test_each_body_paints_one_pole_the_same_in_both_tiers(self, subtests):
        checked = 0
        for body in bodies.BODIES.values():
            if layers.PERENNIAL_ICE.name not in body.surface_layers:
                continue
            for pole, (top, bottom) in self.BANDS.items():
                cap_paint = perennial_ice.cap_ice(body, pole).paint()
                latitude = snow.latitude_per_row(top, bottom, 4)
                window = layer_producers.LayerWindow(
                    raw=None, watercode=None, land=np.ones((4, 4), dtype=bool),
                    ocean=np.zeros((4, 4), dtype=bool), latitude=latitude,
                    ground_metres_per_px=mercator.ground_metres_per_pixel(
                        latitude, (top - bottom) / 4,
                        bodies.ground_metres_per_mercator_unit(body)),
                    top=top, bottom=bottom)
                tile_paint = layer_producers.producer_for(
                    body, layers.PERENNIAL_ICE).paint(window)
                assert tile_paint is not None
                with subtests.test(f"{body.name} {pole}"):
                    for cap_end, tile_end in zip(cap_paint, tile_paint, strict=True):
                        tile_rgb = np.asarray(tile_end, dtype=int).reshape(3, -1)
                        assert (tile_rgb == np.asarray(cap_end, dtype=int).reshape(3, 1)).all(), (
                            f"{body.name}'s {pole} cap and tiles disagree about the ice colour")
                checked += 1
        assert checked == 4, f"expected both poles of both bodies, checked {checked}"

    def test_the_check_can_fail_when_a_tier_is_swung(self, monkeypatch):
        """The control. Without it this class passes on any body whose two tiers happen to read one
        constant, which is the shape that stays green after a seam is introduced."""
        monkeypatch.setitem(perennial_ice.CAP_ICE_BY_BODY, ("mars", "north"),
                            dataclasses.replace(perennial_ice.CAP_ICE_BY_BODY[("mars", "north")],
                                                paint=lambda: ((0, 0, 0), (0, 0, 0))))
        with pytest.raises(AssertionError, match="disagree about the ice colour"):
            TestTheTwoTiersAgreeOnTheColourOfTheSameIce().test_each_body_paints_one_pole_the_same_in_both_tiers(
                _NullSubtests())


class _NullSubtests:
    """`subtests.test` as a no-op context manager, so the control above sees the raw assertion
    rather than the plugin's own swallowing of a subtest failure."""

    def test(self, *_args, **_kwargs):
        import contextlib
        return contextlib.nullcontext()

