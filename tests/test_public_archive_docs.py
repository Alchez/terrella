"""What the outward-facing docs call a published archive.

An archive's elevation bytes are in Terrarium's channel order at an 8 m step, and they are neither
of the two formats a reader would search for. Mapbox's Terrain-RGB decodes them to six-figure
metres and plain Terrarium to a depth below the sea floor; neither errors, and both hand back a
number that looks like elevation. So naming one is worse for a downloader than naming nothing.

Three surfaces tell an outside reader what is downloadable, and only these three: the two docs a
clone lands on and the page they both link to. The pipeline's own lane keeps the name internally,
where the reader is someone with the source in front of them.

The archives' EMBEDDED description still carries the wrong name and is not in scope here: changing
it means re-cutting six keys, which is owed to nobody yet.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PUBLIC_SURFACES = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "web/src/pages/about.astro",
]


@pytest.mark.parametrize("path", PUBLIC_SURFACES, ids=lambda path: path.name)
def test_still_points_a_reader_at_the_archives(path: Path) -> None:
    """The control. Every assertion below is an absence, and an absence is what a renamed heading,
    a deleted section or an emptied file all produce for free."""
    text = path.read_text(encoding="utf-8")
    assert "/archives" in text, f"{path.name} no longer sends a reader to the archives at all"


@pytest.mark.parametrize("path", PUBLIC_SURFACES, ids=lambda path: path.name)
def test_names_no_format_that_would_decode_an_archive_wrongly(path: Path) -> None:
    text = path.read_text(encoding="utf-8").lower()
    for name in ("terrain-rgb", "terrain rgb", "terrarium"):
        assert name not in text, (
            f"{path.name} calls a published archive {name!r}, which decodes its bytes to a "
            "plausible wrong number rather than failing"
        )


def test_the_readme_lists_the_layer_names_a_tile_url_actually_takes() -> None:
    """README spells the three layer names beside the `{layer}` slot they fill, which is a second
    copy of a union that lives in TypeScript. One owner is impossible across the two languages, so
    the copy is made executable instead: rename a layer and this goes red rather than leaving the
    README quietly describing addresses nobody can build."""
    union = (ROOT / "web/src/lib/tileAddress.ts").read_text(encoding="utf-8")
    match = re.search(r"export type LayerId = ([^;]+);", union)
    assert match, "tileAddress.ts no longer declares LayerId, so this guard has no subject"
    layers = re.findall(r'"([^"]+)"', match.group(1))
    assert len(layers) == 3, f"LayerId is no longer three names but {layers}"

    listed = re.search(r"three PMTiles archives per body \(([^)]*)\)", (ROOT / "README.md").read_text(encoding="utf-8"))
    assert listed, "README no longer lists the archives per body"
    assert [name.strip() for name in listed.group(1).split(",")] == layers
