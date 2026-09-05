"""The single home for what differs between one planet and the next.

Modelled on `paths.py`, which does the same job for filesystem roots: one module states the facts,
a test refuses a second copy anywhere else, and every consumer derives.

A body is the small set of facts that make the same pipeline produce a different planet: geometry,
the vertical exaggeration its relief is drawn at, and how deep its pyramid is cut. Everything else
is data. Its colours are a `palette.Look`, its optional surface layers a `layers.Layer` vocabulary,
and what its planet stage emitted a `planet_seam` declaration.

A registry rather than constants, because a wrong sphere radius does not raise: it scales the
per-row z-factor by latitude and produces relief plausible everywhere and true nowhere. A value that
still has a second home is pinned here by a bridge test in `tests/test_bodies.py`.

Every projection here is Earth-sphered, whatever planet the elevations describe. PROJ refuses an
operation between two celestial bodies and `gdal raster tile` reprojects into WebMercatorQuad, so a
Mars-radius Mercator raster cannot be cut into tiles at all. A non-Earth heightfield therefore enters
by having its CRS declared as EPSG:4326, an identity on angles where only the sphere label changes.
That is the shape of three fields below and of `fuse/relabel_mars.py`, so it is stated once here.

Hence three radii. Each turns an angle into a length, and they are separate because that job is
asked in three coordinate systems. Two name projections and are Earth's for every body by the rule
above; the third names the planet and is the single fact converting map units to ground metres:

    mercator_radius_m   the tile grid's sphere     | forced to Earth's, every body
    aeqd_radius_m       the polar caps' sphere     |
    ground_radius_m     the planet itself            what a ground metre is actually worth

Earth hides the distinction: EPSG:3857 is defined on 6378137 m, which is also Earth's own equatorial
radius, so one number answers two questions there. Earth's Mercator ground ratio is exactly 1.0 by
construction of the projection rather than by rounding, while its cap ratio is 1.0011202, which is
why the two conversions at the foot of this module must never collapse into one
`ground_metres_per_map_unit`.

No field may carry a default, and no body inherits one. A default lets a field added later be taken
unexamined by every planet but the one it was written for, invisible in the diff that adds it, and a
class hierarchy is the same mechanism with inheritance around it. A hierarchy would also have
nothing to dispatch, since every consumer reads a field rather than branching on which body it
holds.

    from pipeline import bodies
    body = bodies.get("earth")     # raises on an unknown name; never falls back
"""

from dataclasses import dataclass
from pathlib import Path

from pipeline import paths


@dataclass(frozen=True)
class Body:
    """One planet's geometry and pyramid depth. Frozen: a stage must not be able to retune another.

    Every field is required, for the reason the module note gives.
    """

    #: Registry key and path segment. Lowercase, no spaces — it names directories and archive keys.
    name: str
    #: The tile grid's sphere, in metres. Consumers turn a Mercator y back into a latitude with it
    #: (`block_plan.row_latitude_deg`) and size the per-row height scaling from it
    #: (`prep_block.row_scale`), both of which must agree with the radius the raster was warped at.
    #: Mixing two of the three yields a latitude-varying error that renders plausibly.
    mercator_radius_m: float
    #: The polar caps' azimuthal-equidistant sphere, in metres, and not the Mercator radius above.
    #:
    #: MapLibre's globe radius is 6371008.8, and the cap texture is projected on this sphere then
    #: blended against tiles drawn on another, so collapsing any two of the three puts the polar seam
    #: 8.8 m out. One `radius_m` field would invite that collapse, and nothing downstream reports it
    #: as more than a seam.
    aeqd_radius_m: float
    #: The body's own sphere, in metres: what a ground metre is worth here, and the only one of the
    #: three that is physics rather than a projection.
    ground_radius_m: float
    #: Size of one pixel of the EPSG:3857 raster the pyramid is cut from, in map units.
    #:
    #: Map units, not ground metres: they are metres on `mercator_radius_m`'s sphere, so a ground
    #: distance is this times `ground_metres_per_mercator_unit(body)`. The conversion is written out
    #: at each call site so the units cancel visibly and a site that forgot it reads wrong.
    #:
    #: Stored rather than derived from `tile_max_zoom`. Earth's live `height_3857.tif` is warped at
    #: this rounded 305.7483 against an exact 305.748113, so deriving would sit inert until the next
    #: unrelated re-fuse warped height at the exact figure, moving the grid under every stage at once
    #: under someone else's change. `tests/test_bodies.py` pins each body's value against its own
    #: ceiling relationally.
    map_units_per_pixel: float
    #: Vertical exaggeration the relief is drawn at, shared by the hero scene and the tile shading.
    #: A look constant rather than a physical one, and not transferable: relief as a fraction of
    #: radius differs by ~2.8x between Earth and Mars, so the same number gives different drama.
    exaggeration: float
    #: Deepest zoom the tile pyramids are cut to. Bounds the raster and vector cuts together — they
    #: must agree, or the layers stop at different zooms and the overlay drifts off its basemap.
    tile_max_zoom: int
    #: Directory segment this body's outputs nest under, both its `data/work/` intermediates and its
    #: served assets under `web/public/`. One prefix for both, since nesting them two ways is two
    #: conventions to remember.
    #:
    #: Earth's is deliberately empty. `data/work/planet_tiles` holds the live pyramid, so moving it
    #: under a new segment would make every stage read as missing and re-derive the whole planet to
    #: produce identical pixels. A second body pays no such cost and nests properly from the start.
    path_prefix: str
    #: Which of `layers.SURFACE_LAYERS` this body actually has, by name. Empty is a real answer.
    #:
    #: Names and not `Layer` objects, because this set is serialised: `layers.layers_off` turns it
    #: into the `layers_off` list inside the planet tier's recipe sidecar, and anything whose JSON
    #: differs restages a whole Earth planet raster for identical pixels.
    #:
    #: Spelled out per body rather than defaulting to all of them, so adding a sixth layer is a
    #: decision for every planet including Earth. `tests/test_bodies.py` refuses a name outside the
    #: vocabulary, since a typo would otherwise turn a layer off silently.
    #:
    #: The Antarctic land-ice rule rides with `perennial_ice`, being a patch on that layer, so a
    #: body without it has nothing to patch. `snow.antarctic_snow_mask` holds why the patch exists.
    surface_layers: frozenset[str]
    #: Whether this body publishes rendered polar-cap textures.
    #:
    #: Not a statement about the planet's cryosphere, which is why the name says `renders`: Mars has
    #: real polar ice caps, and `False` read that way would be a plain factual error. What it
    #: describes is the AEQD disc repairing Web Mercator, which dies at ~85 degrees and leaves a hole
    #: at each pole the tiles cannot fill.
    #:
    #: So `False` costs a visible hole rather than saving anything free, and is the right answer only
    #: while a body's ramps are unratified: a cap is shaded by the look the tiles are, so rendering
    #: one publishes a look decision. The cap pass runs happily off the heightfield alone, so without
    #: this field a first tile run quietly ships two discs in a palette nobody has agreed to.
    #:
    #: A body fact rather than a look constant because the two consumers are in different processes:
    #: the planet pass decides whether to invoke the cap pass at all, and the cap pass must give the
    #: same answer when an operator runs it directly.
    renders_polar_caps: bool
    #: No `planet_producer`: every planet raster is raytraced, and the composite is deleted rather
    #: than parked. `test_bodies.TestTheCompositePlanetProducerIsDeletedAndCannotReturn` refuses it.


EARTH = Body(
    name="earth",
    # Web Mercator's sphere. `mercator.WEB_MERCATOR_RADIUS_M` is the projection's own statement of
    # the same number and is bridged to this field; the two agreeing is a coincidence with its own
    # test, not one value read twice.
    mercator_radius_m=6378137.0,
    # The caps' AEQD sphere. Not the Mercator one above, and not MapLibre's globe radius.
    aeqd_radius_m=6371000.0,
    # The same number as its Mercator grid and not a copy of the field above: EPSG:3857 is defined on
    # Earth's equatorial radius, which is what makes Earth's ground ratio exactly 1.0.
    ground_radius_m=6378137.0,
    # The one home: the planet pass reads this, and a test scans for a regrown literal. See the
    # field's note for why the rounding stays.
    map_units_per_pixel=305.7483,
    # Duplicated today in look/palette.py, which the hero scene imports directly.
    exaggeration=15.0,
    # Both cuts read this: the raster pass, and `countries_pmtiles.MAX_ZOOM` for the vectors.
    tile_max_zoom=8,
    # Empty on purpose — see the field's note. Earth's intermediates stay exactly where they are.
    path_prefix="",
    # All of them, written out rather than spelled `SURFACE_LAYERS`: Earth is the reference body, and
    # "whatever the vocabulary happens to contain" is how it would inherit the next layer unexamined.
    surface_layers=frozenset({"lake_depth", "perennial_ice", "glaciers", "sea_ice", "coastline",
                              "antarctic_rock"}),
    # The reference body, and the caps are a signature feature rather than a detail: both poles
    # ship a full rung ladder, feathered into the tiles at the seam.
    renders_polar_caps=True,
)


MARS = Body(
    name="mars",
    # Both projection spheres are Earth's on purpose, neither a copy-paste slip, for the PROJ
    # constraint the module note holds. The tempting fix is Mars's own radius here, and
    # `tests/test_bodies.py` asserts this sameness so it fails at the gate rather than at the tiler.
    mercator_radius_m=6378137.0,
    # The same constraint, and a hand-written proj4 string naming no celestial body does not escape
    # it either.
    aeqd_radius_m=6371000.0,
    # The IAU 2015 Mars sphere, which the source DEM's own CRS also declares, so our ground metres
    # agree with the grid the data was published on. The equatorial radius used as a sphere, not the
    # 3389500 m mean, the two differing by 0.2%. Its ratio against the grid sphere is 0.532474, so a
    # z-factor comes out 1.878x Earth's for the same physical exaggeration.
    ground_radius_m=3396190.0,
    # Exactly 2*pi*6378137 / (512 * 2**7). Stored rather than derived for the reason the field
    # states, and pinned against `tile_max_zoom` relationally — so moving the ceiling without moving
    # this is a red test rather than a pyramid cut at a zoom its raster was not built for.
    map_units_per_pixel=611.49622628141,
    # Judged on the sphere, which is how Earth's 15x was settled and the only way this one could be.
    # Do not re-derive it from metres: the arithmetic that opened at 10x reasoned from Mars's ~30 km
    # range being ~1.5x Earth's ~20 km, and looking at 10x and 20x side by side settled it at 20x.
    #
    # Unsaturated here where Earth at 15x is already saturated, so a deeper cut has headroom to
    # spend and asks this number for a trim rather than a halving. Only the sphere may decide it.
    exaggeration=20.0,
    # Cut but not yet ratified: a ceiling is settled by being served and looked at, which is how
    # Earth's z8 was settled and the only way this one will be.
    #
    # A rung unlocks one octave of wavelength, and z8's lies wholly below MOLA's Nyquist, so HRSC
    # reaches nearer 5-12% of this grid than the 44% it is published with. The ceiling must not be
    # re-argued from that 44%.
    tile_max_zoom=7,
    # Nests, where Earth's is empty. A second body pays no relocation cost, so it starts correct.
    path_prefix="mars",
    # One of them, and the other four are refused for the reason the vocabulary exists: every source
    # behind lakes, glaciers, sea ice and coastline is an Earth dataset sitting on this box, so left
    # unstated a Mars pass would paint Earth's onto Mars at the same latitudes and raise nothing.
    # Naming a layer here claims a Martian producer answers for it, and Mars's ice grades Viking
    # albedo inside units the USGS mapped, sharing only a name with Earth's snow. The four absent are
    # a statement about our data rather than about Mars, which has a cryosphere of its own.
    surface_layers=frozenset({"perennial_ice"}),
    # On, and what it buys first is a projection repair rather than somewhere to paint ice: Web
    # Mercator carries no data past ~85 degrees and smears the band below it, so these two discs
    # would exist as bare relief in the same ramps with nothing white on them at all.
    #
    # Do not reach for False as a cheap way to skip a render: the cost is not a hole but a flat pale
    # plug that MapLibre stretches across the pole, tested on Earth's globe and rejected.
    renders_polar_caps=True,
)


#: Every body the pipeline knows. Keyed by `Body.name`, which a test pins so one planet cannot
#: acquire two spellings.
BODIES: dict[str, Body] = {EARTH.name: EARTH, MARS.name: MARS}


def get(name: str) -> Body:
    """Look a body up by name, or raise.

    No default and no fallback. A run that quietly borrows Earth's geometry because a name was
    misspelled produces a full pyramid that is wrong everywhere and looks right, which is the single
    most expensive failure this registry exists to make impossible.
    """
    try:
        return BODIES[name]
    except KeyError:
        known = ", ".join(sorted(BODIES))
        raise KeyError(f"unknown body {name!r}; known bodies are: {known}") from None


def ground_metres_per_mercator_unit(body: Body) -> float:
    """How many real ground metres one map unit of this body's Mercator raster is worth.

    The whole of what a non-Earth body costs, in one number. Every projection here is Earth-sphered,
    so a raster's map units are Earth metres whatever planet the elevations came from. Anything
    mixing the two, whether a horizon search or a shadow length, must pass through here or compute a
    slope plausible at every latitude and correct at none. It does not raise. Earth's is exactly 1.0.

    Composes so the units cancel where it is read:

        ground_metres_per_pixel = body.map_units_per_pixel * ground_metres_per_mercator_unit(body)
    """
    return body.ground_radius_m / body.mercator_radius_m


def ground_metres_per_aeqd_unit(body: Body) -> float:
    """How many real ground metres one map unit of this body's polar-cap AEQD grid is worth.

    The cap's own conversion, deliberately not the Mercator one above. Earth's is 1.0011202 rather
    than 1.0, so the two are not interchangeable.

    Exact for a body published on a sphere, partial for Earth, and the residual is larger than the
    correction: measured against WGS84, this closes about a quarter of the gap to the true meridian
    arc and leaves three quarters of sphere-versus-ellipsoid, which nothing in this pipeline models.
    Mars's DEM is published on a sphere, so it has no residual.

    Composes the same way, and the units cancel where it is read:

        ground_metres_per_pixel = (2 * grid.edge_m / grid.px) * ground_metres_per_aeqd_unit(body)
    """
    return body.ground_radius_m / body.aeqd_radius_m


def _require_directory_name(stage: str) -> None:
    """A stage is a single directory name, never a path expression.

    One copy, shared by both resolvers: a duplicated guard is the same drift this module exists to
    remove, and would let one resolver be hardened while the other was not.

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

    The body goes in the path, not in the freshness recipe. Every stage of the tile pipeline is
    gated on a recipe sidecar — `raytrace_params.json`, `tile_params.json`, each cap's own — whose
    *contents* are its dependency: change a byte and the stage restages. A body field in those
    recipes would invalidate Earth's entire correct output the moment a second body existed, for no
    pixel change at all. A directory per body makes every one of those sidecars body-specific for
    free, because they are different files.

    `stage` is a directory name, never a path expression, enforced by `_require_directory_name`.
    """
    _require_directory_name(stage)
    # An empty prefix collapses, which is what keeps Earth on its historical layout.
    return paths.DATA / "work" / body.path_prefix / stage


def public_root() -> Path:
    """The directory the site serves at its URL root.

    Named because two things need it: where a served asset is written (`public_dir`) and what its
    URL is, a path under here minus this prefix. A caller assembling the URL from a literal instead
    would be right for Earth, whose segment is empty, and quietly advertise a 404 for every body that
    nests.

    A function rather than a constant, per `paths`. As a constant it binds `paths.ROOT` at import
    while `work_dir` reads `paths.DATA` at call time, so redirecting both roots isolates the working
    tree and leaves the served tree writing into the real checkout.
    """
    return paths.ROOT / "web/public"


def public_dir(body: Body, stage: str) -> Path:
    """Where one body's served assets live, under `web/public/`.

    A separate root from `work_dir`, and deliberately so. `paths.py` draws this line: intermediates
    follow the data store (relocatable via `MAPS_DATA`), while anything the site actually ships must
    follow the checkout, because the build reads it from there. Collapsing the two would make a
    relocated data store silently publish nothing.

    Earth's assets keep their exact URLs — `/caps/caps.json` is a contract the frontend fetches, and
    an empty prefix is what stops a second body rewriting it. Mars nests one level in.
    """
    _require_directory_name(stage)
    return public_root() / stage / body.path_prefix
