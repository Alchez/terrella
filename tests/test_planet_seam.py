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
import os
import pathlib
import subprocess

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from pipeline import bodies, layers, paths, planet_seam


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
        assert not planet_seam.KNOWN_RASTERS & layers.SURFACE_LAYERS


class TestTheDeclarationIsTheAnswer:
    def test_a_body_that_never_ran_raises_rather_than_reading_as_a_planet_with_no_masks(
            self, store) -> None:
        """THE CENTRAL PROPERTY. An empty return here would be a statement about the planet; the
        truth is a statement about the pipeline, so the two cannot share a value."""
        with pytest.raises(FileNotFoundError, match="planet stage has not finished"):
            planet_seam.declared(_body("neverran"))

    def test_the_missing_declaration_names_the_command_that_writes_it(self, store) -> None:
        """Per body, because the producers genuinely differ — Earth fuses 648 cells, Mars relabels
        one file — so a shared message would send half its readers to the wrong tier."""
        earth = dataclasses.replace(bodies.EARTH, path_prefix="neverran")
        with pytest.raises(FileNotFoundError, match="fuse_planet --build-vrts"):
            planet_seam.declared(earth)
        mars = dataclasses.replace(bodies.MARS, path_prefix="neverran-either")
        with pytest.raises(FileNotFoundError, match="relabel_mars"):
            planet_seam.declared(mars)

    def test_every_registered_body_has_a_producer_command(self, subtests) -> None:
        """A third planet must not inherit Earth's command by omission — the same reasoning that
        forbids defaults on `Body` fields, applied to the sentence a stuck reader will act on."""
        for name in sorted(bodies.BODIES):
            with subtests.test(name):
                assert name in planet_seam.PRODUCER_COMMANDS

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


def _cell(chunks_dir, name):
    """One fused cell: a real 1x1 GTiff that `gdalbuildvrt` can actually index."""
    outdir = chunks_dir / name
    outdir.mkdir(parents=True, exist_ok=True)
    transform = from_bounds(0.0, 0.0, 10.0, 10.0, 1, 1)  # pyright: ignore[reportCallIssue] — rasterio untyped
    with rasterio.open(outdir / "heightfield_10s.tif", "w", driver="GTiff", width=1, height=1,
                       count=1, dtype="uint8", crs="EPSG:4326", transform=transform) as dataset:
        dataset.write(np.zeros((1, 1), dtype="uint8"), 1)
    return outdir


def _gdalbuildvrt(sources):
    """The build callback Earth's producer passes — a real `gdalbuildvrt`, not a stub. The whole
    claim under test is that GDAL's own output is reproducible, so stubbing it would test nothing."""
    def build(target):
        subprocess.run(["gdalbuildvrt", "-overwrite", str(target), *map(str, sources)],
                       check=True, capture_output=True)
    return build


class TestWriteVrtIfChanged:
    """Re-indexing a planet must be free when nothing moved.

    NOT AN OPTIMISATION. Every 3857 warp downstream is gated on the VRT's mtime, so an unconditional
    overwrite restages the whole 46 GB planet — a 46 GB re-warp, an 8:28 hillshade, a 53.8 min
    composite and a 3:44 cut — to reproduce pixels that were already correct. Re-indexing is the
    natural thing to do after touching a producer, so that cost sat one command away.
    """

    def test_an_unchanged_source_set_leaves_the_file_untouched(self, tmp_path):
        """Backdated on purpose: a rewrite would stamp `now`, so an unmoved mtime is proof the file
        was never replaced — whatever the filesystem's timestamp granularity."""
        _cell(tmp_path / "chunks", "e000_n00")
        vrt = tmp_path / "planet_heightfield.vrt"
        build = _gdalbuildvrt(sorted((tmp_path / "chunks").glob("*/heightfield_10s.tif")))
        assert planet_seam.write_vrt_if_changed(vrt, build) is True
        os.utime(vrt, (0, 0))
        before = vrt.read_bytes()
        assert planet_seam.write_vrt_if_changed(vrt, build) is False
        assert vrt.stat().st_mtime == 0
        assert vrt.read_bytes() == before

    def test_a_changed_source_set_replaces_the_file(self, tmp_path):
        chunks = tmp_path / "chunks"
        _cell(chunks, "e000_n00")
        vrt = tmp_path / "planet_heightfield.vrt"
        planet_seam.write_vrt_if_changed(
            vrt, _gdalbuildvrt(sorted(chunks.glob("*/heightfield_10s.tif"))))
        os.utime(vrt, (0, 0))
        _cell(chunks, "e010_n00")
        assert planet_seam.write_vrt_if_changed(
            vrt, _gdalbuildvrt(sorted(chunks.glob("*/heightfield_10s.tif")))) is True
        assert vrt.stat().st_mtime > 0

    def test_the_scratch_target_never_survives(self, tmp_path):
        """A leftover `.vrt.new` beside the real one is a second, unreferenced index of the planet."""
        _cell(tmp_path / "chunks", "e000_n00")
        vrt = tmp_path / "planet_heightfield.vrt"
        build = _gdalbuildvrt(sorted((tmp_path / "chunks").glob("*/heightfield_10s.tif")))
        planet_seam.write_vrt_if_changed(vrt, build)
        planet_seam.write_vrt_if_changed(vrt, build)
        assert list(tmp_path.glob("*.new")) == []

    def test_the_scratch_target_shares_the_vrts_directory(self, tmp_path):
        """The build callback records the path it is handed, which is the only way to see where the
        scratch file was actually written."""
        seen: list[pathlib.Path] = []
        vrt = tmp_path / "nested" / "planet_heightfield.vrt"
        _cell(tmp_path / "chunks", "e000_n00")
        sources = sorted((tmp_path / "chunks").glob("*/heightfield_10s.tif"))

        def build(target):
            seen.append(target)
            _gdalbuildvrt(sources)(target)

        planet_seam.write_vrt_if_changed(vrt, build)
        assert seen[0].parent == vrt.parent

    def test_a_vrt_built_in_another_directory_would_never_compare_equal(self, tmp_path):
        """WHY that constraint exists, demonstrated rather than asserted. GDAL writes source paths
        RELATIVE to the VRT, so the same sources indexed from two directories produce different
        bytes — and a scratch file built anywhere else would fail the content comparison on every
        run, replacing the file each time and restaging the planet behind it."""
        planet = tmp_path / "planet"
        _cell(planet / "chunks", "e000_n00")
        sources = sorted((planet / "chunks").glob("*/heightfield_10s.tif"))
        beside, elsewhere = planet / "index.vrt", tmp_path / "index.vrt"
        for target in (beside, elsewhere):
            _gdalbuildvrt(sources)(target)
        assert beside.read_bytes() != elsewhere.read_bytes()
        assert 'relativeToVRT="1"' in beside.read_text(), (
            "the production layout keeps chunks under the VRT, which is what makes paths relative")
