"""Contract for the shared vector-cut driver.

WHAT A MERGE OF TWO COMPOSERS CAN BREAK SILENTLY, and therefore what is pinned here. Both bodies'
archives are LIVE, and each is gated on `recipe()` matching a sidecar sitting beside it: one key
appearing or vanishing re-cuts a pyramid that was correct, with nothing to see but a longer pass.
The knobs are guarded body by body in the two stage tests; what could only break in the shared
driver is the SHAPE of the recipe and the derivation of the paths, so that is what is here.

THE KEY SETS ARE LITERALS, taken from the two sidecars on disk when the driver was written. A test
that derived them from `recipe()` would compare the function with itself and pass whatever it said,
which is exactly the failure the merge risked.
"""

import dataclasses
from pathlib import Path

import pytest

from pipeline import bodies, paths
from pipeline.compose import (
    countries_pmtiles,
    features_pmtiles,
    vector_cut,
    vector_layers,
)

#: What every body records, whatever it cuts. `seam_recipe`'s two keys ride along because the
#: geometry handed to the cut is as much a setting as the cut's own.
SHARED_KEYS = {"layers", "min_zoom", "max_zoom", "simplification", "simplification_max_zoom",
               "buffer", "extent", "seam_band_degrees", "seam_twin_latitude_epsilon"}

#: Earth names the one GeoJSON its whole pyramid descends from; Mars's four layers come from four
#: separate gazetteer files and it names none. That asymmetry is the reason `extra_recipe` exists
#: rather than a shared builder, and it is the thing a merge would have quietly evened out.
EXPECTED_KEYS = {
    countries_pmtiles.CUT: SHARED_KEYS | {"source"},
    features_pmtiles.CUT: SHARED_KEYS,
}


class TestTheRecipeShapeIsWhatTheLIVEArchivesWereCutUnder:
    @pytest.mark.parametrize("cut", list(EXPECTED_KEYS), ids=lambda cut: cut.name)
    def test_the_key_set_is_exactly_what_the_sidecar_carries(self, cut):
        """Equality, not containment: an EXTRA key restages just as surely as a missing one, and
        containment is the assertion that would have let the merge add a body field to both."""
        assert set(vector_cut.recipe(cut)) == EXPECTED_KEYS[cut]

    def test_earths_source_key_is_the_file_it_actually_reads(self):
        """A name recorded by hand would keep matching its sidecar after the source moved."""
        assert (vector_cut.recipe(countries_pmtiles.CUT)["source"]
                == countries_pmtiles.source_path().name)

    def test_mars_records_no_source_at_all(self):
        """The negative instance. Without it, `extra_recipe` could return Earth's key on every body
        and only Earth's assertion above would notice."""
        assert "source" not in vector_cut.recipe(features_pmtiles.CUT)

    @pytest.mark.parametrize("cut", list(EXPECTED_KEYS), ids=lambda cut: cut.name)
    def test_the_recorded_layers_are_the_staged_layers_in_order(self, cut):
        """The sidecar is a producer's claim about what it emitted, and ORDER is part of it: the
        first layer creates the GeoPackage and the rest append to it."""
        assert vector_cut.recipe(cut)["layers"] == list(cut.sources())


class TestThePathsComeFromTheBodyAndTheProduct:
    """Three paths the two stages used to spell out, now derived. A body that got its own directory
    by accident of a literal would have kept it after the merge; these say where it comes from."""

    @pytest.mark.parametrize("cut", list(EXPECTED_KEYS), ids=lambda cut: cut.name)
    def test_the_directory_is_the_bodys_vector_stage(self, cut):
        assert vector_cut.out_dir(cut) == bodies.work_dir(cut.body, "planet_vector")

    @pytest.mark.parametrize("cut", list(EXPECTED_KEYS), ids=lambda cut: cut.name)
    def test_the_archive_is_named_for_the_ROLE(self, cut):
        """`vector.pmtiles` on every planet: the frontend addresses it by role, and two bodies whose
        archives differed in name would need the transport to know which product each holds."""
        assert vector_cut.out(cut).name == "vector.pmtiles"

    @pytest.mark.parametrize("cut", list(EXPECTED_KEYS), ids=lambda cut: cut.name)
    def test_the_intermediates_are_named_for_the_PRODUCT(self, cut):
        """The sidecar keeps its producer's name where the archive takes the role's — so two bodies'
        recipes are still distinguishable in a listing, and INVENTORY's rows stay readable."""
        assert vector_cut.staged(cut).name == f"{cut.name}_staged.gpkg"
        assert vector_cut.recipe_path(cut).name == f"{cut.name}_tiles_params.json"

    def test_two_bodies_do_not_share_a_directory(self):
        """The control for the three above, and the failure they exist to catch: every assertion
        here is satisfied by a driver that ignores `cut.body` entirely."""
        assert vector_cut.out_dir(countries_pmtiles.CUT) != vector_cut.out_dir(features_pmtiles.CUT)

    def test_a_redirected_store_moves_the_archive(self, tmp_path, monkeypatch):
        """What the callables are FOR. `bodies.work_dir` reads `paths.DATA` at call time, so a
        redirect reaches these three — a module-level constant would have frozen them at import and
        moved a stage's sources without its outputs."""
        monkeypatch.setattr(paths, "DATA", tmp_path)
        assert vector_cut.out(countries_pmtiles.CUT).is_relative_to(tmp_path)


class TestTheRunPreflight:
    def test_a_derived_layer_is_not_a_missing_prerequisite(self, tmp_path):
        """This stage WRITES the derived layers, so their absence is work to do. Counting them as
        missing would make a clean store refuse to run the thing that would populate it."""
        absent = tmp_path / "nothing.geojson"
        cut = dataclasses.replace(
            countries_pmtiles.CUT,
            sources=lambda: {countries_pmtiles.FILL_LAYER: absent,
                             countries_pmtiles.OUTLINE_LAYER: absent},
            derived_layers=(countries_pmtiles.OUTLINE_LAYER,),
        )
        assert vector_cut.missing_sources(cut) == [absent]

    def test_an_acquired_source_that_exists_is_not_reported(self, tmp_path):
        """The control: the list is empty for the right reason rather than always."""
        present = tmp_path / "there.geojson"
        present.write_text("x", encoding="utf-8")
        cut = dataclasses.replace(
            countries_pmtiles.CUT,
            sources=lambda: {countries_pmtiles.FILL_LAYER: present},
            derived_layers=(),
        )
        assert vector_cut.missing_sources(cut) == []


class TestNeitherStageKeepsAPrivateCopyOfTheDriver:
    """The seam itself, so a future edit that inlines one of these back into a body fails here.

    Nothing else would catch it: a re-inlined `is_fresh` passes every behavioural test on the day it
    is written and only drifts later, which is the whole argument for the shared module — and is
    exactly how the two composers came to share a nine-function skeleton in the first place.
    """

    DRIVER_FUNCTIONS = ("is_fresh", "derive", "stage", "recipe", "recipe_path",
                        "derivation_is_stamped", "pmtiles_command")

    @pytest.mark.parametrize("module", [countries_pmtiles, features_pmtiles],
                             ids=lambda module: module.__name__.rsplit(".", 1)[-1])
    def test_no_stage_defines_a_driver_function(self, module, subtests):
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        for name in self.DRIVER_FUNCTIONS:
            with subtests.test(function=name):
                assert f"def {name}(" not in source

    def test_the_driver_really_defines_them(self, subtests):
        """The positive control. Renaming a driver function would otherwise make every assertion
        above pass while the property they describe stopped existing."""
        source = Path(vector_cut.__file__ or "").read_text(encoding="utf-8")
        for name in self.DRIVER_FUNCTIONS:
            with subtests.test(function=name):
                assert f"def {name}(" in source


class TestTheKnobsStayPerBody:
    def test_the_driver_holds_no_knob_of_its_own(self, subtests):
        """Both bodies carry the same five values and each argues for its own — Mars keeps Earth's
        simplification because no Mars measurement argues for another, which is a statement about a
        measurement rather than an inheritance. A default here would delete that difference."""
        fields = {field.name for field in dataclasses.fields(vector_cut.VectorCut)}
        for knob in ("min_zoom", "max_zoom", "simplification", "simplification_max_zoom", "buffer"):
            with subtests.test(knob=knob):
                assert knob in fields, f"{knob} must be declared per body, not defaulted"

    def test_the_extent_is_the_ONE_thing_the_driver_owns(self):
        """It is the MVT conversion's contract rather than a body's opinion, and neither stage has
        ever set it — so it has one home and the recipe reads it from there."""
        assert vector_cut.recipe(countries_pmtiles.CUT)["extent"] == vector_layers.EXTENT
        assert vector_cut.recipe(features_pmtiles.CUT)["extent"] == vector_layers.EXTENT
