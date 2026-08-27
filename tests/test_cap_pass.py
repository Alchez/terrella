"""The cap pass: which arm paints a body's discs, and that a switch between them restages both.

A DISC IS BUILT TO MATCH THE TILES IT FEATHERS INTO, so the cap producer is keyed on the same field
the planet producer is. That makes the registry's completeness a real claim rather than a tidiness
one: a planet producer with no cap arm is a body that renders raytraced tiles and composited discs,
which is the seam this whole arc exists to close.
"""

import dataclasses
import json

import pytest

from pipeline import bodies, planet_seam
from pipeline.tile import cap_pass, cap_raytrace, cap_render

EARTH = bodies.BODIES["earth"]
MARS = bodies.BODIES["mars"]
WHOLE_PLANET = planet_seam.KNOWN_RASTERS


class TestEveryPlanetProducerCanAlsoPaintADisc:
    def test_the_registry_covers_the_body_vocabulary_exactly(self):
        """DERIVED FROM `bodies.PLANET_PRODUCERS`, never listed beside it. A hand-written scope goes
        stale in silence, and the direction that matters is a producer nothing can paint a cap for:
        the pass would raise at the tail of a night's render rather than before it."""
        assert set(cap_pass.CAP_PRODUCERS) == set(bodies.PLANET_PRODUCERS)

    def test_an_unknown_producer_is_refused_naming_the_ones_that_exist(self):
        """No fallback, on the rule `bodies.get` and `palette.look_for` already state. A body
        quietly borrowing another's arm spends the render making the wrong kind of disc."""
        invented = dataclasses.replace(EARTH, planet_producer="watercolour")  # pyright: ignore[reportArgumentType]
        with pytest.raises(SystemExit, match="composite, raytrace"):
            cap_pass.producer_for(invented)

    def test_every_registered_body_resolves_to_an_arm(self, subtests):
        for name in sorted(bodies.BODIES):
            with subtests.test(body=name):
                assert cap_pass.producer_for(bodies.BODIES[name]) is not None

    def test_the_two_shipped_bodies_take_DIFFERENT_arms(self):
        """The second instance, with no fixture involved: Earth is raytraced and Mars composited
        today, so the dispatch is exercised on both sides by the registry as it ships. A test that
        only ever saw one body would pass with the key ignored entirely."""
        assert EARTH.planet_producer != MARS.planet_producer
        assert cap_pass.producer_for(EARTH) is not cap_pass.producer_for(MARS)
        assert cap_pass.producer_for(EARTH).render is cap_raytrace.render
        assert cap_pass.producer_for(MARS).render is cap_render.render_cap


class TestAnArmCarriesItsRenderAndItsRecipeTogether:
    """`cap_is_fresh` compares one sidecar per pole, so the arm that renders must be the arm that
    says what it rendered under. Split across two registries they could disagree, and the disagreement
    is silent: the disc would be painted by one producer and declared fresh by the other's recipe.
    """

    def test_every_arm_states_both(self, subtests):
        for name, producer in sorted(cap_pass.CAP_PRODUCERS.items()):
            with subtests.test(producer=name):
                assert callable(producer.render)
                assert callable(producer.recipe)

    def test_the_arms_do_not_write_the_same_recipe_for_one_disc(self, subtests):
        """What makes a producer switch restage. Both poles, because a sidecar is per pole and a
        recipe that happened to differ on one of them would leave the other silently fresh."""
        for grid in (cap_render.north_grid(EARTH), cap_render.south_grid(EARTH)):
            with subtests.test(pole=grid.name):
                written = {name: producer.recipe(grid, WHOLE_PLANET)
                           for name, producer in cap_pass.CAP_PRODUCERS.items()}
                assert len(set(written.values())) == len(written)

    def test_a_switch_leaves_the_disc_stale_in_BOTH_directions(self, tmp_path, subtests):
        """Run rather than argued, through the predicate the pass actually asks. A disc painted by
        one arm and checked by the other must read stale — and the reverse too, since a body can
        move back and the cheap version of this guard only ever tests the way it moved first."""
        grid = cap_render.north_grid(EARTH)
        assets = [tmp_path / "cap.webp"]
        assets[0].write_bytes(b"a disc")
        sidecar = tmp_path / "params.json"
        for wrote, checks in (("composite", "raytrace"), ("raytrace", "composite")):
            with subtests.test(wrote=wrote, checks=checks):
                sidecar.write_text(cap_pass.CAP_PRODUCERS[wrote].recipe(grid, WHOLE_PLANET))
                assert not cap_render.cap_is_fresh(
                    cap_pass.CAP_PRODUCERS[checks].recipe(grid, WHOLE_PLANET),
                    assets, sidecar, [])

    def test_a_disc_checked_by_the_arm_that_painted_it_reads_fresh(self, tmp_path, subtests):
        """The control, and it is the case every real pass takes. Without it the test above passes
        on a predicate that calls everything stale."""
        grid = cap_render.north_grid(EARTH)
        assets = [tmp_path / "cap.webp"]
        assets[0].write_bytes(b"a disc")
        sidecar = tmp_path / "params.json"
        for name, producer in sorted(cap_pass.CAP_PRODUCERS.items()):
            with subtests.test(producer=name):
                sidecar.write_text(producer.recipe(grid, WHOLE_PLANET))
                assert cap_render.cap_is_fresh(producer.recipe(grid, WHOLE_PLANET),
                                               assets, sidecar, [])


class TestTheRecipesAgreeAboutTheDiscTheyDescribe:
    def test_both_arms_record_the_same_grid(self, subtests):
        """The disc's geometry is not a producer's choice, so an arm that recorded its own would let
        the two draw different ground and each read fresh. `grid_recipe_fields` is the one owner."""
        grid = cap_render.north_grid(EARTH)
        wanted = cap_render.grid_recipe_fields(grid)
        for name, producer in sorted(cap_pass.CAP_PRODUCERS.items()):
            with subtests.test(producer=name):
                assert json.loads(producer.recipe(grid, WHOLE_PLANET))["grid"] == json.loads(
                    json.dumps(wanted))


class TestTheCapPassRequiresABody:
    """Moved here with `main`. The cap is the one output where the wrong sphere leaves no trace: it
    projects, blends and downsamples to every rung, and simply sits on a different parallel than the
    tiles it feathers into."""

    def test_omitting_the_body_is_an_error_rather_than_an_assumption(self):
        with pytest.raises(SystemExit):
            cap_pass.build_parser().parse_args([])

    def test_a_named_body_still_parses_the_pole_and_force_flags(self):
        args = cap_pass.build_parser().parse_args(["--body", "earth", "--north", "--force"])
        assert (args.body, args.north, args.force) == ("earth", True, True)

    def test_an_unknown_body_is_rejected_by_the_registry_not_silently_accepted(self):
        args = cap_pass.build_parser().parse_args(["--body", "pluto"])
        with pytest.raises(KeyError):
            bodies.get(args.body)
