"""The cap pass: that a disc's sidecar describes the disc, and that the CLI names its body.

A DISC IS BUILT TO MATCH THE TILES IT FEATHERS INTO, so it is raytraced off the same rig and its
freshness question is asked against that one recipe.
"""

import json

import pytest

from pipeline import bodies, planet_seam
from pipeline.tile import cap_pass, cap_raytrace, cap_render

EARTH = bodies.BODIES["earth"]
WHOLE_PLANET = planet_seam.KNOWN_RASTERS


class TestTheSidecarSaysWhatPaintedTheDisc:
    """`cap_is_fresh` compares one sidecar per pole against the recipe of the arm about to run, so
    the recipe has to move whenever anything it names does. The stale arm is BUILT rather than
    borrowed: it used to be the composite's recipe, and a guard sourcing its negative instance from
    a second producer stops testing anything the day that producer is deleted.
    """

    def test_a_disc_checked_by_the_recipe_that_painted_it_reads_fresh(self, tmp_path, subtests):
        """The case every real pass takes. Without it the test below passes on a predicate that
        calls everything stale."""
        for grid in (cap_render.north_grid(EARTH), cap_render.south_grid(EARTH)):
            with subtests.test(pole=grid.name):
                assets = [tmp_path / f"cap_{grid.name}.webp"]
                assets[0].write_bytes(b"a disc")
                sidecar = tmp_path / f"params_{grid.name}.json"
                sidecar.write_text(cap_raytrace.params(grid, WHOLE_PLANET))
                assert cap_render.cap_is_fresh(cap_raytrace.params(grid, WHOLE_PLANET),
                                               assets, sidecar, [])

    def test_a_disc_whose_recipe_has_moved_reads_stale(self, tmp_path, subtests):
        """Both poles, because a sidecar is per pole and a predicate that happened to answer for
        one of them would leave the other silently fresh."""
        for grid in (cap_render.north_grid(EARTH), cap_render.south_grid(EARTH)):
            with subtests.test(pole=grid.name):
                assets = [tmp_path / f"cap_{grid.name}.webp"]
                assets[0].write_bytes(b"a disc")
                sidecar = tmp_path / f"params_{grid.name}.json"
                painted = json.loads(cap_raytrace.params(grid, WHOLE_PLANET))
                painted["producer"] = "something-else"
                sidecar.write_text(json.dumps(painted, sort_keys=True, indent=2))
                assert not cap_render.cap_is_fresh(cap_raytrace.params(grid, WHOLE_PLANET),
                                                  assets, sidecar, [])

    def test_the_recipe_records_the_grid_from_its_one_owner(self):
        """The disc's geometry is not the renderer's to choose: an arm recording its own would let
        the disc and the elevation texture draw different ground and each read fresh."""
        grid = cap_render.north_grid(EARTH)
        recorded = json.loads(cap_raytrace.params(grid, WHOLE_PLANET))["grid"]
        assert recorded == json.loads(json.dumps(cap_render.grid_recipe_fields(grid)))


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
