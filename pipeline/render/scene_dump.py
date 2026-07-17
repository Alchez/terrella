"""Exhaustive dump of a hero scene: the verification oracle for scene_build.py
and the harness for version A/Bs (e.g. the Blender 5.2 LTS pin decision).

Prints render/cycles/color-management settings, world, object transforms,
modifier state, the full material graph (ramp stops included), all links, and
a sampled evaluation of every ColorRamp (cr.evaluate() at fixed positions —
this tests the *function*, not just the stored stops; it is what caught the
scrambled-ramp bug on 2026-07-07 after the stored stops looked plausible).

Node-editor XY positions are deliberately omitted so two dumps compare with
no filtering:  diff <(sort A.txt) <(sort B.txt)
(sorting normalizes creation order of objects and links).

Lesson encoded here: before trusting a passing comparison, run it once against
a known-bad file and watch it fail — the first version of this oracle passed
on a broken scene because an overzealous grep deleted every node line.

Usage:
  blender -b FILE.blend --python pipeline/scene_dump.py > dump.txt 2>/dev/null
"""
import bpy  # pyright: ignore[reportMissingImports] — exists only in Blender's Python


def p(*values):
    print(*values, flush=True)


RAMP_SAMPLES = (0.0, 0.02, 0.05, 0.075, 0.1, 0.15, 0.3, 0.4, 0.7, 1.0)

scene = bpy.context.scene
render_settings, cycles_settings = scene.render, scene.cycles

p("== render ==")
p(f"engine={render_settings.engine} res={render_settings.resolution_x}x{render_settings.resolution_y}@{render_settings.resolution_percentage}%")
p(f"film_transparent={render_settings.film_transparent}")
p(f"image: format={render_settings.image_settings.file_format} mode={render_settings.image_settings.color_mode}"
  f" depth={render_settings.image_settings.color_depth} compression={render_settings.image_settings.compression}")

p("== cycles ==")
p(f"device={cycles_settings.device} samples={cycles_settings.samples}")
p(f"adaptive={cycles_settings.use_adaptive_sampling} adaptive_threshold={cycles_settings.adaptive_threshold:.6f}"
  f" min_samples={cycles_settings.adaptive_min_samples}")
p(f"denoise={cycles_settings.use_denoising} denoiser={cycles_settings.denoiser}"
  f" input={getattr(cycles_settings, 'denoising_input_passes', 'n/a')}"
  f" prefilter={getattr(cycles_settings, 'denoising_prefilter', 'n/a')}"
  f" quality={getattr(cycles_settings, 'denoising_quality', 'n/a')}"
  f" gpu={getattr(cycles_settings, 'denoising_use_gpu', 'n/a')}")
p(f"dicing_rate={cycles_settings.dicing_rate} max_subdivisions={cycles_settings.max_subdivisions}"
  f" offscreen_dicing_scale={cycles_settings.offscreen_dicing_scale}")
p(f"bounces: total={cycles_settings.max_bounces} diffuse={cycles_settings.diffuse_bounces}"
  f" glossy={cycles_settings.glossy_bounces} transmission={cycles_settings.transmission_bounces}"
  f" volume={cycles_settings.volume_bounces}")
p(f"clamp: direct={cycles_settings.sample_clamp_direct} indirect={cycles_settings.sample_clamp_indirect}")

p("== color management ==")
vs = scene.view_settings
p(f"display_device={scene.display_settings.display_device}"
  f" view_transform={vs.view_transform} look={vs.look}"
  f" exposure={vs.exposure} gamma={vs.gamma}"
  f" curves={vs.use_curve_mapping}")

p("== world ==")
world = scene.world
if world and world.use_nodes:
    for node in world.node_tree.nodes:
        if node.type == "BACKGROUND":
            col = node.inputs["Color"].default_value
            p(f"background rgba=({col[0]:.6f}, {col[1]:.6f}, {col[2]:.6f},"
              f" {col[3]:.3f}) strength={node.inputs['Strength'].default_value}")

p("== objects ==")
for ob in scene.objects:
    p(f"[{ob.name}] type={ob.type} loc=({ob.location.x:.6f}, {ob.location.y:.6f},"
      f" {ob.location.z:.6f}) rot=({ob.rotation_euler.x:.6f},"
      f" {ob.rotation_euler.y:.6f}, {ob.rotation_euler.z:.6f})"
      f" scale=({ob.scale.x:.6f}, {ob.scale.y:.6f}, {ob.scale.z:.6f})")
    if ob.type == "CAMERA":
        cam = ob.data
        p(f"  camera: type={cam.type} ortho_scale={cam.ortho_scale}"
          f" clip=({cam.clip_start}, {cam.clip_end}) sensor_fit={cam.sensor_fit}"
          f" shift=({cam.shift_x}, {cam.shift_y})"
          f" active={'YES' if scene.camera == ob else 'no'}")
    if ob.type == "LIGHT":
        li = ob.data
        p(f"  light: type={li.type} energy={li.energy}"
          f" angle={getattr(li, 'angle', 0.0):.6f}"
          f" use_shadow={getattr(li, 'use_shadow', 'n/a')}"
          f" color=({li.color.r:.4f}, {li.color.g:.4f}, {li.color.b:.4f})")
    if ob.type == "MESH":
        p(f"  mesh: {len(ob.data.vertices)} verts, dims=({ob.dimensions.x:.6f},"
          f" {ob.dimensions.y:.6f}, {ob.dimensions.z:.6f})")
        for modifier in ob.modifiers:
            extra = ""
            if modifier.type == "SUBSURF":
                extra = (f" subdivision_type={modifier.subdivision_type}"
                         f" levels={modifier.levels} render_levels={modifier.render_levels}"
                         f" use_adaptive={getattr(modifier, 'use_adaptive_subdivision', 'n/a')}")
            p(f"  modifier [{modifier.name}] type={modifier.type}{extra}")
        for slot in ob.material_slots:
            p(f"  material slot: {slot.material.name if slot.material else None}")

p("== material graph ==")
mat = bpy.data.objects["Plane"].active_material
p(f"material={mat.name} displacement_method={mat.displacement_method}")
nt = mat.node_tree
for node in sorted(nt.nodes, key=lambda node: node.name):
    head = f"[{node.name}] label={node.label!r} type={node.type} mute={node.mute}"
    if node.type == "TEX_IMAGE":
        if node.image:
            head += (f" image={node.image.name}"
                     f" colorspace={node.image.colorspace_settings.name}"
                     f" interp={node.interpolation} extension={node.extension}")
        else:
            head += " image=None"
    elif node.type == "MAP_RANGE":
        ins = {input_socket.name: round(input_socket.default_value, 6)
               for input_socket in node.inputs if input_socket.type == "VALUE"}
        head += (f" data_type={node.data_type} interp={node.interpolation_type}"
                 f" clamp={node.clamp} inputs={ins}")
    elif node.type == "VALTORGB":
        cr = node.color_ramp
        stops = [(round(element.position, 6),
                  tuple(round(value, 6) for value in element.color))
                 for element in cr.elements]
        head += f" mode={cr.color_mode} interp={cr.interpolation} stops={stops}"
    elif node.type == "MIX":
        head += (f" data_type={node.data_type} blend={node.blend_type}"
                 f" clamp_factor={node.clamp_factor} clamp_result={node.clamp_result}")
    elif node.type == "DISPLACEMENT":
        head += (f" space={node.space}"
                 f" midlevel={node.inputs['Midlevel'].default_value:.8f}"
                 f" scale={node.inputs['Scale'].default_value:.10f}")
    elif node.type == "RGB":
        col = node.outputs[0].default_value
        head += f" rgba=({col[0]:.6f}, {col[1]:.6f}, {col[2]:.6f}, {col[3]:.3f})"
    elif node.type == "BSDF_PRINCIPLED":
        vals = {input_socket.name: round(input_socket.default_value, 4)
                for input_socket in node.inputs
                if input_socket.type == "VALUE" and not input_socket.is_linked
                and input_socket.name in ("Metallic", "Roughness", "IOR", "Alpha")}
        head += f" {vals}"
    p(head)

p("== links ==")
for link in nt.links:
    p(f"  [{link.from_node.name}].{link.from_socket.name}"
      f" -> [{link.to_node.name}].{link.to_socket.name}")

p("== ramp evaluation ==")
for node in sorted(nt.nodes, key=lambda node: node.name):
    if node.type != "VALTORGB":
        continue
    cr = node.color_ramp
    p(f"[{node.name}] n_elements={len(cr.elements)}")
    for sample_position in RAMP_SAMPLES:
        col = cr.evaluate(sample_position)
        p(f"  f({sample_position:5.3f}) = ({col[0]:.4f}, {col[1]:.4f}, {col[2]:.4f})")

p("== images ==")
for img in bpy.data.images:
    if img.users and img.filepath:
        p(f"[{img.name}] filepath={img.filepath!r} size={tuple(img.size)}"
          f" colorspace={img.colorspace_settings.name}")
