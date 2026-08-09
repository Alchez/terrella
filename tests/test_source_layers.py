"""The one executable copy across the Python/TypeScript seam for MVT source-layer names.

WHY A TEST AND NOT AN OWNER. These strings must exist in the cutter, which is Python, and in the
style that reads the tiles, which is TypeScript. Neither language can import the other, so the rule
this repo applies when one owner is impossible holds: make one copy executable, so the drift fails
loudly instead of silently.

AND IT WAS SILENT IN BOTH DIRECTIONS BEFORE THIS. Each side pinned its own constants against its own
hand-written literals — `tests/test_countries_pmtiles.py` against "country_fill", the frontend test
against the same word — so editing a name AND its neighbouring literal in one language left the
other language untouched and every suite green. What ships from that is a globe that draws nothing:
MapLibre renders a layer whose `source-layer` matches no layer in the tile as EMPTY, with no error,
no warning and no difference in the network panel.
"""

import re
from pathlib import Path

import pytest

from pipeline import bodies, paths
from pipeline.compose import countries_pmtiles, features_pmtiles

SOURCE_LAYERS_TS = "web/src/lib/sourceLayers.ts"

#: The work-tree stage every vector cutter writes into, one directory per body. Restated from
#: `devStores.ts`'s `ARCHIVES.vector.stage`, and pinned to both cutters below — the dev server
#: derives an archive's path from this name, so a cutter writing elsewhere is a 500 that reads as a
#: missing pipeline run.
VECTOR_STAGE = "planet_vector"

#: The module that cuts each PRODUCT the frontend can name.
CUTTERS = {"countries": countries_pmtiles, "features": features_pmtiles}

#: Which product each body publishes. The Python-side copy of `VECTOR_PRODUCT`, and not a free
#: statement: `test_each_cutter_writes_into_the_body_it_serves` checks each entry against the
#: directory that cutter actually writes to.
CUT_FOR_BODY = {"earth": "countries", "mars": "features"}

# What each product's cutter calls the layer it writes for a role. The ROLE names are the frontend's
# vocabulary; the values are read off the pipeline modules rather than restated, so a rename there
# reaches this test without anyone editing it.
PRODUCED = {
    "countries": {
        "fill": countries_pmtiles.FILL_LAYER,
        "outline": countries_pmtiles.OUTLINE_LAYER,
        "hit": countries_pmtiles.HIT_LAYER,
        "line": None,
        "label": None,
    },
    "features": {
        "fill": features_pmtiles.FILL_LAYER,
        "outline": features_pmtiles.OUTLINE_LAYER,
        "hit": None,
        "line": features_pmtiles.LINE_LAYER,
        "label": features_pmtiles.LABEL_LAYER,
    },
}


def _declared(module: Path | None = None) -> dict[str, dict[str, str | None]]:
    """Read `SOURCE_LAYERS` out of the TypeScript module, as {body: {role: name or None}}.

    Parsed rather than executed because there is no Node in this suite, and asserted into rather
    than defaulted: every failure below names the file, since a regex that quietly matches nothing
    is the one way a cross-language guard can pass while covering neither side.

    TAKES THE PATH RATHER THAN READING A REDIRECTED ROOT. Monkeypatching the module global was the
    first version and it did not work: pytest imports this file as `test_source_layers`, so
    patching `tests.test_source_layers` imported a SECOND module object and patched that one, while
    the copy under test went on reading the real file. It failed loudly here; the same shape passes
    quietly whenever the real file happens to satisfy the assertion.
    """
    source = (module or paths.ROOT / SOURCE_LAYERS_TS).read_text(encoding="utf-8")
    opening = re.search(r"export const SOURCE_LAYERS\b[^=]*=\s*\{", source)
    assert opening, f"{SOURCE_LAYERS_TS} no longer declares SOURCE_LAYERS — this guard is blind"
    bodies: dict[str, dict[str, str | None]] = {}
    blocks = re.findall(r"\n  (\w+): \{\n(.*?)\n  \},", source[opening.end():], re.DOTALL)
    for body, block in blocks:
        entries: dict[str, str | None] = {}
        for role, value in re.findall(r"^\s{4}(\w+): (null|\"[^\"]*\"),\s*$", block, re.MULTILINE):
            entries[role] = None if value == "null" else value.strip('"')
        assert entries, f"{SOURCE_LAYERS_TS}: `{body}` parsed to no roles at all"
        bodies[body] = entries
    assert bodies, f"{SOURCE_LAYERS_TS}: SOURCE_LAYERS parsed to no bodies at all"
    return bodies


def _declared_products(module: Path | None = None) -> dict[str, str]:
    """Read `VECTOR_PRODUCT` out of the same TypeScript module, as {body: product}.

    Its own parser rather than a generalisation of `_declared`: the two records have different
    shapes — one body to a nested block, one body to a bare string — and a regex loose enough to
    read both would be loose enough to read a block it was never pointed at.
    """
    source = (module or paths.ROOT / SOURCE_LAYERS_TS).read_text(encoding="utf-8")
    opening = re.search(r"export const VECTOR_PRODUCT\b[^=]*=\s*\{", source)
    assert opening, f"{SOURCE_LAYERS_TS} no longer declares VECTOR_PRODUCT — this guard is blind"
    block = source[opening.end():].split("\n};", 1)[0]
    declared = dict(re.findall(r"^\s{2}(\w+): \"([^\"]*)\",\s*$", block, re.MULTILINE))
    assert declared, f"{SOURCE_LAYERS_TS}: VECTOR_PRODUCT parsed to no bodies at all"
    return declared


class TestTheTwoLanguagesAgree:
    def test_every_body_the_producers_cut_is_declared(self):
        assert set(_declared()) == set(CUT_FOR_BODY)

    def test_each_body_is_declared_to_publish_the_product_its_cutter_makes(self):
        """`VECTOR_PRODUCT` against the pipeline, which is the half the layer names cannot cover.

        A body could name every role correctly and still be declared as the wrong PRODUCT — the
        frontend branches on that word to pick a style stack, so getting it wrong points Earth's
        hit-tested, manifest-filtered country layers at Mars's tiles. Same silent symptom as a
        drifted layer name, one level up.
        """
        assert _declared_products() == CUT_FOR_BODY, (
            f"{SOURCE_LAYERS_TS} declares {_declared_products()} and the pipeline cuts "
            f"{CUT_FOR_BODY} — a body pointed at another planet's product draws that planet's "
            "style layers over its own tiles"
        )

    def test_each_cutter_writes_into_the_body_it_serves(self, subtests):
        """What makes `CUT_FOR_BODY` evidence rather than a third copy.

        Also the guard on the stage name itself: the dev server DERIVES an archive's path as
        `work/<prefix>/planet_vector/vector.pmtiles`, so a cutter writing anywhere else serves a
        500 that reads as "you have not run the pipeline" rather than as a moved output.
        """
        for body_name, product in CUT_FOR_BODY.items():
            with subtests.test(body=body_name):
                expected = bodies.work_dir(bodies.BODIES[body_name], VECTOR_STAGE)
                assert CUTTERS[product].OUT_DIR == expected, (
                    f"{product} is declared as {body_name}'s product but its cutter writes to "
                    f"{CUTTERS[product].OUT_DIR}, not {expected}"
                )

    @pytest.mark.parametrize("body", sorted(CUT_FOR_BODY))
    def test_every_role_matches_the_producer(self, body, subtests):
        declared = _declared()[body]
        produced_layers = PRODUCED[CUT_FOR_BODY[body]]
        assert set(declared) == set(produced_layers), (
            f"{body} answers for {sorted(declared)} in {SOURCE_LAYERS_TS} but the producer writes "
            f"{sorted(produced_layers)} — a role on one side only is a layer nobody styles or a "
            "style over a layer nobody cuts"
        )
        for role, produced in produced_layers.items():
            with subtests.test(role=role):
                assert declared[role] == produced, (
                    f"{body}/{role}: the cutter writes {produced!r} and {SOURCE_LAYERS_TS} asks "
                    f"for {declared[role]!r} — MapLibre paints that difference as an empty layer"
                )


class TestTheParserCanFail:
    """A cross-language guard that cannot report a difference is worse than none, because its
    silence reads exactly like agreement."""

    def test_a_renamed_record_is_refused_rather_than_skipped(self, tmp_path):
        empty = tmp_path / "sourceLayers.ts"
        empty.write_text("export const SOMETHING_ELSE = {};\n")
        with pytest.raises(AssertionError, match="this guard is blind"):
            _declared(empty)

    def test_a_drifted_name_is_read_as_drifted(self, tmp_path):
        """The positive control for the comparison itself, BUILT rather than borrowed — a case
        taken from the live file would go quiet the day the live file changed."""
        drifted = tmp_path / "sourceLayers.ts"
        drifted.write_text(
            "export const SOURCE_LAYERS = {\n"
            '  earth: {\n    fill: "country_FILL",\n    outline: null,\n  },\n'
            "};\n"
        )
        assert _declared(drifted) == {"earth": {"fill": "country_FILL", "outline": None}}
        assert _declared(drifted)["earth"]["fill"] != PRODUCED[CUT_FOR_BODY["earth"]]["fill"]

    def test_a_renamed_product_record_is_refused_rather_than_skipped(self, tmp_path):
        """The second record needs its own blindness control — one parser going quiet while the
        other keeps reporting looks exactly like half the seam being fine."""
        empty = tmp_path / "sourceLayers.ts"
        empty.write_text("export const SOURCE_LAYERS = {\n  earth: {\n    fill: null,\n  },\n};\n")
        with pytest.raises(AssertionError, match="no longer declares VECTOR_PRODUCT"):
            _declared_products(empty)

    def test_a_drifted_product_is_read_as_drifted(self, tmp_path):
        """The positive control, BUILT rather than borrowed, for the same reason as its sibling."""
        drifted = tmp_path / "sourceLayers.ts"
        drifted.write_text(
            'export const VECTOR_PRODUCT = {\n  earth: "features",\n  mars: "countries",\n};\n'
        )
        assert _declared_products(drifted) == {"earth": "features", "mars": "countries"}
        assert _declared_products(drifted) != CUT_FOR_BODY

    def test_a_body_with_no_roles_is_refused(self, tmp_path):
        """A block that parses to nothing is the failure that reads as agreement — an empty dict
        compares equal to an empty dict, so the comparison above would have nothing to disagree
        about and would pass."""
        hollow = tmp_path / "sourceLayers.ts"
        hollow.write_text("export const SOURCE_LAYERS = {\n  earth: {\n    nope\n  },\n};\n")
        with pytest.raises(AssertionError, match="parsed to no roles at all"):
            _declared(hollow)
