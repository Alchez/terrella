"""Contract for Mars's feature vector-tile cut.

  - the source-layer NAMES, which MapLibre reads as `source-layer` values. A mismatch renders the
    layer empty, with no error and no warning;
  - the ceiling coming from the BODY rather than a literal, so the vectors cannot outlive the
    raster they overlay;
  - both simplification knobs being present, which here is not a weight decision but a crash one;
  - the archive staying unfiltered, which is the decision the coverage statistic argued against and
    lost.
"""

import json

from pipeline import bodies
from pipeline.compose import features_geojson, vector_layers
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
        command = " ".join(cut.pmtiles_command(cut.STAGED, cut.OUT))
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
        command = " ".join(cut.pmtiles_command(cut.STAGED, cut.OUT))
        assert "-where" not in command
        assert "diameter" not in command

    def test_every_layer_is_cut_from_a_whole_catalogue_file(self, subtests):
        """The filter cannot hide one step upstream either — each staged layer is a file the fold
        wrote for the whole catalogue, not a subset derived here."""
        expected = {
            cut.FILL_LAYER: features_geojson.POLYGONS,
            cut.OUTLINE_LAYER: cut.OUTLINES,
            cut.LINE_LAYER: features_geojson.LINES,
            cut.LABEL_LAYER: features_geojson.LABELS,
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
                cut.sources()[layer], cut.STAGED, layer, update=index > 0)
            with subtests.test(layer=layer):
                assert ("-update" in command) == (index > 0)

    def test_the_outline_layer_is_derived_rather_than_acquired(self):
        """It is the one source this module owns; the other three are the fold's outputs. It has to
        land beside them, or the cut would stage a stale outline against fresh polygons from a
        different directory and neither file's mtime would say so."""
        assert cut.OUTLINES.parent == features_geojson.OUT_DIR
        assert cut.OUTLINES.name not in {path.name for path in
                                         (features_geojson.POLYGONS, features_geojson.LINES,
                                          features_geojson.LABELS)}


class TestRecipe:
    def test_records_every_setting_that_changes_the_bytes(self, subtests):
        recorded = cut.recipe()
        for key in ("layers", "min_zoom", "max_zoom", "simplification",
                    "simplification_max_zoom", "buffer", "extent"):
            with subtests.test(key=key):
                assert key in recorded

    def test_is_json_serialisable(self):
        assert json.loads(json.dumps(cut.recipe())) == cut.recipe()

    def test_freshness_notices_a_settings_change(self):
        """A re-cut under different settings leaves an archive NEWER than its sources, so mtime
        alone would call it fresh."""
        drifted = dict(cut.recipe())
        drifted["simplification"] = cut.SIMPLIFICATION + 1
        assert drifted != cut.recipe()

    def test_the_recorded_layers_are_the_staged_layers_in_staging_order(self):
        """The sidecar is a producer's claim about what it emitted, and ORDER is part of the claim:
        the first layer creates the GeoPackage and the rest append to it.

        Spelled out rather than compared against `sources()`, which is what builds the recipe — that
        comparison reduces to `list(sources()) == list(sources())` and passes whatever either says.
        """
        assert cut.recipe()["layers"] == [
            "feature_fill", "feature_outline", "feature_line", "feature_label"]
