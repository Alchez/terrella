"""naturalearth: the one home for the vectors seven modules share.

Two things under test. The layer NAMING RULE, because Natural Earth repeats each layer's name as
its directory and as every component's stem, and hand-writing that doubling is what five call sites
used to do. And the VOCABULARY PARITY between this module and `download_naturalearth.sh`, which is
the writer — shell cannot import Python, so the list exists twice and only a test can hold the two
copies together.
"""

import os
import re
import subprocess
import sys

import pytest

from pipeline import naturalearth, paths

ACQUIRER = paths.ROOT / "pipeline/acquire/download_naturalearth.sh"


def acquired_layers() -> set[str]:
    """The layer names `download_naturalearth.sh` actually fetches, read out of its own array.

    Parsed rather than restated: a second hand-kept list here would be a third copy of the fact,
    and the drift it exists to catch is precisely someone editing one list and not the other.
    """
    script = ACQUIRER.read_text(encoding="utf-8")
    block = re.search(r"^LAYERS=\((.*?)^\)", script, re.MULTILINE | re.DOTALL)
    assert block is not None, f"no LAYERS=( … ) array in {ACQUIRER} — the parser needs updating"
    return {line.rsplit("/", 1)[-1] for line in re.findall(r'"([^"]+)"', block.group(1))}


class TestTheVocabularyMatchesTheAcquirer:
    def test_every_layer_this_module_knows_is_actually_downloaded(self):
        """The direction that bites at runtime: a name here the acquirer never fetches resolves to
        a path that will not exist, and fails at `shapefile.Reader` looking like a failed download
        rather than like a name that was never going to work."""
        assert naturalearth.LAYERS <= acquired_layers()

    def test_every_downloaded_layer_is_addressable(self):
        """The other direction, which fails quietly instead: a layer the acquirer fetches and this
        module does not know is disk nobody can reach through `layer()`, so the next reader that
        wants it re-invents the longhand join this module exists to delete."""
        assert acquired_layers() <= naturalearth.LAYERS

    def test_the_parser_is_reading_a_real_array(self):
        """The control. Both assertions above are satisfied by two empty sets, which is exactly
        what a parser aimed at a renamed variable would produce."""
        found = acquired_layers()
        assert len(found) >= 5
        assert all(name.startswith("ne_10m_") for name in found)


class TestTheAcquirerWritesWhereThisModuleReads:
    """The writer and the readers must resolve one directory, and they resolve it in two languages.

    DRIVES THE REAL SCRIPT, and it can do so without touching the network because the acquirer is
    idempotent: a layer whose directory already exists is skipped. Pre-creating all seven in a
    throwaway store means every branch short-circuits.

    THE ASSERTION IS ON WHAT THE SCRIPT REPORTS, not on what it skipped, and that distinction is
    the whole test. On a developer box BOTH roots are populated, so "it skipped everything" is
    equally true of a script writing into the checkout — the check would pass while measuring
    nothing. The final line names `DEST`, which is the one observable that differs.
    """

    def test_maps_data_moves_the_acquirers_destination(self, tmp_path):
        store = tmp_path / "store"
        for name in naturalearth.LAYERS:
            (store / "raw/naturalearth" / name).mkdir(parents=True)
        result = subprocess.run(["bash", str(ACQUIRER)], capture_output=True, text=True,
                                env={**os.environ, "MAPS_DATA": str(store)})
        assert result.returncode == 0, result.stderr
        assert f"done: {store / 'raw/naturalearth'} " in result.stdout
        assert result.stdout.count("skip ") == len(naturalearth.LAYERS), (
            "a layer was fetched — the throwaway store is incomplete and this test just hit "
            f"the network:\n{result.stdout}")

    def test_it_lands_exactly_where_python_looks(self, tmp_path):
        """The two languages agreeing, asserted rather than assumed: same override, same answer."""
        store = tmp_path / "store"
        for name in naturalearth.LAYERS:
            (store / "raw/naturalearth" / name).mkdir(parents=True)
        result = subprocess.run(["bash", str(ACQUIRER)], capture_output=True, text=True,
                                env={**os.environ, "MAPS_DATA": str(store)})
        written = result.stdout.strip().rsplit("\n", 1)[-1].removeprefix("done: ").split(" (")[0]
        # A subprocess because the constant binds at import; reloading in-process would be a lie.
        reader = subprocess.run(
            [sys.executable, "-c", "from pipeline import naturalearth; print(naturalearth.DIR)"],
            capture_output=True, text=True, check=True, cwd=paths.ROOT,
            env={**os.environ, "MAPS_DATA": str(store)})
        assert written == reader.stdout.strip()


class TestTheLayerRule:
    def test_the_name_appears_as_both_directory_and_stem(self):
        assert naturalearth.layer("ne_10m_coastline") == \
               naturalearth.DIR / "ne_10m_coastline/ne_10m_coastline.shp"

    def test_it_reads_the_store_at_call_time(self, monkeypatch, tmp_path):
        """So a relocated `MAPS_DATA` moves the layers with it, rather than freezing whichever
        store happened to be set when the module was first imported."""
        monkeypatch.setattr(naturalearth, "DIR", tmp_path / "vectors")
        assert naturalearth.layer("ne_10m_lakes").is_relative_to(tmp_path / "vectors")

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
