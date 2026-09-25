"""Contract for the gallery manifest: its search terms, its two halves, and the download files.

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
import os
import re
import sys
from pathlib import Path

import pytest
from conftest import HERO_SOURCES, write_hero_master
from PIL import Image

from pipeline import attribution
from pipeline.compose import downloads, hero_variants

pytestmark = pytest.mark.filterwarnings("ignore::rasterio.errors.NotGeoreferencedWarning")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "web/scripts/gen_manifest.py"
CONTRACT = REPO_ROOT / "web/src/lib/manifest.ts"

SLUG, NAME = "example", "Example"
WIDTH, HEIGHT = 64, 48
RESOLVED = {"admin": NAME, "name": NAME, "frame": (0.0, 0.0, 1.0, 1.0), "has_hero": True}
LISTED = {**RESOLVED, "has_hero": False}


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


def encode(master: Path, out: Path, long_edge: int = WIDTH) -> None:
    hero_variants.make_variant(master, True, long_edge, hero_variants.quality_for(long_edge), out)


@pytest.fixture
def renders(tmp_path: Path) -> Path:
    """A render store holding one country's master and full-size WebP, both stamped."""
    (tmp_path / "heroes").mkdir()
    (tmp_path / "variants").mkdir()
    master = tmp_path / "heroes" / f"{SLUG}.png"
    write_hero_master(master, WIDTH, HEIGHT, seed=0)
    encode(master, tmp_path / "variants" / f"{SLUG}-{WIDTH}.webp")
    downloads.stamp_country(master, tmp_path / "variants", NAME)
    return tmp_path


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

    def test_the_payload_and_the_interface_name_the_same_fields(self, renders):
        emitted = GEN.country_row(SLUG, RESOLVED, {"CONTINENT": "Europe"}, renders)
        assert sorted(emitted) == sorted(country_fields()), (
            "gen_manifest.py's payload and `Country` in web/src/lib/manifest.ts have drifted — "
            "a field on one side alone is `undefined` at runtime with every gate green"
        )

    def test_the_download_record_and_its_interface_name_the_same_fields(self, renders):
        emitted = GEN.country_row(SLUG, RESOLVED, {}, renders)["download"]
        assert sorted(emitted) == sorted(declared_fields(CONTRACT.read_text(), "DownloadFiles"))

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
        emitted = GEN.country_row("example", RESOLVED, {}, tmp_path)
        assert emitted["rendered"] is False and emitted["native"] is None
        assert emitted["listedOnly"] is False, "a hero not yet rendered is still one to come"
        assert emitted["download"] is None
        assert sorted(emitted) == sorted(country_fields()), (
            "the empty variant store is the shape a consumer sees for a country awaiting its "
            "hero, and it must be missing a value rather than a key"
        )


class TestARenamedCountry:
    def test_shows_its_config_name_and_keeps_natural_earths_for_the_globe(self, tmp_path):
        """The globe matches a country to its shapes by ADMIN, so that key must survive a rename;
        a visitor reads `name`."""
        emitted = GEN.country_row("hongkong", {**RESOLVED, "admin": "Hong Kong S.A.R.",
                                               "name": "Hong Kong"}, {}, tmp_path)
        assert (emitted["name"], emitted["admin"]) == ("Hong Kong", "Hong Kong S.A.R.")


class TestAListedOnlyCountry:
    """A place the globe and its search carry with no hero, told apart from a hero not yet rendered."""

    def test_says_it_is_listed_only_and_offers_nothing(self, tmp_path):
        emitted = GEN.country_row(SLUG, LISTED, {}, tmp_path)
        assert emitted["listedOnly"] is True
        assert emitted["rendered"] is False and emitted["download"] is None
        assert sorted(emitted) == sorted(country_fields())

    def test_one_with_hero_files_on_disk_is_refused(self, renders):
        """The config says no hero and the store holds one, so one of them is wrong."""
        with pytest.raises(ValueError, match=SLUG):
            GEN.country_row(SLUG, LISTED, {}, renders)


class TestTheDownloadFiles:
    """The full-size WebP and PNG a rendered country's page offers, and the refusal to offer one
    that lacks the credit for the name this manifest publishes or predates its master."""

    def test_a_rendered_country_states_the_pixels_and_bytes_of_both_files(self, renders):
        webp = renders / "variants" / f"{SLUG}-{WIDTH}.webp"
        png = renders / "variants" / f"{SLUG}-{WIDTH}.png"
        for offered in (webp, png):
            with Image.open(offered) as image:
                assert image.size == (WIDTH, HEIGHT)
        assert GEN.country_row(SLUG, RESOLVED, {}, renders)["download"] == {
            "width": WIDTH, "height": HEIGHT,
            "webpBytes": webp.stat().st_size, "pngBytes": png.stat().st_size,
        }

    @pytest.mark.parametrize("extension", ["webp", "png"])
    def test_a_file_that_was_never_stamped_is_refused(self, renders, extension):
        master = renders / "heroes" / f"{SLUG}.png"
        unstamped = renders / "variants" / f"{SLUG}-{WIDTH}.{extension}"
        if extension == "webp":
            encode(master, unstamped)
        else:
            unstamped.unlink()
        with pytest.raises(GEN.StaleFiles, match=rf"{re.escape(unstamped.name)}.*downloads stamp"):
            GEN.country_row(SLUG, RESOLVED, {}, renders)

    def test_files_stamped_under_another_name_are_refused(self, renders):
        with pytest.raises(GEN.StaleFiles, match="downloads stamp"):
            GEN.country_row(SLUG, {**RESOLVED, "name": "Renamed"}, {}, renders)

    def test_a_copy_made_before_its_master_last_changed_is_refused(self, renders):
        master = renders / "heroes" / f"{SLUG}.png"
        later = master.stat().st_mtime_ns + 1_000_000_000
        os.utime(master, ns=(later, later))
        attribution.write_hero_record(master, HERO_SOURCES)
        # The WebP redone since, and the copy not.
        os.utime(renders / "variants" / f"{SLUG}-{WIDTH}.webp", ns=(later, later))
        with pytest.raises(GEN.StaleFiles, match=rf"{SLUG}-{WIDTH}\.png") as refusal:
            GEN.country_row(SLUG, RESOLVED, {}, renders)
        assert f"{SLUG}-{WIDTH}.webp" not in str(refusal.value)

    def test_a_rendered_country_names_what_its_render_read(self, renders):
        assert GEN.country_row(SLUG, RESOLVED, {}, renders)["heroSources"] == list(HERO_SOURCES)

    def test_an_unrendered_country_names_nothing(self, tmp_path):
        assert GEN.country_row(SLUG, RESOLVED, {}, tmp_path)["heroSources"] == []

    def test_a_master_with_no_record_is_refused_with_its_fix(self, renders):
        attribution.hero_record_path(renders / "heroes" / f"{SLUG}.png").unlink()
        with pytest.raises(GEN.StaleFiles, match=r"no record.*pipeline\.batch"):
            GEN.country_row(SLUG, RESOLVED, {}, renders)

    def test_a_master_changed_after_its_record_is_refused(self, renders):
        master = renders / "heroes" / f"{SLUG}.png"
        later = master.stat().st_mtime_ns + 1_000_000_000
        os.utime(master, ns=(later, later))
        with pytest.raises(GEN.StaleFiles, match="after its record"):
            GEN.country_row(SLUG, RESOLVED, {}, renders)

    def test_a_full_size_webp_that_is_not_its_masters_image_is_refused(self, renders):
        """Even when the WebP is the newer file, as a store copied without its times can leave it."""
        master = renders / "heroes" / f"{SLUG}.png"
        webp = renders / "variants" / f"{SLUG}-{WIDTH}.webp"
        write_hero_master(master, WIDTH, HEIGHT - 8, seed=0)
        downloads.stamp_country(master, renders / "variants", NAME)
        later = master.stat().st_mtime_ns + 1_000_000_000
        os.utime(webp, ns=(later, later))
        assert downloads.unstamped(master, renders / "variants", NAME) == []
        with pytest.raises(GEN.StaleFiles, match="not its master's image"):
            GEN.country_row(SLUG, RESOLVED, {}, renders)


#: A first render whose own size, 960, is also a rung of a larger render's ladder.
FIRST = (960, 576)
#: Each fix as the refusal must spell it, written out here rather than read from the script.
LADDER = f"python -m pipeline.compose.hero_variants --only {SLUG} --force"
OVERLAYS = f"python -m pipeline.compose.gen_spotlight --only {SLUG} --force"
STAMP = f"python -m pipeline.compose.downloads stamp --only {SLUG}"


def run_ladder(*flags: str) -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sys, "argv", ["hero_variants", "--only", SLUG, *flags])
        hero_variants.main()


def rerender(store: Path, width: int, height: int) -> Path:
    """A new master, with every file already in the store moved ten seconds into the past."""
    for path in store.rglob("*"):
        if path.is_file():
            earlier = path.stat().st_mtime_ns - 10_000_000_000
            os.utime(path, ns=(earlier, earlier))
    master = store / "heroes" / f"{SLUG}.png"
    write_hero_master(master, width, height, seed=2)
    return master


def refusal(store: Path) -> str:
    with pytest.raises(GEN.StaleFiles) as refused:
        GEN.country_row(SLUG, RESOLVED, {}, store)
    return str(refused.value)


def follow(store: Path, message: str) -> None:
    """Do what the refusal says, in its order, and nothing else."""
    for step in message.split("; fix: ", 1)[1].split(", then "):
        if step.startswith("delete "):
            names, folder = step.removeprefix("delete ").split(" from ")
            for name in names.split(" "):
                (Path(folder) / name).unlink()
        elif step == LADDER:
            run_ladder("--force")
        elif step == STAMP:
            downloads.stamp_country(store / "heroes" / f"{SLUG}.png", store / "variants", NAME)
        else:
            pytest.fail(f"the refusal names a step this test cannot follow: {step!r}")


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> Path:
    """One country rendered at FIRST, then laddered and stamped by the real writers."""
    for folder in ("heroes", "variants"):
        (tmp_path / folder).mkdir()
    monkeypatch.setattr(hero_variants, "HEROES", tmp_path / "heroes")
    monkeypatch.setattr(hero_variants, "VARIANTS", tmp_path / "variants")
    monkeypatch.setattr(hero_variants, "RECIPE", tmp_path / "variants" / "recipe.json")
    master = tmp_path / "heroes" / f"{SLUG}.png"
    write_hero_master(master, *FIRST, seed=1)
    run_ladder()
    downloads.stamp_country(master, tmp_path / "variants", NAME)
    return tmp_path


class TestAReRender:
    """The ladder and overlay writers skip a file that exists, so after a re-render the manifest is
    what refuses, and doing what its refusal says must clear it in one pass."""

    def test_at_the_same_size_every_rung_is_refused_until_the_ladder_is_redone(self, store):
        master = rerender(store, *FIRST)
        message = refusal(store)
        for rung in hero_variants.rungs_for(*FIRST):
            assert f"{SLUG}-{rung}.webp" in message
        assert message.endswith(f"fix: {LADDER}, then {STAMP}")
        follow(store, message)
        webp, png = downloads.full_size_files(master, store / "variants")
        assert GEN.country_row(SLUG, RESOLVED, {}, store)["download"] == {
            "width": FIRST[0], "height": FIRST[1],
            "webpBytes": webp.stat().st_size, "pngBytes": png.stat().st_size,
        }

    def test_smaller_the_rungs_it_no_longer_produces_are_refused_until_deleted(self, store):
        rerender(store, 700, 420)
        run_ladder("--force")
        downloads.stamp_country(store / "heroes" / f"{SLUG}.png", store / "variants", NAME)
        message = refusal(store)
        for left in (f"{SLUG}-960.webp", f"{SLUG}-960.png"):
            assert left in message
        follow(store, message)
        assert GEN.country_row(SLUG, RESOLVED, {}, store)["sizes"] == [640, 700]

    def test_larger_the_old_print_copy_is_refused_until_deleted(self, store):
        """Its WebP is rewritten as an ordinary rung of the new ladder, and its PNG is not."""
        rerender(store, 1300, 780)
        run_ladder("--force")
        downloads.stamp_country(store / "heroes" / f"{SLUG}.png", store / "variants", NAME)
        message = refusal(store)
        assert f"{SLUG}-960.png" in message and f"{SLUG}-960.webp" not in message
        follow(store, message)
        row = GEN.country_row(SLUG, RESOLVED, {}, store)
        assert row["sizes"] == [640, 960, 1280, 1300] and row["download"]["width"] == 1300

    def test_an_overlay_is_held_to_its_master_as_the_ladder_is(self, store):
        master = store / "heroes" / f"{SLUG}.png"
        for rung in hero_variants.rungs_for(*FIRST):
            encode(master, store / "variants" / f"{SLUG}-spotlight-{rung}.webp", rung)
        rerender(store, 700, 420)
        run_ladder("--force")
        downloads.stamp_country(master, store / "variants", NAME)
        message = refusal(store)
        older, left = f"{SLUG}-spotlight-640.webp", f"{SLUG}-spotlight-960.webp"
        assert older in message and left in message
        assert message.endswith(f", then {OVERLAYS}") and LADDER not in message


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
            {"admin": "Myanmar", "name": "Myanmar", "frame": (92.0, 9.0, 102.0, 29.0),
             "also": ["Burma"],
             "has_hero": True},
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
