"""Freshness check for `scripts/sabotage.py` — the mutation table, verified without running it.

The harness proves the guards are not vacuous, but only for cases whose needle still exists. When
`perfOverlay.ts` and `perfSnapshot.ts` moved into `src/lib/perf/`, nine of the seventy-one cases went
stale in one commit and nothing said so: the harness reports a stale needle as SKIP, minutes into a
run nobody was watching. A table that silently stops testing things is worse than no table, because
the summary still prints a large number.

So the table's own integrity is checked here instead, in a tenth of a second and on every `pytest`:
paths exist inside the roots a case is allowed to write to, needles still match exactly once, and
every named guard is still a real test. When one of these fails the fix is to update the case or
delete it — both explicit, which is the point.

This asserts nothing about whether a guard actually CATCHES its case. Only the harness can show that,
because only the harness runs the suites. And the harness returns the favour: its `suite='python'`
cases sabotage the assertions below, so this file is held to the same standard it imposes.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from scripts.sabotage import (
    BACKUP_SUFFIX,
    IN_FLIGHT_ENV,
    MUTABLE_ROOTS,
    SABOTAGES,
    SUITES,
    Sabotage,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# The table was assembled from five one-off runs plus this file's own cases, 81 of them. A floor
# rather than an exact count: it should catch the table being emptied or gutted, not fire when a case
# is deliberately retired. An exact pin would be a maintenance tax that reports nothing a floor does not.
MINIMUM_CASES = 70

# Every root vitest actually runs from, not just `web/src`. The Worker's tests live in
# `web/worker`, and while they were missing from here a case guarded by one of them failed this
# check as "renamed" — the guard was real, the search was too narrow.
VITEST_ROOTS = ("web/src", "web/worker")
VITEST_TITLES = "\n".join(
    path.read_text(encoding="utf-8")
    for root in VITEST_ROOTS
    for path in sorted((REPO_ROOT / root).rglob("*.test.ts"))
)
PYTEST_SOURCE = "\n".join(
    path.read_text(encoding="utf-8") for path in sorted((REPO_ROOT / "tests").rglob("*.py"))
)
# `suite='collection'` is a script, not a test framework, so its guards are the check names that
# script prints on failure. Same standard as the other two: the name has to exist in the source.
COLLECTION_SOURCE = (REPO_ROOT / "web/scripts/check_test_collection.ts").read_text(encoding="utf-8")


def guard_is_findable(case: Sabotage) -> bool:
    """True when `case.guard` names a test that exists in the suite it belongs to.

    A `collection` guard is the check name `check_test_collection.ts` prints, so it must be a name
    that script can actually reach `fail()` with.

    A pytest guard is a function name, so it must be defined. A vitest guard is a title, usually a
    literal — but `test.each` builds titles by interpolating `%s`, so the RENDERED title the harness
    matches against run output never appears in source. For those, both halves must: the template up
    to `%s`, and the parameter that fills it. A `%s` in the MIDDLE of a title is not handled, and
    would fail here rather than pass quietly.
    """
    if case.suite == "python":
        return f"def {case.guard}(" in PYTEST_SOURCE
    if case.suite == "collection":
        # Anchored on `fail(` so a name that only appears in a comment does not count, but
        # tolerant of the line break the formatter puts after the paren on multi-line calls.
        return re.search(rf'fail\(\s*"{re.escape(case.guard)}"', COLLECTION_SOURCE) is not None
    if case.guard in VITEST_TITLES:
        return True
    for split in range(20, len(case.guard)):
        head, tail = case.guard[:split], case.guard[split:]
        if f"{head}%s" in VITEST_TITLES and tail in VITEST_TITLES:
            return True
    return False


def case_id(case: Sabotage) -> str:
    return case.label


def test_table_is_not_empty() -> None:
    """A sweep over an empty table passes every check below by testing nothing."""
    assert len(SABOTAGES) >= MINIMUM_CASES, (
        f"{len(SABOTAGES)} cases, expected at least {MINIMUM_CASES} — was the table gutted?"
    )


def test_labels_are_unique() -> None:
    """The harness reports every result by label, so a duplicate makes a report unreadable."""
    labels = [case.label for case in SABOTAGES]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    assert not duplicates, f"duplicate case labels: {duplicates}"


def test_both_suites_are_exercised() -> None:
    """Every suite the harness can drive should have cases, or it is untested machinery."""
    covered = {case.suite for case in SABOTAGES}
    assert covered == set(SUITES), f"suites with no cases: {sorted(set(SUITES) - covered)}"


@pytest.mark.parametrize("case", SABOTAGES, ids=case_id)
def test_suite_is_known(case: Sabotage) -> None:
    """An unknown suite name would raise a KeyError partway through a five-minute run."""
    assert case.suite in SUITES, f"{case.suite!r} is not one of {sorted(SUITES)}"


@pytest.mark.parametrize("case", SABOTAGES, ids=case_id)
def test_case_path_is_inside_a_mutable_root(case: Sabotage) -> None:
    """The harness WRITES to `case.path`. Repo-relative is not a permission — the roots are."""
    assert not Path(case.path).is_absolute(), f"{case.path} is absolute"
    target = (REPO_ROOT / case.path).resolve()
    roots = [(REPO_ROOT / root).resolve() for root in MUTABLE_ROOTS]
    assert any(target.is_relative_to(root) for root in roots), (
        f"{case.path} is outside {list(MUTABLE_ROOTS)}"
    )
    if case.needle:
        assert target.is_file(), f"{case.path} does not exist"
    else:
        assert not target.exists(), f"{case.path} exists; a creation case needs it absent"


@pytest.mark.parametrize("case", [case for case in SABOTAGES if case.needle], ids=case_id)
def test_needle_matches_exactly_once(case: Sabotage) -> None:
    """`str.replace(needle, replacement, 1)` mutates the FIRST match.

    Two matches means the case perturbs whichever one happens to come first in the file, which is not
    the thing its label claims to break.
    """
    matches = (REPO_ROOT / case.path).read_text(encoding="utf-8").count(case.needle)
    assert matches == 1, f"needle appears {matches}x in {case.path}, expected exactly 1"


@pytest.mark.parametrize("case", SABOTAGES, ids=case_id)
def test_replacement_changes_something(case: Sabotage) -> None:
    """A replacement equal to its needle is a no-op the harness would report as MISSED."""
    assert case.replacement != case.needle


@pytest.mark.parametrize("case", SABOTAGES, ids=case_id)
def test_guard_is_a_real_test_name(case: Sabotage) -> None:
    """A renamed test turns CAUGHT into WRONG. Catch it here, not minutes into a run."""
    assert guard_is_findable(case), (
        f"no {case.suite} test matches {case.guard!r} — renamed, or the case needs a new guard"
    )


def test_no_sabotage_backups_are_left_in_the_tree() -> None:
    """A killed run leaves `*.sabotage-backup` beside a still-sabotaged source file.

    The suite would go red too, but only this says why. Recover with
    `uv run scripts/sabotage.py --restore`.

    The one exemption is the backup a run is holding *right now*: the harness names its in-flight
    path in the environment, since its own `suite='python'` cases would otherwise all fail here
    instead of at the assertion they are aiming at. Any other stray backup still fires.
    """
    in_flight = os.environ.get(IN_FLIGHT_ENV)
    exempt = f"{in_flight}{BACKUP_SUFFIX}" if in_flight else None
    leftovers = sorted(
        relative
        for root in MUTABLE_ROOTS
        for path in (REPO_ROOT / root).rglob(f"*{BACKUP_SUFFIX}")
        if (relative := str(path.relative_to(REPO_ROOT))) != exempt
    )
    assert not leftovers, (
        "a sabotage run was killed and the tree is still sabotaged: "
        f"{leftovers} — run `uv run scripts/sabotage.py --restore`"
    )
