"""What a body's surface is painted with, and the law that lights it.

BOTH RIGS READ THIS PACKAGE AND NEITHER OWNS IT, which is why it is a package rather than a folder
inside one of them. The tile composite imports nearly all of it; the hero's Blender scene imports the
palette. Nothing here may import from `pipeline/render/`: the dependency runs one way, upward, and a
cycle is the signal that a module has been placed on the wrong side of the seam.

Two kinds of thing live here. SURFACE LAYERS are what gets painted over the heightfield, each one a
`layers.Layer` that a body either declares or does not: snow, sea ice, lake bathymetry, the Martian
polar ices. THE SHADING LAW is how the result is lit: the hypsometric palette, the per-row hillshade
that keeps a Web Mercator grid honest about latitude, cast shadows, sky-view factor.

`palette` is also the bridge between two interpreters. It is numpy-only on purpose, so Blender's
bundled Python, which cannot import this project's virtual environment, reads the same look constants
the tile cut does instead of transcribing them.
"""
