---
name: block-ab
description: Rendering one tile block twice, from the shipped inputs and from altered ones, to see whether a change to heights, masks or a layer shows. Load when asked whether a data or pipeline change is visible, to A/B a block or a cap frame, to check whether a frame on disk matches today's code before re-stamping a recipe, or to render a before and after for a look call. Carries how to alter one input on the planet grid without touching the store, how to render an old commit's code, and the controls without which a difference means nothing.
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
- **Diff where the input did not change, against a pair that changed as much.** Changing a mask's content lifts the difference across the whole frame above that floor, with a signed mean of zero and no fall-off with distance (measured once, a salt mask on one Earth block: 0.15 DN mean for one scene twice, 0.32 to 0.35 with the mask changed, at most 4 DN 50 km away), so two altered arms against each other are the far-field control. A leak shows as a signed mean or as a difference that decays with distance; the change's own edge reaches about 24 px.
- **Diff each arm's prep directory against the base: exactly the files the change should touch differ.** A layer raster that is absent, a dangling link included, reads as no layer rather than an error (`test_a_declared_layer_whose_raster_is_absent_is_read_as_ABSENT_not_as_an_error`), so an arm whose input never arrived renders as the base with every recipe matching.
- **The three recipes beside the scratch mosaics must be identical.**
- **Read success from the per-block `[1/1] rNNcNN ... s` line, never the exit code**, which is 0 when a block fails.
- **Snapshot the store's mtimes and sizes before the first render and diff after the last.** It is the proof that nothing shipping moved.

## A cap frame, or the code that rendered one

For the question "does a frame on disk match what today's code renders", which decides whether a recipe that moved only in format can be re-stamped rather than re-rendered.

- **A cap has no `--work`, so redirect in-process.** Every writer calls `cap_render.cap_work_dir` at call time, so replacing that function in a scratch script sends the AEQD warps, the render directory and the frames to scratch while the inputs still come from the store. Create `cap_raytrace.frames_dir(grid)` first: `render` makes it and `render_frame` assumes it. Snapshot the store's cap folder before and after, as above.
- **Compare the prepped inputs before any frame.** The images, `frame.json` and `render_inputs.json` against the store's render directory: when all match, only the builder is left to differ.
- **To render with the code that made a frame, export its commit, never check it out**: `git archive <commit> | tar -x -C <scratch>`, then run that tree's `scene_build.py` with the arguments its own `blender_command` built, against today's render directory once its inputs are shown identical. Take the last commit before the frame's mtime that holds the code, and say so if none does.
- **`scene_dump` both built scenes and map node renames before diffing**, or the renames drown the diff.
- **The floors this has measured**: two renders of one code differ at 1 DN on about 0.008% of a 4096² frame's values, and a change in node names or creation order alone moved two pixels by up to 3 DN.

## Hand over frames, not a verdict

Cut the delivered window from each arm with `gdal_translate -srcwin` into separate full-frame images, one pair at 1:1 around the spot in question, plus the difference and the noise floor at one shared amplification. Whether a difference shows is the maintainer's call by eye.
