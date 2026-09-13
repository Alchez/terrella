"""Register a third body that has no data, and ask every per-body registry about it.

WHY THIS EXISTS. Every claim in this project that a stage is body-agnostic is tested against two
bodies, and one of them is Earth, whose answer every default already holds. Mars is the other, and
adding it took a month that went almost entirely on discovering that seams already called
body-agnostic were Earth with a variable in front of them. Before this file, nothing under `tests/`
constructed a synthetic body at all, so the parameterisation had one worked instance and no control.
`test_bodies.test_a_body_on_a_smaller_sphere_reports_a_ratio_below_one` is the exception that proves
it: it makes exactly this move for one function and states the reason in its own docstring.

IT NEEDS NO DATA, WHICH IS THE POINT. Every question below is answered out of a module-level dict, so
a third body can be walked through the whole registry surface without a raster, an account or a
render. A `Body` is a frozen dataclass of scalars, so a Mars-like one costs one `dataclasses.replace`.

THE POPULATION IS DERIVED, NOT LISTED. `registries_in_the_tree` scans the package for module-level
dicts keyed by a body name, and the set-equality test below refuses a registry that nothing here
probes. A hand-kept list would go stale in exactly the direction that matters: silently short.

WHAT A FAILURE MEANS. A registry that raises by name is doing its job, and the shape this catches is
the other one, where a body nobody registered is handed Earth's answer or an empty one and renders
plausibly. That is the failure Mars actually shipped and had to be walked back.
"""

import dataclasses
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from pipeline import attribution, bodies, layers, planet_seam
from pipeline.look import layer_producers, palette, perennial_ice
from pipeline.tile import cap_render

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A body with no data anywhere, shaped like Mars because Mars is the non-default one: it has no
#: ocean, no borders and its own sphere, so it exercises the fields Earth's values would hide.
#: The name is deliberately not a real moon: nothing here is a claim about whether Titan would work.
THIRD = dataclasses.replace(bodies.MARS, name="fixture", path_prefix="fixture")

#: A module-level dict whose first key is a body name, or a tuple opening on one. This is the shape
#: a per-body registry has in this package, and matching the shape rather than the NAME is what
#: catches one that nobody thought to call `*_BY_BODY`.
BODY_KEYED = re.compile(
    r"^([A-Z][A-Z0-9_]*)\s*(?::[^=]+)?=\s*\{\s*(?:#[^\n]*\n\s*)*\(?\"(?:earth|mars)\"",
    re.MULTILINE,
)

#: Registries this file deliberately does not probe for a raise, each with the reason absence is a
#: designed answer rather than an oversight. Exemptions and never targets: a registry nobody thought
#: about is red by default, which is the only direction that stays true as the tree grows.
SILENT_BY_DESIGN = {
    # Read with `.get`, and its own comment says Earth belongs absent because its poles are not
    # reconstructed from an altimeter that missed them. A third body's absence is a decision.
    "POLE_SMOOTH_BY_BODY",
    # `.get` with a fallback STRING, used to build an error message rather than to choose behaviour.
    # Its totality is already pinned by `test_planet_seam`, which is where that check belongs.
    "PRODUCER_COMMANDS",
}


def registries_in_the_tree() -> dict[str, str]:
    """Every module-level dict in `pipeline/` keyed by a body name, as {name: module path}."""
    found: dict[str, str] = {}
    for path in sorted((REPO_ROOT / "pipeline").rglob("*.py")):
        for name in BODY_KEYED.findall(path.read_text()):
            found[name] = str(path.relative_to(REPO_ROOT))
    return found


def ask_each_registry_about(body: bodies.Body) -> dict[str, object]:
    """Put one body through every probed registry, returning what each raised.

    The call shapes differ per registry, so the probes are written out rather than dispatched: a
    generic caller would have to guess the key shape, and guessing wrong reads as a pass.

    EACH PROBE ASKS WHAT THIS BODY ACTUALLY DECLARES, which is the contract rather than an arbitrary
    argument. Asking `producer_for` about a layer the body does not carry raises correctly and would
    have read here as a missing registry entry: the first run of this file failed that way, on my
    probe rather than on the code.
    """
    declared = [layer for layer in layers.LAYERS if layer.name in body.surface_layers]
    asked: dict[str, object] = {}
    probes: list[tuple[str, Callable[[], object]]] = [
        ("LOOK_BY_BODY", lambda: palette.look_for(body.name)),
        ("CREDITS", lambda: attribution.keys_for(body, attribution.ARCHIVE_LAYERS[0])),
    ]
    if declared:
        probes.append(("PRODUCER_BY_BODY_LAYER",
                       lambda: layer_producers.producer_for(body, declared[0])))
    if body.renders_polar_caps and layers.PERENNIAL_ICE.name in body.surface_layers:
        probes.append(("CAP_ICE_BY_BODY", lambda: perennial_ice.cap_ice(body, "north")))
    for name, call in probes:
        try:
            call()
            asked[name] = None
        except Exception as error:  # noqa: BLE001 - the assertion is about WHICH error, below
            asked[name] = error
    return asked


def test_the_registry_population_is_the_one_this_file_probes() -> None:
    """A per-body registry nobody asked about is the whole failure mode, so growing one goes red.

    Set equality rather than containment: "every probe hits a real registry" is satisfied by a scan
    that matched nothing, and the direction that matters is the other one.
    """
    found = registries_in_the_tree()
    assert len(found) >= 4, f"the scan found almost nothing, check BODY_KEYED: {found}"
    probed = set(ask_each_registry_about(bodies.EARTH)) | SILENT_BY_DESIGN
    assert set(found) == probed, (
        "a registry keyed by body is not probed by this dry run (or a probe names one that is "
        f"gone) — found {sorted(found)}, probed {sorted(probed)}"
    )


def test_every_registry_answers_for_every_body_that_is_registered() -> None:
    """Adding a body and forgetting one registry is the defect, and it does not raise on Earth."""
    missing = [
        f"{name} has no answer for {body.name}"
        for body in bodies.BODIES.values()
        for name, error in ask_each_registry_about(body).items()
        if isinstance(error, KeyError)
    ]
    assert not missing, "a registered body is missing from a registry:\n  " + "\n  ".join(missing)


def test_a_body_nobody_registered_is_refused_rather_than_given_earths_answer() -> None:
    """The control, and the only arm that separates "asked and refused" from "never asked".

    Without it every assertion above passes on a registry that answers Earth's value to anything,
    because both registered bodies have an entry and neither can tell you what an absent one gets.
    """
    silent = [name for name, error in ask_each_registry_about(THIRD).items() if error is None]
    assert not silent, (
        "a registry answered for a body nobody registered, so a third planet would inherit that "
        f"answer and render plausibly: {sorted(silent)}"
    )


def test_a_refusal_names_the_body_or_the_bodies_that_exist() -> None:
    """A bare `KeyError: 0` sends the reader into the wrong module, which is half the cost.

    The registries that already do this well carry `known: [...]` in the message; the bar here is
    only that the text reaches either the body asked for or the ones that do exist.
    """
    anonymous = [
        f"{name}: {error!r}"
        for name, error in ask_each_registry_about(THIRD).items()
        if THIRD.name not in str(error) and not any(known in str(error) for known in bodies.BODIES)
    ]
    assert not anonymous, (
        "a refusal names neither the body asked for nor the ones that exist:\n  "
        + "\n  ".join(anonymous)
    )


@pytest.mark.parametrize("pole", ["north", "south"])
def test_the_cap_seam_refuses_a_third_body_at_both_poles(pole: str) -> None:
    """Both poles, because a registry keyed on a pair can be half-filled and Mars's nearly was."""
    with pytest.raises(KeyError):
        perennial_ice.cap_ice(THIRD, pole)


def test_the_planet_seam_refuses_a_body_whose_producer_never_ran() -> None:
    """The declaration is the completion stamp, so a body with no data must not read as complete."""
    with pytest.raises(Exception) as raised:
        planet_seam.declared(THIRD)
    assert THIRD.name in str(raised.value) or "fixture" in str(raised.value)


def test_the_pole_smoothing_default_is_absence_and_is_written_down() -> None:
    """The one exemption above, pinned so it stays a decision rather than becoming an oversight.

    If this registry ever gains a fallback that is not absence, the exemption in `SILENT_BY_DESIGN`
    stops being true and this is what says so.
    """
    assert cap_render.POLE_SMOOTH_BY_BODY.get(THIRD.name) is None
    assert bodies.EARTH.name not in cap_render.POLE_SMOOTH_BY_BODY
