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

import dataclasses
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

from pipeline import bodies, mercator, paths
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
    # A CASE VARIANT OF A REAL BODY, chosen once Mars was registered and the old "mars" stopped
    # being unknown. It is the realistic miss rather than an invented one — the registry is
    # lowercase because the name is a path segment and a URL slug — and it can never quietly become
    # valid the way a plausible planet name could.
    with pytest.raises(KeyError) as caught:
        bodies.get("Mars")
    # The message has to carry the known names, because the first thing anyone does on hitting this
    # is guess the spelling. Every registered body, not a hardcoded pair: a planet missing from the
    # error is one the reader concludes does not exist.
    for known in bodies.BODIES:
        assert known in str(caught.value)


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


def test_earth_s_grid_resolution_is_the_one_its_live_raster_was_built_at() -> None:
    """Pinned to the literal, like Web Mercator's sphere above and for a stronger reason.

    THE BRIDGE THIS REPLACES IS GONE BECAUSE ITS COPY IS. `Z8_RES` briefly lived in `shade_planet`
    beside this field, held to it by an assertion; the constant has since been deleted and every
    caller reads the body. What survives it is the fact the bridge existed to protect, which is not
    derivable and not a tunable: **46 GB of `height_3857.tif` was warped at exactly this number**.
    The exact z8 figure is 305.748113, and `-tap` snapped the live grid 12.2 m past the true
    Mercator edge on every side because of the difference. Correcting it here restages nothing
    today and everything at the next unrelated re-fuse, which would then be blamed for it.
    """
    assert bodies.EARTH.map_units_per_pixel == 305.7483


def test_every_body_s_grid_resolution_agrees_with_its_own_tile_ceiling() -> None:
    """The relational pin that makes two fields which must move together un-driftable.

    `map_units_per_pixel` is stored rather than derived (see its field note: deriving it would leave
    Earth's existing 46 GB raster inert until an unrelated re-fuse restaged the planet under someone
    else's change). Stored means two fields can disagree, so they are compared here instead.

    THE TOLERANCE IS DOING REAL WORK IN BOTH DIRECTIONS. Earth's value is rounded — 305.7483 against
    an exact 305.748113, six parts in ten million — so an equality assertion would fail on the one
    body whose pixels already exist. A wrong ceiling, the error actually worth catching, is a factor
    of two. 1e-5 admits the first and cannot admit the second.
    """
    tile_px = shade_planet.tile_cut(bodies.EARTH)["tile_size"]
    for body in bodies.BODIES.values():
        exact = 2.0 * math.pi * body.mercator_radius_m / (tile_px * 2 ** body.tile_max_zoom)
        assert math.isclose(body.map_units_per_pixel, exact, rel_tol=1e-5), (
            f"{body.name}'s grid resolution ({body.map_units_per_pixel}) is not the pixel size of a "
            f"{tile_px}px tile at its own ceiling z{body.tile_max_zoom} ({exact}) — the two fields "
            "have drifted, and the raster would be cut at a zoom it was not built for"
        )


def test_exaggeration_agrees_with_the_shared_palette_constant() -> None:
    """The hero scene imports this value; a divergence restages 203 renders."""
    assert bodies.EARTH.exaggeration == palette.EXAGGERATION


def test_tile_ceiling_agrees_with_the_vector_pyramid() -> None:
    """The raster cut and the country vector cut must agree, or the layers stop at different zooms.

    Only the vector half is a bridge now: the raster cut READS the body, so asserting the two match
    would be asking a function to agree with its own argument. The countries pyramid is still
    Earth-hardcoded, deliberately — vectors stay Earth's until a Mars layer is designed — so this
    stays a real statement about a real second copy, and it dies with that copy.
    """
    assert bodies.EARTH.tile_max_zoom == countries_pmtiles.MAX_ZOOM


def test_the_cut_differs_between_bodies_in_exactly_one_setting() -> None:
    """The ceiling is the planet's; the other eight belong to the encoder and the tile scheme.

    THE GUARD IS AGAINST OVER-PARAMETERISATION, which is the quieter of the two failures here.
    Under-parameterising is loud — Mars would cut to Earth's z8 and the disk would say so. Moving
    quality, format or tile size onto the body is silent: it reads as thoroughness, it duplicates
    eight facts across every planet, and it lets two bodies' encodings drift apart while every test
    still passes. Nothing about a WebP quality is a property of Mars.
    """
    earth, mars = shade_planet.tile_cut(bodies.EARTH), shade_planet.tile_cut(bodies.MARS)
    differing = {key for key in earth if earth[key] != mars[key]}  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert differing == {"max_zoom"}, (
        f"the cut differs between Earth and Mars in {sorted(differing)} — only the ceiling is a "
        "body fact; the rest describe the encoder and belong in one place"
    )
    assert earth["max_zoom"] == bodies.EARTH.tile_max_zoom
    assert mars["max_zoom"] == bodies.MARS.tile_max_zoom


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
    assert bodies.work_dir(bodies.MARS, "planet_tiles") == paths.DATA / "work/mars/planet_tiles"


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
    assert bodies.public_dir(bodies.MARS, "caps") == paths.ROOT / "web/public/caps/mars"


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


def test_a_body_carries_two_distinct_radii_and_they_are_not_interchangeable() -> None:
    """Mercator and AEQD are different projections on different spheres, by construction.

    THE PROJECT ALREADY CARRIES A WARNING ABOUT COLLAPSING THESE. Three radii are in play: Web
    Mercator's 6378137 (the tile grid), the caps' AEQD sphere at 6371000, and MapLibre's own globe
    radius at 6371008.8 on the frontend. The last two are 8.8 m apart, which is precisely why they
    must stay separate — the cap is drawn on one and blended against tiles drawn on another, and
    collapsing them puts the seam that far out. A single `radius_m` field would invite exactly that.
    """
    assert bodies.EARTH.aeqd_radius_m != bodies.EARTH.mercator_radius_m
    assert bodies.EARTH.aeqd_radius_m == 6371000.0


# --- The body's own sphere, and the ratio that is the whole cost of not being Earth --------------


def test_earths_ground_sphere_is_its_mercator_sphere_so_the_ratio_is_exactly_one() -> None:
    """Not approximately one — one, and the distinction is the reason every Earth pixel survives.

    EPSG:3857 is defined on a sphere of Earth's own equatorial radius, so the two fields hold the
    same number by construction of the projection rather than by our choice. That identity is what
    lets `ground_metres_per_mercator_unit` be adopted one stage at a time with no restage: at every site
    it reaches, Earth's arithmetic is multiplication by a literal 1.0.

    Asserted with `is`-style exactness on purpose. A near-1.0 would still round-trip most pixels and
    would move a few, which is the shape of change this project cannot see until it ships.
    """
    assert bodies.EARTH.ground_radius_m == bodies.EARTH.mercator_radius_m
    assert bodies.ground_metres_per_mercator_unit(bodies.EARTH) == 1.0


def test_a_body_on_a_smaller_sphere_reports_a_ratio_below_one() -> None:
    """The case Earth cannot test, because Earth is the value every default already holds.

    A synthetic body is the only way to exercise this before a second planet is registered — and it
    is the cheap version of the lesson that a parameterisation is unverified until something
    non-default runs through it. Mars's own sphere is ~53% of Earth's, so one map unit of its
    Mercator raster buys about half a ground metre, and the hillshade z-factor that divides by this
    comes out ~1.88x larger. Getting the direction backwards is a 3.5x error in the exaggeration
    that renders perfectly plausibly.
    """
    smaller = dataclasses.replace(bodies.EARTH, name="smaller", path_prefix="smaller",
                                  ground_radius_m=3396190.0)
    ratio = bodies.ground_metres_per_mercator_unit(smaller)
    assert ratio == pytest.approx(0.532474, abs=1e-6)
    assert 1.0 / ratio == pytest.approx(1.878, abs=1e-3)


def test_ground_metres_per_pixel_composes_from_the_two_fields() -> None:
    """The composition the call sites are meant to write, pinned so it cannot be written backwards.

    `map_units_per_pixel * ground_metres_per_mercator_unit` — units cancel, and the result is what a
    hillshade, a horizon search or a shadow length actually needs. Multiplying by the reciprocal
    instead is dimensionally silent and off by the square of the ratio.
    """
    smaller = dataclasses.replace(bodies.EARTH, name="smaller", path_prefix="smaller",
                                  ground_radius_m=3396190.0, map_units_per_pixel=1222.992453,
                                  tile_max_zoom=6)
    ground = smaller.map_units_per_pixel * bodies.ground_metres_per_mercator_unit(smaller)
    # 651 m/px at z6 on a 21,339 km circumference — the figure MARS.md's ceiling table is built on.
    assert ground == pytest.approx(651.2, abs=0.1)
    earth_ground = (bodies.EARTH.map_units_per_pixel
                    * bodies.ground_metres_per_mercator_unit(bodies.EARTH))
    assert earth_ground == bodies.EARTH.map_units_per_pixel


# --- Mars ----------------------------------------------------------------------------------------


def test_mars_is_registered_and_reachable_by_name() -> None:
    assert bodies.get("mars") is bodies.MARS


def test_mars_projects_on_earths_spheres_and_that_is_deliberate() -> None:
    """The assertion that stops someone "fixing" the registry into something that cannot be tiled.

    Reading `MARS.mercator_radius_m == 6378137.0` next to a planet whose radius is 3,396,190 m looks
    exactly like a copy-paste slip, and correcting it is the natural next edit. It would be wrong:
    PROJ refuses to build an operation between two celestial bodies, and `gdal raster tile`
    reprojects into WebMercatorQuad, so a Mars-radius Mercator raster cannot be cut into tiles at
    all — measured, `gdalwarp -t_srs EPSG:3857` from IAU_2015:49900 exits 1 rather than warping.

    So the sameness is a decision and this is where it is written down. Without it the "fix" passes
    every gate and fails at the tiler, on a run that has already spent an hour warping.
    """
    assert bodies.MARS.mercator_radius_m == bodies.EARTH.mercator_radius_m
    assert bodies.MARS.aeqd_radius_m == bodies.EARTH.aeqd_radius_m


def test_mars_is_the_first_body_whose_ground_sphere_is_not_its_grid() -> None:
    """The one geometry field that actually differs, and the arithmetic the ceiling table rests on.

    Pinned against the published figures rather than restating the division, so the registry and the
    standing brief cannot drift: 651 m/px at z6 is what the brief's ceiling table says, and it comes
    out of these two fields multiplied. The z-factor ratio is the same fact inverted — a hillshade on
    Mars needs 1.878x Earth's z for the same physical exaggeration.
    """
    assert bodies.MARS.ground_radius_m != bodies.MARS.mercator_radius_m
    ratio = bodies.ground_metres_per_mercator_unit(bodies.MARS)
    assert ratio == pytest.approx(0.532474, abs=1e-6)
    assert 1.0 / ratio == pytest.approx(1.878, abs=1e-3)
    ground = bodies.MARS.map_units_per_pixel * ratio
    assert ground == pytest.approx(651.2, abs=0.1)


def test_the_two_registries_agree_on_how_a_body_is_spelled() -> None:
    """The pipeline names a body and the browser names the same body; one word, or they are two.

    The slug is a path segment, an archive key, a tile-URL segment and a route, so a divergence is
    not cosmetic — it is a pyramid written under one name and requested under another, which fails
    as a 404 at the edge long after the run that produced it. Neither side can import the other, so
    the only thing that can hold them together is a scan, in the shape `test_palette.py` already
    uses for the colours the browser cannot import.
    """
    web = (paths.ROOT / "web/src/lib/bodies.ts").read_text(encoding="utf-8")
    match = re.search(r"export type BodySlug = ([^;]+);", web)
    assert match, "web/src/lib/bodies.ts no longer declares a BodySlug union — the guard is blind"
    slugs = set(re.findall(r'"([^"]+)"', match.group(1)))
    assert slugs == set(bodies.BODIES), (
        f"the pipeline knows {sorted(bodies.BODIES)} and the browser knows {sorted(slugs)} — "
        "a body present in one and absent from the other publishes tiles nothing will request"
    )


def test_the_cap_module_no_longer_carries_its_own_sphere_radius() -> None:
    """Anti-regrowth, same shape as the render package's scan."""
    from pipeline.tile import cap_render

    source = Path(cap_render.__file__).read_text(encoding="utf-8")  # pyright: ignore[reportArgumentType]
    assert "6371000" not in source, (
        "cap_render has regrown a hard-coded AEQD sphere radius — it belongs to the body"
    )


def test_the_shade_pass_no_longer_carries_its_own_grid_or_ceiling() -> None:
    """Anti-regrowth over the two constants that survived the body parameterisation.

    THIS IS THE GUARD THAT SHOULD HAVE EXISTED A PHASE AGO. `Z8_RES = 305.7483` and a literal
    `max_zoom=8` sat in this module through a refactor whose entire purpose was to remove exactly
    that, and nothing noticed, because the only thing exercising the parameterisation was the Earth
    run — which produces identical output whether the value comes from the body or from a literal.
    A scan is the only oracle that can see a regrown constant: it type-checks, it tests green, and
    it reads as a tidy local.

    Both spellings are checked because they fail differently. The resolution silently orphans the
    raster of any body whose ceiling is not z8; the ceiling silently cuts every planet to Earth's.
    """
    source = Path(shade_planet.__file__).read_text(encoding="utf-8")  # pyright: ignore[reportArgumentType]
    # The prose above the deleted constant explains WHY it left, and naming the number there would
    # re-create this needle in a comment — so the note describes it and this stays a code scan.
    assert "305.7483" not in source, (
        "shade_planet has regrown a hard-coded grid resolution — it is Body.map_units_per_pixel, "
        "and a literal here warps every planet onto Earth's z8 lattice"
    )
    assert "max_zoom=8" not in source, (
        "shade_planet has regrown a hard-coded tile ceiling — it is Body.tile_max_zoom, and a "
        "literal here cuts every planet's pyramid to Earth's depth"
    )


def test_neither_shading_module_carries_its_own_exaggeration() -> None:
    """Anti-regrowth over the third constant, and the one that reached furthest.

    `EXAG` was a module constant in shade_planet and an IMPORT in cap_render, so the caps drew
    every planet at Earth's relief however `--body` was set — and then feathered that into tiles
    shaded at the body's own. Both spellings are scanned because both are how it comes back: a
    local `EXAG = ...` reads as tidy, and re-importing it from the sibling reads as reuse.

    The name is scanned rather than the number. A literal scan would miss `EXAG = 15` and
    `EXAGGERATION = palette.EXAGGERATION` alike, and both are the same bug: a look value pinned
    at module scope, where a body cannot reach it.
    """
    from pipeline.tile import cap_render

    for module in (shade_planet, cap_render):
        source = Path(module.__file__).read_text(encoding="utf-8")  # pyright: ignore[reportArgumentType]
        assert re.search(r"\bEXAG", source) is None, (
            f"{module.__name__} has regrown a module-scope exaggeration — it is Body.exaggeration, "
            "and a constant here draws every planet at whichever one happens to be written down"
        )


def test_the_hillshade_recipe_records_the_body_s_own_exaggeration() -> None:
    """The freshness half. Recording the exaggeration was always right; sourcing it from a
    module constant meant the record could not MOVE, so re-tuning a body's relief would have left
    its own sidecar unchanged and its hillshade reported fresh. Not a cross-body collision — each
    body writes into its own work tree — but the quieter intra-body one: the recipe answers "would
    a rerun produce different pixels?", and a frozen field always answers no."""
    flatter = dataclasses.replace(bodies.EARTH, exaggeration=3.0)

    earth = json.loads(shade_planet.hs_params(bodies.EARTH))
    other = json.loads(shade_planet.hs_params(flatter))

    assert earth["exag"] == bodies.EARTH.exaggeration
    assert other["exag"] == 3.0
    differing = {key for key in earth | other if earth.get(key) != other.get(key)}
    assert differing == {"exag"}, (
        f"changing only the exaggeration moved {sorted(differing)} in the hillshade recipe — "
        "anything else here is a field that restages for a reason it does not have"
    )


def test_the_cap_recipe_records_the_body_s_own_exaggeration() -> None:
    """The same claim one module over, on the recipe whose subject was actually broken. The
    caps drew every planet at Earth's relief, and the recipe faithfully recorded the constant they
    used — so the record was honest about a shader that was not. Now that the shader asks the body,
    a frozen record is the remaining way to be wrong: re-tune a body's exaggeration and the ~14 GB
    render reports fresh against a recipe that cannot see the change."""
    from pipeline.tile import cap_render

    flatter = dataclasses.replace(bodies.EARTH, exaggeration=3.0)

    earth = json.loads(cap_render.cap_recipe(cap_render.north_grid(bodies.EARTH)))
    other = json.loads(cap_render.cap_recipe(cap_render.north_grid(flatter)))

    assert earth["light"]["exag"] == bodies.EARTH.exaggeration
    assert other["light"]["exag"] == 3.0
    earth["light"].pop("exag")
    other["light"].pop("exag")
    assert earth == other, (
        "changing only the exaggeration moved something else in the cap recipe — the body enters "
        "this record one named field at a time, and a whole-Body inline is how that stops holding"
    )


def test_the_hillshade_is_driven_at_the_body_s_exaggeration(tmp_path, monkeypatch) -> None:
    """The scan above cannot see a bare literal at a CALL SITE, and the recipe tests cannot see a
    pixel path that disagrees with the recipe. This drives the real entry point with a synthetic
    body and reads back the number the shader was actually handed.

    A recipe that says one exaggeration while the shader draws another is the worst shape available:
    the sidecar reports fresh, the pyramid is wrong, and re-running changes nothing.
    """
    flatter = dataclasses.replace(bodies.EARTH, exaggeration=3.0)
    handed: list[float] = []

    def fake(_height, out, exaggeration, *_args, **_kwargs):
        handed.append(exaggeration)
        Path(out).write_text("shaded")

    monkeypatch.setattr(shade_planet.hillshade, "per_row_zfactor_hillshade", fake)
    height = tmp_path / "height_3857.tif"
    height.write_text("heights")

    shade_planet.build_hillshade(tmp_path, height, flatter)

    assert handed == [3.0], (
        f"the hillshade was driven at {handed} for a body whose exaggeration is 3.0 — "
        "the shader has stopped asking the body and gone back to knowing the answer"
    )


def test_the_caps_are_shaded_at_the_body_s_exaggeration(monkeypatch) -> None:
    """The same probe on the module where this was genuinely broken: cap_render imported the
    constant, so both suns lit every planet at Earth's relief. Both are checked because the fill is
    a second call with its own argument list, and a fix applied to one line is how the pair drifts.
    """
    from pipeline.tile import cap_render

    flatter = dataclasses.replace(bodies.EARTH, exaggeration=3.0)
    handed: list[float] = []

    def fake(heights, _cell, zfactor, *_args, **_kwargs):
        handed.append(zfactor)
        return np.zeros((heights.shape[0] - 2, heights.shape[1]), dtype=np.float32)

    monkeypatch.setattr(cap_render.hillshade, "hillshade_array", fake)
    grid = cap_render.north_grid(flatter)
    cap_render._shade(grid, np.zeros((4, 4), dtype=np.float32), np.zeros((4, 4), dtype=np.float32))

    assert handed == [3.0, 3.0], (
        f"the caps' main and fill suns were driven at {handed} for a body whose exaggeration is "
        "3.0 — a cap shaded at another planet's relief feathers into tiles shaded at this one's"
    )


def test_the_projection_s_sphere_and_earth_s_own_are_the_same_number_for_a_reason() -> None:
    """Two literals, one value, and the coincidence is the whole reason Earth hid the distinction.

    `mercator.WEB_MERCATOR_RADIUS_M` states what EPSG:3857 is DEFINED on; `EARTH.mercator_radius_m`
    states which sphere Earth's grid is projected on. They agree because the projection was built
    on Earth's equatorial radius — and that agreement is what makes Earth's ground ratio exactly
    1.0, so every stage can adopt the conversion without restaging a pixel.

    Related rather than collapsed: one is projection maths that no planet can change, the other is a
    registry field a second body answers for itself. Collapsing them would make the identity
    unfalsifiable, and it is the identity that is load-bearing.
    """
    assert mercator.WEB_MERCATOR_RADIUS_M == bodies.EARTH.mercator_radius_m
    assert bodies.ground_metres_per_mercator_unit(bodies.EARTH) == 1.0


def test_every_body_rides_the_projection_s_sphere_because_proj_allows_no_other() -> None:
    """Measured, not assumed: `gdalwarp` refuses EPSG:3857 -> a Mars-radius target with "Source and
    target ellipsoid do not belong to the same celestial body", and it identifies the body from a
    bare radius in a proj4 string — an AEQD written `+a=3396190` is refused the same way an
    EPSG-coded one is. So no body can be given its own projection sphere while its rasters are
    EPSG:3857, and a grid row's latitude is the projection's question on every planet.
    """
    for body in bodies.BODIES.values():
        assert body.mercator_radius_m == mercator.WEB_MERCATOR_RADIUS_M, (
            f"{body.name} projects on a sphere that is not EPSG:3857's — PROJ will refuse to warp "
            "it, and `gdal raster tile` will refuse to cut it"
        )


def test_the_hillshade_recipe_records_the_ground_scale_only_when_it_is_not_the_identity() -> None:
    """The conditional-record idiom, third use in this recipe after the fill and the shadow.

    Earth's scale is exactly 1.0, so writing the key would restage an 8:28 hillshade, a 53.8 min
    composite and a 3:44 cut to reproduce identical bytes — and would report the LIVE pyramid stale.
    Any other body's scale is a genuine input to every slope in the raster, and leaving it out would
    let a re-shade at a corrected scale find a matching sidecar and skip.
    """
    earth = json.loads(shade_planet.hs_params(bodies.EARTH))
    assert "ground_scale" not in earth, (
        "Earth's hillshade recipe grew a key whose value is the identity — the live sidecar on disk "
        "does not have it, so every existing tile just went stale for no pixel change"
    )
    mars = json.loads(shade_planet.hs_params(bodies.MARS))
    assert mars["ground_scale"] == bodies.ground_metres_per_mercator_unit(bodies.MARS)


def test_the_sky_view_is_sized_and_searched_in_ground_metres(monkeypatch, tmp_path) -> None:
    """Both sky-view entry points document that they want a GROUND scale, and this function used to
    hand them map units. The body half of that is fixed, so a smaller planet must search a
    proportionally shorter horizon — otherwise its valleys read as open ground.

    Captured at the boundary rather than compared as pixels: the quantity that was wrong is the
    number crossing into `sky_view`, and asserting on it says which of the two errors is closed.
    """
    import rasterio
    import rasterio.transform

    handed: dict[str, float] = {}
    monkeypatch.setattr(shade_planet, "occlusion_shape",
                        lambda w, h, res: (handed.setdefault("shape_res", res), (8, 16))[1])
    monkeypatch.setattr(shade_planet, "normalised_occlusion",
                        lambda low, m_per_px: (handed.setdefault("search_res", m_per_px), low)[1])

    height = tmp_path / "height_3857.tif"
    transform = rasterio.transform.from_origin(0.0, 5_000_000.0, 305.7483, 305.7483)
    with rasterio.open(height, "w", driver="GTiff", height=32, width=64, count=1,
                       dtype="float32", crs="EPSG:3857", transform=transform) as dataset:
        dataset.write(np.zeros((32, 64), dtype="float32"), 1)

    shade_planet.global_occlusion(height, bodies.EARTH)
    earth = dict(handed)
    handed.clear()
    shade_planet.global_occlusion(height, bodies.MARS)

    assert earth["shape_res"] == bodies.EARTH.map_units_per_pixel, (
        "Earth's sky-view sizing moved — its ground scale is exactly 1.0, so it must not"
    )
    ratio = bodies.ground_metres_per_mercator_unit(bodies.MARS)
    assert handed["shape_res"] == pytest.approx(bodies.MARS.map_units_per_pixel * ratio)
    assert handed["search_res"] == pytest.approx(earth["search_res"]
                                                 * (bodies.MARS.map_units_per_pixel * ratio)
                                                 / bodies.EARTH.map_units_per_pixel)
