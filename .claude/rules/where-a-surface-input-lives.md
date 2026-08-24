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
| `layers.LAYERS` | A third-party dataset warped or burned onto the grid — RGI glaciers, OSI SAF sea ice, GLOBathy depth | One row, plus a producer per body that has it |
| Neither — a pure rule | Arithmetic with no dataset behind it, like the forced Antarctic white | Nothing; it rides a layer's DECLARATION |

**Freshness is not the discriminator, because both vocabularies already give it.**
`planet_seam.rasters_off` and `layers.layers_off` are the same guarantee at two tiers: each records
what is switched OFF, which mtimes structurally cannot see. Reaching for `PLANET_RASTERS` *because*
you want an input tracked is the mistake — `layers_off` tracks it too, for one row instead of eight
readers and both bodies.

## A Layer does not have to paint

The tell that sends people to the wrong vocabulary is "my input only modifies another layer, so it
cannot be a Layer." It can. `WHITE_UNION` is `(PERENNIAL_ICE, GLACIERS)` — **`LAKE_DEPTH` and
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
Nothing else in a recipe carries which tuple a layer sits in: `producers_for` walks `WARPED_LAYERS`,
so a layer's producer is recorded whichever half it joins, and `glaciers` and `antarctic_rock` both
grade nothing per window. A `fold_white` caller whose recipe omits it keeps its output looking fresh
across a change that repaints the Antarctic outcrop.

## The rule and the raster are counted differently

Do not conflate implementations with stages when scoping one of these.

- `layer_producers._earth_perennial_ice` (Mercator) serves **both** the composite and the block
  render — `gather` runs it with a different `vocabulary` per stage. One implementation, two stages.
- `perennial_ice._earth_south` (AEQD cap) is the second implementation.

So a shared rule in `look/snow.py` lands in both with one edit, while a **raster feeding a producer**
must be plumbed per window, because each stage builds its own: the composite, `prep_block`, and the
cap. An **exclusion** raster is the cheaper shape and that is a reason to prefer it: `gather` reads
it once and serves both Mercator stages from there, leaving only the cap to supply its own.

## The cap goes to source; the tiles read a warp

`CapIceInputs.warp` and `.burn` open the ORIGINAL file — `_earth_north` warps the NetCDF, Mars burns
its unit shapefiles. The Mercator tiers read a pre-warped `*_3857.tif` built by the layer registry.
Two mechanisms for one dataset is correct here and is not a second reader: the grids differ, and
`layers.Layer` is the single owner of the filename either way.
