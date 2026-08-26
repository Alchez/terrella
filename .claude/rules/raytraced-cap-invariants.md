---
paths:
  - "pipeline/tile/cap_pass.py"
  - "pipeline/tile/cap_raytrace.py"
  - "pipeline/tile/cap_render.py"
  - "pipeline/render/prep_cap.py"
---

# The raytraced cap: what spans files, and what is silent when broken

The polar disc has two producers and the facts that keep them the same picture are spread across
five modules. None of these is visible from any single file, and none of them fails loudly.

## Four modules, and which one owns what

- **`cap_pass`** is the CLI, the freshness loop and `CAP_PRODUCERS`. It is the entry point:
  `python -m pipeline.tile.cap_pass --body earth`, invoked at the planet pass's tail.
- **`cap_render`** is the COMPOSITE arm plus everything both arms share — `CapGrid`, the warps,
  `azimuth_delta`, `_lonlat_grid`, `finish_disc`, `write_cap_rungs`, `cap_sources`, `cap_is_fresh`.
- **`cap_raytrace`** is the Cycles arm. It imports `cap_render`, which is why the registry cannot
  live there: a registry inside either arm is an import cycle. That is the whole reason `cap_pass`
  is a separate module rather than tidiness.
- **`prep_cap`** fills one render directory per pole. Its output is NOT an mtime dependency of the
  disc, so anything it decides has to reach `cap_raytrace.params` or it restages nothing.

## The arm is keyed on `planet_producer` and both halves ride in one record

A disc is built to match the tiles it feathers into, and the two producers of `planet_rgb` do not
agree on colour. `CapProducer` carries the render AND the recipe together because `cap_is_fresh`
asks them as one question — one sidecar per pole, compared against whichever arm is current. Two
registries could hold a pair that disagrees, and that is silent in the worst direction: a disc
painted by one arm and declared fresh under the other's recipe, forever.

**The raytrace recipe deliberately has no `planet_producer` key.** The composite's needs one because
a switch would otherwise leave its recipe identical across it. Here the switch changes which
function writes the sidecar at all, so both directions restage and `"producer"` says which side a
sidecar is on. Verified in production: the first raytraced run restaged without `--force`.

## The units: heights are GROUND metres and the grid is not

`edge_m` is map metres on `aeqd_radius_m`, the sphere PROJ forces every body onto. Heights are
ground metres on the body itself. **Both arms must divide by `bodies.ground_metres_per_aeqd_unit`** —
the composite in `_shade`'s z-factor, the raytraced one in the extent `prep_cap.write_frame` hands
`scene_numbers`. Skipping it renders a plausible disc at the wrong relief.

**Earth cannot show this class of defect**: its ratio is 1.0011, so the error is 0.11%. Mars's is
0.5331. Any per-body constant near 1 on the body you test leaves its whole arithmetic untested, and
the second body is the only instrument. The guard is a synthetic body whose two radii coincide,
because inverting the quotient leaves that case identical and every other case wrong.

## The ring: 28 frames a pole, derived, never assumed

A quadrant spans a quarter of the longitude circle and needs 7 of the 24 passes plus the upper
neighbour. **Which 7 is derived off `_lonlat_grid`, the same function the blend reads.** Which
quarter a given `(row, col)` holds depends on the AEQD convention and on the pole's `az_sign`, and
the two poles disagree about the second — a plan written from one pole's convention renders 28
correct-looking frames for the other, all of them the wrong half of the circle. It does not crash;
the blend's coverage check is what stops it, after the GPU has been spent.

The plan is a statement about LONGITUDES, so it does not move with the disc's resolution. That is
what lets tests plan a 256 px stand-in for an 8192 px disc.

## The echoes are a contract with `scene_build`, and they compare VALUES

`--sun-azimuth-delta` and `--tile` are invisible when lost: one renders the base bearing, the other
photographs the whole plane at a quadrant's resolution. Both succeed. `check_echoes` requires the
reported quadrant and delta to MATCH what was asked, not merely to be present — a `--tile` arriving
as a different pair renders, stitches, and lands under the name of the quadrant that was asked for.

**A frame is rendered to `.part.png` and renamed**, so existence is the completeness claim the
resume reads. A killed Blender leaves a non-empty partial PNG, which does not fail on the next run:
it blends garbage into the disc.

## What no gate can see

`check.sh` needs no GPU, no Blender and no store, so nothing in it looks at a rendered pixel. The
stitch was controlled once and the numbers are in HISTORY, *the cap edge goes to 82 and not 84*:
geometry correlation 0.99327 against a full-disc render, join at the 89.4th percentile of the
image's own column means, no cross at the four-tile corner. **Do not re-derive these; cite them.**
Whether a disc ships is a look ratification and belongs to the maintainer.
