"""The mutation harness's own control flow — how it decides a guard fired, and the audit's verdicts.

`tests/test_sabotage_cases.py` checks the TABLE without running anything. This file checks the
JUDGING, which nothing covered: the harness could credit a guard with someone else's failure and
every case would still read CAUGHT.
"""

import re
from pathlib import Path

import pytest

from scripts.sabotage import (
    AUDIT_OTHER,
    AUDIT_PROVEN,
    AUDIT_SILENT,
    AUDIT_UNSELECTED,
    SABOTAGES,
    SUITES,
    Sabotage,
    audit_verdict,
    guard_fired,
    judge_narrowly,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_TEST_NAMES = sorted(set(re.findall(
    r"^\s*def (test_\w+)",
    "\n".join(path.read_text(encoding="utf-8") for path in sorted((REPO_ROOT / "tests").rglob("*.py"))),
    re.MULTILINE,
)))


def _case(guard: str, suite: str = "python") -> Sabotage:
    return Sabotage(suite=suite, label="a case", path="scripts/sabotage.py",
                    needle="x", replacement="y", guard=guard)


def test_the_guard_failing_credits_the_guard() -> None:
    assert guard_fired("test_a_thing", ["test_a_thing"])


def test_a_longer_sibling_failing_does_not_credit_the_guard() -> None:
    """`-k` selects by substring, so the sibling comes along and can fail in the guard's place."""
    assert not guard_fired("test_a_thing", ["test_a_thing_and_another"])


def test_a_title_the_guard_only_prefixes_still_credits_it() -> None:
    """A web guard may be a prefix of its title, so the break must be at a non-word character."""
    assert guard_fired("keeps the header wide", ["keeps the header wide open under Save-Data"])


def test_no_python_guard_can_be_credited_by_a_sibling_that_k_would_select() -> None:
    """The law, swept over the whole table rather than over the four cases that have a sibling.

    A guard that is a strict prefix of another test name is selected together with it, and a
    substring credit rule then reports the guard as fired when only the sibling did.
    """
    for case in (one for one in SABOTAGES if one.suite == "python"):
        siblings = [name for name in PYTHON_TEST_NAMES
                    if case.guard in name and name != case.guard]
        for sibling in siblings:
            assert not guard_fired(case.guard, [sibling]), (
                f"{case.guard!r} would be credited with {sibling!r}, which `-k` also selects")


def test_the_audit_calls_its_suite_once_and_narrowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of the audit: no escalation, so the cost is one narrow run a case."""
    calls: list[dict[str, object]] = []

    def fake(name: str, in_flight: str | None = None, only: str | None = None) -> tuple[bool, str]:
        calls.append({"name": name, "in_flight": in_flight, "only": only})
        return False, "FAILED tests/test_x.py::test_a_thing"

    monkeypatch.setattr("scripts.sabotage.run_suite", fake)
    green, _output, escalated = judge_narrowly(_case("test_a_thing"))

    assert not green
    assert not escalated
    assert calls == [{"name": "python", "in_flight": "scripts/sabotage.py", "only": "test_a_thing"}]


def test_a_narrow_run_that_names_the_guard_is_proven() -> None:
    verdict, _ = audit_verdict(_case("test_a_thing"), False,
                               "FAILED tests/test_x.py::test_a_thing - AssertionError")
    assert verdict == AUDIT_PROVEN


def test_a_narrow_run_that_stays_green_is_silent() -> None:
    """The guard was selected, the mutation was live, and it did not fail."""
    verdict, _ = audit_verdict(_case("test_a_thing"), True, "1 passed in 0.30s")
    assert verdict == AUDIT_SILENT


def test_a_narrow_run_that_names_only_a_sibling_is_other() -> None:
    verdict, detail = audit_verdict(_case("test_a_thing"), False,
                                    "FAILED tests/test_x.py::test_a_thing_and_another")
    assert verdict == AUDIT_OTHER
    assert "test_a_thing_and_another" in detail


def test_a_narrow_run_that_selected_nothing_is_unselected() -> None:
    """pytest exits 5 when `-k` matches nothing, which is red with no failure to read."""
    verdict, _ = audit_verdict(_case("test_a_thing"), False, "no tests ran in 0.12s")
    assert verdict == AUDIT_UNSELECTED


def test_every_audit_verdict_is_reachable_from_the_suites_own_fail_pattern() -> None:
    """The oracle's own units: a verdict built from a pattern the suite never prints is untestable."""
    assert SUITES["python"].fail_pattern.match("FAILED tests/test_x.py::test_a_thing")
    assert SUITES["python"].narrow is not None
