"""The names a render directory's images go by, and nothing about who wrote them.

At the top level because five packages read these spellings: `render/` fills a directory, `tile/`
raytraces a block out of one, `compose/` and `look/` read the finished masks, and `batch` drives the
run. `render/render_seam.py` is the other half, the declaration of what a stage actually emitted,
and it stays in the rig's package because only the rig reads it.

Stdlib only, and that is a hard constraint rather than a preference. `scene_build` runs inside
Blender's interpreter, which cannot import this project's virtual environment, which is also why the
rig takes a body slug and not a `Body`. So this module may not import `bodies`, `layers` or
`planet_seam`, and cannot answer any question that needs them. It records filenames, which is
exactly what both interpreters can agree about.
"""

#: The rig's four mandatory images. A directory missing one of these is not a partial scene.
HEIGHTFIELD = "heightfield.tif"
OCEANMASK = "oceanmask.png"
INLANDLAKE = "inlandlake.png"
RIVER = "river.png"

#: The three a prep may legitimately not write, being measurements of the region rather than of
#: the planet: a block with no snow in it, no lake bed in it, or no sea ice on its ocean. The ice
#: image is a continuous 0..1 alpha, already confined to ocean pixels by the prep that cut it.
SNOWMASK = "snowmask.png"
LAKEDEPTH = "lakedepth.tif"
SEAICE = "seaice.png"

#: The per-row Mercator correction, one pixel wide and as tall as the plane. Named beside the three
#: optional images above but unlike them in kind: those are absent when a region has no snow or no
#: lake bed to measure, where this is a property of the projection. So the block path always writes
#: one and the hero path, which is not in Mercator at all, never does.
ROWSCALE = "rowscale.tif"

#: Prep byproducts on the hero path: analytical masks the post stages read and the rig never
#: loads, which is why they are named here but stay outside the declaration vocabulary.
OCEANMASK_TIF = "oceanmask.tif"
WATERMASK = "watermask.tif"

#: The whole vocabulary a declaration may name.
#:
#: The one owner for these spellings, on the rule that a second reader with no owner is the defect.
#: No projection suffix: the hero path writes Albers cuts and the block path writes EPSG:3857 ones
#: under these same names, so no such suffix can be true for both writers.
KNOWN_IMAGES = frozenset({HEIGHTFIELD, OCEANMASK, INLANDLAKE, RIVER, SNOWMASK, LAKEDEPTH, SEAICE,
                          ROWSCALE})
