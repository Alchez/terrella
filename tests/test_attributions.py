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

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ATTRIBUTIONS = REPO_ROOT / "ATTRIBUTIONS.md"
ABOUT_PAGE = REPO_ROOT / "web/src/pages/about.astro"

# The licence on the site's OWN output, as opposed to the input obligations below. It is stated to
# readers in four places and, until these two checks, was verified in none — which is how a licence
# change leaves a stale copy behind. The failure is not legal but epistemic: a reader believes
# whichever copy they land on, and nothing tells them the others disagree.
OUTPUT_LICENSE = "CC BY-SA 4.0"
LICENSE_SITES: list[Path] = [
    REPO_ROOT / "LICENSE",
    REPO_ROOT / "README.md",
    ATTRIBUTIONS,
    ABOUT_PAGE,
]

# Assembled from two halves on purpose: this file is inside the sweep that forbids the string, so
# writing it out would make the guard fail on its own source.
SUPERSEDED_LICENSE_URL = "creativecommons.org/licenses/by-" + "nc/"
CURRENT_LICENSE_URL = "creativecommons.org/licenses/by-sa/4.0"

# Formats where a licence is declared rather than merely mentioned, plus the extension-less LICENSE.
# A URL is the discriminator the prose cannot give: ATTRIBUTIONS.md and MARS.md both discuss the
# superseded licence by name in recording why it changed, and must go on being allowed to.
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

# Each entry: (label, the exact string the licence requires).
# Sourced from ATTRIBUTIONS.md § Required / requested attribution strings, which records that the
# Copernicus terms were verified against the primary licence PDF rather than a secondary summary.
REQUIRED_STRINGS: list[tuple[str, str]] = [
    (
        "Copernicus WorldDEM-30 Art. 6(b) notice",
        ("produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and "
         "Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all "
         "rights reserved"),
    ),
    (
        "Copernicus WorldDEM-30 Art. 6(c) liability sentence",
        ("The organisations in charge of the Copernicus programme by law or by delegation do not "
         "incur any liability for any use of the Copernicus WorldDEM-30"),
    ),
    (
        "ESA WorldCover CC-BY notice",
        "© ESA WorldCover project 2021",
    ),
    (
        "RGI 7.0 CC-BY creator credit",
        "Randolph Glacier Inventory 7.0",
    ),
    (
        "OSI SAF CC-BY creator credit",
        "EUMETSAT Ocean and Sea Ice",
    ),
    # Not a courtesy, which is why it is in this list rather than excluded with GEBCO and GLOBathy.
    # The USGS product page states a Use Constraint of "Please cite authors" — the publisher asking
    # in its own terms field, where the excluded ones are public-domain sources asking for nothing.
    # Held to the same standard as the notices above: the exact citation, on the page a reader sees.
    (
        "MOLA / HRSC blend requested citation",
        ("Fergason, R. L, Hare, T. M., & Laura, J. (2018). HRSC and MOLA Blended Digital "
         "Elevation Model at 200m v2. Astrogeology PDS Annex, U.S. Geological Survey."),
    ),
    # ADMITTED ON THE SAME RULE AS THE BLEND ABOVE, and the rule is what keeps this list honest:
    # `Use_Constraints: please cite authors.` is the publisher asking in its own terms field. The
    # Viking mosaic, acquired in the same arc and credited beside this one, is deliberately ABSENT —
    # its fields read public domain and no use constraint, so listing it would assert an obligation
    # the publisher does not make.
    (
        "SIM 3292 requested citation",
        ("K.L. Tanaka, J.A. Skinner, Jr., J.M. Dohm, R.P. Irwin, III, E.J. Kolb, C.M. Fortezzo, "
         "Thomas Platz, G.G. Michael, and T.M. Hare, 2014, Geologic Map of Mars, Scale "
         "1:20,000,000, U.S. Geological Survey Scientific Investigations Map SIM 3292, "
         "http://pubs.usgs.gov/sim/3292"),
    ),
]


def _normalised(path: Path) -> str:
    """Collapse every whitespace run to one space.

    Both files wrap: Prettier breaks the `.astro` template across lines and Markdown reflows. A
    required notice split over two source lines is still present on the rendered page, so matching
    raw text would fail for a formatting reason and teach everyone to ignore this test.
    """
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("label,required", REQUIRED_STRINGS, ids=[e[0] for e in REQUIRED_STRINGS])
def test_about_page_carries_the_required_string(label: str, required: str) -> None:
    """The user-facing page is what discharges the obligation, not the repo file."""
    haystack = _normalised(ABOUT_PAGE)
    assert re.sub(r"\s+", " ", required) in haystack, (
        f"{label}: ATTRIBUTIONS.md records this as licence-REQUIRED, but web/src/pages/about.astro "
        f"does not contain it verbatim.\n  expected: {required!r}\n"
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


def test_every_source_on_the_about_page_declares_a_licence() -> None:
    """A missing licence badge is the failure mode that reads as 'no licence needed'."""
    about = ABOUT_PAGE.read_text(encoding="utf-8")
    names = re.findall(r'^\s*name: "([^"]+)",', about, re.MULTILINE)
    licences = re.findall(r'^\s*license: "([^"]+)",', about, re.MULTILINE)
    assert names, "no source entries parsed — the about.astro `sources` shape changed"
    assert len(names) == len(licences), (
        f"{len(names)} data sources but {len(licences)} licence fields — every source card must "
        f"declare one. Sources: {names}"
    )
    assert "NSIDC" not in licences and "EUMETSAT" not in licences, (
        "a data CENTRE is not a licence: NSIDC-0791 is public domain and OSI SAF is CC-BY 4.0. "
        f"Got: {licences}"
    )


@pytest.mark.parametrize("site", LICENSE_SITES, ids=[p.name for p in LICENSE_SITES])
def test_every_site_states_the_output_license(site: Path) -> None:
    """Four copies of one sentence, held together.

    ATTRIBUTIONS.md § Terrella's own outputs is the source of truth and the other three restate it.
    A restatement that drifts is worse than one never written, because each copy reads as
    authoritative on its own — nothing on the page a reader lands on says a sibling disagrees.
    """
    assert OUTPUT_LICENSE in _normalised(site), (
        f"{site.relative_to(REPO_ROOT)} does not state the output licence {OUTPUT_LICENSE!r} "
        "verbatim. If the licence changed, change all four sites and this constant together."
    )


def test_no_tracked_file_links_the_superseded_output_license() -> None:
    """A licence URL is an active declaration; prose naming the old licence is history.

    The distinction is what makes this checkable at all. ATTRIBUTIONS.md and MARS.md both discuss
    the superseded licence at length — recording why share-alike input could not flow into it is the
    reason the current one was chosen — so a ban on the NAME would forbid the explanation. Nobody
    links a licence they are describing in the past tense, so the link is the honest discriminator.
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
