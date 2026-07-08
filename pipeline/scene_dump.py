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


def p(*a):
    print(*a, flush=True)


RAMP_SAMPLES = (0.0, 0.02, 0.05, 0.075, 0.1, 0.15, 0.3, 0.4, 0.7, 1.0)

s = bpy.context.scene
r, c = s.render, s.cycles

p("== render ==")
p(f"engine={r.engine} res={r.resolution_x}x{r.resolution_y}@{r.resolution_percentage}%")
p(f"film_transparent={r.film_transparent}")
p(f"image: format={r.image_settings.file_format} mode={r.image_settings.color_mode}"
  f" depth={r.image_settings.color_depth} compression={r.image_settings.compression}")

p("== cycles ==")
p(f"device={c.device} samples={c.samples}")
p(f"adaptive={c.use_adaptive_sampling} adaptive_threshold={c.adaptive_threshold:.6f}"
  f" min_samples={c.adaptive_min_samples}")
p(f"denoise={c.use_denoising} denoiser={c.denoiser}"
  f" input={getattr(c, 'denoising_input_passes', 'n/a')}"
  f" prefilter={getattr(c, 'denoising_prefilter', 'n/a')}"
  f" quality={getattr(c, 'denoising_quality', 'n/a')}"
  f" gpu={getattr(c, 'denoising_use_gpu', 'n/a')}")
p(f"dicing_rate={c.dicing_rate} max_subdivisions={c.max_subdivisions}"
  f" offscreen_dicing_scale={c.offscreen_dicing_scale}")
p(f"bounces: total={c.max_bounces} diffuse={c.diffuse_bounces}"
  f" glossy={c.glossy_bounces} transmission={c.transmission_bounces}"
  f" volume={c.volume_bounces}")
p(f"clamp: direct={c.sample_clamp_direct} indirect={c.sample_clamp_indirect}")

p("== color management ==")
vs = s.view_settings
p(f"display_device={s.display_settings.display_device}"
  f" view_transform={vs.view_transform} look={vs.look}"
  f" exposure={vs.exposure} gamma={vs.gamma}"
  f" curves={vs.use_curve_mapping}")

p("== world ==")
w = s.world
if w and w.use_nodes:
    for n in w.node_tree.nodes:
        if n.type == "BACKGROUND":
            col = n.inputs["Color"].default_value
            p(f"background rgba=({col[0]:.6f}, {col[1]:.6f}, {col[2]:.6f},"
              f" {col[3]:.3f}) strength={n.inputs['Strength'].default_value}")

p("== objects ==")
for ob in s.objects:
    p(f"[{ob.name}] type={ob.type} loc=({ob.location.x:.6f}, {ob.location.y:.6f},"
      f" {ob.location.z:.6f}) rot=({ob.rotation_euler.x:.6f},"
      f" {ob.rotation_euler.y:.6f}, {ob.rotation_euler.z:.6f})"
      f" scale=({ob.scale.x:.6f}, {ob.scale.y:.6f}, {ob.scale.z:.6f})")
    if ob.type == "CAMERA":
        cam = ob.data
        p(f"  camera: type={cam.type} ortho_scale={cam.ortho_scale}"
          f" clip=({cam.clip_start}, {cam.clip_end}) sensor_fit={cam.sensor_fit}"
          f" shift=({cam.shift_x}, {cam.shift_y})"
          f" active={'YES' if s.camera == ob else 'no'}")
    if ob.type == "LIGHT":
        li = ob.data
        p(f"  light: type={li.type} energy={li.energy}"
          f" angle={getattr(li, 'angle', 0.0):.6f}"
          f" use_shadow={getattr(li, 'use_shadow', 'n/a')}"
          f" color=({li.color.r:.4f}, {li.color.g:.4f}, {li.color.b:.4f})")
    if ob.type == "MESH":
        p(f"  mesh: {len(ob.data.vertices)} verts, dims=({ob.dimensions.x:.6f},"
          f" {ob.dimensions.y:.6f}, {ob.dimensions.z:.6f})")
        for m in ob.modifiers:
            extra = ""
            if m.type == "SUBSURF":
                extra = (f" subdivision_type={m.subdivision_type}"
                         f" levels={m.levels} render_levels={m.render_levels}"
                         f" use_adaptive={getattr(m, 'use_adaptive_subdivision', 'n/a')}")
            p(f"  modifier [{m.name}] type={m.type}{extra}")
        for slot in ob.material_slots:
            p(f"  material slot: {slot.material.name if slot.material else None}")

p("== material graph ==")
mat = bpy.data.objects["Plane"].active_material
p(f"material={mat.name} displacement_method={mat.displacement_method}")
nt = mat.node_tree
for n in sorted(nt.nodes, key=lambda x: x.name):
    head = f"[{n.name}] label={n.label!r} type={n.type} mute={n.mute}"
    if n.type == "TEX_IMAGE":
        if n.image:
            head += (f" image={n.image.name}"
                     f" colorspace={n.image.colorspace_settings.name}"
                     f" interp={n.interpolation} extension={n.extension}")
        else:
            head += " image=None"
    elif n.type == "MAP_RANGE":
        ins = {i.name: round(i.default_value, 6) for i in n.inputs
               if i.type == "VALUE"}
        head += (f" data_type={n.data_type} interp={n.interpolation_type}"
                 f" clamp={n.clamp} inputs={ins}")
    elif n.type == "VALTORGB":
        cr = n.color_ramp
        stops = [(round(e.position, 6),
                  tuple(round(v, 6) for v in e.color)) for e in cr.elements]
        head += f" mode={cr.color_mode} interp={cr.interpolation} stops={stops}"
    elif n.type == "MIX":
        head += (f" data_type={n.data_type} blend={n.blend_type}"
                 f" clamp_factor={n.clamp_factor} clamp_result={n.clamp_result}")
    elif n.type == "DISPLACEMENT":
        head += (f" space={n.space}"
                 f" midlevel={n.inputs['Midlevel'].default_value:.8f}"
                 f" scale={n.inputs['Scale'].default_value:.10f}")
    elif n.type == "RGB":
        col = n.outputs[0].default_value
        head += f" rgba=({col[0]:.6f}, {col[1]:.6f}, {col[2]:.6f}, {col[3]:.3f})"
    elif n.type == "BSDF_PRINCIPLED":
        vals = {i.name: round(i.default_value, 4) for i in n.inputs
                if i.type == "VALUE" and not i.is_linked
                and i.name in ("Metallic", "Roughness", "IOR", "Alpha")}
        head += f" {vals}"
    p(head)

p("== links ==")
for l in nt.links:
    p(f"  [{l.from_node.name}].{l.from_socket.name}"
      f" -> [{l.to_node.name}].{l.to_socket.name}")

p("== ramp evaluation ==")
for n in sorted(nt.nodes, key=lambda x: x.name):
    if n.type != "VALTORGB":
        continue
    cr = n.color_ramp
    p(f"[{n.name}] n_elements={len(cr.elements)}")
    for x in RAMP_SAMPLES:
        col = cr.evaluate(x)
        p(f"  f({x:5.3f}) = ({col[0]:.4f}, {col[1]:.4f}, {col[2]:.4f})")

p("== images ==")
for img in bpy.data.images:
    if img.users and img.filepath:
        p(f"[{img.name}] filepath={img.filepath!r} size={tuple(img.size)}"
          f" colorspace={img.colorspace_settings.name}")
