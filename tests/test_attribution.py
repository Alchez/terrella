"""The credit registry: that it is total, that it derives, and that its copies cannot drift.

The sibling `test_attributions.py` asks whether a licence-required string has drifted between the
places a reader meets it. This one asks whether the registry itself is complete and whether what
derives from it still does, which a string sweep cannot see: a notice can be word-perfect in every
file and still be absent from the archive that owes it, or present on a card for a body that does
not use it.

Four events should move a credit, and each has a row here: a new body, a new surface layer on one,
a new archive layer, and a change to what an archive bakes. The one event with no guard yet is a
new DATASET arriving in an existing layer, which needs an acquisition-side sweep rather than
anything this file can see.
"""

import json
import re
from pathlib import Path

import pytest

from pipeline import attribution, bodies, layers

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_TS = REPO_ROOT / "web/src/lib/tileAddress.ts"
GENERATED_JSON = REPO_ROOT / "web/src/data/attributions.json"


class TestTheRegistryIsTotal:
    """Every body answers for every destination, or the failure waits until a cut is running.

    Before `CREDITS` this was three dicts keyed by body name and only two of them had a check, so
    a new planet reddened on the heightfield and the paint and raised `KeyError: 'moon'` from the
    vector cut, on the box, mid-pass.
    """

    def test_every_body_has_a_credits_entry(self, subtests):
        for name in bodies.BODIES:
            with subtests.test(name):
                assert name in attribution.CREDITS

    def test_every_body_answers_for_every_destination(self, subtests):
        for name, credits in attribution.CREDITS.items():
            with subtests.test(f"{name} heightfield"):
                assert credits.heightfield
            with subtests.test(f"{name} vector"):
                assert credits.vector

    def test_every_key_named_anywhere_resolves_to_a_source(self, subtests):
        for name, credits in attribution.CREDITS.items():
            named = {*credits.heightfield, *credits.vector, *credits.heroes,
                     *(key for keys in credits.painted.values() for key in keys)}
            with subtests.test(name):
                assert named <= set(attribution.SOURCES), (
                    f"{sorted(named - set(attribution.SOURCES))} named by {name} but not declared"
                )

    def test_no_source_is_declared_and_then_used_by_nobody(self):
        """A source reachable from no body reaches no archive and no card, so it is a dead entry
        that still reads as a credit being given."""
        used = {key for credits in attribution.CREDITS.values()
                for key in (*credits.heightfield, *credits.vector, *credits.heroes,
                            *(k for keys in credits.painted.values() for k in keys))}
        assert set(attribution.SOURCES) == used


class TestWhatEachArchivePaints:
    """The painted half must equal the layers a relief cut actually bakes, so switching a layer on
    reddens until the source is credited and switching one off reddens until the claim is dropped.
    """

    def test_every_body_credits_exactly_the_layers_it_paints(self, subtests):
        for body in bodies.BODIES.values():
            with subtests.test(body.name):
                assert set(attribution.CREDITS[body.name].painted) == \
                       attribution.painted_layers(body)

    def test_the_coastline_is_not_painted_into_a_tile(self):
        """It is a vector overlay the client draws, so a raster archive owes it no credit. The
        column that decides is the block render's, and copying `in_planet` is the near miss."""
        assert "coastline" in bodies.EARTH.surface_layers
        assert "coastline" not in attribution.painted_layers(bodies.EARTH)

    def test_a_layer_the_vocabulary_does_not_have_cannot_be_credited(self, subtests):
        for name, credits in attribution.CREDITS.items():
            with subtests.test(name):
                assert set(credits.painted) <= layers.SURFACE_LAYERS


class TestTheArchiveLayersAreTheSiteS:
    """The pyramid vocabulary is spelled in two languages, which is exactly where "they happen to
    be equal" stops being checkable by either side. `test_paths.py` already crosses this boundary
    for the stage directories; this is the same guard for the layer names."""

    def test_the_layer_vocabulary_matches_the_typescript_union(self):
        source = REGISTRY_TS.read_text(encoding="utf-8")
        union = re.search(r"export type LayerId = ([^;]+);", source)
        assert union is not None, (
            "tileAddress.ts no longer declares `LayerId` as a plain union this guard can read — "
            "an assertion it cannot make is not one it passes"
        )
        declared = set(re.findall(r'"(\w+)"', union.group(1)))
        assert declared == set(attribution.ARCHIVE_LAYERS), (
            f"tileAddress.ts publishes {sorted(declared)} while attribution.py credits "
            f"{sorted(attribution.ARCHIVE_LAYERS)} — a pyramid declared on one side of the "
            "language boundary alone is the drift this refuses"
        )

    def test_the_packer_takes_only_the_raster_layers(self):
        """`pack_pmtiles` builds no vector archive: `compose/vector_cut.py` cuts those straight to
        PMTiles, so the packer's `--layer` choices are the narrower set."""
        assert set(attribution.RASTER_LAYERS) < set(attribution.ARCHIVE_LAYERS)
        assert "vector" not in attribution.RASTER_LAYERS


class TestTheRequiredNoticesReachTheArchiveThatOwesThem:
    """Obligations only. Courtesy citations are carried too, and asserting them would make this
    fail for reasons that are not legal ones, which is how a guard gets deleted."""

    def test_earth_relief_carries_every_licence_required_notice(self, subtests):
        credit = attribution.for_archive(bodies.EARTH, "relief")
        for key in ("glo30", "rgi", "seaice", "addrock"):
            with subtests.test(key):
                assert attribution.SOURCES[key].notice in credit
        with subtests.test("Copernicus 6(c)"):
            assert attribution.COPERNICUS_LIABILITY in credit

    def test_mars_relief_carries_both_of_its_requested_citations(self, subtests):
        credit = attribution.for_archive(bodies.MARS, "relief")
        for key in ("mars_dem", "mars_sim3292"):
            with subtests.test(key):
                assert attribution.SOURCES[key].notice in credit

    def test_a_terrain_cut_carries_its_heightfield_and_none_of_the_paint(self, subtests):
        for body in bodies.BODIES.values():
            credit = attribution.for_archive(body, "terrain")
            painted = {key for keys in attribution.CREDITS[body.name].painted.values()
                       for key in keys}
            with subtests.test(f"{body.name} keeps the DEM"):
                assert all(attribution.SOURCES[key].notice in credit
                           for key in attribution.CREDITS[body.name].heightfield)
            with subtests.test(f"{body.name} drops the paint"):
                assert not any(attribution.SOURCES[key].notice in credit for key in painted)

    def test_a_vector_cut_names_its_geometry_and_no_elevation_data(self, subtests):
        for body in bodies.BODIES.values():
            credit = attribution.for_archive(body, "vector")
            with subtests.test(f"{body.name} names its source"):
                assert all(attribution.SOURCES[key].notice in credit
                           for key in attribution.CREDITS[body.name].vector)
            with subtests.test(f"{body.name} claims no heightfield"):
                assert not any(attribution.SOURCES[key].notice in credit
                               for key in attribution.CREDITS[body.name].heightfield)

    def test_the_copernicus_disclaimer_follows_the_dem_and_not_the_body(self):
        """Earth's vector archive is Natural Earth geometry with no WorldDEM-30 in it. It carried
        the Article 6(c) sentence until the module was made to print itself."""
        assert attribution.COPERNICUS_LIABILITY not in \
               attribution.for_archive(bodies.EARTH, "vector")

    def test_every_archive_states_the_licence_on_its_own_output(self, subtests):
        for body in bodies.BODIES.values():
            for layer in attribution.ARCHIVE_LAYERS:
                with subtests.test(f"{body.name}/{layer}"):
                    assert "CC BY-SA 4.0" in attribution.for_archive(body, layer)

    def test_the_three_pyramids_do_not_compose_one_credit(self):
        """The vacuity control: every assertion here is a substring test, and a function returning
        one long constant for everything would satisfy the positive half of all of them."""
        composed = {attribution.for_archive(bodies.EARTH, layer)
                    for layer in attribution.ARCHIVE_LAYERS}
        assert len(composed) == len(attribution.ARCHIVE_LAYERS)

    def test_an_unknown_layer_raises_rather_than_composing_something(self):
        with pytest.raises(ValueError, match="not an archive layer"):
            attribution.for_archive(bodies.EARTH, "")


class TestThePageListIsDerived:
    """The About page's cards used to be a hand-kept list beside this one, and it had drifted in
    both directions: SCAR ADD is CC-BY, named required in ATTRIBUTIONS.md, and appeared on no card.
    """

    def test_a_source_the_body_uses_anywhere_gets_a_card(self, subtests):
        for body in bodies.BODIES.values():
            credits = attribution.CREDITS[body.name]
            expected = {*credits.heightfield, *credits.vector, *credits.heroes,
                        *(key for keys in credits.painted.values() for key in keys)}
            carded = {source.name for source in attribution.on_the_page(body)}
            with subtests.test(body.name):
                assert carded == {attribution.SOURCES[key].name for key in expected}

    def test_the_two_sources_that_were_missing_are_on_a_card(self, subtests):
        """Named rather than left to the derivation, because these are the failures that motivated
        it and a regression should say which one came back."""
        earth = {source.name for source in attribution.on_the_page(bodies.EARTH)}
        mars = {source.name for source in attribution.on_the_page(bodies.MARS)}
        with subtests.test("SCAR ADD"):
            assert attribution.SOURCES["addrock"].name in earth
        with subtests.test("IAU gazetteer"):
            assert attribution.SOURCES["mars_nomenclature"].name in mars

    def test_worldcover_is_credited_in_the_raster_archives_and_not_only_on_the_page(self, subtests):
        """It reaches them through the WATERMASK, not the snow mask.

        The standing brief says the tiles replaced WorldCover with NSIDC-0791 plus RGI, and that is
        about snow. OpenTopography serves the withheld GLO-30 tiles without a WBM, so
        `fuse/build_void_wbm.py` builds one from WorldCover class 80 and `build_mosaics.sh` globs it
        into the mosaic `fuse_heightfield` reads. CC-BY, so both raster cuts owe it a notice.
        """
        worldcover = attribution.SOURCES["worldcover"]
        with subtests.test("on the page"):
            assert worldcover in attribution.on_the_page(bodies.EARTH)
        for layer in ("relief", "terrain"):
            with subtests.test(f"in earth/{layer}"):
                assert worldcover.notice in attribution.for_archive(bodies.EARTH, layer)
        with subtests.test("not in the vector cut, which is geometry"):
            assert worldcover.notice not in attribution.for_archive(bodies.EARTH, "vector")

    def test_no_card_is_listed_twice(self, subtests):
        for body in bodies.BODIES.values():
            names = [source.name for source in attribution.on_the_page(body)]
            with subtests.test(body.name):
                assert len(names) == len(set(names))


class TestWhatAnArchiveSaysItIs:
    """A downloaded archive is otherwise anonymous. `name` reads `terrella-relief` on a raster cut
    and `countries` on a vector one, and no key in the blob says which planet the tiles are of.

    Authored notes are NOT this. `ARCHIVED[].note` in `tileAddress.ts` says what one cut changed
    against the one before it, which is a fact about a pair rather than about a file, and lives
    where it can still be corrected after the bytes are published.
    """

    def test_every_archive_gets_one(self, subtests):
        for body in bodies.BODIES.values():
            for layer in attribution.ARCHIVE_LAYERS:
                with subtests.test(f"{body.name}/{layer}"):
                    assert attribution.describe(body, layer).strip()

    def test_it_names_the_body(self, subtests):
        for body in bodies.BODIES.values():
            for layer in attribution.ARCHIVE_LAYERS:
                with subtests.test(f"{body.name}/{layer}"):
                    assert body.name.title() in attribution.describe(body, layer)

    def test_it_restates_nothing_the_blob_already_carries(self, subtests):
        """`minzoom`, `maxzoom` and `format` are their own keys in the same metadata. A description
        repeating them is a second copy that can disagree with the one a reader parses."""
        for body in bodies.BODIES.values():
            for layer in attribution.ARCHIVE_LAYERS:
                with subtests.test(f"{body.name}/{layer}"):
                    assert not re.search(r"z\d|webp|png|jpe?g|pbf|mvt",
                                         attribution.describe(body, layer), re.IGNORECASE)

    def test_the_three_pyramids_do_not_share_one_description(self):
        """The vacuity control, on `for_archive`'s reasoning: a function returning one constant
        would satisfy every positive assertion above."""
        composed = {attribution.describe(bodies.EARTH, layer)
                    for layer in attribution.ARCHIVE_LAYERS}
        assert len(composed) == len(attribution.ARCHIVE_LAYERS)

    def test_the_two_bodies_do_not_share_one_description(self):
        assert attribution.describe(bodies.EARTH, "relief") != \
               attribution.describe(bodies.MARS, "relief")

    def test_an_unknown_layer_raises_rather_than_describing_something(self):
        with pytest.raises(ValueError, match="not an archive layer"):
            attribution.describe(bodies.EARTH, "")


class TestTheCommittedJsonIsInStep:
    """The site imports a generated file, so the file can go stale against the module it came from.
    Same hazard `tileTokens.json` carries, and the same answer: regenerate and compare."""

    def test_the_generated_file_matches_the_registry(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "gen_attributions", REPO_ROOT / "web/scripts/gen_attributions.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert json.loads(GENERATED_JSON.read_text(encoding="utf-8")) == module.payload(), (
            "web/src/data/attributions.json is stale. Regenerate it:\n"
            "  cd web && ../.venv/bin/python scripts/gen_attributions.py "
            "--out src/data/attributions.json"
        )

    def test_the_page_form_carries_the_notice_it_is_built_from(self, subtests):
        """The card may add a sentence; it may not reword the citation, which is the half a licence
        can require."""
        for key, source in attribution.SOURCES.items():
            with subtests.test(key):
                assert source.notice in source.page_attribution()
