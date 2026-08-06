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

WHICH IS ALSO WHY THIS IS A FLAT REGISTRY OF FROZEN DATACLASSES AND NOT A CLASS HIERARCHY, a
question worth answering once rather than each time it is asked. Inheritance is the mechanism for
acquiring an unexamined answer, so a `class Mars(Body)` would reintroduce exactly what the rule
above exists to refuse. It would also have nothing to dispatch: no consumer anywhere branches on
which body it holds — every one of them reads a FIELD (`body.exaggeration`, `body.ground_radius_m`,
`"snow" in body.surface_layers`), so a subclass would carry no overridden behaviour and be a
constructor call spelled longer. A body's facts are DATA, and a frozen dataclass is how Python
states data.

    from pipeline import bodies
    body = bodies.get("earth")     # raises on an unknown name; never falls back
"""

from dataclasses import dataclass
from pathlib import Path

from pipeline import paths

#: The optional layers a body may declare, and the whole vocabulary `Body.surface_layers` may use.
#:
#: Each names something the render paints OVER the heightfield, and each comes from a dataset that
#: describes exactly one planet — Earth. That is why this is a body fact and not, as it looks, a
#: question of whether a file happens to be on disk: every one of these sources is a module constant
#: at a fixed global path (`snow.SP_NC`, `snow.RGI_GPKG`, `seaice.SEAICE_SRC`, `lake_depth.LAKE_VRT`,
#: `cap_render.COAST_SHP`), shared by every body. So an `.exists()` check answers "did we download
#: Earth's data", which is True on this machine for every planet — and a Mars run would warp Earth's
#: northern-hemisphere snow onto Mars's grid at the same latitudes and composite it. Snow in the
#: north, none in the south, entirely plausible, entirely wrong, and nothing raises.
#:
#: NOT EVERY LAYER IS A RASTER, AND NO STAGE READS ALL OF THEM — hence the two subsets below.
SURFACE_LAYERS = frozenset({"lake_depth", "snow", "glaciers", "sea_ice", "coastline"})

#: The layers the Mercator tile composite reads.
#:
#: `coastline` is absent because the tiles never bake one: coasts and borders are a vector overlay
#: the client draws, and only the caps — which reach past the latitude those vectors can be drawn at
#: — burn the line into their own pixels.
COMPOSITE_LAYERS = frozenset({"lake_depth", "snow", "glaciers", "sea_ice"})

#: The layers the polar cap render reads.
#:
#: No `lake_depth` (the cap composites with `depth=None`) and no `glaciers` (the north's snow is
#: persistence-only), so naming either here would claim a dependency the render does not have.
#:
#: WHY THE VOCABULARY IS SPLIT PER STAGE RATHER THAN SHARED, which is the whole reason these two
#: constants exist: each stage records the layers it is MISSING in its own freshness recipe, so that
#: turning one off restages it — something file mtimes cannot do, because an unbuilt raster scores
#: 0.0 and is therefore silently not a dependency. Recording a layer a stage never reads inverts the
#: trap instead of closing it: switching the coastline would restage a 46 GB tile composite that
#: cannot contain one. Over-tracking and under-tracking are both silent, so this has to be exact.
CAP_LAYERS = frozenset({"snow", "sea_ice", "coastline"})


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
    #: Sphere radius for the polar caps' azimuthal-equidistant projection, in metres.
    #:
    #: A SECOND RADIUS, AND DELIBERATELY NOT THE FIRST. Three are in play on Earth: Web Mercator's
    #: 6378137 (the tile grid), this AEQD sphere at 6371000, and MapLibre's own globe radius of
    #: 6371008.8 on the frontend. The last two sit 8.8 m apart, and that gap is load-bearing — the
    #: cap texture is projected on one and blended against tiles drawn on another, so collapsing
    #: them puts the polar seam exactly that far out. One `radius_m` field would invite the collapse.
    #:
    #: A SECOND UNIT CONVENTION, THEREFORE A SECOND GROUND RATIO. Like the Mercator sphere above,
    #: this one is forced to Earth's for every body — measured, and the interesting half is that a
    #: bare proj4 string does not escape the check: `gdalwarp` from EPSG:3857 to an AEQD written
    #: `+a=3396190 +b=3396190` is refused with "do not belong to the same celestial body (Mars vs
    #: Earth)", with no EPSG code anywhere, while the identical warp to `+a=6371000` succeeds. So a
    #: cap's map units are Earth metres too, and turning them into ground metres needs
    #: `ground_metres_per_aeqd_unit` — NOT `ground_metres_per_mercator_unit`, which divides by a
    #: different sphere. Earth's cap ratio is 1.0011202 rather than 1.0, so unlike the Mercator one
    #: it could not be adopted for free; what made it affordable is that both cap sidecars were
    #: already stale against this very field, so the render it costs was owed either way.
    aeqd_radius_m: float
    #: Radius of the body ITSELF, in metres — what a ground metre is worth on this planet.
    #:
    #: A THIRD RADIUS, AND THE ONLY ONE THAT IS PHYSICS. The two above name projections; this one
    #: names the sphere. They are separate because a radius does exactly one job here — turning an
    #: angle into a length — and that job is asked in three different coordinate systems.
    #:
    #: EARTH HIDES THE DISTINCTION, which is why nothing noticed it until a second body: EPSG:3857
    #: is defined on a sphere of 6378137 m, which is also Earth's own equatorial radius, so
    #: `mercator_radius_m` has been answering two questions with one number. Earth's ratio below is
    #: therefore exactly 1.0 by construction of the projection, not by luck or by rounding.
    #:
    #: WHY A BODY DOES NOT SIMPLY PROJECT ONTO ITS OWN SPHERE, which would make this field
    #: redundant: PROJ refuses to build an operation between two celestial bodies ("Source and
    #: target ellipsoid do not belong to the same celestial body"), and `gdal raster tile` reprojects
    #: into WebMercatorQuad, i.e. EPSG:3857. So a Mars-radius Mercator raster cannot be cut into
    #: tiles at all without disabling that guard globally. Every projection in this pipeline is
    #: therefore Earth-sphered for every body, a non-Earth heightfield enters by having its CRS
    #: DECLARED as EPSG:4326 (an identity on angles; only the sphere label changes), and this field
    #: is the single fact that converts the resulting map units back into real ground metres.
    ground_radius_m: float
    #: Size of one pixel of the EPSG:3857 raster the pyramid is cut from, in MAP UNITS.
    #:
    #: Map units, not ground metres — they are metres on `mercator_radius_m`'s sphere, so a ground
    #: distance is this times `ground_metres_per_mercator_unit(body)`. Writing the conversion out at
    #: each call site is deliberate: the units then cancel visibly, and a site that forgot it reads
    #: wrong.
    #:
    #: STORED RATHER THAN DERIVED FROM `tile_max_zoom`, and the reason is measured. Earth's live
    #: 46 GB `height_3857.tif` was warped at 305.7483, a rounded value: the exact figure is
    #: 305.748113, and `-tap` snapped the grid 12.2 m past the true Mercator edge on every side.
    #: Deriving would not restage anything today — `height_3857` is gated on its sources' mtimes and
    #: every sibling raster compares against height's ACTUAL grid rather than against this number —
    #: it would instead sit inert until the next unrelated re-fuse re-warped height at a new
    #: resolution, moving the grid under all six siblings at once and restaging the planet under
    #: someone else's change. A latent trap that misattributes itself is worse than a recorded
    #: asymmetry, so Earth keeps the number its pixels were actually built at, and
    #: `tests/test_bodies.py` pins every body's value against its own ceiling relationally.
    map_units_per_pixel: float
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
    #: Which of `SURFACE_LAYERS` this body actually has, as a frozenset. Empty is a real answer.
    #:
    #: Spelled out per body rather than defaulting to "all of them", so adding a fifth layer is a
    #: decision for every planet including Earth. `tests/test_bodies.py` refuses a name outside the
    #: vocabulary — a typo would otherwise turn a layer off silently, which is the same failure this
    #: field exists to close.
    #:
    #: THE ANTARCTIC LAND-ICE RULE RIDES WITH `snow`, and that is not a conflation. The rule exists
    #: only because the snow dataset has a hole — NSIDC-0791 is northern-hemisphere-only and RGI
    #: region 19 is excluded — so the continent would render on the tan LAND ramp. It is a patch on
    #: the snow layer, so a body without that layer has nothing to patch. On a body with no sea it
    #: would instead whiten every piece of land below 60 degrees south.
    surface_layers: frozenset[str]
    #: Whether this body PUBLISHES rendered polar-cap textures.
    #:
    #: NOT A STATEMENT ABOUT THE PLANET'S CRYOSPHERE, and the name says `renders` for exactly that
    #: reason: Mars has real polar ice caps, and `False` here would be a plain factual error read
    #: that way. What it describes is the AEQD disc that repairs Web Mercator, which dies at ~85
    #: degrees and leaves a hole at each pole that the tiles cannot fill.
    #:
    #: SO `False` COSTS A VISIBLE HOLE, and that is the trade rather than a free saving. It is the
    #: right answer only while a body's ramps are unratified, because a cap is shaded by the same
    #: `shade.composite` as the tiles: rendering one publishes a look decision. Measured on Mars,
    #: the cap pass runs happily today off the heightfield alone — one source, nothing missing, no
    #: refusal — so without this field a first tile run quietly spends ~14 GB per pole to ship two
    #: discs in a palette nobody has agreed to.
    #:
    #: A body fact rather than a look constant because the two consumers are in different processes:
    #: the shade pass decides whether to invoke the cap pass at all, and the cap pass must give the
    #: same answer when an operator runs it directly. Absence on disk cannot carry that — it cannot
    #: tell "this body publishes none" from "the render died", which is the distinction
    #: `planet_seam` exists to preserve one tier up.
    renders_polar_caps: bool


EARTH = Body(
    name="earth",
    # Web Mercator's sphere. Duplicated today in render/hillshade.py and render/snow.py.
    mercator_radius_m=6378137.0,
    # The caps' AEQD sphere. NOT the Mercator one above, and not MapLibre's globe radius.
    aeqd_radius_m=6371000.0,
    # Earth's own sphere — the SAME number as its Mercator grid, because EPSG:3857 is defined on
    # Earth's equatorial radius. That identity is what makes Earth's ground ratio exactly 1.0 and
    # every existing pixel byte-identical; it is not a copy of the field above.
    ground_radius_m=6378137.0,
    # The ONE home now: the shade pass reads this, and a test scans it for a regrown literal. The
    # number is what the live 46 GB raster was actually warped at, and it is a rounded value — the
    # exact z8 figure is 305.748113. See the field's note for why the rounding stays.
    map_units_per_pixel=305.7483,
    # Duplicated today in render/palette.py, which the hero scene imports directly.
    exaggeration=15.0,
    # The raster cut reads this; compose/countries_pmtiles.py still carries its own copy, because
    # the vector pyramid is Earth-only until a Mars layer is designed. That last copy is bridged.
    tile_max_zoom=8,
    # Empty on purpose — see the field's note. Earth's intermediates stay exactly where they are.
    path_prefix="",
    # All of them, written out rather than spelled `SURFACE_LAYERS`: Earth is the reference body, and
    # "whatever the vocabulary happens to contain" is how it would inherit the next layer unexamined.
    surface_layers=frozenset({"lake_depth", "snow", "glaciers", "sea_ice", "coastline"}),
    # The reference body, and the caps are a signature feature rather than a detail: both poles
    # ship a full rung ladder, feathered into the tiles at the seam.
    renders_polar_caps=True,
)


MARS = Body(
    name="mars",
    # BOTH PROJECTION SPHERES ARE EARTH'S, ON PURPOSE, AND NEITHER IS A COPY-PASTE SLIP. The
    # tempting "fix" is to put Mars's own radius here; it would be wrong, and wrong in a way that
    # surfaces months later. PROJ refuses to build an operation between two celestial bodies, and
    # `gdal raster tile` reprojects into WebMercatorQuad — i.e. EPSG:3857 — so a Mars-radius
    # Mercator raster cannot be cut into tiles at all. Measured, not assumed: `gdalwarp -t_srs
    # EPSG:3857` from IAU_2015:49900 exits 1 with "Source and target ellipsoid do not belong to the
    # same celestial body (Earth vs Mars)". Mars therefore rides Earth's grid, its heightfield
    # enters with its CRS DECLARED as EPSG:4326 — an identity on angles, only the sphere label
    # changes — and `ground_radius_m` below is what converts back. `tests/test_bodies.py` asserts
    # this sameness deliberately, so the "fix" fails at the gate rather than at the tiler.
    mercator_radius_m=6378137.0,
    # The same constraint, separately measured, because the obvious objection is that a hand-written
    # proj4 string names no celestial body: it does not escape the check either. See the field note.
    aeqd_radius_m=6371000.0,
    # The IAU 2015 Mars sphere, which is also what the source DEM's own CRS declares — so our
    # ground metres agree with the grid the data was published on. It is the equatorial radius used
    # as a sphere, NOT the 3389500 m mean; the two differ by 0.2%, and the ceiling table in MARS.md
    # is built on this one. The ratio against the grid sphere is 0.532474, so a hillshade z-factor
    # comes out 1.878x Earth's for the same physical exaggeration.
    ground_radius_m=3396190.0,
    # Exactly 2*pi*6378137 / (512 * 2**6). Stored rather than derived for the reason the field
    # states, and pinned against `tile_max_zoom` relationally — so moving the ceiling without moving
    # this is a red test rather than a pyramid cut at a zoom its raster was not built for.
    map_units_per_pixel=1222.99245256282,
    # JUDGED ON THE SPHERE, which is how Earth's own 15x was settled and the only way this number
    # was ever going to be. The arithmetic that opened at 10x is kept because it is worth knowing it
    # was wrong: MapLibre's globe shader draws every body on one Earth-sized sphere and displaces in
    # metres, so only metres matter, and Mars's ~30 km range is ~1.5x Earth's ~20 km — hence
    # 15 / 1.5 ~ 10. Looking at 10x and 20x side by side at the same camera settled it at 20x.
    #
    # THE SATURATION WORRY WAS MEASURED AND DOES NOT APPLY HERE, and it is recorded because it is
    # the reason not to fear the next step up. Earth is already saturated at 15x, so more steepness
    # there buys less than the number suggests. Mars at 20x is not: on the real hillshade raster,
    # 0.00% of pixels sit at DN 0 or DN 255 and the tonal spread is 48.05 against Earth's 45.59.
    # The term that saturates is the gradient PER PIXEL, and Mars's z6 grid is 651 m/px against
    # Earth's z8 at 306 — half the sampling rate is half the slope. So there is headroom above 20x,
    # and a deeper cut would eat it, which is a thing to re-measure at z7 rather than to assume.
    exaggeration=20.0,
    # PROVISIONAL, for the cheapest lookable thing rather than for the eventual ceiling — a z6
    # pyramid is ~2.8 GB of master against z7's ~11 GB, and its only job is to exist on the sphere.
    # The honest ceiling is probably z7: the blended DEM is HRSC over only 44% of the planet and
    # MOLA upsampled beneath the rest, so z8 buys four times the disk for a 2.8x upsample over most
    # of it. Ratified by looking, never from the table.
    tile_max_zoom=6,
    # Nests, where Earth's is empty. A second body pays no relocation cost, so it starts correct.
    path_prefix="mars",
    # NONE OF THEM, and this is the field's whole reason for existing. Every source behind these
    # layers is an Earth dataset at a fixed global path that IS present on the build box, so the
    # `.exists()` guards that make them "optional" all answer yes for Mars. Left unstated, a Mars
    # pass would warp Earth's snow, glaciers, sea ice and lake bathymetry onto Mars's grid at the
    # same latitudes and paint them — no error, no missing file, and a plausible planet. The
    # coastline is the same failure in vector form: Natural Earth's line burnt into a Martian cap.
    #
    # Empty is a statement about our DATA, not about Mars: it has polar ice, seasonal CO2 frost and
    # its own cryosphere. We have no product for any of it, and the physics is not Earth's, so the
    # honest answer today is none. That is a Phase-2 question to re-ask with Mars on screen.
    surface_layers=frozenset(),
    # ON, AND WHAT IT BUYS IS A PROJECTION REPAIR RATHER THAN ICE. Mars declares no surface layers,
    # so these two discs are the same bare relief as the tiles in the same ramps — the cap exists
    # because Web Mercator carries no data past ~85 degrees and brutally smears the band below it,
    # not because there is snow to paint. Anyone expecting white is expecting `surface_layers`.
    #
    # Held False while the ramps were unratified, since a cap is shaded by the same
    # `shade.composite` as the tiles and rendering one publishes a look decision. That reason
    # expired when the M2a ramp was judged on the sphere; what the False cost in the meantime was
    # not a hole but something worse — `shade_planet.CAP_RGB`, the flat pale plug the cap textures
    # exist to be drawn over, which MapLibre stretched across the pole and which was tested on
    # Earth's globe and rejected.
    renders_polar_caps=True,
)


#: Every body the pipeline knows. Keyed by `Body.name`, which a test pins so one planet cannot
#: acquire two spellings.
BODIES: dict[str, Body] = {EARTH.name: EARTH, MARS.name: MARS}


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


def ground_metres_per_mercator_unit(body: Body) -> float:
    """How many real ground metres one map unit of this body's Mercator raster is worth.

    NAMED FOR ITS PROJECTION, because "map unit" cannot answer the question on its own. This
    pipeline projects into two systems — the Mercator tile grid and the caps' AEQD disc — and each
    is defined on its own sphere, so each has its own conversion. An unqualified name here would
    read as the general one and be adopted by the cap path, which needs `aeqd_radius_m` in the
    denominator and gets a different number (1.00112 for Earth, not 1.0). One name per concept.

    THE WHOLE OF WHAT A NON-EARTH BODY COSTS, in one number. Every projection in this pipeline is
    Earth-sphered (see `ground_radius_m` for the PROJ constraint that forces it), so a raster's map
    units are Earth metres whatever planet the elevations came from. Anything that mixes the two —
    a hillshade dividing a rise in body metres by a run in map units, a horizon search, a shadow
    length — must pass through here or it computes a slope that is plausible at every latitude and
    correct at none. That is the failure this module exists to prevent, and it does not raise.

    Returns EXACTLY 1.0 for Earth, and not by rounding: EPSG:3857's defining sphere is Earth's own
    equatorial radius, so the division is a number by itself. Earth's pixels are therefore
    byte-identical through every call site that adopts this, which is what lets it be adopted one
    stage at a time.

    Composes so the units cancel where it is read:

        ground_metres_per_pixel = body.map_units_per_pixel * ground_metres_per_mercator_unit(body)
    """
    return body.ground_radius_m / body.mercator_radius_m


def ground_metres_per_aeqd_unit(body: Body) -> float:
    """How many real ground metres one map unit of this body's polar-cap AEQD grid is worth.

    THE CAP'S OWN CONVERSION, and deliberately not the Mercator one above. Both answer "what is a map
    unit worth", and they answer differently because they divide by different spheres: a cap disc is
    projected on `aeqd_radius_m` and the tile grid on `mercator_radius_m`. A single
    `ground_metres_per_map_unit` would have been adopted here by name and been wrong by the ratio
    between those two spheres, at every pixel, in the one output where nothing would show it.

    EARTH'S IS NOT 1.0, WHICH IS THE WHOLE DIFFERENCE FROM THE MERCATOR CASE. It is 1.0011202,
    because Earth's Mercator sphere doubles as its `ground_radius_m` and its AEQD sphere does not. So
    adopting this moved Earth's cap pixels, where adopting the Mercator one moved none.

    EXACT FOR A BODY PUBLISHED ON A SPHERE, PARTIAL FOR EARTH — worth stating, because the residual
    is larger than the correction. Measured with `pyproj.Geod` on WGS84: the true meridian arc from
    78N to the pole is 1,340,131 m where this AEQD grid calls it 1,334,339 m, a true ratio of
    1.004341. The 1.001120 here therefore closes about a quarter of that gap and leaves three
    quarters of sphere-versus-ellipsoid, which nothing in this pipeline models. Mars's DEM is
    published on a sphere, so for Mars there is no residual at all and this is simply right.

    Composes the same way, and the units cancel where it is read:

        ground_metres_per_pixel = (2 * grid.edge_m / grid.px) * ground_metres_per_aeqd_unit(body)
    """
    return body.ground_radius_m / body.aeqd_radius_m


def layers_off(body: Body, vocabulary: frozenset[str]) -> list[str]:
    """Which of `vocabulary` this body does NOT have, sorted — one stage's freshness record.

    THE LAYERS THAT ARE OFF, NEVER THE ONES THAT ARE ON, and that asymmetry is load-bearing rather
    than stylistic. Earth declares every layer, so its list is empty and the caller's conditional
    record writes nothing at all, leaving a 46 GB composite and a 14 GB cap render byte-identical.
    Recording the layers that are ON would put a list into Earth's recipe for the first time and
    restage the planet to produce the pixels already sitting there.

    `vocabulary` is the CALLER'S stage vocabulary — `COMPOSITE_LAYERS` or `CAP_LAYERS`, never
    `SURFACE_LAYERS` — so that a stage records only what it actually reads. See `CAP_LAYERS` for why
    a shared vocabulary here would trade one silent freshness bug for another.
    """
    return sorted(vocabulary - body.surface_layers)


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


def public_root() -> Path:
    """The directory the site serves at its URL root.

    Named because two things need it: where a served asset is WRITTEN (`public_dir`) and what its
    URL IS — a path under here, minus this prefix. A caller that assembled the URL from a literal
    instead would be right for Earth, whose segment is empty, and quietly advertise a 404 for every
    body that nests.

    A FUNCTION, NOT A CONSTANT, AND THE DIFFERENCE IS NOT STYLE. As a module constant this bound
    `paths.ROOT` at import, while `work_dir` reads `paths.DATA` at call time — so redirecting both
    roots isolated the working tree and silently left the served tree pointing at the real checkout.
    The failure could not surface as an error: both readers here went stale together, so
    `served_url`'s `relative_to` still matched and every URL assertion still passed. What it did
    instead was write test output into `web/public/`, which `web/.gitignore` covers and the next
    `astro build` copies into `dist/`.
    """
    return paths.ROOT / "web/public"


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
    return public_root() / stage / body.path_prefix
