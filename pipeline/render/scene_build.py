"""Build one relief scene from code: a country's hero, or one block of a planet.

The shared rig, not the hero rig. Two callers stage a render directory and shell into this exact
file: `render_prep.py` for a country in its own Albers projection, and the block prep for a z8
EPSG:3857 block, which writes its cuts under the same filenames purely to satisfy the table below.
Nothing here is country-shaped.

Builds the whole scene from the constants below: plane plus adaptive-subdivision displacement, a
land ramp with lake/river switches over an optional sea ramp (plus a snow switch iff snowmask.png
exists in the render dir, and a depth-keyed lake ramp iff lakedepth.tif does), sun plus a shadowless
fill sun, ortho camera, locked render settings.

The look arrives as `--body`, a slug and not a `Body`: Blender's interpreter cannot import this
project's virtual environment, and `palette.look_for` keys on slugs for that reason.

Runs inside Blender's Python, which has no GDAL: all geographic math (projection, frame width, plane
aspect) happens in render_prep.py and arrives here as plain numbers in frame.json (plane height,
ortho scale, displacement scale, render resolution; docs/framing-math.md). The heightfield's pixel
size is cross-checked against frame.json so a stale or mismatched file fails loudly instead of
framing the wrong scene.

Colour constants are stored in linear floats exactly as Blender holds them; the hex alongside is the
sRGB the GUI takes, which it converts on entry and bpy does not.

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

#: How wide the displacement plane is in Blender units, the ruler every other number in this module
#: is written on: `ortho_scale` is a fraction of it, `plane_height_units` is measured against it, a
#: tile's camera offset is a multiple of it. A constant rather than four literals because the tiling
#: law has to agree with the plane `build_plane` adds, and a disagreement photographs the wrong
#: ground and stitches perfectly. Outside `Rig` deliberately, for the reason
#: `test_no_rig_constant_is_left_at_module_level` gives.
PLANE_WIDTH_UNITS = 2.0


def _rgba(stops):
    """palette Stop list (position, linear RGB) -> the (position, RGBA) ColorRamps take."""
    return [(pos, (*rgb, 1.0)) for pos, rgb in stops]


def arrival_azimuth_deg(rotation):
    """Compass bearing a sun with this XYZ euler arrives from, clockwise from north.

    A Blender sun shines along its own local -Z, so an euler says where the light goes; the
    cartographic convention says where it comes from, and the two differ by 180 degrees before the
    euler's own sign conventions apply. The executable copy of that conversion, with the pinned
    bearing in the test that calls it. Pure arithmetic, so a test reaches it without Blender.
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
    """`rotation` turned so its light arrives `delta_deg` further clockwise. Checks its own work.

    The euler turns the other way: +90 on Z takes the arrival bearing from 315 to 225, and a frame
    lit from the wrong side of the meridian is a plausible frame. The residual is itself an angle,
    so it wraps; compared linearly it would refuse a correct 180-degree turn. The check runs at
    delta 0 as well, which is every hero and every block, so it cannot rot on the path nobody turns.
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

    The split is derived from `ortho_scale` and never passed in: the camera fraction the prep chose
    is already in the frame, so a driver asking for tile 1,1 of a frame framed for the whole plane
    is a contradiction visible here, where a split arriving as its own argument would agree with
    whichever of the two was wrong. It moves the object rather than `shift_x`, which is expressed in
    sensor widths and inherits the sensor-fit rules. Square planes only, refused rather than
    generalised: the rows step by `ortho_scale`, the plane's own step only while height equals
    width, and a block's plane is not square, so a two-axis version has nothing to verify it.
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


@dataclasses.dataclass(frozen=True)
class Rig:
    """Every constant that reaches a rendered pixel and is this module's rather than a look's.

    One structure, so `rig_recipe` can be `dataclasses.asdict` of the instance below and a forgotten
    constant is unrepresentable rather than merely caught. The rule beside this file owns what that
    derivation costs, field names being recipe keys.

    No snow or ice albedo is a field here: those arrive per render directory through
    `render_seam.paint_for`, and a default restores the fallback that rendered Earth's whites on
    every body. `test_rig_whites_are_the_bodys` is the guard.
    """

    displacement_midlevel: float
    sun_rotation: tuple[float, float, float]
    sun_angle: float
    sun_strength: float
    fill_rotation: tuple[float, float, float]
    fill_angle: float
    #: 15% of `sun_strength`; a shadowless SE fill so shadowed faces keep directional modelling and
    #: never go pure black. `arrival_azimuth_deg` is what says which bearing it arrives from.
    fill_strength: float
    #: Achromatic, and the scene's only ambient light rather than a backdrop swatch: a tint does not
    #: tint a near-white surface, it replaces it, so re-warming this to colour the backdrop tints
    #: every white on the planet to do it. Its grey is the luminance of the warm colour it replaced,
    #: which made that move hue-only rather than the twice-rejected ambient raise.
    world_rgba: tuple[float, float, float, float]
    world_strength: float
    water_rgba: tuple[float, float, float, float]
    #: Depth-position ramp; stop 0 is the flat water tint.
    lake_stops: list[tuple[float, tuple[float, float, float, float]]]
    ramp_interpolation: str
    #: A Cycles sample count, and the one number here measured in the same units as a block edge
    #: without being one. Never search-and-replace it.
    samples: int
    adaptive_threshold: float
    dicing_rate: float
    #: Per patch, not per mesh; `base_patches` holds what that means.
    max_subdivisions: int
    #: How much coarser geometry outside the camera is diced. It exists for the block path, whose
    #: plane carries terrain far past the traced rectangle so that off-block ridges cast shadows in;
    #: at Earth's widest that plane is 7,808 px against a 4,352 px frame, so most of the mesh is
    #: never seen. Pinned because it was an unrecorded Blender default rather than because it is a
    #: quality lever: 4, 16 and 64 sit within 0.06 DN of each other, and 16 is the default 4 raised
    #: for memory.
    offscreen_dicing_scale: float
    bounces: dict[str, int]
    clamp_indirect: float
    #: Set on every image the rig loads, so 0-255 maps linearly to 0-1 with no sRGB transform on
    #: top: the thing a binary mask never notices and a soft alpha very much does.
    image_colorspace: str
    #: The other end of the same axis: how linear light becomes an 8-bit value, and the last thing
    #: to touch every pixel in the frame. A view name from Blender's OCIO config, not a colorspace.
    view_transform: str

    subdivision_type: str
    #: Viewport and render subdivision. Only the second reaches a rendered pixel; the first is here
    #: because a mismatch between them is how a frame that previewed correctly renders coarse.
    subdivision_levels: int
    subdivision_render_levels: int
    use_adaptive_subdivision: bool
    camera_type: str
    camera_clip_end: float
    #: The FILL sun's shadow, not the main one's. It is off so the fill lifts shadowed faces
    #: without casting a second set of its own.
    fill_casts_shadow: bool
    map_range_clamp: bool
    mix_blend_type: str
    mix_clamp_factor: bool
    displacement_method: str
    displacement_space: str
    #: The B input of the ice-flatten mix: the height ice is pulled toward, in displacement units.
    ice_flatten_floor: float
    rowscale_operation: str
    rowscale_use_clamp: bool
    bsdf_roughness: float
    engine: str
    image_file_format: str
    image_color_mode: str
    #: What Cycles renders on. `configure_render`'s `denoise_device` argument is a different
    #: question and stays a caller decision, for the reason its own docstring gives.
    device: str
    #: The quasi-random sequence the path tracer walks, pinned for continuity rather than quality:
    #: 5.1.2 defaults to TABULATED_SOBOL and 5.2.1 to AUTOMATIC, so the two versions build different
    #: scenes and every pixel of the planet on disk was drawn with this one. Which is best is a
    #: separate question this does not answer.
    sampling_pattern: str
    use_adaptive_sampling: bool
    use_denoising: bool
    denoiser: str
    denoising_input_passes: str
    denoising_prefilter: str
    denoising_quality: str


RIG = Rig(
    displacement_midlevel=0.0,
    sun_rotation=(math.radians(90.0 - palette.SUN_ALT_DEG), 0.0, math.radians(-135.0)),
    sun_angle=math.radians(palette.SUN_ANGULAR_DIAMETER_DEG),
    sun_strength=3.0,
    # Derived from the authored angles rather than transcribed: both spellings gave the same two
    # floats, so nothing here reads as a live dial that is not one. `arrival_azimuth_deg` inverts
    # the Z law, a light arriving from a bearing pointing at `180 - bearing`.
    fill_rotation=(math.radians(90.0 - palette.FILL_ALTITUDE), 0.0,
                   math.radians(180.0 - palette.FILL_AZIMUTH)),
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
    subdivision_type="SIMPLE",
    subdivision_levels=1,
    subdivision_render_levels=2,
    use_adaptive_subdivision=True,
    camera_type="ORTHO",
    camera_clip_end=100.0,
    fill_casts_shadow=False,
    map_range_clamp=True,
    mix_blend_type="MIX",
    mix_clamp_factor=True,
    displacement_method="DISPLACEMENT",
    displacement_space="OBJECT",
    ice_flatten_floor=0.0,
    rowscale_operation="MULTIPLY",
    rowscale_use_clamp=False,
    bsdf_roughness=1.0,
    engine="CYCLES",
    image_file_format="PNG",
    image_color_mode="RGBA",
    device="GPU",
    sampling_pattern="TABULATED_SOBOL",
    use_adaptive_sampling=True,
    use_denoising=True,
    denoiser="OPENIMAGEDENOISE",
    denoising_input_passes="RGB_ALBEDO_NORMAL",
    denoising_prefilter="ACCURATE",
    denoising_quality="HIGH",
)

@dataclasses.dataclass(frozen=True)
class TextureSpec:
    """One image node's whole wiring, declared here rather than spelled at the call site.

    Every value on a texture is a look decision except its name: `interpolation` decides whether a
    mask has a hard edge or a feathered one, and `extension` decides whether a texture wraps at the
    plane's UV boundary, which at the poles is whether one pole's row bleeds into the other's. The
    name is identity rather than look, and the one field `rig_recipe` leaves out. `optional` is the
    raster's presence, never a look: an optional node is built iff its file was declared.
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

    Both ends of each range come off the `Surface` rather than restating the 0.0, which is the
    Earth-is-the-datum assumption `origin_m` exists to remove. No assertion over Earth can tell the
    read from the restatement, so `test_scene_build_sync` supplies a moved origin.
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

    Derived from the structure rather than enumerated, so `Rig` and `TEXTURES` are the enumeration
    and what is still spelled inline is invisible here;
    `TestTheBuilderSpellsNoLookValueWhereTheRecipeCannotSeeIt` holds those, with the cost of moving
    them in. A hash of this file would also be honest and is deliberately not what this is: it would
    restage a planet render on a docstring edit, where a recipe moves when a value moves. The look
    arrives as an argument because it is not this module's to own.
    """
    constants = look_constants(look)
    return {
        "rig": dataclasses.asdict(RIG),
        # The whole table rather than the four this look loads, and keyed by the raster minus the
        # node's name: the rule beside this file owns both, and
        # `TestRenamingANodeDoesNotRestageThePlanet` is the guard.
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

    The optional ones are built at their own sites, beside the mixes and ramps they feed, which is
    what keeps each optional branch readable as one block.

    A declaration decides this and never `Path.exists()`: `prep_block.build` writes the lake and
    river masks only when the planet seam declared a watermask, so what is loaded is what some stage
    said it wrote. A look still answers for the sea: `Look.sea` decides whether the sea branch
    exists in the graph, the declaration whether the image can be loaded, and the pair that must
    never resolve quietly is the one the raise below describes.
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
    """Build one image node entirely from its declaration, this being the only place one is
    configured, so there is nowhere left to spell an interpolation or an extension inline."""
    node = nt.nodes.new("ShaderNodeTexImage")
    node.name = spec.name
    node.image = load_image(render_dir, spec.filename)
    node.interpolation = spec.interpolation
    node.extension = spec.extension
    return node


#: GPU backends best-first, from Blender's own `enum_device_type` minus `CPU`.
#:
#: The order is a preference and the membership is not: anything here that Blender reports as
#: present is acceptable, and what must never appear is `CPU` or `NONE`, because taking either is
#: the silent fallback this whole mechanism exists to refuse. OPTIX leads because it uses the RT
#: cores and is the only one measured on this box; HIP, ONEAPI and METAL are exercised by no
#: hardware here, which is worth knowing before trusting them.
GPU_BACKENDS = ("OPTIX", "HIP", "ONEAPI", "METAL", "CUDA")


def choose_compute_backend(available):
    """The best GPU backend among those Blender reports, or raise rather than fall back.

    A CPU render is a failure and not a degraded mode: it is correct, several times slower, and
    identical on disk, so no gate can catch it.
    """
    for backend in GPU_BACKENDS:
        if backend in available:
            return backend
    raise RuntimeError(
        f"no GPU backend among {sorted(available)}: Cycles would render on the CPU, which is "
        f"correct and roughly seven times slower. Wanted one of {list(GPU_BACKENDS)}.")


def select_compute_device(preferences):
    """Set the compute backend from what this build reports, and enable its devices.

    Derived per run, never read from saved preferences: those live in `~/.config/blender/<version>/`,
    so they are outside this repo, unversioned, and absent on any Blender the box has not run
    interactively, which is every upgrade, every fresh checkout and every other machine.
    """
    preferences.get_devices()
    backend = choose_compute_backend({device.type for device in preferences.devices})
    preferences.compute_device_type = backend
    # Re-read: the device list is rebuilt per backend, so the objects fetched above belong to
    # whatever backend was selected before this call.
    preferences.get_devices()
    for device in preferences.devices:
        device.use = device.type == backend
    if preferences.compute_device_type != backend:
        raise RuntimeError(f"asked for {backend} and this build kept "
                           f"{preferences.compute_device_type!r}")
    return backend


def clear_scene():
    """Empty the startup scene. The compute device is `select_compute_device`'s and is set per run,
    so nothing here depends on a preferences file surviving."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                  bpy.data.cameras, bpy.data.images, bpy.data.worlds):
        for item in list(block):
            block.remove(item)


def plane_span_px(frame):
    """How many render pixels the displacement plane spans, which is what dicing counts.

    Not the heightfield's pixel width, which is the tempting number and wrong on both paths for
    opposite reasons: a hero's 16384-wide grid is photographed at 7680, and a block's plane is
    deliberately wider than the rectangle its camera sees. Both come off the frame's own arithmetic
    instead, the camera spanning `ortho_scale` of the plane along the longer axis.
    """
    pixels_per_unit = max(frame["res_x"], frame["res_y"]) / frame["ortho_scale"]
    return max(PLANE_WIDTH_UNITS, frame["plane_height_units"]) * pixels_per_unit


def base_patches(span_px):
    """Quads per plane edge, so adaptive subdivision can reach one micropolygon per pixel.

    `RIG.max_subdivisions` caps each patch and not the mesh, which is the whole reason this exists:
    a plane added as a single quad caps at 2**12 micropolygons along its entire edge however many
    pixels the render asks for, and past that Cycles dices coarser than the pixels with no warning
    and no error, an image that merely looks a little softer than it should.

    A grid rather than a larger cap, because a constant has to be re-derived every time the block
    edge or the context moves and this does not; `test_scene_build_sync` holds one micropolygon per
    pixel across every planned block on every registered body.

    Reached only through `--base-grid fitted`, and the reason is a hard VRAM ceiling rather than a
    cost: the grid multiplies micropolygons by 4x on both callers alike, but a hero's plane is
    entirely in frame where `RIG.offscreen_dicing_scale` coarsens the ~69% of a block's plane its
    camera never sees. On this box's 12 GB card the largest heroes fail outright to build an OptiX
    acceleration structure, so the hero lane keeps the single quad, knowingly under-diced, the
    alternative being no hero at all. Which frame sizes sit on which side of that wall is unmeasured.
    """
    return max(1, math.ceil(span_px / 2 ** RIG.max_subdivisions))


def build_plane(height, patches_per_edge):
    # No default, for the reason no field on `Body` has one: a defaulted 1 is exactly the value that
    # under-dices in silence, so a caller that dropped the argument would render a softer planet and
    # raise nothing, where without one it is a TypeError before Cycles starts.
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
    mod.subdivision_type = RIG.subdivision_type
    mod.levels = RIG.subdivision_levels
    mod.render_levels = RIG.subdivision_render_levels
    mod.use_adaptive_subdivision = RIG.use_adaptive_subdivision
    return ob


def build_camera(ortho_scale, offset=(0.0, 0.0)):
    cam = bpy.data.cameras.new("Camera")
    cam.type = RIG.camera_type
    cam.ortho_scale = ortho_scale
    cam.clip_end = RIG.camera_clip_end
    ob = bpy.data.objects.new("Camera", cam)
    ob.location = (*offset, 5.0)
    bpy.context.collection.objects.link(ob)
    bpy.context.scene.camera = ob
    return ob


def declared_albedo(render_dir: Path, image: str) -> tuple[float, float, float, float]:
    """The linear RGBA this render directory says `image`'s mask is painted in.

    Only the sunlit half is wired: Cycles produces the shaded end from light rather than keying it
    to the producer's second colour. That is why a body's authored shadow hue reaches no raytraced
    pixel, and the seam keeps the other half recoverable.
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
    """The fill turns with the key, never on its own. `cap_render.azimuth_delta` applies to both
    azimuths, so a rig that moved only the key would be a different intervention from the one the
    cap's law describes."""
    sun = bpy.data.lights.new("Fill", "SUN")
    sun.energy = RIG.fill_strength
    sun.angle = RIG.fill_angle
    sun.use_shadow = RIG.fill_casts_shadow
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
    map_range_node.clamp = RIG.map_range_clamp
    map_range_node.inputs["From Min"].default_value = from_range[0]
    map_range_node.inputs["From Max"].default_value = from_range[1]
    map_range_node.inputs["To Min"].default_value = to_range[0]
    map_range_node.inputs["To Max"].default_value = to_range[1]
    return map_range_node


def make_mix(nt, name, label):
    mix_node = nt.nodes.new("ShaderNodeMix")
    mix_node.name, mix_node.label = name, label
    mix_node.data_type = "RGBA"
    mix_node.blend_type = RIG.mix_blend_type
    mix_node.clamp_factor = RIG.mix_clamp_factor
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
    mix_node.blend_type = RIG.mix_blend_type
    mix_node.clamp_factor = RIG.mix_clamp_factor
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
    mat.displacement_method = RIG.displacement_method
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
    disp.space = RIG.displacement_space
    disp.inputs["Midlevel"].default_value = RIG.displacement_midlevel
    # Live on the hero path and overridden on the block path, where the rowscale Math node below
    # drives this socket instead. Not a second owner of the constant despite appearing twice: a
    # linked socket ignores its default, so exactly one of the two reaches a pixel per render, and
    # a hero has no `rowscale.tif` to link from.
    disp.inputs["Scale"].default_value = displacement_scale

    # Named for what they are, and the sea nodes stay interleaved with the land ones rather than
    # grouped: a node's name answers to the reader and to the arm probes that address one by name.
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

    # Each mix exists only where its mask does, the same rule the optional nodes below follow.
    lake = make_mix(nt, "Lake Mix", "Lake") if lake_spec.filename in present else None
    river = make_mix(nt, "River Mix", "River") if river_spec.filename in present else None
    ocean = None if sea_ramp is None else make_mix(nt, "Ocean Mix", "Ocean")

    # optional data-driven snow/ice (render/snow_mask.py); layer not declared -> no snow node
    snow = None
    if render_seam.SNOWMASK in present:
        tex[snow_spec.name] = make_texture(nt, render_dir, snow_spec)
        snow = make_mix(nt, "Snow Mix", "Snow")
        mix_socket(snow, "B").default_value = declared_albedo(render_dir, render_seam.SNOWMASK)
        print(f"{render_seam.SNOWMASK} declared — wiring Snow mix", flush=True)

    # optional depth-keyed lake tint (render/lake_mask.py); raster absent -> the Lake mix keeps the
    # flat RGB node, which is stop 0 of this ramp, so a lake without depth data degrades to that
    # colour with no selector logic. The raster stores the log1p ramp position (0..1), not metres.
    # Rivers stay flat by decision, there being no global bed data. Depth is tint-only and must
    # never reach displacement: at 15x a carved bed makes a crater of the lake.
    lake_ramp = None
    if render_seam.LAKEDEPTH in present:
        tex[lake_depth_spec.name] = make_texture(nt, render_dir, lake_depth_spec)
        lake_ramp = make_ramp(nt, "Lake Ramp", "Lake Bed", RIG.lake_stops)
        print(f"{render_seam.LAKEDEPTH} declared — wiring depth-keyed Lake ramp", flush=True)

    # optional sea ice (block prep only today): one continuous ocean-gated alpha drives both arms,
    # an ice-white mix over the finished sea colour and the displacement pulled toward sea level,
    # which is what a floating sheet is. The ramps keep reading the raw heightfield on purpose:
    # damping the branch that feeds them would read 0 m under pack and collapse abyssal colour to
    # shelf colour, deleting the see-through the alpha's ceiling exists for.
    ice = None
    ice_flatten = None
    if render_seam.SEAICE in present:
        tex[ice_spec.name] = make_texture(nt, render_dir, ice_spec)
        ice = make_mix(nt, "Ice Mix", "Ice")
        mix_socket(ice, "B").default_value = declared_albedo(render_dir, render_seam.SEAICE)
        ice_flatten = make_float_mix(nt, "Ice Flatten", "Ice Flatten")
        float_socket(ice_flatten, "B").default_value = RIG.ice_flatten_floor  # sea level
        print(f"{render_seam.SEAICE} declared — wiring Ice mix + displacement damp", flush=True)

    # The driven socket is Scale and not Height, for two reasons that outlast today's constants.
    # `disp = (Height - Midlevel) * Scale`, so multiplying Scale is right at any midlevel where
    # multiplying Height is right only while `RIG.displacement_midlevel` is 0.0; and it leaves the
    # Height chain alone, so the sea-ice damp above and the ramps' raw metres both need no thought.
    rowscale = None
    if render_seam.ROWSCALE in present:
        tex[rowscale_spec.name] = make_texture(nt, render_dir, rowscale_spec)
        rowscale = nt.nodes.new("ShaderNodeMath")
        rowscale.name = "Row Scale Multiply"
        rowscale.operation = RIG.rowscale_operation
        rowscale.use_clamp = RIG.rowscale_use_clamp  # leaves 1.0 in both directions
        rowscale.inputs[1].default_value = displacement_scale
        print(f"{render_seam.ROWSCALE} declared — wiring per-row displacement scale", flush=True)

    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.inputs["Roughness"].default_value = RIG.bsdf_roughness
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
    # The chain is threaded rather than fixed, so a body with no inland water hands the land colour
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

    Denoising on the GPU is much faster and the heroes still must not use it: render and denoise
    then contend for the same card and the driver throws the Xid 31 fault CLAUDE.md's rule is about.

    It cannot be derived from `res_x`/`res_y`, the obvious idea: the two populations overlap, with
    the largest heroes below a 4096 block's 18.9 Mpx, so any threshold either flips a hero into an
    untested regime or puts the blocks back on the CPU. It would also encode this machine's card as
    though it were a fact about the project, and reading the device at render time makes the output
    depend on the host with nothing on disk saying which way it went: a recipe records a value, not
    a rule.

    So the caller decides and records what it decided, the default being the conservative one a
    future caller at an unknown frame size inherits.
    """
    if denoise_device not in ("cpu", "gpu"):
        raise ValueError(f"denoise_device must be 'cpu' or 'gpu', not {denoise_device!r}")
    scene = bpy.context.scene
    render_settings, cycles_settings = scene.render, scene.cycles
    render_settings.engine = RIG.engine
    render_settings.resolution_x, render_settings.resolution_y = res_x, res_y
    render_settings.image_settings.file_format = RIG.image_file_format
    render_settings.image_settings.color_mode = RIG.image_color_mode
    cycles_settings.device = RIG.device
    cycles_settings.sampling_pattern = RIG.sampling_pattern
    cycles_settings.samples = RIG.samples
    cycles_settings.use_adaptive_sampling = RIG.use_adaptive_sampling
    cycles_settings.adaptive_threshold = RIG.adaptive_threshold
    cycles_settings.use_denoising = RIG.use_denoising
    cycles_settings.denoiser = RIG.denoiser
    cycles_settings.denoising_input_passes = RIG.denoising_input_passes
    cycles_settings.denoising_prefilter = RIG.denoising_prefilter
    cycles_settings.denoising_quality = RIG.denoising_quality
    cycles_settings.denoising_use_gpu = denoise_device == "gpu"
    cycles_settings.dicing_rate = RIG.dicing_rate
    cycles_settings.max_subdivisions = RIG.max_subdivisions
    cycles_settings.offscreen_dicing_scale = RIG.offscreen_dicing_scale
    for attr, val in RIG.bounces.items():
        setattr(cycles_settings, attr, val)
    cycles_settings.sample_clamp_indirect = RIG.clamp_indirect
    scene.view_settings.view_transform = RIG.view_transform


def build_parser():
    """The CLI, separated from `main` so its defaults can be asserted without Blender.

    Four of these defaults are load-bearing and fail the same way: `--denoise-device`,
    `--base-grid`, `--sun-azimuth-delta` and `--tile` each describe a regime one caller opts into
    and the other must not, which is what keeps the pinned hero renders clear of settings measured
    on blocks and caps.
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
                         "renders under; the cap renders a ring of these because Cycles takes one "
                         "sun direction per frame where the cap's light turns per pixel")
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
    backend = select_compute_device(bpy.context.preferences.addons["cycles"].preferences)
    configure_render(frame["res_x"], frame["res_y"], denoise_device=args.denoise_device)
    # Echoed so a caller can assert it: a flag that failed to arrive would otherwise render on the
    # CPU while the caller's recipe records "gpu", which is the producer-declares rule inverted into
    # a lie, the block correct, slow, and permanently mislabelled.
    print(f"DENOISE_DEVICE {args.denoise_device}", flush=True)
    build_world()
    offset = ((0.0, 0.0) if args.tile is None
              else tile_camera_location(frame["ortho_scale"], frame["plane_height_units"],
                                        args.tile))
    build_camera(frame["ortho_scale"], offset)
    sun = build_sun(args.sun_azimuth_delta)
    fill = build_fill(args.sun_azimuth_delta)
    # Echoed so a caller can assert them, for `--denoise-device`'s reason and harder: a dropped
    # `--sun-azimuth-delta` renders a frame lit from the base bearing and a dropped `--tile`
    # photographs the whole plane at a quadrant's resolution, both succeeding, both looking like a
    # rendered cap, neither leaving anything on disk that differs from the frame that was asked for.
    # The bearings are read back off the built objects rather than recomputed.
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

    print(f"body {args.body}, {'sea' if look.sea is not None else 'no sea'}; ", flush=True)
    # Echoed so a caller can assert it, for `--denoise-device`'s reason: a base grid that failed to
    # be cut renders successfully, a little soft, and leaves nothing on disk that differs. The
    # policy rides with the count because they fail independently: `fitted` on a plane under the cap
    # yields 1, indistinguishable from the flag never arriving.
    print(f"BASE_GRID {args.base_grid} BASE_PATCHES {patches} SPAN_PX {span_px:.0f}", flush=True)
    print(f"plane 2.0 x {frame['plane_height_units']:.6f}; "
          f"ortho {frame['ortho_scale']:.6f}; "
          f"displacement {frame['displacement_scale']:.6e}; "
          f"res {frame['res_x']} x {frame['res_y']}; compute device {backend}", flush=True)
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
