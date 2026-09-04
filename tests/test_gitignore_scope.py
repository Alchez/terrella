"""Every root ignore pattern is anchored, or is on the list of kinds that occur at any depth.

A pattern with no leading slash and no interior slash matches at EVERY depth, and it fails silently:
the path stops existing as far as git is concerned, and `git add` reports success having added
nothing. A bare `data/` did this to `web/src/data/`, the frontend's own source-data directory, and
the cost was not a lost file. It was two committed generated files placed elsewhere, each carrying
a comment explaining that a file could not live where it belonged.

THE SHAPE IS THE SUBJECT, NOT A LIST OF PATHS. Pinning the paths that were once swallowed guards
only the wound that has already been closed; the mistake that can still happen is the NEXT bare
directory name, which no such case would see. So this reads the pattern shapes and refuses a new
unanchored one until its author either anchors it or says here why it must match everywhere.

ROOT ONLY, AND THAT IS A DISTINCTION RATHER THAN A CONVENIENCE. The root file's patterns compete
with this repo's own source directories, so a bare name there can collide with one. `web/.gitignore`
is a conventional frontend ignore file whose entries (`dist/`, `node_modules/`, editor droppings)
are meant to match at any depth, and a guard over it would be a list of every line it contains.
"""

from pathlib import Path

import pytest

GITIGNORE = Path(__file__).resolve().parents[1] / ".gitignore"

# Kinds rather than places: each names something that legitimately occurs at more than one depth,
# so anchoring it would be the bug. Adding a line here is a deliberate act with a reason attached,
# which is the whole mechanism.
ANY_DEPTH_BY_DESIGN = {
    "*.part": "a partial download, written beside whatever it is fetching",
    "*.blend1": "Blender's own backup, written beside every .blend it saves",
    "*.pyc": "bytecode, written beside every module",
    "__pycache__/": "the same, one directory per package",
    ".venv/": "a nested virtualenv is still a virtualenv",
    ".coverage": "written wherever pytest --cov is run",
    ".env": "two roots hold one, and neither may ship",
    ".env.*": "the same, for the per-environment variants",
    ".wrangler/": "wrangler writes its state wherever a wrangler command runs",
}


def patterns() -> list[str]:
    """Every live pattern in the root ignore file, comments and blanks dropped."""
    lines = GITIGNORE.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def matches_at_any_depth(pattern: str) -> bool:
    """git anchors a pattern to the ignore file's directory only if it has a non-trailing slash."""
    body = pattern.lstrip("!").rstrip("/")
    return not body.startswith("/") and "/" not in body


@pytest.mark.parametrize("pattern", patterns())
def test_a_pattern_is_anchored_or_declared_depth_free(pattern: str) -> None:
    if not matches_at_any_depth(pattern):
        return
    assert pattern in ANY_DEPTH_BY_DESIGN, (
        f"`{pattern}` has no leading slash and no interior slash, so it matches a path of that "
        f"name at EVERY depth, silently. Anchor it (`/{pattern}`) if it means one place, or add it "
        f"to ANY_DEPTH_BY_DESIGN with the reason it must match everywhere.")


def test_the_shape_rule_separates_the_two_cases() -> None:
    """Both arms, or a rule that answered True for everything would exempt the whole file."""
    assert matches_at_any_depth("data/")
    assert matches_at_any_depth("*.pyc")
    assert not matches_at_any_depth("/data/")
    assert not matches_at_any_depth("blender/renders/")


def test_every_declared_exemption_is_still_in_the_file() -> None:
    """An exemption for a pattern nobody has any more reads as coverage and is not."""
    live = set(patterns())
    orphans = sorted(set(ANY_DEPTH_BY_DESIGN) - live)
    assert not orphans, f"{orphans} are exempted here but no longer in .gitignore"
