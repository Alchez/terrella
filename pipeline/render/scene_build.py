"""Build one relief scene from code: a country's hero, or one block of a planet.

THIS IS THE SHARED RIG AND NOT THE HERO RIG. Two callers stage a render
directory and shell into this exact file: `render_prep.py` for a country in
its own Albers projection, and the block prep for a z8 EPSG:3857 block,
which writes its cuts under the same filenames purely to satisfy the
table below. Nothing here is country-shaped.

Reconstructs the hand-built Phase 0 scene — plane + adaptive-subdivision
displacement, a land ramp with lake/river switches over an optional sea ramp
(plus a snow switch iff snowmask.png exists in the render dir, and a
depth-keyed lake ramp iff lakedepth.tif does), sun plus a shadowless
fill sun, ortho camera, locked render settings — entirely from the constants
below. Verified against the hand-built .blend by structural dump-diff and a
pixel-diff of test renders

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
    rx, _, rz = rotation
    # Travel direction is Rz @ Ry @ Rx applied to (0, 0, -1), giving a source direction whose
    # horizontal part is sin(rx) * (sin rz, -cos rz). For any sun above the horizon sin(rx) is
    # positive and divides out, so the bearing is the z euler's alone — but only then, which is why
    # the tilt is asserted rather than assumed away.
    if math.sin(rx) <= 0.0:
        raise ValueError(f"a sun tilted {math.degrees(rx):.1f} degrees is at or below the horizon, "
                         f"where it has no arrival bearing to report")
    return math.degrees(math.atan2(math.sin(rz), -math.cos(rz))) % 360.0


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
    byte-identically. It rides along because the table is recorded whole, and that is the one key
    here whose change costs a re-render it does not need.

    `optional` is the raster's presence, never a look: an optional node is built iff its file was
    declared, which is how a body that draws no sea ice simply has no ice node.
    """

    name: str
    filename: str
    interpolation: str
    extension: str
    optional: bool


#: Every image node the rig can build, in creation order. THE ORDER IS LOAD-BEARING: the dump-diff
#: against the hand-built .blend sees creation order, so the mandatory four are built by one loop
#: in this sequence and the optional four at their own sites, where their mixes and ramps are wired.
TEXTURES = {
    spec.name: spec for spec in (
        TextureSpec("Image Texture", render_seam.HEIGHTFIELD, "Linear", "REPEAT", optional=False),
        TextureSpec("Image Texture.001", render_seam.OCEANMASK, "Closest", "REPEAT", optional=False),
        TextureSpec("Image Texture.002", render_seam.INLANDLAKE, "Closest", "REPEAT", optional=False),
        TextureSpec("Image Texture.003", render_seam.RIVER, "Closest", "REPEAT", optional=False),
        # Closest because snow is a hard-edged mask; the softening it ships with is baked into the
        # raster by `snow.soften_source_cells`, never asked of the sampler.
        TextureSpec("Image Texture.004", render_seam.SNOWMASK, "Closest", "REPEAT", optional=True),
        # Linear on both of these: a continuous field, like the heightfield.
        TextureSpec("Image Texture.005", render_seam.LAKEDEPTH, "Linear", "REPEAT", optional=True),
        TextureSpec("Image Texture.006", render_seam.SEAICE, "Linear", "REPEAT", optional=True),
        # The rowscale column is one texel wide, so there is nothing to interpolate across u, and
        # EXTEND rather than REPEAT is what stops one pole's row wrapping into the other's.
        TextureSpec("Image Texture.007", render_seam.ROWSCALE, "Closest", "EXTEND", optional=True),
    )
}

#: The one texture a look can decline, being the sea branch's own input.
SEA_IMAGE = "Image Texture.001"


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

    THE ENUMERATION LIVES WITH THE CONSTANTS, which is the whole point of it being here rather than
    in the runner that serialises it. A freshness recipe is a list of things that reach a pixel, and
    a list kept anywhere but beside them is a second copy that goes quietly short: the constant gets
    added, the recipe does not, and the output that was rendered with the old value keeps reading as
    current forever. `test_scene_build_sync` closes that by scanning this module's own capitals and
    requiring every one of them to appear below, so forgetting is a red test rather than a silent
    stale planet.

    KEYED BY CONSTANT NAME AND NOT BY CONCEPT, for the same reason: a key like "sun" cannot be
    checked against anything, where `SUN_STRENGTH` can be checked against the module.

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
        "textures": {name: dataclasses.asdict(spec) for name, spec in TEXTURES.items()},
        "sea_texture": None if look.sea is None else SEA_IMAGE,
        "look": {
            "land_range": list(constants.land_range),
            "land_stops": [[position, list(rgba)] for position, rgba in constants.land_stops],
            "sea_range": None if constants.sea_range is None else list(constants.sea_range),
            "sea_stops": None if constants.sea_stops is None else
            [[position, list(rgba)] for position, rgba in constants.sea_stops],
        },
    }


def textures_for(look: palette.Look) -> dict[str, TextureSpec]:
    """The textures built unconditionally for this look: the mandatory four, bar the oceanmask for
    a sea-less body.

    THE OPTIONAL ONES ARE NOT HERE because they are built at their own sites, beside the mixes and
    ramps they feed, and the dump-diff against the hand-built .blend sees creation order.

    A DECLARATION DECIDES THIS AND NEVER `Path.exists()`. Snow and lake depth are sniffed below and
    survive it because a missing mask degrades to a defined colour; a missing oceanmask cannot tell
    "this planet has no sea" from "prep crashed", and guessing the first renders a planet of land.

    THE OCEANMASK IS THE ONLY ONE A LOOK CAN ANSWER FOR, because it selects between this look's two
    ramps. The lake and river masks stay mandatory: whether a planet has inland water is its planet
    seam's `watermask` declaration, not a colour, and absent one the image load fails loudly rather
    than drawing anything. Giving the rig that declaration to read is unit 4's block sidecar.
    """
    return {name: spec for name, spec in TEXTURES.items()
            if not spec.optional and (look.sea is not None or name != SEA_IMAGE)}


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
    return max(2.0, frame["plane_height_units"]) * pixels_per_unit


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
    bpy.ops.mesh.primitive_plane_add(size=2.0)
    ob = bpy.context.active_object
    ob.name = "Plane"
    for vertex in ob.data.vertices:
        vertex.co.y *= height / 2.0
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


def build_camera(ortho_scale):
    cam = bpy.data.cameras.new("Camera")
    cam.type = "ORTHO"
    cam.ortho_scale = ortho_scale
    cam.clip_end = 100.0
    ob = bpy.data.objects.new("Camera", cam)
    ob.location = (0.0, 0.0, 5.0)
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


def build_sun():
    sun = bpy.data.lights.new("Light", "SUN")
    sun.energy = RIG.sun_strength
    sun.angle = RIG.sun_angle
    ob = bpy.data.objects.new("Light", sun)
    ob.location = (4.076245, 1.005454, 5.903862)  # cosmetic; sun is a direction
    ob.rotation_euler = RIG.sun_rotation
    bpy.context.collection.objects.link(ob)
    return ob


def build_fill():
    sun = bpy.data.lights.new("Fill", "SUN")
    sun.energy = RIG.fill_strength
    sun.angle = RIG.fill_angle
    sun.use_shadow = False
    ob = bpy.data.objects.new("Fill", sun)
    ob.rotation_euler = RIG.fill_rotation
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
    mat = bpy.data.materials.new("Material.001")
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

    tex = {}
    for name, spec in textures_for(look).items():
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

    # The sea nodes stay interleaved rather than grouped, and the `.00N` names stay frozen: the
    # rig's only baseline is a hand-built .blend compared by dump-diff, which sees both.
    land_range = make_map_range(nt, "Map Range", "Land",
                                constants.land_range, (0.0, 1.0))
    sea_range = (None if constants.sea_range is None else
                 make_map_range(nt, "Map Range.001", "Sea", constants.sea_range, (1.0, 0.0)))
    land_ramp = make_ramp(nt, "Color Ramp.001", "", constants.land_stops)
    sea_ramp = (None if constants.sea_stops is None else
                make_ramp(nt, "Color Ramp", "", constants.sea_stops))

    rgb = nt.nodes.new("ShaderNodeRGB")
    rgb.name = "Color"
    rgb.outputs[0].default_value = RIG.water_rgba

    lake = make_mix(nt, "Mix.001", "Lake")
    river = make_mix(nt, "Mix.002", "River")
    ocean = None if sea_ramp is None else make_mix(nt, "Mix", "")

    # optional data-driven snow/ice (render/snow_mask.py); layer not declared
    # -> graph identical to the pre-snow scene
    snow = None
    if render_seam.SNOWMASK in present:
        tex[snow_spec.name] = make_texture(nt, render_dir, snow_spec)
        snow = make_mix(nt, "Mix.003", "Snow")
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
        lake_ramp = make_ramp(nt, "Color Ramp.002", "", RIG.lake_stops)
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
        ice = make_mix(nt, "Mix.004", "Ice")
        mix_socket(ice, "B").default_value = declared_albedo(render_dir, render_seam.SEAICE)
        ice_flatten = make_float_mix(nt, "Mix.005", "Ice Flatten")
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
        rowscale.name = "Math"
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
    hf = tex["Image Texture"]
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
    link(land_color, mix_socket(lake, "A"))
    link(tex["Image Texture.002"].outputs["Color"], lake.inputs[0])
    if lake_ramp is not None:
        link(tex[lake_depth_spec.name].outputs["Color"], lake_ramp.inputs["Factor"])
        link(lake_ramp.outputs["Color"], mix_socket(lake, "B"))
    else:
        link(rgb.outputs["Color"], mix_socket(lake, "B"))
    link(mix_socket(lake, "Result"), mix_socket(river, "A"))
    link(tex["Image Texture.003"].outputs["Color"], river.inputs[0])
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

    Only one of them is load-bearing and it is `--denoise-device`: that default is the whole
    mechanism protecting 203 pinned hero renders from a setting measured only on blocks, and a
    default nothing can reach is a default nothing can pin.
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
    build_camera(frame["ortho_scale"])
    build_sun()
    build_fill()

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
