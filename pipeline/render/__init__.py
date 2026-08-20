"""The hero rig: one country, one Blender scene, one high-resolution image.

What the look is made of lives in `pipeline/look/`, which this package reads and never writes back
to. What is here is the machinery around a single Cycles render: projecting a fused heightfield and
its masks into the scene's grid (`render_prep`), the two mask stages the material needs (`snow_mask`,
`lake_mask`), the scene itself (`scene_build`), and the exhaustive dump that verifies it
(`scene_dump`).

`scene_build` and `scene_dump` are the only modules in the pipeline that a DIFFERENT interpreter
runs: Blender's bundled Python, which cannot import this project's virtual environment or anything
installed into it. That boundary is enforced by test and by a type-check pass rather than by this
directory, and `look/palette.py` is the one module deliberately written to satisfy both.
"""
