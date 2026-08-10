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


class TestTheRowIsReshapedForTheWeb:
    def test_the_gazetteers_field_names_become_the_frontends(self, subtests):
        [row] = producer().index_from(collection(anchor("Gale")))
        for key in ("name", "cleanName", "type", "origin", "diameterKm", "longitude", "latitude"):
            with subtests.test(key=key):
                assert key in row
        assert "clean_name" not in row and "diameter" not in row

    def test_a_zero_diameter_becomes_null_rather_than_zero(self):
        """The gazetteer sizes two features at zero, and the tiles DROP a falsy diameter — so
        `candidateFrom` already reads them as unsized. A literal 0 here would leave one catalogue
        disagreeing with itself about which features have a size, and frame them at no kilometres."""
        [row] = producer().index_from(collection(anchor("Candor Chaos", diameter="0.000000")))
        assert row["diameterKm"] is None

    def test_the_publishers_fifteen_decimals_are_quantised_to_metres(self):
        [row] = producer().index_from(collection(anchor("Blunck", diameter="66.484999999999999")))
        assert row["diameterKm"] == 66.485

    def test_the_folded_centre_is_copied_rather_than_refolded(self):
        """The anchors arrive folded. Refolding here is how the two longitude conventions get mixed
        back together — a second fold of -21.57 is a no-op, but a second fold of +200 is not."""
        [row] = producer().index_from(collection(anchor("Aarna", longitude=-21.57, latitude=14.7)))
        assert (row["longitude"], row["latitude"]) == (-21.57, 14.7)


class TestOneFeatureEnteredTwiceBecomesOneRow:
    """The gazetteer publishes Bohar twice, agreeing on every attribute it carries.

    The collapse is on the WHOLE ROW rather than on the name, and the two tests below are the two
    halves of that: identical rows are one feature, and a shared name over differing data is two.
    Collapsing by name would pass the first and silently fail the second, in an edition nobody has
    seen — which is exactly the kind of drift that surfaces as a search result that is simply absent.
    """

    def test_rows_agreeing_in_every_field_collapse(self):
        rows = producer().index_from(collection(anchor("Bohar"), anchor("Bohar")))
        assert [row["name"] for row in rows] == ["Bohar"]

    def test_a_shared_name_over_different_data_keeps_both(self):
        rows = producer().index_from(collection(
            anchor("Bohar", longitude=40.0), anchor("Bohar", longitude=-15.0), anchor("Aarna"),
        ))
        assert [(row["name"], row["longitude"]) for row in rows] == [
            ("Aarna", 0.0), ("Bohar", -15.0), ("Bohar", 40.0)]


class TestTheOrderIsTotal:

    def test_the_input_order_cannot_reach_the_output(self):
        forwards = producer().index_from(collection(
            anchor("Aarna"), anchor("Bohar", longitude=40.0), anchor("Bohar", longitude=-15.0)))
        backwards = producer().index_from(collection(
            anchor("Bohar", longitude=-15.0), anchor("Bohar", longitude=40.0), anchor("Aarna")))
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
        if not features_geojson.LABELS.exists():
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
        if not features_geojson.LABELS.exists():
            pytest.skip("gazetteer not composed on this machine")
        perturbed = json.loads(self.fresh(tmp_path))
        perturbed[0]["longitude"] += 0.001
        assert json.dumps(perturbed, indent=2, ensure_ascii=False) + "\n" != COMMITTED.read_text(
            encoding="utf-8")
