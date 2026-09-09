"""naturalearth: the one home for the vectors seven modules share.

Two things under test. The layer NAMING RULE, because Natural Earth repeats each layer's name as
its directory and as every component's stem, and hand-writing that doubling is what five call sites
used to do. And that the ACQUIRER writes where these readers look, which is a claim about a whole
run rather than about a path expression.

THE VOCABULARY IS NO LONGER TWO COPIES, so the pair of parity assertions that used to stand here
is gone rather than kept as a tautology. `naturalearth.LAYERS` is built from the acquirer's own
table, and the parser that used to read a bash array went with the script it parsed.
"""

import os
import subprocess
import sys

import pytest

from pipeline import datasets, naturalearth, paths
from pipeline.acquire.earth import download_naturalearth

ACQUIRER = ("python", "-m", "pipeline.acquire.earth.download_naturalearth")


def test_the_vocabulary_is_derived_and_not_empty():
    """The control the derivation still needs: `frozenset()` of a renamed table is an empty
    vocabulary, and `layer()` would then refuse every name rather than resolve one."""
    assert naturalearth.LAYERS == frozenset(download_naturalearth.LAYERS)
    assert len(naturalearth.LAYERS) >= 5
    assert all(name.startswith("ne_10m_") for name in naturalearth.LAYERS)


class TestTheAcquirerWritesWhereThisModuleReads:
    """DRIVES THE REAL ACQUIRER, and can do so without touching the network because it is
    idempotent: a layer whose directory already exists is skipped. Pre-creating all seven in a
    throwaway store means every branch short-circuits.

    THE ASSERTION IS ON WHAT THE RUN REPORTS, not on what it skipped, and that distinction is the
    whole test. On a developer box BOTH roots are populated, so "it skipped everything" is equally
    true of an acquirer writing into the checkout, and the check would pass while measuring
    nothing. The final line names the destination, which is the one observable that differs.
    """

    def _prepared(self, tmp_path):
        store = tmp_path / "store"
        for name in naturalearth.LAYERS:
            (store / "raw/naturalearth" / name).mkdir(parents=True)
        return store, subprocess.run([sys.executable, *ACQUIRER[1:]], capture_output=True,
                                     text=True, cwd=paths.ROOT, check=False,
                                     env={**os.environ, "MAPS_DATA": str(store)})

    def test_maps_data_moves_the_acquirers_destination(self, tmp_path):
        store, result = self._prepared(tmp_path)
        assert result.returncode == 0, result.stderr
        assert f"done: {store / 'raw/naturalearth'} " in result.stdout
        assert result.stdout.count("skip ") == len(naturalearth.LAYERS), (
            "a layer was fetched — the throwaway store is incomplete and this test just hit "
            f"the network:\n{result.stdout}")

    def test_it_lands_exactly_where_python_looks(self, tmp_path):
        """Asserted rather than assumed, because the acquirer being Python is not the same claim as
        it resolving the store through `datasets`: a module-level path built at import would answer
        this differently, and a subprocess is what makes the override real rather than patched."""
        store, result = self._prepared(tmp_path)
        assert result.returncode == 0, result.stderr
        written = result.stdout.strip().rsplit("\n", 1)[-1].removeprefix("done: ").split(" (")[0]
        reader = subprocess.run(
            [sys.executable, "-c", "from pipeline import datasets; print(datasets.naturalearth())"],
            capture_output=True, text=True, check=True, cwd=paths.ROOT,
            env={**os.environ, "MAPS_DATA": str(store)})
        assert written == reader.stdout.strip()


class TestTheLayerRule:
    def test_the_name_appears_as_both_directory_and_stem(self):
        assert naturalearth.layer("ne_10m_coastline") == \
               datasets.naturalearth() / "ne_10m_coastline/ne_10m_coastline.shp"

    def test_it_reads_the_store_at_call_time(self, monkeypatch, tmp_path):
        """So a relocated `MAPS_DATA` moves the layers with it, rather than freezing whichever
        store happened to be set when the module was first imported.

        THE STORE ITSELF IS MOVED, not this module's own copy of where it is. Redirecting a
        module-level `DIR` was what stood here, and it could only ever prove that `layer` read
        that constant — the freeze it claims to rule out lived in the constant.
        """
        monkeypatch.setattr(paths, "DATA", tmp_path / "elsewhere")
        assert naturalearth.layer("ne_10m_lakes").is_relative_to(tmp_path / "elsewhere")

    def test_an_explicit_directory_wins(self):
        """`--ne-dir` on the two entry points that expose it — the rule travels, the root does not."""
        assert naturalearth.layer("ne_10m_lakes", directory=paths.ROOT / "elsewhere") == \
               paths.ROOT / "elsewhere/ne_10m_lakes/ne_10m_lakes.shp"

    def test_an_unknown_layer_names_the_ones_that_exist(self):
        """A typo in a layer name is otherwise indistinguishable from a dataset we never fetched,
        and both look like a missing file several frames later."""
        with pytest.raises(ValueError, match="unknown Natural Earth layer"):
            naturalearth.layer("ne_10m_coastlines")  # the plural: the realistic slip

    def test_the_refusal_names_the_vocabulary(self):
        with pytest.raises(ValueError, match="ne_10m_coastline"):
            naturalearth.layer("ne_50m_coastline")  # a real Natural Earth scale we do not fetch
