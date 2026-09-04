---
name: blender-rig
description: Working with Blender for Terrella's relief renders. Load when driving the Blender GUI, writing or changing bpy code in the render rig, or diagnosing an OptiX or CUDA failure. Carries the 5.1.2 UI posture, the shader gotchas that produce plausible wrong output rather than an error, and the crash recipe.
---

# Blender, for this project

Local Blender is **5.1.2**, tarball at `~/software/blender-5.1.2-linux-x64/blender`, not on PATH.
Blender's bundled Python is a separate interpreter from the uv venv, so a bpy script cannot import
this project's packages. That is why `scene_build.py` takes a body **slug** and plain numbers from
`frame.json` rather than a `Body`, and why all geographic maths happens upstream in Python.

**5.2.1 is also unpacked, at `~/software/blender-5.2.1-linux-x64/`, and is NOT what production
runs.** `paths.BLENDER` names 5.1.2 and `MAPS_BLENDER` overrides it, which is how an A/B runs a
second binary without a code change.

**TWO THINGS BITE ON EVERY VERSION CHANGE, AND NEITHER RAISES.**

- **A Blender default the rig does not pin becomes a look change.** `cycles.sampling_pattern`
  defaults `TABULATED_SOBOL` on 5.1 and `AUTOMATIC` on 5.2, and unpinned it moved a block by 1.0973
  DN against a 0.0363 DN floor and cost 9% more time. It is pinned in `Rig` now, and
  `test_every_rig_field_is_actually_read_by_the_builder` covers the field being applied. When a
  version moves, diff the built scene's state, not the property list: a property present in both can
  still arrive with a different value.
- **A new version has no preferences directory, so the GPU silently is not used.** Preferences live
  per version in `~/.config/blender/<version>/`. `select_compute_device` now derives the backend per
  run and raises rather than falling back, because the CPU render is correct and ~7x slower and no
  gate can see it. To drive a version interactively without touching the real config, point
  `BLENDER_USER_RESOURCES` at a scratch dir.

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
- **`is` on any RNA reference is False even for the same datablock**, because Blender returns a fresh Python wrapper on every access: `link.to_node is node` and `link.to_socket is node.inputs[0]` never match, so compare `.name`. A probe that unlinks a socket this way cuts nothing, the socket keeps its link, the default it then writes is ignored because a linked socket has no default, and the render is production under a different filename. Assert the count of links you CUT, never the count of nodes you found.

## When a render dies

`OPTIX_ERROR_UNKNOWN` at context creation is usually not a driver fault. Check `journalctl -k` for
NVRM **Xid** lines. If the Xid names a Blender pid, the driver is fine and the CUDA context is dead:
restart Blender to clear it.

Render heavy jobs one at a time under the project's cgroup scope. A hook enforces this, and the
category that matters is "touches a full-planet raster" rather than "is a pipeline stage".
