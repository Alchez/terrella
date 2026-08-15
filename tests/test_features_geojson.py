"""Contract for the gazetteer fold.

Everything pinned here fails QUIETLY if it drifts, which is why it is pinned at all:

  - the SRS being declared rather than transformed. Reprojecting Mars angles through an Earth datum
    produces coordinates that are plausible, wrong, and off by kilometres with no error;
  - the fold flag. `RFC7946=YES` looks like a substitute for `-wrapdateline` — both keep every
    feature and both land inside the window — but it emits GeometryCollections, the container that
    once cost Greenland its entire hover outline;
  - the centres never travelling as properties. A folded geometry carrying an unfolded longitude is
    two conventions in one file, which is the bug this module exists to end;
  - nothing being simplified here, because the tile cut can spend detail reversibly and this cannot.
"""

import json
import os
import time

import pytest

from pipeline.acquire import download_nomenclature
from pipeline.compose import features_geojson as fold


class TestTheSrsIsDeclaredNotTransformed:
    def test_source_and_target_are_the_same_frame(self, subtests):
        """Naming EPSG:4326 on BOTH sides is what makes the pass a relabelling rather than a datum
        shift. The refusal it avoids is `bodies.py`'s to state, not this file's."""
        command = fold.ogr_command(fold.POLYGONS, fold.LINES)
        for flag in ("-s_srs", "-t_srs"):
            with subtests.test(flag=flag):
                assert command[command.index(flag) + 1] == "EPSG:4326"


class TestDeclaringIsOnlyTheCureForAGeographicSource:
    """THE HALF THE FLAGS CANNOT EXPRESS, and the one this file exists to guard.

    `download_sim3292` records it: `-a_srs`/`-s_srs` used INSTEAD of reprojecting is the classic
    bug, and its failure is silent. The command above looks identical either way, so a test over the
    flags can never catch it — only a test over the SOURCE can.
    """

    def _prj(self, tmp_path, monkeypatch, text):
        written = tmp_path / "MARS_nomenclature_poly.prj"
        written.write_text(text)
        monkeypatch.setattr(download_nomenclature, "layer_path",
                            lambda layer, suffix="shp": written)
        return written

    def test_the_real_gazetteer_is_geographic(self):
        """The positive control, against the file actually on disk. Without it the refusals below
        would pass on a guard that rejected everything."""
        projection = download_nomenclature.layer_path("poly", "prj")
        if not projection.exists():
            pytest.skip("gazetteer not acquired on this machine")
        assert projection.read_text().lstrip().startswith("GEOGCS")
        fold.assert_geographic_source("poly")

    def test_a_projected_source_is_refused(self, tmp_path, monkeypatch):
        """SIM 3292's shapefile is exactly this — Robinson on the Mars sphere in METRES — so the
        hazard sits one directory away rather than in the abstract."""
        self._prj(tmp_path, monkeypatch,
                  'PROJCS["Mars_Robinson",GEOGCS["GCS_Mars_2000",'
                  'DATUM["D_Mars_2000",SPHEROID["Mars_2000_IAU_IAG",3396190.0,0.0]]],'
                  'UNIT["Meter",1.0]]')
        with pytest.raises(SystemExit) as refusal:
            fold.assert_geographic_source("poly")
        assert "GEOGCS" in str(refusal.value)

    def test_a_geographic_source_passes(self, tmp_path, monkeypatch):
        self._prj(tmp_path, monkeypatch,
                  'GEOGCS["GCS_Mars_2000",DATUM["D_Mars_2000",'
                  'SPHEROID["Mars_2000_IAU_IAG",3396190.0,169.8944472236118]],'
                  'PRIMEM["Reference_Meridian",0.0],UNIT["Degree",0.0174532925199433]]')
        fold.assert_geographic_source("poly")

    def test_a_missing_prj_is_refused_rather_than_assumed_geographic(self, tmp_path, monkeypatch):
        """Absent is undocumented, not permissive — the same rule this repo applies to a licence."""
        monkeypatch.setattr(download_nomenclature, "layer_path",
                            lambda layer, suffix="shp": tmp_path / "gone.prj")
        with pytest.raises(SystemExit) as refusal:
            fold.assert_geographic_source("poly")
        assert "missing" in str(refusal.value)


class TestTheFoldFlag:
    def test_wrapdateline_does_the_fold(self):
        assert "-wrapdateline" in fold.ogr_command(fold.POLYGONS, fold.LINES)

    def test_destination_precedes_source(self):
        """ogr2ogr's argument order, which reads backwards."""
        command = fold.ogr_command(fold.LINES, fold.POLYGONS)
        assert command.index(str(fold.POLYGONS)) < command.index(str(fold.LINES))


class TestFoldLongitude:
    @pytest.mark.parametrize("east_positive,expected", [
        (0.0, 0.0), (77.6873, 77.6873), (180.0, 180.0),
        (180.0001, -179.9999), (197.26, -162.74), (359.9, -0.1),
    ])
    def test_east_positive_lands_in_the_signed_window(self, east_positive, expected):
        assert fold.fold_longitude(east_positive) == pytest.approx(expected)

    def test_it_is_applied_to_centres_only(self):
        """A scalar cannot SPLIT a feature that straddles the seam, and 13 of them do — so this is
        the centres' fold and `-wrapdateline` is the geometry's. Using this on geometry would drag
        a crossing polygon's far edge across the whole map."""
        assert fold.fold_longitude(179.0) == 179.0
        assert fold.fold_longitude(181.0) == -179.0


class TestWhatTravelsIntoTheTiles:
    def test_the_identity_is_first(self):
        """`vector_layers.carried` treats the first key as the identity and drops a feature without
        it. Reordering this tuple would silently change which features exist."""
        assert fold.CARRIED_FIELDS[0] == "name"

    def test_the_card_can_be_filled_from_a_tile_alone(self, subtests):
        """Mars has no heroes, so the panel's whole content is these fields. A tap that needed a
        second fetch to say anything would be a blank card on a slow connection."""
        for field in ("name", "type", "origin", "diameter"):
            with subtests.test(field=field):
                assert field in fold.CARRIED_FIELDS

    def test_the_centres_do_not_travel_as_properties(self, subtests):
        """They are east-positive 0-360 in the source. A folded geometry carrying an unfolded
        longitude property is a mixed-convention file, and the next reader cannot tell which of the
        two any given number is. They reach `feature_labels.geojson` as GEOMETRY, folded."""
        for field in ("center_lon", "center_lat", "min_lon", "max_lon"):
            with subtests.test(field=field):
                assert field not in fold.CARRIED_FIELDS

    def test_every_carried_field_exists_in_the_source_schema(self):
        """Against the acquirer's own pin, so a typo here fails at the gate rather than producing a
        layer that is silently missing a property."""
        assert set(fold.CARRIED_FIELDS) <= download_nomenclature.REQUIRED_FIELDS


class TestFreshnessAnswersRatherThanRaises:
    """`is_fresh` had no test at all, and carried two ways to raise out of a yes/no question.

    Both are the same defect wearing different names: a predicate asked whether a stage can be
    skipped, meeting a state it had not been written for, and throwing instead of saying no.
    """

    def _store(self, tmp_path, monkeypatch, *, acquired: bool = True):
        """Outputs newer than their sources, with a matching recipe beside them."""
        sources = tmp_path / "raw"
        sources.mkdir()
        monkeypatch.setattr(download_nomenclature, "layer_path",
                            lambda layer, suffix="shp": sources / f"{layer}.{suffix}")
        if acquired:
            for layer in download_nomenclature.LAYERS:
                download_nomenclature.layer_path(layer).write_text("source\n")

        outputs = tmp_path / "out"
        outputs.mkdir()
        produced = {name: outputs / f"{name}.geojson" for name in fold.GEOMETRY_OUTPUTS}
        labels = outputs / "labels.geojson"
        for path in (*produced.values(), labels):
            path.write_text('{"type": "FeatureCollection", "features": []}\n')
        recipe = outputs / "recipe.json"
        recipe.write_text(json.dumps(fold.recipe()))

        now = time.time()
        for layer in download_nomenclature.LAYERS:
            source = download_nomenclature.layer_path(layer)
            if source.exists():
                os.utime(source, (now - 100, now - 100))
        for path in (*produced.values(), labels, recipe):
            os.utime(path, (now, now))

        monkeypatch.setattr(fold, "GEOMETRY_OUTPUTS", produced)
        monkeypatch.setattr(fold, "LABELS", labels)
        monkeypatch.setattr(fold, "recipe_path", lambda: recipe)
        return recipe

    def test_the_fixture_reports_fresh_before_anything_is_perturbed(self, tmp_path, monkeypatch):
        """The control. Both cases below assert False, which a permanently-False predicate also
        satisfies."""
        self._store(tmp_path, monkeypatch)
        assert fold.is_fresh()

    @pytest.mark.parametrize("rubbish", ["{not json", "5", "[]", "null", ""])
    def test_an_UNREADABLE_recipe_is_stale_rather_than_an_exception(self, rubbish, tmp_path,
                                                                     monkeypatch):
        recipe = self._store(tmp_path, monkeypatch)
        recipe.write_text(rubbish)
        assert not fold.is_fresh()

    def test_an_UNACQUIRED_gazetteer_is_stale_rather_than_a_ValueError(self, tmp_path, monkeypatch):
        """The second bug, and it fired on the machine least able to notice: the source mtime came
        from `max(... if ... .exists())`, so with nothing acquired the generator was empty and
        `max` raised. Asking whether the outputs could be skipped crashed on any clean clone.
        """
        self._store(tmp_path, monkeypatch, acquired=False)
        assert not any(download_nomenclature.layer_path(layer).exists()
                       for layer in download_nomenclature.LAYERS), "fixture must leave none acquired"
        assert fold.is_fresh() in (True, False)


class TestNothingIsSimplifiedHere:
    def test_no_douglas_peucker_runs(self):
        """The Earth sibling simplifies because its output is fetched and stroked directly. Nothing
        fetches this file — so simplifying would permanently discard detail the tile cut's own
        per-zoom knobs can spend or keep reversibly."""
        assert "-simplify" not in fold.ogr_command(fold.POLYGONS, fold.LINES)

    def test_the_recipe_says_so_where_a_reader_will_look(self):
        assert fold.recipe()["simplified"] is False

    def test_quantisation_is_far_below_a_tile_pixel(self):
        """1e-4 deg is 5.9 m on Mars against a 325.6 m z7 pixel. This moves vertices without
        deciding which survive, which is why it is not the thing the test above forbids."""
        assert fold.COORDINATE_PRECISION == 4


class TestAssertFolded:
    """The three failures, each of which passes while the others fail."""

    def _write(self, tmp_path, features):
        path = tmp_path / "layer.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
        return path

    def _feature(self, geometry, name="Gale"):
        return {"type": "Feature", "properties": {"name": name}, "geometry": geometry}

    def test_a_short_count_is_refused(self, tmp_path):
        path = self._write(tmp_path, [self._feature(
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]})])
        with pytest.raises(SystemExit) as refusal:
            fold.assert_folded(path, 2)
        assert "dropped" in str(refusal.value)

    def test_a_geometrycollection_is_refused_by_name(self, tmp_path):
        """The RFC 7946 fold's signature. Measured: it emits two of these where -wrapdateline emits
        none, and a walk that does not know about the container returns nothing for them."""
        path = self._write(tmp_path, [self._feature({
            "type": "GeometryCollection",
            "geometries": [{"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}],
        })])
        with pytest.raises(SystemExit) as refusal:
            fold.assert_folded(path, 1)
        assert "GeometryCollection" in str(refusal.value)

    def test_a_vertex_outside_the_window_is_refused(self, tmp_path):
        """The fold not running at all. The tiler would clip these away without an error, so the
        symptom is a missing feature rather than a failure."""
        path = self._write(tmp_path, [self._feature(
            {"type": "Polygon", "coordinates": [[[359.5, 0], [360.3, 0], [360.0, 1], [359.5, 0]]]})])
        with pytest.raises(SystemExit) as refusal:
            fold.assert_folded(path, 1)
        assert "fold did not run" in str(refusal.value)

    def test_a_correctly_folded_layer_passes(self, tmp_path):
        """The positive control. Without it the three refusals above would pass on a function that
        rejected everything."""
        path = self._write(tmp_path, [
            self._feature({"type": "Polygon",
                           "coordinates": [[[-179.5, 0], [-178.0, 0], [-178.0, 1], [-179.5, 0]]]}),
            self._feature({"type": "MultiPolygon",
                           "coordinates": [[[[10, 10], [12, 10], [12, 12], [10, 10]]]]}, "Jezero"),
        ])
        fold.assert_folded(path, 2)

    def test_a_null_geometry_does_not_crash_the_walk(self, tmp_path):
        path = self._write(tmp_path, [self._feature(None)])
        fold.assert_folded(path, 1)


class TestVerticesOf:
    @pytest.mark.parametrize("geometry,expected", [
        ({"type": "Point", "coordinates": [1, 2]}, 1),
        ({"type": "LineString", "coordinates": [[1, 2], [3, 4]]}, 2),
        ({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, 4),
        ({"type": "MultiPolygon",
          "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]], [[[5, 5], [6, 5], [6, 6], [5, 5]]]]},
         8),
    ])
    def test_every_nesting_depth_is_reached(self, geometry, expected):
        """A depth this misses is a vertex the window check never sees, which is the same as not
        checking at all for the geometry types it happens to miss."""
        assert len(fold.vertices_of(geometry)) == expected


class TestRecipe:
    def test_records_what_leaves_no_trace_in_the_output(self, subtests):
        """A flag change moves no mtime and marks no geometry a reader would notice."""
        recorded = fold.recipe()
        for key in ("carried_fields", "coordinate_precision", "fold", "srs", "simplified"):
            with subtests.test(key=key):
                assert key in recorded

    def test_is_json_serialisable(self):
        assert json.loads(json.dumps(fold.recipe())) == fold.recipe()

    def test_freshness_notices_a_flag_change(self):
        drifted = dict(fold.recipe())
        drifted["fold"] = "-lco RFC7946=YES"
        assert drifted != fold.recipe()
