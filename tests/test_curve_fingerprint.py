"""The committed curves still equal what this code computes, and the sampler can still see a change.

The recipe fingerprint beside this one records constants. A curve is not a constant: replacing a
smoothstep with a straight line moves every pixel it touches and moves no recorded value, which is
the gap this file exists to close. `scripts/curve_fingerprint` samples each pure transform over a
fixed domain, and a moved sample arrives as a red gate and a diff in the pull request's own files.

Three of the four tests below guard the instrument rather than the pipeline. A sampler that cannot
separate a smoothstep from a ramp passes its baseline comparison forever, so the control that must
fail when the instrument is broken is `TestTheSamplerSeesACurveChange`, and the registry guard is
what stops a new transform being invisible by never having been added.
"""

import ast
import json

import numpy as np
import pytest

from pipeline import paths
from pipeline.look import seaice
from scripts.curve_fingerprint import (
    BASELINE,
    DIGITS,
    EXCLUDED,
    REGENERATE,
    SAMPLES,
    fingerprint,
    serialise,
)

LOOK = paths.ROOT / "pipeline" / "look"


def public_functions() -> set[str]:
    """Every `module.function` a reader of `pipeline/look/` would call, from the source."""
    found = set()
    for entry in sorted(LOOK.glob("*.py")):
        tree = ast.parse(entry.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                found.add(f"{entry.stem}.{node.name}")
    return found


def test_the_committed_curves_still_equal_what_this_code_computes() -> None:
    """The failure is the product: it names the transform whose output moved.

    Regenerating is correct when the change was deliberate, and the regenerated file belongs in the
    same commit so the diff states what the change costs.
    """
    assert BASELINE.exists(), f"no committed baseline; write one with `{REGENERATE}`"
    rows = fingerprint()
    committed = BASELINE.read_text(encoding="utf-8")
    if serialise(rows) == committed:
        return
    recorded = json.loads(committed)
    moved = [name for name, row in rows.items() if row != recorded.get(name)]
    raise AssertionError(
        f"these transforms compute differently than the committed baseline: {sorted(moved)}. "
        f"If that was deliberate, regenerate with `{REGENERATE}` and commit it with this change.")


def test_every_public_look_function_is_sampled_or_excluded_with_a_reason() -> None:
    """A transform nobody registered is invisible, which is the failure this guard exists for.

    Hand-listing is what makes a registry go stale, so the population is read from the source and
    every member must be accounted for on one side or the other.
    """
    covered = {sample.covers for sample in SAMPLES.values()} | set(EXCLUDED)
    missing = public_functions() - covered
    assert not missing, (
        f"{len(missing)} function(s) in pipeline/look/ are neither sampled nor excluded: "
        f"{sorted(missing)}. Add a sample, or an EXCLUDED entry saying why it has no curve.")


def test_the_registry_names_nothing_that_has_gone() -> None:
    """The other direction: a sample or an exclusion outliving the function it names."""
    covered = {sample.covers for sample in SAMPLES.values()} | set(EXCLUDED)
    stale = covered - public_functions()
    assert not stale, f"registered names that no longer exist in pipeline/look/: {sorted(stale)}"


class TestTheSamplerSeesACurveChange:
    """The control. Every other test here passes on a sampler that reads three agreeing points.

    `seaice.ice_alpha` is the worked case: a smoothstep and a straight line agree exactly at both
    ends and at the midpoint, so a sampler taking only those reports no change while every sea-ice
    pixel moves. If this class goes green on a sampler that cannot tell them apart, the baseline
    comparison above is guarding nothing.
    """

    @staticmethod
    def _linear(frequency, ice_lo=None, ice_band=None, ice_max_alpha=None):
        low = seaice.ICE_LO if ice_lo is None else ice_lo
        band = seaice.ICE_BAND if ice_band is None else ice_band
        top = seaice.ICE_MAX_ALPHA if ice_max_alpha is None else ice_max_alpha
        return top * np.clip((np.asarray(frequency) - low) / max(1e-6, band), 0.0, 1.0)

    def test_a_straight_line_moves_the_sea_ice_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        before = fingerprint()
        monkeypatch.setattr(seaice, "ice_alpha", self._linear)
        after = fingerprint()
        assert before != after, "the sampler cannot separate a smoothstep from a linear ramp"

    def test_it_moves_that_row_and_leaves_the_others_alone(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        before = fingerprint()
        monkeypatch.setattr(seaice, "ice_alpha", self._linear)
        after = fingerprint()
        moved = {name for name in before if before[name] != after[name]}
        assert moved == {name for name, sample in SAMPLES.items()
                         if sample.covers == "seaice.ice_alpha"}


def test_the_rounding_leaves_room_between_float_noise_and_a_real_change() -> None:
    """`DIGITS` has to be coarse enough to survive a re-associated float and fine enough to see a
    curve move. The margin is measured rather than asserted: the worked change moves a sample by
    about 0.08 where float noise moves one by about 1e-16."""
    quarter = 0.25
    smoothstep = quarter * quarter * (3.0 - 2.0 * quarter)
    real_change = abs(smoothstep - quarter) * seaice.ICE_MAX_ALPHA
    resolution = 10.0 ** -DIGITS
    assert real_change > resolution * 1000, (
        f"rounding to {DIGITS} digits cannot see a change of {real_change:.4g}")
    assert resolution > np.finfo(np.float64).eps * 100, (
        f"rounding to {DIGITS} digits is inside float noise and will flake across platforms")
