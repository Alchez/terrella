"""The body registry: one home for what differs between one planet and the next.

WHY A REGISTRY AT ALL. A wrong sphere radius does not crash: it produces a latitude-varying wrong
exaggeration that renders perfectly plausibly, so a second body turns any duplicated constant into a
silent cross-body bug.

THE BRIDGE TESTS ARE THE POINT OF THIS FILE, and they are temporary by design. The registry states
each value and the tests below hold every remaining copy to it, so the duplication cannot drift; as
each copy is deleted its bridge becomes a statement about the one remaining home. Copied look
constants have already cost this project a full overnight re-render of the heroes; a guarded copy is
the only kind worth having.

NO FIELD MAY CARRY A DEFAULT. That is what makes adding a field to `Body` a hard error at every
call site rather than a silent inheritance of Earth's value by a planet nobody checked.
"""

import ast
import dataclasses
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

from pipeline import bodies, layers, mercator, paths, planet_seam
from pipeline.compose import countries_pmtiles, features_pmtiles
from pipeline.render import palette
from pipeline.tile import cap_render, shade_planet, terrain_rgb

#: A planet whose seam emitted all three rasters — what Earth declares, and the only
#: shape these tests care about unless they say otherwise.
WHOLE_PLANET = planet_seam.KNOWN_RASTERS


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


#: The only two modules allowed to spell Web Mercator's sphere. `mercator.py` states what the
#: projection is DEFINED on; `bodies.py` states it as a planet's own fact. Every other module gets
#: it from one of them.
RADIUS_OWNERS = {"pipeline/mercator.py", "pipeline/bodies.py"}


def test_no_module_regrows_web_mercators_sphere() -> None:
    """The bridge that pinned the two copies is GONE because the copies are.

    Replaced by an anti-regrowth scan rather than deleted outright, in the shape `test_paths.py`
    already uses for filesystem roots: the failure worth catching now is not divergence between two
    literals but the reappearance of a second literal at all. A regrown constant type-checks, tests
    green, and reads as a tidy local, so a scan is the only thing that can see it.

    SWEEPS THE PACKAGE RATHER THAN A LIST OF MODULES, which is the correction this test needed.
    Naming `hillshade` and `snow` described where the constant had been found, not where it could
    appear — and `tile/terrain_rgb.py` then carried an unguarded copy for as long as it existed,
    along with its own transcription of the inverse projection written in a different algebraic
    form. A hand-written list of nouns cannot see the next noun; the closed question is which
    modules are ALLOWED to hold it.

    Parsed rather than grepped, so prose naming the number is prose: `mercator.py`'s own docstring
    cites it, and `bodies.py`'s field notes discuss it, neither of which is a second home.
    """
    offenders = {}
    for path in sorted((paths.ROOT / "pipeline").rglob("*.py")):
        relative = str(path.relative_to(paths.ROOT))
        if relative in RADIUS_OWNERS:
            continue
        found = [node.lineno for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                 if isinstance(node, ast.Constant) and node.value == 6378137.0]
        if found:
            offenders[relative] = found
    assert not offenders, (
        f"these modules have regrown Web Mercator's sphere radius: {offenders}. Import "
        "`mercator.WEB_MERCATOR_RADIUS_M` for a grid question, or read the body's own field for a "
        "ground one — a second literal is how the two silently drift apart."
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


def test_both_roots_follow_a_redirect_so_a_fixture_can_isolate_every_write(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirecting the two roots must move EVERY derived location, not just the data one.

    `work_dir` reads `paths.DATA` at call time, so it always followed. `public_root` used to be a
    module constant binding `paths.ROOT` at import, so it never did — and the asymmetry could not
    surface as an error, because the served root's two readers went stale TOGETHER: `served_url`
    takes a URL relative to the same stale root the asset was written under, so the arithmetic
    agreed and every URL assertion passed. What it produced instead was test output written into the
    real `web/public/`, which `web/.gitignore` covers and the next site build copies into `dist/`.

    The neighbouring `test_served_assets_follow_the_checkout_not_the_data_store` cannot see this: it
    asserts the served path sits under `paths.ROOT`, which is true of the stale root as well.
    """
    monkeypatch.setattr(paths, "ROOT", tmp_path / "checkout")
    monkeypatch.setattr(paths, "DATA", tmp_path / "store")
    assert bodies.public_dir(bodies.EARTH, "caps") == tmp_path / "checkout/web/public/caps"
    assert bodies.work_dir(bodies.EARTH, "cap") == tmp_path / "store/work/cap"


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
    """The one geometry field that actually differs, and the arithmetic every resolution claim uses.

    LITERALS RATHER THAN A RESTATED DIVISION, because a test that recomputes the expression it is
    guarding agrees with any value the registry happens to hold. 325.6 m/px is what a Mars tile
    carries at the equator at this ceiling, and it is the number every band, seam and sampling
    argument about this body is built on. The z-factor ratio is the same fact inverted — a hillshade
    on Mars needs 1.878x Earth's z for the same physical exaggeration.
    """
    assert bodies.MARS.ground_radius_m != bodies.MARS.mercator_radius_m
    ratio = bodies.ground_metres_per_mercator_unit(bodies.MARS)
    assert ratio == pytest.approx(0.532474, abs=1e-6)
    assert 1.0 / ratio == pytest.approx(1.878, abs=1e-3)
    ground = bodies.MARS.map_units_per_pixel * ratio
    assert ground == pytest.approx(325.6, abs=0.1)


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


def _blocks_from(source: str, start: int) -> dict[str, str]:
    """Split a TypeScript object literal into one source block per top-level key.

    BRACE-COUNTED RATHER THAN SPAN-MATCHED, and that is the whole reason this helper exists. A
    regex that runs from a body's key to the next `}` cannot tell which braces enclose the value it
    captured — nest one object literal inside a descriptor (`accent` already is one) and the span
    ends early or late, silently, and the guard above it starts comparing the wrong planet's
    answer. Counting decides enclosure; matching text only guesses at it.

    `start` is the offset just inside the literal's opening brace, so a block this returns can be
    fed straight back in at 0 to split a nested record — which is what reaches `PUBLISHED`'s
    per-layer entries two levels down.
    """
    blocks: dict[str, str] = {}
    index, depth = start, 1
    key_at_top: str | None = None
    block_start = 0
    while index < len(source) and depth > 0:
        character = source[index]
        if depth == 1 and key_at_top is None:
            key = re.match(r"\s*(\w+)\s*:\s*\{", source[index:])
            if key:
                key_at_top = key.group(1)
                index = block_start = index + key.end()
                depth = 2
                continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 1 and key_at_top is not None:
                blocks[key_at_top] = source[block_start:index]
                key_at_top = None
        index += 1
    return blocks


def _record_blocks(relative_path: str, record: str) -> dict[str, str]:
    """One source block per top-level key of `export const <record> = {…}` in a web module."""
    source = (paths.ROOT / relative_path).read_text(encoding="utf-8")
    opening = re.search(rf"export const {record}\b[^=]*=\s*\{{", source)
    assert opening, f"{relative_path} no longer declares a {record} record — the guard is blind"
    return _blocks_from(source, opening.end())


def _browser_descriptor_blocks() -> dict[str, str]:
    """Split `web/src/lib/bodies.ts`'s BODIES record into one source block per body."""
    return _record_blocks("web/src/lib/bodies.ts", "BODIES")


def _browser_zoom(block: str, field: str) -> int:
    """Read a `minZoom:`/`maxZoom:` out of a registry entry, following a named constant.

    The two bodies write this field in different shapes — Earth's entry reads the module constants
    it is the values of, Mars's are literals — so a digits-only match would silently skip Earth and
    leave the guard covering one planet while reading as if it covered both.
    """
    declared = re.search(rf"\b{field}:\s*(\w+)\s*,", block)
    assert declared, f"a published relief entry declares no {field} — the guard is blind"
    value = declared.group(1)
    if value.isdigit():
        return int(value)
    defined = [
        found
        for module in sorted((paths.ROOT / "web/src/lib").glob("*.ts"))
        for found in re.findall(
            rf"^export const {value}\s*=\s*(\d+);", module.read_text(encoding="utf-8"), re.MULTILINE
        )
    ]
    assert len(defined) == 1, (
        f"{field} is declared as `{value}`, which web/src/lib defines {len(defined)} times — "
        "the guard cannot resolve it to one number"
    )
    return int(defined[0])


def _pipeline_zoom_range(layer: str, body: bodies.Body) -> tuple[int | None, int]:
    """Where a published layer's zoom range is DECIDED, pipeline-side. `None` floor = not decided.

    Relief is the only per-body one, which is why it takes the body: its ceiling follows each
    planet's own source data. The other two are Earth's, and their constants live with the producer
    that writes them. Terrain states no floor at all, so there is nothing there to bridge to and the
    caller must not invent one.

    RAISES ON AN UNKNOWN LAYER ON PURPOSE. A fourth pyramid — Mars's features are the one being
    designed — must either name its owner here or make this test say why it has none. Returning a
    default would let a new layer's ceiling go unpinned while every suite stayed green.
    """
    if layer == "relief":
        cut = shade_planet.tile_cut(body)
        return cut["min_zoom"], cut["max_zoom"]
    if layer == "terrain":
        # PER BODY, like `vector` below and for the same reason: the elevation cut descends from
        # that planet's own master, so its ceiling is the master's native zoom. A single arm here
        # handed Mars Earth's answer, which is the silent factor-of-two the producer's
        # `master_zoom_for` records.
        return None, terrain_rgb.master_zoom_for(body)
    if layer == "vector":
        # PER BODY, because `vector` names a ROLE and each planet cuts its own products into it.
        # A single arm here would hand Mars Earth's ceiling the moment it publishes — silently, and
        # in the direction that reads as working: the browser would ask for zooms nobody cut.
        cutter = {"earth": countries_pmtiles, "mars": features_pmtiles}.get(body.name)
        assert cutter is not None, (
            f"`{body.name}` publishes a vector pyramid but no producer is named for it here — "
            "add it beside the module that cuts it rather than letting it borrow another planet's"
        )
        return cutter.MIN_ZOOM, cutter.MAX_ZOOM
    raise AssertionError(
        f"`{layer}` is published but names no pipeline constant that decides its zoom range — "
        "add it here beside the producer that cuts it, or the browser's copy is pinned to nothing"
    )


def test_the_browser_publishes_every_pyramid_at_the_zoom_the_pipeline_cut_it_to() -> None:
    """The zoom range the browser ASKS for against the one the pipeline CUT.

    THE LAST LINK IN THE CHAIN, AND IT WAS THE UNGUARDED ONE. `tile_max_zoom` decides the relief
    cut, `tile_cut` carries it into the pyramid, and `describeArchiveHeaderMismatch` checks that
    pyramid's own header against this registry — but only at runtime, with archives on disk. On a
    checkout without them, which is every CI run, the browser's copy was pinned to nothing: the
    pipeline could say one ceiling and the registry another and both suites would pass. Six comments
    across five web modules drifted to a stale ceiling behind exactly that gap.

    THE FLOOR IS CHECKED WHERE ONE IS DECLARED AND SKIPPED WHERE IT IS NOT, rather than compared
    against a literal 0 here — a 0 written in this file would be one more copy of the number, and
    this test exists to remove copies.
    """
    published = _record_blocks("web/src/lib/tileAddress.ts", "PUBLISHED")
    assert set(published) == set(bodies.BODIES), (
        f"the pipeline knows {sorted(bodies.BODIES)} and the registry publishes for "
        f"{sorted(published)} — one of them is describing a body the other has never heard of"
    )
    seen: set[str] = set()
    for name, block in published.items():
        layers_declared = _blocks_from(block, 0)
        assert "relief" in layers_declared, (
            f"{name} publishes no relief archive — a globe with no relief is not a globe"
        )
        for layer, entry in layers_declared.items():
            floor, ceiling = _pipeline_zoom_range(layer, bodies.BODIES[name])
            expected = {"maxZoom": ceiling} | ({} if floor is None else {"minZoom": floor})
            for field, value in expected.items():
                declared = _browser_zoom(entry, field)
                assert declared == value, (
                    f"{name}/{layer}: the pipeline cuts {field} z{value} and "
                    f"PUBLISHED.{name}.{layer} says z{declared} — the browser would ask for a zoom "
                    "that was never cut, which arrives as a 404 and paints exactly like a tile "
                    "still in flight"
                )
            seen.add(layer)
    # A `null` layer contributes no block, so the loop skips it in silence. This is what notices a
    # pyramid that stopped being published — the loop above would go on passing, having compared one
    # layer fewer and said nothing about it.
    assert seen == {"relief", "terrain", "vector"}, (
        f"the registry publishes {sorted(seen)}, so this test compared no zoom range for "
        f"{sorted({'relief', 'terrain', 'vector'} - seen)} — either that pyramid is gone or it "
        "is newly unpinned, and both need saying out loud"
    )


def test_the_two_registries_hold_one_radius_for_a_body_that_is_really_a_sphere() -> None:
    """Where the two `ground_radius_m` fields agree, and the one place they must not.

    Both sides turn an angle or a map unit into a ground length, and both name the field after the
    body's own sphere — but they are calibrated for different consumers, so a reader who spots the
    mismatch and "fixes" it silently moves one of them. This states which way each goes.

    THE PIPELINE'S IS EQUATORIAL, because its consumer works in EPSG:3857 map units and those units
    are defined on a sphere of 6378137 m. Earth's ratio there is exactly 1.0 by construction of the
    projection, which is the property `ground_metres_per_mercator_unit` is built on.

    THE BROWSER'S IS THE MEAN RADIUS, because its consumer turns an ANGLE into an arc — and because
    6371008.8 is the sphere MapLibre draws the globe on, so the scale ruler measures the geometry it
    is sitting on top of.

    MARS SETTLES THE SHAPE OF THE RULE: its DEM is published on a true sphere with flattening 0, so
    equatorial, mean and polar are one number and both registries carry it. The disagreement belongs
    to Earth alone, and only because Earth is not a sphere.
    """
    blocks = _browser_descriptor_blocks()
    assert set(blocks) == set(bodies.BODIES), (
        f"the pipeline knows {sorted(bodies.BODIES)} and the browser's BODIES record holds "
        f"{sorted(blocks)} — the scan is reading a different set of planets than it is judging"
    )
    declared: dict[str, float] = {}
    for name, block in blocks.items():
        found = re.search(r"\bgroundRadiusM:\s*([0-9_.]+)\b", block)
        assert found, f"the browser descriptor for {name} declares no groundRadiusM"
        declared[name] = float(found.group(1).replace("_", ""))

    assert declared["mars"] == bodies.BODIES["mars"].ground_radius_m, (
        f"Mars is a sphere in both registries, so one number serves both: the pipeline says "
        f"{bodies.BODIES['mars'].ground_radius_m} and the browser says {declared['mars']}"
    )
    assert declared["earth"] != bodies.BODIES["earth"].ground_radius_m, (
        "Earth's two radii are deliberately different — equatorial for Mercator map units, mean for "
        "an arc — so making them equal moves one consumer's answer. See this test's docstring."
    )
    # The size of the deliberate gap, so "different" cannot be satisfied by a typo. 0.11%: the same
    # figure the cap pass met when it adopted its own conversion.
    ratio = bodies.BODIES["earth"].ground_radius_m / declared["earth"]
    assert 1.001 < ratio < 1.0012, f"Earth's two radii differ by {ratio:.6f}, which is not the ellipsoid"


def test_the_two_registries_agree_on_which_bodies_render_polar_caps() -> None:
    """One fact, two languages, and each half decides something the other cannot see.

    The pipeline's `renders_polar_caps` decides whether to spend ~14 GB per pole rendering the two
    AEQD discs; the browser's `rendersPolarCaps` decides whether to fetch them. A disagreement is
    silent in both directions — a globe carrying polar holes it has textures for, or one asking for
    a `caps.json` nobody wrote and swallowing the 404 in a `.catch`.

    WHAT THIS NO LONGER PROVES, since both bodies answer `true`: that the scan reads the right
    planet's block. A scanner that returned Earth's descriptor for every name would pass here now.
    That claim moved to the sibling below, and belongs there rather than here — `path_prefix`'s two
    answers differ in KIND, Earth's empty and Mars's its own name, so a scan reading the wrong body
    fails on Earth alone and can never be satisfied by a registry that happens to agree with itself.
    """
    blocks = _browser_descriptor_blocks()
    assert set(blocks) == set(bodies.BODIES), (
        f"the pipeline knows {sorted(bodies.BODIES)} and the browser's BODIES record holds "
        f"{sorted(blocks)} — the scan is reading a different set of planets than it is judging"
    )
    for name, block in blocks.items():
        declared = re.search(r"\brendersPolarCaps:\s*(true|false)\b", block)
        assert declared, f"the browser descriptor for {name} declares no rendersPolarCaps"
        assert (declared.group(1) == "true") is bodies.BODIES[name].renders_polar_caps, (
            f"{name}: the pipeline says renders_polar_caps="
            f"{bodies.BODIES[name].renders_polar_caps} and the browser says {declared.group(1)}"
        )


def test_the_two_registries_agree_on_where_a_body_nests_its_served_assets() -> None:
    """The prefix that names a body's directories, held across the language boundary that uses it.

    THE PIPELINE WRITES AND THE BROWSER FETCHES, so this is the one field where the two halves never
    meet at runtime and disagreement produces a 200. `cap_render` writes `caps.json` and four texture
    rungs a pole under `public_dir(body, "caps")`, which is `web/public/caps/<path_prefix>`; the
    browser rebuilds that URL from `pathPrefix` in its own registry. Earth's prefix is EMPTY, so a
    browser answer that drifted toward Earth's — an omitted field, a copied descriptor, a slug used
    where a prefix was meant — does not 404. It fetches Earth's manifest, parses it, and draws
    Earth's Arctic over the other planet's pole, correctly sized and silently wrong.

    Non-vacuous by construction, and for a sharper reason than the sibling above: the two answers
    differ in KIND, not just in value. Earth's is empty and Mars's is its own name, so a scan that
    read the wrong body, or a browser field that was really the slug, fails on Earth alone.
    """
    blocks = _browser_descriptor_blocks()
    assert set(blocks) == set(bodies.BODIES), (
        f"the pipeline knows {sorted(bodies.BODIES)} and the browser's BODIES record holds "
        f"{sorted(blocks)} — the scan is reading a different set of planets than it is judging"
    )
    for name, block in blocks.items():
        declared = re.search(r'\bpathPrefix:\s*"([^"]*)"', block)
        assert declared, f"the browser descriptor for {name} declares no pathPrefix"
        assert declared.group(1) == bodies.BODIES[name].path_prefix, (
            f"{name}: the pipeline writes its assets under path_prefix="
            f"{bodies.BODIES[name].path_prefix!r} and the browser fetches them from "
            f"{declared.group(1)!r}"
        )
    # The asymmetry IS the anti-vacuity: without it every body could answer its own slug and this
    # would still pass, which is exactly the drift the field's docstring warns about.
    assert bodies.BODIES["earth"].path_prefix == "", (
        "Earth's prefix stopped being empty, so this guard no longer covers the collapse case and "
        "every served URL on the site has moved"
    )
    assert any(body.path_prefix for body in bodies.BODIES.values()), (
        "no body nests its assets, so a prefix that was ignored entirely would pass this guard"
    )


def test_the_browser_reaches_the_served_assets_the_pipeline_actually_wrote() -> None:
    """The prefix agreeing is necessary and not sufficient — the two must compose to one URL.

    The guard above compares a string to a string. This one runs the pipeline's own `served_url` on
    the file `cap_render` writes and asserts the browser's builder produces the identical text, so a
    change to EITHER side's assembly — a lost separator, a doubled one, a segment reordered — fails
    here rather than in a browser nobody has open.

    `caps.json` specifically, because it is the only cap URL the browser builds. Every texture URL
    is read out of the manifest, so the pipeline states those and no second implementation exists to
    disagree with.
    """
    source = (paths.ROOT / "web/src/lib/assetBase.ts").read_text(encoding="utf-8")
    builder = re.search(r"export function capsManifestUrl\(body: BodySlug\): string \{(.+?)\n\}",
                        source, re.DOTALL)
    assert builder, "assetBase.ts no longer exports capsManifestUrl — this guard is blind"

    for name, body in sorted(bodies.BODIES.items()):
        expected = cap_render.served_url(cap_render.caps_public_dir(body) / "caps.json")
        segments = [segment for segment in ("caps", body.path_prefix, "caps.json") if segment]
        assert expected == "/" + "/".join(segments), (
            f"{name}: the pipeline serves its cap manifest at {expected}, which is not what the "
            f"browser's documented rule (/caps/<prefix>/caps.json, empty prefix collapsing) builds"
        )
    # Earth's exact historical URL, spelled out rather than derived, because it is a CONTRACT with
    # every browser cache in the wild and not merely the output of the rule above.
    assert cap_render.served_url(
        cap_render.caps_public_dir(bodies.BODIES["earth"]) / "caps.json") == "/caps/caps.json"


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

    earth = json.loads(cap_render.cap_recipe(cap_render.north_grid(bodies.EARTH), WHOLE_PLANET))
    other = json.loads(cap_render.cap_recipe(cap_render.north_grid(flatter), WHOLE_PLANET))

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

    ASSERTED AS A RATIO BETWEEN TWO BODIES, not against a literal, because the z-factor stopped being
    the bare exaggeration: the cap divides it by the body's AEQD ground scale, so an equality here
    would only restate that arithmetic and would fail again at the next honest change to it. What
    this test owns is narrower and does not move — that the number reaching the shader tracks THE
    BODY'S exaggeration. A reimported module constant makes both bodies equal and the ratio 1.0;
    `TestTheCapIsShadedInGroundMetres` in test_cap_render.py owns the scale itself.
    """
    from pipeline.tile import cap_render

    handed: list[float] = []

    def fake(heights, _cell, zfactor, *_args, **_kwargs):
        handed.append(zfactor)
        return np.zeros((heights.shape[0] - 2, heights.shape[1]), dtype=np.float32)

    monkeypatch.setattr(cap_render.hillshade, "hillshade_array", fake)
    for exaggeration in (3.0, 15.0):
        body = dataclasses.replace(bodies.EARTH, exaggeration=exaggeration)
        cap_render._shade(cap_render.north_grid(body), np.zeros((4, 4), dtype=np.float32),
                          np.zeros((4, 4), dtype=np.float32))

    main_at_3, fill_at_3, main_at_15, fill_at_15 = handed
    assert (main_at_3, fill_at_3) == (pytest.approx(main_at_15 * 0.2),
                                      pytest.approx(fill_at_15 * 0.2)), (
        f"the caps' suns were driven at {handed} for bodies whose exaggerations are 3.0 and 15.0 — "
        "a cap shaded at another planet's relief feathers into tiles shaded at this one's"
    )
    assert main_at_3 == fill_at_3  # one correction, applied to both lights


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


def test_every_body_names_only_surface_layers_the_pipeline_knows() -> None:
    """A typo in a layer name turns that layer OFF, silently — the same failure the field closes.

    Nothing else would notice: the composite would skip a warp, the recipe would record a layer
    nobody recognises, and the planet would render one product short with every gate green.
    """
    for body in bodies.BODIES.values():
        unknown = body.surface_layers - layers.SURFACE_LAYERS
        assert not unknown, (
            f"{body.name} declares {sorted(unknown)}, which no stage builds — the vocabulary is "
            f"{sorted(layers.SURFACE_LAYERS)}, and an unrecognised name reads as a layer switched off"
        )


#: A body declaring NO surface layer, which Mars supplied until its ice landed.
#:
#: THE LESSON `test_run_pass_preflight.CAPLESS` ALREADY RECORDS, arriving a second time on a
#: different field: a guard whose only negative instance is a live registry value stops testing
#: anything the day that value changes, and stays green while it happens. Four tests in this file
#: took "declares nothing" from Mars and went quiet together the moment it declared one thing. Built
#: off Earth so every unrelated field is a real planet's.
LAYERLESS = dataclasses.replace(bodies.EARTH, name="layerless", path_prefix="layerless",
                                surface_layers=frozenset())


def test_earth_has_every_surface_layer_and_mars_declares_only_what_it_can_produce() -> None:
    """Earth is the reference body, so its set is what "all of them" means.

    Mars's set is the interesting one and it is a statement about our DATA rather than about the
    planet: it declares the one layer a MARTIAN producer answers for, and stays silent on the four
    whose only sources are Earth datasets sitting on this same disk. Pinned as an exact set, so
    adding a layer to Mars has to be a decision someone makes here rather than a set that drifts.
    """
    assert bodies.EARTH.surface_layers == layers.SURFACE_LAYERS
    assert bodies.MARS.surface_layers == frozenset({layers.PERENNIAL_ICE.name})
    assert LAYERLESS.surface_layers == frozenset(), "the negative instance must stay negative"


def test_a_layer_is_refused_for_a_body_that_does_not_declare_it_even_though_the_source_is_there(
        capsys, tmp_path) -> None:
    """THE BUG THIS PHASE EXISTS TO CLOSE, stated as an executable claim.

    Every source behind these layers is a module constant at one global path, so `.exists()` asks
    "have we downloaded Earth's data" — which is True for every body on a build box that has it.
    A gate that checked the file first would let Mars through on Earth's NSIDC snow, warp it onto
    Mars's grid at the same latitudes and composite it: snow in the north, none in the south, no
    error raised, and a planet that looks entirely reasonable.

    So this asserts the refusal WHILE THE SOURCE IS PRESENT. A test that deleted the source first
    would pass against the broken gate too, which is the whole trap.

    THE SOURCE IS A FILE THIS TEST WRITES, deliberately, rather than the real `snow.SP_NC`. Reading
    the constant tied the claim to whether this particular machine happens to hold a multi-gigabyte
    NSIDC download, and the assertion that kept the test honest is exactly what fired on a checkout
    with no data store. The claim is about the ORDER OF TWO QUESTIONS, so any file that exists
    proves it and which file is incidental — building one here makes the test true everywhere
    instead of true on one box. The mutation guarded by this test has the same shape: it only makes
    the subject wrong while a source exists, so an absent store would score it caught while the
    guard never ran.
    """
    present = tmp_path / "persistence.nc"
    present.write_text("only its existence is read")

    assert layers.layer_is_buildable(bodies.EARTH, layers.PERENNIAL_ICE, present, "no ice") is True
    assert layers.layer_is_buildable(LAYERLESS, layers.PERENNIAL_ICE, present, "no ice") is False
    assert "layerless declares no perennial_ice layer" in capsys.readouterr().out


def test_the_composite_recipe_records_only_the_layers_that_are_off() -> None:
    """The conditional-record idiom again, and here it is load-bearing rather than tidy.

    An unbuilt raster is SILENTLY not a dependency — `newest_mtime` scores a missing path 0.0 and
    `composite_deps` lists all four unconditionally — so turning a layer off would otherwise leave
    the old composite, painted with that layer, looking perfectly fresh. Earth has every layer, so
    its list is empty and nothing is written: the live 46 GB composite cannot restage.
    """
    earth = json.loads(shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET))
    assert "layers_off" not in earth, (
        "Earth's composite recipe grew a key for a body that omits nothing — the live sidecar on "
        "disk does not have it, so the whole pyramid just went stale for no pixel change"
    )
    mars = json.loads(shade_planet.composite_params({None: None}, bodies.MARS, WHOLE_PLANET))
    # THE COMPOSITE'S OWN VOCABULARY, not the whole one. `coastline` is a cap-only layer, and
    # recording it here would make a decision about a polar texture restage the 46 GB planet.
    assert mars["layers_off"] == sorted(layers.COMPOSITE_LAYERS - {layers.PERENNIAL_ICE.name})
    assert "coastline" not in mars["layers_off"]
    # The layer Mars DOES declare is absent from the off-list by being present in the render, which
    # is the direction that would fail silently: an over-full list restages for nothing, an
    # under-full one leaves a composite painted with a layer that has since been switched off.
    assert layers.PERENNIAL_ICE.name not in mars["layers_off"]


def _southern_window(body: bodies.Body, persistence: "np.ndarray | None"):
    """One synthetic composite window over land at ~70 degrees south, where the Antarctic patch
    fires. All land, no ocean: the patch's other term is `land`, so a sea-less body is exactly the
    case that would come out entirely white."""
    from rasterio.windows import Window

    rows, cols = 8, 16
    zeros = np.zeros((rows, cols), dtype=np.float32)
    return shade_planet._WindowInputs(
        win=Window(0, 0, cols, rows),  # pyright: ignore[reportCallIssue]
        win_h=rows,
        win_top=-11_000_000.0,   # ~ -68 deg; the whole window sits south of the patch's -60
        win_bottom=-12_000_000.0,
        height_win=zeros,
        ocean_raw=np.zeros((rows, cols), dtype=np.uint8),   # all land
        watercode=np.zeros((rows, cols), dtype=np.uint8),   # no inland water
        hs_raw=np.full((rows, cols), 128, dtype=np.uint8),
        layer_raw={layer.name: persistence if layer is layers.PERENNIAL_ICE else None
                   for layer in layers.WARPED_LAYERS},
        occ_win=zeros,
        body=body)


def test_a_body_without_the_perennial_ice_layer_composites_no_ice_at_all() -> None:
    """Two independent Earth-only rules meet in this window, and both must be off.

    The dataset half: `persistence_raw` was the one read of four with no `.exists()` guard, so a
    body whose snow layer is off used to die here on a raster that was never built. The rule half:
    `antarctic_snow_mask` is pure latitude-and-land with no dataset behind it, so nothing on disk
    could ever switch it off — on a body with no sea, every pixel below 60 south is land, and the
    southern third of the planet would render solid white.
    """
    shared = shade_planet._compute_shared(_southern_window(bodies.MARS, None))
    assert shared.snow_a.max() == 0.0, (
        f"a body with no snow layer painted snow (max alpha {shared.snow_a.max()}) — over all-land "
        "high southern latitudes, which is the Antarctic patch firing on a planet that has none"
    )
    assert shared.ice_a is None


def test_earth_still_forces_its_antarctic_land_white() -> None:
    """The companion that shows the guard above can FAIL — without it the assertion would pass on a
    composite that had simply stopped painting snow for everyone."""
    persistence = np.zeros((8, 16), dtype=np.float32)  # no measured snow; the patch is the only source
    shared = shade_planet._compute_shared(_southern_window(bodies.EARTH, persistence))
    assert shared.snow_a.min() == 1.0, (
        "Earth stopped forcing its Antarctic land white — NSIDC-0791 is northern-hemisphere-only "
        "and RGI excludes region 19, so without this patch the continent renders on the tan ramp"
    )


def test_earths_antarctic_patch_survives_a_missing_persistence_raster() -> None:
    """A producer runs because the BODY declared the layer, never because its raster is on disk.

    Gating on the slice instead is the obvious tidy — it is right there in `layer_raw` — and it is
    correct for every layer but this one, whose southern half is latitude-and-land arithmetic with
    no file behind it. Under that tidy Earth's continent renders on the tan ramp the first time
    NSIDC-0791 is not where it was, with nothing missing that anyone would notice.
    """
    shared = shade_planet._compute_shared(_southern_window(bodies.EARTH, None))
    assert shared.snow_a.min() == 1.0, (
        "Earth's Antarctic land went unforced with no persistence raster — the patch reads no "
        "file, so no absent file should be able to switch it off"
    )


def test_every_built_layer_names_the_raster_the_composite_reads(subtests) -> None:
    """Pinned against literals, because every consumer of these names now derives from this column.

    A dropped `warped_basename` takes its layer out of the warp, out of the window reads and out of
    `composite_deps` in one edit — so the layer stops being painted AND stops being a dependency the
    composite must be newer than, which is a stale pyramid that reports itself fresh forever.
    """
    assert {layer.name: layer.warped_basename for layer in layers.WARPED_LAYERS} == {
        "lake_depth": "lakedepth_3857.tif",
        "perennial_ice": "snow_persistence_3857.tif",
        "glaciers": "glacier_3857.tif",
        "sea_ice": "seaice_3857.tif",
    }
    with subtests.test("every composite layer builds a raster today"):
        assert {layer.name for layer in layers.WARPED_LAYERS} == layers.COMPOSITE_LAYERS, (
            "the two agree today but are set independently — a composite layer answered by pure "
            "arithmetic would carry no basename, so neither column may be derived from the other"
        )
    with subtests.test("the cap-only layer builds nothing"):
        assert layers.COASTLINE.warped_basename is None


def test_the_stage_vocabularies_together_cover_the_whole_one_and_nothing_else(subtests) -> None:
    """Every layer is read by at least one stage.

    A layer no stage claims is one a body can declare and nothing will ever build — a switch wired
    to nothing, which reads exactly like a working one. The mirror failure, a stage naming a layer
    outside the vocabulary, is now structurally impossible: both stage views are derived from the
    same table, so this half of the old test asserted a derivation against itself. What is left is
    the half a table can still get wrong, which is a row that answers `False` to every stage.
    """
    for layer in layers.LAYERS:
        with subtests.test(layer.name):
            assert layer.in_composite or layer.in_cap, (
                f"{layer.name} is read by no stage — a body could declare it and nothing would "
                f"ever build it, and `layers_off` would never mention it either"
            )
    with subtests.test("no stage is empty"):
        assert layers.COMPOSITE_LAYERS and layers.CAP_LAYERS


def test_every_required_raster_is_one_the_planet_seam_can_emit(subtests) -> None:
    """`Layer.requires_raster` holds a NAME, so a typo must not read as "requires nothing".

    The table deliberately does not import `planet_seam` — that module imports `bodies` beside it,
    and the string keeps the dependency one-way. The cost of a string is that nothing at the
    definition site can spell-check it, and the failure is silent in the direction that matters:
    `_require_coherent` compares the misspelling against what a producer emitted, finds it absent,
    and refuses every body that declares the layer — or, if the name collides with nothing anyone
    declares, never fires at all. This is the check that makes the docstring's claim true.
    """
    for layer in layers.LAYERS:
        if layer.requires_raster is None:
            continue
        with subtests.test(layer.name):
            assert layer.requires_raster in planet_seam.KNOWN_RASTERS, (
                f"{layer.name} requires {layer.requires_raster!r}, which no planet stage can emit; "
                f"known rasters are {sorted(planet_seam.KNOWN_RASTERS)}"
            )


def test_the_stages_disagree_about_which_layers_they_read(subtests) -> None:
    """The split is load-bearing, not bookkeeping, so it is pinned by the DIFFERENCES.

    Equal vocabularies would defeat the purpose while passing the coverage test above: the caps would
    record `lake_depth` and `glaciers`, which they never read (`depth=None`, persistence-only snow),
    and the tile composite would record `coastline`, which it cannot contain — so a cap-only look
    decision would restage a 46 GB planet. Over- and under-tracking are both silent.

    DERIVING THE TWO VIEWS FROM ONE TABLE DID NOT MAKE THIS REDUNDANT — it is what keeps the table
    honest. A wrong `in_composite` / `in_cap` column is exactly as silent as two frozensets drifting
    apart was, so these literals are the hand-written expectation the derivation is checked against.
    """
    with subtests.test("cap only"):
        assert layers.CAP_LAYERS - layers.COMPOSITE_LAYERS == {"coastline"}
    with subtests.test("composite only"):
        assert layers.COMPOSITE_LAYERS - layers.CAP_LAYERS == {"lake_depth", "glaciers"}


def test_layers_off_names_what_is_missing_and_stays_silent_when_nothing_is(subtests) -> None:
    """Off, never on. Earth answers with an empty list at every stage, which is what lets the
    callers' conditional record write nothing and leave a live 46 GB composite and a 14 GB cap
    render byte-identical."""
    for name, vocabulary in (("composite", layers.COMPOSITE_LAYERS), ("cap", layers.CAP_LAYERS)):
        with subtests.test(f"earth {name}"):
            assert layers.layers_off(bodies.EARTH, vocabulary) == []
    with subtests.test("mars cap"):
        assert layers.layers_off(bodies.MARS, layers.CAP_LAYERS) == ["coastline", "sea_ice"]
    with subtests.test("a body that declares nothing names the whole vocabulary"):
        # The all-off end of the range, which Mars stopped supplying when its ice landed. Without
        # it the sweep only ever exercises "none off" and "some off", and the branch that names
        # every layer would never run.
        assert layers.layers_off(LAYERLESS, layers.CAP_LAYERS) == sorted(layers.CAP_LAYERS)
    with subtests.test("sorted"):
        # Sorted, so a frozenset's iteration order cannot make one body's recipe two recipes.
        partial = dataclasses.replace(bodies.EARTH, name="partial",
                                      surface_layers=frozenset({"perennial_ice"}))
        assert layers.layers_off(partial, layers.SURFACE_LAYERS) == sorted(
            layers.layers_off(partial, layers.SURFACE_LAYERS))


def test_the_cap_ground_ratio_divides_by_the_cap_sphere_and_not_the_tile_grids() -> None:
    """Two conversions, two spheres, and Earth is the body that cannot tell them apart by value.

    Its Mercator ratio is exactly 1.0 because EPSG:3857 is defined on Earth's own equatorial radius;
    its AEQD ratio is 1.0011202 because the cap discs are drawn on 6371000. Reaching for the wrong
    helper in the cap path is therefore a 0.11% error on Earth — invisible — and a 1.88x error on
    Mars. Pinned against the arithmetic spelled out, so the assertion cannot be satisfied by the
    same expression it is checking.
    """
    assert bodies.ground_metres_per_mercator_unit(bodies.EARTH) == 1.0
    assert bodies.ground_metres_per_aeqd_unit(bodies.EARTH) == pytest.approx(1.0011202, abs=1e-7)
    assert bodies.ground_metres_per_aeqd_unit(bodies.EARTH) == 6378137.0 / 6371000.0
    assert bodies.ground_metres_per_aeqd_unit(bodies.MARS) == 3396190.0 / 6371000.0
    assert bodies.ground_metres_per_aeqd_unit(bodies.MARS) == pytest.approx(0.5330, abs=1e-4)


def test_every_body_rides_the_projections_aeqd_sphere_too(subtests) -> None:
    """The cap's sphere is as forced as the tile grid's, and separately measured: PROJ refuses
    EPSG:3857 -> `+proj=aeqd +a=3396190` with "do not belong to the same celestial body", from a
    bare proj4 string naming no body at all. So the tempting fix — give Mars its own cap sphere —
    fails at the tiler, and this is what makes it fail at the gate instead."""
    for body in bodies.BODIES.values():
        with subtests.test(body.name):
            assert body.aeqd_radius_m == bodies.EARTH.aeqd_radius_m


def test_the_defaulted_field_case_still_names_the_last_field_of_body() -> None:
    """The one mutation case whose validity depends on FIELD ORDER, made executable.

    Defaulting anything but the final field leaves a field without a default after it, so Python
    refuses the class at import: the module never loads, the harness scores the mutation as caught,
    and `test_no_field_carries_a_default_so_a_new_one_must_be_decided_per_body` is never actually
    run. The case becomes a hollow pass that reads exactly like a real one.

    IT HAS NOW DRIFTED TWICE, both times invisibly. The case names a field by text, so appending a
    field to `Body` invalidates it while its needle still matches exactly once — which is all
    `tests/test_sabotage_cases.py` can check, and all it stayed green on. Order is not a property a
    string can carry, so it is asserted here against the dataclass itself.
    """
    from scripts.sabotage import SABOTAGES

    case = next(sabotage for sabotage in SABOTAGES
                if sabotage.guard == "test_no_field_carries_a_default_so_a_new_one_must_be_decided_per_body")
    last = dataclasses.fields(bodies.Body)[-1].name
    assert f"    {last}:" in case.needle, (
        f"the defaulted-field mutation targets {case.needle.strip()!r}, but Body's last field is now "
        f"{last!r} — defaulting anything earlier makes the module unimportable, which the harness "
        "scores as CAUGHT while the guard it names never runs"
    )
