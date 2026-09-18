---
name: block-ab
description: Rendering one tile block twice, from the shipped inputs and from altered ones, to see whether a change to heights, masks or a layer shows. Load when asked whether a data or pipeline change is visible, to A/B a block or a cap frame, to check whether a frame on disk matches today's code before re-stamping a recipe, to price which blocks a pass would actually move, or to render a before and after for a look call. Carries how to alter one input on the planet grid without touching the store, how to render an old commit's code, and the controls without which a difference means nothing.
---

# A/B one tile block

`block_render --help` owns the flags: `--only rNNcNN` picks the block, `--mosaic` sends the raster and every sidecar beside a scratch file, and `--work` points the inputs at another directory. What follows is what the help cannot say.

## Build the altered arm on the planet grid

- **A scratch work directory holds a symlink to every input the block reads**, `planet_warp`'s three rasters, each of `layers.warped_for(layers.BLOCK_LAYERS)`, `relief_cells.tif` and their `.done` markers, with the one input under test replaced.
- **The replacement must keep the planet's grid, so lay a patch over the real raster rather than cutting a small one.** Warp only the block's cut window plus a margin, with the planet warp's own `-tr`, `-tap` and resampling and an explicit `-te`, then `gdalbuildvrt -write_absolute_path` the real raster and the patch, patch last, into a file carrying the real name. GDAL opens a VRT by its content, whatever the extension.
- **Prove the patch before rendering**: the same windowed warp from the unaltered source must match the real raster in that window, or the A/B measures the warp as well as the change.
- **`--work` does not yet reach the relief scan** (FUTURE, *`block_render --work` still stops short of the relief scan*), so the live store's relief cache must be fresh and the scratch directory must link it.

## Controls, or the difference means nothing

- **Render the unaltered arm twice.** Cycles is not bit-deterministic, and the spread between those two is the floor for one scene rendered twice.
- **A change that moves geometry needs a second seed as its floor instead**, the mesh, the heights or the exaggeration: it moves where every ray lands, so it decorrelates the noise across the whole frame as a new seed does. Set `scene.cycles.seed` from a `render_pre` handler and print it back. On the Himalaya block a seed alone moves the mean 1.6 DN and 19% of pixels past 2, so read such a change in its tail.
- **Diff where the input did not change, against a pair that changed as much.** Changing a mask's content lifts the difference across the whole frame above that floor, with a signed mean of zero and no fall-off with distance (measured once, a salt mask on one Earth block: 0.15 DN mean for one scene twice, 0.32 to 0.35 with the mask changed, at most 4 DN 50 km away), so two altered arms against each other are the far-field control. A leak shows as a signed mean or as a difference that decays with distance; the change's own edge reaches about 24 px.
- **Diff each arm's prep directory against the base: exactly the files the change should touch differ.** A layer raster that is absent, a dangling link included, reads as no layer rather than an error (`test_a_declared_layer_whose_raster_is_absent_is_read_as_ABSENT_not_as_an_error`), so an arm whose input never arrived renders as the base with every recipe matching.
- **The three recipes beside the scratch mosaics must be identical.**
- **Read success from the per-block `[1/1] rNNcNN ... s` line, never the exit code**, which is 0 when a block fails.
- **Snapshot the store's mtimes and sizes before the first render and diff after the last.** It is the proof that nothing shipping moved.

## A block against the live planet

For "does the shipped planet still match today's code", and for "which blocks would a pass actually move", which is what decides whether a pass can be a partial one.

- **The data half of that second question needs no render at all.** `block_render.run` names the blocks it owes before it renders any, from each block's own digest, and `block_freshness.refresh` with `block_digest` answers it out of process against a store it only reads. Reach for a render for the other half, whether today's build reproduces the planet at all, which no file can carry.
- **A partial run already renders a sample of what it skips** and stops on a disagreement, so what follows is how to ask that question by hand, on blocks of your own choosing, or against an arm.
- **No flags and no scratch work directory**: `prep_block.cut(body, block, scratch_dir, work=<the store's>)`, then `block_render.blender_command`, then `block_render.cropped(png, block)` against `planet_rgb.tif` read at `block.delivered_window`. The store is read and never written, and the mtime snapshot above is the proof.
- **Pick the blocks by what each one holds, never at random or by convenience.** A change that moves only the polar rows is invisible to every mid-latitude block, and the blocks nearest a previous arc are all mid-latitude. Cover both polar rows, ice, ocean, desert, mountain, forest and lakes.
- **Name a cause by putting the old value back, in-process, and rendering the same block again.** Reproducing the live pixels names the cause; a difference that merely looks like the suspect leaves it open. `prep_block.ROW_EDGE_MODE` set to `"constant"`, the fill its block row was rendered under, is the worked case.
- **The floors this has measured on blocks**: one block rendered twice sits at 1 DN on p99 and 2 at worst, and ten blocks rendered weeks after the mosaic sit at 1 DN on p99, mean 0.10 to 0.16, with no pixel above 2 DN. A block that differs by more than that has a cause worth naming.

## A cap frame, or the code that rendered one

For the question "does a frame on disk match what today's code renders", which decides whether a recipe that moved only in format can be re-stamped rather than re-rendered.

- **A cap has no `--work`, so redirect in-process.** Every writer calls `cap_render.cap_work_dir` at call time, so replacing that function in a scratch script sends the AEQD warps, the render directory and the frames to scratch while the inputs still come from the store. Create `cap_raytrace.frames_dir(grid)` first: `render` makes it and `render_frame` assumes it. Snapshot the store's cap folder before and after, as above.
- **Compare the prepped inputs before any frame.** The images, `frame.json` and `render_inputs.json` against the store's render directory: when all match, only the builder is left to differ.
- **To render with the code that made a frame, export its commit, never check it out**: `git archive <commit> | tar -x -C <scratch>`, then run that tree's `scene_build.py` with the arguments its own `blender_command` built, against today's render directory once its inputs are shown identical. Take the last commit before the frame's mtime that holds the code, and say so if none does.
- **`scene_dump` both built scenes and map node renames before diffing**, or the renames drown the diff.
- **The floors this has measured**: two renders of one code differ at 1 DN on about 0.008% of a 4096² frame's values, and a change in node names or creation order alone moved two pixels by up to 3 DN.

## A lane difference, rather than a data one

For "what does one of the flags the hero and tile lanes disagree on actually cost", which is a look question rather than a freshness one.

- **Prep the block once and render it twice, swapping only the flag.** `block_render.blender_command` hardcodes `BLOCK_DENOISE_DEVICE` and `BLOCK_BASE_GRID`, so an arm rebuilds the same argument list with one value changed rather than calling it.
- **Read Blender's own `BASE_GRID` / `DENOISE_DEVICE` line back from each run.** Without it two arms that silently took the same setting are indistinguishable from a flag that changes nothing.
- **Choose the block for what the flag acts on.** Dicing is carried by relief, so flat ground cannot show a base-grid difference at all whatever the numbers say.
- **A block is the mild case for anything plane-width dependent.** The single quad caps at 2**12 micropolygons along the whole edge, so a 4,864 px block plane sits at 1.19 px each and a 7,680 px hero at 1.875: whatever a block measures, a hero loses more.
- **Measured for `--base-grid`** on the Himalaya block: the mean (1.95 DN against a seed's 1.61) and the share over 2 DN (23% against 19%) are almost all noise, and the signal is the tail, 1.6% of pixels past 10 DN against a seed's 0.09%. Time is not the constraint (67.4 s against 65.0); VRAM is.

## A rig setting, changed in-process

For a look round on a light or a surface colour: a Blender-side script, run as `blender -b --python`, changes one thing and then calls `scene_build.main()` with production's own arguments, so every other setting is the rig's.

- **A light or the seed changes in a `render_pre` handler**, which runs before Cycles reads the scene. Print the value back from inside the handler: an arm whose change never landed renders as the base with every recipe matching.
- **Hold a coloured light to the luminance of the white it replaces**, or the arm moves brightness and hue together and the eye cannot say which it judged.
- **A surface colour is read at build time through a module-level seam**, so replace it before `main()`: `scene_build.declared_albedo` for snow, salt and sea ice, `palette.LOOK_BY_BODY[body]` for the land and sea ramps, and `scene_build.RIG` through `dataclasses.replace` for lakes and river water. Each is looked up when called, which is what lets the replacement reach the build.
- **Measure by surface with the prep's own masks**, cut to the delivered window from the centre of the plane-sized mask. A brightness quartile mixes surfaces, and the look calls come back split by surface.

## A projection arm on a hero

- **`render_prep` hardcodes `dst_crs = aea_crs(args.frame)`**, so a projection arm replaces that function in a scratch script, exactly as the cap arm replaces `cap_work_dir`.
- **Filling a far-north frame needs no re-fuse.** The empty share is the per-country fuse stopping at its lon/lat box; `planet_heightfield.vrt` is global at 10 arcsec, which is finer than Greenland, Canada and Russia are rendered at. Only the small frames need their own fuse.

## Hand over frames, not a verdict

Cut the delivered window from each arm with `gdal_translate -srcwin` into separate full-frame images, one pair at 1:1 around the spot in question, plus the difference and the noise floor at one shared amplification. Whether a difference shows is the maintainer's call by eye.
