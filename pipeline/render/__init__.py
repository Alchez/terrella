"""One relief scene: a directory of images and numbers in, one Cycles render out.

What the look is made of lives in `pipeline/look/`, which this package reads and never writes back
to. What is here is the machinery around a single Cycles render: the frame arithmetic that projects
a fused heightfield and its masks into the scene's grid (`render_prep`), the two mask stages the
material needs (`snow_mask`, `lake_mask`), the scene itself (`scene_build`), the exhaustive dump
that verifies it (`scene_dump`), the declaration of what a render directory holds (`render_seam`),
and the preps that fill one (`prep_block`, `prep_cap`).

THE UNIT THIS PACKAGE IS ORGANISED BY IS THE RENDER DIRECTORY, NOT THE HERO. It used to be the
hero, and that stopped being true when a second and third prep arrived: `render_prep` cuts a
country's Albers frame, `prep_block` a z8 EPSG:3857 block, `prep_cap` a polar disc in AEQD. All
three fill the same directory shape for the same `scene_build`, and the two that are not the hero's
are driven from `pipeline/tile/` — which is the crossing this package exists to make possible
rather than a layering violation.

`scene_build` and `scene_dump` are the only modules in the pipeline that a DIFFERENT interpreter
runs: Blender's bundled Python, which cannot import this project's virtual environment or anything
installed into it. That boundary is enforced by test and by a type-check pass rather than by this
directory, and `look/palette.py` is the one module deliberately written to satisfy both.
"""
