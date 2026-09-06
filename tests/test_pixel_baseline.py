"""The look layers still compute what they computed, on a fixture, without a store or a GPU.

This is the arithmetic half of the pair. `test_render_fingerprint` asks whether a recorded setting
moved; this asks whether the numbers those settings are fed into still come out the same. A change
that alters a curve moves this and not that, which is the whole reason it exists: a contributor who
does not realise their change alters the image has nothing to declare, and a declaration was the
only thing covering that case.

Going red is the product, exactly as it is for the fingerprint. It is the normal outcome of a
deliberate look change: regenerate with the command the failure names and commit the result in the
same change, so the diff says what it costs.

What a green here does not mean is in `scripts/pixel_baseline`'s own docstring, with the boundary
measured. Read it before treating this as proof that a change left the render alone: the Blender rig
is outside it, and so is everything upstream of the look layers.
"""

import json

import numpy as np
import pytest

from pipeline.look import seaice
from scripts.pixel_baseline import (
    BASELINE,
    DECLARED_SILENT,
    OWED_PASS,
    REGENERATE,
    WINDOWS,
    _describe,
    baseline,
    fixture,
    subjects,
)


def _reads(facet: object) -> str:
    """One facet as a reader needs it, whatever shape it turns out to be.

    Defensive on purpose: this runs only when something already disagreed, so raising here would
    mean the real failure is never reported and the run dies on the reporting instead.
    """
    if not isinstance(facet, dict):
        return repr(facet)
    identity = facet.get("digest") or facet.get("result") or "?"
    if "mean" not in facet:
        return str(identity)
    # Mean and max: most of a fixture window is ice-free, so a curve change dilutes to a small mean
    # while moving the peak substantially. Reporting the mean alone reads like a rounding artifact.
    return f"{identity} (mean {facet.get('mean')}, max {facet.get('max')})"


def moved(computed: dict, committed: dict) -> list[str]:
    """Every subject and window that disagrees, with the summary that says how far."""
    report: list[str] = []
    for key in sorted(set(computed) | set(committed)):
        if key not in committed:
            report.append(f"{key}: SUBJECT IS NEW")
            continue
        if key not in computed:
            report.append(f"{key}: SUBJECT IS GONE")
            continue
        for window in sorted(set(computed[key]) | set(committed[key])):
            before = committed[key].get(window, {})
            after = computed[key].get(window, {})
            for facet in sorted(set(before) | set(after)):
                if before.get(facet) != after.get(facet):
                    report.append(f"{key} [{window}] {facet}: "
                                  f"{_reads(before.get(facet))} -> {_reads(after.get(facet))}")
    return report


def test_the_committed_baseline_still_matches_what_the_code_computes() -> None:
    computed = baseline()
    committed = json.loads(BASELINE.read_text(encoding="utf-8"))
    if computed == committed:
        return
    listed = "\n".join(f"    {line}" for line in moved(computed, committed))
    pytest.fail(
        f"the look layers compute different numbers than the committed baseline, so this change "
        f"alters what would be rendered:\n{listed}\n"
        f"  A re-render is owed; its measured cost is in {OWED_PASS}.\n"
        f"  If that is what you meant, regenerate with `{REGENERATE}` and commit the result in "
        f"this change, so the diff says what it costs.")


def test_the_digest_moves_when_the_arithmetic_does() -> None:
    """Without this every digest could be a constant and the file above would still read green.

    The two curves are the real pair: `seaice.ice_alpha`'s smoothstep against the linear ramp it was
    mutated to, which moves every sea-ice pixel on Earth by up to 20.3 DN and leaves the recipe
    fingerprint byte-identical. If this instrument cannot separate them it covers nothing.
    """
    fraction = np.linspace(0.0, 1.0, 64)
    smoothstep = _describe(fraction * fraction * (3.0 - 2.0 * fraction))
    linear = _describe(fraction)
    assert smoothstep["digest"] != linear["digest"]
    assert _describe(None) != smoothstep, "a silent producer must not read as a computing one"


def test_the_fixture_still_reaches_both_hemispheres() -> None:
    """`_earth_sea_ice` selects a different tuning per row, so one window records half a layer."""
    computed = baseline()
    ice = computed["earth/sea_ice"]
    north = ice["arctic"]["contribution"]
    south = ice["antarctic"]["contribution"]
    assert north["digest"] != south["digest"], "the hemisphere branch is no longer exercised"


def test_the_fixture_spans_the_whole_input_domain() -> None:
    """A fixture on a curve's flat end still yields digests that differ by hemisphere, so coverage
    needs its own arm and that arm has to measure the input.

    Counting distinct outputs instead does not work: narrowing the fixture onto the steep part of a
    curve raises that count rather than lowering it. `0` to `10_000` is the full packed domain,
    `seaice.ICE_SCALE` being 1e-4.
    """
    for name, (top, bottom) in WINDOWS.items():
        raw = fixture(top, bottom).raw
        assert raw is not None
        assert (float(raw.min()), float(raw.max())) == (0.0, 10_000.0), (
            f"the {name} fixture no longer spans the packed input domain, so a producer whose "
            f"transition sits outside what it offers is being sampled on a flat end")


def test_the_fixture_lands_inside_the_sea_ice_curve_and_not_only_its_flat_ends() -> None:
    """Spanning the domain is not the same as sampling the part that bends.

    A band narrow enough, or moved far enough, leaves a fixture that still spans `0` to `10_000`
    with almost every sample pinned at 0 or 1, where a smoothstep and a straight line agree exactly.
    Derived from `seaice`'s own constants rather than pinned to a number, so a deliberate move of
    `ICE_LO` or `ICE_BAND` reports that the fixture needs revisiting instead of rotting quietly.
    """
    raw = fixture(*WINDOWS["arctic"]).raw
    assert raw is not None
    fraction = np.clip(
        (seaice.unpack_seaice(raw[0]) - seaice.ICE_LO) / max(1e-6, seaice.ICE_BAND), 0.0, 1.0)
    inside = int(((fraction > 0) & (fraction < 1)).sum())
    assert inside >= 8, (
        f"only {inside} of {raw.shape[1]} fixture columns land inside the ice transition, so a "
        f"change to the curve's shape has almost nothing to move; widen the fixture or add columns")


def test_every_subject_computes_something_or_is_a_declared_silence() -> None:
    """A subject returning `None` unexpectedly is a fixture that stopped reaching its arithmetic."""
    computed = baseline()
    for key, entry in sorted(computed.items()):
        for window in WINDOWS:
            contribution = entry[window]["contribution"]
            if key in DECLARED_SILENT:
                assert contribution == {"result": "none"}, (
                    f"{key} is listed as a declared silence but now contributes {contribution}; "
                    f"if that is deliberate it must leave DECLARED_SILENT in the same change")
                continue
            assert "digest" in contribution, f"{key} [{window}] returned nothing to compare"
            assert contribution["distinct"] > 1, (
                f"{key} [{window}] is one value everywhere, so its digest can never move")


def test_the_subject_set_is_derived_and_matches_the_baseline() -> None:
    """Set equality, not containment: a listing whose subject vanished must fail, not pass."""
    committed = json.loads(BASELINE.read_text(encoding="utf-8"))
    derived = {key for key, _, _ in subjects()}
    assert derived == set(committed), (
        f"only in the code: {sorted(derived - set(committed))}; "
        f"only in the baseline: {sorted(set(committed) - derived)}. "
        f"A producer was added or removed without regenerating; `{REGENERATE}`")
    assert DECLARED_SILENT <= derived, (
        f"{sorted(DECLARED_SILENT - derived)} is excused from a check it is no longer subject to")


def test_the_comparison_can_actually_fail() -> None:
    """`moved` returning [] for everything would make the first test vacuous."""
    real = {"digest": "aaaa", "mean": 0.5}
    other = {"digest": "bbbb", "mean": 0.9}
    assert moved({"a": {"w": {"c": other}}}, {"a": {"w": {"c": real}}}) == [
        "a [w] c: aaaa (mean 0.5, max None) -> bbbb (mean 0.9, max None)"]
    assert moved({"a": {"w": {"c": {"result": "none"}}}}, {"a": {"w": {"c": real}}}) == [
        "a [w] c: aaaa (mean 0.5, max None) -> none"]
    assert moved({"a": {}}, {}) == ["a: SUBJECT IS NEW"]
    assert moved({}, {"a": {}}) == ["a: SUBJECT IS GONE"]
    assert moved({"same": {"w": {"c": real}}}, {"same": {"w": {"c": real}}}) == []
    assert moved({"a": {"w": {"c": 1}}}, {"a": {"w": {"c": 2}}}) == ["a [w] c: 2 -> 1"]


def test_the_baseline_is_committed_and_readable() -> None:
    """A missing baseline must fail here, not be silently regenerated by the thing checking it."""
    assert BASELINE.exists(), f"{BASELINE} is missing; regenerate with `{REGENERATE}` and commit it"
    assert isinstance(json.loads(BASELINE.read_text(encoding="utf-8")), dict)
