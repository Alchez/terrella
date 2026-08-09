"""Contract for the vector-tile machinery both bodies' pyramids share.

This file inherited the GREENLAND WALK when a second body made the walk worth owning. The cases
below are its only guard — there is no TypeScript twin left to disagree with it, and the two callers
now go through one copy, so a regression here breaks both planets at once rather than one.

The other two things pinned here fail silently rather than loudly: `ogr2ogr`'s destination-before-
source argument order, which reads backwards and has been got wrong before; and the conversion
carrying its simplification knobs at all, which on Earth measured a 4.3x weight regression when
absent and on Mars is the difference between an archive and a segfault.
"""

from pathlib import Path

import pytest

from pipeline.compose import countries_pmtiles, features_pmtiles, vector_layers

# Two polygons in one part each, plus a hole, plus the shape that caused the bug.
SQUARE = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
HOLE = [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5], [0.5, 0.5]]
OTHER = [[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]]


def feature(properties, geometry):
    return {"type": "Feature", "properties": properties, "geometry": geometry}


class TestPolygonPartsOf:
    """THE GREENLAND WALK, in its owning module."""

    def test_a_polygon_is_one_part(self):
        assert vector_layers.polygon_parts_of(
            {"type": "Polygon", "coordinates": [SQUARE, HOLE]}
        ) == [[SQUARE, HOLE]]

    def test_a_multipolygon_keeps_every_part(self):
        parts = vector_layers.polygon_parts_of(
            {"type": "MultiPolygon", "coordinates": [[SQUARE], [OTHER]]}
        )
        assert parts == [[SQUARE], [OTHER]]

    def test_a_geometrycollection_is_flattened_and_its_lines_dropped(self):
        """THE GREENLAND CASE. Natural Earth ships it as a collection of polygons plus one stray
        LineString, and the walks this replaced returned nothing for it — so an in-scope country
        had a fill wash and a click but no hover outline and no hit targets, live, unnoticed.

        Mars reaches this branch from the other direction: its gazetteer ships no collections, but
        folding the antimeridian with `RFC7946=YES` instead of `-wrapdateline` MAKES two of them,
        which is why `features_geojson.assert_folded` refuses that output rather than relying on
        this walk to rescue it.
        """
        parts = vector_layers.polygon_parts_of({
            "type": "GeometryCollection",
            "geometries": [
                {"type": "MultiPolygon", "coordinates": [[SQUARE]]},
                {"type": "Polygon", "coordinates": [OTHER]},
                {"type": "LineString", "coordinates": SQUARE},
            ],
        })
        assert parts == [[SQUARE], [OTHER]]

    @pytest.mark.parametrize("kind", ["LineString", "Point", "MultiLineString"])
    def test_non_polygonal_geometry_yields_nothing(self, kind):
        assert vector_layers.polygon_parts_of({"type": kind, "coordinates": []}) == []


class TestCarried:
    def test_the_first_key_is_the_identity_and_a_feature_without_it_is_dropped(self, subtests):
        """A feature with no name cannot be hovered as one thing, labelled, or joined to anything.
        Carrying it anonymously would put an unreachable shape in the layer instead of leaving a
        gap someone can see."""
        for label, properties in (
            ("absent", {"type": "Crater, craters"}),
            ("empty", {"name": "", "type": "Crater, craters"}),
            ("not a string", {"name": 7}),
        ):
            with subtests.test(identity=label):
                assert vector_layers.carried(properties, ("name", "type")) is None

    def test_payload_keys_are_optional_where_the_identity_is_not(self):
        """A missing `origin` is a thinner card; a missing name is a broken layer."""
        assert vector_layers.carried({"name": "Gale"}, ("name", "origin")) == {"name": "Gale"}

    def test_only_the_named_keys_travel(self):
        """Everything carried is paid for in every tile the feature appears in."""
        assert vector_layers.carried(
            {"name": "Gale", "origin": "Walter F. Gale", "approval": 1973}, ("name", "origin")
        ) == {"name": "Gale", "origin": "Walter F. Gale"}


class TestOutlinesFrom:
    def test_outlines_carry_every_ring_including_holes(self):
        collection = {"type": "FeatureCollection", "features": [
            feature({"ADMIN": "Testland"}, {"type": "Polygon", "coordinates": [SQUARE, HOLE]})
        ]}
        out = vector_layers.outlines_from(collection, ("ADMIN",))
        assert out["features"][0]["geometry"] == {
            "type": "MultiLineString", "coordinates": [SQUARE, HOLE]
        }

    def test_a_feature_with_no_polygon_yields_no_outline(self):
        """Not an empty MultiLineString — a feature with nothing to stroke rather than an absent
        one is the shape that renders as an invisible defect."""
        collection = {"type": "FeatureCollection", "features": [
            feature({"ADMIN": "Testland"}, {"type": "LineString", "coordinates": SQUARE})
        ]}
        assert vector_layers.outlines_from(collection, ("ADMIN",))["features"] == []

    def test_a_feature_with_null_geometry_is_skipped_rather_than_raising(self):
        collection = {"type": "FeatureCollection", "features": [
            feature({"ADMIN": "Testland"}, None)
        ]}
        assert vector_layers.outlines_from(collection, ("ADMIN",))["features"] == []

    def test_the_identity_is_carried_so_one_hover_lights_every_part(self):
        collection = {"type": "FeatureCollection", "features": [
            feature({"ADMIN": "Testland"},
                    {"type": "MultiPolygon", "coordinates": [[SQUARE], [OTHER]]})
        ]}
        out = vector_layers.outlines_from(collection, ("ADMIN",))
        assert {f["properties"]["ADMIN"] for f in out["features"]} == {"Testland"}

    def test_mars_carries_more_than_one_property_through_the_same_walk(self):
        """THE SECOND INSTANCE, which is what makes the parameterisation more than a rename: Earth
        carries a single join key and Mars carries the card's whole content, through this code."""
        collection = {"type": "FeatureCollection", "features": [
            feature({"name": "Gale", "type": "Crater, craters", "origin": "Walter F. Gale",
                     "diameter": 154.084},
                    {"type": "Polygon", "coordinates": [SQUARE]})
        ]}
        out = vector_layers.outlines_from(collection, ("name", "type", "origin", "diameter"))
        assert out["features"][0]["properties"] == {
            "name": "Gale", "type": "Crater, craters", "origin": "Walter F. Gale",
            "diameter": 154.084,
        }


class TestStageCommand:
    def test_first_layer_creates_and_the_rest_update(self, subtests):
        """The PMTiles driver cannot append a layer to an archive it already wrote, so every layer
        has to reach ogr2ogr as ONE multi-layer dataset. That is the only reason a GeoPackage
        exists in this pipeline at all."""
        first = vector_layers.stage_command(Path("a.geojson"), Path("s.gpkg"), "one", update=False)
        later = vector_layers.stage_command(Path("b.geojson"), Path("s.gpkg"), "two", update=True)
        with subtests.test(step="create"):
            assert "-update" not in first
        with subtests.test(step="append"):
            assert "-update" in later
        with subtests.test(step="names the layer"):
            assert later[later.index("-nln") + 1] == "two"


class TestPmtilesCommand:
    def test_destination_precedes_source(self):
        """ogr2ogr's argument order, which reads backwards and has been got wrong before."""
        command = vector_layers.pmtiles_command(
            Path("in.gpkg"), Path("out.pmtiles"), name="x", min_zoom=0, max_zoom=8, buffer=0,
            simplification=2.0, simplification_max_zoom=0.5)
        assert command.index("out.pmtiles") < command.index("in.gpkg")

    def test_both_simplification_knobs_are_required(self, subtests):
        """No defaults, and the reason is not tidiness. GDAL simplifies nothing unless told to, and
        that costs Earth 4.3x the tile weight and costs Mars the whole run — its MVT writer
        SEGFAULTS on the gazetteer polygons when the option is absent or zero. A default here would
        make the crash reachable by forgetting rather than by choosing."""
        for missing in ("simplification", "simplification_max_zoom"):
            arguments = {"name": "x", "min_zoom": 0, "max_zoom": 8, "buffer": 0,
                         "simplification": 2.0, "simplification_max_zoom": 0.5}
            del arguments[missing]
            with subtests.test(without=missing), pytest.raises(TypeError):
                vector_layers.pmtiles_command(Path("in.gpkg"), Path("out.pmtiles"), **arguments)

    def test_every_knob_reaches_the_command(self, subtests):
        command = " ".join(vector_layers.pmtiles_command(
            Path("in.gpkg"), Path("out.pmtiles"), name="features", min_zoom=1, max_zoom=7,
            buffer=0, simplification=3.0, simplification_max_zoom=0.25))
        for label, expected in (
            ("format", "-f PMTiles"),
            ("name", "NAME=features"),
            ("min zoom", "MINZOOM=1"),
            ("max zoom", "MAXZOOM=7"),
            ("buffer", "BUFFER=0"),
            ("extent", f"EXTENT={vector_layers.EXTENT}"),
            ("simplification", "SIMPLIFICATION=3.0"),
            ("top-zoom simplification", "SIMPLIFICATION_MAX_ZOOM=0.25"),
        ):
            with subtests.test(option=label):
                assert expected in command


class TestBothBodiesGoThroughTheOneOwner:
    """The seam itself, so a future edit that inlines a private copy fails here.

    Nothing else would catch it: a re-inlined walk passes every behavioural test on the day it is
    written, and only drifts later — which is the whole argument for the shared module.
    """

    def test_neither_body_defines_its_own_polygon_walk(self, subtests):
        for module in (countries_pmtiles, features_pmtiles):
            with subtests.test(module=module.__name__):
                source = Path(module.__file__ or "").read_text(encoding="utf-8")
                assert "def polygon_parts_of" not in source
                assert "def outlines_from(collection" not in source

    def test_earth_still_reaches_the_shared_walk(self):
        assert countries_pmtiles.polygon_parts_of is vector_layers.polygon_parts_of
