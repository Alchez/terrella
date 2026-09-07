"""Attribution drift scan — the licence-required strings must reach the shipped About page.

`ATTRIBUTIONS.md` declares itself the single source of truth for credits and states, per source,
which strings a licence *requires* rather than merely invites. Nothing enforced that:
the Copernicus Article 6(b) notice had been paraphrased on the About page (year ranges, "GmbH" and
"all rights reserved" all dropped) and the Article 6(c) liability sentence was absent entirely,
while ATTRIBUTIONS.md carried both correctly. Prose cannot notice its own drift, so this does.

Only obligations are asserted here. Courtesy citations (GEBCO, GLOBathy, NSIDC, Natural Earth —
public domain or CC0) are deliberately excluded: adding them would make the test fail for reasons
that are not legal ones, and a check that cries wolf gets deleted.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

from pipeline import attribution

REPO_ROOT = Path(__file__).resolve().parents[1]
ATTRIBUTIONS = REPO_ROOT / "ATTRIBUTIONS.md"
ABOUT_PAGE = REPO_ROOT / "web/src/pages/about.astro"
# The credits moved off the page and into a per-body module; the OUTPUT licence did not. Two
# constants rather than one because the two obligations now live in two files, and pointing both at
# whichever file happens to hold one of them is how a sweep goes quietly vacuous.
# The cards themselves, which moved out of `aboutContent.ts` when `pipeline/attribution.py` became
# their one owner: that module keeps the page's prose and imports this for its `sources` and
# `legal`. Committed, so this is what the built page renders.
ABOUT_CONTENT = REPO_ROOT / "web/src/data/attributions.json"

# The licence on the site's OWN output, as opposed to the input obligations below. Every site listed
# restates it and, until these two checks, none was verified — which is how a licence change leaves a
# stale copy behind. The failure is not legal but epistemic: a reader believes whichever copy they
# land on, and nothing tells them the others disagree.
#
# LICENSE is deliberately NOT a site, and adding it back would undo a decision rather than tighten
# one. It is pure MIT so that GitHub's licence detection reports MIT instead of "Other", which is the
# truthful label: no rendered asset is in git, so everything the repository actually contains is MIT.
# The output licence has better owners in ATTRIBUTIONS.md and on the About page, where the imagery is
# published. The cost of appending here again is invisible from inside the repo, which is the point.
OUTPUT_LICENSE = "CC BY-SA 4.0"
LICENSE_SITES: list[Path] = [
    REPO_ROOT / "README.md",
    ATTRIBUTIONS,
    ABOUT_PAGE,
]

# Assembled from two halves on purpose: this file is inside the sweep that forbids the string, so
# writing it out would make the guard fail on its own source.
SUPERSEDED_LICENSE_URL = "creativecommons.org/licenses/by-" + "nc/"
CURRENT_LICENSE_URL = "creativecommons.org/licenses/by-sa/4.0"

# Formats where a licence is declared rather than merely mentioned, plus the extension-less LICENSE.
# A URL is the discriminator the prose cannot give: ATTRIBUTIONS.md discusses the superseded licence
# by name in recording why it changed, and must go on being allowed to.
LICENSE_BEARING_SUFFIXES = {".md", ".py", ".ts", ".astro", ".html"}

# The one file exempt, and the reason is structural rather than convenient: the mutation table's
# whole purpose is to hold strings this repo forbids, so it will always state the thing under ban.
# Sweeping it would make every guard that bans a string fail the moment the string gets a case.
LICENSE_SWEEP_EXEMPT = {"scripts/sabotage.py"}


def tracked_license_bearing_files() -> list[Path]:
    """Every tracked file that could plausibly declare a licence to a reader."""
    listing = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [
        REPO_ROOT / name
        for name in sorted(listing)
        if name not in LICENSE_SWEEP_EXEMPT
        and (Path(name).suffix in LICENSE_BEARING_SUFFIXES or Path(name).name == "LICENSE")
        and (REPO_ROOT / name).is_file()
    ]

# DERIVED, and it was the fourth hand-kept copy of one fact until it was.
#
# The list said which notices are obligations; `Source.obligation` says the same thing beside the
# notice itself, so the two could disagree and did: SCAR ADD is CC-BY, is named required in
# ATTRIBUTIONS.md, and was in neither this list nor the About page.
#
# Each entry is now the FULL notice rather than a distinguishing fragment. The fragments were chosen
# to be robust against wording that has since stopped being allowed to vary.
#
# The courtesy citations are still excluded, by the same rule and now structurally: a public-domain
# source carries `obligation=False`, so asserting it would take a deliberate edit rather than an
# oversight. The Viking mosaic is the case that keeps this honest — acquired in the same arc as
# SIM 3292 and credited beside it, but its fields read public domain with no use constraint, so
# listing it would assert an obligation the publisher does not make.
REQUIRED_STRINGS: list[tuple[str, str]] = [
    (source.name, source.notice)
    for source in attribution.SOURCES.values()
    if source.obligation
]
# Plus the one required string that is not any source's citation: Article 6(c) is a disclaimer the
# licence obliges alongside 6(b), rendered under Earth's cards rather than on the DEM's own.
REQUIRED_STRINGS.append(
    ("Copernicus WorldDEM-30 Art. 6(c) liability sentence", attribution.COPERNICUS_LIABILITY)
)


def test_the_obligations_are_the_ones_the_registry_marks() -> None:
    """Set EQUALITY, so a source losing `obligation=True` fails here rather than going unasserted.

    One-way containment is satisfied by a derivation that produced nothing, which is exactly the
    failure that let SCAR ADD sit uncredited while every licence test passed.
    """
    marked = {name for name, source in attribution.SOURCES.items() if source.obligation}
    assert marked == {"glo30", "worldcover", "rgi", "addrock", "seaice", "mars_dem",
                      "mars_sim3292"}, (
        "the set of licence-required sources changed. That is a legal claim, not a refactor: "
        "confirm it against ATTRIBUTIONS.md § Required / requested attribution strings, then "
        "update this literal."
    )


#: A line whose first non-space characters are `//`. Anchored at the start on purpose: `https://`
#: appears in every licence URL on these pages, so a mid-line rule would delete the declarations.
LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.MULTILINE)


def _normalised(path: Path) -> str:
    """Collapse every whitespace run to one space, after dropping source comments.

    Both files wrap: Prettier breaks the `.astro` template across lines and Markdown reflows. A
    required notice split over two source lines is still present on the rendered page, so matching
    raw text would fail for a formatting reason and teach everyone to ignore this test.

    COMMENTS ARE REMOVED BECAUSE A COMMENT DISCHARGES NOTHING. Every assertion built on this asks
    whether a page STATES something to a visitor, and a comment states it to nobody — but it does
    satisfy a substring search, so a second copy in a comment holds the test green while the
    sentence on the page says something else. That is not hypothetical: the About page's own note
    about a whitespace bug quoted the output licence, and the sabotage case for a wrong licence on
    the page sat silent behind it.
    """
    source = path.read_text(encoding="utf-8")
    if path.suffix in {".astro", ".ts", ".js"}:
        source = LINE_COMMENT.sub("", source)
    return re.sub(r"\s+", " ", source)


@pytest.mark.parametrize("label,required", REQUIRED_STRINGS, ids=[e[0] for e in REQUIRED_STRINGS])
def test_about_page_carries_the_required_string(label: str, required: str) -> None:
    """The user-facing page is what discharges the obligation, not the repo file.

    BOTH HALVES OF THE PAGE ARE SEARCHED, because either file can legitimately hold a notice and
    which one it is follows from SCOPE. A per-source credit belongs to one planet and lives in
    `aboutContent.ts`; anything the whole site owes would live in the page's shared block. The
    Copernicus Art. 6(c) liability sentence moved from the second to the first once it was read
    properly — it is about WorldDEM-30, which only Earth is built from, so it now sits in Earth's
    `legal` list. The union weakens nothing: a string in neither file still fails, which is the only
    way this can pass, and searching one file would make the guard turn on where prose happens to
    sit rather than on whether it is there at all.
    """
    # The CARDS and the page, never the whole generated file: it also carries the archive credits,
    # and those hold every notice too, so searching the file would let a card lose a citation and
    # still match. Found by a sabotage case escalating instead of reporting CAUGHT.
    cards = json.loads(ABOUT_CONTENT.read_text(encoding="utf-8"))["bodies"]
    rendered = " ".join(
        [card["attribution"] for body in cards.values() for card in body["sources"]]
        + [line for body in cards.values() for line in body["legal"]]
    )
    haystack = f"{re.sub(r'\\s+', ' ', rendered)} {_normalised(ABOUT_PAGE)}"
    assert re.sub(r"\s+", " ", required) in haystack, (
        f"{label}: ATTRIBUTIONS.md records this as licence-REQUIRED, but neither "
        f"web/src/lib/aboutContent.ts nor web/src/pages/about.astro contains it verbatim.\n"
        f"  expected: {required!r}\n"
        "A paraphrase does not discharge an exact-notice obligation — copy the string unchanged."
    )


@pytest.mark.parametrize("label,required", REQUIRED_STRINGS, ids=[e[0] for e in REQUIRED_STRINGS])
def test_attributions_file_still_records_the_required_string(label: str, required: str) -> None:
    """Scan the other direction too, or the pair can drift by editing the source of truth."""
    haystack = _normalised(ATTRIBUTIONS)
    assert re.sub(r"\s+", " ", required) in haystack, (
        f"{label}: this test asserts the string against the About page, but ATTRIBUTIONS.md no "
        "longer contains it. Either the licence text changed — in which case update both and this "
        "test — or the source of truth was edited by mistake."
    )


#: The one required notice no ARCHIVE owes. WorldCover is the heroes' snow mask and the tiles
#: replaced it with NSIDC-0791 plus RGI, so a pyramid crediting it would name a source not in it.
#: It stays in `REQUIRED_STRINGS` because the heroes are published and still owe it.
# EMPTY, and the entry it used to hold is why the list is exceptions rather than targets. WorldCover
# was exempted here as "the heroes' snow mask, replaced in the tiles by NSIDC-0791 plus RGI", which
# is true of the SNOW mask and not of the dataset: it also synthesises the watermask for the void
# GLO-30 tiles, which reaches every Earth raster archive through the fused heightfield. An exemption
# stated in a standing brief's own words survived until the acquisition chain was read.
NOT_IN_ANY_ARCHIVE: set[str] = set()


def every_archive_credit() -> str:
    """What the four raster pyramids say about themselves, composed the way a pack composes it.

    Values rather than source text: the notices are built from adjacent string literals, so a
    substring search over this module's own file would be matching across the quote seams.
    """
    from pipeline import attribution, bodies

    return " ".join(
        attribution.for_archive(body, layer)
        for body in bodies.BODIES.values()
        for layer in attribution.ARCHIVE_LAYERS
    )


@pytest.mark.parametrize("label,required", REQUIRED_STRINGS, ids=[e[0] for e in REQUIRED_STRINGS])
def test_an_archive_carries_the_required_string_in_its_own_bytes(label: str, required: str) -> None:
    """The third place the same obligation has to hold, and the only one that survives a download.

    The About page discharges it for a visitor and ATTRIBUTIONS.md records it for us, but both are
    on a host a downloaded `.pmtiles` has left behind. `pmtiles convert` copies the MBTiles
    `attribution` row into the archive metadata, so this is the copy that travels with the file.
    """
    if label in NOT_IN_ANY_ARCHIVE:
        pytest.skip(f"{label} is baked into heroes, never into a tile pyramid")
    assert re.sub(r"\s+", " ", required) in every_archive_credit(), (
        f"{label}: ATTRIBUTIONS.md records this as licence-required and no published archive "
        "carries it. Add it to the right entry in pipeline/attribution.py — a notice that reaches "
        "only the website does not travel with a file someone downloaded."
    )


def test_the_archive_credit_check_can_fail(monkeypatch) -> None:
    """The control for the sweep above, which is a substring test over a long composed string and
    would pass just as quietly against a credit that had lost a notice."""
    assert "a notice no licence has ever required" not in every_archive_credit()


def test_every_source_on_the_about_page_declares_a_licence() -> None:
    """A missing licence badge is the failure mode that reads as 'no licence needed'.

    Reads the generated cards rather than the module that renders them: every field is required on
    `attribution.Source`, so an omission can no longer be a blank line, but a card can still carry
    a data CENTRE where a licence belongs, which is a wrong answer rather than a missing one.
    """
    cards = [card
             for body in json.loads(ABOUT_CONTENT.read_text(encoding="utf-8"))["bodies"].values()
             for card in body["sources"]]
    assert cards, "no source cards parsed — the attributions.json shape changed"
    licences = [card["license"] for card in cards]
    assert all(card["name"] and card["href"] and card["role"] and card["attribution"]
               for card in cards), f"a card is missing a field: {cards}"
    assert len(cards) == len(licences), (
        f"{len(cards)} data sources but {len(licences)} licence fields — every source card must "
        f"declare one."
    )
    assert "NSIDC" not in licences and "EUMETSAT" not in licences, (
        "a data CENTRE is not a licence: NSIDC-0791 is public domain and OSI SAF is CC-BY 4.0. "
        f"Got: {licences}"
    )


@pytest.mark.parametrize("site", LICENSE_SITES, ids=[p.name for p in LICENSE_SITES])
def test_every_site_states_the_output_license(site: Path) -> None:
    """Every restatement of one sentence, held together.

    ATTRIBUTIONS.md § Terrella's own outputs is the source of truth and the others restate it.
    A restatement that drifts is worse than one never written, because each copy reads as
    authoritative on its own — nothing on the page a reader lands on says a sibling disagrees.
    """
    assert OUTPUT_LICENSE in _normalised(site), (
        f"{site.relative_to(REPO_ROOT)} does not state the output licence {OUTPUT_LICENSE!r} "
        "verbatim. If the licence changed, change all four sites and this constant together."
    )


def test_a_notice_that_exists_only_in_a_comment_does_not_count(tmp_path: Path) -> None:
    """The control for the stripper above, and it is not optional.

    Every licence assertion here PASSES on a substring being present, so a stripper that quietly
    removed nothing would leave all of them green and say so in exactly the same words. This plants
    the licence in a comment and nowhere else, and requires it to be invisible; the second half
    plants a URL on the same line to hold the anchoring, since `https://` is `//` too.
    """
    commented = tmp_path / "commented.astro"
    commented.write_text(f"// the imagery is {OUTPUT_LICENSE}\nconst nothing = 1;\n")
    assert OUTPUT_LICENSE not in _normalised(commented)

    declared = tmp_path / "declared.astro"
    declared.write_text(f'const html = "see {CURRENT_LICENSE_URL} for {OUTPUT_LICENSE}";\n')
    assert OUTPUT_LICENSE in _normalised(declared), (
        "the stripper removed a declaration containing a URL, so it is cutting on `//` anywhere "
        "rather than at the start of a line")


def test_no_tracked_file_links_the_superseded_output_license() -> None:
    """A licence URL is an active declaration; prose naming the old licence is history.

    The distinction is what makes this checkable at all. ATTRIBUTIONS.md discusses the superseded
    licence at length — recording why share-alike input could not flow into it is the reason the
    current one was chosen — so a ban on the NAME would forbid the explanation. Nobody links a
    licence they are describing in the past tense, so the link is the honest discriminator.
    """
    linking: list[str] = []
    declaring_current: set[str] = set()
    for path in tracked_license_bearing_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        name = str(path.relative_to(REPO_ROOT))
        if SUPERSEDED_LICENSE_URL in text:
            linking.append(name)
        if CURRENT_LICENSE_URL in text:
            declaring_current.add(name)

    # Anti-vacuity, and it NAMES both sites rather than counting them. A sweep re-narrowed to one
    # file, or one whose suffix set stops matching anything, passes a count and passes a bare `> 0`
    # — the exact narrowing this guard exists to survive.
    assert {"README.md", "web/src/pages/about.astro"} <= declaring_current, (
        "the sweep found no live link to the current licence in the two files that carry one, so "
        "it cannot be trusted to find a stale one either. Check that "
        f"{sorted(LICENSE_BEARING_SUFFIXES)} still selects them. Found: {sorted(declaring_current)}"
    )
    assert not linking, (
        f"these files still LINK the superseded output licence: {linking}. The site's renders are "
        f"{OUTPUT_LICENSE}; a live link to the old one grants rights that were withdrawn and "
        "withholds rights that were granted. Naming it in prose is fine — linking it is not."
    )
