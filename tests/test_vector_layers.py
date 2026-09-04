"""Contract for the vector-tile machinery both bodies' pyramids share.

This file inherited the GREENLAND WALK when a second body made the walk worth owning. The cases
below are its only guard — there is no TypeScript twin left to disagree with it, and the two callers
now go through one copy, so a regression here breaks both planets at once rather than one.

The other two things pinned here fail silently rather than loudly: `ogr2ogr`'s destination-before-
source argument order, which reads backwards and has been got wrong before; and the conversion
carrying its simplification knobs at all, which on Earth measured a 4.3x weight regression when
absent and on Mars is the difference between an archive and a segfault.
"""

import itertools
from pathlib import Path

import pytest

from pipeline.compose import countries_pmtiles, features_pmtiles, vector_layers

# Two polygons in one part each, plus a hole, plus the shape that caused the bug.
SQUARE = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
HOLE = [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5], [0.5, 0.5]]
OTHER = [[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]]

# A feature cut at the antimeridian: two halves, each closed along the seam between the same two
# latitudes. The closure is at edge index 1 east and index 3 west — deliberately mid-ring, since a
# cut at the ends would never exercise the rejoin.
CUT_EAST = [[170, 10], [180, 10], [180, 30], [170, 30], [170, 10]]
CUT_WEST = [[-180, 30], [-170, 30], [-170, 10], [-180, 10], [-180, 30]]

# The same cut as a publisher that did not snap it: USGS ships Arcadia Planitia pre-split and closes
# each half a fraction off the meridian, at 179.711 and (unfolded) 180.091.
UNSNAPPED_EAST = [[165, 34], [179.711, 34.27], [180, 55.1], [175, 54.6], [165, 34]]
UNSNAPPED_WEST = [[-180, 34.29], [-176, 34.5], [-170, 62], [-179.909, 55.114], [-180, 34.29]]

# Terra Cimmeria: ONE unsplit polygon whose published eastern boundary follows the meridian for 57°
# of latitude. Nothing about its geometry says "artifact" except that nothing answers it.
LONE_MERIDIAN_BOUNDARY = [[100, -16], [179.56, -16], [179.66, -73], [100, -73], [100, -16]]

# Fiji: real coast on both sides of the seam, near it and unmirrored.
COAST_EAST = [[179.1, -16], [179.9, -16], [179.9, -16.5], [179.1, -16.5], [179.1, -16]]
COAST_WEST = [[-179.9, -20], [-179.1, -20], [-179.1, -20.7], [-179.9, -20.7], [-179.9, -20]]


def seam_edges_of(geometry, minimum_span=0.0):
    """Every drawn edge left inside the seam band, as latitude spans — the thing a reader sees."""
    return [abs(end[1] - start[1])
            for line in geometry["coordinates"]
            for start, end in itertools.pairwise(line)
            if min(abs(start[0]), abs(end[0])) >= 179.0 and start[0] * end[0] > 0
            and abs(end[1] - start[1]) >= minimum_span]


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


class TestSeamClosures:
    """The cut a split polygon closes itself along, told apart from a boundary that follows it."""

    def test_both_halves_of_a_cut_are_dropped(self):
        assert vector_layers.seam_closures([CUT_EAST, CUT_WEST]) == {(0, 1), (1, 3)}

    def test_a_lone_meridian_boundary_is_KEPT(self):
        """THE LOAD-BEARING CASE. Terra Cimmeria's published eastern boundary runs 57° down the
        meridian and Terra Sirenum's western one answers it from the other side — but they are two
        FEATURES, so neither has a counterpart within itself. Drop this and the fix deletes real
        boundary from the two largest named regions on the planet to remove a line from a third."""
        assert vector_layers.seam_closures([LONE_MERIDIAN_BOUNDARY]) == set()

    def test_a_cut_the_publisher_did_not_snap_to_the_meridian_is_still_dropped(self):
        """The case an exact-meridian test passes on Earth and fails on Mars."""
        assert vector_layers.seam_closures([UNSNAPPED_EAST, UNSNAPPED_WEST]) == {(0, 1), (1, 3)}

    def test_that_unsnapped_fixture_really_is_off_the_meridian(self):
        """Otherwise the case above proves nothing — it would be the exact case wearing a name."""
        start, end = UNSNAPPED_EAST[1], UNSNAPPED_EAST[2]
        assert min(abs(abs(start[0]) - 180.0), abs(abs(end[0]) - 180.0)) == pytest.approx(0.0)
        assert max(abs(abs(start[0]) - 180.0), abs(abs(end[0]) - 180.0)) > 0.25

    def test_real_coast_on_both_sides_is_kept_when_it_is_not_mirrored(self):
        """Fiji sits on the seam and contributes hundreds of candidate edges; every one is coast."""
        assert vector_layers.seam_closures([COAST_EAST, COAST_WEST]) == set()

    def test_two_degenerate_spans_do_not_twin_each_other(self):
        """Without the span guard, any pair of short opposite-side edges at one latitude matches —
        which is most of a coastline rather than a cut, and the failure is silent deletion."""
        east = [[179.5, 5], [180, 5], [170, 8], [179.5, 5]]
        west = [[-180, 5], [-179.5, 5], [-170, 8], [-180, 5]]
        assert vector_layers.seam_closures([east, west]) == set()

    def test_a_MIRRORED_pair_of_real_edges_is_dropped_and_that_is_the_known_limit(self):
        """THE RULE'S FALSE POSITIVE, pinned rather than left to be discovered. One feature with
        lobes on both sides whose seam-adjacent edges happen to span the same latitudes reads as a
        cut, because that is all a cut looks like. Found by writing a fixture, not in the data —
        neither catalogue contains it, and the alternative discriminators are worse: winding is not
        guaranteed by publishers, and a length or Δlon threshold deletes Terra Cimmeria."""
        east = [[179.5, 5], [179.8, 6], [170, 8], [179.5, 5]]
        west = [[-179.5, 5], [-179.8, 6], [-170, 8], [-179.5, 5]]
        assert vector_layers.seam_closures([east, west]) == {(0, 0), (1, 0)}

    def test_an_edge_ACROSS_the_meridian_is_not_one_along_it(self):
        """An unfolded feature reaching over the seam has a real edge joining the two sides.

        THE SECOND RING IS WHAT MAKES THE SKIP LOAD-BEARING, and the first alone did not. A crossing
        edge admitted as a candidate only becomes a closure by twinning with one on the OTHER side at
        the same latitudes, so a fixture carrying a single seam edge comes back empty whether the
        skip runs or not — the assertion held for want of a partner rather than because of the rule,
        and the mutation that deletes the skip outright sat silent behind it.
        """
        lone = [[179.5, 10], [-179.5, 40], [170, 40], [179.5, 10]]
        assert vector_layers.seam_closures([lone]) == set()

        # The crossing edge (east, 10..40) now has a west-side edge spanning the same latitudes, so
        # admitting it would pair the two and cut a feature that never split.
        with_partner = [[179.5, 10], [-179.5, 40], [-179.6, 10], [179.5, 10]]
        assert vector_layers.seam_closures([with_partner]) == set()


class TestArcsWithout:
    def test_a_ring_with_nothing_dropped_is_returned_whole(self):
        assert vector_layers.arcs_without(SQUARE, set()) == [SQUARE]

    def test_a_cut_mid_ring_REJOINS_the_tail_to_the_head(self):
        """One arc, not two. Removing edge 1 of a closed ring leaves a run that has to wrap through
        the ring's arbitrary start point; two arcs would put a second gap wherever the publisher
        happened to begin, and it would read as a shorter version of the bug being fixed."""
        arcs = vector_layers.arcs_without(CUT_EAST, {1})
        assert arcs == [[[180, 30], [170, 30], [170, 10], [180, 10]]]

    def test_the_arc_ends_on_the_two_seam_vertices(self):
        """The outline should stop AT the meridian from both directions, not short of it."""
        (arc,) = vector_layers.arcs_without(CUT_EAST, {1})
        assert [arc[0][0], arc[-1][0]] == [180, 180]

    def test_two_cuts_in_one_ring_leave_two_arcs(self):
        ring = [[180, 0], [180, 10], [170, 10], [170, 20], [180, 20], [180, 30], [180, 0]]
        assert len(vector_layers.arcs_without(ring, {0, 4})) == 2

    def test_an_unclosed_ring_is_split_where_it_is_cut_and_not_wrapped(self):
        """A publisher habit, like the Greenland collection — wrapping an open line would invent an
        edge between two ends that were never joined."""
        line = [[0, 0], [1, 0], [2, 0], [3, 0]]
        assert vector_layers.arcs_without(line, {1}) == [[[0, 0], [1, 0]], [[2, 0], [3, 0]]]


class TestOutlinesKeepTheSeamClean:
    def test_the_straight_line_down_the_antimeridian_is_gone(self):
        collection = {"type": "FeatureCollection", "features": [
            feature({"name": "Arcadia Planitia"},
                    {"type": "MultiPolygon", "coordinates": [[UNSNAPPED_EAST], [UNSNAPPED_WEST]]})
        ]}
        out = vector_layers.outlines_from(collection, ("name",))
        assert seam_edges_of(out["features"][0]["geometry"], minimum_span=1.0) == []

    def test_the_feature_survives_the_drop_rather_than_disappearing(self):
        """A feature that loses its cut must still be hoverable, tappable and outlined."""
        collection = {"type": "FeatureCollection", "features": [
            feature({"name": "Arcadia Planitia"},
                    {"type": "MultiPolygon", "coordinates": [[UNSNAPPED_EAST], [UNSNAPPED_WEST]]})
        ]}
        out = vector_layers.outlines_from(collection, ("name",))
        assert len(out["features"]) == 1
        assert len(out["features"][0]["geometry"]["coordinates"]) == 2

    def test_a_body_with_a_real_meridian_boundary_keeps_every_degree_of_it(self):
        collection = {"type": "FeatureCollection", "features": [
            feature({"name": "Terra Cimmeria"},
                    {"type": "Polygon", "coordinates": [LONE_MERIDIAN_BOUNDARY]})
        ]}
        out = vector_layers.outlines_from(collection, ("name",))
        assert seam_edges_of(out["features"][0]["geometry"]) == [pytest.approx(57.0)]

    def test_geometry_away_from_the_seam_is_untouched(self):
        """The drop must be invisible to the 1,700 features that never approach the meridian."""
        collection = {"type": "FeatureCollection", "features": [
            feature({"ADMIN": "Testland"}, {"type": "Polygon", "coordinates": [SQUARE, HOLE]})
        ]}
        out = vector_layers.outlines_from(collection, ("ADMIN",))
        assert out["features"][0]["geometry"]["coordinates"] == [SQUARE, HOLE]


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
