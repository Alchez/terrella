"""The single home for what differs between one planet and the next.

Modelled on `paths.py`, which does the same job for filesystem roots: one module states the facts,
a test enforces that nothing else grows a second copy, and every consumer derives.

WHAT A BODY IS. Not a look and not a dataset — the small set of facts that make the same pipeline
produce a different planet. Geometry (how big the sphere is), the vertical exaggeration its relief
is drawn at, and how deep its pyramid is cut. Everything else about a planet is data.

WHAT A BODY IS NOT, so the neighbours are findable: its colours are a `palette.Look`, its optional
surface layers are a `layers.Layer` vocabulary (a body answers for them in `surface_layers`, but the
vocabulary itself is a pipeline fact), and what its planet stage emitted is a `planet_seam`
declaration.

WHY A REGISTRY AND NOT CONSTANTS. A wrong sphere radius does not raise: it scales the per-row
hillshade z-factor by latitude and produces relief that is plausible everywhere and true nowhere.
Copied look constants have already cost this project one overnight re-render of every hero, so a
value that still has a second home is pinned to this module by a bridge test in
`tests/test_bodies.py`, and each bridge dies with the copy it holds.

EVERY PROJECTION HERE IS EARTH-SPHERED, WHATEVER PLANET THE ELEVATIONS DESCRIBE. Stated once
because it is the shape of three fields below and of `fuse/relabel_mars.py`, not a fact about any
one of them. PROJ refuses to build an operation between two celestial bodies, and `gdal raster
tile` reprojects into WebMercatorQuad — EPSG:3857 — so a Mars-radius Mercator raster cannot be cut
into tiles at all without disabling that guard globally. Measured twice, because the obvious
objection is that a hand-written proj4 string names no body and might slip past: `gdalwarp -t_srs
EPSG:3857` from IAU_2015:49900 exits 1 with "Source and target ellipsoid do not belong to the same
celestial body (Earth vs Mars)", and so does a warp to an AEQD spelled `+a=3396190 +b=3396190`,
with no EPSG code anywhere — while the identical warp to `+a=6371000` succeeds. A non-Earth
heightfield therefore enters by having its CRS DECLARED as EPSG:4326, an identity on angles where
only the sphere label changes.

WHICH IS WHY THERE ARE THREE RADII. Each does the one job a radius does — turn an angle into a
length — and they are separate because that job is asked in three coordinate systems. Two name
projections and are Earth's for every body by the rule above; the third names the planet, and is
the single fact that converts map units back into ground metres:

    mercator_radius_m   the tile grid's sphere     | forced to Earth's, every body
    aeqd_radius_m       the polar caps' sphere     |
    ground_radius_m     the planet itself            what a ground metre is actually worth

EARTH HIDES THE DISTINCTION, which is why nothing noticed it until a second body: EPSG:3857 is
defined on a sphere of 6378137 m, which is also Earth's own equatorial radius, so
`mercator_radius_m` had been answering two questions with one number. Earth's Mercator ground ratio
is therefore exactly 1.0 by construction of the projection rather than by rounding, while its cap
ratio is 1.0011202 — which is why the two conversions at the foot of this module are separate
functions and must never be collapsed into one `ground_metres_per_map_unit`.

NO FIELD MAY CARRY A DEFAULT. A default would let a field added later be inherited unexamined by
every planet but the one it was written for — invisible in the diff that adds it. Without defaults,
adding a field is a hard error at every construction until each body answers for it.

WHICH IS ALSO WHY THIS IS A FLAT REGISTRY OF FROZEN DATACLASSES AND NOT A CLASS HIERARCHY, a
question worth answering once rather than each time it is asked. Inheritance is the mechanism for
acquiring an unexamined answer, so a `class Mars(Body)` would reintroduce exactly what the rule
above exists to refuse. It would also have nothing to dispatch: no consumer anywhere branches on
which body it holds — every one of them reads a FIELD (`body.exaggeration`, `body.ground_radius_m`,
`"perennial_ice" in body.surface_layers`), so a subclass would carry no overridden behaviour and be a
constructor call spelled longer. A body's facts are DATA, and a frozen dataclass is how Python
states data. THIS ARGUMENT IS ABOUT BODIES AND DOES NOT CARRY TO PRODUCERS — those are behaviour and
they do dispatch, which is why `look/perennial_ice.py` is a registry of functions instead.

    from pipeline import bodies
    body = bodies.get("earth")     # raises on an unknown name; never falls back
"""

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
    #: The tile grid's sphere, in metres — one of the three the module note sets out.
    #:
    #: Consumers turn a Mercator y back into a latitude with it and size the per-row hillshade
    #: z-factor from it, both of which must agree with the radius the raster was actually warped
    #: with. Mixing two of the three yields a latitude-varying error that renders plausibly.
    mercator_radius_m: float
    #: The polar caps' azimuthal-equidistant sphere, in metres — NOT the Mercator radius above.
    #:
    #: THE 8.8 m BETWEEN THIS AND THE FRONTEND IS LOAD-BEARING, which is the one thing about this
    #: field the module note does not cover. MapLibre's globe radius is 6371008.8; the cap texture
    #: is projected on this sphere and blended against tiles drawn on another, so collapsing any
    #: two of the three puts the polar seam exactly that far out. One `radius_m` field would invite
    #: the collapse, and nothing downstream would report it as anything but a seam.
    aeqd_radius_m: float
    #: The body's own sphere, in metres — what a ground metre is worth on this planet, and the only
    #: one of the three that is physics rather than a projection. See the module note for why the
    #: other two are Earth's and this one is what converts their map units back.
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
    #: Which of `layers.SURFACE_LAYERS` this body actually has, by name. Empty is a real answer.
    #:
    #: NAMES AND NOT `Layer` OBJECTS, because this set is serialised: `layers.layers_off` turns it
    #: into the `layers_off` list inside `composite_params.json`, and anything whose JSON differs
    #: restages a 33-minute Earth composite for identical pixels.
    #:
    #: Spelled out per body rather than defaulting to "all of them", so adding a sixth layer is a
    #: decision for every planet including Earth. `tests/test_bodies.py` refuses a name outside the
    #: vocabulary — a typo would otherwise turn a layer off silently, which is the same failure this
    #: field exists to close.
    #:
    #: THE ANTARCTIC LAND-ICE RULE RIDES WITH `perennial_ice`, and that is not a conflation. The rule
    #: exists only because the snow dataset has a hole — NSIDC-0791 is northern-hemisphere-only and
    #: RGI region 19 is excluded — so the continent would render on the tan LAND ramp. It is a patch
    #: on that layer, so a body without it has nothing to patch. On a body with no sea it would
    #: instead whiten every piece of land below 60 degrees south.
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
    # Web Mercator's sphere. `mercator.WEB_MERCATOR_RADIUS_M` is the projection's own statement of
    # the same number and is bridged to this field; the two agreeing is a coincidence with its own
    # test, not one value read twice.
    mercator_radius_m=6378137.0,
    # The caps' AEQD sphere. NOT the Mercator one above, and not MapLibre's globe radius.
    aeqd_radius_m=6371000.0,
    # The SAME number as its Mercator grid, and NOT a copy of the field above: EPSG:3857 is defined
    # on Earth's equatorial radius, which is what makes Earth's ground ratio exactly 1.0 and every
    # existing pixel byte-identical through each call site that adopts the conversion.
    ground_radius_m=6378137.0,
    # The ONE home now: the shade pass reads this, and a test scans it for a regrown literal. The
    # number is what the live 46 GB raster was actually warped at, and it is a rounded value — the
    # exact z8 figure is 305.748113. See the field's note for why the rounding stays.
    map_units_per_pixel=305.7483,
    # Duplicated today in look/palette.py, which the hero scene imports directly.
    exaggeration=15.0,
    # Both cuts read this now — the raster pass and, since the two vector composers merged onto one
    # driver, `countries_pmtiles.MAX_ZOOM` as well. The bridging test that stood in for that second
    # copy is gone with it.
    tile_max_zoom=8,
    # Empty on purpose — see the field's note. Earth's intermediates stay exactly where they are.
    path_prefix="",
    # All of them, written out rather than spelled `SURFACE_LAYERS`: Earth is the reference body, and
    # "whatever the vocabulary happens to contain" is how it would inherit the next layer unexamined.
    surface_layers=frozenset({"lake_depth", "perennial_ice", "glaciers", "sea_ice", "coastline"}),
    # The reference body, and the caps are a signature feature rather than a detail: both poles
    # ship a full rung ladder, feathered into the tiles at the seam.
    renders_polar_caps=True,
)


MARS = Body(
    name="mars",
    # BOTH PROJECTION SPHERES ARE EARTH'S, ON PURPOSE, AND NEITHER IS A COPY-PASTE SLIP — the module
    # note holds the PROJ constraint that forces it and the two warps that measured it. The tempting
    # "fix" is Mars's own radius here; `tests/test_bodies.py` asserts this sameness so that fix fails
    # at the gate rather than months later at the tiler.
    mercator_radius_m=6378137.0,
    # The same constraint, separately measured against a hand-written proj4 string naming no
    # celestial body — which does not escape the check either. See the module note.
    aeqd_radius_m=6371000.0,
    # The IAU 2015 Mars sphere, which is also what the source DEM's own CRS declares — so our
    # ground metres agree with the grid the data was published on. It is the equatorial radius used
    # as a sphere, NOT the 3389500 m mean; the two differ by 0.2%. The ratio against the grid sphere
    # is 0.532474, so a hillshade z-factor comes out 1.878x Earth's for the same physical
    # exaggeration.
    ground_radius_m=3396190.0,
    # Exactly 2*pi*6378137 / (512 * 2**7). Stored rather than derived for the reason the field
    # states, and pinned against `tile_max_zoom` relationally — so moving the ceiling without moving
    # this is a red test rather than a pyramid cut at a zoom its raster was not built for.
    map_units_per_pixel=611.49622628141,
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
    #
    # A DEEPER CUT SPENDS SOME OF THAT HEADROOM, AND FAR LESS THAN HALVING THE PIXEL SUGGESTS.
    # The saturating term is the gradient PER PIXEL, which would double with the sampling rate only
    # if relief were scale-free in amplitude. The blend says otherwise — self-affine at a Hurst
    # exponent of 0.875, so RMS slope grows 1.09x per rung. Do not re-derive a 2x from the pixel
    # size: what a rung asks of this number is a trim, and only the sphere may decide it.
    exaggeration=20.0,
    # CUT BUT NOT YET RATIFIED — a ceiling is settled by being served and looked at, which is how
    # Earth's z8 was settled and the only way this one will be. z6 came first as the cheapest
    # lookable thing rather than as an answer.
    #
    # THE SOURCE'S HALF IS MEASURED, AND IT IS NOT THE COVERAGE FIGURE IT LOOKS LIKE. A rung
    # unlocks one octave of wavelength: z7's is 652-1302 m, of which MOLA's own 463 m grid resolves
    # 926-1302 m — so of the 4.28 m RMS z7 adds, 3.25 m is measurement. z8's octave lies wholly
    # below MOLA's Nyquist, and the blend's detail there correlates 0.99 with a bilinear upsample of
    # its own coarse grid, where Earth's fused field returns 0.75 through the identical test. HRSC
    # therefore reaches nearer 5-12% of this grid than the 44% coverage it is published with, and
    # the ceiling must not be re-argued from that 44%.
    tile_max_zoom=7,
    # Nests, where Earth's is empty. A second body pays no relocation cost, so it starts correct.
    path_prefix="mars",
    # ONE OF THEM, AND THE OTHER FOUR ARE REFUSED FOR THE REASON THE VOCABULARY WAS WRITTEN FOR:
    # every source behind lakes, glaciers, sea ice and coastline is an Earth dataset present on this
    # box, so left unstated a Mars pass would paint Earth's onto Mars at the same latitudes and raise
    # nothing. Naming a layer here is a claim that a MARTIAN producer answers for it — Mars's ice
    # grades Viking albedo inside units the USGS mapped, sharing only a name with Earth's snow.
    #
    # Each of the four still absent is a statement about our DATA rather than about Mars: it has
    # seasonal CO2 frost and a cryosphere of its own that no product here describes.
    surface_layers=frozenset({"perennial_ice"}),
    # ON, AND IT PREDATES THE ICE BY SEVERAL COMMITS. What it buys first is a projection repair: Web
    # Mercator carries no data past ~85 degrees and brutally smears the band below it, so these two
    # discs would exist as bare relief in the same ramps even with nothing white to paint on them.
    #
    # Held False until the M2a ramp was ratified, per the field note. What the False cost meanwhile
    # was not a hole but something worse — `shade_planet.CAP_RGB`, the flat pale plug the cap
    # textures exist to be drawn over, which MapLibre stretched across the pole and which was tested
    # on Earth's globe and rejected. Do not reach for False again as a cheap way to skip a render.
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

    NAMED FOR ITS PROJECTION, and there is a second function below named for the other one. An
    unqualified `ground_metres_per_map_unit` would read as the general answer and be adopted by the
    cap path, which divides by a different sphere and gets a different number. One name per concept.

    THE WHOLE OF WHAT A NON-EARTH BODY COSTS, in one number: because every projection here is
    Earth-sphered (module note), a raster's map units are Earth metres whatever planet the
    elevations came from. Anything that mixes the two — a hillshade dividing a rise in body metres
    by a run in map units, a horizon search, a shadow length — must pass through here or it computes
    a slope that is plausible at every latitude and correct at none. It does not raise.

    Earth's is exactly 1.0, so every call site that adopts this keeps its pixels byte-identical —
    which is what let it be adopted one stage at a time.

    Composes so the units cancel where it is read:

        ground_metres_per_pixel = body.map_units_per_pixel * ground_metres_per_mercator_unit(body)
    """
    return body.ground_radius_m / body.mercator_radius_m


def ground_metres_per_aeqd_unit(body: Body) -> float:
    """How many real ground metres one map unit of this body's polar-cap AEQD grid is worth.

    THE CAP'S OWN CONVERSION, deliberately not the Mercator one above — see that function for why
    the two are named apart. Earth's is 1.0011202 rather than 1.0, so adopting this MOVED Earth's cap
    pixels where adopting the Mercator one moved none.

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

    `stage` is a DIRECTORY NAME, never a path expression — enforced by `_require_directory_name`,
    which holds the reason.
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

    A FUNCTION, NOT A CONSTANT, per `paths` — and this module is where that rule was paid for. As a
    constant it bound `paths.ROOT` at import while `work_dir` read `paths.DATA` at call time, so
    redirecting both roots isolated the working tree and left the served tree pointing at the real
    checkout, writing test output into `web/public/` for the next `astro build` to copy into
    `dist/`.
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
