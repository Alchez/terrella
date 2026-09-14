"""What a body's surface is painted with.

Both rigs read this package and neither owns it, which is why it is a package rather than a folder
inside one of them. The tile lane imports nearly all of it; the hero's Blender scene imports the
palette. Nothing here may import `pipeline/render/`: the dependency runs one way, upward, a cycle
is the signal that a module has been placed on the wrong side of the seam, and a test fails on one.

Two kinds of thing live here: surface layers, painted over the heightfield, each a `layers.Layer`
that a body either declares or does not (snow, sea ice, lake bathymetry, salt flats, the Martian
polar ices); and the palette, the hypsometric ramps the rest is coloured with. Cycles lights every
tile and every hero and casts its own shadows, so `cast_shadow` is arithmetic that sizes a block's
context and nothing here shades an image.

`palette` is also the bridge between two interpreters. It is numpy-only on purpose, so Blender's
bundled Python, which cannot import this project's virtual environment, reads the same look constants
the tile cut does instead of transcribing them.
"""
