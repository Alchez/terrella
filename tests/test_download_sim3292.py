"""The SIM 3292 acquisition recipe, checked without the network and without the fetched files.

WHAT IS HONESTLY TESTABLE HERE. The outputs live under gitignored `data/`, so a clone has neither
them nor the scout copies they replace — a test reading either would be red on a fresh checkout for
a reason that has nothing to do with the code. `GEOMETRY_DIGESTS` therefore cannot be re-derived by
any test; it is verified by `--verify` against the real files, which is a human or pipeline step.

Two things can still be checked, and between them they catch every mistake that is not a mistyped
hash:

  - the pins against EACH OTHER — a unit present in one table and missing from another, or a paging
    limit that no longer exceeds the counts it is supposed to protect;
  - the CHECKING LOGIC against synthetic documents, including the `timeStamp` trap the whole module
    is shaped around, and the near-miss rejections rather than only the absurd ones.
"""

import json
from typing import Any

import pytest

from pipeline.acquire import download_sim3292 as sim3292


def _feature(unit: str = "lApc", area: float = 100.0, **overrides: Any) -> dict[str, Any]:
    """One feature in the shape pygeoapi actually serves — lowercased FGDC fields, MultiPolygon."""
    feature: dict[str, Any] = {
        "type": "Feature",
        "id": 1,
        "properties": {"unit": unit, "unitdesc": f"{unit} unit", "spharea_km": area,
                       "objectid": 1, "shape_leng": 1.0, "shape_area": 1.0},
        "geometry": {"type": "MultiPolygon",
                     "coordinates": [[[[0.0, 80.0], [1.0, 80.0], [1.0, 81.0], [0.0, 80.0]]]]},
    }
    feature.update(overrides)
    return feature


def _document(features: list[dict[str, Any]], stamp: str = "2026-08-07T08:45:51.405948Z"):
    """A FeatureCollection carrying the per-request `timeStamp` pygeoapi always adds."""
    return {"type": "FeatureCollection", "features": features,
            "links": [{"href": "/collections/mars/x/items?f=json", "rel": "self"}],
            "timeStamp": stamp}


@pytest.fixture
def pinned_to_one_feature(monkeypatch):
    """Re-pin the module to a single synthetic feature, so the real digests stay untouched."""
    document = _document([_feature(area=100.0)])
    monkeypatch.setattr(sim3292, "UNITS", ("lApc",))
    monkeypatch.setattr(sim3292, "FEATURE_COUNTS", {"lApc": 1})
    monkeypatch.setattr(sim3292, "SPHERE_AREAS_KM2", {"lApc": 100.0})
    monkeypatch.setattr(sim3292, "GEOMETRY_DIGESTS",
                        {"lApc": sim3292.geometry_digest(document)})
    return document


class TestThePinsAgreeWithEachOther:
    def test_every_unit_appears_in_every_table(self, subtests):
        """A unit added to `UNITS` and forgotten in a pin table would `KeyError` mid-fetch, after
        the network call — and a unit left in a table after being dropped from `UNITS` is a pin
        nothing enforces. Both directions, because they fail differently."""
        for name, table in (("FEATURE_COUNTS", sim3292.FEATURE_COUNTS),
                            ("GEOMETRY_DIGESTS", sim3292.GEOMETRY_DIGESTS),
                            ("SPHERE_AREAS_KM2", sim3292.SPHERE_AREAS_KM2)):
            with subtests.test(name):
                assert set(table) == set(sim3292.UNITS)

    def test_the_paging_limit_still_exceeds_every_count_it_protects(self):
        """`QUERY_LIMIT` is the source's paging control. Below a unit's feature count the response
        truncates, and it carries no `numberMatched` — so the only thing standing between a short
        page and a smaller ice cap is that this number stays above the counts."""
        assert sim3292.QUERY_LIMIT > max(sim3292.FEATURE_COUNTS.values())

    def test_each_digest_is_a_sha256(self, subtests):
        """A truncated or half-pasted hash would fail every fetch with a mismatch that reads like
        the source changed."""
        for unit, digest in sim3292.GEOMETRY_DIGESTS.items():
            with subtests.test(unit):
                assert len(digest) == 64
                assert set(digest) <= set("0123456789abcdef")

    def test_the_query_names_the_unit_and_the_limit(self, subtests):
        """The URL is built rather than stored, so this is the only place its shape is asserted —
        and a query that dropped `unit=` would fetch the whole collection and pass every count
        check by returning too many rather than too few."""
        url = sim3292.unit_url("Apu")
        with subtests.test("names the unit"):
            assert "unit=Apu" in url
        with subtests.test("carries the paging limit"):
            assert f"limit={sim3292.QUERY_LIMIT}" in url
        with subtests.test("is absolute, since the data's own links are relative"):
            assert url.startswith(sim3292.HOST)


class TestTheTimestampTrap:
    """The trap the module exists to survive: two fetches of identical data differ in hash while
    matching in length, so a raw-bytes pin re-acquires forever and a size check agrees it is fine."""

    def test_two_stamps_are_the_same_length_and_different_bytes(self):
        """The premise, asserted rather than assumed — this is what makes the trap silent."""
        first = json.dumps(_document([_feature()], stamp="2026-08-05T10:45:46.374774Z"))
        second = json.dumps(_document([_feature()], stamp="2026-08-07T08:45:51.405948Z"))
        assert len(first) == len(second)
        assert first != second

    def test_the_digest_ignores_the_stamp(self):
        """The cure. Same features, different stamps, one digest."""
        features = [_feature()]
        assert (sim3292.geometry_digest(_document(features, stamp="2026-08-05T10:45:46.374774Z"))
                == sim3292.geometry_digest(_document(features, stamp="2026-08-07T08:45:51.405948Z")))

    def test_the_digest_still_moves_when_a_coordinate_moves(self):
        """And it is not vacuous: an invariant that ignored everything would also ignore the ice."""
        moved = _feature()
        moved["geometry"]["coordinates"][0][0][0] = [0.5, 80.0]
        assert (sim3292.geometry_digest(_document([_feature()]))
                != sim3292.geometry_digest(_document([moved])))

    def test_a_stamp_only_change_reads_as_FRESH_on_disk(self, tmp_path, monkeypatch,
                                                        pinned_to_one_feature):
        """The end-to-end consequence: re-fetching unchanged data must not re-acquire. This is the
        assertion that would have caught a bytes-keyed freshness rule."""
        monkeypatch.setattr(sim3292, "DATA_DIR", tmp_path)
        sim3292.write_unit("lApc", pinned_to_one_feature)
        sim3292.recipe_path().write_text(sim3292.build_recipe())
        assert sim3292.is_fresh("lApc")

        restamped = dict(pinned_to_one_feature, timeStamp="2099-01-01T00:00:00.000000Z")
        sim3292.write_unit("lApc", restamped)
        assert sim3292.is_fresh("lApc"), "a re-fetch of unchanged data must still read as fresh"


class TestTheDocumentContractRejectsNearMisses:
    def test_a_truncated_page_is_refused(self, pinned_to_one_feature):
        """The check nothing else can make: the response carries no `numberMatched`, so a short
        page is indistinguishable from a smaller map without this count."""
        with pytest.raises(SystemExit, match="TRUNCATED"):
            sim3292.assert_document("lApc", _document([]))

    def test_a_missing_fgdc_property_is_refused(self, pinned_to_one_feature):
        """The property schema is what identifies these bytes as the published product."""
        stripped = _feature()
        del stripped["properties"]["spharea_km"]
        with pytest.raises(SystemExit, match="spharea_km"):
            sim3292.assert_document("lApc", _document([stripped]))

    def test_a_non_areal_geometry_is_refused(self, pinned_to_one_feature):
        """A point or line extent rasterises to nothing, which looks like a body with no ice
        rather than like an error — the exact silent-empty failure the seam rule exists for."""
        point = _feature(geometry={"type": "Point", "coordinates": [0.0, 80.0]})
        with pytest.raises(SystemExit, match="MultiPolygon"):
            sim3292.assert_document("lApc", _document([point]))

    def test_a_drifted_publisher_area_is_refused(self, pinned_to_one_feature):
        """The independent oracle: `spharea_km` is USGS's own geodesic measurement, so it catches a
        document that parsed cleanly into geometry we did not expect."""
        with pytest.raises(SystemExit, match="geodesic area"):
            sim3292.assert_document("lApc", _document([_feature(area=999.0)]))

    def test_a_moved_polygon_is_refused_and_named_as_not_a_timestamp(self, pinned_to_one_feature):
        """The digest failure must say what it is NOT, or the next reader spends the afternoon
        suspecting the stamp this module already excludes."""
        moved = _feature(area=100.0)
        moved["geometry"]["coordinates"][0][0][0] = [0.5, 80.0]
        with pytest.raises(SystemExit, match="NOT a timeStamp"):
            sim3292.assert_document("lApc", _document([moved]))

    def test_the_real_shape_passes(self, pinned_to_one_feature):
        """The control. Every rejection above is worthless if the accepted case cannot be reached."""
        sim3292.assert_document("lApc", pinned_to_one_feature)


class TestFreshnessReadsTheFileNotTheSidecar:
    def test_a_missing_file_is_not_fresh(self, tmp_path, monkeypatch, pinned_to_one_feature):
        monkeypatch.setattr(sim3292, "DATA_DIR", tmp_path)
        assert not sim3292.is_fresh("lApc")

    def test_a_corrupt_file_is_not_fresh_rather_than_an_exception(self, tmp_path, monkeypatch,
                                                                  pinned_to_one_feature):
        """A half-written file must make the acquirer re-fetch, not crash it — the resumability
        rule: a crash at unit N must not require deleting the world by hand."""
        monkeypatch.setattr(sim3292, "DATA_DIR", tmp_path)
        sim3292.recipe_path().write_text(sim3292.build_recipe())
        sim3292.unit_path("lApc").write_text('{"type": "FeatureColl')
        assert not sim3292.is_fresh("lApc")

    def test_a_correct_sidecar_cannot_make_a_wrong_FILE_fresh(self, tmp_path, monkeypatch,
                                                              pinned_to_one_feature):
        """The sidecar records what the producer MEANT to emit; the file is what a consumer reads.
        A recipe agreeing with the module must never vouch for bytes that do not."""
        monkeypatch.setattr(sim3292, "DATA_DIR", tmp_path)
        sim3292.recipe_path().write_text(sim3292.build_recipe())
        wrong = _feature(area=100.0)
        wrong["geometry"]["coordinates"][0][0][0] = [0.5, 80.0]
        sim3292.write_unit("lApc", _document([wrong]))
        assert not sim3292.is_fresh("lApc")


class TestTheWrittenFileIsStable:
    def test_the_stamp_is_dropped_so_two_acquisitions_are_byte_identical(self, tmp_path, monkeypatch,
                                                                        pinned_to_one_feature):
        """Keeping the stamp would push the same trap one layer down, onto anything diffing the
        store or hashing it into a downstream recipe."""
        monkeypatch.setattr(sim3292, "DATA_DIR", tmp_path)
        first = sim3292.write_unit("lApc", pinned_to_one_feature).read_bytes()
        second = sim3292.write_unit(
            "lApc", dict(pinned_to_one_feature, timeStamp="2099-01-01T00:00:00.000000Z")
        ).read_bytes()
        assert first == second
        assert b"timeStamp" not in first

    def test_no_part_file_survives_a_completed_write(self, tmp_path, monkeypatch,
                                                     pinned_to_one_feature):
        """A file under its final name is always complete, so a consumer never reads a partial."""
        monkeypatch.setattr(sim3292, "DATA_DIR", tmp_path)
        sim3292.write_unit("lApc", pinned_to_one_feature)
        assert list(tmp_path.glob("*.part")) == []


class TestTheRecipeDeclaresWhatTheDataCannot:
    def test_the_host_is_recorded_because_the_responses_links_are_relative(self):
        """The gap that made the scout copies unreproducible: every `links[].href` comes back
        relative, so nothing in a fetched file names where it came from."""
        recipe = json.loads(sim3292.build_recipe())
        assert recipe["host"] == sim3292.HOST
        assert recipe["collection"] == sim3292.COLLECTION

    def test_every_unit_carries_its_digest_and_count(self, subtests):
        for unit in sim3292.UNITS:
            with subtests.test(unit):
                recorded = json.loads(sim3292.build_recipe())["units"][unit]
                assert recorded["geometry_sha256"] == sim3292.GEOMETRY_DIGESTS[unit]
                assert recorded["features"] == sim3292.FEATURE_COUNTS[unit]


class TestTheRecipeDownloadsNothingByAccident:
    def test_verify_reads_disk_and_never_the_network(self, tmp_path, monkeypatch,
                                                     pinned_to_one_feature):
        """`--verify` is the on-disk oracle for the one pin no test can re-derive, so it must be
        runnable with the network down."""
        monkeypatch.setattr(sim3292, "DATA_DIR", tmp_path)
        monkeypatch.setattr(sim3292, "fetch_unit",
                            lambda unit: pytest.fail(f"--verify reached the network for {unit}"))
        sim3292.write_unit("lApc", pinned_to_one_feature)
        monkeypatch.setattr("sys.argv", ["download_sim3292", "--verify"])
        assert sim3292.main() == 0

    def test_check_writes_nothing(self, tmp_path, monkeypatch, pinned_to_one_feature):
        """`--check` reaches the host on purpose; the assertion is that the store stays empty."""
        monkeypatch.setattr(sim3292, "DATA_DIR", tmp_path)
        monkeypatch.setattr(sim3292, "fetch_unit", lambda unit: pinned_to_one_feature)
        monkeypatch.setattr("sys.argv", ["download_sim3292", "--check"])
        assert sim3292.main() == 0
        assert list(tmp_path.iterdir()) == []
