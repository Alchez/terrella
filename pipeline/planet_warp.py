"""Warp a body's 4326 planet rasters onto the shared WebMercatorQuad-aligned 3857 grid.

Every input is warped GLOBALLY and STREAMING, so nothing is normalised or edge-extrapolated per
block: the height, whichever of the two masks the body emitted, and every optional surface layer
land on one reference grid that `tile.block_render` then renders against.

THIS IS THE FIRST OF THE TWO PLANET STAGES AND IT IS NOT AN ENTRY POINT. `tile/planet_pass.py` owns
the sequence; `tile/cut_tiles.py` is the other end, cutting tiles out of the finished raster hours
later. The two lived in one module called `shade_planet` because a windowed numpy composite stood
between them and they were its input and output stages. That shader is deleted, and with it the only
thing the two halves had in common.

Every stage skips if its output is FRESH -- present, completed, and newer than everything it
derives from (`is_stale`). An exists()-only guard cannot tell "built" from "still correct":
the Caspian re-fuse rewrote 4 of the 540 chunks, and a plain re-run would have
skipped every stage and silently re-cut tiles from the pre-Caspian, pre-sea-rework rasters.
"""

import json
import subprocess
from pathlib import Path

import rasterio

from pipeline import bodies, layers, progress, wrap_seam
from pipeline.freshness import (
    mark_done,
    reference_needs_rebuild,
    warp_needs_rebuild,
    write_if_changed,
)
from pipeline.look import (
    layer_producers,
)

# The grid resolution used to live here as a module constant named for the one zoom Earth cuts to.
# It is `Body.map_units_per_pixel` now, because a planet with a different ceiling needs a different
# pixel and a module constant cannot have one — and because a constant with no field to be bridged
# to is exactly how this one survived the body parameterisation with every gate green.
#
# The value is deliberately NOT written out here. `tests/test_bodies.py` scans this file for it, and
# a comment quoting a deleted number re-creates the needle the scan exists to find.
#
# The vertical exaggeration left the same way and for a sharper reason: it is a LOOK decision, and
# two bodies whose relief is a different fraction of their radius cannot read right at one value.
# It is `Body.exaggeration`, threaded to the places that shade. Same rule as above: the number is
# not written out, because the same scan looks for its name.

#: The band height `warp_inputs` builds each optional layer's raster in. Must stay 256: the
#: persistence raster is banded at this height to be byte-identical to the per-window warp it
#: replaced. It was also the composite's default window and its RAM lever; that half went with the
#: composite, and what remains is the banding contract alone.
WINDOW_ROWS = 256


def _run(cmd):
    subprocess.run([str(part) for part in cmd], check=True)


#: The planet rasters this stage warps onto the Mercator grid, named once.
#:
#: THEY REACHED FIVE SPELLINGS HERE AND WOULD HAVE REACHED EIGHT, because the block prep consumes
#: exactly these files and would have restated all three to do it. `layers.Layer.warped_basename`
#: already owns the optional layers' names; these three are the planet seam's rasters, which have
#: no such row. THE BASENAMES ARE SHIPPED AND MUST NOT BE TIDIED — each is a dependency by mtime,
#: so renaming one restages Earth's whole pyramid to reproduce the pixels already there.
HEIGHT_3857 = "height_3857.tif"
OCEAN_3857 = "ocean_3857.tif"
WATER_3857 = "water_3857.tif"

#: What the finished pixels lose when a layer is skipped at the WARP stage, by layer name.
#:
#: A CONSEQUENCE IS PER (LAYER, STAGE), which is why this is here and not a column on `Layer`:
#: `cap_render` says something different about the same layers because it paints a different
#: picture. Each states what the reader will see rather than what was missing, so a partial build
#: can be read back off its own output.
#:
#: Keyed by name and looked up unconditionally, so a layer added to the planet's set and forgotten
#: here raises on the next pass of any body rather than being quietly skipped forever.
WARP_CONSEQUENCE: dict[str, str] = {
    layers.LAKE_DEPTH.name: "lakes stay flat; run pipeline.acquire.extract_globathy",
    layers.PERENNIAL_ICE.name: "no ice painted; the reader gets None and skips it",
    layers.GLACIERS.name: "persistence-only snow",
    layers.SEA_ICE.name: "bathymetry bare at the poles",
    layers.ANTARCTIC_ROCK.name: "Antarctic outcrop stays under the forced white",
}


def warp_inputs(work: Path, planet: Path, body: bodies.Body, rasters: frozenset[str]):
    """Warp height + whichever masks this planet HAS to the shared WMQ-aligned 3857 grid.

    Each warp depends on the chunk DIRECTORY, not just its VRT -- re-fusing a cell leaves the
    VRT untouched, so the directory walk is the only thing that sees the change.

    `rasters` is the planet stage's own declaration of what it emitted (`planet_seam`), and it is
    passed in rather than read off the disk here for the reason the layer gates already follow: a
    mask's presence and a body's answer are different questions, and the file system can only answer
    the first. The two masks are gated SEPARATELY because the known next case needs it — a Mars that
    gains a sea at a chosen contour has an ocean mask and still no inland water.
    """
    chunks = planet / "chunks"
    height = work / HEIGHT_3857
    resolution = body.map_units_per_pixel
    # NOT `is_stale` ALONE: this raster's inputs are a VRT and a chunk directory, and neither moves
    # when the body's ceiling does. `reference_needs_rebuild` asks the raster its own pixel size.
    if reference_needs_rebuild(height, resolution, planet / "planet_heightfield.vrt", chunks):
        progress.stage("warp height -> 3857 ...")
        height.unlink(missing_ok=True)  # gdalwarp UPDATES an existing target; it must be gone
        _run(["gdalwarp", "-q", "-t_srs", "EPSG:3857", "-tr", resolution, resolution, "-tap",
              "-r", "bilinear", "-ot", "Float32", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
              "-co", "BIGTIFF=YES", "-co", "NUM_THREADS=ALL_CPUS",
              planet / "planet_heightfield.vrt", height])
        mark_done(height)
    # OUTSIDE THE FRESHNESS GATE ON PURPOSE, and this is the half that is easy to get wrong: the
    # raster this has to reach was written by a warp that already ran, so gating the fill on a
    # re-warp would leave every existing planet exactly as broken while reading as fixed. It is free
    # to re-ask — a closed raster declares no nodata, so `close_wrap_seam` returns without touching
    # a pixel — which is what lets it sit here rather than behind a condition.
    #
    # Height only, and deliberately not the mask warps below: those are class codes resampled with
    # `near`, where the midpoint between two categories is not a category.
    filled = wrap_seam.close_wrap_seam(height)
    if filled:
        # The bytes moved, so everything keyed on this marker has to rebuild — the render reads the
        # filled column as ground instead of a cliff. Re-stamping IS that instruction.
        print(f"wrap seam: filled {filled} px at the antimeridian -> height restaged", flush=True)
        mark_done(height)
    with rasterio.open(height) as dataset:
        bounds = [repr(value) for value in dataset.bounds]
        size = [str(dataset.width), str(dataset.height)]
        # Numeric forms for the layer builds below, which take a (left, bottom, right, top) tuple and
        # int width/height rather than the gdalwarp -te/-ts string lists the mask warps splice in.
        grid_bounds = tuple(dataset.bounds)
        grid_width, grid_height = dataset.width, dataset.height
    # The reference grid every raster below is warped onto. warp_needs_rebuild re-warps a target when
    # its source moved OR when this grid grew under it (the Antarctica re-fuse; see grid_matches).
    grid = (grid_width, grid_height, grid_bounds)
    for name, raster in (("ocean", "oceanmask"), ("water", "watermask")):
        if raster not in rasters:
            progress.stage(f"{body.name}'s planet stage emitted no {raster} -> {name}_3857 "
                           f"skipped (the reader gets None and treats every pixel as land)")
            continue
        src = f"planet_{raster}.vrt"
        out = work / f"{name}_3857.tif"
        if warp_needs_rebuild(out, grid, planet / src, chunks):
            progress.stage(f"warp {name} -> 3857 ...")
            out.unlink(missing_ok=True)
            _run(["gdalwarp", "-q", "-t_srs", "EPSG:3857", "-te", *bounds, "-ts", *size,
                  "-r", "near", "-ot", "Byte", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
                  "-co", "BIGTIFF=YES", planet / src, out])
            mark_done(out)

    # Every optional surface layer, warped ONCE here rather than per window (optimisation #4). The
    # old composite loop forked gdalwarp + gdal_rasterize for every window (~728 subprocesses) into
    # fixed-path temps -- the shared paths that blocked threading it. Deliberately NOT in the mask
    # loop above: those are class codes wanting `near`/Byte, and every one of these is a continuous
    # or vector source with its own resampling.
    for layer in layers.warped_for(layers.PLANET_LAYERS):
        consequence = WARP_CONSEQUENCE[layer.name]
        out = layer.warped_in(work)
        # THE BODY IS ASKED FIRST AND THE PRODUCER SECOND, and the order is what makes the disk
        # question honest: `producer.sources()` are that body's files, where the constants they
        # replaced were Earth's at a fixed global path on every planet alike.
        if not layers.body_declares_layer(body, layer, consequence):
            continue
        producer = layer_producers.producer_for(body, layer)
        sources = producer.sources()
        if not all(layers.layer_is_buildable(body, layer, source, consequence)
                   for source in sources):
            continue
        # A BUILD-TIME CONSTANT IS MATERIALISED INTO A SOURCE, because `warp_needs_rebuild` is closed
        # over PATHS and no Python value can reach it. A producer that grades before it writes has
        # its tunables frozen into the file; recorded only in the painting stage's recipe, changing
        # one would restage that stage and then repaint from the unchanged raster — the same wrong
        # pixels behind a restage that looks like it worked. `write_if_changed` moves an mtime if and
        # only if a value moved, and is written BEFORE the question is asked, per its own docstring.
        #
        # Empty for every Earth producer, which writes no file and leaves this list exactly as it
        # was — the reason adopting this restages nothing.
        tunables = producer.build_recipe()
        if tunables:
            sources = (*sources, write_if_changed(
                out.with_name(f"{out.stem}_build.json"),
                json.dumps(tunables, indent=2, sort_keys=True) + "\n"))
        # `warp_needs_rebuild` re-warps when a source moved OR when the grid grew under the target;
        # the sources are the producer's because they are what it will actually read.
        if warp_needs_rebuild(out, grid, *sources):
            producer.build(layer_producers.LayerBuild(
                bounds=grid_bounds, width=grid_width, height=grid_height, out=out,
                band_rows=WINDOW_ROWS))
            mark_done(out)
    return height
