"""Shade the whole (non-Antarctic) planet into ONE seamless Web-Mercator RGB raster.

Supersedes the 194-strip `tile_planet.py`, whose seam-avoidance hacks (a single global
z-factor, SVF off, per-strip `gdaldem` edges) caused the defects seen on the first globe:
blown-out tropics / flat high latitudes (wrong exaggeration), and faint block seams. That
script was deleted rather than left runnable beside this one -- it defaulted
to the same --out and would have cut tiles into the LIVE pyramid with no rollback. Read it
with `git show a7b7223:pipeline/tile/tile_planet.py`.

The fix is to compute every shading input GLOBALLY and STREAMING, so nothing is normalised
or edge-extrapolated per block, then composite in RAM-budgeted horizontal windows (the
composite is per-pixel, so windowing it cannot seam):

  1. warp the 4326 planet heightfield + masks once to a WebMercatorQuad-aligned 3857 grid;
  2. `gdaldem color-relief` the height globally (per-pixel -> seamless);
  3. custom per-row-z hillshade (pipeline/render/hillshade.py) -> seamless + correct 15x;
  4. sky-view factor once on a global downsample with a single global normalisation;
  5. composite each full-width horizontal window (reusing tile/shade.py::composite) with the
     latitude-ramped snow (blue-white shadows) and RGI glaciers, and cap both polar edges
     (>84N, <-59.5S -> flat pale sea-ice) so MapLibre's globe shows clean polar discs;
  6. cut 512px tiles from z0 to THIS BODY's ceiling -- z8 for Earth, and the body says so rather
     than this module (no overview step: `gdal raster tile` never reads them; see build_tiles).

Every stage skips if its output is FRESH -- present, completed, and newer than everything it
derives from (`is_stale`). An exists()-only guard cannot tell "built" from "still correct":
the Caspian re-fuse rewrote 4 of the 540 chunks, and a plain re-run would have
skipped every stage and silently re-cut tiles from the pre-Caspian, pre-sea-rework rasters.
Grid matches the existing tile pyramid exactly (131072 x 131072 — square since Antarctica was
fused in; it was 131072 x 93009 while the pyramid stopped at -60).

    python -m pipeline.tile.shade_planet --body earth            # shade only
    python -m pipeline.tile.shade_planet --body earth --tiles    # + cut tiles
"""

import argparse
import gc
import json
import math
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict, cast

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window

from pipeline import bodies, planet_seam
from pipeline.raster_io import GTIFF_CREATE, band_window
from pipeline.render import (
    cast_shadow,
    hillshade,
    lake_depth,
    palette,
    seaice,
    sky_view,
    snow,
)
from pipeline.render.sky_view import normalised_occlusion, occlusion_shape
from pipeline.tile import shade
from pipeline.tile.shade import KNOBS

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
ALT, AZ = KNOBS["alt"], 315.0
WINDOW_ROWS = 256          # the snow-persistence banded-warp height (Phase A) AND composite_planet's
                           # DEFAULT window. Must stay 256: the persistence raster is banded at this
                           # height to be byte-identical to the per-window warp it replaced, and the
                           # composite reads slices of that fixed raster. Also the RAM lever for the
                           # serial default (full 131072-wide float32 windows peak ~6 GB; 384 rows in
                           # float64 peaked ~18 GB, OOM). Launch with GDAL_CACHEMAX=512 for headroom.
COMPOSITE_ROWS = 128       # PRODUCTION composite window (optimisation #5). Smaller than
                           # WINDOW_ROWS purely to fit N_WORKERS concurrent windows under the 12 G cap
                           # -- 256/N3 OOMs, and 128 is not a speed lever by itself (serial rows/s ~
                           # equal). It shifts the look sub-perceptibly (SVF window slicing; worst 15
                           # DN on amplified mountain-snow edges, invisible at true scale -- judged
                           # judged it on a render). Reads 128-row slices of the 256-banded
                           # persistence, exactly as the delta A/B validated.
N_WORKERS = 4              # composite worker threads. The knee: numpy is DRAM-bandwidth-bound, so
                           # threads scale 1.8×@2 / 3.1×@4 / 3.4×@6, and RAM grows linearly (128-row
                           # peak: N4 8.5 G, N6 11.3 G). 4 = ~3.1× at safe margin under 12 G.
                           # (the sky-view downsample is no longer a planet-only constant: it is
                           # derived from sky_view.OCCLUSION_TARGET_M_PER_PX, which the region path
                           # shares, so the two cannot drift again)
# Latitudes above/below which the poles are flat-filled with CAP_RGB. CAP_SOUTH mirrors CAP_NORTH
# now that Antarctica is fused into the pyramid: the flat fill covers only the last
# smeared Mercator sliver past -84, not real Antarctica (which is shaded down to the -85.06 grid edge).
# It was -59.5 while the pyramid stopped at -60 and the AEQD cap supplied everything south of it.
CAP_NORTH, CAP_SOUTH = 84.0, -84.0
CAP_RGB = (216, 226, 233)   # pale sea-ice fill for the poles (web-mercator has no data past ~85 deg)
INFLIGHT_BUFFER = 2        # windows read AHEAD of the workers (optimisation #5): the main thread
                           # may queue max_workers + this many window-input bundles before it must
                           # block on the oldest result and write it. Bounds peak RAM to
                           # (max_workers + INFLIGHT_BUFFER) windows in flight; keep it small.


def _run(cmd):
    subprocess.run([str(part) for part in cmd], check=True)


def done_marker(output: Path) -> Path:
    """The completion stamp beside `output` (height_3857.tif -> height_3857.done)."""
    return output.with_suffix(".done")


def mark_done(output: Path) -> None:
    """Stamp `output` complete. Call ONLY after its stage has returned successfully."""
    done_marker(output).touch()


def newest_mtime(*inputs: Path) -> float:
    """Newest mtime among `inputs`, recursing into directories. Missing paths score 0.0.

    Directories are walked rather than stat'ed because a VRT's own mtime does NOT move when
    the chunks it points at are re-fused -- which is exactly how the Caspian re-fuse stayed
    invisible to the old guard. The planet is 540 cells x 3 rasters, so this is ~1.6k stats.
    """
    newest = 0.0
    for path in inputs:
        if not path.exists():
            continue
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    newest = max(newest, child.stat().st_mtime)
        else:
            newest = max(newest, path.stat().st_mtime)
    return newest


def is_stale(output: Path, *inputs: Path) -> bool:
    """True if `output` must be rebuilt: never completed, or older than any of `inputs`.

    Freshness is read from the .done marker, never from `output` itself: GDAL creates its
    target at the START of a run, so a crashed pass leaves a full-sized, freshly-stamped,
    half-written raster that an mtime test on the raster would happily accept as current.
    """
    if not output.exists() or not done_marker(output).exists():
        return True
    return newest_mtime(*inputs) > done_marker(output).stat().st_mtime


def grid_matches(path: Path, width: int, height: int, bounds) -> bool:
    """True if `path` exists on exactly the reference grid (`width` x `height`, same `bounds`).

    Every 3857 raster below `height_3857` is warped to height's grid (via -te/-ts), but each one's
    freshness is gated on its own SOURCE, not on height. A re-fuse that GROWS the grid -- un-skipping
    Antarctica takes the planet from 93009 to 131072 rows -- re-warps height while these sit falsely
    fresh at the old dimensions, and the composite then reads window slices past their bottom (silent
    corruption). A dimension/bounds comparison catches exactly that, and is deliberately NOT an mtime
    dependency on height: that would re-warp all of them on a SAME-grid re-fuse (the Caspian
    rewrote 4 chunks without moving the grid), which is 30+ min of needless work.

    Bounds are compared with a 1 m tolerance -- far below the 305 m pixel, so a real grid shift always
    trips it, while the float noise of a -te repr round-trip never does. -> PLAN Antarctica precondition.
    """
    if not path.exists():
        return False
    with rasterio.open(path) as dataset:
        return (dataset.width == width and dataset.height == height
                and all(math.isclose(actual, expected, abs_tol=1.0)
                        for actual, expected in zip(tuple(dataset.bounds), tuple(bounds))))


def warp_needs_rebuild(out: Path, grid, *inputs: Path) -> bool:
    """Whether a 3857 warp target must be rebuilt: `is_stale` (a source moved) OR off `grid`
    (a re-fuse resized the planet under it). `grid` is (width, height, bounds).

    Split out so the composed condition is testable on its own. The load-bearing case is the one
    `is_stale` alone cannot see: a raster whose SOURCE is unchanged but whose grid shrank beneath it.
    """
    return is_stale(out, *inputs) or not grid_matches(out, *grid)


def write_if_changed(path: Path, text: str) -> Path:
    """Write `text` to `path` only when it differs, and return `path`.

    The only-when-different part is load-bearing, not an optimisation: it lets a generated
    file stand in as a dependency for `is_stale`. Tunables like KNOBS and the ramp colours
    live in source, whose mtime moves on any `git checkout` and would force a full planet
    rebuild; materialised here, their mtime moves if and only if a VALUE actually changed.
    """
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
    return path


# KNOBS entries consumed by the HILLSHADE stage rather than by composite(). Excluded from
# composite_params below.
#
# The exclusion is not an optimisation, it is correctness: these already have a file of their own
# (hs_params.json), and they reach planet_rgb through composite_deps' dependency on `hs` -- change
# one, the hillshade restages, its mtime moves, and the composite restages behind it. Recording
# them HERE as well would restage a 53.8 min composite + 3:44 tile cut for byte-identical pixels
# every time the fill is merely present at strength 0 -- which is exactly what it did when
# `fill_strength` was first added to KNOBS (caught before any pass ran).
#
# `alt` is deliberately NOT in here: the hillshade takes it AND composite reads it (`flat =
# 255*sin(alt)`), so it belongs in both records. The filter defaults to INCLUDE, so a new composite
# knob is tracked unless someone deliberately names it here.
HILLSHADE_ONLY_KNOBS = frozenset({"fill_strength", "shadow_strength", "shadow_reach"})


def hs_params(body: bodies.Body) -> str:
    """The hillshade's tunables, recorded as hs_3857's dependency — composite_params' sibling.

    Takes the body because the exaggeration is one of those tunables and belongs to the planet, not
    to this module. Recording it was already right; sourcing it from a module constant was not, and
    the two were indistinguishable while Earth was the only body. Earth's sidecar is unmoved — its
    field holds the value the constant did — so this cannot restage the live pyramid.

    Split out of build_hillshade so BOTH halves of the freshness contract are
    testable from the outside. The asymmetry was itself the hazard: composite_params had tests
    pinning what it must and must not record, and this side had none, while every freshness bug so
    far has been a tunable that failed to reach one of these two records.

    The fill sun's geometry is recorded ONLY when it is actually on. This exists to answer "would a
    rerun produce different pixels?", and at strength 0 the fill provably cannot -- it is skipped
    entirely and the result is bit-identical (tests/test_hillshade.py). Recording it unconditionally
    would restage an 8:28 hillshade, a 53.8 min composite and a 3:44 tile cut to reproduce the same
    bytes, and would falsely report the LIVE pyramid as stale. Turning the fill on flips this dict
    and correctly restages all three.

    Composite-stage knobs must NOT appear here: this raster cannot see them, so recording one
    restages an 11:48 hillshade that would produce identical bytes.
    """
    params: dict[str, Any] = {"exag": body.exaggeration, "alt": ALT, "az": AZ}
    # Recorded only when it is not the identity, the same rule the fill and the shadow follow below
    # and for the same reason: on Earth the scale is exactly 1.0, so writing it would restage an
    # 8:28 hillshade, a 53.8 min composite and a 3:44 cut to reproduce identical bytes. On any other
    # body it is a genuine input to every slope in the raster, and an untracked one would leave a
    # re-shaded planet reporting fresh.
    ground_scale = bodies.ground_metres_per_mercator_unit(body)
    if ground_scale != 1.0:
        params["ground_scale"] = ground_scale
    if KNOBS["fill_strength"] != 0.0:
        params["fill"] = {"strength": KNOBS["fill_strength"],
                          "alt": hillshade.FILL_ALTITUDE, "az": hillshade.FILL_AZIMUTH}
    # Same rule as the fill, for the same reason: recorded only when on, so adding the knob at 0.0
    # cannot restage a pyramid whose pixels are provably unchanged. `reach` rides inside the block
    # because it only alters pixels while the shadow is switched on.
    if KNOBS["shadow_strength"] != 0.0:
        params["shadow"] = {"strength": KNOBS["shadow_strength"],
                            "reach_px": int(KNOBS["shadow_reach"]),
                            "disc": cast_shadow.SUN_ANGULAR_DIAMETER}
    return json.dumps(params, sort_keys=True, indent=2)


def composite_params(variants, body: bodies.Body, rasters: frozenset[str],
                     window_rows=WINDOW_ROWS) -> str:
    """The composite's tunables, recorded as planet_rgb's dependency.

    KNOBS and the palette colours never reach a file of their own, so without this a knob or
    palette edit (WATER_RGB -> 8EC6C4, or a lake-ramp re-tune) would leave a stale planet_rgb
    looking fresh. LAKE_STOPS earns its place the hard way: an untracked colour relationship
    is exactly how WATER_RGB drifted silently against the sea. `lake_curve` needs no entry of
    its own -- it rides in KNOBS. Must be read BEFORE the variant loop, which mutates KNOBS.

    `window_rows` (the composite window height) is recorded because it is NOT just a RAM lever:
    it slices the SVF occlusion per window, so a change perturbs the output sub-perceptibly (the
    256->128 A/B). Without it here, switching the production window height would leave a
    stale planet_rgb looking fresh -- the same untracked-input trap as WATER_RGB. `max_workers` is
    deliberately NOT recorded: threading is byte-identical (proven), so it changes no pixel.

    HILLSHADE_ONLY_KNOBS are filtered out -- see its comment: they are tracked by hs_params.json and
    arrive here through `hs`, so repeating them would force composites that change nothing.
    """
    knobs = {key: value for key, value in KNOBS.items() if key not in HILLSHADE_ONLY_KNOBS}
    # THE LAYERS THAT ARE OFF, never the ones that are on — the conditional-record idiom that `fill`,
    # `shadow` and `ground_scale` already follow. Earth has every layer, so its list is empty and
    # nothing is written: the live 46 GB composite stays fresh. A body missing one records it, and
    # turning a layer off on a body that had it correctly restages, which file mtimes cannot do —
    # `newest_mtime` scores an absent path 0.0, so an unbuilt raster is silently not a dependency.
    #
    # COMPOSITE_LAYERS, not the whole vocabulary: the caps read a coastline and this stage does not,
    # so enumerating every layer here would make a cap-only decision restage the planet.
    #
    # `rasters_off` is the same idiom one tier up, and it tracks the OTHER direction of the same
    # trap. When a mask APPEARS, `warp_inputs` builds it and `composite_deps` sees a new mtime, so
    # the composite restages on its own. When one goes AWAY, nothing moves at all: the old
    # `ocean_3857.tif` is still sitting on disk from the last run, and the composite painted with it
    # reads perfectly fresh. That is exactly the loop Phase 2 runs on Mars — a shoreline contour,
    # then a different one, then none — so the transition that has no mtime behind it needs a record.
    absent_layers = bodies.layers_off(body, bodies.COMPOSITE_LAYERS)
    absent_rasters = planet_seam.rasters_off(rasters)
    missing: dict[str, list[str]] = {}
    if absent_layers:
        missing["layers_off"] = absent_layers
    if absent_rasters:
        missing["rasters_off"] = absent_rasters
    return json.dumps({**missing, "knobs": knobs, "water_rgb": palette.WATER_RGB,
                       "composite_window_rows": window_rows,
                       # The occlusion resolution reached NO freshness record at all --
                       # it was a module constant (`SVF_LONG_EDGE`, now OCCLUSION_TARGET_M_PER_PX)
                       # that visibly changes planet_rgb, so moving it left a stale pyramid looking
                       # fresh. Same untracked-input trap as WATER_RGB and snow's RAMP_* constants.
                       # It rides in `knobs`' company rather than inside it because it is a
                       # resolution, not an art dial, and `--knob` must not reach it.
                       "occlusion_target_m_per_px": sky_view.OCCLUSION_TARGET_M_PER_PX,
                       # land/sea stops moved in here when color-relief was
                       # deleted: they used to be tracked by ramp_{land,sea}.txt's mtime, whose
                       # whole purpose was to gate the gdaldem stages. With those gone, nothing
                       # else would notice a ramp re-tune and planet_rgb would sit falsely fresh
                       # -- the exact failure this function exists to prevent.
                       "land_stops": palette.LAND_STOPS, "sea_stops": palette.SEA_STOPS,
                       "land_max_m": palette.LAND_MAX_M, "sea_min_m": palette.SEA_MIN_M,
                       "lut_step_m": palette.LUT_STEP_M,
                       "snow_rgb": palette.SNOW_RGB,
                       "snow_shadow_rgb": palette.SNOW_SHADOW_RGB,
                       "ice_rgb": palette.ICE_RGB,
                       "ice_shadow_rgb": palette.ICE_SHADOW_RGB,
                       # sea-ice alpha knobs run at composite time inside seaice.ice_alpha, so they
                       # ride here (not in composite_deps) -- the untracked-input trap that let snow's
                       # RAMP_* constants slip freshness; do not repeat it.
                       "ice_lo": seaice.ICE_LO, "ice_band": seaice.ICE_BAND,
                       "ice_max_alpha": seaice.ICE_MAX_ALPHA,
                       # The toned SH pack (seaice.SH_ICE_*) runs at composite time for southern
                       # windows, so it rides here too -- the same untracked-input trap the globals
                       # above avoid. A re-tune must restage the composite.
                       "sh_ice_lo": seaice.SH_ICE_LO, "sh_ice_max_alpha": seaice.SH_ICE_MAX_ALPHA,
                       "lake_stops": palette.LAKE_STOPS,
                       "lake_max_m": palette.LAKE_MAX_M,
                       "cap": [CAP_NORTH, CAP_SOUTH, list(CAP_RGB)],
                       "variants": {str(name): knobs for name, knobs in variants.items()}},
                      sort_keys=True, indent=2)


def composite_deps(work, hs, params) -> tuple:
    """Everything planet_rgb must be newer than.

    `height_3857.tif` replaced land_3857/sea_3857 here: composite() now applies the
    ramps itself from elevation, so the height raster IS the colour input. The ramp constants ride
    in `params` (composite_params) rather than in ramp_*.txt, which no longer exists.

    `snow_persistence_3857.tif` + `glacier_3857.tif` joined (optimisation #4): the
    composite reads pre-warped snow slices per window instead of forking gdalwarp/gdal_rasterize in
    the loop, so a re-warp (new NSIDC/RGI, or a re-fuse to a new grid) must restage it. `glacier`
    may be absent (RGI not downloaded) -- `newest_mtime` scores a missing path 0.0, so listing it
    unconditionally is safe. The ramp TUNABLES (`RAMP_*`) run at composite time inside `snow_alpha`,
    so they ride in `composite_params`, NOT here -- this pair tracks the warp SOURCES only.

    `seaice_3857.tif` joined, the sea-side twin of snow persistence: its warp SOURCE is
    tracked here, its ICE_LO/ICE_BAND alpha knobs in `composite_params`. Optional -- a missing path
    scores `newest_mtime` 0.0, so listing it unconditionally is safe when the source isn't built.

    THAT SAFETY CUTS THE OTHER WAY AND IS WHY `composite_params` RECORDS THE ABSENT LAYERS. A path
    that scores 0.0 is not merely harmless, it is INVISIBLE: switching a layer off leaves the old
    composite — painted with that layer — looking perfectly fresh against a dependency list that can
    no longer see it. The mtimes here track a layer that is ON; the recipe is what tracks one going
    OFF.

    SO THIS LIST IS DELIBERATELY OVER-INCLUSIVE, AND ITS SIBLING `cap_render.cap_sources` IS
    DELIBERATELY EXACT. That reads like an inconsistency and is not: the two feed different
    predicates. `is_stale` merely takes the newest mtime, so naming an input this planet does not
    have costs nothing. `cap_is_fresh` requires every source to EXIST, so naming one there pins the
    cap to a file that will never appear and leaves it permanently stale. Unifying them would mean
    making this one exact, which trades a harmless imprecision for the chance to under-track — and
    under-tracking is the direction that is silent. `test_the_two_freshness_predicates_disagree_on_a
    _missing_input` is the executable form of this paragraph; read it before changing either.
    """
    return (work / "height_3857.tif", hs, work / "ocean_3857.tif", work / "water_3857.tif",
            work / "lakedepth_3857.tif", work / "snow_persistence_3857.tif",
            work / "glacier_3857.tif", work / "seaice_3857.tif", params)


def body_declares_layer(body: bodies.Body, layer: str, consequence: str) -> bool:
    """Whether this body has `layer` at all — the body half of the gate, on its own.

    SPLIT OUT BECAUSE ONE RULE HAS NO DATASET BEHIND IT. The forced Antarctic land-ice patch is pure
    latitude-and-land arithmetic (`snow.antarctic_snow_mask`), so there is no file whose absence
    could ever switch it off — on a sea-less body it would simply whiten every piece of land below
    60 degrees south. It rides the `snow` layer, and this is what lets it ask that question with the
    same words and the same printed consequence as the four layers that do read a file.
    """
    if layer not in body.surface_layers:
        print(f"{body.name} declares no {layer} layer -> skipped ({consequence})", flush=True)
        return False
    return True


def layer_is_buildable(body: bodies.Body, layer: str, source: Path, consequence: str) -> bool:
    """Whether this body's `layer` can be warped — asked of the BODY first, then of the disk.

    THE ORDER IS THE POINT, and it is structural here rather than a convention: the body half is a
    separate function and this one calls it first. Each of these sources is a module constant at a
    fixed global path, so `source.exists()` answers "have we downloaded Earth's data" for every
    planet alike. Asking it first would let a second body pass the check on Earth's file and paint
    Earth's cryosphere onto its own grid — at the same latitudes, so it renders as a perfectly
    plausible planet.

    Both branches print, and each states the consequence rather than only the cause: a skipped layer
    is a look decision, and a pass that goes quiet about one is a pass whose output cannot be read
    back. Returning False rather than raising keeps a partial build legal, which is what makes the
    layers switchable at all.
    """
    if not body_declares_layer(body, layer, consequence):
        return False
    if not source.exists():
        print(f"no {source.name} -> {layer} skipped ({consequence})", flush=True)
        return False
    return True


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
    height = work / "height_3857.tif"
    if is_stale(height, planet / "planet_heightfield.vrt", chunks):
        print("warp height -> 3857 ...", flush=True)
        height.unlink(missing_ok=True)  # gdalwarp UPDATES an existing target; it must be gone
        resolution = body.map_units_per_pixel
        _run(["gdalwarp", "-q", "-t_srs", "EPSG:3857", "-tr", resolution, resolution, "-tap",
              "-r", "bilinear", "-ot", "Float32", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
              "-co", "BIGTIFF=YES", "-co", "NUM_THREADS=ALL_CPUS",
              planet / "planet_heightfield.vrt", height])
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
            print(f"{body.name}'s planet stage emitted no {raster} -> {name}_3857 skipped "
                  f"(the composite reads None and treats every pixel as land)", flush=True)
            continue
        src = f"planet_{raster}.vrt"
        out = work / f"{name}_3857.tif"
        if warp_needs_rebuild(out, grid, planet / src, chunks):
            print(f"warp {name} -> 3857 ...", flush=True)
            out.unlink(missing_ok=True)
            _run(["gdalwarp", "-q", "-t_srs", "EPSG:3857", "-te", *bounds, "-ts", *size,
                  "-r", "near", "-ot", "Byte", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
                  "-co", "BIGTIFF=YES", planet / src, out])
            mark_done(out)

    # GLOBathy lake depth, warped ONCE here rather than per window: it is an 83k-source VRT,
    # and a many-source VRT re-reads every source on each touch (the same reason the tiler
    # materialises before cutting). Deliberately NOT in the loop above -- depth is continuous,
    # so it needs bilinear/Float32, while `near`/Byte is right for the class codes and would
    # quantise every lake to whole metres and hard-step its gradient.
    # Its dependency is the VRT alone, unlike the chunk directory above: extract_globathy
    # rebuilds the VRT whenever the raster set changes, so its mtime really does move.
    depth_out = work / "lakedepth_3857.tif"
    if layer_is_buildable(body, "lake_depth", lake_depth.LAKE_VRT,
                          "lakes stay flat; run pipeline.acquire.extract_globathy") \
            and warp_needs_rebuild(depth_out, grid, lake_depth.LAKE_VRT):
        print("warp lake depth -> 3857 ...", flush=True)
        depth_out.unlink(missing_ok=True)
        _run(["gdalwarp", "-q", "-t_srs", "EPSG:3857", "-te", *bounds, "-ts", *size,
              "-srcnodata", str(lake_depth.GLOBATHY_NODATA), "-dstnodata", "0",
              "-r", "bilinear", "-ot", "Float32", "-co", "TILED=YES",
              "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=YES",
              "-co", "NUM_THREADS=ALL_CPUS", lake_depth.LAKE_VRT, depth_out])
        mark_done(depth_out)

    # Snow persistence + RGI glaciers, warped ONCE here rather than per window (optimisation #4).
    # The old composite loop forked gdalwarp + gdal_rasterize for every window (~728 subprocesses)
    # into two fixed-path temps -- the shared paths that blocked threading the composite. Same
    # precedent as lakedepth above. Persistence stores the RAW PACKED Float32 (snow.warp_persistence_
    # raster's docstring: the composite unpacks per window in float64, so a slice is bit-identical to
    # the old per-window warp). Glacier is a 0/1 Byte mask; absent RGI leaves it unbuilt and the snow
    # is persistence-only, exactly as before.
    persistence_out = work / "snow_persistence_3857.tif"
    if layer_is_buildable(body, "snow", snow.SP_NC,
                          "no snow painted; the composite reads None and skips it") \
            and warp_needs_rebuild(persistence_out, grid, snow.SP_NC):
        print("warp snow persistence -> 3857 (banded) ...", flush=True)
        persistence_out.unlink(missing_ok=True)
        # band_rows == the composite window height, aligned to it: each band is exactly the
        # per-window warp it replaces, so the mosaic is byte-identical to the old per-window path.
        # A single whole-grid warp would DECIMATE this coarse source (snow.warp_persistence_raster).
        snow.warp_persistence_raster(grid_bounds, grid_width, grid_height, persistence_out,
                                     band_rows=WINDOW_ROWS)
        mark_done(persistence_out)

    glacier_out = work / "glacier_3857.tif"
    if layer_is_buildable(body, "glaciers", snow.RGI_GPKG, "persistence-only snow") \
            and warp_needs_rebuild(glacier_out, grid, snow.RGI_GPKG):
        print("rasterize RGI glaciers -> 3857 ...", flush=True)
        snow.rasterize_glaciers_raster(grid_bounds, grid_width, grid_height, glacier_out)
        mark_done(glacier_out)

    # Sea-ice frequency climatology, warped ONCE here like snow persistence (same banded warp: a
    # single whole-grid warp of the coarse 0.1deg source would decimate the ice edge). Optional,
    # like glacier/depth -- an absent source just skips it and the composite paints no ice, leaving
    # the bathymetry bare at the poles.
    seaice_out = work / "seaice_3857.tif"
    if layer_is_buildable(body, "sea_ice", seaice.SEAICE_SRC,
                          "bathymetry bare at the poles") \
            and warp_needs_rebuild(seaice_out, grid, seaice.SEAICE_SRC):
        print("warp sea-ice frequency -> 3857 (banded) ...", flush=True)
        seaice_out.unlink(missing_ok=True)
        seaice.warp_seaice_raster(grid_bounds, grid_width, grid_height, seaice_out,
                                  band_rows=WINDOW_ROWS)
        mark_done(seaice_out)
    return height


def build_hillshade(work: Path, height: Path, body: bodies.Body):
    """The seamless per-row-z hillshade (skip if fresh), at THIS body's vertical exaggeration.

    Was `color_and_hillshade`: the two `gdaldem color-relief` passes it also ran were deleted
    (28:19 and 24.4% of all pass CPU, single-threaded; profile said `libgdal` 19.37%
    interpolation vs `libdeflate` 4.33%, so no threading flag could reach it). composite() now
    applies the ramps from elevation via a 17.6 KB LUT -- verified against gdaldem's own output
    over all 12.19 G px, 6/6 bands, zero pixels beyond 1 DN.
    """
    hs = work / "hs_3857.tif"
    hs_params_path = write_if_changed(work / "hs_params.json", hs_params(body))
    if is_stale(hs, height, hs_params_path):
        fill_note = (f", fill {KNOBS['fill_strength']:.2f}" if KNOBS["fill_strength"] else "")
        shadow_note = (f", shadow {KNOBS['shadow_strength']:.2f}" if KNOBS["shadow_strength"]
                       else "")
        print(f"per-row-z hillshade (exag={body.exaggeration}{fill_note}{shadow_note}) ...",
              flush=True)
        hillshade.per_row_zfactor_hillshade(
            height, hs, body.exaggeration, ALT, AZ,
            fill_strength=KNOBS["fill_strength"],
            shadow_strength=KNOBS["shadow_strength"],
            shadow_reach_px=int(KNOBS["shadow_reach"]),
            ground_scale=bodies.ground_metres_per_mercator_unit(body))
        mark_done(hs)
    return hs


def global_occlusion(height: Path, body: bodies.Body):
    """Sky-view occlusion (1 = valley, 0 = open) on a global downsample, normalised globally.

    Sized from `sky_view.OCCLUSION_TARGET_M_PER_PX` — the same constant the region path uses — so
    a region preview and the planet it predicts can no longer drift apart. `SVF_LONG_EDGE` was the
    old planet-only spelling of this and is now derived, not chosen.

    `occlusion_shape` and `normalised_occlusion` both document that they want a GROUND scale, and
    this function used to hand them a map-unit one. Two independent errors hid behind that, and only
    one of them is fixed here.

    FIXED: THE BODY TERM. Every projection in this pipeline is Earth-sphered, so a map unit is a
    ground metre only on Earth; elsewhere it is worth `ground_metres_per_mercator_unit(body)`. On
    Mars the horizon run would be overstated by 1.878x, flattening the sky-view exactly where the
    relief is most dramatic. The factor is EXACTLY 1.0 for Earth by construction of EPSG:3857, so
    adopting it here moves no existing pixel.

    NOT FIXED: THE LATITUDE TERM, which is the older half and is Earth's. Ground metres in Web
    Mercator are also `cos(lat)` times map units, so the run is understated by `1/cos(lat)` —
    1.22x at 35N, 2.00x at 60N, 3.86x at 75N — and high latitudes come out systematically
    under-occluded. The global affine renormalisation provably cannot absorb a latitude-varying
    error. It stays out because it is a different KIND of change: it needs a per-ROW scale (the
    hillshade's z-factor trick) plus a decision about which latitude sizes the downsample, and it
    moves Earth's production pixels — a re-shade and a re-cut, judged on the sphere rather than
    accepted from a number. The region path already applies its own `cos(mid_lat)`, so the two
    shading paths disagree on this term today; that is the shape of the outstanding work.
    """
    ground = bodies.ground_metres_per_mercator_unit(body)
    ground_res = body.map_units_per_pixel * ground
    with rasterio.open(height) as dataset:
        full_w, full_h = dataset.width, dataset.height
        small_h, small_w = occlusion_shape(full_w, full_h, ground_res)
        low = dataset.read(1, out_shape=(small_h, small_w),
                           resampling=Resampling.average).astype(float)
    low = np.nan_to_num(np.where(low < -500, np.nan, low), nan=0.0)
    m_per_px = ground_res * (full_w / small_w)
    return normalised_occlusion(low, m_per_px)  # shape (small_h, small_w)


def read3_window(path, window):
    with rasterio.open(path) as dataset:
        return dataset.read([1, 2, 3], window=window).astype(np.float32)


def read1_window(path, window):
    with rasterio.open(path) as dataset:
        return dataset.read(1, window=window)


@dataclass
class _WindowInputs:
    """One window's RAW reads plus its geometry — everything a window needs from disk.

    Populated on the MAIN thread only: rasterio datasets are not thread-safe, so every GDAL
    read lives here and the pure-numpy compute (`_compute_shared`/`_compose`) takes this bundle.
    The fields are the untransformed slices (`ocean_raw`, not `ocean != 0`); the cheap numpy
    that derives masks/alpha from them runs on the worker, which is where optimisation #5 wants
    the CPU. `depth_raw`/`glacier_raw`/`sea_ice_raw` are None when that optional input was never built.

    `ocean_raw`/`watercode` are None on a planet whose seam emitted no masks, and that is a
    DIFFERENT kind of None from the four above: theirs says an Earth dataset was not downloaded,
    this one says the planet has no sea. `_compute_shared` turns it into an all-False selector,
    which is the true answer rather than a stand-in — no pixel is ocean, none is inland water, and
    every pixel is land.
    """

    win: Window
    win_h: int
    win_top: float
    win_bottom: float
    height_win: np.ndarray
    ocean_raw: "np.ndarray | None"
    watercode: "np.ndarray | None"
    hs_raw: np.ndarray
    depth_raw: np.ndarray | None
    persistence_raw: np.ndarray | None
    glacier_raw: np.ndarray | None
    sea_ice_raw: np.ndarray | None
    occ_win: np.ndarray
    #: Which planet this window belongs to. Present for ONE decision — whether the Antarctic
    #: land-ice patch applies — and deliberately not for paths: this struct crosses onto worker
    #: threads, and a stage that reads the filesystem there would leave `_compute_shared` impure.
    body: bodies.Body


@dataclass
class _WindowShared:
    """The per-window work that does NOT depend on the sea knobs, so a multi-variant pass
    computes it once and every variant's `_compose` reuses it. Snow alpha, the polar-cap mask
    and the three masks are all variant-independent; only `shade.composite`'s sea-light math
    (and thus the KNOBS it reads) differs between variants.
    """

    ocean_win: np.ndarray
    water_win: np.ndarray
    hs_win: np.ndarray
    depth_win: np.ndarray | None
    snow_a: np.ndarray
    ice_a: np.ndarray | None
    cap: np.ndarray


def _compute_shared(inputs: _WindowInputs) -> _WindowShared:
    """Derive the variant-independent per-window arrays from the raw reads (pure numpy).

    This is exactly the old loop's pre-variant body, lifted out verbatim so the serial and
    threaded paths run identical arithmetic on identical inputs — byte-identity by construction.
    Runs on a worker thread in the threaded path; numpy releases the GIL, which is the whole
    basis of optimisation #5.
    """
    # ALL-FALSE, NOT A SYNTHESISED RASTER, and the difference is the whole of Gap A. A planet with
    # no sea could have been given an all-zero ocean mask on disk, and nothing downstream would have
    # needed a line changed — but that file is indistinguishable from one produced by measuring the
    # planet's oceans and finding none, and it would be the only body fact in this project expressed
    # as a fabricated dataset. Built here instead, from the seam's declaration, it is a computation
    # with a stated premise. `shade.composite` needs no branch either way: its eight selectors are
    # boolean, and all-False means land everywhere, which is the answer.
    shape = inputs.height_win.shape
    ocean_win = inputs.ocean_raw != 0 if inputs.ocean_raw is not None else np.zeros(shape, bool)
    watercode = inputs.watercode
    water_win = (lake_depth.inland_water(watercode) if watercode is not None
                 else np.zeros(shape, bool))
    hs_win = inputs.hs_raw.astype(float)
    # Lake depth, zeroed off class 2 so rivers stay flat and the (class 1) Caspian keeps GEBCO's
    # measured bathymetry instead of GLOBathy's cone. The watercode cannot be None while depth is
    # not: `planet_seam` refuses a body that declares the lake-depth layer with no watermask.
    depth_win = (lake_depth.lakes_only(inputs.depth_raw, watercode)
                 if inputs.depth_raw is not None and watercode is not None else None)
    # unpack_persistence runs the float64 unpack per window (as the old per-window path did), so
    # snow_alpha sees bit-identical input. Glacier is optional (persistence-only when RGI absent).
    if inputs.persistence_raw is not None:
        persistence_win = snow.unpack_persistence(inputs.persistence_raw)
        snow_a = snow.snow_alpha(persistence_win, inputs.win_top, inputs.win_bottom)
    else:
        # float, not float32: this is what `snow_alpha` returns, and the maxima below promote to it
        # anyway. Matching the dtype keeps the two branches feeding `composite` identical arrays.
        snow_a = np.zeros(inputs.height_win.shape, dtype=float)
    if inputs.glacier_raw is not None:
        snow_a = np.maximum(snow_a, inputs.glacier_raw.astype(float))
    latitude = snow.latitude_per_row(inputs.win_top, inputs.win_bottom, inputs.win_h)
    # Force Antarctic land white: NSIDC-0791 is NH-only and RGI region 19 is excluded, so snow_a is 0
    # over the continent and it would render on the tan LAND ramp. The same shared rule the south cap
    # uses, so the two agree across the -84 seam (snow.antarctic_snow_mask).
    land_win = ~(ocean_win | water_win)
    # ASKED OF THE BODY, not of the raster. The rule is a patch on the snow layer's own hole, so a
    # body without that layer has nothing to patch — and this is a latitude+land test with no
    # dataset behind it, so nothing else could ever turn it off. On a sea-less planet it whitens
    # every piece of land below 60 degrees south, which is most of one.
    if "snow" in inputs.body.surface_layers:
        snow_a = np.maximum(snow_a, snow.antarctic_snow_mask(land_win, latitude))
    # Sea-ice alpha: frequency -> smoothstep, the sea-side twin of snow_a (no latitude ramp needed).
    # Optional (None when the seaice source was never warped); shade.composite gates it on ocean. South
    # of the equator the SH pack is toned to the cap's fainter, pulled-in fringe (seaice.SH_ICE_*), else
    # the full-strength Antarctic belt reads as a bright halo -- proven on the cap. No window straddles
    # both hemispheres' ice, and the equator is ice-free, so the per-row split is exact.
    if inputs.sea_ice_raw is not None:
        frequency = seaice.unpack_seaice(inputs.sea_ice_raw)
        ice_a = seaice.ice_alpha(frequency)
        southern = latitude < 0.0
        if southern.any():
            toned = seaice.ice_alpha(frequency, ice_lo=seaice.SH_ICE_LO,
                                     ice_max_alpha=seaice.SH_ICE_MAX_ALPHA)
            ice_a = np.where(southern[:, None], toned, ice_a)
    else:
        ice_a = None
    cap = (latitude > CAP_NORTH) | (latitude < CAP_SOUTH)
    return _WindowShared(ocean_win, water_win, hs_win, depth_win, snow_a, ice_a, cap)


def _compose(inputs: _WindowInputs, shared: _WindowShared) -> np.ndarray:
    """Shade one window into RGB with the CURRENT KNOBS, then force the polar edges flat.

    Reads KNOBS through `shade.composite`; on the threaded path KNOBS is never mutated mid-pass
    (single variant), so this is a pure function of its two arguments there. On the serial
    multi-variant path the caller mutates KNOBS between variants, exactly as before.
    """
    rgb = shade.composite(inputs.height_win, shared.ocean_win, shared.water_win, shared.snow_a,
                          shared.hs_win, inputs.occ_win, inputs.occ_win.shape,
                          (inputs.win_h, inputs.height_win.shape[1]), depth=shared.depth_win,
                          ice_a=shared.ice_a)
    if shared.cap.any():  # force the smeared polar edges to a flat deep-sea disc
        for band in range(3):
            rgb[band][shared.cap] = CAP_RGB[band]
    return rgb


def _compute_window_rgb(inputs: _WindowInputs) -> tuple[Window, np.ndarray]:
    """One worker unit: shared work + single-variant compose. Returns (window, rgb) so the main
    thread can write it in order. Used only by the threaded single-variant path."""
    return inputs.win, _compose(inputs, _compute_shared(inputs))


def composite_planet(work: Path, hs, compute_occlusion: Callable[[], np.ndarray],
                     body: bodies.Body, rasters: frozenset[str], variants=None,
                     window_rows=WINDOW_ROWS, max_windows=None, max_workers=1, row_start=0):
    """Composite the whole planet window-by-window into seamless RGB GeoTIFF(s).

    `variants` maps a name -> a dict of sea-knob overrides (sea_shade/sea_lift/sea_svf);
    each name is emitted as planet_rgb_<name>.tif in ONE shared pass — the expensive
    per-window work (reads, snow warp, glacier rasterize) is done once and only the cheap
    sea-light math + write differs per variant. `variants=None` keeps the production path:
    a single planet_rgb.tif shaded with the default KNOBS. `window_rows` is the RAM lever;
    `max_windows` (smoke test) stops after N windows, leaving a partially-filled raster.
    `row_start` begins the window loop below the top (for compositing one region, e.g. a
    256-vs-128 window-height A/B over a chosen latitude band); like `max_windows` it produces a
    partial raster, so it never marks the output done.

    `max_workers` > 1 threads the single-variant compute (optimisation #5): the main thread reads
    each window and writes the finished RGB back in window order, while up to `max_workers` workers
    run the pure-numpy `_compute_window_rgb` (numpy drops the GIL, so threads scale ~3x before DRAM
    bandwidth saturates -- measured). A bounded in-flight deque caps peak RAM at
    `max_workers + INFLIGHT_BUFFER` windows. Multi-variant passes IGNORE it and stay serial: that
    loop mutates the global KNOBS between variants, which is not safe to run concurrently.

    `compute_occlusion` is a CALLABLE, not the array itself, and that IS the sky-view guard.
    Measured on the first instrumented tile cut: computing it costs 2:33
    single-threaded reading the whole 31 GB master -- and on a tiles-only re-run the composite
    is fresh, so the array was built and discarded, 41% of that pass. Every other stage is
    gated by `is_stale`, but SVF has no file of its own to stamp, so deferring it behind the
    same freshness check is the equivalent guard. Keep the call BELOW the early return.
    """
    if variants is None:
        variants = {None: None}
    outs = {name: work / f"planet_rgb{f'_{name}' if name else ''}.tif" for name in variants}
    params = write_if_changed(work / "composite_params.json",
                              composite_params(variants, body, rasters, window_rows))
    deps = composite_deps(work, hs, params)
    # One shared params file is sound because every variant is composited in a single pass:
    # the guard rebuilds all of them or none.
    if max_windows is None and not any(is_stale(tif, *deps) for tif in outs.values()):
        print("planet_rgb fresh -> skip composite", flush=True)
        return outs
    print("global sky-view factor ...", flush=True)
    occ = compute_occlusion()
    with rasterio.open(work / "height_3857.tif") as h:
        width, height, transform = h.width, h.height, h.transform
    small_h, _small_w = occ.shape
    # dict[str, Any]: GDAL creation options are a heterogeneous bag, and `**profile` otherwise
    # hands rasterio.open's bool-typed `sharing`/`thread_safe` an inferred `str | int`.
    profile: dict[str, Any] = dict(
        driver="GTiff", width=width, height=height, count=3, dtype="uint8",
        crs="EPSG:3857", transform=transform, photometric="RGB", BIGTIFF="YES",
        num_threads="ALL_CPUS", **GTIFF_CREATE)
    ocean_p, water_p = work / "ocean_3857.tif", work / "water_3857.tif"
    depth_p = work / "lakedepth_3857.tif"
    persistence_p = work / "snow_persistence_3857.tif"
    glacier_p = work / "glacier_3857.tif"
    seaice_p = work / "seaice_3857.tif"

    def read_window(row0: int) -> _WindowInputs:
        """Gather one window's raw reads + geometry — MAIN thread only (GDAL is not thread-safe)."""
        row1 = min(height, row0 + window_rows)
        win = band_window(width, row0, row1)
        # sky-view occlusion slice for this window (smooth -> nearest rows are fine)
        sr0 = int(row0 / height * small_h)
        sr1 = max(sr0 + 1, round(row1 / height * small_h))
        return _WindowInputs(
            win=win, win_h=row1 - row0,
            win_top=transform.f + row0 * transform.e,
            win_bottom=transform.f + row1 * transform.e,
            height_win=read1_window(work / "height_3857.tif", win),
            # Gated on the SEAM'S DECLARATION, never on `ocean_p.exists()`. A declared mask that is
            # missing from disk must crash here — the planet said it has one — where an existence
            # check would quietly composite a sea-less Earth after a half-finished warp.
            ocean_raw=read1_window(ocean_p, win) if "oceanmask" in rasters else None,
            watercode=read1_window(water_p, win) if "watermask" in rasters else None,
            hs_raw=read1_window(hs, win),
            depth_raw=read1_window(depth_p, win) if depth_p.exists() else None,
            # The fourth of four, and the one that was not guarded. Its three siblings have read
            # this way for a long time; snow did not, so a body whose snow layer is off crashed
            # here on a raster that was never built.
            persistence_raw=read1_window(persistence_p, win) if persistence_p.exists() else None,
            glacier_raw=read1_window(glacier_p, win) if glacier_p.exists() else None,
            sea_ice_raw=read1_window(seaice_p, win) if seaice_p.exists() else None,
            occ_win=occ[sr0:sr1],
            body=body)

    rows = list(range(row_start, height, window_rows))
    if max_windows is not None:  # smoke test: only the first N windows
        rows = rows[:max_windows]
    # Thread ONLY the production single-variant path (see the docstring): the A/B loop mutates the
    # shared KNOBS, so it stays serial. Both paths run the SAME `_compute_shared`/`_compose`, so a
    # single-variant threaded pass is byte-identical to the serial one by construction.
    threaded = max_workers > 1 and len(variants) == 1
    started = time.monotonic()
    writers = {name: rasterio.open(tif, "w", **profile) for name, tif in outs.items()}
    try:
        if threaded:
            writer = writers[next(iter(variants))]
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                inflight: deque[Any] = deque()  # futures, oldest first -> writes stay in order
                for index, row0 in enumerate(rows):
                    inflight.append(pool.submit(_compute_window_rgb, read_window(row0)))
                    if len(inflight) >= max_workers + INFLIGHT_BUFFER:
                        win, rgb = inflight.popleft().result()  # block on the oldest, then write
                        writer.write(rgb, window=win)
                        del rgb
                    if index % 20 == 0:
                        gc.collect()
                        print(f"  composited rows {row0}/{height}", flush=True)
                while inflight:  # drain the tail in order
                    win, rgb = inflight.popleft().result()
                    writer.write(rgb, window=win)
                    del rgb
        else:
            for index, row0 in enumerate(rows):
                inputs = read_window(row0)
                shared = _compute_shared(inputs)
                for name, knobs in variants.items():
                    if knobs:
                        # Variant keys are data, not literals, so they take the same untyped view
                        # of KNOBS that shade.py's --knob override does.
                        cast(dict[str, Any], KNOBS).update(knobs)  # only the sea knobs differ
                    rgb = _compose(inputs, shared)
                    writers[name].write(rgb, window=inputs.win)
                    del rgb
                # release the window's big arrays each iteration so RSS can't creep up over the
                # hundreds of windows (fragmentation growth OOM-killed the earlier float64 runs).
                del inputs, shared
                if index % 20 == 0:
                    gc.collect()
                    print(f"  composited rows {row0}/{height}", flush=True)
    finally:
        for writer in writers.values():
            writer.close()
    elapsed = time.monotonic() - started
    mode = f"threaded x{max_workers}" if threaded else "serial"
    print(f"composite: {len(rows)} windows in {elapsed:.1f}s "
          f"({len(rows) / max(elapsed, 1e-9):.2f} win/s, {mode})", flush=True)
    if max_windows is None and row_start == 0:  # a partial raster (smoke/region) is never done
        for tif in outs.values():
            mark_done(tif)
    for tif in outs.values():
        print(f"wrote {tif}", flush=True)
    return outs


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

    The recipe is written BEFORE the freshness question is asked, so changing the cut is what
    triggers its own re-cut; `write_if_changed` means an unchanged recipe never moves an mtime and
    never restages a pyramid that is still correct.

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
        print("tiles fresh -> skip cut", flush=True)
        return
    staging = out / "tiles_new"
    if staging.exists():
        _run(["rm", "-rf", str(staging)])   # a partial from a prior mid-cut crash: never resume over it
    print(f"cutting z{cut['min_zoom']}-{cut['max_zoom']} {cut['tile_size']}px tiles "
          f"-> {staging} ...", flush=True)
    _run(_tile_cmd(planet_tif, staging, body))
    live = out / "tiles"
    if live.exists():
        old = out / "tiles_old"
        if old.exists():
            _run(["rm", "-rf", str(old)])
        live.rename(old)
    staging.rename(live)
    mark_done(live)
    print(f"tiles live -> {live} (previous kept at {out / 'tiles_old'})", flush=True)


def build_parser() -> argparse.ArgumentParser:
    """The CLI, split out of `main` so its contract is testable without running a pass."""
    ap = argparse.ArgumentParser()
    # REQUIRED, WITH NO DEFAULT, and that is the whole point. A pass that assumes Earth because
    # nobody said otherwise does not fail — it produces a complete, plausible, entirely wrong
    # pyramid, and the cost of discovering that late is a planet. Naming it costs one word.
    ap.add_argument("--body", required=True,
                    help=f"which planet this pass is for ({', '.join(sorted(bodies.BODIES))})")
    # Optional override. Left unset it follows the body, which also honours the MAPS_DATA seam its
    # checkout-rooted default used to bypass; set, it is how a look A/B is pointed elsewhere. The
    # old spelling is described rather than quoted — `tests/test_paths.py` scans for it, and a
    # comment reproducing it re-creates the needle the scan exists to find.
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--tiles", action="store_true",
                    help="also cut tiles from the mosaic, z0 to the body's own ceiling")
    ap.add_argument("--knob", action="append", default=[], metavar="KEY=VALUE",
                    help="override a locked KNOBS entry (repeatable), as tile/shade.py does. "
                         "Look changes used to be made by EDITING the constant, which meant an "
                         "experiment and production shared one source of truth. Overrides are "
                         "safe for freshness by construction: composite_params/hs_params "
                         "serialise KNOBS, so an override restages exactly what it changes and "
                         "the recorded params always describe the pyramid that exists.")
    return ap


def resolve_body(args: argparse.Namespace) -> bodies.Body:
    """The body this run is for. Raises through the registry, which names the ones that exist."""
    return bodies.get(args.body)


def cap_pass_command(body: bodies.Body) -> list[str]:
    """The command that renders this body's polar caps at the tail of a shade pass.

    Built here rather than spelled inline because the body crosses a PROCESS boundary as a string
    on a command line, which is the one hop the registry cannot type-check. Left off, the cap pass
    would refuse to start (its `--body` is required too) — which is the failure this shape converts
    into a hard stop instead of a Mars pass quietly re-rendering Earth's poles.
    """
    return [sys.executable, "-m", "pipeline.tile.cap_render", "--body", body.name]


def resolve_out(args: argparse.Namespace) -> Path:
    """Where this run writes: the explicit `--out`, else the body's own tile-work directory."""
    return args.out if args.out is not None else bodies.work_dir(resolve_body(args), "planet_tiles")


def main():
    args = build_parser().parse_args()
    # A key off argv is dynamic by construction, so a TypedDict cannot check it -- this view is
    # the honest escape hatch, and the membership test below is what actually validates the key.
    knobs = cast(dict[str, Any], KNOBS)
    for override in args.knob:
        key, _, value = override.partition("=")
        if key not in knobs:
            raise SystemExit(f"unknown knob {key!r}; valid: {', '.join(sorted(knobs))}")
        knobs[key] = value if isinstance(knobs[key], str) else float(value)
        print(f"knob override: {key} = {knobs[key]}", flush=True)
    body = resolve_body(args)
    work = resolve_out(args)
    work.mkdir(parents=True, exist_ok=True)

    # Read ONCE, at the top, and threaded down. The planet stage declares what it emitted and this
    # raises if it never finished, so a half-built planet stops here rather than being shaded into a
    # plausible-looking pyramid. Threading it (rather than each stage reading the file) keeps
    # `_compute_shared` a pure function of its arguments, which is what lets it run on workers.
    rasters = planet_seam.declared(body)
    height = warp_inputs(work, planet_seam.planet_dir(body), body, rasters)
    hs = build_hillshade(work, height, body)
    # Passed unevaluated: composite_planet runs it only if the composite is actually stale.
    # Production composite is threaded at COMPOSITE_ROWS/N_WORKERS (optimisation #5); the snow
    # persistence stays banded at WINDOW_ROWS (256), sliced 128 rows at a time.
    planet_tif = composite_planet(work, hs, lambda: global_occlusion(height, body), body, rasters,
                                  window_rows=COMPOSITE_ROWS, max_workers=N_WORKERS)[None]
    if args.tiles:
        build_tiles(planet_tif, work, body)
    # The polar caps are shade-stage outputs too: they run the same composite over the same
    # sources, so a look change that restages planet_rgb must restage them. Both caps once sat
    # stale against the tiles they feather into (the north −6.7 DN adrift) because nothing
    # coupled them to the recipe. cap_render guards
    # itself (cap_is_fresh), so a fresh pass pays only the ~2 s import here. Subprocess, not
    # import: cap_render imports FROM this module, and the caps' pyproj/scipy stack stays out
    # of the tile pass.
    print("polar caps ...", flush=True)
    subprocess.run(cap_pass_command(body), check=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
