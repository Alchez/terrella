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
- **`rig_recipe` is DERIVED, not enumerated**: `dataclasses.asdict(RIG)` plus the texture table plus
  the look. A constant added to `Rig` is in the recipe with nothing to remember.
  - **And what it costs is the whole planet.** Moving one value into `Rig` changes the recipe's text,
    so `start_generation` clears every marker and the body re-renders end to end, plus a re-cut, an
    upload and a Worker deploy. PROCESS.md holds the figure.
  - **Never assume a re-render is already owed.** Diff the on-disk sidecar against `params()` first.
    Equal means the next look change buys a whole pass on its own, so batch look changes rather than
    landing them one at a time.
  - **What is spelled INLINE in the builder is invisible to all of this**, and is pinned instead by
    `TestTheBuilderSpellsNoLookValueWhereTheRecipeCannotSeeIt`, which enumerates every such value.
    Editing one of those is a red test, not a restage: that is a tripwire and not a fix.
  - It used to be a hand-written list policed by a scan for this module's ALL-CAPS names, and that
    scan was blind by construction to a value spelled inline in a function body. Three such values
    shipped. **Do not re-add the scan**: it is the mechanism the derivation replaced.
  - **Field names ARE recipe keys**, so renaming one restages every rendered block.
- **The stage directory is the RUNNER'S and is threaded, never re-derived.** `run` takes `work`,
  `render_block` carries it and `prep_block.cut` reads from it; `relief_scan.work_dir` is the one
  owner of the name, and `tests/test_paths.py` refuses a second spelling of any stage.
  - The prep used to resolve the body's default itself, so `--work` moved every check a run made
    and none of the pixels it cut: inputs validated in one store, blocks planned from its relief
    scan, freshness stamped against it, and the default planet rendered into the mosaic and marked.
  - **A redirect that reaches only some readers has no symptom**, because both directories hold a
    complete openable planet. Adding a raster read here means threading `work` to it.
- **Every image node is built by `make_texture` from a `TextureSpec`**, and that is the only place
  one is configured. An interpolation or extension spelled at a call site is a look decision no
  recipe can see; `test_no_pixel_moving_value_is_spelled_inline_in_the_builder` fails on it.
  - The table is recorded WHOLE rather than per look: the optional textures are declined by a body's
    planet seam, not by its look, so a planet that gained one would otherwise restage nothing.
  - **So WHICH textures a directory loads is free to change and WHAT THE TABLE CONTAINS is not**, and
    that asymmetry is what let the rig learn to render a body with no inland water for nothing.
    `textures_for` is a filter over the recorded table, so its rule is invisible to the recipe.
  - **NO NODE NAME REACHES THE RECIPE, so renaming one is free on every tier.** The table is keyed
    into the recipe by `filename` and the `name` field is excluded, because a consistent rename
    renders byte-identically; it used to ride in whole and put a planet re-render behind a change
    that moved nothing. The exclusion is one NAMED field, so a field added to `TextureSpec` later
    is still recorded. `TestNoNodeCarriesBlendersAutoName` keeps names off Blender's `.00N`, and
    `TestRenamingANodeDoesNotRestageThePlanet` holds both directions of the exclusion.
  - **NOTHING COMPARES THE BUILT GRAPH AGAINST A HAND-BUILT BASELINE ANY MORE**, so creation order
    and node names answer only to the reader and to the arm probes that reach into the built graph.
    The hand-built origin scene is out of version control and lives in history alone
    (`git show 3e35eb6:blender/india_hero_handbuilt_phase0.blend`): it diverges on the view
    transform, the world colour and the fill sun, and a single file cannot track a graph whose
    shape depends on what the prep declared. What survives is `scene_dump`'s other use, diffing
    two dumps across a change, which needs no baseline at all.
- **The fold's law is a third entry, through `layer_producers.white_law`.** Which of `WHITE_UNION`
  and `WHITE_EXCLUSIONS` a layer sits in decides whether its raster adds white or removes it, and no
  producer's recipe can carry that: `producers_for` walks `layers.warped_for(vocabulary)`, so a
  producer is recorded whichever half its layer joins, and `glaciers` and `antarctic_rock` grade
  nothing per window.
- **Heroes do not restage.** `rig_recipe`'s only reader is `block_render.params`; the hero path
  shells into `scene_build` without one.

So a change that moves pixels but reaches none of `Rig`, the texture table, the fold's law or a
context is **silently invisible to freshness**. Put it in the structure.

## A per-block parameter that differs across a shared edge does NOT become a seam

`context_px` is chosen per block from that block's own haloed relief, so two adjacent blocks can get
different contexts and hence different `SPAN_PX`. That much is true. **Everything that used to be
written here about what it costs was wrong, and both halves failed for different reasons.**

- **"Hence a different fitted base grid" is false.** `base_patches` is `ceil(span / 2**12)` and
  takes the single value **2** across every one of Earth's 1,024 blocks, so it cannot discriminate
  between any pair of neighbours. Guarded by
  `test_the_base_grid_cannot_discriminate_between_neighbouring_blocks`.
- **"Widening the quantum is the lever" is REJECTED, twice, on two different pairs.** On the
  worst-disagreeing pair on Earth the join sits inside the distribution of the same terrain's own
  adjacent-column steps, and matching the rims recovers a small fraction of one DN. An earlier arm
  that forced every context equal found the same, marginally worse rather than better.
- **The asymmetry is why it is closed rather than unproven**: a coarser quantum can only round
  contexts up, and while the plane costs no render time, `prep_block.cut` runs inside
  `render_block`'s own clock and scales superlinearly with plane area. Every coarser value is a
  pass-time cost buying an invisible improvement.

**The transferable part is the oracle, not the verdict.** A join is visible because it is *coherent*
along a straight line, so a raw difference cannot settle it: terrain routinely differs more across
one pixel than a seam does. Compare the join's signed mean against the distribution of signed means
over the render's own interior column pairs; that is the same terrain measuring itself with no
boundary present, it needs no extra render, and it is what turns "there is a difference" into "there
is or is not a line".

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
