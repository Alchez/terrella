"""The committed fingerprint still equals what this code would record beside its outputs.

This does not test the pipeline: every stage already has its own tests. It compares every recorded
recipe against a committed copy, so a change that moves a constant arrives as a red gate and a diff
in the pull request's own file list rather than as a discovery on the next pass.

What a green run here does not mean is in `render_fingerprint`'s own docstring, with the measurement
behind it. Read it before treating this gate as evidence that a change left the render alone: it is
a necessary condition and not a sufficient one. Nothing covers the arithmetic, nor the Blender
shader graph, nor `pipeline/fuse/`, nor the hero lane.

A committed file rather than a workflow comment, because a workflow commenting on a pull request
needs `pull-requests: write`, which `GITHUB_TOKEN` does not carry for a `pull_request` event raised
from a fork, and a fork is every outside contribution. The comment would post nothing on exactly the
pull requests it exists for, and the workarounds (`pull_request_target`, a `workflow_run` handoff)
are more machinery than the fact they carry. A tracked file needs no permissions, survives in the
record, and shows up where changes are already reviewed.

Going red is the product. It is the normal outcome of a deliberate look change rather than a defect:
the message names every moved field and points at the pass that is owed. Regenerate with the command
the failure names, and commit the result in the same change, so the diff states what it costs.
"""

import json
from pathlib import Path

import pytest

from scripts.render_fingerprint import (
    BASELINE,
    OWED_PASS,
    REGENERATE,
    STAGE_COUNT,
    fingerprint,
)

#: Long enough to identify a moved value, short enough that fifty of them stay readable. A ramp is
#: a list of stops and a rig is fifty fields; printing either whole buries the one that moved.
VALUE_WIDTH = 80


def flatten(value: object, prefix: str = "") -> dict[str, object]:
    """One entry per leaf, keyed by its dotted path.

    RECURSES, because the interesting case is nested: `block_render`'s recipe carries the whole rig
    under one `rig` key, so a one-level walk reports "the rig changed" and prints both copies of a
    fifty-field dict. What a reader needs is `rig.sun_strength`.
    """
    if not isinstance(value, dict):
        return {prefix: value}
    if not value:
        return {prefix: {}}
    flat: dict[str, object] = {}
    for key, nested in value.items():
        flat.update(flatten(nested, f"{prefix}.{key}" if prefix else str(key)))
    return flat


def _short(value: object) -> str:
    text = repr(value)
    return text if len(text) <= VALUE_WIDTH else text[:VALUE_WIDTH - 3] + "..."


def moved_fields(computed: dict, committed: dict) -> list[str]:
    """Every leaf that disagrees, as `stage.path: committed -> computed`."""
    report: list[str] = []
    for stage in sorted(set(computed) | set(committed)):
        if stage not in committed:
            report.append(f"{stage}: STAGE IS NEW")
            continue
        if stage not in computed:
            report.append(f"{stage}: STAGE IS GONE")
            continue
        before = flatten(committed[stage], stage)
        after = flatten(computed[stage], stage)
        for field in sorted(set(before) | set(after)):
            if before.get(field) != after.get(field):
                report.append(f"{field}: {_short(before.get(field))} -> {_short(after.get(field))}")
    return report


def test_the_committed_fingerprint_still_matches_the_code() -> None:
    computed = fingerprint()
    committed = json.loads(BASELINE.read_text(encoding="utf-8"))
    if computed == committed:
        return
    moved = moved_fields(computed, committed)
    listed = "\n".join(f"    {line}" for line in moved)
    pytest.fail(
        f"{len(moved)} recipe field(s) moved, so this change alters what the pipeline would "
        f"render:\n{listed}\n"
        f"  A re-render is owed; its measured cost is in {OWED_PASS}.\n"
        f"  Regenerate with `{REGENERATE}` and commit the result in this change, so the diff "
        f"says what it costs.")


def test_the_fingerprint_covers_every_recipe_producer() -> None:
    """A fingerprint that quietly stopped calling a stage would go green on that stage forever."""
    computed = fingerprint()
    assert len(computed) == STAGE_COUNT, (
        f"{len(computed)} stages recorded, expected {STAGE_COUNT}: a producer was added to the "
        f"pipeline without joining the fingerprint, or one was dropped from it")
    empty = sorted(stage for stage, recipe in computed.items() if not recipe)
    assert not empty, f"{empty} recorded an empty recipe, which can never disagree with anything"


def test_the_comparison_can_actually_fail() -> None:
    """`moved_fields` returning [] for everything would make the test above vacuous."""
    assert moved_fields({"stage": {"knob": 1}}, {"stage": {"knob": 2}}) == ["stage.knob: 2 -> 1"]
    assert moved_fields({"a": {}}, {}) == ["a: STAGE IS NEW"]
    assert moved_fields({}, {"a": {}}) == ["a: STAGE IS GONE"]
    assert moved_fields({"same": {"knob": 1}}, {"same": {"knob": 1}}) == []


def test_the_baseline_is_committed_and_readable() -> None:
    """A missing baseline must fail here, not be silently regenerated by the thing checking it."""
    assert BASELINE.exists(), f"{BASELINE} is missing; regenerate with `{REGENERATE}` and commit it"
    assert isinstance(json.loads(BASELINE.read_text(encoding="utf-8")), dict)
    assert BASELINE == Path(__file__).resolve().parent / "render_fingerprint.json"
