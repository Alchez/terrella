#!/usr/bin/env python3
"""Build the hero-render Blender scene from code (Phase 1 keystone).

Reconstructs the hand-built Phase 0 scene — plane + adaptive-subdivision
displacement, two-ramp land/sea material with lake/river switches (plus a
snow switch iff snowmask_aea.png exists in the render dir), sun plus a
shadowless fill sun, ortho camera, locked render settings — entirely from
the constants below.
Verified against the hand-built .blend by structural dump-diff and a
pixel-diff of test renders (see PLAN.md Phase 1).

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
  blender -b --python pipeline/scene_build.py -- \
      --render-dir data/work/nepal/render \
      --out blender/nepal_hero.blend \
      [--frame-json data/work/nepal/render/frame.json]  # default: sibling
      [--render blender/renders/nepal_hero_8k.png]      # save, then render
"""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy  # pyright: ignore[reportMissingImports] — exists only in Blender's Python

# ---- locked look (PLAN.md "Locked global constants", 2026-07-06;
# ---- amended 2026-07-08: snow, fill sun, sun angle, land ramp top) --------
DISPLACEMENT_MIDLEVEL = 0.0
SUN_ROTATION = (math.radians(44.0), 0.0, math.radians(-45.0))
SUN_ANGLE = math.radians(12.0)
SUN_STRENGTH = 3.0
FILL_ROTATION = (math.radians(30.0), 0.0, math.radians(135.0))
FILL_ANGLE = math.radians(10.0)
FILL_STRENGTH = 0.45   # 15% of SUN_STRENGTH; shadowless SE fill so shadowed
                       # faces keep directional modeling (never pure black)
WORLD_RGBA = (0.887923, 0.799103, 0.665388, 1.0)   # F2E7D5
WORLD_STRENGTH = 0.3
WATER_RGBA = (0.313989, 0.558341, 0.577581, 1.0)   # 98C5C8
SNOW_RGBA = (0.806952, 0.879622, 0.921582, 1.0)    # E8F1F6 — glacial blue-white

LAND_RANGE = (0.0, 6000.0)       # meters -> ramp position 0..1
SEA_RANGE = (-3000.0, 0.0)       # meters -> ramp position 1..0 (reversed To)
LAND_STOPS = [                   # position, linear RGBA        (sRGB hex)
    (0.000, (0.814847, 0.693872, 0.527115, 1.0)),  # E9D9C0
    (0.083, (0.679543, 0.412543, 0.270498, 1.0)),  # D7AC8E
    (0.250, (0.617207, 0.313989, 0.215861, 1.0)),  # CE9880
    (0.500, (0.584079, 0.417885, 0.309469, 1.0)),  # C9AD97
    (0.750, (0.715694, 0.584078, 0.445201, 1.0)),  # DCC9B2
    (1.000, (0.814847, 0.715694, 0.577580, 1.0)),  # E9DCC8 — top stays in the
    # warm sand register: white/blue belongs to the snow mask alone
]
SEA_STOPS = [                    # 6-stop "smooth-C": shallow water a real teal, not
    (0.000, (0.274677, 0.571125, 0.558340, 1.0)),  # 8FC7C5  near-white ice; smooth
    (0.100, (0.201556, 0.479320, 0.479320, 1.0)),  # 7CB8B8  shelf->deep gradient
    (0.220, (0.138432, 0.381326, 0.412543, 1.0)),  # 68A6AC
    (0.380, (0.093059, 0.291771, 0.341914, 1.0)),  # 56939E
    (0.620, (0.063010, 0.215861, 0.274677, 1.0)),  # 47808F
    (1.000, (0.042311, 0.155926, 0.205079, 1.0)),  # 3A6E7D
]
RAMP_INTERPOLATION = "EASE"

SAMPLES = 4096
ADAPTIVE_THRESHOLD = 0.01
DICING_RATE = 1.0
MAX_SUBDIVISIONS = 12
BOUNCES = dict(max_bounces=12, diffuse_bounces=4, glossy_bounces=4,
               transmission_bounces=12, volume_bounces=0)
CLAMP_INDIRECT = 10.0

IMAGES = {  # node name -> (filename, interpolation)
    "Image Texture": ("heightfield_aea.tif", "Linear"),
    "Image Texture.001": ("oceanmask_aea.png", "Closest"),
    "Image Texture.002": ("inlandlake_aea.png", "Closest"),
    "Image Texture.003": ("river_aea.png", "Closest"),
}


def clear_scene():
    """Empty the startup scene but keep user preferences (OptiX device)."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                  bpy.data.cameras, bpy.data.images, bpy.data.worlds):
        for item in list(block):
            block.remove(item)


def build_plane(height):
    bpy.ops.mesh.primitive_plane_add(size=2.0)
    ob = bpy.context.active_object
    ob.name = "Plane"
    for vertex in ob.data.vertices:
        vertex.co.y *= height / 2.0
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


def build_material(ob, render_dir, displacement_scale):
    mat = bpy.data.materials.new("Material.001")
    mat.use_nodes = True
    mat.displacement_method = "DISPLACEMENT"
    nt = mat.node_tree
    for node in list(nt.nodes):
        nt.nodes.remove(node)

    tex = {}
    for name, (filename, interp) in IMAGES.items():
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

    land_range = make_map_range(nt, "Map Range", "Land",
                                LAND_RANGE, (0.0, 1.0))
    sea_range = make_map_range(nt, "Map Range.001", "Sea",
                               SEA_RANGE, (1.0, 0.0))
    land_ramp = make_ramp(nt, "Color Ramp.001", "", LAND_STOPS)
    sea_ramp = make_ramp(nt, "Color Ramp", "", SEA_STOPS)

    rgb = nt.nodes.new("ShaderNodeRGB")
    rgb.name = "Color"
    rgb.outputs[0].default_value = WATER_RGBA

    lake = make_mix(nt, "Mix.001", "Lake")
    river = make_mix(nt, "Mix.002", "River")
    ocean = make_mix(nt, "Mix", "")

    # optional data-driven snow/ice (experiments/snow_mask.py); mask absent
    # -> graph identical to the pre-snow scene
    snow = None
    if (render_dir / "snowmask_aea.png").exists():
        snow_image_node = nt.nodes.new("ShaderNodeTexImage")
        snow_image_node.name = "Image Texture.004"
        snow_image_node.image = load_image(render_dir, "snowmask_aea.png")
        snow_image_node.interpolation = "Closest"
        snow_image_node.extension = "REPEAT"
        tex["Image Texture.004"] = snow_image_node
        snow = make_mix(nt, "Mix.003", "Snow")
        mix_socket(snow, "B").default_value = SNOW_RGBA
        print("snowmask_aea.png found — wiring Snow mix", flush=True)

    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.inputs["Roughness"].default_value = 1.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.name = "Material Output"

    link = nt.links.new
    hf = tex["Image Texture"]
    link(hf.outputs["Color"], disp.inputs["Height"])
    link(disp.outputs["Displacement"], out.inputs["Displacement"])
    link(hf.outputs["Color"], land_range.inputs["Value"])
    link(hf.outputs["Color"], sea_range.inputs["Value"])
    link(land_range.outputs["Result"], land_ramp.inputs["Factor"])
    link(sea_range.outputs["Result"], sea_ramp.inputs["Factor"])
    land_color = land_ramp.outputs["Color"]
    if snow is not None:
        link(land_color, mix_socket(snow, "A"))
        link(tex["Image Texture.004"].outputs["Color"], snow.inputs[0])
        land_color = mix_socket(snow, "Result")
    link(land_color, mix_socket(lake, "A"))
    link(tex["Image Texture.002"].outputs["Color"], lake.inputs[0])
    link(rgb.outputs["Color"], mix_socket(lake, "B"))
    link(mix_socket(lake, "Result"), mix_socket(river, "A"))
    link(tex["Image Texture.003"].outputs["Color"], river.inputs[0])
    link(rgb.outputs["Color"], mix_socket(river, "B"))
    link(mix_socket(river, "Result"), mix_socket(ocean, "A"))
    link(sea_ramp.outputs["Color"], mix_socket(ocean, "B"))
    link(tex["Image Texture.001"].outputs["Color"], ocean.inputs[0])
    link(mix_socket(ocean, "Result"), bsdf.inputs["Base Color"])
    link(bsdf.outputs["BSDF"], out.inputs["Surface"])

    ob.data.materials.append(mat)


def configure_render(res_x, res_y):
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
    cycles_settings.denoising_use_gpu = False
    cycles_settings.dicing_rate = DICING_RATE
    cycles_settings.max_subdivisions = MAX_SUBDIVISIONS
    for attr, val in BOUNCES.items():
        setattr(cycles_settings, attr, val)
    cycles_settings.sample_clamp_indirect = CLAMP_INDIRECT
    scene.view_settings.view_transform = "Standard"


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-dir", type=Path, required=True)
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
    args = ap.parse_args(argv)
    render_dir = args.render_dir.resolve()

    frame_path = args.frame_json or render_dir / "frame.json"
    if not frame_path.exists():
        sys.exit(f"{frame_path} not found — render_prep.py emits it")
    frame = json.loads(frame_path.read_text())

    clear_scene()
    configure_render(frame["res_x"], frame["res_y"])
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
    plane = build_plane(frame["plane_height_units"])
    build_material(plane, render_dir, frame["displacement_scale"])

    prefs = bpy.context.preferences.addons["cycles"].preferences
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
