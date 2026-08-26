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
  3. custom per-row-z hillshade (pipeline/look/hillshade.py) -> seamless + correct 15x;
  4. sky-view factor once on a global downsample with a single global normalisation;
  5. composite each full-width horizontal window (reusing tile/shade.py::composite) with the
     latitude-ramped snow (blue-white shadows) and RGI glaciers, and cap both polar edges
     (>84N, <-59.5S -> flat pale sea-ice) so MapLibre's globe shows clean polar discs;
  6. cut 512px tiles from z0 to THIS BODY's ceiling -- z8 for Earth, and the body says so rather
     than this module (no overview step: `gdal raster tile` never reads them; see build_tiles).

THIS MODULE IS NOT AN ENTRY POINT. It holds the shared stages above AND one of the two producers of
step 5; `tile/planet_pass.py` owns the sequence and picks the producer from the body, so that the
composite is not the host of its own alternative.

Every stage skips if its output is FRESH -- present, completed, and newer than everything it
derives from (`is_stale`). An exists()-only guard cannot tell "built" from "still correct":
the Caspian re-fuse rewrote 4 of the 540 chunks, and a plain re-run would have
skipped every stage and silently re-cut tiles from the pre-Caspian, pre-sea-rework rasters.
Grid matches the existing tile pyramid exactly (131072 x 131072 — square since Antarctica was
fused in; it was 131072 x 93009 while the pyramid stopped at -60).

    python -m pipeline.tile.planet_pass --body earth            # produce only
    python -m pipeline.tile.planet_pass --body earth --tiles    # + cut tiles
"""

import gc
import json
import subprocess
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

from pipeline import bodies, layers, mercator, planet_seam, progress, wrap_seam
from pipeline.freshness import (
    done_marker,
    is_stale,
    mark_done,
    reference_needs_rebuild,
    warp_needs_rebuild,
    write_if_changed,
)
from pipeline.look import (
    hillshade,
    lake_depth,
    layer_producers,
    palette,
    sky_view,
    snow,
)
from pipeline.look.sky_view import normalised_occlusion, occlusion_shape
from pipeline.raster_io import GTIFF_CREATE, band_window
from pipeline.tile import producer_seam, shade
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
CAP_RGB = (216, 226, 233)   # pale sea-ice fill for the poles (web-mercator has no data past ~85 deg)
INFLIGHT_BUFFER = 2        # windows read AHEAD of the workers (optimisation #5): the main thread
                           # may queue max_workers + this many window-input bundles before it must
                           # block on the oldest result and write it. Bounds peak RAM to
                           # (max_workers + INFLIGHT_BUFFER) windows in flight; keep it small.


def _run(cmd):
    subprocess.run([str(part) for part in cmd], check=True)


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
                            "disc": palette.SUN_ANGULAR_DIAMETER_DEG}
    return json.dumps(params, sort_keys=True, indent=2)


def _ramp_origin(kind: str, ramp: palette.Surface) -> dict[str, float]:
    """`{kind}_origin_m`, recorded ONLY when the ramp does not start at the datum.

    The conditional-record idiom, for the fourth time in this module (`fill`, `shadow`,
    `ground_scale`) and for the identical reason. Earth's two ramps both hinge on 0 m, so an
    unconditional record would add a key to a 2,672-byte sidecar that has been stable across the
    whole shipped pyramid — restaging a 46 GB planet, a 21:37 composite and a 4:19 cut to reproduce
    byte-identical output, and reporting the LIVE pyramid stale on the way.

    Conditional is not the same as untracked, which is the trap this idiom always has to answer.
    The origin cannot move WITHIN a body without changing this dict, because the only two states
    are absent (0 m) and present (some other number) — and a body moving off the datum flips it
    from absent to present, which is a change. What it deliberately cannot do is distinguish two
    bodies, and it does not have to: sidecars are per-body files.
    """
    return {} if ramp.origin_m == 0.0 else {f"{kind}_origin_m": ramp.origin_m}


def _when(evaluated: bool, values: dict[str, Any]) -> dict[str, Any]:
    """`values` when this body's composite evaluates them, `{}` when it cannot reach them.

    A body records only what can move its own pixels, so one body's re-tune cannot restage
    another's composite for output that could not have changed.

    Conditional is not untracked, and every caller has to earn that. A gate is correct only when
    the values behind it are unreachable while it is false, AND the gate itself rides in the
    recipe, so that opening it is a change: `layers_off` and `rasters_off` carry the layer and
    raster gates, `knobs` carries the knob gates.
    """
    return values if evaluated else {}


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
    # `layers.COMPOSITE_LAYERS`, not the whole vocabulary: the caps read a coastline and this stage
    # does not, so enumerating every layer here would make a cap-only decision restage the planet.
    #
    # `rasters_off` is the same idiom one tier up, and it tracks the OTHER direction of the same
    # trap. When a mask APPEARS, `warp_inputs` builds it and `composite_deps` sees a new mtime, so
    # the composite restages on its own. When one goes AWAY, nothing moves at all: the old
    # `ocean_3857.tif` is still sitting on disk from the last run, and the composite painted with it
    # reads perfectly fresh. That is exactly the loop Phase 2 runs on Mars — a shoreline contour,
    # then a different one, then none — so the transition that has no mtime behind it needs a record.
    absent_layers = layers.layers_off(body, layers.COMPOSITE_LAYERS)
    absent_rasters = planet_seam.rasters_off(rasters)
    missing: dict[str, list[str]] = {}
    if absent_layers:
        missing["layers_off"] = absent_layers
    if absent_rasters:
        missing["rasters_off"] = absent_rasters
    look = palette.look_for(body.name)
    # The sea ramp is recorded only when the body draws one — the conditional-record idiom this
    # function already uses for `layers_off` and `rasters_off`, and `hs_params` for `ground_scale`.
    # A body with no sea has no sea values to track, and writing nulls would put entries in the
    # recipe that no edit could ever move, which reads as tracked while tracking nothing.
    sea_recipe: dict[str, Any] = (
        {} if look.sea is None
        else {"sea_stops": look.sea.stops, "sea_min_m": look.sea.extreme_m,
              **_ramp_origin("sea", look.sea)}
    )
    declared = body.surface_layers
    # `snow_position` keys BOTH the snow and the sea-ice whites, so its curve constants are live
    # when either layer is painted.
    keys_white = bool({layers.PERENNIAL_ICE.name, layers.SEA_ICE.name} & declared)
    # WHAT EACH DECLARED LAYER'S OWN PRODUCER READS, asked of the producer rather than spelled out
    # here — `layer_producers.constants_for` carries why, for both stages that ask it.
    #
    # `painted=True` because this stage blends the contribution and the white in one pass, so both
    # halves of a producer's declaration reach a pixel here; the block render reads one of the two.
    #
    # Order-free by construction: `sort_keys` below normalises the output, so where a key enters
    # this dict cannot move a byte of a live sidecar.
    produced = layer_producers.constants_for(body, layers.COMPOSITE_LAYERS, painted=True)
    return json.dumps({**missing, **sea_recipe, **produced,
                       "knobs": knobs,
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
                       # Read off the BODY'S look, not the module globals. Those globals are
                       # Earth's, so every planet's recipe used to record Earth's ramp — and this
                       # dict is precisely what decides whether a look change restages. A Mars
                       # re-tune would have left the Mars composite reading fresh.
                       "land_stops": look.land.stops,
                       "land_max_m": look.land.extreme_m,
                       **_ramp_origin("land", look.land),
                       "lut_step_m": palette.LUT_STEP_M,
                       # Inland water is filled flat with this colour, so it is live only where a
                       # watermask exists to select it.
                       **_when("watermask" in rasters, {"water_rgb": palette.WATER_RGB}),
                       **_when(layers.LAKE_DEPTH.name in declared,
                               {"lake_stops": palette.LAKE_STOPS,
                                "lake_max_m": palette.LAKE_MAX_M}),
                       # BOTH WHITE PAIRS MOVED INTO `produced` ABOVE, where the producer that
                       # paints with them declares them. This gate said "one white family for every
                       # body's perennial ice", which held while Earth was the only body painting
                       # any and fails twice over now: a second body arrived, and its two poles
                       # measure as different colours from each other. A layer gate can only hold
                       # one value per layer, so it had no way to be right for both.
                       #
                       # Earth's keys and values are unchanged — `produced` merges flat into this
                       # dict and `sort_keys` normalises it — so this move restages nothing.
                       # `shadow_tint` returns exactly 1.0 at warmth 0, bit-identical to not being
                       # called, so the tint vector is live only above it.
                       **_when(KNOBS["shadow_warmth"] != 0.0,
                               {"shadow_tint": list(shade.SHADOW_TINT)}),
                       # One branch of `snow_position`; the other curves never read them.
                       **_when(KNOBS["snow_curve"] == "knee" and keys_white,
                               {"knee_x": shade.KNEE_X, "knee_share": shade.KNEE_SHARE}),
                       "cap": [CAP_NORTH, CAP_SOUTH, list(CAP_RGB)],
                       "variants": {str(name): knobs for name, knobs in variants.items()}},
                      sort_keys=True, indent=2)


def composite_deps(work, hs, params) -> tuple:
    """Everything planet_rgb must be newer than.

    `height_3857.tif` replaced land_3857/sea_3857 here: composite() now applies the
    ramps itself from elevation, so the height raster IS the colour input. The ramp constants ride
    in `params` (composite_params) rather than in ramp_*.txt, which no longer exists.

    THE BUILT LAYERS COME FROM `layers.warped_for(COMPOSITE_LAYERS)`, so this list, the warp that fills it and the
    per-window reads cannot disagree about the set or the order. Each is joined here because the
    composite reads a pre-warped slice per window instead of forking gdalwarp/gdal_rasterize in the
    loop (optimisation #4), so a re-warp -- new NSIDC/RGI, or a re-fuse to a new grid -- must restage
    it. Any of them may be absent, and `newest_mtime` scores a missing path 0.0, so naming them all
    unconditionally is safe. The ramp TUNABLES (`RAMP_*`) run at composite time inside `snow_alpha`,
    so they do not belong here either -- this tracks the warp SOURCES only.

    THEY RIDE IN `composite_params` INSTEAD, and the split is the point: a warp source moves an
    mtime, a constant moves nothing at all. A look constant that reaches a pixel and reaches
    neither record leaves a stale composite reading fresh forever, so a new one goes into the
    recipe beside the layer that reads it — never into this list, which cannot see it.

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

    THE PRODUCER STAMP IS THE ONE ENTRY HERE THAT IS NOT A WARP SOURCE, and it is here rather than
    in the recipe for the reason the recipe cannot reach: the fact it records is not a constant this
    composite read, it is WHICH PRODUCER wrote the raster this list is deciding about. A raster left
    by the other producer is newer than every source and every recipe here, so nothing else in this
    tuple can see it. `producer_seam` holds the argument in full.
    """
    return (work / HEIGHT_3857, hs, work / OCEAN_3857, work / WATER_3857,
            *(layer.warped_in(work) for layer in layers.warped_for(layers.COMPOSITE_LAYERS)),
            params,
            producer_seam.stamp_path(work))


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
        progress.stage(f"per-row-z hillshade (exag={body.exaggeration}"
                       f"{fill_note}{shadow_note}) ...")
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
    the CPU.

    `ocean_raw`/`watercode` are None on a planet whose seam emitted no masks, and that is a
    DIFFERENT kind of None from a `layer_raw` entry's: that one says a dataset was not downloaded,
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
    #: One slice per `layers.warped_for(COMPOSITE_LAYERS)` row, keyed by layer name, None where that layer's
    #: raster was never built. ONE DICT AND NOT A FIELD PER LAYER: the reads are gated identically,
    #: so a field each is four chances for the fourth to be written without the guard — which is
    #: exactly what happened to snow persistence before this was one expression.
    layer_raw: dict[str, "np.ndarray | None"]
    occ_win: np.ndarray
    #: Which planet this window belongs to, and therefore which producers `_compute_shared` asks
    #: for its layers. Deliberately not carrying paths: this struct crosses onto worker threads,
    #: and a stage that read the filesystem there would leave `_compute_shared` impure.
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
    #: The whites their producers declared for this window, or None where nothing paints one.
    #: Variant-independent for the reason everything else here is: a sea knob cannot move them.
    snow_paint: "tuple[Any, Any] | None"
    ice_paint: "tuple[Any, Any] | None"
    cap: np.ndarray


def _merge_paint(current: "tuple[Any, Any] | None", current_alpha: np.ndarray,
                 incoming: "tuple[Any, Any] | None",
                 incoming_alpha: np.ndarray) -> "tuple[Any, Any] | None":
    """Fold one layer's white into the union's: the layer that WINS a pixel's alpha paints it.

    The union is a `np.maximum` over several layers' alphas, so without this the first-registered
    layer's colour would be painted over another layer's pixels — invisible on a body whose layers
    agree and wrong on one whose layers do not.

    EQUAL WHITES SHORT-CIRCUIT, and that is the only path any shipping body takes today: Earth's
    perennial ice and glaciers both declare `palette.SNOW_RGB`, and Mars declares one ice layer with
    nothing to merge against. The general branch below is therefore reached by NO live data, so its
    guard has to construct two disagreeing paints rather than borrow a pair — a test that took its
    negative case from the registry would go quiet the moment a body changed, not red.

    The short circuit is also what keeps the cost at zero. Merging materialises `(3, H, W)` per end,
    which on a planet window is ~400 MB apiece; agreeing whites never pay it.
    """
    if incoming is None:
        return current
    if current is None:
        return incoming
    if all(np.array_equal(np.asarray(old), np.asarray(new))
           for old, new in zip(current, incoming, strict=True)):
        return current
    wins = (incoming_alpha > current_alpha)[None]
    merged = tuple(np.where(wins, shade.paint_end(new), shade.paint_end(old))
                   for old, new in zip(current, incoming, strict=True))
    return merged[0], merged[1]


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
    land_win = ~(ocean_win | water_win)
    latitude = snow.latitude_per_row(inputs.win_top, inputs.win_bottom, inputs.win_h)
    # THE WALK AND THE FOLD BELONG TO `layer_producers`, and the block render is the second caller
    # that proves it: which layers a stage reads, how a `LayerWindow` is built, and the order and
    # dtype the whites fold in are all decisions, and a stage that re-wrote them would re-decide
    # every one with nothing going red. What stays here is the PAINT, because only the compositor
    # paints — the raytraced rig reads a ramp.
    contributions, paints, exclusions = layer_producers.gather(
        inputs.body, inputs.layer_raw,
        layer_producers.LayerWindow(raw=None, watercode=watercode, land=land_win,
                                    ocean=ocean_win, latitude=latitude,
                                    ground_metres_per_px=mercator.ground_metres_per_pixel(
                                        latitude, inputs.body.map_units_per_pixel,
                                        bodies.ground_metres_per_mercator_unit(inputs.body)),
                                    top=inputs.win_top, bottom=inputs.win_bottom),
        layers.COMPOSITE_LAYERS)
    depth_win = contributions.get(layers.LAKE_DEPTH.name)
    snow_a, snow_paint = layer_producers.fold_white(
        contributions, inputs.height_win.shape, exclusions=exclusions,
        merge=lambda carried, alpha, name, contribution:
            _merge_paint(carried, alpha, paints.get(name), contribution))
    # The sea-side twin, kept OUT of that union on purpose: `shade.composite` gates it on the ocean
    # selector where snow_a paints land, and None there means the layer is absent rather than zero.
    ice_a = contributions.get(layers.SEA_ICE.name)
    cap = (latitude > CAP_NORTH) | (latitude < CAP_SOUTH)
    return _WindowShared(ocean_win, water_win, hs_win, depth_win, snow_a, ice_a,
                         snow_paint, paints.get(layers.SEA_ICE.name), cap)


def _compose(inputs: _WindowInputs, shared: _WindowShared) -> np.ndarray:
    """Shade one window into RGB with the CURRENT KNOBS, then force the polar edges flat.

    Reads KNOBS through `shade.composite`; on the threaded path KNOBS is never mutated mid-pass
    (single variant), so this is a pure function of its two arguments there. On the serial
    multi-variant path the caller mutates KNOBS between variants, exactly as before.
    """
    rgb = shade.composite(inputs.height_win, shared.ocean_win, shared.water_win, shared.snow_a,
                          shared.hs_win, inputs.occ_win, inputs.occ_win.shape,
                          (inputs.win_h, inputs.height_win.shape[1]), depth=shared.depth_win,
                          ice_a=shared.ice_a, look=palette.look_for(inputs.body.name),
                          snow_paint=shared.snow_paint, ice_paint=shared.ice_paint)
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
    outs = {name: work / (PLANET_RGB if not name else f"planet_rgb_{name}.tif")
            for name in variants}
    # THIS PRODUCER NAMES ITSELF, and it does so before its own freshness question because that
    # question depends on the answer. Only when the canonical raster is among the outputs: a
    # variants-only pass writes `planet_rgb_<name>.tif` and leaves `planet_rgb.tif` to whoever made
    # it, so claiming it here would restage a raster this call never touched.
    if None in outs:
        producer_seam.declare(work, "composite")
    params = write_if_changed(work / "composite_params.json",
                              composite_params(variants, body, rasters, window_rows))
    deps = composite_deps(work, hs, params)
    # One shared params file is sound because every variant is composited in a single pass:
    # the guard rebuilds all of them or none.
    if max_windows is None and not any(is_stale(tif, *deps) for tif in outs.values()):
        progress.stage("planet_rgb fresh -> skip composite")
        return outs
    progress.stage("global sky-view factor ...")
    occ = compute_occlusion()
    with rasterio.open(work / HEIGHT_3857) as h:
        width, height, transform = h.width, h.height, h.transform
    small_h, _small_w = occ.shape
    # dict[str, Any]: GDAL creation options are a heterogeneous bag, and `**profile` otherwise
    # hands rasterio.open's bool-typed `sharing`/`thread_safe` an inferred `str | int`.
    profile: dict[str, Any] = dict(
        driver="GTiff", width=width, height=height, count=3, dtype="uint8",
        crs="EPSG:3857", transform=transform, photometric="RGB", BIGTIFF="YES",
        num_threads="ALL_CPUS", **GTIFF_CREATE)
    ocean_p, water_p = work / OCEAN_3857, work / WATER_3857
    layer_paths = {layer.name: layer.warped_in(work)
                   for layer in layers.warped_for(layers.COMPOSITE_LAYERS)}

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
            height_win=read1_window(work / HEIGHT_3857, win),
            # Gated on the SEAM'S DECLARATION, never on `ocean_p.exists()`. A declared mask that is
            # missing from disk must crash here — the planet said it has one — where an existence
            # check would quietly composite a sea-less Earth after a half-finished warp.
            ocean_raw=read1_window(ocean_p, win) if "oceanmask" in rasters else None,
            watercode=read1_window(water_p, win) if "watermask" in rasters else None,
            hs_raw=read1_window(hs, win),
            # ONE EXPRESSION FOR EVERY BUILT LAYER, which is what retires a bug rather than
            # guarding it: written a field each, three of the four had this check and snow
            # persistence did not, so a body whose ice layer was off crashed on a raster nothing
            # had built. Four separate reads is four chances to write the fourth without it.
            layer_raw={name: read1_window(path, win) if path.exists() else None
                       for name, path in layer_paths.items()},
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
    progress.stage(f"composite: {len(rows)} windows in {elapsed:.1f}s "
                   f"({len(rows) / max(elapsed, 1e-9):.2f} win/s, {mode})")
    if max_windows is None and row_start == 0:  # a partial raster (smoke/region) is never done
        for tif in outs.values():
            mark_done(tif)
    for tif in outs.values():
        progress.stage(f"wrote {tif}")
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
