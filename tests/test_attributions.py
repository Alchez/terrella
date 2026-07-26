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

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ATTRIBUTIONS = REPO_ROOT / "ATTRIBUTIONS.md"
ABOUT_PAGE = REPO_ROOT / "web/src/pages/about.astro"

# Each entry: (label, the exact string the licence requires).
# Sourced from ATTRIBUTIONS.md § Required / requested attribution strings, which records that the
# Copernicus terms were verified against the primary licence PDF rather than a secondary summary.
REQUIRED_STRINGS: list[tuple[str, str]] = [
    (
        "Copernicus WorldDEM-30 Art. 6(b) notice",
        "produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and "
        "Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all "
        "rights reserved",
    ),
    (
        "Copernicus WorldDEM-30 Art. 6(c) liability sentence",
        "The organisations in charge of the Copernicus programme by law or by delegation do not "
        "incur any liability for any use of the Copernicus WorldDEM-30",
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
