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

import pytest

from pipeline import bodies
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


def test_earth_radius_agrees_with_both_copies_in_the_render_package() -> None:
    """`hillshade` and `snow` each hold their own literal, and nothing related them before this."""
    assert bodies.EARTH.mercator_radius_m == hillshade.EARTH_RADIUS
    assert bodies.EARTH.mercator_radius_m == snow.EARTH_RADIUS


def test_exaggeration_agrees_with_the_shared_palette_constant() -> None:
    """The hero scene imports this value; a divergence restages 203 renders."""
    assert bodies.EARTH.exaggeration == palette.EXAGGERATION


def test_tile_ceiling_agrees_with_both_pyramids() -> None:
    """The raster cut and the country vector cut must agree, or the layers stop at different zooms."""
    assert bodies.EARTH.tile_max_zoom == shade_planet.TILE_CUT["max_zoom"]
    assert bodies.EARTH.tile_max_zoom == countries_pmtiles.MAX_ZOOM
