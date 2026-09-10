"""The two files a stranger lands on, and whether they still agree about what this project is.

`CONTRIBUTING.md` opens by saying what KIND of thing Terrella is, which is a question asked from the
front page rather than from a contributor guide. README restates it, because the reader who wants it
has no reason to open a file addressed to people who have already decided to contribute. That
restatement is a second copy nothing else could make go red.

The same shape, one file over: CONTRIBUTING also tells a contributor that a green local run is
weaker than the pull request's, and the machinery behind that sentence is in two files that are not
docs at all.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Both files are unwrapped, so today the claim is one line in each. A reflow is one edit away and
#: would break a literal match while changing nothing, which is the failure worth not having.
FLATTEN = re.compile(r"\s+")


def flattened(path: Path) -> str:
    return FLATTEN.sub(" ", path.read_text(encoding="utf-8"))


def test_the_readme_carries_the_identity_claim_contributing_opens_with() -> None:
    """`REPO-2` sat `PARTIAL` because the only answer in the tree was behind the one door a reader
    asking it has no reason to open."""
    opening = re.search(r"# Contributing (Terrella is [^.]+\.)", flattened(ROOT / "CONTRIBUTING.md"))
    assert opening, "CONTRIBUTING.md no longer opens by saying what kind of project this is"

    claim = opening.group(1)
    assert claim in flattened(ROOT / "README.md"), (
        "README does not carry CONTRIBUTING's identity sentence, so the two front doors can drift "
        f"apart on what this is:\n  {claim}"
    )


def test_the_ci_only_coverage_floor_contributing_names_still_exists() -> None:
    """`RUN-12`'s remaining half: a green local run is weaker than the pull request's.

    The mechanism is in two files that are not docs, so dropping either leaves the sentence lying to
    the one reader who acts on it.
    """
    assert "coverage floor your local run leaves off" in flattened(ROOT / "CONTRIBUTING.md")
    assert "PYTEST_ARGS: --cov" in (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert re.search(r"^fail_under\s*=", (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
                     re.MULTILINE), "the floor CI enforces is gone, so the local run is not weaker"


def test_the_readme_and_the_archives_page_agree_on_which_download_can_be_measured() -> None:
    """Relief bakes the vertical stretch into its pixels and terrain does not.

    README states the property and sends the reader to the page for each body's figure, so losing
    the page's half leaves the pointer aimed at nothing while README goes on promising it.
    """
    assert "picture rather than a measurement" in flattened(ROOT / "README.md"), (
        "README no longer says the relief archive cannot be measured, which is the half of the "
        "licence a reuser acts on"
    )
    roles = (ROOT / "web/src/lib/archiveIndex.ts").read_text(encoding="utf-8")
    assert "body.bakedExaggeration" in roles, (
        "the archives page states no per-body figure for README to point at"
    )
    assert "Real metres" in roles, "the terrain archive no longer says its elevations are undistorted"


def test_the_readme_states_the_pyramid_size_its_delivery_argument_rests_on() -> None:
    """README argues an archive against a directory of loose tiles, and the count is the argument.

    A raster pyramid is dense, every address from z0 to the body's ceiling, so the figure follows
    from `tile_max_zoom` and moves only when someone moves a ceiling. Stating it in prose puts a
    second copy beside the registry; this is the copy that goes red.
    """
    from pipeline import bodies

    readme = flattened(ROOT / "README.md")
    for body in bodies.BODIES.values():
        dense = (4 ** (body.tile_max_zoom + 1) - 1) // 3
        assert f"{dense:,}" in readme, (
            f"{body.name} cuts to z{body.tile_max_zoom}, so each of its raster pyramids holds "
            f"{dense:,} tiles, and README states no such figure for the delivery argument to rest on"
        )
    for clause, lost in (
        ("a new key, never an overwrite",
         "why an archive beats a directory of loose tiles, which is the re-cut and not the bytes"),
        ("strips a `Range` header",
         "why the browser does not open the archive itself, the usual way PMTiles is served"),
    ):
        assert clause in readme, (
            f"README no longer says {lost}. Both halves of the delivery question live here and in "
            f"the Worker rule, which only opens when someone is already editing Worker code"
        )
