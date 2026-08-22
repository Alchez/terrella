---
paths:
  - "pipeline/block_plan.py"
  - "pipeline/tile/block_render.py"
  - "pipeline/render/prep_block.py"
  - "pipeline/render/scene_build.py"
  - "pipeline/render/render_seam.py"
---

# The raytraced block: what is invariant, and what silently is not

Four things about this producer that are expensive to re-derive and silent when broken. Every one
of them cost a measurement to establish; none of them is visible from any single file here.

## The freshness chain has exactly one lever, and it is not a file

A rendered block is skipped by **marker existence alone** (`block_render.py`, `todo = [...]`). The
only thing that clears markers is `generation_is_current(markers, deps)` going false, and `deps` is
the params recipe plus the planet rasters. So:

- **Changing what `prep_block` writes does NOT restage a rendered block.** `raytrace_deps` tracks
  planet rasters, not the per-block prep directory. A new prep image reaches only blocks that were
  going to render anyway.
- **`params()` is the lever.** Inside it, two entries move for block-geometry work: `contexts`
  (`context_census`, the context law's *output*) and `rig` (`scene_build.rig_recipe`).
- **`rig_recipe` records this module's CAPITALS and nothing else**, enforced from the module's side
  by `test_every_module_constant_is_in_the_recipe`. A value spelled as a literal at its call site
  is a value a planet can be re-rendered without noticing — which the snow, lake-depth and sea-ice
  node names and interpolations still are.
- **Heroes do not restage.** `rig_recipe`'s only reader is `block_render.params`; the hero path
  shells into `scene_build` without one.

So a change that moves pixels but touches no capital and no context is **silently invisible to
freshness**. Give it a capital.

## A per-block parameter that differs across a shared edge becomes a seam

`context_px` is chosen per block from that block's own haloed relief, so two vertically adjacent
blocks can get different contexts, hence different `SPAN_PX`, hence a different fitted base grid.

**Measured**: three blocks whose `SPAN_PX` was unchanged between two renders are identical to
**0.0000 DN mean**; the one block whose `SPAN_PX` moved 4,992 → 5,120 shifted **+0.545 DN mean and
+0.68 DN in the rows on the join**, turning a ~0 DN join into ~1.2 DN. That is the same base-grid
sensitivity already recorded at ~1.4 DN mean.

`CONTEXT_QUANTUM_PX` exists to make neighbours share plane sizes, and this is the reason it matters
beyond allocator reuse. **Widening the quantum is the lever if joins need to get better**, and it
trades a little wasted plane for neighbours agreeing more often.

## The exaggeration law lives on the OCCLUDER, not on the block

Since `prep_block.row_scale` made the applied exaggeration uniform, shadow reach in pixels is set
by the *occluder's* latitude. Two consequences that look like details and are not:

- **Size context at the poleward plane edge, in both hemispheres.** "A 315-degree sun puts every
  occluder north" is true of the column component and false about the binding latitude: the
  occluder set is the north ring **plus the west ring**, and the west ring spans the block's own
  rows. A north-edge rule narrowed 306 of Earth's 1,024 blocks and 2-cycled on 7. REJECTED, not
  open. See `poleward_sizing_latitude`.
- **Under-context is silent on both sides.** There is no edge, no warning and no failing test; the
  shadow simply stops. So any change to the sizing law needs a census printing the **narrowing**
  direction as its own column, including when it is zero.

## The three widths are not interchangeable

`delivered` reaches the mosaic, `traced` is what Cycles path-traces, `plane` is heightfield the
camera never sees. Swapping plane for traced in the frame renders the context and every downstream
shape check still passes, because the crop is taken by offset. `rowscale.tif`'s height is the
**plane's**; taking `size_px` stretches the correction over the context and still writes a
plausible file.
