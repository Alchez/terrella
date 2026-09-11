---
name: block-ab
description: Rendering one tile block twice, from the shipped inputs and from altered ones, to see whether a change to heights, masks or a layer shows. Load when asked whether a data or pipeline change is visible, to A/B a block, or to render a before and after for a look call. Carries how to alter one input on the planet grid without touching the store, and the controls without which a difference means nothing.
---

# A/B one tile block

`block_render --help` owns the flags: `--only rNNcNN` picks the block, `--mosaic` sends the raster and every sidecar beside a scratch file, and `--work` points the inputs at another directory. What follows is what the help cannot say.

## Build the altered arm on the planet grid

- **A scratch work directory holds a symlink to every input the block reads**, `planet_warp`'s three rasters, each of `layers.warped_for(layers.BLOCK_LAYERS)`, `relief_cells.tif` and their `.done` markers, with the one input under test replaced.
- **The replacement must keep the planet's grid, so lay a patch over the real raster rather than cutting a small one.** Warp only the block's cut window plus a margin, with the planet warp's own `-tr`, `-tap` and resampling and an explicit `-te`, then `gdalbuildvrt -write_absolute_path` the real raster and the patch, patch last, into a file carrying the real name. GDAL opens a VRT by its content, whatever the extension.
- **Prove the patch before rendering**: the same windowed warp from the unaltered source must match the real raster in that window, or the A/B measures the warp as well as the change.
- **`--work` does not yet reach the relief scan** (FUTURE, *`block_render --work` still stops short of the relief scan*), so the live store's relief cache must be fresh and the scratch directory must link it.

## Controls, or the difference means nothing

- **Render the unaltered arm twice.** Cycles is not bit-deterministic, and the spread between those two is the floor any real difference has to clear.
- **Diff where the input did not change.** Outside the altered footprint the two arms must differ only by that floor; a larger difference there means the arms differ in something besides the input.
- **The three recipes beside the scratch mosaics must be identical.**
- **Read success from the per-block `[1/1] rNNcNN ... s` line, never the exit code**, which is 0 when a block fails.
- **Snapshot the store's mtimes and sizes before the first render and diff after the last.** It is the proof that nothing shipping moved.

## Hand over frames, not a verdict

Cut the delivered window from each arm with `gdal_translate -srcwin` into separate full-frame images, one pair at 1:1 around the spot in question, plus the difference and the noise floor at one shared amplification. Whether a difference shows is the maintainer's call by eye.
