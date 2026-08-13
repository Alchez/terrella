"""The gazetteer acquirer's contract, none of which touches the network.

WHY THE SYNTHETIC ARCHIVE. `extract` is the only function here with a destructive failure mode, and
the thing worth proving about it is a NEGATIVE — that a refused archive leaves the directory
untouched. That needs a bad archive, and building a two-member zip with monkeypatched digests states
the property in ten lines where a fixture carrying real shapefiles would state it in megabytes.

WHY `assert_layer` IS FED DICTS. It takes rows rather than a path precisely so its five checks can
be exercised without OGR, a shapefile, or a temp directory. The one test that does reach OGR is the
encoding diagnosis, because what it asserts is about a missing file rather than about geometry.
"""

import json
import zipfile

import pytest

from pipeline.acquire import download_nomenclature as gazetteer


def rows(count: int = 3, **overrides) -> list[dict[str, str]]:
    """`count` well-formed attribute rows, with any field overridden across all of them."""
    base = {"name": "Gale", "clean_name": "Gale", "origin": "Walter F.; Australian astronomer.",
            "diameter": "154.0", "type": "Crater, craters", "code": "AA",
            "center_lon": "137.8", "center_lat": "-5.4",
            "min_lon": "-180.0", "max_lon": "360.3366", "approval": "Adopted by IAU",
            "link": "http://planetarynames.wr.usgs.gov/Feature/2071"}
    return [dict(base, name=f"{base['name']}{index}", **overrides) for index in range(count)]


@pytest.fixture
def pinned_to_one_layer(monkeypatch):
    """Collapse the module to a single 3-feature layer, so a test states one thing."""
    monkeypatch.setattr(gazetteer, "LAYERS", ("poly",))
    monkeypatch.setattr(gazetteer, "FEATURE_COUNTS", {"poly": 3})
    monkeypatch.setattr(gazetteer, "LONGITUDE_BOUNDS", {"poly": (-180.0, 360.3366)})
    monkeypatch.setattr(gazetteer, "CENTRES_EAST_OF_180", {"poly": 3})


class TestThePinsAgreeWithEachOther:
    """The module's own constants, which nothing else checks and every assertion below assumes."""

    def test_every_layer_has_a_count_a_bound_and_a_centre_pin(self):
        for layer in gazetteer.LAYERS:
            assert layer in gazetteer.FEATURE_COUNTS
            assert layer in gazetteer.LONGITUDE_BOUNDS
            assert layer in gazetteer.CENTRES_EAST_OF_180

    def test_every_layer_s_four_shapefile_components_are_pinned(self):
        for layer in gazetteer.LAYERS:
            for suffix in ("shp", "shx", "dbf", "prj"):
                assert f"MARS_nomenclature_{layer}.{suffix}" in gazetteer.MEMBER_DIGESTS

    def test_the_licence_bearing_member_is_pinned_too(self):
        # The one member that is neither geometry nor an index, and the only evidence on disk that
        # this data may be published at all.
        assert gazetteer.METADATA_MEMBER in gazetteer.MEMBER_DIGESTS

    def test_centres_east_of_180_cannot_exceed_the_feature_count(self):
        for layer in gazetteer.LAYERS:
            assert gazetteer.CENTRES_EAST_OF_180[layer] <= gazetteer.FEATURE_COUNTS[layer]


class TestARefusedArchiveLeavesTheDirectoryAlone:
    """The property that is a NEGATIVE, and the one this module got wrong before it was measured."""

    @staticmethod
    def _archive(path, members: dict[str, bytes]):
        with zipfile.ZipFile(path, "w") as bundle:
            for name, data in members.items():
                bundle.writestr(name, data)
        return path

    @pytest.fixture
    def two_member_pins(self, monkeypatch):
        monkeypatch.setattr(gazetteer, "LAYERS", ())          # no .cpg to write
        monkeypatch.setattr(gazetteer, "MEMBER_DIGESTS", {
            "aaa.txt": gazetteer.digest_of(b"first"),
            "zzz.txt": gazetteer.digest_of(b"second"),
        })

    def test_a_good_archive_extracts_every_member(self, tmp_path, monkeypatch, two_member_pins):
        monkeypatch.setattr(gazetteer, "DATA_DIR", tmp_path)
        archive = self._archive(tmp_path / "a.zip", {"aaa.txt": b"first", "zzz.txt": b"second"})
        gazetteer.extract(archive)
        assert (tmp_path / "aaa.txt").read_bytes() == b"first"
        assert (tmp_path / "zzz.txt").read_bytes() == b"second"

    def test_a_bad_digest_writes_NOTHING_not_even_the_members_before_it(
            self, tmp_path, monkeypatch, two_member_pins):
        """The two-pass property, stated as the failure it prevents.

        `aaa.txt` sorts before `zzz.txt`, so a verify-then-write loop would land the good member and
        only then refuse — leaving a directory holding half of one edition and half of another. That
        is what this asserts against, and it is what the one-pass version actually did.
        """
        monkeypatch.setattr(gazetteer, "DATA_DIR", tmp_path)
        archive = self._archive(tmp_path / "a.zip", {"aaa.txt": b"first", "zzz.txt": b"TAMPERED"})
        with pytest.raises(SystemExit) as refusal:
            gazetteer.extract(archive)
        assert "zzz.txt" in str(refusal.value)
        assert not (tmp_path / "aaa.txt").exists(), (
            "the member sorting BEFORE the bad one landed — a refused archive must leave the "
            "previous edition intact rather than half-overwritten"
        )

    def test_a_restructured_archive_is_refused_by_its_member_list(
            self, tmp_path, monkeypatch, two_member_pins):
        monkeypatch.setattr(gazetteer, "DATA_DIR", tmp_path)
        archive = self._archive(tmp_path / "a.zip", {"aaa.txt": b"first", "other.txt": b"second"})
        with pytest.raises(SystemExit) as refusal:
            gazetteer.extract(archive)
        assert "restructured" in str(refusal.value)

    def test_the_cpg_is_written_because_the_archive_ships_none(self, tmp_path, monkeypatch):
        """The encoding fix travels WITH the data, which is the whole reason `extract` invents it."""
        monkeypatch.setattr(gazetteer, "DATA_DIR", tmp_path)
        monkeypatch.setattr(gazetteer, "MEMBER_DIGESTS", {"aaa.txt": gazetteer.digest_of(b"x")})
        archive = self._archive(tmp_path / "a.zip", {"aaa.txt": b"x"})
        gazetteer.extract(archive)
        for layer in gazetteer.LAYERS:
            assert gazetteer.layer_path(layer, "cpg").read_text() == "UTF-8"

    def test_no_part_file_survives_a_completed_extraction(self, tmp_path, monkeypatch,
                                                          two_member_pins):
        monkeypatch.setattr(gazetteer, "DATA_DIR", tmp_path)
        gazetteer.extract(self._archive(tmp_path / "a.zip",
                                        {"aaa.txt": b"first", "zzz.txt": b"second"}))
        assert list(tmp_path.glob("*.part")) == []


class TestTheLayerContractRejectsNearMisses:
    """Six checks that can each pass while another fails, so each gets its own case."""

    def test_a_well_formed_layer_passes(self, pinned_to_one_layer):
        gazetteer.assert_layer("poly", rows(3, center_lon="200.0"))

    def test_a_short_count_is_a_truncated_extraction(self, pinned_to_one_layer):
        with pytest.raises(SystemExit, match="pinned to 3"):
            gazetteer.assert_layer("poly", rows(2, center_lon="200.0"))

    def test_a_missing_field_names_the_field(self, pinned_to_one_layer):
        thin = [{key: value for key, value in row.items() if key != "origin"}
                for row in rows(3, center_lon="200.0")]
        with pytest.raises(SystemExit, match="origin"):
            gazetteer.assert_layer("poly", thin)

    def test_a_blank_origin_is_a_panel_that_says_nothing(self, pinned_to_one_layer):
        with pytest.raises(SystemExit, match="origin"):
            gazetteer.assert_layer("poly", rows(3, origin="   ", center_lon="200.0"))

    def test_a_link_that_is_not_a_feature_page_is_refused(self, pinned_to_one_layer, subtests):
        """The field the detail card sends readers to. A moved host and a moved path both leave
        every other check here passing, and the failure only ever surfaces on a click."""
        for astray in ("https://planetarynames.wr.usgs.gov/Feature/2071",  # scheme is the DBF's
                       "http://planetarynames.wr.usgs.gov/Feature/",
                       "http://example.com/Feature/2071", "   "):
            with subtests.test(link=astray), pytest.raises(SystemExit, match="gazetteer feature"):
                gazetteer.assert_layer("poly", rows(3, link=astray, center_lon="200.0"))

    def test_longitudes_normalised_into_0_360_are_refused(self, pinned_to_one_layer):
        # The trap the 540-degree span exists to catch: every other check passes on this file.
        with pytest.raises(SystemExit, match="longitude bounds"):
            gazetteer.assert_layer("poly", rows(3, min_lon="0.0", center_lon="200.0"))

    def test_centres_switching_convention_is_caught_by_its_own_check(self, pinned_to_one_layer):
        # Bounds untouched, so only the centre count can see this.
        with pytest.raises(SystemExit, match="centres east of 180"):
            gazetteer.assert_layer("poly", rows(3, center_lon="-160.0"))


class TestTheLicenceIsReadFromTheProductEveryRun:
    def test_the_pinned_use_constraint_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gazetteer, "DATA_DIR", tmp_path)
        (tmp_path / gazetteer.METADATA_MEMBER).write_text(
            f"<idinfo><useconst>{gazetteer.USE_CONSTRAINT}</useconst></idinfo>", encoding="utf-8")
        gazetteer.assert_licence()

    def test_changed_terms_stop_the_pipeline(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gazetteer, "DATA_DIR", tmp_path)
        (tmp_path / gazetteer.METADATA_MEMBER).write_text(
            "<idinfo><useconst>CC BY-NC 4.0</useconst></idinfo>", encoding="utf-8")
        with pytest.raises(SystemExit, match="CC BY-NC"):
            gazetteer.assert_licence()

    def test_an_absent_element_is_undocumented_rather_than_permissive(self, tmp_path, monkeypatch):
        # The distinction `licence-attaches-to-the-product` turns on: no field is not "no terms".
        monkeypatch.setattr(gazetteer, "DATA_DIR", tmp_path)
        (tmp_path / gazetteer.METADATA_MEMBER).write_text("<idinfo></idinfo>", encoding="utf-8")
        with pytest.raises(SystemExit, match="undocumented"):
            gazetteer.assert_licence()


class TestFreshnessReadsTheFilesNotTheSidecar:
    @pytest.fixture
    def one_member(self, monkeypatch):
        monkeypatch.setattr(gazetteer, "LAYERS", ())
        monkeypatch.setattr(gazetteer, "MEMBER_DIGESTS", {"aaa.txt": gazetteer.digest_of(b"x")})

    def test_a_missing_member_is_not_fresh(self, tmp_path, monkeypatch, one_member):
        monkeypatch.setattr(gazetteer, "DATA_DIR", tmp_path)
        gazetteer.recipe_path().write_text("{}", encoding="utf-8")
        assert gazetteer.is_fresh() is False

    def test_a_correct_sidecar_cannot_make_a_WRONG_member_fresh(self, tmp_path, monkeypatch,
                                                                one_member):
        monkeypatch.setattr(gazetteer, "DATA_DIR", tmp_path)
        gazetteer.recipe_path().write_text(gazetteer.build_recipe(), encoding="utf-8")
        (tmp_path / "aaa.txt").write_bytes(b"not x")
        assert gazetteer.is_fresh() is False

    def test_a_missing_cpg_is_not_fresh_even_when_every_member_matches(self, tmp_path, monkeypatch):
        """The `.cpg` is ours, not the publisher's, so no member digest can vouch for it."""
        monkeypatch.setattr(gazetteer, "DATA_DIR", tmp_path)
        monkeypatch.setattr(gazetteer, "MEMBER_DIGESTS", {"aaa.txt": gazetteer.digest_of(b"x")})
        gazetteer.recipe_path().write_text(gazetteer.build_recipe(), encoding="utf-8")
        (tmp_path / "aaa.txt").write_bytes(b"x")
        assert gazetteer.is_fresh() is False


class TestTheEncodingFailsLoudlyRatherThanAsATraceback:
    def test_a_missing_cpg_names_the_file_and_the_consequence(self, tmp_path, monkeypatch):
        """Found by mutation: without this, the layer guards were unreachable behind a stack trace."""
        monkeypatch.setattr(gazetteer, "DATA_DIR", tmp_path)
        gazetteer.layer_path("poly").write_bytes(b"")
        with pytest.raises(SystemExit, match="mojibake"):
            gazetteer.read_attributes("poly")


class TestTheRecipeDeclaresWhatTheDataCannot:
    def test_the_recipe_records_the_url_because_a_zip_cannot(self):
        recipe = json.loads(gazetteer.build_recipe())
        assert recipe["url"] == gazetteer.archive_url()
        assert gazetteer.HOST in recipe["url"]

    def test_the_recipe_records_the_encoding_the_archive_omits(self):
        # The `.cpg` is the fix; this is the note saying the fix is ours rather than the source's.
        assert "UTF-8" in json.loads(gazetteer.build_recipe())["dbf_encoding"]

    def test_the_recipe_records_the_terms_it_was_acquired_under(self):
        assert json.loads(gazetteer.build_recipe())["use_constraints"] == gazetteer.USE_CONSTRAINT


class TestNothingReachesTheNetworkByAccident:
    def test_verify_never_opens_a_url(self, tmp_path, monkeypatch):
        def refuse(*_args, **_kwargs):
            raise AssertionError("--verify reached the network")

        monkeypatch.setattr(gazetteer.fetch, "open_url", refuse)
        monkeypatch.setattr(gazetteer.fetch, "download_one", refuse)
        monkeypatch.setattr(gazetteer, "DATA_DIR", tmp_path)
        monkeypatch.setattr("sys.argv", ["download_nomenclature", "--verify"])
        with pytest.raises(SystemExit) as refusal:
            gazetteer.main()  # exits on the absent metadata file, having touched no network
        # The message rides on SystemExit rather than stderr — `sys.exit(str)` never reaches the
        # stream under pytest, so asserting on capsys here would pass for the wrong reason.
        assert "not on disk" in str(refusal.value)
