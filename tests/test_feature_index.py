"""Contract for the web's named-feature index.

THE COMMITTED FILE IS THE THING UNDER TEST, not the producer's return value, because the file is
what ships. It is generated and tracked, which is a combination nothing else in this repo has: the
other generated JSON is either gitignored (`countries.json`, machine state) or tiny enough to read
(`tileTokens.json`). A tracked 1,920-row artifact can be edited by hand, can be left behind by a
field rename, and can be regenerated from a gazetteer that quietly changed — and all three look
identical on disk.

SPLIT ACROSS TWO SUITES ON PURPOSE, AND THE SPLIT IS ABOUT WHAT NEEDS THE DATA. Everything here that
compares against a fresh run needs the acquired gazetteer and SKIPS without it — which on a clean
checkout reads exactly like a pass. So the assertions that need no data at all live in
`web/src/lib/featureIndex.test.ts` and run unconditionally: the row count, the fold, the sort, the
duplicate name, the diameter rule. What is left here is the one question only this machine can
answer — whether the committed bytes are still what the producer emits.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from pipeline.acquire import download_nomenclature
from pipeline.compose import features_geojson

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "web/scripts/gen_feature_index.py"
COMMITTED = REPO_ROOT / "web/src/lib/featureIndex.json"


def producer():
    """The generator module, loaded by path — `web/scripts/` is a script directory, not a package."""
    spec = importlib.util.spec_from_file_location("gen_feature_index", SCRIPT)
    assert spec is not None and spec.loader is not None, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def anchor(name: str, *, clean: str | None = None, diameter: str = "12.5",
           longitude: float = 0.0, latitude: float = 0.0) -> dict[str, Any]:
    """One label anchor in the shape `features_geojson.label_points` writes."""
    return {
        "type": "Feature",
        "properties": {"name": name, "clean_name": clean or name,
                       "type": "Crater, craters", "origin": "A person.", "diameter": diameter},
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
    }


def collection(*anchors: dict[str, Any]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(anchors)}


def links(*names: str) -> dict[str, str]:
    """A gazetteer page per name, in the shape `gazetteer_links` builds from the DBF.

    Derived from the SORTED unique names so the same set of names yields the same pages whatever
    order they are passed in — which the order test below relies on, and which a counter over the
    argument list would quietly break.
    """
    return {name: f"https://planetarynames.wr.usgs.gov/Feature/{2000 + index}"
            for index, name in enumerate(sorted(set(names)))}


class TestTheRowIsReshapedForTheWeb:
    def test_the_gazetteers_field_names_become_the_frontends(self, subtests):
        [row] = producer().index_from(collection(anchor("Gale")), links("Gale"))
        for key in ("name", "cleanName", "type", "origin", "gazetteer", "diameterKm",
                    "longitude", "latitude"):
            with subtests.test(key=key):
                assert key in row
        assert "clean_name" not in row and "diameter" not in row

    def test_a_zero_diameter_becomes_null_rather_than_zero(self):
        """The gazetteer sizes two features at zero, and the tiles DROP a falsy diameter — so
        `candidateFrom` already reads them as unsized. A literal 0 here would leave one catalogue
        disagreeing with itself about which features have a size, and frame them at no kilometres."""
        [row] = producer().index_from(
            collection(anchor("Candor Chaos", diameter="0.000000")), links("Candor Chaos"))
        assert row["diameterKm"] is None

    def test_the_publishers_fifteen_decimals_are_quantised_to_metres(self):
        [row] = producer().index_from(
            collection(anchor("Blunck", diameter="66.484999999999999")), links("Blunck"))
        assert row["diameterKm"] == 66.485

    def test_the_folded_centre_is_copied_rather_than_refolded(self):
        """The anchors arrive folded. Refolding here is how the two longitude conventions get mixed
        back together — a second fold of -21.57 is a no-op, but a second fold of +200 is not."""
        [row] = producer().index_from(
            collection(anchor("Aarna", longitude=-21.57, latitude=14.7)), links("Aarna"))
        assert (row["longitude"], row["latitude"]) == (-21.57, 14.7)

    def test_an_anchor_with_no_gazetteer_page_stops_the_run(self):
        """The two reads of one gazetteer disagreeing about what is in it. A row written anyway
        carries a card whose link goes nowhere, which renders exactly like one that works."""
        with pytest.raises(SystemExit) as refused:
            producer().index_from(collection(anchor("Barsoom")), links("Gale"))
        assert "Barsoom" in str(refused.value)


class TestTheGazetteerPageIsCarriedWhole:
    """The card's one outbound link, and the field this index takes from the DBF rather than the
    anchors. Every assertion here is about an address, which is the one kind of value that is
    indistinguishable from a working one until somebody clicks it."""

    def test_the_publishers_http_becomes_the_https_it_redirects_to(self):
        assert producer().gazetteer_url(
            "http://planetarynames.wr.usgs.gov/Feature/2596", download_nomenclature.FEATURE_URL,
        ) == "https://planetarynames.wr.usgs.gov/Feature/2596"

    def test_an_address_that_is_not_a_feature_page_stops_the_run(self, subtests):
        """The pattern is the acquirer's, so this is the second consumer proving it is enforced
        here too — a moved host, a moved path and a search URL all serialise identically."""
        for astray in ("https://example.com/Feature/2596",
                       "http://planetarynames.wr.usgs.gov/SearchResults?Feature=Huygens",
                       "http://planetarynames.wr.usgs.gov/Feature/"):
            with subtests.test(url=astray), pytest.raises(SystemExit):
                producer().gazetteer_url(astray, download_nomenclature.FEATURE_URL)

    def test_one_feature_entered_twice_keeps_its_single_page(self):
        """Bohar's two DBF rows carry the same URL, which is what lets the row collapse survive."""
        rows = [{"name": "Bohar", "link": "http://planetarynames.wr.usgs.gov/Feature/16054"},
                {"name": "Bohar", "link": "http://planetarynames.wr.usgs.gov/Feature/16054"}]
        assert producer().gazetteer_links(rows, download_nomenclature.FEATURE_URL) == {
            "Bohar": "https://planetarynames.wr.usgs.gov/Feature/16054"}

    def test_a_name_with_two_pages_stops_the_run(self):
        """The index is keyed by name, so the alternative is picking one at random and looking
        right — the same shape the whole-row collapse next door exists to keep loud."""
        rows = [{"name": "Bohar", "link": "http://planetarynames.wr.usgs.gov/Feature/16054"},
                {"name": "Bohar", "link": "http://planetarynames.wr.usgs.gov/Feature/99999"}]
        with pytest.raises(SystemExit) as refused:
            producer().gazetteer_links(rows, download_nomenclature.FEATURE_URL)
        assert "Bohar" in str(refused.value)


class TestOneFeatureEnteredTwiceBecomesOneRow:
    """The gazetteer publishes Bohar twice, agreeing on every attribute it carries.

    The collapse is on the WHOLE ROW rather than on the name, and the two tests below are the two
    halves of that: identical rows are one feature, and a shared name over differing data is two.
    Collapsing by name would pass the first and silently fail the second, in an edition nobody has
    seen — which is exactly the kind of drift that surfaces as a search result that is simply absent.
    """

    def test_rows_agreeing_in_every_field_collapse(self):
        rows = producer().index_from(collection(anchor("Bohar"), anchor("Bohar")), links("Bohar"))
        assert [row["name"] for row in rows] == ["Bohar"]

    def test_a_shared_name_over_different_data_keeps_both(self):
        rows = producer().index_from(collection(
            anchor("Bohar", longitude=40.0), anchor("Bohar", longitude=-15.0), anchor("Aarna"),
        ), links("Bohar", "Aarna"))
        assert [(row["name"], row["longitude"]) for row in rows] == [
            ("Aarna", 0.0), ("Bohar", -15.0), ("Bohar", 40.0)]


class TestTheOrderIsTotal:

    def test_the_input_order_cannot_reach_the_output(self):
        forwards = producer().index_from(collection(
            anchor("Aarna"), anchor("Bohar", longitude=40.0), anchor("Bohar", longitude=-15.0)),
            links("Aarna", "Bohar"))
        backwards = producer().index_from(collection(
            anchor("Bohar", longitude=-15.0), anchor("Bohar", longitude=40.0), anchor("Aarna")),
            links("Bohar", "Aarna"))
        assert forwards == backwards


class TestTheCommittedFileIsStillWhatTheProducerEmits:
    """The question no clean checkout can answer, and the reason this file is not all in vitest.

    A tracked generated artifact drifts in ways its own content cannot reveal: a hand edit, a field
    the producer stopped writing, a gazetteer republished under the same digests. Only regenerating
    against the real source and comparing bytes tells them apart.
    """

    def fresh(self, tmp_path: Path) -> str:
        """The real entry point, run as documented — not `index_from` called directly, which would
        skip the argument parsing, the JSON writer and the exact serialisation that lands on disk."""
        out = tmp_path / "featureIndex.json"
        subprocess.run([sys.executable, str(SCRIPT), "--out", str(out)],
                       cwd=REPO_ROOT / "web", check=True, capture_output=True)
        return out.read_text(encoding="utf-8")

    def test_regenerating_reproduces_the_committed_bytes(self, tmp_path):
        if not features_geojson.labels().exists():
            pytest.skip("gazetteer not composed on this machine")
        committed = COMMITTED.read_text(encoding="utf-8")
        assert len(json.loads(committed)) == 1919, (
            "the committed index is not the whole catalogue — compare before trusting the diff"
        )
        assert self.fresh(tmp_path) == committed, (
            f"{COMMITTED.relative_to(REPO_ROOT)} is not what the producer emits — regenerate it "
            f"with `../.venv/bin/python scripts/gen_feature_index.py --out src/lib/"
            f"featureIndex.json` from web/, and read the diff rather than committing it blind"
        )

    def test_the_comparison_can_fail(self, tmp_path):
        """The control. Byte-identity between two generated things is the kind of assertion that
        passes for the wrong reason, so one perturbed row must be seen to break it."""
        if not features_geojson.labels().exists():
            pytest.skip("gazetteer not composed on this machine")
        perturbed = json.loads(self.fresh(tmp_path))
        perturbed[0]["longitude"] += 0.001
        assert json.dumps(perturbed, indent=2, ensure_ascii=False) + "\n" != COMMITTED.read_text(
            encoding="utf-8")


class TestEveryNameInTheTilesHasARowToFlyTo:
    """The two sets the globe silently assumes are one.

    A tile answers the pointer with a NAME and carries no centre — `features_geojson.CARRIED_FIELDS`
    keeps the gazetteer's unfolded longitudes away from its folded geometry — so the click path
    turns that name into a place through the committed index. A feature reaching a tile without
    reaching the index is therefore one that lights, names itself and then refuses to be flown to:
    a per-feature hole nothing else here can see, because both halves are internally consistent.

    They agree today by construction — `label_points` and the geometry outputs read the same two
    gazetteer layers — which is exactly the kind of coincidence a later filter on either side ends
    without a word. Needs the composed gazetteer, so it skips like its neighbours above.
    """

    @staticmethod
    def _named(path: Path) -> set[str]:
        collection = json.loads(path.read_text(encoding="utf-8"))
        return {
            feature["properties"]["name"]
            for feature in collection["features"]
            if feature["properties"].get("name")
        }

    def _tile_names(self) -> set[str]:
        return self._named(features_geojson.polygons()) | self._named(features_geojson.lines())

    def _require_composed(self) -> tuple[set[str], set[str]]:
        if not features_geojson.polygons().exists() or not features_geojson.lines().exists():
            pytest.skip("gazetteer not composed on this machine")
        indexed = {row["name"] for row in json.loads(COMMITTED.read_text(encoding="utf-8"))}
        tiled = self._tile_names()
        # BOTH SIDES PROVED NON-EMPTY BEFORE ANY DIFFERENCE IS TAKEN. Two empty sets differ by
        # nothing, so a mistyped path or a schema change that stopped yielding names would satisfy
        # every assertion below by having nothing to compare.
        assert len(tiled) > 1000 and len(indexed) > 1000, (len(tiled), len(indexed))
        return tiled, indexed

    def test_no_feature_in_the_tiles_is_missing_from_the_index(self):
        tiled, indexed = self._require_composed()
        assert sorted(tiled - indexed) == []

    def test_no_row_in_the_index_is_absent_from_the_tiles(self):
        """The other direction, which is a different defect: a searchable feature that can never be
        pointed at, lit, or seen to exist on the globe it claims to be on."""
        tiled, indexed = self._require_composed()
        assert sorted(indexed - tiled) == []

    def test_the_comparison_can_fail(self):
        """A planted tile-only name must surface, or both assertions above are `[] == []` over
        whatever the two reads happened to produce."""
        tiled, indexed = self._require_composed()
        assert sorted((tiled | {"Barsoom"}) - indexed) == ["Barsoom"]
        assert sorted((indexed | {"Barsoom"}) - tiled) == ["Barsoom"]
