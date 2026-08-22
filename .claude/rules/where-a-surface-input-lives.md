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
`SEA_ICE` are already rows that never fold into the white alpha.** A Layer whose raster is read by
a different layer's producer, through a `LayerWindow` field beside `watercode`, is in-idiom.

## The rule and the raster are counted differently

Do not conflate implementations with stages when scoping one of these.

- `layer_producers._earth_perennial_ice` (Mercator) serves **both** the composite and the block
  render — `gather` runs it with a different `vocabulary` per stage. One implementation, two stages.
- `perennial_ice._earth_south` (AEQD cap) is the second implementation.

So a shared rule in `look/snow.py` lands in both with one edit, while the **raster** must be plumbed
three times, because each stage builds its own window: the composite, `prep_block`, and the cap.

## The cap goes to source; the tiles read a warp

`CapIceInputs.warp` and `.burn` open the ORIGINAL file — `_earth_north` warps the NetCDF, Mars burns
its unit shapefiles. The Mercator tiers read a pre-warped `*_3857.tif` built by the layer registry.
Two mechanisms for one dataset is correct here and is not a second reader: the grids differ, and
`layers.Layer` is the single owner of the filename either way.
