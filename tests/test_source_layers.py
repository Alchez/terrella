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

from pipeline import paths
from pipeline.compose import countries_pmtiles, features_pmtiles

SOURCE_LAYERS_TS = "web/src/lib/sourceLayers.ts"

# What each body's producer calls the layer it writes for a role. The ROLE names are the frontend's
# vocabulary; the values are read off the pipeline modules rather than restated, so a rename there
# reaches this test without anyone editing it.
PRODUCED = {
    "earth": {
        "fill": countries_pmtiles.FILL_LAYER,
        "outline": countries_pmtiles.OUTLINE_LAYER,
        "hit": countries_pmtiles.HIT_LAYER,
        "line": None,
        "label": None,
    },
    "mars": {
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


class TestTheTwoLanguagesAgree:
    def test_every_body_the_producers_cut_is_declared(self):
        assert set(_declared()) == set(PRODUCED)

    @pytest.mark.parametrize("body", sorted(PRODUCED))
    def test_every_role_matches_the_producer(self, body, subtests):
        declared = _declared()[body]
        assert set(declared) == set(PRODUCED[body]), (
            f"{body} answers for {sorted(declared)} in {SOURCE_LAYERS_TS} but the producer writes "
            f"{sorted(PRODUCED[body])} — a role on one side only is a layer nobody styles or a "
            "style over a layer nobody cuts"
        )
        for role, produced in PRODUCED[body].items():
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
        assert _declared(drifted)["earth"]["fill"] != PRODUCED["earth"]["fill"]

    def test_a_body_with_no_roles_is_refused(self, tmp_path):
        """A block that parses to nothing is the failure that reads as agreement — an empty dict
        compares equal to an empty dict, so the comparison above would have nothing to disagree
        about and would pass."""
        hollow = tmp_path / "sourceLayers.ts"
        hollow.write_text("export const SOURCE_LAYERS = {\n  earth: {\n    nope\n  },\n};\n")
        with pytest.raises(AssertionError, match="parsed to no roles at all"):
            _declared(hollow)
