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

import dataclasses
import json
import os
import re
import time

import pytest

from pipeline import paths
from pipeline.compose import countries_pmtiles as cut
from pipeline.compose import vector_cut, vector_layers


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
        staged, out = vector_cut.staged(cut.CUT), vector_cut.out(cut.CUT)
        command = vector_cut.pmtiles_command(cut.CUT, staged, out)
        assert command.index(str(out)) < command.index(str(staged))

    def test_command_carries_the_contract(self, subtests):
        command = " ".join(vector_cut.pmtiles_command(
            cut.CUT, vector_cut.staged(cut.CUT), vector_cut.out(cut.CUT)))
        for label, expected in (
            ("format", "-f PMTiles"),
            ("min zoom", f"MINZOOM={cut.MIN_ZOOM}"),
            ("max zoom", f"MAXZOOM={cut.MAX_ZOOM}"),
            ("buffer", "BUFFER=0"),
            ("extent", f"EXTENT={vector_layers.EXTENT}"),
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
        source = (paths.ROOT / "web/src/lib/reliefTiles.ts").read_text()
        found = re.search(r"export const RELIEF_MAX_ZOOM = (\d+);", source)
        assert found is not None, "RELIEF_MAX_ZOOM is gone or renamed in web/src/lib/reliefTiles.ts"
        assert cut.MAX_ZOOM == int(found.group(1))


class TestStagingCommand:
    def test_first_layer_creates_and_the_rest_update(self, subtests):
        """The PMTiles driver cannot append a layer to an archive it already wrote, so all three
        have to reach ogr2ogr as ONE multi-layer dataset. That is the only reason a GeoPackage
        exists in this pipeline at all."""
        staged = vector_cut.staged(cut.CUT)
        first = vector_layers.stage_command(
            cut.source_path(), staged, cut.FILL_LAYER, update=False)
        later = vector_layers.stage_command(
            cut.outlines_path(), staged, cut.OUTLINE_LAYER, update=True)
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
        recorded = vector_cut.recipe(cut.CUT)
        for key in ("simplification", "simplification_max_zoom", "buffer", "extent",
                    "min_zoom", "max_zoom", "layers"):
            with subtests.test(key=key):
                assert key in recorded

    def test_is_json_serialisable(self):
        recorded = vector_cut.recipe(cut.CUT)
        assert json.loads(json.dumps(recorded)) == recorded

    def test_freshness_notices_a_settings_change(self):
        """A re-cut under different settings leaves an archive NEWER than its source, so mtime
        alone would call it fresh. The recipe comparison is the half that catches it."""
        drifted = dict(vector_cut.recipe(cut.CUT))
        drifted["simplification"] = cut.SIMPLIFICATION + 1
        assert drifted != vector_cut.recipe(cut.CUT)


#: A derivation's payload is irrelevant to every case here — what is under test is the GATE, and a
#: real collection would only make the fixture slower and the failures longer.
_EMPTY: dict = {"type": "FeatureCollection", "features": []}


class TestDerivationFreshness:
    """The gate that decides whether `vector_layers`' opinion has reached the bytes on disk.

    THE BUG THIS EXISTS FOR SHIPPED, and it was silent by construction. `derive` skipped on the
    source's mtime alone, so a change to the shared geometry walk left the GeoJSON untouched; the
    cut then re-ran (its own recipe HAD changed), produced a byte-identical archive from the stale
    outlines, and stamped the new recipe over it — consuming the only signal that anything was out
    of date. Earth's antimeridian closures survived the fix that was written to remove them, and
    every test stayed green because they all exercise the walk directly.
    """

    @staticmethod
    def _store(tmp_path, monkeypatch):
        """A complete, internally consistent store, DECLARED rather than monkeypatched.

        Its predecessor set six module globals and one function, which is the shape that cannot be
        checked: a fixture missing one of them writes the rest into the real work tree, and that is
        how a test starts depending on a store it did not build. A `VectorCut` names every path it
        reads, so an incomplete redirect is no longer expressible — the driver has no globals of its
        own, and `paths.DATA` carries the three it derives from the body.
        """
        borders, work = tmp_path / "borders", tmp_path / "work"
        (work / "planet_vector").mkdir(parents=True)
        borders.mkdir()
        source = borders / "countries.geojson"
        outlines = borders / "country_outlines.geojson"
        hits = borders / "country_hits.geojson"
        stamp = borders / "country_outlines_params.json"
        archive = work / "planet_vector/vector.pmtiles"
        monkeypatch.setattr(paths, "DATA", tmp_path)
        monkeypatch.setattr(cut, "CUT", dataclasses.replace(
            cut.CUT,
            sources=lambda: {cut.FILL_LAYER: source, cut.OUTLINE_LAYER: outlines,
                             cut.HIT_LAYER: hits},
            derived_from=lambda: source,
            derivation=lambda: {outlines: _EMPTY, hits: _EMPTY},
            derivation_stamp=lambda: stamp,
        ))
        recipe = vector_cut.recipe_path(cut.CUT)
        for path in (source, outlines, hits, archive):
            path.write_text("x")
        stamp.write_text(json.dumps(vector_layers.seam_recipe()))
        recipe.write_text(json.dumps(vector_cut.recipe(cut.CUT)))
        # The archive must be the NEWEST thing in the store, or mtime alone fails it and the
        # recipe half of the gate is never reached — the check would pass for the wrong reason.
        now = time.time()
        for offset, path in enumerate((source, outlines, hits, stamp, recipe)):
            os.utime(path, (now - 100 + offset, now - 100 + offset))
        os.utime(archive, (now, now))
        return stamp

    def test_the_fixture_reports_fresh_before_anything_is_perturbed(self, tmp_path, monkeypatch):
        """The control. Every case below asserts `is_fresh()` went False, and a fixture that was
        never True would satisfy all of them while testing nothing."""
        self._store(tmp_path, monkeypatch)
        assert vector_cut.is_fresh(cut.CUT)

    def _knob_moves_but_the_archive_recipe_is_restamped(self, tmp_path, monkeypatch, knob, value):
        """Perturb a shared knob, then re-stamp the ARCHIVE's recipe as a real cut would.

        WITHOUT THE RE-STAMP THIS TESTS THE OLD GUARD. `recipe()` interpolates `seam_recipe()`, so
        moving a knob invalidates the archive's own sidecar too and `is_fresh()` goes False for a
        reason that predates this class. Re-stamping reproduces the state that actually shipped:
        the cut re-ran under the new recipe, from outlines derived under the old one.
        """
        self._store(tmp_path, monkeypatch)
        monkeypatch.setattr(vector_layers, knob, value)
        recipe = vector_cut.recipe_path(cut.CUT)
        recipe.write_text(json.dumps(vector_cut.recipe(cut.CUT)))
        older = vector_cut.out(cut.CUT).stat().st_mtime - 1
        os.utime(recipe, (older, older))

    def test_a_seam_knob_change_makes_the_ARCHIVE_stale_though_no_mtime_moved(
            self, tmp_path, monkeypatch):
        """The regression, isolated to the derivation stamp: archive newest, archive recipe
        current, and the only thing out of date is the geometry it was cut from."""
        self._knob_moves_but_the_archive_recipe_is_restamped(
            tmp_path, monkeypatch, "SEAM_BAND_DEGREES", vector_layers.SEAM_BAND_DEGREES + 1.0)
        assert (json.loads(vector_cut.recipe_path(cut.CUT).read_text())
                == vector_cut.recipe(cut.CUT)), "recipe half must PASS"
        assert not vector_cut.is_fresh(cut.CUT)

    def test_the_other_seam_knob_counts_too(self, tmp_path, monkeypatch):
        """Both knobs or neither: a stamp comparing one field would pass this suite while leaving
        the other free to drift."""
        self._knob_moves_but_the_archive_recipe_is_restamped(
            tmp_path, monkeypatch, "SEAM_TWIN_LATITUDE_EPSILON",
            vector_layers.SEAM_TWIN_LATITUDE_EPSILON * 2)
        assert (json.loads(vector_cut.recipe_path(cut.CUT).read_text())
                == vector_cut.recipe(cut.CUT)), "recipe half must PASS"
        assert not vector_cut.is_fresh(cut.CUT)

    def test_a_derivation_that_was_never_stamped_is_not_believed(self, tmp_path, monkeypatch):
        """The state every store was in before this guard existed. Absence must read as stale
        rather than as "no objection", or the fix reaches nothing already on disk."""
        stamp = self._store(tmp_path, monkeypatch)
        stamp.unlink()
        assert not vector_cut.is_fresh(cut.CUT)

    @pytest.mark.parametrize("rubbish", ["{not json", "5", "[]", "null", ""])
    def test_an_UNREADABLE_stamp_is_stale_rather_than_an_exception(self, rubbish, tmp_path,
                                                                    monkeypatch):
        """Absence was handled; garbage was not. Both comparisons here read a sidecar with a bare
        `json.loads` and no `try`, so a truncated write raised out of a freshness question — the
        family `freshness.recorded_json` now owns."""
        stamp = self._store(tmp_path, monkeypatch)
        stamp.write_text(rubbish)
        assert not vector_cut.is_fresh(cut.CUT)

    @pytest.mark.parametrize("rubbish", ["{not json", "5", "[]", "null", ""])
    def test_an_UNREADABLE_archive_recipe_is_stale_rather_than_an_exception(
            self, rubbish, tmp_path, monkeypatch):
        """The second of the two sidecars, checked separately because they are read by different
        functions and only one of them used to guard `.exists()`."""
        self._store(tmp_path, monkeypatch)
        vector_cut.recipe_path(cut.CUT).write_text(rubbish)
        assert not vector_cut.is_fresh(cut.CUT)

    def test_derive_reruns_when_the_stamp_is_stale_and_stamps_what_it_wrote(
            self, tmp_path, monkeypatch):
        """The producing half, asserted on the file it writes rather than on a print. `derive`
        rewriting is what makes the archive's staleness actionable."""
        stamp = self._store(tmp_path, monkeypatch)
        stamp.write_text(json.dumps({"seam_band_degrees": -1.0}))
        vector_cut.derive(cut.CUT, force=False)
        assert json.loads(stamp.read_text()) == vector_layers.seam_recipe()
