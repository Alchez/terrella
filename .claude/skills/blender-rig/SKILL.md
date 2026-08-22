---
name: blender-rig
description: Working with Blender for Terrella's relief renders. Load when driving the Blender GUI, writing or changing bpy code in the render rig, or diagnosing an OptiX or CUDA failure. Carries the 5.1.2 UI posture, the shader gotchas that produce plausible wrong output rather than an error, and the crash recipe.
---

# Blender, for this project

Local Blender is **5.1.2**, tarball at `~/software/blender-5.1.2-linux-x64/blender`, not on PATH.
Blender's bundled Python is a separate interpreter from the uv venv, so a bpy script cannot import
this project's packages. That is why `scene_build.py` takes a body **slug** and plain numbers from
`frame.json` rather than a `Body`, and why all geographic maths happens upstream in Python.

## GUI sessions

- Assume no prior Blender experience. Give exact click paths, introduce UI vocabulary as it is used, and verify state with screenshots rather than assuming it.
- Claude's Blender UI knowledge is 4.x-era while this box runs 5.1.2. Give 5.1.2 paths, and where uncertain say so and point at node search rather than guessing a menu location.
- Render headless (`blender -b`). The GUI OOMs at 8K.

## Shader gotchas, all proven in 5.1.2

Every one of these produces plausible-looking wrong output rather than an error, which is what makes
them worth carrying rather than rediscovering.

- **8-bit images are divided by 255 on load.** Export masks as 0/255, and set Non-Color so no sRGB transform is applied on top.
- **Map Range with reversed ranges is undefined.** Use Math Multiply plus Clamp instead.
- **ColorRamp stops re-sort by position**, so never address one by index. The bpy edition of this is documented where it bites, in `scene_build.make_ramp`: `elements.new()` and position writes both re-sort the collection and invalidate any element reference held across the mutation.
- **`ShaderNodeMath` defaults to ADD with `use_clamp` off.** Both need setting explicitly; a silently clamped factor is correct near 1.0 and wrong at the extremes.

## When a render dies

`OPTIX_ERROR_UNKNOWN` at context creation is usually not a driver fault. Check `journalctl -k` for
NVRM **Xid** lines. If the Xid names a Blender pid, the driver is fine and the CUDA context is dead:
restart Blender to clear it.

Render heavy jobs one at a time under the project's cgroup scope. A hook enforces this, and the
category that matters is "touches a full-planet raster" rather than "is a pipeline stage".
