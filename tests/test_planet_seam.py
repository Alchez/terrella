"""The planet seam: a producer states what it emitted, and absence stops being a statement.

WHAT IS ACTUALLY UNDER TEST. Not "does a JSON file round-trip" — that would pass with the module
deleted and a dict in its place. The property is that the three questions downstream stages ask
have three DIFFERENT answers, where a filesystem check collapses them into one:

  * "this planet has no ocean mask"        -> a declaration that omits it
  * "the producer has not run"             -> no declaration at all, and every consumer refuses
  * "the producer ran and crashed partway" -> also no declaration, because it is written LAST

Every test below is aimed at one of those three, or at the freshness consequence that follows from
them: a raster that goes away scores `newest_mtime` 0.0, so it stops being a dependency at the
same moment it stops being an input, and the composite painted with it reads fresh forever.
"""

import dataclasses
import json

import pytest

from pipeline import bodies, paths, planet_seam


def _body(name: str, layers: frozenset[str] = frozenset()) -> bodies.Body:
    """A synthetic body with its own directory, so a test never touches a real planet's store."""
    return dataclasses.replace(bodies.EARTH, name=name, path_prefix=name, surface_layers=layers)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Relocate the data store, so `declare` writes under tmp_path and nothing real is read."""
    monkeypatch.setattr(paths, "DATA", tmp_path)
    return tmp_path


def _emit(body: bodies.Body, *rasters: str) -> None:
    """Put stand-in VRTs on disk for `rasters` — `declare` checks presence, never contents."""
    planet_seam.planet_dir(body).mkdir(parents=True, exist_ok=True)
    for raster in rasters:
        planet_seam.vrt_path(body, raster).write_text("<VRTDataset/>")


class TestTheVocabulary:
    def test_the_three_rasters_are_the_ones_the_pipeline_shades(self) -> None:
        assert planet_seam.PLANET_RASTERS == ("heightfield", "oceanmask", "watermask")
        assert planet_seam.KNOWN_RASTERS == frozenset(planet_seam.PLANET_RASTERS)

    def test_an_unknown_raster_raises_and_names_the_ones_that_exist(self) -> None:
        """A typo must not read as an absence — that is the whole failure mode this module closes."""
        with pytest.raises(ValueError, match="oceanmsak"):
            planet_seam.vrt_path(bodies.EARTH, "oceanmsak")

    def test_the_raster_vocabulary_and_the_surface_layer_vocabulary_do_not_overlap(self) -> None:
        """Two vocabularies, two words. `layers_off` and `rasters_off` are different switches, and a
        name in both would let a reader believe one guard covers the other."""
        assert not planet_seam.KNOWN_RASTERS & bodies.SURFACE_LAYERS


class TestTheDeclarationIsTheAnswer:
    def test_a_body_that_never_ran_raises_rather_than_reading_as_a_planet_with_no_masks(
            self, store) -> None:
        """THE CENTRAL PROPERTY. An empty return here would be a statement about the planet; the
        truth is a statement about the pipeline, so the two cannot share a value."""
        with pytest.raises(FileNotFoundError, match="planet stage has not finished"):
            planet_seam.declared(_body("neverran"))

    def test_the_missing_declaration_names_the_command_that_writes_it(self, store) -> None:
        with pytest.raises(FileNotFoundError, match="fuse_planet --build-vrts"):
            planet_seam.declared(_body("neverran"))

    def test_a_full_planet_round_trips(self, store) -> None:
        body = _body("full", bodies.EARTH.surface_layers)
        _emit(body, *planet_seam.PLANET_RASTERS)
        planet_seam.declare(body, planet_seam.PLANET_RASTERS)
        assert planet_seam.declared(body) == planet_seam.KNOWN_RASTERS

    def test_a_body_with_no_masks_declares_that_and_is_believed(self, store) -> None:
        body = _body("bare")
        _emit(body, "heightfield")
        planet_seam.declare(body, ["heightfield"])
        assert planet_seam.declared(body) == frozenset({"heightfield"})

    def test_the_declaration_is_body_scoped_by_path(self, store) -> None:
        """Two bodies are two files, so neither can answer for the other — the same reason the
        freshness sidecars carry no body field."""
        assert (planet_seam.declaration_path(_body("one"))
                != planet_seam.declaration_path(_body("two")))


class TestTheDeclarationCannotOverstate:
    def test_declaring_a_raster_that_is_not_on_disk_is_refused(self, store) -> None:
        """A declaration is only worth trusting about what is MISSING if it can be trusted about
        what is present."""
        body = _body("liar")
        _emit(body, "heightfield")
        with pytest.raises(FileNotFoundError, match="not on disk"):
            planet_seam.declare(body, planet_seam.PLANET_RASTERS)

    def test_a_refused_declaration_leaves_no_file_behind(self, store) -> None:
        """Half a declaration is worse than none: its presence is the completion stamp."""
        body = _body("liar")
        _emit(body, "heightfield")
        with pytest.raises(FileNotFoundError):
            planet_seam.declare(body, planet_seam.PLANET_RASTERS)
        assert not planet_seam.declaration_path(body).exists()

    def test_a_planet_with_no_heightfield_is_not_a_partial_planet(self, store) -> None:
        body = _body("nofloor")
        _emit(body, "oceanmask")
        with pytest.raises(ValueError, match="must emit a heightfield"):
            planet_seam.declare(body, ["oceanmask"])

    def test_an_unknown_raster_in_a_declaration_on_disk_is_refused_on_read(self, store) -> None:
        """Hand-edited or written by an older producer — either way it must not pass silently."""
        body = _body("stale")
        _emit(body, "heightfield")
        planet_seam.declaration_path(body).write_text(
            json.dumps({"rasters": ["heightfield", "bathymetry"]}))
        with pytest.raises(ValueError, match="bathymetry"):
            planet_seam.declared(body)


class TestCoherenceWithTheBodysOwnLayers:
    def test_lake_depth_without_a_watermask_is_refused(self, store) -> None:
        """`lakes_only` zeroes depth off watermask class 2, so there is nothing to zero against."""
        body = _body("lakey", frozenset({"lake_depth"}))
        _emit(body, "heightfield")
        with pytest.raises(ValueError, match="lake_depth"):
            planet_seam.declare(body, ["heightfield"])

    def test_sea_ice_without_an_ocean_mask_is_refused(self, store) -> None:
        """`shade.composite` gates ice on `ocean`, so it would cost a warp and reach no pixel."""
        body = _body("icy", frozenset({"sea_ice"}))
        _emit(body, "heightfield")
        with pytest.raises(ValueError, match="sea_ice"):
            planet_seam.declare(body, ["heightfield"])

    def test_coherence_is_rechecked_on_READ_not_only_on_write(self, store) -> None:
        """The two facts have different lifetimes: the declaration is written once, and the registry
        can gain a layer months later. That edit must fail against the file already on disk."""
        body = _body("later")
        _emit(body, "heightfield")
        planet_seam.declare(body, ["heightfield"])
        grown = dataclasses.replace(body, surface_layers=frozenset({"lake_depth"}))
        with pytest.raises(ValueError, match="watermask"):
            planet_seam.declared(grown)

    def test_a_layer_whose_mask_is_present_is_coherent(self, store) -> None:
        body = _body("ok", frozenset({"lake_depth", "sea_ice"}))
        _emit(body, *planet_seam.PLANET_RASTERS)
        planet_seam.declare(body, planet_seam.PLANET_RASTERS)
        assert planet_seam.declared(body) == planet_seam.KNOWN_RASTERS


class TestRastersOff:
    def test_a_full_planet_records_nothing(self) -> None:
        """Earth's list must stay empty, or the conditional record writes a key into a recipe that
        has never had one and restages a 46 GB composite to reproduce identical pixels."""
        assert planet_seam.rasters_off(planet_seam.KNOWN_RASTERS) == []

    def test_the_missing_ones_are_named_and_sorted(self) -> None:
        assert planet_seam.rasters_off(frozenset({"heightfield"})) == ["oceanmask", "watermask"]

    def test_it_names_what_is_OFF_never_what_is_ON(self) -> None:
        """The asymmetry is the whole idiom: the ON direction is already carried by mtimes, because
        a raster that appears gets warped and the composite's dependency list sees it. The OFF
        direction is the silent one — the stale warp stays on disk and nothing moves."""
        assert "heightfield" not in planet_seam.rasters_off(frozenset({"heightfield"}))
