"""The body registry: one home for what differs between one planet and the next.

WHY A REGISTRY AT ALL. Everything that makes a globe a globe is currently a module-level constant
sized for Earth, and several of them are already duplicated — `EARTH_RADIUS = 6378137.0` is written
out twice, in `render/hillshade.py` and `render/snow.py`, with no test relating them. A second body
turns every one of those into a silent cross-body bug: the wrong radius does not crash, it produces
a latitude-varying wrong exaggeration that renders perfectly plausibly.

THE BRIDGE TESTS ARE THE POINT OF THIS FILE, and they are temporary by design. The registry states
each value and the tests below hold every existing copy to it, so the interim duplication cannot
drift. As each copy is deleted in a later commit its bridge test becomes a statement about the one
remaining home. Copied look constants have already cost this project a full overnight re-render of
203 heroes; a guarded copy is the only kind worth having.

NO FIELD MAY CARRY A DEFAULT. That is what makes adding a field to `Body` a hard error at every
call site rather than a silent inheritance of Earth's value by a planet nobody checked.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from pipeline import bodies, paths
from pipeline.compose import countries_pmtiles
from pipeline.render import hillshade, palette, snow
from pipeline.tile import shade_planet


def test_earth_is_registered_and_reachable_by_name() -> None:
    assert bodies.get("earth") is bodies.EARTH


def test_an_unknown_body_raises_and_names_the_ones_that_exist() -> None:
    """A lookup must never fall back to Earth.

    A default here is the whole failure mode the registry exists to prevent: a Mars run that
    silently borrows Earth's radius produces output that is wrong everywhere and looks right.
    """
    with pytest.raises(KeyError) as caught:
        bodies.get("mars")
    # The message has to carry the known names, because the first thing anyone does on hitting this
    # is guess the spelling.
    assert "earth" in str(caught.value)


def test_no_field_carries_a_default_so_a_new_one_must_be_decided_per_body() -> None:
    """Adding a field to `Body` must break every construction until each body answers for it.

    With a default, a new field would silently take Earth's value on every other planet — and the
    reader of the diff that added it would see nothing wrong.
    """
    defaulted = [
        field.name
        for field in dataclasses.fields(bodies.Body)
        if field.default is not dataclasses.MISSING
        or field.default_factory is not dataclasses.MISSING  # pyright: ignore[reportUnnecessaryComparison]
    ]
    assert defaulted == [], f"these fields would be inherited unexamined by a new body: {defaulted}"


def test_a_body_is_frozen() -> None:
    """Mutating a body at runtime would let one stage's change leak into another's freshness key."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        bodies.EARTH.exaggeration = 1.0  # pyright: ignore[reportAttributeAccessIssue]


def test_the_registry_key_is_the_body_s_own_name() -> None:
    """Two spellings of one body is the drift this whole module exists to stop."""
    assert all(key == body.name for key, body in bodies.BODIES.items())


# --- Bridges to the constants that still live elsewhere ------------------------------------------
# Each of these dies with the copy it pins. Until then it is what makes the duplication safe.


def test_the_render_package_no_longer_carries_its_own_earth_radius() -> None:
    """The bridge that pinned the two copies is GONE because the copies are.

    Replaced by an anti-regrowth scan rather than deleted outright, in the shape `test_paths.py`
    already uses for filesystem roots: the failure worth catching now is not divergence between two
    literals but the reappearance of a second literal at all. A source scan is the only thing that
    can see that, because a regrown constant type-checks, tests green, and reads as a tidy local.
    """
    for module in (hillshade, snow):
        source = Path(module.__file__).read_text(encoding="utf-8")  # pyright: ignore[reportArgumentType]
        assert "6378137" not in source, (
            f"{Path(module.__file__).name} has regrown a hard-coded sphere radius — "  # pyright: ignore[reportArgumentType]
            "it belongs to the body, and the conversion lives in pipeline/mercator.py"
        )


def test_earth_carries_web_mercator_s_defining_sphere() -> None:
    """Pinned to the literal, because this one is not a tunable.

    EPSG:3857 IS a sphere of exactly 6378137 m — the value is fixed by the projection's definition,
    not chosen by us, so an oracle that restates it is honest rather than circular. Every latitude
    the hillshade z-factor is computed at depends on it, and a wrong one is invisible: the relief
    comes out plausible at every latitude and correct at none.
    """
    assert bodies.EARTH.mercator_radius_m == 6378137.0


def test_exaggeration_agrees_with_the_shared_palette_constant() -> None:
    """The hero scene imports this value; a divergence restages 203 renders."""
    assert bodies.EARTH.exaggeration == palette.EXAGGERATION


def test_tile_ceiling_agrees_with_both_pyramids() -> None:
    """The raster cut and the country vector cut must agree, or the layers stop at different zooms."""
    assert bodies.EARTH.tile_max_zoom == shade_planet.TILE_CUT["max_zoom"]
    assert bodies.EARTH.tile_max_zoom == countries_pmtiles.MAX_ZOOM


# --- Where a body's intermediates live -----------------------------------------------------------


def test_earth_keeps_its_existing_unprefixed_work_paths() -> None:
    """Earth's directories must not move, and this is the assertion that says so.

    THE REASON IS MEASURED, NOT AESTHETIC. `data/work/planet_tiles` currently holds 97 GB including
    the live pyramid. Relocating it would make every stage read as missing and re-derive the planet
    — a full composite and cut, ~26 minutes — to produce pixels identical to the ones already there.
    So Earth carries an empty `path_prefix` and a second body nests under its own name.
    """
    assert bodies.work_dir(bodies.EARTH, "planet_tiles") == paths.DATA / "work/planet_tiles"
    assert bodies.work_dir(bodies.EARTH, "planet") == paths.DATA / "work/planet"


def test_another_body_nests_under_its_own_name() -> None:
    """Two bodies must never be able to write to one directory.

    This is also what keeps the body OUT of the freshness recipes: a second body writes its own
    `composite_params.json` at its own path, so the params file is already body-specific and adding
    a body key inside it would only invalidate Earth's correct output.
    """
    other = dataclasses.replace(bodies.EARTH, name="mars", path_prefix="mars")
    assert bodies.work_dir(other, "planet_tiles") == paths.DATA / "work/mars/planet_tiles"


def test_no_two_bodies_share_a_path_prefix() -> None:
    """One shared prefix is one planet silently overwriting another's intermediates."""
    prefixes = [body.path_prefix for body in bodies.BODIES.values()]
    assert len(prefixes) == len(set(prefixes))


@pytest.mark.parametrize("stage", ["", "/absolute", "../escape", "a/../../b"])
def test_a_stage_name_cannot_escape_the_body_s_own_directory(stage: str) -> None:
    """A stage name is a directory name, never a path expression.

    Without this, a caller that built a stage name by concatenation could write outside the body's
    tree — and the failure would land on ANOTHER body's intermediates, which is the one place a
    mistake here becomes unrecoverable rather than merely wrong.
    """
    with pytest.raises(ValueError):
        bodies.work_dir(bodies.EARTH, stage)


def test_earth_keeps_the_served_cap_urls_the_frontend_already_fetches() -> None:
    """`/caps/caps.json` is a shipped contract; a prefix here would break it silently at runtime."""
    assert bodies.public_dir(bodies.EARTH, "caps") == paths.ROOT / "web/public/caps"


def test_a_second_body_publishes_under_its_own_segment() -> None:
    other = dataclasses.replace(bodies.EARTH, name="mars", path_prefix="mars")
    assert bodies.public_dir(other, "caps") == paths.ROOT / "web/public/caps/mars"


def test_served_assets_follow_the_checkout_not_the_data_store() -> None:
    """The two roots must not be collapsed.

    Intermediates are relocatable via MAPS_DATA; published assets are read by the site build from
    the checkout. One root for both means a relocated data store publishes nothing, silently.
    """
    assert paths.ROOT in bodies.public_dir(bodies.EARTH, "caps").parents
    assert paths.DATA in bodies.work_dir(bodies.EARTH, "cap").parents


@pytest.mark.parametrize("stage", ["", "/absolute", "../escape"])
def test_a_served_stage_name_cannot_escape_either(stage: str) -> None:
    with pytest.raises(ValueError):
        bodies.public_dir(bodies.EARTH, stage)
