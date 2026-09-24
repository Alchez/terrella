---
name: blender-rig
description: Working with Blender for Terrella's relief renders. Load when driving the Blender GUI, writing or changing bpy code in the render rig, or diagnosing an OptiX or CUDA failure. Carries the 5.1.2 UI posture, the shader gotchas that produce plausible wrong output rather than an error, the crash recipe, and how to read how dense a mesh Cycles diced.
---

# Blender, for this project

Local Blender is **5.1.2**, tarball at `~/software/blender-5.1.2-linux-x64/blender`, not on PATH. Blender's bundled Python is a separate interpreter from the uv venv, so a bpy script cannot import this project's packages. That is why `scene_build.py` takes a body **slug** and plain numbers from `frame.json` rather than a `Body`, and why all geographic maths happens upstream in Python.

**Blender's bundled Python does carry numpy, OpenImageIO and PyOpenColorIO**, so a bpy script can read its own multilayer EXR and apply the scene's view transform in-process, through the OCIO config under `bpy.utils.resource_path('LOCAL')`, `datafiles/colormanagement/config.ocio`. In 5.1 a multilayer EXR needs `image_settings.media_type = 'MULTI_LAYER_IMAGE'` before `file_format = 'OPEN_EXR_MULTILAYER'`; setting the format while `media_type` is still `IMAGE` raises.

**5.2.1 is also unpacked, at `~/software/blender-5.2.1-linux-x64/`, and is NOT what production runs.** `paths.BLENDER` names 5.1.2 and `MAPS_BLENDER` overrides it, which is how an A/B runs a second binary without a code change.

**The rig never pitches its camera, and what that does and does not imply is easy to get backwards.** `build_camera` sets `camera_type` `ORTHO` and no rotation; grep `rotation_euler` across `pipeline/` and the only hits are the sun and the fill. So every hero and every block is baked straight down.

- **A pitched frame is a fair stand-in for a HERO.** Pitching the hero camera is a live proposal, so a pitched render is the thing being evaluated rather than an error. Say which pitch and exaggeration it used, because both are undecided and a value solved at one does not transfer to another.
- **A pitched frame is NOT a stand-in for a TILE.** A tile's shading is baked straight down under a fixed north-west sun, then draped as a `raster` source over a mesh the browser displaces from an independent `raster-dem` pyramid (`terrainSource.ts` states the split). A visitor pitching the globe re-projects the geometry and not the baked shadows, which a pitched Blender render does re-project.
- **Before offering any frame as a comparison, say which rig and camera produced it and what it is standing in for.** A round of look frames was once sent as "what the tiles do today" at a pitch and an exaggeration no tile uses.

**`Body.baked_exaggeration` is NOT what the globe displaces at, and a frame rendered at it is not a picture of the globe.** The browser ramps terrain exaggeration down with zoom in `web/src/lib/terrainSource.ts`: `rampedExaggeration` holds the baked value to `TERRAIN_RAMP_START_ZOOM` and decays it geometrically to `DEFAULT_TERRAIN_RAMP_FLOOR` at `TERRAIN_RAMP_END_ZOOM`. Read those three constants and compute rather than quoting a remembered figure.

- **Heroes and the baked tile shading DO use the flat baked value**, since a hero is one image and `cut_tiles` downsamples one mosaic to every zoom. So the mismatch is real and one-sided: at depth the shading is lit as if the baked exaggeration while the mesh is displaced at a fraction of it.
- **The ramp exists to remove needles and its own derivation says so**, naming the zoom where an earlier floor let them back in. Proposing a needle fix without reading it re-opens a solved problem: that has now happened twice, and the archive's entry about labelling a flat baked value "ratified" was written the first time.

**TWO THINGS BITE ON EVERY VERSION CHANGE, AND NEITHER RAISES.**

- **A Blender default the rig does not pin becomes a look change.** `cycles.sampling_pattern` defaults `TABULATED_SOBOL` on 5.1 and `AUTOMATIC` on 5.2, and unpinned it moved a block by 1.0973 DN against a 0.0363 DN floor and cost 9% more time. It is pinned in `Rig` now, and `test_every_rig_field_is_actually_read_by_the_builder` covers the field being applied. When a version moves, diff the built scene's state, not the property list: a property present in both can still arrive with a different value.
- **A new version has no preferences directory, so the GPU silently is not used.** Preferences live per version in `~/.config/blender/<version>/`. `select_compute_device` now derives the backend per run and raises rather than falling back, because the CPU render is correct and ~7x slower and no gate can see it. To drive a version interactively without touching the real config, point `BLENDER_USER_RESOURCES` at a scratch dir.

## GUI sessions

- Assume no prior Blender experience. Give exact click paths, introduce UI vocabulary as it is used, and verify state with screenshots rather than assuming it.
- Claude's Blender UI knowledge is 4.x-era while this box runs 5.1.2. Give 5.1.2 paths, and where uncertain say so and point at node search rather than guessing a menu location.
- Render headless (`blender -b`). The GUI OOMs at 8K.

## Shader gotchas, all proven in 5.1.2

Every one of these produces plausible-looking wrong output rather than an error, which is what makes them worth carrying rather than rediscovering.

- **8-bit images are divided by 255 on load.** Export masks as 0/255, and set Non-Color so no sRGB transform is applied on top.
- **Map Range with reversed ranges is undefined.** Use Math Multiply plus Clamp instead.
- **ColorRamp stops re-sort by position**, so never address one by index. The bpy edition of this is documented where it bites, in `scene_build.make_ramp`: `elements.new()` and position writes both re-sort the collection and invalidate any element reference held across the mutation.
- **`ShaderNodeMath` defaults to ADD with `use_clamp` off.** Both need setting explicitly; a silently clamped factor is correct near 1.0 and wrong at the extremes.
- **Blender's blackbody stops at 12,000 K, in the Blackbody node and in a light's own temperature field alike.** Every temperature from 12,000 K up returns 12,000 K's colour exactly, so a hotter light renders as 12,000 K and raises nothing. Below that both agree with the CIE Planckian locus within 0.2%; a hotter colour needs an explicit RGB computed from the locus.
- **"Displacement and Bump" replaces the mesh's shading normal rather than adding to it.** Cycles rebuilds each normal from the displacement sampled at the shading point and one ray differential away, on the undisplaced surface, so nothing is counted twice, and on terrain the mesh already resolves it changes nothing. A new material is "Bump Only" until told otherwise, which drops the geometry and every shadow.
  - **Its strength is fixed at 1 and no Blender property reaches it.** The kernel ends `normalize(strength * bumped + (1 - strength) * mesh)`, and `bump_from_displacement` builds that node with distance 1 and the default strength. Dialling it means building the bump in the shader: either mix the bumped surface with one shaded off the per-facet normal, whose travel is unknown at one facet per pixel, or drive an explicit bump node, which counts the mesh's own slope twice unless the height is high-passed first.
  - **It darkens wherever fine relief exists**, since facets turned from a low sun lose more than facets turned toward it gain. The loss is roughly a fixed number of DN, so it is a far larger share of ground that was already shaded, which is what reads as valleys deepening.
- **A Transparent BSDF over displaced terrain runs out of transparent bounces**, and the rig leaves `scene.cycles.transparent_max_bounces` at Blender's default of 8. A ray grazing several hidden peaks stops at the ninth surface, which renders black and casts a shadow, so a cut-out shows its neighbours' mountains as dark ghosts. Raise it for any render that hides terrain with transparency: 256 cleared a cut-out at 7×.
- **`is` on any RNA reference is False even for the same datablock**, because Blender returns a fresh Python wrapper on every access: `link.to_node is node` and `link.to_socket is node.inputs[0]` never match, so compare `.name`. A probe that unlinks a socket this way cuts nothing, the socket keeps its link, the default it then writes is ignored because a linked socket has no default, and the render is production under a different filename. Assert the count of links you CUT, never the count of nodes you found.

## When a render dies

`OPTIX_ERROR_UNKNOWN` at context creation is usually not a driver fault. Check `journalctl -k` for NVRM **Xid** lines. If the Xid names a Blender pid, the driver is fine and the CUDA context is dead: restart Blender to clear it.

Render heavy jobs one at a time under the project's cgroup scope. A hook enforces this, and the category that matters is "touches a full-planet raster" rather than "is a pipeline stage".

Two settings turn an ordinary scene into an OOM, each measured on Saint Lucia's grid against a normal render's 7.5 GB:

- **Any emission on the terrain material makes every diced triangle a light**, and Cycles builds sampling data for all of them: a mask rendered through emission died past 12 GB, and the same render with `material.cycles.emission_sampling = "NONE"` peaked at 5.3 GB. Set it whenever emission is used to photograph a mask through the camera.
- **`max_subdivisions` above the rig's 12 lets the whole view dice at the full-size rate, and a render border does not limit it**: a full-size crop at 12 peaked at 6.7 GB and the same crop at 14 died past 12 GB. The cap is what bounds a hero's mesh, so raising it for a sharper crop measures a mesh no hero builds.

Two more set a floor that splitting a render into camera pieces does not lower:

- **Blender holds every image as four channels**, so a single-band float heightfield costs 16 bytes a pixel whatever its file says (`image.channels` reads 4). A 940-megapixel heightfield put a render of a 33 × 35 px window at 15.5 GB, because every piece carries every image whole. Cut the plane and its rasters to the ground the camera can see before reaching for more pieces. A 16-bit PNG loads as floats too, and the GPU holds the same 16 bytes: a frame-sized 16-bit mask left no room for a hero's acceleration structure where the same mask at 8 bits fitted, so write a mask at 8 bits whenever 8 bits carry it.
- **Steep displacement costs GPU memory in the acceleration structure.** The same Finland frame rendered in 2 × 2 pieces at 15× failed to build its OptiX acceleration structure at 44×, with host memory well under the cap, and 3 × 3 pieces fitted. The error reads "System is out of GPU memory", not a host OOM.

## How dense a mesh Cycles actually built

Nothing in bpy reports the diced mesh. Run Blender with `--log cycles --log-level debug` and read the `Buffer allocate: tri_verts` line: its bytes scale with the vertices Cycles made, off-screen dicing included, so two setups compare by bytes per pixel in view. Read it before trusting that a changed camera or dicing rate changed only what you meant: a camera narrowed onto a window meshes that window more densely than the full block's camera does.
