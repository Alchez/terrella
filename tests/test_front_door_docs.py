"""The two files a stranger lands on, and whether they still agree about what this project is.

`CONTRIBUTING.md` opens by saying what KIND of thing Terrella is, which is a question asked from the
front page rather than from a contributor guide. README restates it, because the reader who wants it
has no reason to open a file addressed to people who have already decided to contribute. That
restatement is a second copy nothing else could make go red.
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
