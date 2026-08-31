"""Contract for Mars's feature vector-tile cut.

  - the source-layer NAMES, which MapLibre reads as `source-layer` values. A mismatch renders the
    layer empty, with no error and no warning;
  - the ceiling coming from the BODY rather than a literal, so the vectors cannot outlive the
    raster they overlay;
  - both simplification knobs being present, which here is not a weight decision but a crash one;
  - the archive staying unfiltered, which is the decision the coverage statistic argued against and
    lost.
"""

import dataclasses
import json
import os
import time

import pytest

from pipeline import bodies, paths
from pipeline.compose import features_geojson, vector_cut, vector_layers
from pipeline.compose import features_pmtiles as cut


class TestSourceLayerNames:
    def test_names_are_body_neutral_and_distinct(self, subtests):
        """`feature_*` rather than `crater_*`: a third of the catalogue is not a crater, and the
        line layer holds valles and rupes that are not areal at all."""
        for name, expected in (
            (cut.FILL_LAYER, "feature_fill"),
            (cut.OUTLINE_LAYER, "feature_outline"),
            (cut.LINE_LAYER, "feature_line"),
            (cut.LABEL_LAYER, "feature_label"),
        ):
            with subtests.test(layer=expected):
                assert name == expected
        assert len(set(cut.sources())) == 4


class TestTheCeilingComesFromTheBody:
    def test_max_zoom_is_the_body_field_not_a_literal(self):
        """The one thing this commit was asked to keep single-homed. A literal here would let the
        vector pyramid and the relief pyramid drift with nothing going red until someone compared
        tiles by eye."""
        assert cut.MAX_ZOOM == bodies.MARS.tile_max_zoom

    def test_it_is_not_earths(self):
        """The negative instance, and it is the whole reason the field is read: on the day Mars was
        cut to z7 while Earth stayed at z8, a copied constant would have passed every other test
        here. Mars's own ceiling is what makes this assertion falsifiable rather than decorative."""
        assert cut.MAX_ZOOM != bodies.EARTH.tile_max_zoom

    def test_the_floor_is_the_whole_globe(self):
        assert cut.MIN_ZOOM == 0


class TestSimplificationIsRequiredNotPreferred:
    def test_both_knobs_reach_the_command(self, subtests):
        command = " ".join(vector_cut.pmtiles_command(
            cut.CUT, vector_cut.staged(cut.CUT), vector_cut.out(cut.CUT)))
        for label, expected in (
            ("simplification", f"SIMPLIFICATION={cut.SIMPLIFICATION}"),
            ("top-zoom simplification",
             f"SIMPLIFICATION_MAX_ZOOM={cut.SIMPLIFICATION_MAX_ZOOM}"),
        ):
            with subtests.test(option=label):
                assert expected in command

    def test_neither_knob_is_zero(self):
        """GDAL 3.12.2's MVT writer SEGFAULTS on the gazetteer polygons when simplification is
        absent or zero — isolated against Earth's countries, which cut clean through the same code
        path with none. So on this body a zero is not a gentler setting, it is exit 139."""
        assert cut.SIMPLIFICATION > 0
        assert cut.SIMPLIFICATION_MAX_ZOOM > 0

    def test_top_zoom_simplification_is_gentler_than_the_rest(self):
        """The whole reason there are two knobs, and measured on this catalogue: z7 came out
        byte-identical across every SIMPLIFICATION arm, so overview weight is tunable without
        touching the zoom the outline is judged at."""
        assert cut.SIMPLIFICATION_MAX_ZOOM < cut.SIMPLIFICATION

    def test_buffer_is_zero_because_the_wash_double_paints(self):
        """A vector source cannot make this choice at runtime, so losing it here is unrecoverable
        in the browser."""
        assert cut.BUFFER == 0


class TestTheArchiveIsUnfiltered:
    def test_no_diameter_cutoff_reaches_the_command(self):
        """THE DECISION THE COVERAGE STATISTIC LOST. Ranking by diameter and keeping the top 200
        carries 99.2% of the union coverage, but that metric is area-weighted, so rank 200 is a
        394 km floor that deletes Gale and Jezero. Declutter is a runtime filter on `diameter`,
        which can always narrow; an archive cannot widen without a re-cut."""
        command = " ".join(vector_cut.pmtiles_command(
            cut.CUT, vector_cut.staged(cut.CUT), vector_cut.out(cut.CUT)))
        assert "-where" not in command
        assert "diameter" not in command

    def test_every_layer_is_cut_from_a_whole_catalogue_file(self, subtests):
        """The filter cannot hide one step upstream either — each staged layer is a file the fold
        wrote for the whole catalogue, not a subset derived here."""
        expected = {
            cut.FILL_LAYER: features_geojson.polygons(),
            cut.OUTLINE_LAYER: cut.outlines_path(),
            cut.LINE_LAYER: features_geojson.lines(),
            cut.LABEL_LAYER: features_geojson.labels(),
        }
        for layer, path in expected.items():
            with subtests.test(layer=layer):
                assert cut.sources()[layer] == path


class TestStaging:
    def test_the_first_layer_creates_and_the_rest_append(self, subtests):
        """Four layers, one dataset — the PMTiles driver cannot append to an archive it wrote."""
        layers = list(cut.sources())
        for index, layer in enumerate(layers):
            command = vector_layers.stage_command(
                cut.sources()[layer], vector_cut.staged(cut.CUT), layer, update=index > 0)
            with subtests.test(layer=layer):
                assert ("-update" in command) == (index > 0)

    def test_the_outline_layer_is_derived_rather_than_acquired(self):
        """It is the one source this module owns; the other three are the fold's outputs. It has to
        land beside them, or the cut would stage a stale outline against fresh polygons from a
        different directory and neither file's mtime would say so."""
        assert cut.outlines_path().parent == features_geojson.out_dir()
        assert cut.outlines_path().name not in {path.name for path in
                                         (features_geojson.polygons(), features_geojson.lines(),
                                          features_geojson.labels())}


class TestRecipe:
    def test_records_every_setting_that_changes_the_bytes(self, subtests):
        recorded = vector_cut.recipe(cut.CUT)
        for key in ("layers", "min_zoom", "max_zoom", "simplification",
                    "simplification_max_zoom", "buffer", "extent"):
            with subtests.test(key=key):
                assert key in recorded

    def test_is_json_serialisable(self):
        recorded = vector_cut.recipe(cut.CUT)
        assert json.loads(json.dumps(recorded)) == recorded

    def test_freshness_notices_a_settings_change(self):
        """A re-cut under different settings leaves an archive NEWER than its sources, so mtime
        alone would call it fresh."""
        drifted = dict(vector_cut.recipe(cut.CUT))
        drifted["simplification"] = cut.SIMPLIFICATION + 1
        assert drifted != vector_cut.recipe(cut.CUT)

    def test_the_recorded_layers_are_the_staged_layers_in_staging_order(self):
        """The sidecar is a producer's claim about what it emitted, and ORDER is part of the claim:
        the first layer creates the GeoPackage and the rest append to it.

        Spelled out rather than compared against `sources()`, which is what builds the recipe — that
        comparison reduces to `list(sources()) == list(sources())` and passes whatever either says.
        """
        assert vector_cut.recipe(cut.CUT)["layers"] == [
            "feature_fill", "feature_outline", "feature_line", "feature_label"]


class TestDerivationFreshness:
    """Mars's half of the guard whose absence let Earth's antimeridian closures survive their fix.

    THIS BODY ESCAPED THE BUG BY ORDERING, WHICH IS NOT A PROPERTY. Its outlines happened to be
    derived after the seam rule landed, so nothing here was ever observed wrong — the next change
    to `vector_layers` would have been the one that skipped. A second instance of the same gate is
    the point: the first passed by construction. See `test_countries_pmtiles.TestDerivationFreshness`.
    """

    @staticmethod
    def _store(tmp_path, monkeypatch):
        """The same shape as Earth's: a `VectorCut` that names every path, and `paths.DATA` for
        the three the driver derives from the body."""
        features = tmp_path / "work/mars/features"
        features.mkdir(parents=True)
        (tmp_path / "work/mars/planet_vector").mkdir(parents=True)
        outlines = features / "feature_outlines.geojson"
        stamp = features / "feature_outlines_params.json"
        archive = tmp_path / "work/mars/planet_vector/vector.pmtiles"
        sources = {layer: features / f"{layer}.geojson" for layer in cut.sources()}
        sources[cut.OUTLINE_LAYER] = outlines
        monkeypatch.setattr(paths, "DATA", tmp_path)
        monkeypatch.setattr(cut, "CUT", dataclasses.replace(
            cut.CUT,
            sources=lambda: sources,
            derived_from=lambda: sources[cut.FILL_LAYER],
            derivation=lambda: {outlines: {"type": "FeatureCollection", "features": []}},
            derivation_stamp=lambda: stamp,
        ))
        recipe = vector_cut.recipe_path(cut.CUT)
        for path in (*sources.values(), archive):
            path.write_text("x", encoding="utf-8")
        stamp.write_text(json.dumps(vector_layers.seam_recipe()), encoding="utf-8")
        recipe.write_text(json.dumps(vector_cut.recipe(cut.CUT)), encoding="utf-8")
        now = time.time()
        for offset, path in enumerate((*sources.values(), stamp, recipe)):
            os.utime(path, (now - 100 + offset, now - 100 + offset))
        os.utime(archive, (now, now))
        return stamp

    def test_the_fixture_reports_fresh_before_anything_is_perturbed(self, tmp_path, monkeypatch):
        """The control, without which every assertion below passes on a broken fixture."""
        self._store(tmp_path, monkeypatch)
        assert vector_cut.is_fresh(cut.CUT)

    def test_a_seam_knob_change_makes_MARS_ARCHIVE_stale_though_no_mtime_moved(
            self, tmp_path, monkeypatch):
        """Archive newest, archive recipe re-stamped as a real cut would leave it, and the only
        stale thing is the geometry it was cut from."""
        self._store(tmp_path, monkeypatch)
        monkeypatch.setattr(vector_layers, "SEAM_BAND_DEGREES",
                            vector_layers.SEAM_BAND_DEGREES + 1.0)
        recipe = vector_cut.recipe_path(cut.CUT)
        recipe.write_text(json.dumps(vector_cut.recipe(cut.CUT)), encoding="utf-8")
        older = vector_cut.out(cut.CUT).stat().st_mtime - 1
        os.utime(recipe, (older, older))
        assert (json.loads(recipe.read_text())
                == vector_cut.recipe(cut.CUT)), "recipe half must PASS"
        assert not vector_cut.is_fresh(cut.CUT)

    def test_MARS_derivation_that_was_never_stamped_is_not_believed(self, tmp_path, monkeypatch):
        """The state every store was in before this guard existed."""
        stamp = self._store(tmp_path, monkeypatch)
        stamp.unlink()
        assert not vector_cut.is_fresh(cut.CUT)

    @pytest.mark.parametrize("rubbish", ["{not json", "5", "[]", "null", ""])
    def test_an_UNREADABLE_stamp_is_stale_rather_than_an_exception(self, rubbish, tmp_path,
                                                                    monkeypatch):
        """Mars's copy of Earth's guard, and it had Earth's hole: absence handled, garbage not."""
        stamp = self._store(tmp_path, monkeypatch)
        stamp.write_text(rubbish, encoding="utf-8")
        assert not vector_cut.is_fresh(cut.CUT)

    @pytest.mark.parametrize("rubbish", ["{not json", "5", "[]", "null", ""])
    def test_an_UNREADABLE_archive_recipe_is_stale_rather_than_an_exception(
            self, rubbish, tmp_path, monkeypatch):
        self._store(tmp_path, monkeypatch)
        vector_cut.recipe_path(cut.CUT).write_text(rubbish, encoding="utf-8")
        assert not vector_cut.is_fresh(cut.CUT)
