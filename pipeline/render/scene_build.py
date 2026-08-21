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
DISPLACEMENT_MIDLEVEL = 0.0
SUN_ROTATION = (math.radians(90.0 - palette.SUN_ALT_DEG), 0.0, math.radians(-135.0))
SUN_ANGLE = math.radians(12.0)
SUN_STRENGTH = 3.0
FILL_ROTATION = (math.radians(30.0), 0.0, math.radians(45.0))
FILL_ANGLE = math.radians(10.0)
FILL_STRENGTH = 0.45   # 15% of SUN_STRENGTH; shadowless SE fill so shadowed
                       # faces keep directional modeling (never pure black).
                       # The comment said SE while the light arrived from NE;
                       # putting the main sun on 315 put this on 135 and made
                       # it true. `arrival_azimuth_deg` is what says so.
WORLD_RGBA = (0.887923, 0.799103, 0.665388, 1.0)   # F2E7D5
WORLD_STRENGTH = 0.3
WATER_RGBA = (*palette.srgb8_to_linear(palette.WATER_RGB), 1.0)  # 8EC6C4 — sea
                       # surface +7%, pinned relationally (the 98C5C8 drift's cure)
SNOW_RGBA = (*palette.srgb8_to_linear(palette.SNOW_RGB), 1.0)    # E8F1F6
ICE_RGBA = (*palette.srgb8_to_linear(palette.ICE_RGB), 1.0)      # D4E4F0 — sea ice; a single
                       # albedo where the composite keys a (sunlit, shadowed) pair, because
                       # Cycles lights the sheet itself and the pair's shadowed half was the
                       # fake light key's job (seaice.ice_white)

LAKE_STOPS = _rgba(palette.LAKE_STOPS)   # depth-position ramp; stop 0 IS the water tint
RAMP_INTERPOLATION = "EASE"

SAMPLES = 4096        # a Cycles SAMPLE COUNT, and the one number here measured in the same units
                      # as a block edge without being one. Never search-and-replace it.
ADAPTIVE_THRESHOLD = 0.01
DICING_RATE = 1.0
MAX_SUBDIVISIONS = 12   # per PATCH, not per mesh — `base_patches` holds what that means
OFFSCREEN_DICING_SCALE = 16.0
                      # How much coarser geometry outside the camera is diced. It exists for the
                      # block path, whose plane carries terrain far past the traced rectangle so
                      # that off-block ridges cast shadows in; at Earth's widest that plane is
                      # 7,808 px against a 4,352 px frame, so most of the mesh is never seen.
                      # PINNED BECAUSE IT WAS AN UNRECORDED BLENDER DEFAULT, not because it is a
                      # quality lever: 4, 16 and 64 sit within 0.06 DN mean of each other on the
                      # same block, against 37.58 DN for the control that deletes the context
                      # outright. 16 over the default 4 for memory rather than for pixels.
BOUNCES = dict(max_bounces=12, diffuse_bounces=4, glossy_bounces=4,
               transmission_bounces=12, volume_bounces=0)
CLAMP_INDIRECT = 10.0

IMAGES = {  # node name -> (filename, interpolation)
    "Image Texture": (render_seam.HEIGHTFIELD, "Linear"),
    "Image Texture.001": (render_seam.OCEANMASK, "Closest"),
    "Image Texture.002": (render_seam.INLANDLAKE, "Closest"),
    "Image Texture.003": (render_seam.RIVER, "Closest"),
}

#: The one entry in `IMAGES` a look can decline, being the sea branch's own input.
SEA_IMAGE = "Image Texture.001"


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
        "DISPLACEMENT_MIDLEVEL": DISPLACEMENT_MIDLEVEL,
        "SUN_ROTATION": list(SUN_ROTATION),
        "SUN_ANGLE": SUN_ANGLE,
        "SUN_STRENGTH": SUN_STRENGTH,
        "FILL_ROTATION": list(FILL_ROTATION),
        "FILL_ANGLE": FILL_ANGLE,
        "FILL_STRENGTH": FILL_STRENGTH,
        "WORLD_RGBA": list(WORLD_RGBA),
        "WORLD_STRENGTH": WORLD_STRENGTH,
        "WATER_RGBA": list(WATER_RGBA),
        "SNOW_RGBA": list(SNOW_RGBA),
        "ICE_RGBA": list(ICE_RGBA),
        "LAKE_STOPS": [[position, list(rgba)] for position, rgba in LAKE_STOPS],
        "RAMP_INTERPOLATION": RAMP_INTERPOLATION,
        "SAMPLES": SAMPLES,
        "ADAPTIVE_THRESHOLD": ADAPTIVE_THRESHOLD,
        "DICING_RATE": DICING_RATE,
        "MAX_SUBDIVISIONS": MAX_SUBDIVISIONS,
        "OFFSCREEN_DICING_SCALE": OFFSCREEN_DICING_SCALE,
        "BOUNCES": dict(BOUNCES),
        "CLAMP_INDIRECT": CLAMP_INDIRECT,
        # The interpolation beside each filename is as much a look decision as a colour is: an
        # oceanmask read Linear instead of Closest feathers every coastline.
        "IMAGES": {name: list(spec) for name, spec in images_for(look).items()},
        "SEA_IMAGE": SEA_IMAGE,
        "look": {
            "land_range": list(constants.land_range),
            "land_stops": [[position, list(rgba)] for position, rgba in constants.land_stops],
            "sea_range": None if constants.sea_range is None else list(constants.sea_range),
            "sea_stops": None if constants.sea_stops is None else
            [[position, list(rgba)] for position, rgba in constants.sea_stops],
        },
    }


def images_for(look: palette.Look) -> dict[str, tuple[str, str]]:
    """The images this look's graph loads: all of `IMAGES` bar the oceanmask, for a sea-less body.

    A DECLARATION DECIDES THIS AND NEVER `Path.exists()`. Snow and lake depth are sniffed below and
    survive it because a missing mask degrades to a defined colour; a missing oceanmask cannot tell
    "this planet has no sea" from "prep crashed", and guessing the first renders a planet of land.

    THE OCEANMASK IS THE ONLY ONE A LOOK CAN ANSWER FOR, because it selects between this look's two
    ramps. The lake and river masks stay mandatory: whether a planet has inland water is its planet
    seam's `watermask` declaration, not a colour, and absent one the image load fails loudly rather
    than drawing anything. Giving the rig that declaration to read is unit 4's block sidecar.
    """
    return {name: spec for name, spec in IMAGES.items()
            if look.sea is not None or name != SEA_IMAGE}


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
    """
    return max(1, math.ceil(span_px / 2 ** MAX_SUBDIVISIONS))


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


def build_sun():
    sun = bpy.data.lights.new("Light", "SUN")
    sun.energy = SUN_STRENGTH
    sun.angle = SUN_ANGLE
    ob = bpy.data.objects.new("Light", sun)
    ob.location = (4.076245, 1.005454, 5.903862)  # cosmetic; sun is a direction
    ob.rotation_euler = SUN_ROTATION
    bpy.context.collection.objects.link(ob)
    return ob


def build_fill():
    sun = bpy.data.lights.new("Fill", "SUN")
    sun.energy = FILL_STRENGTH
    sun.angle = FILL_ANGLE
    sun.use_shadow = False
    ob = bpy.data.objects.new("Fill", sun)
    ob.rotation_euler = FILL_ROTATION
    bpy.context.collection.objects.link(ob)
    return ob


def build_world():
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = WORLD_RGBA
    bg.inputs["Strength"].default_value = WORLD_STRENGTH
    bpy.context.scene.world = world


def load_image(render_dir, filename):
    img = bpy.data.images.load(str(render_dir / filename))
    img.colorspace_settings.name = "Non-Color"
    return img


def make_ramp(nt, name, label, stops):
    ramp_node = nt.nodes.new("ShaderNodeValToRGB")
    ramp_node.name, ramp_node.label = name, label
    cr = ramp_node.color_ramp
    cr.interpolation = RAMP_INTERPOLATION
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
    tex = {}
    for name, (filename, interp) in images_for(look).items():
        image_node = nt.nodes.new("ShaderNodeTexImage")
        image_node.name = name
        image_node.image = load_image(render_dir, filename)
        image_node.interpolation = interp
        image_node.extension = "REPEAT"
        tex[name] = image_node

    disp = nt.nodes.new("ShaderNodeDisplacement")
    disp.name = "Displacement"
    disp.space = "OBJECT"
    disp.inputs["Midlevel"].default_value = DISPLACEMENT_MIDLEVEL
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
    rgb.outputs[0].default_value = WATER_RGBA

    lake = make_mix(nt, "Mix.001", "Lake")
    river = make_mix(nt, "Mix.002", "River")
    ocean = None if sea_ramp is None else make_mix(nt, "Mix", "")

    # optional data-driven snow/ice (render/snow_mask.py); layer not declared
    # -> graph identical to the pre-snow scene
    snow = None
    if render_seam.SNOWMASK in present:
        snow_image_node = nt.nodes.new("ShaderNodeTexImage")
        snow_image_node.name = "Image Texture.004"
        snow_image_node.image = load_image(render_dir, render_seam.SNOWMASK)
        snow_image_node.interpolation = "Closest"
        snow_image_node.extension = "REPEAT"
        tex["Image Texture.004"] = snow_image_node
        snow = make_mix(nt, "Mix.003", "Snow")
        mix_socket(snow, "B").default_value = SNOW_RGBA
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
        lake_depth_node = nt.nodes.new("ShaderNodeTexImage")
        lake_depth_node.name = "Image Texture.005"
        lake_depth_node.image = load_image(render_dir, render_seam.LAKEDEPTH)
        lake_depth_node.interpolation = "Linear"  # continuous field, like the heightfield
        lake_depth_node.extension = "REPEAT"
        tex["Image Texture.005"] = lake_depth_node
        lake_ramp = make_ramp(nt, "Color Ramp.002", "", LAKE_STOPS)
        print(f"{render_seam.LAKEDEPTH} declared — wiring depth-keyed Lake ramp", flush=True)

    # optional sea ice (block prep only today): ONE continuous ocean-gated alpha drives BOTH
    # arms — an ice-white mix over the finished sea colour, and the displacement pulled toward
    # sea level, which is what a floating sheet is. The ramps keep reading the RAW heightfield
    # on purpose: damping the branch that feeds them would read 0 m under pack and collapse
    # abyssal colour to shelf colour, deleting the see-through the alpha's ceiling exists for.
    ice = None
    ice_flatten = None
    if render_seam.SEAICE in present:
        ice_image_node = nt.nodes.new("ShaderNodeTexImage")
        ice_image_node.name = "Image Texture.006"
        ice_image_node.image = load_image(render_dir, render_seam.SEAICE)
        ice_image_node.interpolation = "Linear"  # continuous alpha, like the heightfield
        ice_image_node.extension = "REPEAT"
        tex["Image Texture.006"] = ice_image_node
        ice = make_mix(nt, "Mix.004", "Ice")
        mix_socket(ice, "B").default_value = ICE_RGBA
        ice_flatten = make_float_mix(nt, "Mix.005", "Ice Flatten")
        float_socket(ice_flatten, "B").default_value = 0.0  # sea level
        print(f"{render_seam.SEAICE} declared — wiring Ice mix + displacement damp", flush=True)

    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.inputs["Roughness"].default_value = 1.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.name = "Material Output"

    link = nt.links.new
    hf = tex["Image Texture"]
    if ice_flatten is not None:
        link(hf.outputs["Color"], float_socket(ice_flatten, "A"))
        link(tex["Image Texture.006"].outputs["Color"], ice_flatten.inputs["Factor"])
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
        link(tex["Image Texture.004"].outputs["Color"], snow.inputs[0])
        land_color = mix_socket(snow, "Result")
    link(land_color, mix_socket(lake, "A"))
    link(tex["Image Texture.002"].outputs["Color"], lake.inputs[0])
    if lake_ramp is not None:
        link(tex["Image Texture.005"].outputs["Color"], lake_ramp.inputs["Factor"])
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
        link(tex["Image Texture.006"].outputs["Color"], ice.inputs[0])
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
    cycles_settings.samples = SAMPLES
    cycles_settings.use_adaptive_sampling = True
    cycles_settings.adaptive_threshold = ADAPTIVE_THRESHOLD
    cycles_settings.use_denoising = True
    cycles_settings.denoiser = "OPENIMAGEDENOISE"
    cycles_settings.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    cycles_settings.denoising_prefilter = "ACCURATE"
    cycles_settings.denoising_quality = "HIGH"
    cycles_settings.denoising_use_gpu = denoise_device == "gpu"
    cycles_settings.dicing_rate = DICING_RATE
    cycles_settings.max_subdivisions = MAX_SUBDIVISIONS
    cycles_settings.offscreen_dicing_scale = OFFSCREEN_DICING_SCALE
    for attr, val in BOUNCES.items():
        setattr(cycles_settings, attr, val)
    cycles_settings.sample_clamp_indirect = CLAMP_INDIRECT
    scene.view_settings.view_transform = "Standard"


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

    probe = load_image(render_dir, IMAGES["Image Texture"][0])
    if tuple(probe.size) != (frame["width_px"], frame["height_px"]):
        sys.exit(f"heightfield is {tuple(probe.size)} px but frame.json says "
                 f"({frame['width_px']}, {frame['height_px']}) — stale or "
                 f"mismatched frame.json")
    bpy.data.images.remove(probe)
    span_px = plane_span_px(frame)
    patches = base_patches(span_px)
    plane = build_plane(frame["plane_height_units"], patches)
    build_material(plane, render_dir, frame["displacement_scale"], look,
                   render_seam.declared(render_dir))

    prefs = bpy.context.preferences.addons["cycles"].preferences
    print(f"body {args.body}, {'sea' if look.sea is not None else 'no sea'}; ", flush=True)
    # ECHOED SO A CALLER CAN ASSERT IT, for `--denoise-device`'s reason: a base grid that failed to
    # be cut renders successfully, a little soft, and leaves nothing on disk that differs.
    print(f"BASE_PATCHES {patches} SPAN_PX {span_px:.0f}", flush=True)
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
