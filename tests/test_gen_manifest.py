"""Contract for the gallery manifest's search terms.

THE PURE FUNCTION IS WHAT IS TESTED, not a generated manifest, because `countries.json` is
gitignored — a suite that read it would pass on this machine and skip on every clean checkout,
which is the shape that reads exactly like coverage and is not. `search_terms` takes a record dict
and returns a list, so every rule it enforces is reachable with a literal.

The one thing a literal cannot check is whether `SEARCH_FIELDS` still names columns Natural Earth
actually ships, and that is deliberately left to the data-bound assertions at the bottom, which skip
without the shapefile. What does NOT skip is the guard on the `_EH` spellings: that choice was made
against measured data, the alternative is a plausible-looking simplification, and reverting it would
break five countries silently.
"""

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "web/scripts/gen_manifest.py"
CONTRACT = REPO_ROOT / "web/src/lib/manifest.ts"


def producer():
    """The generator module, loaded by path — `web/scripts/` is a script directory, not a package."""
    spec = importlib.util.spec_from_file_location("gen_manifest", SCRIPT)
    assert spec is not None and spec.loader is not None, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = producer()


def record(**fields: str) -> dict:
    """One Natural Earth attribute row, with every search column absent unless named."""
    return {"ADMIN": "Example", **fields}


class TestWhatBecomesTypeable:
    def test_the_columns_are_taken_in_order(self):
        terms = GEN.search_terms(
            record(NAME="Short", NAME_LONG="Longer", NAME_EN="English", FORMAL_EN="Formal",
                   NAME_ALT="Other", ABBREV="Sh.", ISO_A2_EH="SH", ISO_A3_EH="SHO"),
            "Example",
        )
        assert terms == ["Short", "Longer", "English", "Formal", "Other", "Sh.", "SH", "SHO"], (
            "the output order is the field order, which is what makes a re-run on unchanged "
            "data rewrite unchanged bytes"
        )

    def test_the_display_name_is_not_repeated(self):
        terms = GEN.search_terms(record(NAME="Netherlands", FORMAL_EN="Kingdom of the Netherlands"),
                                 "Netherlands")
        assert terms == ["Kingdom of the Netherlands"]

    def test_a_spelling_two_columns_agree_on_appears_once(self):
        terms = GEN.search_terms(record(NAME="Czechia", NAME_LONG="Czech Republic",
                                        FORMAL_EN="Czech Republic"), "Czechia")
        assert terms == ["Czech Republic"], "first spelling wins, later repeats are dropped"

    def test_natural_earths_null_is_not_a_search_term(self):
        terms = GEN.search_terms(record(FORMAL_EN="Republic of Somaliland",
                                        ISO_A2_EH=GEN.NE_NULL, ISO_A3_EH=GEN.NE_NULL),
                                 "Somaliland")
        assert terms == ["Republic of Somaliland"], (
            f"{GEN.NE_NULL!r} is a null, and a country whose code is contested must not become "
            "reachable by typing it"
        )

    def test_blank_and_whitespace_columns_are_dropped(self):
        terms = GEN.search_terms(record(NAME_ALT="", FORMAL_EN="   ", ABBREV=" Ex. "), "Example")
        assert terms == ["Ex."]

    def test_a_country_with_nothing_but_its_name_yields_an_empty_list(self):
        assert GEN.search_terms(record(), "Example") == [], (
            "an empty list, never None — the field is always present in the payload, because "
            "`Country.searchTerms` is not optional and a consumer maps over it unguarded"
        )


class TestTheIsoColumnsAreTheEhVariants:
    """The one design choice here that a plausible edit would silently undo.

    Natural Earth ships `ISO_A2` beside `ISO_A2_EH`, and the bare pair is the obvious-looking name.
    Measured over the 203 in-scope countries, the bare columns are null for five of them and carry a
    worldview-loaded value for a sixth; the `_EH` pair is null for strictly fewer and never disagrees
    except where the bare column is the loaded one. These assertions are what stops that measurement
    from having to be taken twice.
    """

    def test_the_bare_iso_columns_are_not_read(self):
        assert "ISO_A2" not in GEN.SEARCH_FIELDS and "ISO_A3" not in GEN.SEARCH_FIELDS, (
            "the bare ISO columns are null for France, Norway and three others — reading them "
            "loses 'FR', 'FRA', 'NO' and 'NOR' with every gate still green"
        )

    def test_the_eh_iso_columns_are_read(self):
        assert "ISO_A2_EH" in GEN.SEARCH_FIELDS and "ISO_A3_EH" in GEN.SEARCH_FIELDS


@pytest.fixture(scope="module")
def records():
    """Every in-scope attribute row, read once. Skips where Natural Earth is not acquired."""
    pytest.importorskip("shapefile")
    from pipeline import naturalearth
    shp = naturalearth.layer("ne_10m_admin_0_countries")
    if not shp.exists():
        pytest.skip(f"{shp} not acquired")
    return GEN.records_by_admin(shp)


def declared_fields(source: str, interface: str) -> list[str]:
    """The property names of one TypeScript interface.

    Takes the source rather than reading `manifest.ts` itself, so the comment stripping below can be
    shown to work on a literal instead of asserted. It is not decoration: a block comment whose
    continuation lines carry no `*` gutter puts prose at the start of a line, and `legacy: was the
    old name` reads as a field declaration to any regex cheap enough to belong in a test.
    """
    body = re.search(rf"export interface {interface} \{{(.*?)\n\}}", source, re.DOTALL)
    assert body, f"no `export interface {interface}` — was it renamed?"
    code = re.sub(r"/\*.*?\*/", "", body.group(1), flags=re.DOTALL)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.MULTILINE)
    return re.findall(r"^\s*(\w+)\??\s*:", code, re.MULTILINE)


def country_fields() -> list[str]:
    """What `Country` in `web/src/lib/manifest.ts` declares today."""
    return declared_fields(CONTRACT.read_text(), "Country")


class TestTheTwoHalvesOfTheContract:
    """`Country` in TypeScript and the payload in Python, which nothing else compares.

    The manifest is gitignored, so `astro check` type-checks every consumer against an interface no
    build ever holds a real file up to: a field added on one side alone produces `undefined` at
    runtime and a clean gate on both. The header on `manifest.ts` has asked for lockstep in prose
    since the wrapper was written; this is that sentence made to fail.
    """

    def test_the_payload_and_the_interface_name_the_same_fields(self, tmp_path):
        emitted = GEN.country_row(
            "example",
            {"admin": "Example", "frame": (0.0, 0.0, 1.0, 1.0)},
            {"CONTINENT": "Europe"},
            tmp_path,
        )
        assert sorted(emitted) == sorted(country_fields()), (
            "gen_manifest.py's payload and `Country` in web/src/lib/manifest.ts have drifted — "
            "a field on one side alone is `undefined` at runtime with every gate green"
        )

    def test_prose_inside_a_comment_is_not_read_as_a_field(self):
        source = (
            "export interface Country {\n"
            "  /*\n"
            "  legacy: this line has no asterisk gutter and would parse as a declaration\n"
            "  */\n"
            "  // renamed: from an older spelling\n"
            "  /** One country. */\n"
            "  slug: string;\n"
            "  native?: number | null;\n"
            "}\n"
        )
        assert declared_fields(source, "Country") == ["slug", "native"], (
            "a phantom field read out of prose makes the lockstep guard fail on a contract that "
            "is actually in step, which is the way a guard gets deleted rather than believed"
        )

    def test_an_unrendered_country_still_carries_every_field(self, tmp_path):
        emitted = GEN.country_row("example", {"admin": "Example", "frame": (0.0, 0.0, 1.0, 1.0)},
                                  {}, tmp_path)
        assert emitted["rendered"] is False and emitted["native"] is None
        assert sorted(emitted) == sorted(country_fields()), (
            "the empty variant store is the shape a consumer sees for a country awaiting its "
            "hero, and it must be missing a value rather than a key"
        )


class TestAgainstNaturalEarth:
    """Whether `SEARCH_FIELDS` still names real columns. Skips without the shapefile."""

    def test_every_named_column_exists(self, records):
        row = records["France"]
        missing = [field for field in GEN.SEARCH_FIELDS if field not in row]
        assert not missing, (
            f"Natural Earth has no such column(s): {missing} — a renamed column yields an empty "
            "string for every country, so the search silently loses a whole class of query"
        )

    def test_france_is_reachable_by_its_iso_codes(self, records):
        terms = GEN.search_terms(records["France"], "France")
        assert "FR" in terms and "FRA" in terms, (
            "France is the live instance of the bare-column null; if this fails the `_EH` choice "
            "has been undone or Natural Earth has changed which column it fills"
        )

    def test_the_vatican_is_reachable_as_the_holy_see(self, records):
        assert "Holy See" in GEN.search_terms(records["Vatican"], "Vatican"), (
            "NAME_ALT is empty for all but four in-scope countries, so it is easy to read as "
            "dead weight — this is one of the three it carries"
        )

    def test_the_english_column_carries_what_the_admin_name_dropped(self, records):
        # NAME_EN disagrees with ADMIN for four countries and two of those are live usage. Both are
        # named, because a column that agrees 199 times out of 203 is the kind a tidy-up deletes.
        assert "Cape Verde" in GEN.search_terms(records["Cabo Verde"], "Cabo Verde"), (
            "the 2013 rename is not what English writes — 'Cape Verde' lives only in NAME_EN"
        )
        assert "Vatican City" in GEN.search_terms(records["Vatican"], "Vatican"), (
            "every query term must match, and no token in 'Vatican' is prefixed by 'city' — "
            "without NAME_EN the query 'vatican city' returns nothing at all"
        )


class TestAuthoredAliases:
    """`also` — the names Natural Earth publishes in no column the manifest reads."""

    def test_authored_names_land_after_the_columns(self):
        terms = GEN.search_terms(record(NAME="Myanmar", ABBREV="Myan."), "Myanmar", ["Burma"])
        assert terms == ["Myan.", "Burma"], (
            "column order then authored order — a stable order is what lets an unchanged config "
            "rewrite unchanged bytes"
        )

    def test_an_authored_name_matching_a_column_is_dropped(self):
        terms = GEN.search_terms(record(NAME_EN="Cape Verde"), "Cabo Verde", ["Cape Verde"])
        assert terms == ["Cape Verde"], "one string, whichever source offered it first"

    def test_an_authored_name_equal_to_the_display_name_is_dropped(self):
        assert GEN.search_terms(record(), "Myanmar", ["Myanmar"]) == []

    def test_the_default_is_no_aliases(self):
        assert GEN.search_terms(record(ABBREV="Myan."), "Myanmar") == ["Myan."]

    def test_blank_and_repeated_entries_cannot_reach_the_payload(self):
        # `country_config._valid_also` rejects these at load, so this is the second line rather
        # than the first — the producer must not emit junk even if it is handed junk.
        assert GEN.search_terms(record(), "X", ["", "  ", "Burma", "Burma"]) == ["Burma"]

    def test_a_row_carries_the_authored_aliases(self, tmp_path):
        """The ROW, not just `search_terms` — the threading is its own failure and its own silence.

        Called rather than read: a scan of `country_row`'s source would see the argument spelled
        and never learn whether the value arrives. With the aliases dropped the manifest is still
        well-formed and every other guard still passes; ten countries just quietly stop answering.
        """
        row = GEN.country_row(
            "myanmar",
            {"admin": "Myanmar", "frame": (92.0, 9.0, 102.0, 29.0), "also": ["Burma"]},
            record(NAME="Myanmar", CONTINENT="Asia"),
            tmp_path,
        )
        assert "Burma" in row["searchTerms"]


class TestTheAliasesActuallyShipped:
    """The real `config/countries.toml` against the real shapefile. Skips without either."""

    def test_no_alias_restates_something_the_columns_already_give(self, records):
        """An alias must be a name `SEARCH_FIELDS` does NOT already emit.

        Not "absent from the shapefile" — that rule is wrong, and this guard asserted it first and
        failed. "Burma" is in `NAME_CIAWF` and "Türkiye" in `NAME_TR`; both are real columns and
        both are deliberately unread, one publishing sort keys and the other 153 Turkish names.
        What must never happen is one name having two homes, because only the authored one goes
        stale and nothing would say so.
        """
        from pipeline.frame.country_config import (
            build_scope,
            load_config,
            load_ne_rows,
            resolve,
        )
        cfg = load_config()
        _sf, rows = load_ne_rows()
        scope = build_scope(cfg, rows)
        offenders = []
        for slug, table in cfg.get("countries", {}).items():
            aliases = table.get("also", [])
            if not aliases or slug not in scope:
                continue
            resolved = resolve(slug, scope[slug], cfg)
            assert resolved is not None, f"{slug}: carries aliases but does not resolve"
            admin = resolved["admin"]
            from_columns = {t.casefold() for t in GEN.search_terms(records.get(admin, {}), admin)}
            from_columns.add(admin.casefold())
            offenders += [(slug, a) for a in aliases if a.casefold() in from_columns]
        assert not offenders, (
            f"already emitted from SEARCH_FIELDS, so `also` would be a second home: {offenders}"
        )

    def test_every_aliased_slug_is_a_country_that_exists(self, records):
        """A typo'd slug is silent: the table parses, validates, and reaches no country at all.

        `records` is unused and is the SKIP GATE. This class's docstring claimed both tests skip
        without the shapefile and only the sibling did, because a skip comes from requesting the
        fixture rather than from saying so — so on a clean checkout this called `load_ne_rows`,
        which `sys.exit`s, and CI went red on a machine that simply has no Natural Earth.
        """
        assert records is not None
        from pipeline.frame.country_config import build_scope, load_config, load_ne_rows
        cfg = load_config()
        _sf, rows = load_ne_rows()
        scope = build_scope(cfg, rows)
        stray = [slug for slug, table in cfg.get("countries", {}).items()
                 if table.get("also") and slug not in scope]
        assert not stray, f"aliases authored against slugs no country resolves to: {stray}"
