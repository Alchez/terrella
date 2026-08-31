"""Build one relief scene from code: a country's hero, or one block of a planet.

THIS IS THE SHARED RIG AND NOT THE HERO RIG. Two callers stage a render
directory and shell into this exact file: `render_prep.py` for a country in
its own Albers projection, and the block prep for a z8 EPSG:3857 block,
which writes its cuts under the same filenames purely to satisfy the
table below. Nothing here is country-shaped.

Builds the whole scene from the constants below — plane + adaptive-subdivision
displacement, a land ramp with lake/river switches over an optional sea ramp
(plus a snow switch iff snowmask.png exists in the render dir, and a
depth-keyed lake ramp iff lakedepth.tif does), sun plus a shadowless
fill sun, ortho camera, locked render settings.

It began as a reconstruction of a hand-built scene, verified against it by
structural dump-diff and a pixel-diff of test renders. THAT BASELINE IS RETIRED
and no longer shipped: the graph built here is conditional on what the render
directory declared, so no single file can track it, and regenerating one from
this module would only compare the code against itself. `scene_dump` still
verifies a CHANGE, by diffing two dumps of scenes it built itself. The origin
scene is recoverable from history:
  git show 3e35eb6:blender/india_hero_handbuilt_phase0.blend > origin.blend

THE LOOK ARRIVES AS `--body`, WHICH IS A SLUG AND NOT A `Body`: Blender's
interpreter cannot import this project's virtual environment, and
`palette.look_for` keys on slugs for that reason.

Runs inside Blender's Python, which has no GDAL: all geographic math
(projection, frame width, plane aspect) happens in render_prep.py and
arrives here as plain numbers in frame.json — plane height, ortho scale,
displacement scale, render resolution (docs/framing-math.md). The
heightfield's pixel size is cross-checked against frame.json so a stale or
mismatched file fails loudly instead of framing the wrong scene.

Color constants are stored in LINEAR floats exactly as Blender holds them
(hex comments alongside are the sRGB values entered in the GUI, which
converts on entry — bpy does not).

Usage:
  blender -b --python pipeline/render/scene_build.py -- \
      --body earth \
      --render-dir data/work/nepal/render \
      --out blender/nepal_hero.blend \
      [--frame-json data/work/nepal/render/frame.json]  # default: sibling
      [--render blender/renders/nepal_hero_8k.png]      # save, then render
"""

import argparse
import dataclasses
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy  # pyright: ignore[reportMissingImports] — exists only in Blender's Python

# Blender's interpreter knows nothing of the repo; palette is dependency-light by
# design (numpy only, which Blender bundles) precisely so BOTH interpreters can
# import it. parents[2] = the repo root, regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.look import palette
from pipeline.render import render_seam

#: How wide the displacement plane is in Blender units, which is the ruler every other number in
#: this module is written on: `ortho_scale` is a fraction of it, `plane_height_units` is measured
#: against it, and a tile's camera offset is a multiple of it.
#:
#: NOT A RIG CONSTANT AND DELIBERATELY OUTSIDE `Rig`. Every look value there decides what a pixel
#: comes out as; this decides what a unit means, and moving it renders identically because the
#: frame arithmetic that feeds it moves in the same step. It is a constant rather than four
#: literals because the tiling law has to agree with the plane `build_plane` actually adds, and a
#: disagreement photographs the wrong ground and stitches perfectly.
PLANE_WIDTH_UNITS = 2.0


def _rgba(stops):
    """palette Stop list (position, linear RGB) -> the (position, RGBA) ColorRamps take."""
    return [(pos, (*rgb, 1.0)) for pos, rgb in stops]


def arrival_azimuth_deg(rotation):
    """Compass bearing a sun with this XYZ euler ARRIVES FROM, clockwise from north.

    THE ONLY THING ABOUT A SUN THAT IS VISIBLE IN THE OUTPUT, and for two years nothing derived it.
    A Blender sun shines along its own local -Z, so an euler is a statement about where the light
    GOES; the cartographic convention is about where it COMES FROM, and the two differ by 180
    degrees before the euler's own sign conventions are applied at all. The guard that was supposed
    to pin the light asserted `SUN_ROTATION[2] == -45.0`, which stays true with the light arriving
    from any bearing whatever, and the rig shipped 90 degrees off the convention it was written to.

    So this is the executable copy of the conversion, and the pinned number lives in the test that
    calls it. Rotating the sun and its guard together is then the mutation that has to fail, which
    is exactly what a coordinate assertion cannot catch.

    Pure arithmetic on purpose: no `bpy`, so a test can call it without Blender, and it was checked
    against Blender's own world matrix on the renders the 315 decision was taken from.
    """
    rx, ry, rz = rotation
    # Travel direction is Rz @ Ry @ Rx applied to (0, 0, -1), giving a source direction whose
    # horizontal part is sin(rx) * (sin rz, -cos rz). For any sun above the horizon sin(rx) is
    # positive and divides out, so the bearing is the z euler's alone — but only then, which is why
    # the tilt is asserted rather than assumed away.
    if math.sin(rx) <= 0.0:
        raise ValueError(f"a sun tilted {math.degrees(rx):.1f} degrees is at or below the horizon, "
                         f"where it has no arrival bearing to report")
    # The Y euler drops out of that arithmetic entirely, so a yawed light would be REPORTED at a
    # bearing it does not arrive from — and `rotate_arrival` would then confirm its own rotation
    # against that report. Admissible only because no light in the rig is yawed, which is a fact
    # `test_the_rig_it_ships_with_is_not_yawed` keeps true rather than one this may assume.
    if ry != 0.0:
        raise ValueError(f"a light yawed {math.degrees(ry):.1f} degrees about Y has no bearing "
                         f"this can report: the horizontal term is no longer the Z euler's alone")
    return math.degrees(math.atan2(math.sin(rz), -math.cos(rz))) % 360.0


def rotate_arrival(rotation, delta_deg):
    """`rotation` turned so its light ARRIVES `delta_deg` further clockwise. Checks its own work.

    THE EULER TURNS THE OTHER WAY, and that was measured rather than reasoned: +90 on the Z euler
    took the arrival bearing from 315 to 225. This is the sign convention `arrival_azimuth_deg` was
    written about, and a frame lit from the wrong side of the meridian is a plausible frame.

    THE RESIDUAL IS ITSELF AN ANGLE, so it wraps. Comparing it linearly refuses a correct
    180-degree turn, where the move reads +180 and the ask normalises to -180: one rotation, 360
    apart on a straight number line.

    Pure arithmetic, so a test reaches it without Blender — and the check runs at delta 0 too,
    which is every hero and every block, so the conversion cannot rot on the path nobody turns.
    """
    turned = (rotation[0], rotation[1], rotation[2] - math.radians(delta_deg))
    moved = (arrival_azimuth_deg(turned) - arrival_azimuth_deg(rotation) + 180.0) % 360.0 - 180.0
    want = (delta_deg + 180.0) % 360.0 - 180.0
    if abs((moved - want + 180.0) % 360.0 - 180.0) > 1e-6:
        raise ValueError(f"asked for {want:+.4f} degrees of arrival and the euler moved it "
                         f"{moved:+.4f}")
    return turned


def tile_index(text: str) -> tuple[int, int]:
    """`--tile`'s ROW,COL. Parsed here so a malformed one fails before Blender starts.

    Negatives are refused although they are legal ints: -1 is a legal index too, so it would
    photograph the last tile while the driver's recipe recorded the first.
    """
    parts = text.split(",")
    if len(parts) != 2 or not all(part.strip().isdigit() for part in parts):
        raise argparse.ArgumentTypeError(
            f"--tile takes ROW,COL as two non-negative integers, got {text!r}")
    return int(parts[0]), int(parts[1])


def tile_camera_location(ortho_scale, plane_height_units, tile):
    """Where the ortho camera sits to photograph one tile of the plane, as (x, y) in plane units.

    THE SPLIT IS DERIVED FROM `ortho_scale` AND NEVER PASSED IN. The camera fraction the prep chose
    is already in the frame, so a driver asking for tile 1,1 of a frame framed for the whole plane
    is a contradiction visible here — where a split arriving as its own argument would simply agree
    with whichever of the two was wrong.

    MOVING THE OBJECT AND NOT `shift_x`, because shift is expressed in sensor widths and inherits
    the sensor-fit rules, while a location is in the units the plane itself is measured in.

    SQUARE PLANES ONLY, refused rather than generalised. The rows here step by `ortho_scale`, which
    is the plane's own step only while its height equals its width; a block's plane is not square
    and nothing tiles one, so a two-axis version would have no second instance to verify it.
    """
    if abs(plane_height_units - PLANE_WIDTH_UNITS) > 1e-9:
        raise ValueError(f"tiling needs a square plane and this one is {PLANE_WIDTH_UNITS} x "
                         f"{plane_height_units} units")
    exact = PLANE_WIDTH_UNITS / ortho_scale
    split = round(exact)
    if split < 1 or abs(exact - split) > 1e-9:
        raise ValueError(f"a camera spanning {ortho_scale} of a {PLANE_WIDTH_UNITS}-unit plane "
                         f"tiles it {exact:.4f} times, which is not a whole number, so no set of "
                         f"tiles covers it")
    row, col = tile
    if not (0 <= row < split and 0 <= col < split):
        raise ValueError(f"tile {row},{col} is outside the {split}x{split} grid this frame's "
                         f"camera fraction implies")
    half = PLANE_WIDTH_UNITS / 2
    return ((col + 0.5) * ortho_scale - half, half - (row + 0.5) * ortho_scale)


# ---- locked look
# ---- angle, land ramp top). Colour + sun-altitude constants are DERIVED from
# ---- pipeline/look/palette.py since the hero sea-sync: copies drifted three
# ---- times (sea ramp, water tint, sun altitude) —
# ---- imports cannot. WORLD_*/FILL_*/SUN_ANGLE/STRENGTH stay local: they have no
# ---- tile counterpart or are deliberately not ports (ART.md hero→tile map). ----
@dataclasses.dataclass(frozen=True)
class Rig:
    """Every constant that reaches a rendered pixel and is this module's rather than a look's.

    ONE STRUCTURE SO THE RECIPE CAN BE DERIVED RATHER THAN ENUMERATED. `rig_recipe` is
    `dataclasses.asdict` of the instance below, which makes a forgotten constant *unrepresentable*
    instead of merely caught. What it replaces was a hand-written list of keys policed by a scan for
    module-level ALL-CAPS names, and that scan is blind by construction to a value written inline in
    a function body: three such values shipped, reaching every pixel and no freshness record.

    FIELD NAMES ARE RECIPE KEYS, so renaming one restages every rendered block. That is the price of
    the derivation and it is deliberate: the alternative is a name-to-key mapping, which is the
    second copy this exists to delete.
    """

    displacement_midlevel: float
    sun_rotation: tuple[float, float, float]
    sun_angle: float
    sun_strength: float
    fill_rotation: tuple[float, float, float]
    fill_angle: float
    #: 15% of `sun_strength`; a shadowless SE fill so shadowed faces keep directional modeling and
    #: never go pure black. The comment said SE while the light arrived from NE; putting the main
    #: sun on 315 put this on 135 and made it true. `arrival_azimuth_deg` is what says so.
    fill_strength: float
    #: ACHROMATIC ON PURPOSE, and it is the scene's only ambient light rather than a backdrop
    #: swatch. Authored warm as `F2E7D5` it arrived with a linear B/R of 0.749, and a tint does not
    #: tint a near-white surface, it REPLACES it: measured on the hero arms that cost snow 64% of
    #: its blue, the sea 7%, and land nothing. Its grey is the luminance of that warm colour, so the
    #: move was hue-only and not the twice-rejected ambient raise. Re-warming it to colour the
    #: backdrop tints every white on the planet to do it.
    world_rgba: tuple[float, float, float, float]
    world_strength: float
    water_rgba: tuple[float, float, float, float]
    #: NO SNOW OR ICE ALBEDO LIVES HERE. Both were module constants spelling Earth's whites, wired
    #: into every body's render while the composite tier asked each body's registry — which on Earth
    #: returns that same constant, so the two agreed by coincidence of value and nothing went red.
    #: The colour arrives per render directory through `render_seam.paint_for`; re-adding a default
    #: here restores the silent fallback that hid this.
    #: Depth-position ramp; stop 0 IS the flat water tint.
    lake_stops: list[tuple[float, tuple[float, float, float, float]]]
    ramp_interpolation: str
    #: A Cycles SAMPLE COUNT, and the one number here measured in the same units as a block edge
    #: without being one. Never search-and-replace it.
    samples: int
    adaptive_threshold: float
    dicing_rate: float
    #: Per PATCH, not per mesh — `base_patches` holds what that means.
    max_subdivisions: int
    #: How much coarser geometry outside the camera is diced. It exists for the block path, whose
    #: plane carries terrain far past the traced rectangle so that off-block ridges cast shadows in;
    #: at Earth's widest that plane is 7,808 px against a 4,352 px frame, so most of the mesh is
    #: never seen. PINNED BECAUSE IT WAS AN UNRECORDED BLENDER DEFAULT, not because it is a quality
    #: lever: 4, 16 and 64 sit within 0.06 DN mean of each other on the same block, against 37.58 DN
    #: for the control that deletes the context outright. 16 over the default 4 for memory.
    offscreen_dicing_scale: float
    bounces: dict[str, int]
    clamp_indirect: float
    #: Set on EVERY image the rig loads, so 0-255 maps linearly to 0-1 with no sRGB transform on
    #: top — the thing a binary mask never notices and a soft alpha very much does. One of the
    #: founding bpy lessons, and it was spelled inline in `load_image` where no recipe could see it.
    image_colorspace: str
    #: The other end of the same axis: how linear light becomes an 8-bit value, and the last thing
    #: to touch every pixel in the frame. It must be a VIEW name from Blender's OCIO config, not a
    #: colorspace name. Spelled inline in `configure_render` until snow was measured clipping under
    #: it, so no change of tone map could restage anything.
    view_transform: str


RIG = Rig(
    displacement_midlevel=0.0,
    sun_rotation=(math.radians(90.0 - palette.SUN_ALT_DEG), 0.0, math.radians(-135.0)),
    sun_angle=math.radians(palette.SUN_ANGULAR_DIAMETER_DEG),
    sun_strength=3.0,
    fill_rotation=(math.radians(30.0), 0.0, math.radians(45.0)),
    fill_angle=math.radians(10.0),
    fill_strength=0.45,
    world_rgba=(0.808332, 0.808332, 0.808332, 1.0),   # the luminance F2E7D5 carried
    world_strength=0.3,
    # 8EC6C4 — sea surface +7%, pinned relationally (the 98C5C8 drift's cure)
    water_rgba=(*palette.srgb8_to_linear(palette.WATER_RGB), 1.0),
    lake_stops=_rgba(palette.LAKE_STOPS),
    ramp_interpolation="EASE",
    samples=4096,
    adaptive_threshold=0.01,
    dicing_rate=1.0,
    max_subdivisions=12,
    offscreen_dicing_scale=16.0,
    bounces=dict(max_bounces=12, diffuse_bounces=4, glossy_bounces=4,
                 transmission_bounces=12, volume_bounces=0),
    clamp_indirect=10.0,
    image_colorspace="Non-Color",
    view_transform="Khronos PBR Neutral",
)

@dataclasses.dataclass(frozen=True)
class TextureSpec:
    """One image node's whole wiring, declared here rather than spelled at the call site.

    EVERY VALUE ON A TEXTURE IS A LOOK DECISION EXCEPT ITS NAME. `interpolation` decides whether a
    mask has a hard edge or a feathered one; `extension` decides whether a texture wraps at the
    plane's UV boundary, which at the poles is whether one pole's row bleeds into the other's. Both
    reach every pixel and neither moves an mtime, so both belong in the recipe.

    The name is an IDENTITY and not a look value: renaming a node consistently renders
    byte-identically. It is therefore the one field `rig_recipe` leaves out, which is why the
    recipe keys this table by `filename` rather than by the name that opens it here.

    `optional` is the raster's presence, never a look: an optional node is built iff its file was
    declared, which is how a body that draws no sea ice simply has no ice node.
    """

    name: str
    filename: str
    interpolation: str
    extension: str
    optional: bool


#: Every image node the rig can build, in creation order: the mandatory four are built by one loop
#: in this sequence and the optional four at their own sites, where their mixes and ramps are wired.
TEXTURES = {
    spec.name: spec for spec in (
        TextureSpec("Heightfield", render_seam.HEIGHTFIELD, "Linear", "REPEAT", optional=False),
        TextureSpec("Ocean Mask", render_seam.OCEANMASK, "Closest", "REPEAT", optional=False),
        TextureSpec("Inland Lake", render_seam.INLANDLAKE, "Closest", "REPEAT", optional=False),
        TextureSpec("River", render_seam.RIVER, "Closest", "REPEAT", optional=False),
        # Closest because snow is a hard-edged mask; the softening it ships with is baked into the
        # raster by `snow.soften_source_cells`, never asked of the sampler.
        TextureSpec("Snow Mask", render_seam.SNOWMASK, "Closest", "REPEAT", optional=True),
        # Linear on both of these: a continuous field, like the heightfield.
        TextureSpec("Lake Depth", render_seam.LAKEDEPTH, "Linear", "REPEAT", optional=True),
        TextureSpec("Sea Ice", render_seam.SEAICE, "Linear", "REPEAT", optional=True),
        # The rowscale column is one texel wide, so there is nothing to interpolate across u, and
        # EXTEND rather than REPEAT is what stops one pole's row wrapping into the other's.
        TextureSpec("Row Scale", render_seam.ROWSCALE, "Closest", "EXTEND", optional=True),
    )
}

#: The one texture a look can decline, being the sea branch's own input.
SEA_IMAGE = "Ocean Mask"


def texture_for(filename: str) -> TextureSpec:
    """The one spec that reads this raster, so no call site spells a node's values itself."""
    for spec in TEXTURES.values():
        if spec.filename == filename:
            return spec
    raise KeyError(f"no texture declared for {filename}")


@dataclasses.dataclass(frozen=True)
class LookConstants:
    """One look's ramps in the shapes bpy takes, rather than the ones palette authors them in.

    `sea_range` and `sea_stops` are both-or-neither: `Look.sea = None` says the planet draws no
    sea, so four nodes are never built rather than built in a colour no pixel can select.
    """

    land_range: tuple[float, float]
    land_stops: list[tuple[float, tuple[float, float, float, float]]]
    sea_range: tuple[float, float] | None
    sea_stops: list[tuple[float, tuple[float, float, float, float]]] | None


def look_constants(look: palette.Look) -> LookConstants:
    """Derive the rig's ramp inputs from a look, restating none of them.

    BOTH ENDS OF EACH RANGE COME OFF THE `Surface` rather than restating the 0.0, which was the
    same Earth-is-the-datum assumption `origin_m` exists to remove. No assertion over Earth can
    tell the read from the restatement, so `test_scene_build_sync` supplies a moved origin.
    """
    sea = look.sea
    return LookConstants(
        land_range=(look.land.origin_m, look.land.extreme_m),  # meters -> ramp position 0..1
        land_stops=_rgba(look.land.stops),
        sea_range=None if sea is None else (sea.extreme_m, sea.origin_m),
        sea_stops=None if sea is None else _rgba(sea.stops),
    )


def rig_recipe(look: palette.Look) -> dict[str, Any]:
    """Every constant here that can move a rendered pixel, keyed by its own name.

    DERIVED FROM THE STRUCTURE, NEVER ENUMERATED, and that replaced a hand-written list policed by a
    scan of this module's capitals. A list kept beside the constants still goes quietly short — the
    constant gets added, the list does not, and the output rendered with the old value reads as
    current forever — and the scan could not see a value spelled inline in a function body at all.
    So there is no list: `Rig` and `TEXTURES` are the enumeration, and the capitals scan now asks the
    opposite question, that no constant survives OUTSIDE them.

    WHAT IS STILL SPELLED INLINE IS THEREFORE INVISIBLE HERE. Those values are pinned rather than
    derived, and `TestTheBuilderSpellsNoLookValueWhereTheRecipeCannotSeeIt` enumerates them and
    holds both the reason and the cost of moving them in.

    A HASH OF THIS FILE WOULD ALSO BE HONEST AND IS DELIBERATELY NOT WHAT THIS IS. It would restage
    a planet render on a docstring edit, and the render is the most expensive output the project
    has; the point of a recipe over a source stamp is that it moves when a VALUE moves.

    The look arrives as an argument because it is not this module's to own — `look_constants` is
    what turns it into the numbers the graph takes, and both ends of every ramp ride along.
    """
    constants = look_constants(look)
    return {
        # DERIVED, NEVER ENUMERATED. A field added to `Rig` is in the recipe with nothing to
        # remember, which is the whole reason the constants are a structure.
        "rig": dataclasses.asdict(RIG),
        # DERIVED TOO, and the whole table rather than the four this look loads: the optional ones
        # are declined by a body's planet seam rather than by its look, so recording only what is
        # loaded would let a planet that GAINED sea ice restage nothing. An interpolation is as much
        # a look decision as a colour is — an oceanmask read Linear instead of Closest feathers
        # every coastline — and it is the half that used to be spelled inline where no recipe saw it.
        #
        # KEYED BY THE RASTER AND MINUS THE NODE'S NAME, which is the one field in the row that
        # cannot move a pixel: renaming a node consistently renders byte-identically, so recorded,
        # it put 11h41m of Cycles plus both cap discs behind a change that moves nothing. Excluded
        # BY NAME rather than by listing what to keep, so a field added to `TextureSpec` later is
        # recorded with nothing here to remember. `TestRenamingANodeDoesNotRestageThePlanet` holds
        # both directions, its control being that `interpolation` in the same row still moves this.
        "textures": {spec.filename: {field: value
                                     for field, value in dataclasses.asdict(spec).items()
                                     if field != "name"}
                     for spec in TEXTURES.values()},
        "sea_texture": None if look.sea is None else TEXTURES[SEA_IMAGE].filename,
        "look": {
            "land_range": list(constants.land_range),
            "land_stops": [[position, list(rgba)] for position, rgba in constants.land_stops],
            "sea_range": None if constants.sea_range is None else list(constants.sea_range),
            "sea_stops": None if constants.sea_stops is None else
            [[position, list(rgba)] for position, rgba in constants.sea_stops],
        },
    }


def textures_for(look: palette.Look, declared: frozenset[str]) -> dict[str, TextureSpec]:
    """The mandatory textures this render directory can actually supply, in table order.

    THE OPTIONAL ONES ARE NOT HERE because they are built at their own sites, beside the mixes and
    ramps they feed, which is what keeps each optional branch readable as one block.

    A DECLARATION DECIDES THIS AND NEVER `Path.exists()`, which is the rule the optional four have
    always followed and these four used to be exempt from. `prep_block.build` writes the lake and
    river masks only when the planet seam declared a watermask, so the rig loading both for every
    look made a body with no inland water unrenderable — refused before its first block rather than
    drawn without them. What is loaded is now what some stage said it wrote.

    A LOOK STILL ANSWERS FOR THE SEA AND THAT HAS NOT COLLAPSED INTO THE DECLARATION. `Look.sea`
    decides whether the sea BRANCH exists in the graph; the declaration decides whether the IMAGE
    can be loaded. The pair that must never resolve quietly is a look with a sea over a directory
    with no oceanmask: dropping the image there wires the sea ramp to nothing and renders a planet
    of land, which is indistinguishable from a correct render of a body that has no sea. So it
    raises, on the same reasoning that keeps this off `Path.exists()` in the first place.
    """
    if look.sea is not None and TEXTURES[SEA_IMAGE].filename not in declared:
        raise ValueError(
            f"this look draws a sea but the render directory declared no "
            f"{TEXTURES[SEA_IMAGE].filename}: {sorted(declared)}. A sea ramp with no mask to "
            f"select it renders the whole planet as land, which is why this refuses rather than "
            f"loading the smaller set.")
    return {name: spec for name, spec in TEXTURES.items()
            if not spec.optional and spec.filename in declared}


def make_texture(nt, render_dir, spec: TextureSpec):
    """Build one image node entirely from its declaration.

    THE ONLY PLACE AN IMAGE NODE IS CONFIGURED, so there is nowhere left to spell an interpolation
    or an extension inline. That is what closes the hole the capitals scan could never see: three
    nodes set those values as literals here for months, reaching every rendered pixel and no recipe.
    """
    node = nt.nodes.new("ShaderNodeTexImage")
    node.name = spec.name
    node.image = load_image(render_dir, spec.filename)
    node.interpolation = spec.interpolation
    node.extension = spec.extension
    return node


def clear_scene():
    """Empty the startup scene but keep user preferences (OptiX device)."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                  bpy.data.cameras, bpy.data.images, bpy.data.worlds):
        for item in list(block):
            block.remove(item)


def plane_span_px(frame):
    """How many RENDER pixels the displacement plane spans, which is what dicing counts.

    NOT the heightfield's pixel width, which is the tempting number and is wrong on both paths for
    opposite reasons: a hero's 16384-wide grid is photographed at 7680, and a block's plane is
    deliberately wider than the rectangle its camera sees. What both have in common is the frame's
    own arithmetic — the plane is 2.0 Blender units across, the camera spans `ortho_scale` of them
    along the longer axis, and the render puts its long resolution across that span.
    """
    pixels_per_unit = max(frame["res_x"], frame["res_y"]) / frame["ortho_scale"]
    return max(PLANE_WIDTH_UNITS, frame["plane_height_units"]) * pixels_per_unit


def base_patches(span_px):
    """Quads per plane edge, so adaptive subdivision can reach one micropolygon per pixel.

    `MAX_SUBDIVISIONS` CAPS EACH PATCH, NOT THE MESH, and that is the whole reason this exists. The
    plane is added as a single quad, so the cap is 2**12 = 4096 micropolygons along its entire
    edge however many pixels the render asks for. Past that, Cycles dices coarser than the pixels
    and the displacement detail the raytrace exists for is quietly lost — no warning, no error, an
    image that merely looks a little softer than it should.

    Measured at 256 px, where 256 micropolygons per edge are needed: a bare quad at maxsub 5
    (cap 32) differs from a maxsub 9 reference by 26.10 DN mean and 154 max, while an 8x8 grid at
    maxsub 5 is bit-identical to that reference, 0.0000 DN. It is also bit-identical when the cap
    is not binding, so a patch count larger than necessary costs nothing.

    A GRID RATHER THAN A LARGER `MAX_SUBDIVISIONS` because a constant has to be re-derived every
    time the block edge or the context moves, and this does not: it is computed from the frame that
    is actually being rendered. `test_scene_build_sync` asserts every planned block on every
    registered body clears one micropolygon per pixel through it.

    IT IS REACHED ONLY THROUGH `--base-grid fitted`, AND THE REASON IS A HARD VRAM CEILING RATHER
    THAN A COST. The grid multiplies micropolygons by 4x on both callers alike; what differs is the
    total, because `OFFSCREEN_DICING_SCALE` coarsens the ~69% of a block's plane its camera never
    sees while a hero's plane is entirely in frame. Measured on this box's 12 GB card: a block lands
    near 21M and is comfortable; Nepal at 41.8M renders but takes 177% longer; Australia at 67M
    fails outright with `Failed to build OptiX acceleration structure`, having also wanted 17.0 GB
    of host against a 16 G rule. So the hero lane keeps the single quad -- knowingly under-diced,
    and the alternative is not a slower hero but no hero at all. Which frame sizes sit on which side
    of that wall is unmeasured; Nepal at 36.8 Mpx clears it and Australia at 58.8 does not.
    """
    return max(1, math.ceil(span_px / 2 ** RIG.max_subdivisions))


def build_plane(height, patches_per_edge):
    # NO DEFAULT, for the reason no field on `Body` has one. A defaulted 1 is exactly the value
    # that under-dices in silence, so a caller that dropped the argument would render a softer
    # planet and raise nothing; without one it is a TypeError before Cycles starts.
    bpy.ops.mesh.primitive_plane_add(size=PLANE_WIDTH_UNITS)
    ob = bpy.context.active_object
    ob.name = "Plane"
    for vertex in ob.data.vertices:
        vertex.co.y *= height / PLANE_WIDTH_UNITS
    if patches_per_edge > 1:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.subdivide(number_cuts=patches_per_edge - 1)
        bpy.ops.object.mode_set(mode="OBJECT")
    mod = ob.modifiers.new("Subdivision", "SUBSURF")
    mod.subdivision_type = "SIMPLE"
    mod.levels = 1
    mod.render_levels = 2
    mod.use_adaptive_subdivision = True
    return ob


def build_camera(ortho_scale, offset=(0.0, 0.0)):
    cam = bpy.data.cameras.new("Camera")
    cam.type = "ORTHO"
    cam.ortho_scale = ortho_scale
    cam.clip_end = 100.0
    ob = bpy.data.objects.new("Camera", cam)
    ob.location = (*offset, 5.0)
    bpy.context.collection.objects.link(ob)
    bpy.context.scene.camera = ob
    return ob


def declared_albedo(render_dir: Path, image: str) -> tuple[float, float, float, float]:
    """The linear RGBA this render directory says `image`'s mask is painted in.

    Only the sunlit half is wired: Cycles is meant to produce the shaded end from light, where the
    composite keys it to the producer's second colour. That substitution is what stopped a body's
    authored shadow hue reaching a raytraced pixel, and the seam keeps the other half recoverable.
    """
    sunlit, _shadowed = render_seam.paint_for(render_dir, image)
    return (*palette.srgb8_to_linear(sunlit), 1.0)


def build_sun(azimuth_delta_deg=0.0):
    sun = bpy.data.lights.new("Light", "SUN")
    sun.energy = RIG.sun_strength
    sun.angle = RIG.sun_angle
    ob = bpy.data.objects.new("Light", sun)
    ob.location = (4.076245, 1.005454, 5.903862)  # cosmetic; sun is a direction
    ob.rotation_euler = rotate_arrival(RIG.sun_rotation, azimuth_delta_deg)
    bpy.context.collection.objects.link(ob)
    return ob


def build_fill(azimuth_delta_deg=0.0):
    """THE FILL TURNS WITH THE KEY, never on its own. `cap_render.azimuth_delta` is added to both
    of the composite's azimuths, so a rig that moved only the key would be a different intervention
    from the one the raytraced arm has to reproduce."""
    sun = bpy.data.lights.new("Fill", "SUN")
    sun.energy = RIG.fill_strength
    sun.angle = RIG.fill_angle
    sun.use_shadow = False
    ob = bpy.data.objects.new("Fill", sun)
    ob.rotation_euler = rotate_arrival(RIG.fill_rotation, azimuth_delta_deg)
    bpy.context.collection.objects.link(ob)
    return ob


def build_world():
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = RIG.world_rgba
    bg.inputs["Strength"].default_value = RIG.world_strength
    bpy.context.scene.world = world


def load_image(render_dir, filename):
    img = bpy.data.images.load(str(render_dir / filename))
    img.colorspace_settings.name = RIG.image_colorspace
    return img


def make_ramp(nt, name, label, stops):
    ramp_node = nt.nodes.new("ShaderNodeValToRGB")
    ramp_node.name, ramp_node.label = name, label
    cr = ramp_node.color_ramp
    cr.interpolation = RIG.ramp_interpolation
    # bpy gotcha (API edition of "stops re-sort by position"): elements.new()
    # and position writes re-sort the collection and invalidate held element
    # references — colors then land on the wrong stops. Never hold refs across
    # mutations: shrink to one element, then append in ascending order,
    # coloring each element immediately via the ref .new() just returned.
    while len(cr.elements) > 1:
        cr.elements.remove(cr.elements[len(cr.elements) - 1])
    cr.elements[0].position, cr.elements[0].color = stops[0]
    for pos, rgba in stops[1:]:
        cr.elements.new(pos).color = rgba
    return ramp_node


def make_map_range(nt, name, label, from_range, to_range):
    map_range_node = nt.nodes.new("ShaderNodeMapRange")
    map_range_node.name, map_range_node.label = name, label
    map_range_node.data_type = "FLOAT"
    map_range_node.clamp = True
    map_range_node.inputs["From Min"].default_value = from_range[0]
    map_range_node.inputs["From Max"].default_value = from_range[1]
    map_range_node.inputs["To Min"].default_value = to_range[0]
    map_range_node.inputs["To Max"].default_value = to_range[1]
    return map_range_node


def make_mix(nt, name, label):
    mix_node = nt.nodes.new("ShaderNodeMix")
    mix_node.name, mix_node.label = name, label
    mix_node.data_type = "RGBA"
    mix_node.blend_type = "MIX"
    mix_node.clamp_factor = True
    return mix_node


def mix_socket(mix_node, sock):
    """A/B/Result sockets of a Mix node for its RGBA data type."""
    coll = mix_node.outputs if sock == "Result" else mix_node.inputs
    return next(socket for socket in coll
                if socket.name == sock and socket.type == "RGBA")


def make_float_mix(nt, name, label):
    """`make_mix`'s FLOAT twin, for mixing the displacement height toward sea level."""
    mix_node = nt.nodes.new("ShaderNodeMix")
    mix_node.name, mix_node.label = name, label
    mix_node.data_type = "FLOAT"
    mix_node.blend_type = "MIX"
    mix_node.clamp_factor = True
    return mix_node


def float_socket(mix_node, sock):
    """A/B/Result sockets of a Mix node for its FLOAT data type."""
    coll = mix_node.outputs if sock == "Result" else mix_node.inputs
    return next(socket for socket in coll
                if socket.name == sock and socket.type == "VALUE")


def build_material(ob, render_dir, displacement_scale, look, present):
    """`present` is the prep's own declaration of what it wrote, never a `Path.exists()` sweep.

    The two optional images are skipped by a prep that measured no snow or no lake bed in this
    region, and an absent file cannot tell that measurement from a prep that died before writing it.
    """
    mat = bpy.data.materials.new("Terrain")
    mat.use_nodes = True
    mat.displacement_method = "DISPLACEMENT"
    nt = mat.node_tree
    for node in list(nt.nodes):
        nt.nodes.remove(node)

    constants = look_constants(look)
    # The optional four, looked up unconditionally: a DECLARATION exists whether or not the raster
    # does, and only the node below is conditional on `present`.
    snow_spec = texture_for(render_seam.SNOWMASK)
    lake_depth_spec = texture_for(render_seam.LAKEDEPTH)
    ice_spec = texture_for(render_seam.SEAICE)
    rowscale_spec = texture_for(render_seam.ROWSCALE)
    # The two inland-water masks, looked up the same way, because they are no longer guaranteed:
    # a body whose seam declares no watermask has neither, and the mixes they drive are skipped.
    lake_spec = texture_for(render_seam.INLANDLAKE)
    river_spec = texture_for(render_seam.RIVER)

    tex = {}
    for name, spec in textures_for(look, present).items():
        tex[name] = make_texture(nt, render_dir, spec)

    disp = nt.nodes.new("ShaderNodeDisplacement")
    disp.name = "Displacement"
    disp.space = "OBJECT"
    disp.inputs["Midlevel"].default_value = RIG.displacement_midlevel
    # Live on the hero path and overridden on the block path, where the rowscale Math node below
    # drives this socket instead. Not a second owner of the constant despite appearing twice: a
    # linked socket ignores its default, so exactly one of the two reaches a pixel per render, and
    # a hero has no `rowscale.tif` to link from.
    disp.inputs["Scale"].default_value = displacement_scale

    # NAMED FOR WHAT THEY ARE, and the sea nodes stay interleaved with the land ones rather than
    # grouped. Both used to be frozen against a hand-built .blend compared by dump-diff; that
    # baseline is retired, so a node's name now answers to the reader and to the arm probes that
    # reach into the built graph, which is the only thing that ever addressed one by name.
    land_range = make_map_range(nt, "Land Range", "Land",
                                constants.land_range, (0.0, 1.0))
    sea_range = (None if constants.sea_range is None else
                 make_map_range(nt, "Sea Range", "Sea", constants.sea_range, (1.0, 0.0)))
    land_ramp = make_ramp(nt, "Land Ramp", "Land", constants.land_stops)
    sea_ramp = (None if constants.sea_stops is None else
                make_ramp(nt, "Sea Ramp", "Sea", constants.sea_stops))

    rgb = nt.nodes.new("ShaderNodeRGB")
    rgb.name = "Water Color"
    rgb.outputs[0].default_value = RIG.water_rgba

    # EACH MIX EXISTS ONLY WHERE ITS MASK DOES, which is the same rule the optional nodes below
    # follow.
    lake = make_mix(nt, "Lake Mix", "Lake") if lake_spec.filename in present else None
    river = make_mix(nt, "River Mix", "River") if river_spec.filename in present else None
    ocean = None if sea_ramp is None else make_mix(nt, "Ocean Mix", "Ocean")

    # optional data-driven snow/ice (render/snow_mask.py); layer not declared
    # -> graph identical to the pre-snow scene
    snow = None
    if render_seam.SNOWMASK in present:
        tex[snow_spec.name] = make_texture(nt, render_dir, snow_spec)
        snow = make_mix(nt, "Snow Mix", "Snow")
        mix_socket(snow, "B").default_value = declared_albedo(render_dir, render_seam.SNOWMASK)
        print(f"{render_seam.SNOWMASK} declared — wiring Snow mix", flush=True)

    # optional depth-keyed lake tint (render/lake_mask.py); raster absent ->
    # the Lake mix keeps the flat RGB node, the pre-lake-depth graph exactly.
    # The raster stores the log1p ramp POSITION (0..1), not metres, and
    # LAKE_STOPS[0] IS the flat water tint, so a lake without depth data
    # degrades to today's colour with no selector logic. Rivers stay flat by
    # decision (no global bed data) — the River mix keeps the RGB node. Depth
    # is tint-only and must NEVER reach displacement (at 15x exaggeration a
    # carved bed makes Namtso a 1.5 km crater).
    lake_ramp = None
    if render_seam.LAKEDEPTH in present:
        tex[lake_depth_spec.name] = make_texture(nt, render_dir, lake_depth_spec)
        lake_ramp = make_ramp(nt, "Lake Ramp", "Lake Bed", RIG.lake_stops)
        print(f"{render_seam.LAKEDEPTH} declared — wiring depth-keyed Lake ramp", flush=True)

    # optional sea ice (block prep only today): ONE continuous ocean-gated alpha drives BOTH
    # arms — an ice-white mix over the finished sea colour, and the displacement pulled toward
    # sea level, which is what a floating sheet is. The ramps keep reading the RAW heightfield
    # on purpose: damping the branch that feeds them would read 0 m under pack and collapse
    # abyssal colour to shelf colour, deleting the see-through the alpha's ceiling exists for.
    ice = None
    ice_flatten = None
    if render_seam.SEAICE in present:
        tex[ice_spec.name] = make_texture(nt, render_dir, ice_spec)
        ice = make_mix(nt, "Ice Mix", "Ice")
        mix_socket(ice, "B").default_value = declared_albedo(render_dir, render_seam.SEAICE)
        ice_flatten = make_float_mix(nt, "Ice Flatten", "Ice Flatten")
        float_socket(ice_flatten, "B").default_value = 0.0  # sea level
        print(f"{render_seam.SEAICE} declared — wiring Ice mix + displacement damp", flush=True)

    # THE DRIVEN SOCKET IS SCALE AND NOT HEIGHT, for two reasons that outlast today's constants.
    # `disp = (Height - Midlevel) * Scale`, so multiplying Scale is right at any midlevel where
    # multiplying Height is right only while `DISPLACEMENT_MIDLEVEL` is 0.0; and it leaves the
    # Height chain alone, so the sea-ice damp above and the ramps' raw metres both need no thought.
    rowscale = None
    if render_seam.ROWSCALE in present:
        tex[rowscale_spec.name] = make_texture(nt, render_dir, rowscale_spec)
        rowscale = nt.nodes.new("ShaderNodeMath")
        rowscale.name = "Row Scale Multiply"
        rowscale.operation = "MULTIPLY"
        rowscale.use_clamp = False  # the correction leaves 1.0 in both directions
        rowscale.inputs[1].default_value = displacement_scale
        print(f"{render_seam.ROWSCALE} declared — wiring per-row displacement scale", flush=True)

    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.inputs["Roughness"].default_value = 1.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.name = "Material Output"

    link = nt.links.new
    if rowscale is not None:
        link(tex[rowscale_spec.name].outputs["Color"], rowscale.inputs[0])
        link(rowscale.outputs["Value"], disp.inputs["Scale"])
    hf = tex[texture_for(render_seam.HEIGHTFIELD).name]
    if ice_flatten is not None:
        link(hf.outputs["Color"], float_socket(ice_flatten, "A"))
        link(tex[ice_spec.name].outputs["Color"], ice_flatten.inputs["Factor"])
        link(float_socket(ice_flatten, "Result"), disp.inputs["Height"])
    else:
        link(hf.outputs["Color"], disp.inputs["Height"])
    link(disp.outputs["Displacement"], out.inputs["Displacement"])
    link(hf.outputs["Color"], land_range.inputs["Value"])
    link(land_range.outputs["Result"], land_ramp.inputs["Factor"])
    if sea_range is not None and sea_ramp is not None:
        link(hf.outputs["Color"], sea_range.inputs["Value"])
        link(sea_range.outputs["Result"], sea_ramp.inputs["Factor"])
    land_color = land_ramp.outputs["Color"]
    if snow is not None:
        link(land_color, mix_socket(snow, "A"))
        link(tex[snow_spec.name].outputs["Color"], snow.inputs[0])
        land_color = mix_socket(snow, "Result")
    # THE CHAIN IS THREADED RATHER THAN FIXED, so a body with no inland water hands the land colour
    # straight to the sea branch instead of through two mixes it has no masks to drive.
    surface_color = land_color
    if lake is not None:
        link(surface_color, mix_socket(lake, "A"))
        link(tex[lake_spec.name].outputs["Color"], lake.inputs[0])
        if lake_ramp is not None:
            link(tex[lake_depth_spec.name].outputs["Color"], lake_ramp.inputs["Factor"])
            link(lake_ramp.outputs["Color"], mix_socket(lake, "B"))
        else:
            link(rgb.outputs["Color"], mix_socket(lake, "B"))
        surface_color = mix_socket(lake, "Result")
    if river is not None:
        link(surface_color, mix_socket(river, "A"))
        link(tex[river_spec.name].outputs["Color"], river.inputs[0])
        link(rgb.outputs["Color"], mix_socket(river, "B"))
        surface_color = mix_socket(river, "Result")
    if ocean is not None and sea_ramp is not None:
        link(surface_color, mix_socket(ocean, "A"))
        link(sea_ramp.outputs["Color"], mix_socket(ocean, "B"))
        link(tex[SEA_IMAGE].outputs["Color"], ocean.inputs[0])
        surface_color = mix_socket(ocean, "Result")
    if ice is not None:
        link(surface_color, mix_socket(ice, "A"))
        link(tex[ice_spec.name].outputs["Color"], ice.inputs[0])
        surface_color = mix_socket(ice, "Result")
    link(surface_color, bsdf.inputs["Base Color"])
    link(bsdf.outputs["BSDF"], out.inputs["Surface"])

    ob.data.materials.append(mat)


def configure_render(res_x, res_y, *, denoise_device):
    """Cycles settings for one frame. `denoise_device` is the caller's, and deliberately so.

    OIDN ON THE GPU IS ROUGHLY EIGHT TIMES FASTER AND THE HEROES STILL MUST NOT USE IT. Render and
    denoise then contend for the same 12 GB and the driver throws an Xid 31 MMU fault, which is what
    CLAUDE.md's rule is about; measured, a block frame denoises in 0.85 s on the GPU against 5.93 s
    on the CPU, and a hero is several times a block.

    IT CANNOT BE DERIVED FROM `res_x`/`res_y`, which is the obvious idea and does not survive the
    numbers: the two populations OVERLAP. Maldives is 13.8 Mpx and Chile 18.1 against a 4096 block's
    18.9, so no threshold separates "block" from "hero" -- one placed above the block flips two
    heroes into an untested regime, one placed below it puts the blocks back on the CPU. A threshold
    would also encode THIS machine's 12 GB as though it were a fact about the project, and a rule
    that reads the device at render time makes the output depend on the host with nothing on disk
    saying which way it went. A recipe can record a value; it cannot record a rule.

    So the caller decides and records what it decided. The default is the conservative one, because
    the default is what a future caller at an unknown frame size inherits.
    """
    if denoise_device not in ("cpu", "gpu"):
        raise ValueError(f"denoise_device must be 'cpu' or 'gpu', not {denoise_device!r}")
    scene = bpy.context.scene
    render_settings, cycles_settings = scene.render, scene.cycles
    render_settings.engine = "CYCLES"
    render_settings.resolution_x, render_settings.resolution_y = res_x, res_y
    render_settings.image_settings.file_format = "PNG"
    render_settings.image_settings.color_mode = "RGBA"
    cycles_settings.device = "GPU"
    cycles_settings.samples = RIG.samples
    cycles_settings.use_adaptive_sampling = True
    cycles_settings.adaptive_threshold = RIG.adaptive_threshold
    cycles_settings.use_denoising = True
    cycles_settings.denoiser = "OPENIMAGEDENOISE"
    cycles_settings.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    cycles_settings.denoising_prefilter = "ACCURATE"
    cycles_settings.denoising_quality = "HIGH"
    cycles_settings.denoising_use_gpu = denoise_device == "gpu"
    cycles_settings.dicing_rate = RIG.dicing_rate
    cycles_settings.max_subdivisions = RIG.max_subdivisions
    cycles_settings.offscreen_dicing_scale = RIG.offscreen_dicing_scale
    for attr, val in RIG.bounces.items():
        setattr(cycles_settings, attr, val)
    cycles_settings.sample_clamp_indirect = RIG.clamp_indirect
    scene.view_settings.view_transform = RIG.view_transform


def build_parser():
    """The CLI, separated from `main` so its DEFAULTS can be asserted without Blender.

    FOUR OF THESE DEFAULTS ARE LOAD-BEARING AND THEY FAIL THE SAME WAY: `--denoise-device`,
    `--base-grid`, `--sun-azimuth-delta` and `--tile` each describe a regime one caller opts into
    and the other must not. Together they are the whole mechanism protecting 203 pinned hero
    renders from settings measured on blocks and caps, and a default nothing can reach is a default
    nothing can pin.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", required=True, choices=sorted(palette.LOOK_BY_BODY),
                    help="which planet's ramps to draw with; no default, because a body that "
                         "quietly inherited Earth's would render a plausible wrong planet")
    ap.add_argument("--render-dir", type=Path, required=True)
    ap.add_argument("--denoise-device", choices=("cpu", "gpu"), default="cpu",
                    help="where OpenImageDenoise runs. Defaults to cpu because that is what an "
                         "unknown frame size should inherit: at hero sizes render and denoise "
                         "contend for the same VRAM and the driver faults. The block runner opts "
                         "in explicitly and records that it did")
    ap.add_argument("--base-grid", choices=("single", "fitted"), default="single",
                    help="how many quads the plane starts as. 'fitted' derives the count from the "
                         "frame so adaptive subdivision can reach one micropolygon per pixel; "
                         "'single' is the historical bare quad, which under-dices any plane wider "
                         "than 4096 px. Defaults to single because that is the only one that is "
                         "known to RENDER at hero sizes -- see `base_patches` for the VRAM "
                         "ceiling. The block runner opts in explicitly and records that it did")
    ap.add_argument("--sun-azimuth-delta", type=float, default=0.0, metavar="DEG",
                    help="turn the WHOLE lighting rig this many degrees clockwise in arrival "
                         "bearing. Defaults to 0, which is the rig every hero and every block "
                         "renders under; the cap's raytraced arm renders a ring of these because "
                         "Cycles takes one sun direction per frame where the composite turns its "
                         "light per pixel")
    ap.add_argument("--tile", type=tile_index, default=None, metavar="ROW,COL",
                    help="photograph one tile of the plane instead of the whole frame, by moving "
                         "the ortho camera. The grid is derived from the frame's own camera "
                         "fraction. Defaults to none: a plane small enough to render whole should "
                         "render whole, and a tiled hero would ship a quarter of a country")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--frame-json", type=Path, default=None,
                    help="per-country numbers from render_prep.py; "
                         "default <render-dir>/frame.json")
    ap.add_argument("--render", type=Path, default=None,
                    help="after saving the .blend, render a still to this PNG")
    ap.add_argument("--render-scale", type=int, default=100,
                    help="resolution_percentage for the --render still; the "
                         "saved .blend always keeps 100 (Phase 0's 2048-wide "
                         "test convention ~= 27)")
    return ap


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = build_parser().parse_args(argv)
    render_dir = args.render_dir.resolve()
    look = palette.look_for(args.body)

    frame_path = args.frame_json or render_dir / "frame.json"
    if not frame_path.exists():
        sys.exit(f"{frame_path} not found — render_prep.py emits it")
    frame = json.loads(frame_path.read_text())
    # The executable copy of a fact that lives in two places. Refusing an absent `body` rather than
    # assuming Earth is the same refusal as the flag having no default: a frame written before
    # render_prep recorded one needs backfilling, and guessing would draw a plausible wrong planet.
    if "body" not in frame:
        sys.exit(f"{frame_path} records no body — render_prep writes one, so this frame predates "
                 f"that and needs backfilling rather than assuming {args.body!r}")
    if frame["body"] != args.body:
        sys.exit(f"--body {args.body} but {frame_path} was written for {frame['body']!r}; one of "
                 f"the two is wrong and the render would be plausible either way")

    clear_scene()
    configure_render(frame["res_x"], frame["res_y"], denoise_device=args.denoise_device)
    # ECHOED SO A CALLER CAN ASSERT IT. A flag that failed to arrive would otherwise render on the
    # CPU while the caller's recipe records "gpu", which is the producer-declares rule inverted into
    # a lie: the block would be correct, slow, and permanently mislabelled.
    print(f"DENOISE_DEVICE {args.denoise_device}", flush=True)
    build_world()
    offset = ((0.0, 0.0) if args.tile is None
              else tile_camera_location(frame["ortho_scale"], frame["plane_height_units"],
                                        args.tile))
    build_camera(frame["ortho_scale"], offset)
    sun = build_sun(args.sun_azimuth_delta)
    fill = build_fill(args.sun_azimuth_delta)
    # ECHOED SO A CALLER CAN ASSERT THEM, for `--denoise-device`'s reason and harder. A dropped
    # `--sun-azimuth-delta` renders a frame lit from the base bearing, a dropped `--tile`
    # photographs the whole plane at a quadrant's resolution: both succeed, both look like a
    # rendered cap, and neither leaves anything on disk that differs from the frame that was asked
    # for. The BEARINGS are read back off the built objects rather than recomputed, so what is
    # reported is what Blender stored.
    print(f"SUN_AZIMUTH_DELTA {args.sun_azimuth_delta:.4f} main arrives from "
          f"{arrival_azimuth_deg(tuple(sun.rotation_euler)):.2f} "
          f"fill from {arrival_azimuth_deg(tuple(fill.rotation_euler)):.2f}", flush=True)
    tile = "none" if args.tile is None else f"{args.tile[0]},{args.tile[1]}"
    print(f"TILE {tile} camera at {offset[0]:+.6f},{offset[1]:+.6f}", flush=True)

    probe = load_image(render_dir, texture_for(render_seam.HEIGHTFIELD).filename)
    if tuple(probe.size) != (frame["width_px"], frame["height_px"]):
        sys.exit(f"heightfield is {tuple(probe.size)} px but frame.json says "
                 f"({frame['width_px']}, {frame['height_px']}) — stale or "
                 f"mismatched frame.json")
    bpy.data.images.remove(probe)
    span_px = plane_span_px(frame)
    patches = base_patches(span_px) if args.base_grid == "fitted" else 1
    plane = build_plane(frame["plane_height_units"], patches)
    build_material(plane, render_dir, frame["displacement_scale"], look,
                   render_seam.declared(render_dir))

    prefs = bpy.context.preferences.addons["cycles"].preferences
    print(f"body {args.body}, {'sea' if look.sea is not None else 'no sea'}; ", flush=True)
    # ECHOED SO A CALLER CAN ASSERT IT, for `--denoise-device`'s reason: a base grid that failed to
    # be cut renders successfully, a little soft, and leaves nothing on disk that differs. The
    # POLICY rides with the count because they fail independently -- `fitted` on a plane under the
    # cap yields 1, which is indistinguishable from the flag never arriving.
    print(f"BASE_GRID {args.base_grid} BASE_PATCHES {patches} SPAN_PX {span_px:.0f}", flush=True)
    print(f"plane 2.0 x {frame['plane_height_units']:.6f}; "
          f"ortho {frame['ortho_scale']:.6f}; "
          f"displacement {frame['displacement_scale']:.6e}; "
          f"res {frame['res_x']} x {frame['res_y']}; compute device "
          f"{getattr(prefs, 'compute_device_type', '?')}", flush=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out.resolve()),
                                relative_remap=True)
    print(f"saved {args.out}", flush=True)

    if args.render:
        bpy.context.scene.render.resolution_percentage = args.render_scale
        bpy.context.scene.render.filepath = str(args.render.resolve())
        bpy.ops.render.render(write_still=True)
        print(f"rendered {args.render} @ {args.render_scale}%", flush=True)


if __name__ == "__main__":
    main()
