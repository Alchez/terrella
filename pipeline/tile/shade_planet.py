"""The planet stages either side of the raster: warp the inputs in, cut the tiles out.

Every shading input is computed GLOBALLY and STREAMING, so nothing is normalised or
edge-extrapolated per block:

  1. warp the 4326 planet heightfield + masks once to a WebMercatorQuad-aligned 3857 grid;
  2. custom per-row-z hillshade (pipeline/look/hillshade.py) -> seamless + correct exaggeration;
  3. cut 512px tiles from z0 to THIS BODY's ceiling, the body saying so rather than this module
     (no overview step: `gdal raster tile` never reads them; see build_tiles).

THIS MODULE IS NOT AN ENTRY POINT and no longer fills the raster between those stages: the windowed
numpy composite that used to live here was deleted with the producer choice, and `block_render`
renders every planet through Cycles. `tile/planet_pass.py` owns the sequence.

Every stage skips if its output is FRESH -- present, completed, and newer than everything it
derives from (`is_stale`). An exists()-only guard cannot tell "built" from "still correct":
the Caspian re-fuse rewrote 4 of the 540 chunks, and a plain re-run would have
skipped every stage and silently re-cut tiles from the pre-Caspian, pre-sea-rework rasters.
Grid matches the existing tile pyramid exactly (131072 x 131072 — square since Antarctica was
fused in; it was 131072 x 93009 while the pyramid stopped at -60).

    python -m pipeline.tile.planet_pass --body earth            # produce only
    python -m pipeline.tile.planet_pass --body earth --tiles    # + cut tiles
"""

import json
import subprocess
from pathlib import Path
from typing import TypedDict

import rasterio

from pipeline import bodies, layers, progress, wrap_seam
from pipeline.freshness import (
    done_marker,
    is_stale,
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
# It is `Body.exaggeration`, threaded to the two places that shade — the hillshade here, and the
# caps, which used to import it from this module and therefore drew every planet at Earth's.
# Same rule as above: the number is not written out, because the same scan looks for its name.
# Latitudes above/below which the poles are flat-filled. CAP_SOUTH mirrors CAP_NORTH
# now that Antarctica is fused into the pyramid: the flat fill covers only the last
# smeared Mercator sliver past -84, not real Antarctica (which is shaded down to the -85.06 grid edge).
# It was -59.5 while the pyramid stopped at -60 and the AEQD cap supplied everything south of it.
#
# ON A BODY THAT RENDERS CAPS THIS FILL IS MOSTLY DEAD PIXELS, AND THAT IS THE POINT OF IT. The fill
# exists because the raster must hold SOMETHING between here and the 85.05 grid edge, and a smeared
# Mercator sliver is uglier than a flat plug in the one case the plug shows.
#
# IT IS NO LONGER THE FEATHER'S CEILING, and that separation is deliberate. `caps_manifest` served
# this same number as `feather_hi` until the cap edge moved to 82, which made one constant answer
# two questions: where a composited raster starts being flat-filled, and where the cap finishes
# fading over the tiles. The second is `cap_render.feather_hi_deg`, derived from the Mercator limit,
# because a fade must end where there is nothing left beneath it to hide. Tied together, the fade
# could not widen on Earth without moving the plug on Mars.
#
# It shows on a body with `renders_polar_caps = False`, where it becomes the whole pole — MapLibre
# extends the top tile row over the projection's hole as well, so a flat disc replaces the ice cap.
# NO REGISTERED BODY IS IN THAT STATE, which is why this stays one constant rather than a per-body
# field: Mars was the only capless body and its caps went on with its ramps. Pricing a colour per
# planet would be pricing pixels that are covered on every planet that exists.
CAP_NORTH, CAP_SOUTH = 84.0, -84.0

#: The band height `warp_inputs` builds each optional layer's raster in. Must stay 256: the
#: persistence raster is banded at this height to be byte-identical to the per-window warp it
#: replaced. It was also the composite's default window and its RAM lever; that half went with the
#: composite, and what remains is the banding contract alone.
WINDOW_ROWS = 256


def _run(cmd):
    subprocess.run([str(part) for part in cmd], check=True)


#: What the finished pixels lose when a layer is skipped at the WARP stage, by layer name.
#:
#: A CONSEQUENCE IS PER (LAYER, STAGE), which is why this is here and not a column on `Layer`:
#: The planet rasters this stage warps onto the Mercator grid, named once.
#:
#: THEY REACHED FIVE SPELLINGS HERE AND WOULD HAVE REACHED EIGHT, because the block prep consumes
#: exactly these files and would have restated all three to do it. `layers.Layer.warped_basename`
#: already owns the optional layers' names; these three are the planet seam's rasters, which have
#: no such row. THE BASENAMES ARE SHIPPED AND MUST NOT BE TIDIED — each is a composite dependency
#: by mtime, so renaming one restages Earth's whole pyramid to reproduce the pixels already there.
HEIGHT_3857 = "height_3857.tif"
OCEAN_3857 = "ocean_3857.tif"
WATER_3857 = "water_3857.tif"

#: The shaded colour raster the tile cut reads, whatever produced it.
#:
#: NAMED HERE BECAUSE IT NOW HAS TWO PRODUCERS. `composite_planet` builds it window by window and
#: `tile.block_render` renders it block by block, and the tile cut, the freshness marker and the
#: publish all key on this one basename — so it is exactly the kind of spelling the second writer
#: would otherwise copy. The variant suffix stays a local f-string: only the composite emits those.
PLANET_RGB = "planet_rgb.tif"

#: `cap_render` says something different about the same layers because it paints a different
#: picture. Each states what the reader will see rather than what was missing, so a partial build
#: can be read back off its own output.
#:
#: Keyed by name and looked up unconditionally, so a layer added to the composite's set and forgotten
#: here raises on the next pass of any body rather than being quietly skipped forever.
WARP_CONSEQUENCE: dict[str, str] = {
    layers.LAKE_DEPTH.name: "lakes stay flat; run pipeline.acquire.extract_globathy",
    layers.PERENNIAL_ICE.name: "no ice painted; the composite reads None and skips it",
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
        # The bytes moved, so everything keyed on this marker has to rebuild — the hillshade reads
        # the filled column as ground instead of a cliff, and the composite ramps it as terrain
        # instead of clamping it to the darkest stop. Re-stamping IS that instruction.
        print(f"wrap seam: filled {filled} px at the antimeridian -> height restaged", flush=True)
        mark_done(height)
    with rasterio.open(height) as dataset:
        bounds = [repr(value) for value in dataset.bounds]
        size = [str(dataset.width), str(dataset.height)]
        # Numeric forms for the snow warps below, which take a (left, bottom, right, top) tuple and
        # int width/height rather than the gdalwarp -te/-ts string lists the mask warps splice in.
        grid_bounds = tuple(dataset.bounds)
        grid_width, grid_height = dataset.width, dataset.height
    # The reference grid every raster below is warped onto. warp_needs_rebuild re-warps a target when
    # its source moved OR when this grid grew under it (the Antarctica re-fuse; see grid_matches).
    grid = (grid_width, grid_height, grid_bounds)
    for name, raster in (("ocean", "oceanmask"), ("water", "watermask")):
        if raster not in rasters:
            progress.stage(f"{body.name}'s planet stage emitted no {raster} -> {name}_3857 "
                           f"skipped (the composite reads None and treats every pixel as land)")
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
    # fixed-path temps -- the shared paths that blocked threading the composite. Deliberately NOT in
    # the mask loop above: those are class codes wanting `near`/Byte, and every one of these is a
    # continuous or vector source with its own resampling.
    for layer in layers.warped_for(layers.COMPOSITE_LAYERS):
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
        # its tunables frozen into the file; recorded only in `composite_params`, changing one would
        # restage the whole composite and then repaint from the unchanged raster — the same wrong
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


class TileCut(TypedDict):
    """Every setting of the tile cut that changes the bytes GDAL writes.

    A TypedDict for the reason `Knobs` is one: it is consumed both as a command line and as a JSON
    freshness record, and a plain dict would infer `str | int | bool` for every value, so a typo'd
    key or a quality read as a string would only surface as a wrong pyramid.
    """
    format: str
    quality: int
    tile_size: int
    min_zoom: int
    max_zoom: int
    resampling: str
    overview_resampling: str
    convention: str
    skip_blank: bool


# WebP q95 replaced PNG. Measured on 73 tiles sampled proportionally across all nine
# zooms: q95 is 20.0% of PNG byte-weighted, and z8 -- three quarters of the pyramid -- is the
# cheapest at 14.8%, so the aggregate is conservative. The archive goes ~16 GB -> ~3.2 GB and the
# Worker's single R2 read per cold tile drops with it (~380 ms -> ~80 ms, it is bandwidth-bound).
def tile_cut(body: bodies.Body) -> TileCut:
    """This body's cut settings — eight encoder facts that are the same everywhere, and its ceiling.

    A FUNCTION RATHER THAN A CONSTANT because exactly one of these keys belongs to the planet.
    `max_zoom` was a literal 8 here, which is Earth's ceiling and nobody else's, and it is the
    second of the two constants that survived the body parameterisation by having no field to be
    bridged to. The other seven are properties of the encoder and the tile scheme, so they stay
    written once here rather than being copied onto every body — a body answers for what differs
    about it, not for what does not.

    Earth's result is the same dict the constant held, so `tile_params` still serialises the exact
    bytes beside the live pyramid and the cut does not restage.
    """
    return TileCut(format="WEBP", quality=95, tile_size=512, min_zoom=0,
                   max_zoom=body.tile_max_zoom,
                   resampling="cubic", overview_resampling="cubic", convention="xyz",
                   skip_blank=True)


def tile_params(body: bodies.Body) -> str:
    """The tile cut's own settings, recorded as the live pyramid's dependency — hs_params' sibling.

    This stage used to key freshness off `planet_rgb` ALONE, which meant the cut was the
    one stage that could not see its own recipe: changing the output format left `tiles_are_fresh`
    true, so the PNG->WebP switch would have silently shipped the old pyramid. Everything in
    the cut alters the emitted bytes, and nothing outside it does — the input raster and the output
    directory are `is_stale`'s own arguments, not settings.

    The BODY is not recorded here and must not be: each body writes this file into its own work
    tree, so the recipe is already body-specific by location, and adding the name would restage
    Earth's entire pyramid the day a second planet existed for no pixel change at all.
    """
    return json.dumps(tile_cut(body), sort_keys=True, indent=2)


def tile_params_path(out: Path) -> Path:
    """Where the cut's recipe is recorded, beside the pyramid it describes."""
    return out / "tile_params.json"


def _tile_cmd(planet_tif: Path, staging: Path, body: bodies.Body) -> list[str]:
    """The `gdal raster tile` invocation that cuts this body's 512px tiles into `staging`.

    Built FROM `tile_cut` rather than from literals, so the command and the freshness record cannot
    disagree about what was cut — the same one-fact-one-spelling rule pack_pmtiles now follows for
    the tile encoding.

    `--overview-resampling=cubic` pins what is otherwise an UNDOCUMENTED default -- identified by
    elimination: unset, it silently inherits `--resampling`. This is byte-identical to
    today and is what built the verified 07-14 pyramid, so it is a pin, not a change. z0-7 carry
    most of the globe's zoomed-out surface; they should not ride on a default GDAL may alter.

    `--webviewer=none`: the default is `all`, which emits leaflet/openlayers/mapml/stac files into
    the pyramid. We serve our own MapLibre page, and they would ride into PMTiles.

    NO `--resume` (removed): GDAL skips existing files by existence without reading them,
    so a truncated tile from a mid-write kill would survive a resume. build_tiles instead removes
    any partial staging dir and cuts clean every time -- see its docstring.
    """
    cut = tile_cut(body)
    cmd = ["gdal", "raster", "tile",
           f"--min-zoom={cut['min_zoom']}", f"--max-zoom={cut['max_zoom']}",
           f"--tile-size={cut['tile_size']}",
           f"--resampling={cut['resampling']}",
           f"--overview-resampling={cut['overview_resampling']}",
           f"--convention={cut['convention']}",
           f"--format={cut['format']}", "--co", f"QUALITY={cut['quality']}"]
    if cut["skip_blank"]:
        cmd.append("--skip-blank")
    return [*cmd, "--webviewer=none", str(planet_tif), str(staging)]


def tiles_are_fresh(planet_tif: Path, out: Path) -> bool:
    """True if the live pyramid is current: present, non-empty, and stamped newer than BOTH the
    composite that feeds it and the recipe that describes it.

    Keyed off `planet_rgb`'s `.done` marker, NOT the `.tif` (GDAL stamps its target at write-start,
    the trap `is_stale` exists to avoid). `is_stale(live, ...)` stats only `tiles/` + `tiles.done` +
    the two input markers -- never a 62k-tile walk (the dir is the OUTPUT, not a walked input). The
    non-empty + marker-exists checks reject a half-swapped empty dir or a missing composite stamp.

    tile_params.json joined the key. A missing one scores 0.0 in `newest_mtime` and so
    cannot make a pyramid look stale on its own; build_tiles writes it through `write_if_changed`
    before asking, which is what makes a settings change -- and only a settings change -- restage.
    """
    live = out / "tiles"
    return (live.is_dir() and any(live.iterdir())
            and done_marker(planet_tif).exists()
            and not is_stale(live, done_marker(planet_tif), tile_params_path(out)))


def build_tiles(planet_tif: Path, out: Path, body: bodies.Body):
    """Cut this body's 512px tiles into a staging dir, then swap over the live tiles.

    Fresh-guarded like every other stage (`tiles_are_fresh`): a re-run whose `planet_rgb` AND
    `tile_params.json` are unchanged skips the ~4:19 cut entirely. This used to be the one
    unguarded stage -- the staging dir is renamed away on success, so `--resume` always started from
    empty and the cut re-ran in full every time. The completion stamp is `tiles.done`, touched only
    after the swap.

    Recipe-gated in the usual order — see `freshness.write_if_changed`.

    EVERY CUT IS A CLEAN FULL CUT: the staging dir is removed first and `--resume` is not passed
    (see `_tile_cmd`). GDAL writes each tile in place, so a worker killed mid-write leaves a
    truncated file that an existence-only `--resume` would keep; re-cutting from empty (~4:19) is
    the cheap price of never trusting a partial tile. The one-generation rollback stays at
    `tiles_old`.

    THERE IS NO gdaladdo STEP, deliberately. `gdal raster tile` builds each low zoom from the tiles
    it just generated, never from the source's overviews -- proven by tiling one raster
    with and without them for byte-identical output at identical wall time. The overviews this
    function used to build cost ~3 min and ~4 GB appended to the master, for nothing. The
    note that justified them credited a confounded fix: materialising the 194-source VRT
    to a GTiff was the real speed-up; the overviews rode along on the same commit untested.
    """
    cut = tile_cut(body)
    write_if_changed(tile_params_path(out), tile_params(body))
    if tiles_are_fresh(planet_tif, out):
        progress.stage("tiles fresh -> skip cut")
        return
    staging = out / "tiles_new"
    if staging.exists():
        _run(["rm", "-rf", str(staging)])   # a partial from a prior mid-cut crash: never resume over it
    progress.stage(f"cutting z{cut['min_zoom']}-{cut['max_zoom']} {cut['tile_size']}px tiles "
                   f"-> {staging} ...")
    _run(_tile_cmd(planet_tif, staging, body))
    live = out / "tiles"
    if live.exists():
        old = out / "tiles_old"
        if old.exists():
            _run(["rm", "-rf", str(old)])
        live.rename(old)
    staging.rename(live)
    mark_done(live)
    progress.stage(f"tiles live -> {live} (previous kept at {out / 'tiles_old'})")
