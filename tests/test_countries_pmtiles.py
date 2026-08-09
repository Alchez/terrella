"""Contract for the country vector-tile cut.

Three things are pinned here, and each fails silently in production if it drifts:

  - the source-layer NAMES, which MapLibre reads as `source-layer` values. A mismatch renders
    every country layer empty, with no error and no warning;
  - the two SIMPLIFICATION knobs staying separate, which is what lets overview weight be tuned
    without touching the z8 fidelity the hover outline is judged against;
  - the geometry walks — whose cases now live in tests/test_vector_layers.py, because a second body
    cuts a pyramid through the same code. What stays here is what is EARTH's about this cut: the
    join key it carries, the ceiling it is pinned to, and the derivation being unscoped.
"""

import json
import re

from pipeline.compose import countries_pmtiles as cut


class TestSourceLayerNames:
    def test_names_match_the_frontend(self, subtests):
        """The other end of these strings is web/src/lib/countryTiles.ts, which no type reaches."""
        for name, expected in (
            (cut.FILL_LAYER, "country_fill"),
            (cut.OUTLINE_LAYER, "country_outline"),
            (cut.HIT_LAYER, "country_hit"),
        ):
            with subtests.test(layer=expected):
                assert name == expected

    def test_the_three_layers_are_distinct(self):
        assert len({cut.FILL_LAYER, cut.OUTLINE_LAYER, cut.HIT_LAYER}) == 3


class TestConversionCommand:
    def test_destination_precedes_source(self):
        """ogr2ogr's argument order, which reads backwards and has been got wrong before."""
        command = cut.pmtiles_command(cut.STAGED, cut.OUT)
        assert command.index(str(cut.OUT)) < command.index(str(cut.STAGED))

    def test_command_carries_the_contract(self, subtests):
        command = " ".join(cut.pmtiles_command(cut.STAGED, cut.OUT))
        for label, expected in (
            ("format", "-f PMTiles"),
            ("min zoom", f"MINZOOM={cut.MIN_ZOOM}"),
            ("max zoom", f"MAXZOOM={cut.MAX_ZOOM}"),
            ("buffer", "BUFFER=0"),
            ("extent", f"EXTENT={cut.EXTENT}"),
            ("simplification", f"SIMPLIFICATION={cut.SIMPLIFICATION}"),
            ("top-zoom simplification", f"SIMPLIFICATION_MAX_ZOOM={cut.SIMPLIFICATION_MAX_ZOOM}"),
        ):
            with subtests.test(option=label):
                assert expected in command

    def test_buffer_is_zero_because_the_wash_double_paints(self):
        """The runtime GeoJSON source sets `buffer: 0` for the same reason; a vector pyramid can
        only make that choice at cut time, so losing it here is unrecoverable in the browser."""
        assert cut.BUFFER == 0

    def test_top_zoom_simplification_is_gentler_than_the_rest(self):
        """The whole reason there are two knobs. z8 is what the hover outline is judged at, and
        the sweep measured it byte-identical across every SIMPLIFICATION — that property only
        holds while the top-zoom factor stays well below the general one."""
        assert cut.SIMPLIFICATION_MAX_ZOOM < cut.SIMPLIFICATION

    def test_max_zoom_reaches_the_relief_ceiling(self):
        """Vector detail has to reach where the raster does, or the outline it traces outlives it.

        Read out of the frontend's own constant rather than restated, and the regex must MATCH or
        this fails — a `getattr(..., default)` here would have compared 8 against a default of 8
        and passed whether or not the constant still existed.
        """
        source = (cut.ROOT / "web/src/lib/reliefTiles.ts").read_text()
        found = re.search(r"export const RELIEF_MAX_ZOOM = (\d+);", source)
        assert found is not None, "RELIEF_MAX_ZOOM is gone or renamed in web/src/lib/reliefTiles.ts"
        assert cut.MAX_ZOOM == int(found.group(1))


class TestStagingCommand:
    def test_first_layer_creates_and_the_rest_update(self, subtests):
        """The PMTiles driver cannot append a layer to an archive it already wrote, so all three
        have to reach ogr2ogr as ONE multi-layer dataset. That is the only reason a GeoPackage
        exists in this pipeline at all."""
        first = cut.stage_command(cut.SRC, cut.STAGED, cut.FILL_LAYER, update=False)
        later = cut.stage_command(cut.OUTLINES, cut.STAGED, cut.OUTLINE_LAYER, update=True)
        with subtests.test(step="create"):
            assert "-update" not in first
        with subtests.test(step="append"):
            assert "-update" in later
        with subtests.test(step="names the layer"):
            assert later[later.index("-nln") + 1] == cut.OUTLINE_LAYER


# Two polygons, one part each — enough for the per-part questions this file still asks.
SQUARE = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
OTHER = [[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]]


def feature(admin, geometry):
    return {"type": "Feature", "properties": {"ADMIN": admin}, "geometry": geometry}


class TestTheJoinKey:
    def test_only_admin_is_carried(self):
        """The frontend joins these tiles to countries.json by name and reads nothing else off
        them. Every extra property would be paid for in every tile the country appears in."""
        assert cut.CARRIED == ("ADMIN",)


class TestDerivedLayers:
    def test_hit_points_are_one_per_part_at_the_bbox_centre(self):
        collection = {"type": "FeatureCollection", "features": [
            feature("Archipelago", {"type": "MultiPolygon", "coordinates": [[SQUARE], [OTHER]]})
        ]}
        points = cut.hit_points_from(collection)["features"]
        assert [p["geometry"]["coordinates"] for p in points] == [[1.0, 1.0], [11.0, 11.0]]

    def test_admin_is_carried_so_one_hover_lights_the_whole_country(self):
        collection = {"type": "FeatureCollection", "features": [
            feature("Testland", {"type": "MultiPolygon", "coordinates": [[SQUARE], [OTHER]]})
        ]}
        for layer in (cut.outlines_from(collection), cut.hit_points_from(collection)):
            assert {f["properties"]["ADMIN"] for f in layer["features"]} == {"Testland"}

    def test_derivation_is_unscoped(self):
        """The archive carries ALL countries; scope is a runtime layer filter. That is what keeps
        a newly rendered hero from requiring a re-cut, and keeps "which countries are interactive"
        single-homed in the manifest rather than split across a build step and a filter."""
        collection = {"type": "FeatureCollection", "features": [
            feature("Rendered", {"type": "Polygon", "coordinates": [SQUARE]}),
            feature("Unrendered", {"type": "Polygon", "coordinates": [OTHER]}),
        ]}
        assert len(cut.outlines_from(collection)["features"]) == 2


class TestRecipe:
    def test_records_every_setting_that_changes_the_bytes(self, subtests):
        """The archive's name carries none of this. Without a sidecar a SIMPLIFICATION change is
        invisible to every guard and to anyone reading the store."""
        recorded = cut.recipe()
        for key in ("simplification", "simplification_max_zoom", "buffer", "extent",
                    "min_zoom", "max_zoom", "layers"):
            with subtests.test(key=key):
                assert key in recorded

    def test_is_json_serialisable(self):
        assert json.loads(json.dumps(cut.recipe())) == cut.recipe()

    def test_freshness_notices_a_settings_change(self):
        """A re-cut under different settings leaves an archive NEWER than its source, so mtime
        alone would call it fresh. The recipe comparison is the half that catches it."""
        drifted = dict(cut.recipe())
        drifted["simplification"] = cut.SIMPLIFICATION + 1
        assert drifted != cut.recipe()
