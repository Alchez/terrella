---
paths:
  - "pipeline/layers.py"
  - "pipeline/look/layer_producers.py"
  - "pipeline/look/perennial_ice.py"
  - "pipeline/planet_seam.py"
---

# Where a new surface input belongs, and how to tell

Three vocabularies can hold a grid-aligned input, they look interchangeable from any one file, and
picking the wrong one is expensive in a direction that reads as thoroughness. Ask what the thing
**is** before asking which mechanism gives you the property you want.

| Vocabulary | What belongs in it | What it costs to add |
| --- | --- | --- |
| `planet_seam.PLANET_RASTERS` | The fused planet's OWN outputs: heightfield, oceanmask, watermask | Every body must answer for it, and **eight modules call `planet_seam.declared`** |
| `layers.LAYERS` | A third-party dataset warped or burned onto the grid (RGI glaciers, OSI SAF sea ice, GLOBathy depth) | One row, plus a producer per body that has it |
| Neither, a pure rule | Arithmetic with no dataset behind it, like the forced Antarctic white | Nothing; it rides a layer's DECLARATION |

**Freshness is not the discriminator, because both vocabularies already give it.**
`planet_seam.rasters_on` and `layers.layers_on` are the same guarantee at two tiers: each records what
a body has, so switching one off moves the recipe, which mtimes structurally cannot see, and a new
entry moves only the bodies that have it. Reaching for `PLANET_RASTERS` *because* you want an input
tracked is the mistake: `layers_on` tracks it too, for one row instead of eight readers and both
bodies.

**A new layer that paints names its rig image on its row (`Layer.image`)**, which is what brings that
texture's wiring into the recipe of each stage that can load it and no other's.

## A Layer does not have to paint

The tell that sends people to the wrong vocabulary is "my input only modifies another layer, so it
cannot be a Layer." It can. `WHITE_UNION` is `(PERENNIAL_ICE, GLACIERS)`, and **`LAKE_DEPTH` and
`SEA_ICE` are already rows that never fold into the white alpha.**

## An input that REMOVES white goes in `WHITE_EXCLUSIONS`, never inside a producer

`fold_white` is a maximum over POSITIVE claims, so "this pixel is definitively not ice" has no
representation in it. Put such an input inside one producer's contribution and every OTHER union
member re-claims the pixel in the next operation: that is what cost the Antarctic outcrop 63% of its
subtraction, because `persistence_alpha` reads a median 1.0000 on the very rock SCAR ADD maps.

So the two tuples are one law and are read together. A raster answering "where this is white" joins
`WHITE_UNION`; a raster answering "where this is not" joins `WHITE_EXCLUSIONS`, `gather` returns it
beside the contributions, and `fold_white` applies it AFTER the union. No producer ever sees it, and
`LayerWindow` deliberately has no field it could arrive on.

**The guard has to be an OUTCOME.** Every plumbing guard over the old placement passed while the
outcrop still rendered solid white, because each named a mechanism. A test for an exclusion must
saturate a union member over the same pixels and assert the finished alpha, or it is green on both
arrangements alike.

**A stage that folds the law must also record it, through `white_law` and not through any producer.**
Nothing else in a recipe carries which tuple a layer sits in: `producers_for` walks
`layers.warped_for(vocabulary)`, so a layer's producer is recorded whichever half it joins, and
`glaciers` and `antarctic_rock` both
grade nothing per window. A `fold_white` caller whose recipe omits it keeps its output looking fresh
across a change that repaints the Antarctic outcrop.

## An input that TAKES white for a paint of its own lands after both halves

The salt flats are the one case: `layer_producers.salt_ground` hands the packed salt over and
`salt.take` splits the FINISHED white between snow and salt, after the union and the exclusions, so
no white source added later can re-claim salt ground. It is its own image (`saltmask.png`), mixed
last in the rig so it also covers the lake paint, and `white_law` records it only where a stage
reads it, so the caps' recipes do not move. Its raster is baked whole by the warp stage, a lake body
and a white component crossing block edges, from the planet's own heightfield and water mask, which
`LayerProducer.grid_rasters` names so the warp counts them as sources.

## The rule and the raster are counted differently

Do not conflate implementations with stages when scoping one of these.

- `layer_producers._earth_perennial_ice` serves **both** the block prep and the hero snow stage:
  `gather` runs it on a Mercator window in one and on a country's conic grid in the other, with a
  vocabulary per stage. One implementation, two stages.
- `perennial_ice._earth_south` (AEQD cap) is the second implementation.

So a shared rule in `look/snow.py` lands in all of them with one edit, while a **raster feeding a
producer** has to reach each grid: the planet warp lands it for `prep_block` to window, and the cap
and the hero snow stage land it from source themselves. An **exclusion** raster is the cheaper shape
and that is a reason to prefer it: it rides the same landing as every other layer, and no producer
has to be taught it.

## The cap and the heroes go to source; the tiles read a warp

`CapIceInputs.warp` and `.burn` open the ORIGINAL file: `_earth_north` warps the NetCDF, Mars burns
its unit shapefiles. `snow_mask.LANDERS` does the same on a hero's grid, a hero pixel being finer
than the 3857 rasters. The Mercator tiers read a pre-warped `*_3857.tif` built by the layer
registry. Two mechanisms for one dataset is correct here and is not a second reader: the grids
differ, and `layers.Layer` is the single owner of the filename either way.
