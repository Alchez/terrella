"""The single home for what differs between one planet and the next.

Modelled on `paths.py`, which does the same job for filesystem roots: one module states the facts,
a test enforces that nothing else grows a second copy, and every consumer derives.

WHAT A BODY IS. Not a look and not a dataset — the small set of facts that make the same pipeline
produce a different planet. Geometry (how big the sphere is), the vertical exaggeration its relief
is drawn at, and how deep its pyramid is cut. Everything else about a planet is data.

WHY THIS EXISTS BEFORE THERE IS A SECOND BODY. Every one of these values is currently a module-level
constant sized for Earth, and two of them are already written out twice with nothing relating them
(`EARTH_RADIUS` in `render/hillshade.py` and `render/snow.py`). Adding a planet turns each into a
cross-body bug of the worst kind: the wrong sphere radius does not raise, it scales the per-row
hillshade z-factor by latitude and produces a relief that is plausible everywhere and true nowhere.

THE VALUES HERE ARE STILL DUPLICATED ELSEWHERE, ON PURPOSE AND UNDER GUARD. This module is a pure
addition — nothing reads it yet — so every constant it states also still lives at its original call
site. `tests/test_bodies.py` pins each pair, so the interim cannot drift, and each bridge assertion
dies with the copy it holds. Copied look constants have already cost this project one overnight
re-render of every hero; the only safe copy is one a test refuses to let diverge.

NO FIELD MAY CARRY A DEFAULT. A default would let a field added later be inherited unexamined by
every planet but the one it was written for — invisible in the diff that adds it. Without defaults,
adding a field is a hard error at every construction until each body answers for it.

    from pipeline import bodies
    body = bodies.get("earth")     # raises on an unknown name; never falls back
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline import paths


@dataclass(frozen=True)
class Body:
    """One planet's geometry and pyramid depth. Frozen: a stage must not be able to retune another.

    Every field is required. See the module note — a default is how a new planet silently inherits
    Earth's answer to a question nobody asked it.
    """

    #: Registry key and path segment. Lowercase, no spaces — it names directories and archive keys.
    name: str
    #: Sphere radius used for Web-Mercator ground-metre arithmetic, in metres.
    #:
    #: This is the projection's sphere, NOT the body's mean or equatorial radius, and the two are
    #: different questions. Consumers use it to turn a Mercator y back into a latitude and to size
    #: the per-row hillshade z-factor, both of which must agree with whatever radius the raster was
    #: warped with. Mixing two radii yields a latitude-varying error that renders plausibly.
    mercator_radius_m: float
    #: Vertical exaggeration the relief is drawn at, shared by the hero scene and the tile shading.
    #:
    #: A look constant rather than a physical one: it is chosen so the planet reads well, and it is
    #: not transferable between bodies. Relief as a fraction of radius differs by ~2.8x between
    #: Earth and Mars, so the same number does not produce the same drama.
    exaggeration: float
    #: Deepest zoom the tile pyramids are cut to. Bounds the raster and vector cuts together — they
    #: must agree, or the layers stop at different zooms and the overlay drifts off its basemap.
    tile_max_zoom: int
    #: Directory segment this body's outputs nest under — BOTH its `data/work/` intermediates and
    #: its served assets under `web/public/`. One prefix for both, because a body that nested its
    #: intermediates one way and its published files another is two conventions to remember.
    #:
    #: EARTH'S IS DELIBERATELY EMPTY, and that asymmetry is a measured decision rather than an
    #: oversight. `data/work/planet_tiles` already holds 97 GB including the live pyramid; moving it
    #: under a new segment would make every stage read as missing and re-derive the whole planet —
    #: a full composite and cut, ~26 minutes — to produce pixels identical to the ones sitting there.
    #: A second body pays no such cost, so it nests properly from the start.
    path_prefix: str


EARTH = Body(
    name="earth",
    # Web Mercator's sphere. Duplicated today in render/hillshade.py and render/snow.py.
    mercator_radius_m=6378137.0,
    # Duplicated today in render/palette.py, which the hero scene imports directly.
    exaggeration=15.0,
    # Duplicated today in tile/shade_planet.py's TILE_CUT and compose/countries_pmtiles.py.
    tile_max_zoom=8,
    # Empty on purpose — see the field's note. Earth's intermediates stay exactly where they are.
    path_prefix="",
)


#: Every body the pipeline knows. Keyed by `Body.name`, which a test pins so one planet cannot
#: acquire two spellings.
BODIES: dict[str, Body] = {EARTH.name: EARTH}


def get(name: str) -> Body:
    """Look a body up by name, or raise.

    THERE IS DELIBERATELY NO DEFAULT AND NO FALLBACK. A run that quietly borrows Earth's geometry
    because a name was misspelled produces a full pyramid that is wrong everywhere and looks right —
    the single most expensive failure this registry exists to make impossible. Raising costs one
    re-run; defaulting costs a planet.
    """
    try:
        return BODIES[name]
    except KeyError:
        known = ", ".join(sorted(BODIES))
        raise KeyError(f"unknown body {name!r}; known bodies are: {known}") from None


def _require_directory_name(stage: str) -> None:
    """A stage is a single directory name, never a path expression.

    ONE COPY, shared by both resolvers. It was briefly written out twice, and the mutation harness's
    freshness gate caught it within seconds — a duplicated guard is the same drift this whole module
    exists to remove, and it would have let one resolver be hardened while the other was not.

    Without it, a stage assembled by concatenation could walk out of this body's tree and land in
    another's, which is the one place a mistake here stops being wrong and becomes unrecoverable.
    """
    if not stage or "/" in stage or "\\" in stage or stage in {".", ".."}:
        raise ValueError(
            f"stage must be a single directory name, got {stage!r} — "
            "compose nested paths from the returned directory instead"
        )


def work_dir(body: Body, stage: str) -> Path:
    """Where one body's `stage` intermediates live, under `data/work/`.

    THE BODY GOES IN THE PATH, NOT IN THE FRESHNESS RECIPE, and that is the load-bearing decision
    here. Every stage of the tile pipeline is gated on a recipe sidecar — `composite_params.json`,
    `hs_params.json`, `tile_params.json` — whose *contents* are its dependency: change a byte and the
    stage restages. Adding a body field to those recipes would therefore invalidate Earth's entire
    correct output the moment a second body existed, for no pixel change at all. Giving each body its
    own directory makes every one of those sidecars body-specific for free, because they are
    different files. The identity is carried by location, which costs nothing.

    `stage` is a DIRECTORY NAME, never a path expression. A caller that assembled one by
    concatenation could otherwise walk out of this body's tree and land in another's — the single
    place a mistake here stops being wrong and starts being unrecoverable.
    """
    _require_directory_name(stage)
    # An empty prefix collapses, which is what keeps Earth on its historical layout.
    return paths.DATA / "work" / body.path_prefix / stage


def public_dir(body: Body, stage: str) -> Path:
    """Where one body's SERVED assets live, under `web/public/`.

    A separate root from `work_dir`, and deliberately so. `paths.py` draws this line: intermediates
    follow the data store (relocatable via `MAPS_DATA`), while anything the site actually ships must
    follow the CHECKOUT, because the build reads it from there. Collapsing the two would make a
    relocated data store silently publish nothing.

    Earth's assets keep their exact URLs — `/caps/caps.json` is a contract the frontend fetches, and
    an empty prefix is what stops a second body rewriting it. Mars nests one level in.
    """
    _require_directory_name(stage)
    return paths.ROOT / "web/public" / stage / body.path_prefix
