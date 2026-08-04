"""Shade planet chunks into one seamless Web Mercator RGB raster, ready to tile.

Reproject each chunk's height + masks
to a WebMercatorQuad-aligned 3857 grid, mosaic them (VRT), then shade the MOSAIC once
(color-relief x hillshade x SVF, composited by mask) so there are no chunk-edge seams.
Knobs are locked to the values validated on the Nepal chunk (single-NW sun, the physical
15x exaggeration via the latitude z-factor, the tuned composite defaults).

Snow comes from NSIDC-0791 snow persistence (pipeline/render/snow.py) as a latitude-ramped
soft alpha — replacing WorldCover class 70, which left mid/high-latitude ranges bare. The
composite loads the whole region into RAM — fine per-region; a planet run must window it.

    python -m pipeline.tile.shade --cells e070_n20 e080_n20 ... --out data/work/tiles/southasia
"""

import argparse
import math
import subprocess
from pathlib import Path
from typing import Any, TypedDict, cast

import numpy as np
import rasterio
from rasterio.enums import Resampling
from scipy.ndimage import zoom

from pipeline import bodies, paths
from pipeline.raster_io import GTIFF_CREATE
from pipeline.render import hillshade, lake_depth, palette, relief, snow
from pipeline.render.sky_view import (
    OCCLUSION_TARGET_M_PER_PX,
    normalised_occlusion,
    occlusion_shape,
)

DATA = paths.DATA
CHUNKS = DATA / "work/planet/chunks"
Z8_MERC_RES = 305.7483  # metres/pixel of a 512px WebMercatorQuad tile at zoom 8
EXAG = palette.EXAGGERATION  # the region path exists to PREDICT the planet, so it cannot hold its
                             # own copy of a look value. This was a third literal 15.0, uncovered by
                             # the guard that calls the hero/planet pair "the last copy-pair". It
                             # stays Earth-shaped: this path takes --cells, not --body, and a
                             # Copernicus cell name is not a thing another planet has.
MERCATOR = "EPSG:3857"

class Knobs(TypedDict):
    """The locked composite tunables.

    A TypedDict, not a plain dict, because `lake_curve` is a str among fifteen floats: inferred
    as `dict[str, float | str]`, every one of the ~20 `KNOBS["..."]` reads below became
    `float | str` and none of the arithmetic type-checked. Declaring it here types each key
    exactly, and turns a mistyped key into an error rather than a KeyError at composite time.

    It stays ONE dict rather than splitting `lake_curve` out into its own constant, because
    `shade_planet.composite_params()` serialises KNOBS wholesale as planet_rgb's freshness
    dependency -- a curve that rode outside would have to be remembered into that record by
    hand, which is exactly the untracked-constant bug the guard exists to catch. TypedDict is
    a pure annotation: at runtime this is still a plain dict, so the params JSON is unchanged.
    """

    alt: float
    fill_strength: float
    shadow_strength: float
    shadow_reach: float
    ambient_knee: float
    shadow_warmth: float
    ambient: float
    hi: float
    exposure: float
    saturation: float
    warmth: float
    svf_strength: float
    svf_threshold: float
    sea_shade: float
    sea_lift: float
    sea_saturation: float
    sea_svf: float
    ice_relief_damp: float
    snow_lo: float
    snow_hi_pt: float
    snow_curve: str  # light->snow ramp mapping; see snow_position()
    lake_curve: str  # depth->ramp mapping; see lake_position()


# `fill_strength` is the hero's fill sun as a fraction of the main sun (its FILL_STRENGTH 0.45 /
# SUN_STRENGTH 3.0 = 0.15). It rides in KNOBS beside `alt` because, like `alt`, it is consumed at
# the HILLSHADE stage rather than by composite() -- which also makes it reachable from `--knob` for
# region A/Bs, the way every other art value here is tuned. `shade_planet.build_hillshade` records
# it in hs_params.json, so a change to it correctly restages the hillshade (and, through
# composite_deps' dependency on hs, the composite and the tiles).
#
# **0.15, chosen by eye** off a five-strength sweep on real tiles under production's own
# global SVF. It is the hero's own ratio, and any value >= 0.10 already drives pure black to 0.00%
# everywhere; past ~0.20 the compression starts reading flat rather than soft.
#
# `hi` 1.30 -> 1.12 lands with it, as ART.md:56 demands (tune the pair, never each alone): the fill
# lowers peak light, so the old 1.30 ceiling no longer binds and only clips the pale ramp.
# `ambient` deliberately STAYS 0.50 -- the sweep tried 0.56/0.62 and both re-created the "washed
# rosy and flat" failure the hero's own A/B already rejected. The fill IS the shadow floor
# (ART.md:90); a second floor under it only hazes the pale high country. Every metric said 0.62 was
# best and every metric was wrong -- the eye decided it.
# hero's fill sun
#
# `snow_curve` **"gamma8", chosen by eye** off a four-curve A/B (linear/gamma4/gamma8/
# knee) rendered through composite() at Greenland Summit + north and the Alps + Himalaya. It rides
# here, not as a function parameter, for the same reason `lake_curve` does: it is a tunable, so
# composite_params must see it. `snow_lo`/`snow_hi_pt` deliberately stay 0.55/1.05 -- the window is
# not the lever, the CURVE is; a window narrow enough for Greenland is a threshold for the Alps.
# `shadow_strength` 0.0 -- **REJECTED TWICE on the look (once under the ambient clip, once under the
# knee) and rejected on the MECHANISM the second time.** Do not re-open with a new strength
# value: `per_row_zfactor_hillshade` applies `shaded *= (1 - strength * shadow)`, which scales the
# MAIN sun, and fine detail amplitude is proportional to light amplitude -- so local high-frequency
# detail falls with it (68% kept at 0.35, 55% in full shadow; predicted to within a point by
# arithmetic). Any cast shadow that attenuates the main sun erases the modeling it carries. Reopening
# requires a different mechanism, not a different number.
# `shadow_reach` is a truncation distance in pixels, not a
# safety limit -- a shadow longer than this simply stops, with no error and no visible edge. 300 px
# covers Damavand (5,610 m -> 275 px) and the Zagros (~4,400 m -> 216 px) at the z8 grid; use
# `cast_shadow.shadow_reach_px` to size it for any other terrain.
# `ambient_knee` **0.30, chosen by eye** on a full-planet pass judged on /earth. See
# `apply_ambient_floor`: `ambient` is a CLIFF, not a floor -- measured, 18.07% of Iran's
# land sat under it carrying no hillshade information at all, and the knee is what gives that land
# its form back. My metric-based recommendation was 0.15 and the eye overruled it; the local-contrast
# std that argued for 0.15 is the same proxy that lost the fill-sun A/B, so it is now
# twice-failed as a stand-in for perceived softness.
# `shadow_warmth` **0.55, chosen by eye** on a full-planet pass judged on /earth, after
# 1.0 read too copper on Alpine crops. 1.0 would reproduce the hero's MEASURED shadow warmth (see
# SHADOW_TINT), so this is 55% of the hero -- the value is anchored to a measurement even where it
# departs from it. 0.0 is the pre-`shadow_warmth` look and is bit-identical when off.
# `ice_relief_damp` **0.75, chosen by eye** off a five-rung cap A/B (0/0.25/0.5/0.75/
# 1.0, swept with `cap_ladder --axis ice_relief_damp` -- the 21 s pole loop): how much thick sea ice
# CONCEALS the seafloor's shading. The ice whites are light-keyed by `snow_t`, whose light over
# ocean is the SEAFLOOR's hillshade -- so at full pack the floor's ridges painted into the ice at
# full strength and the Arctic pack read as terrain above the sea. This pulls the ice's light-key
# toward its flat-ocean position in proportion to `damp * ice_alpha`: the perennial pack calms, the
# marginal fringe keeps its relief, and the `(1 - alpha)` colour glow-through (the "ocean
# floor under ice" decision) is a different channel and untouched. The rungs measured
# linear (mean 2.8/5.2/7.6/10.0 DN at 0.25..1.0); 1.0 read soft but 0.75 kept a touch more
# surface life. 0.0 is the pre-`ice_relief_damp` look, bit-identical when off.
KNOBS = Knobs(alt=palette.SUN_ALT_DEG, fill_strength=0.15, shadow_strength=0.0, shadow_reach=300.0,
              shadow_warmth=0.55,
              ambient=0.50, ambient_knee=0.30, hi=1.12, exposure=1.05, saturation=1.18,
              warmth=0.06, svf_strength=0.20, svf_threshold=0.45, sea_shade=0.55, sea_lift=1.00,
              sea_saturation=0.90, sea_svf=0.5, ice_relief_damp=0.75, snow_lo=0.55, snow_hi_pt=1.05,
              snow_curve="gamma8", lake_curve="log1p")


def run(cmd):
    subprocess.run([str(part) for part in cmd], check=True, capture_output=True)


def cell_mid_lat(name: str) -> float:
    """Centre latitude of a 10-degree cell from its name, e.g. e080_n20 -> 25.0."""
    lat_part = name.split("_")[1]
    lat = int(lat_part[1:]) * (1 if lat_part[0] == "n" else -1)
    return lat + 5.0


def reproject_cell(name: str, merc_dir: Path):
    """Warp one cell's height + masks to a WMQ-aligned 3857 grid (-tap keeps chunks
    pixel-aligned to each other and to the tile grid, so the mosaic is seamless)."""
    chunk = CHUNKS / name
    height = merc_dir / f"{name}_height.tif"
    run(["gdalwarp", "-overwrite", "-q", "-t_srs", MERCATOR,
         "-tr", Z8_MERC_RES, Z8_MERC_RES, "-tap", "-r", "bilinear",
         chunk / "heightfield_10s.tif", height])
    with rasterio.open(height) as dataset:
        te = [repr(value) for value in dataset.bounds]
        ts = [str(dataset.width), str(dataset.height)]
    for raster in ("oceanmask", "watermask"):
        run(["gdalwarp", "-overwrite", "-q", "-t_srs", MERCATOR, "-te", *te, "-ts", *ts,
             "-r", "near", chunk / f"{raster}_10s.tif", merc_dir / f"{name}_{raster}.tif"])


def build_vrt(vrt_path, sources):
    run(["gdalbuildvrt", "-overwrite", vrt_path, *sources])


def read3(path):
    with rasterio.open(path) as dataset:
        return dataset.read([1, 2, 3]).astype(float)


def read1(path, shape=None):
    with rasterio.open(path) as dataset:
        if shape is None:
            return dataset.read(1)
        return dataset.read(1, out_shape=shape, resampling=Resampling.nearest)


def add_fill_gdaldem(height_vrt, hs_tif: Path, zfactor: float, out: Path) -> None:
    """Mix the fill sun into a `gdaldem`-produced hillshade, in place. No-op at strength 0.

    This exists so the REGION path and the planet path share one light model. `shade_planet` gets
    the fill inside `per_row_zfactor_hillshade`; this branch shades with `gdaldem`, which takes one
    sun, so the fill needs its own pass. Both then meet at `hillshade.combine_fill` -- the point
    being that the arithmetic is not copied here. Skipping this would leave `--cells` (the A/B tool
    the sea and lake ramps were judged on) rendering a DIFFERENT light model from production, which
    is how an A/B silently stops predicting the thing it is judging.

    Region-scale only: it reads the whole hillshade into RAM, exactly as `composite` already does
    on this path ("the composite loads the whole region into RAM — fine per-region").
    """
    if KNOBS["fill_strength"] == 0.0:
        return
    fill_tif = out / "hs_fill.tif"
    print(f"hillshade: + fill sun {KNOBS['fill_strength']:.2f} "
          f"(alt {hillshade.FILL_ALTITUDE:.0f}, az {hillshade.FILL_AZIMUTH:.0f})", flush=True)
    run(["gdaldem", "hillshade", height_vrt, fill_tif, "-z", f"{zfactor:.4f}",
         "-alt", str(hillshade.FILL_ALTITUDE), "-az", str(hillshade.FILL_AZIMUTH),
         "-compute_edges"])
    with rasterio.open(hs_tif) as dataset:
        profile: dict[str, Any] = dict(dataset.profile)
        main_hs = dataset.read(1).astype(np.float32)
    with rasterio.open(fill_tif) as dataset:
        fill_hs = dataset.read(1).astype(np.float32)
    combined = hillshade.combine_fill(main_hs, fill_hs, KNOBS["fill_strength"], KNOBS["alt"])
    with rasterio.open(hs_tif, "w", **profile) as dst:
        dst.write(np.rint(combined).astype("uint8"), 1)
    fill_tif.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--knob", action="append", default=[], metavar="KEY=VALUE",
                    help="override a locked KNOBS entry (repeatable), e.g. --knob snow_floor=0.85")
    ap.add_argument("--zfactor", type=float, default=None,
                    help="use a single global hillshade z-factor instead of the per-region "
                         "mid-latitude one — for seamless multi-block planet shading")
    ap.add_argument("--occlusion-target", type=float, default=None, metavar="M_PER_PX",
                    help="override sky_view.OCCLUSION_TARGET_M_PER_PX for an A/B (region only; "
                         "production always reads the shared constant)")
    ap.add_argument("--per-row-z", action="store_true",
                    help="hillshade with a per-latitude-row z-factor (EXAG/cos(lat)) via the "
                         "custom seamless shader — correct exaggeration at every latitude")
    args = ap.parse_args()
    # A key off argv is dynamic by construction, so a TypedDict cannot check it -- this view is
    # the honest escape hatch, and the membership test below is what actually validates the key.
    knobs = cast(dict[str, Any], KNOBS)
    for override in args.knob:
        key, _, value = override.partition("=")
        if key not in knobs:
            raise SystemExit(f"unknown knob {key!r}; valid: {', '.join(sorted(knobs))}")
        # Most knobs are floats; lake_curve names a mapping, so coerce by the existing type.
        knobs[key] = value if isinstance(knobs[key], str) else float(value)
        print(f"knob override: {key} = {knobs[key]}", flush=True)
    merc = args.out / "merc"
    merc.mkdir(parents=True, exist_ok=True)

    print(f"reprojecting {len(args.cells)} cells to WMQ-aligned Mercator...", flush=True)
    for name in args.cells:
        reproject_cell(name, merc)

    height_vrt = args.out / "height.vrt"
    ocean_vrt = args.out / "ocean.vrt"
    water_vrt = args.out / "water.vrt"
    build_vrt(height_vrt, [merc / f"{n}_height.tif" for n in args.cells])
    build_vrt(ocean_vrt, [merc / f"{n}_oceanmask.tif" for n in args.cells])
    build_vrt(water_vrt, [merc / f"{n}_watermask.tif" for n in args.cells])

    with rasterio.open(height_vrt) as dataset:
        bounds = dataset.bounds
        grid_h, grid_w = dataset.height, dataset.width
    print(f"region mosaic: {grid_w} x {grid_h} px in Mercator", flush=True)

    # The ramps are applied inside composite() from the elevation itself (palette.relief_lut)
    # -- the two `gdaldem color-relief` passes that used to materialise c_land/c_sea
    # were 24.4% of all planet-pass CPU and reproduced to <=1 DN by a 17.6 KB lookup table.
    hs_tif = args.out / "hs.tif"
    mid_lat = sum(cell_mid_lat(n) for n in args.cells) / len(args.cells)
    if args.per_row_z:
        shadow_note = (f", shadow {KNOBS['shadow_strength']:.2f} reach {int(KNOBS['shadow_reach'])}px"
                       if KNOBS["shadow_strength"] else "")
        print(f"hillshade: per-row z-factor (EXAG={EXAG}/cos(lat)), custom seamless shader"
              f"{shadow_note}", flush=True)
        hillshade.per_row_zfactor_hillshade(height_vrt, hs_tif, EXAG, KNOBS["alt"], 315.0,
                                            # Spelled through the registry rather than as a bare
                                            # 1.0: this path takes Copernicus cells, so Earth is
                                            # not a default here, it is the subject.
                                            ground_scale=bodies.ground_metres_per_mercator_unit(
                                                bodies.EARTH),
                                            fill_strength=KNOBS["fill_strength"],
                                            shadow_strength=KNOBS["shadow_strength"],
                                            shadow_reach_px=int(KNOBS["shadow_reach"]))
    elif KNOBS["shadow_strength"] != 0.0:
        # `gdaldem hillshade` is local by construction and cannot cast shadows. Silently dropping
        # the knob here would make the two branches disagree while both reported success -- the
        # copied-constant drift this project has hit four times. Refuse instead.
        raise SystemExit("shadow_strength requires --per-row-z; the gdaldem branch cannot cast "
                         "shadows. Re-run with --per-row-z (which is what production uses).")
    else:
        zfactor = args.zfactor if args.zfactor is not None else relief.mercator_zfactor(mid_lat, EXAG)
        print(f"hillshade z-factor {zfactor:.2f} (region mid-lat {mid_lat:.1f})", flush=True)
        run(["gdaldem", "hillshade", height_vrt, hs_tif, "-z", f"{zfactor:.4f}",
             "-alt", str(KNOBS["alt"]), "-az", "315", "-compute_edges"])
        add_fill_gdaldem(height_vrt, hs_tif, zfactor, args.out)

    # composite (whole region in RAM)
    heights = read1(height_vrt).astype("float32")
    ocean = read1(ocean_vrt) != 0
    watercode = read1(water_vrt)
    water = lake_depth.inland_water(watercode)
    hs = read1(hs_tif).astype(float)

    # snow: NSIDC-0791 persistence -> latitude-ramped soft alpha (pipeline/render/snow.py)
    persistence = snow.warp_persistence(
        (bounds.left, bounds.bottom, bounds.right, bounds.top), grid_w, grid_h,
        args.out / "sp_merc.tif")
    snow_a = snow.snow_alpha(persistence, bounds.top, bounds.bottom)
    glacier = snow.rasterize_glaciers(
        (bounds.left, bounds.bottom, bounds.right, bounds.top), grid_w, grid_h,
        args.out / "rgi_merc.tif")
    if glacier is not None:
        snow_a = np.maximum(snow_a, glacier.astype(float))
        print(f"unioned RGI glaciers: {int((glacier > 0).sum()):,} px", flush=True)

    # lake depth: GLOBathy modelled depth, tint-only (pipeline/render/lake_depth.py)
    depth = lake_depth.lakes_only(
        lake_depth.warp_depth((bounds.left, bounds.bottom, bounds.right, bounds.top),
                              grid_w, grid_h, args.out / "lakedepth_merc.tif"),
        watercode)
    if depth is not None and (depth > 0).any():
        print(f"lake depth: {int((depth > 0).sum()):,} px, max {depth.max():.0f} m, "
              f"curve={KNOBS['lake_curve']}", flush=True)
    else:
        print("lake depth: none in this region -> lakes stay flat", flush=True)

    # Occlusion at the SHARED ground resolution, not a region-local pixel count. The old
    # `long_edge = 2400` made this preview 12.9x finer than the planet it exists to predict.
    occlusion_target = args.occlusion_target or OCCLUSION_TARGET_M_PER_PX
    if args.occlusion_target:
        print(f"occlusion target override: {occlusion_target:.0f} m/px "
              f"(production is {OCCLUSION_TARGET_M_PER_PX:.0f})", flush=True)
    with rasterio.open(height_vrt) as dataset:
        full_res_m_per_px = Z8_MERC_RES * math.cos(math.radians(mid_lat))
        sh, sw = occlusion_shape(dataset.width, dataset.height, full_res_m_per_px,
                                 target=occlusion_target)
        low = dataset.read(1, out_shape=(sh, sw), resampling=Resampling.average).astype(float)
        m_per_px = (dataset.bounds.right - dataset.bounds.left) / sw * math.cos(math.radians(mid_lat))
    low = np.nan_to_num(np.where(low < -500, np.nan, low), nan=0.0)
    occ = normalised_occlusion(low, m_per_px)

    rgb = composite(heights, ocean, water, snow_a, hs, occ, (sh, sw), (grid_h, grid_w),
                    depth=depth)

    out_tif = args.out / "region_rgb.tif"
    with rasterio.open(height_vrt) as src:
        profile: dict[str, Any] = dict(
            driver="GTiff", height=grid_h, width=grid_w, count=3, dtype="uint8",
            crs=src.crs, transform=src.transform, photometric="RGB",
            num_threads="ALL_CPUS", **GTIFF_CREATE)
    with rasterio.open(out_tif, "w", **profile) as out:
        out.write(rgb)
    print(f"wrote {out_tif}", flush=True)


def lake_position(depth, curve):
    """Lake depth (m below surface) -> 0..1 along the lake ramp.

    This curve is the honesty/legibility dial, and the two pull against each other. The median
    lake is 11.2 m deep while Baikal is 1642 -- three orders of magnitude -- so a LINEAR axis
    parks 99% of lakes in the first 2% of the ramp and shows nothing. LOG1P spreads them
    (median -> 0.34) but hands most of the ramp to shallow water, which is exactly where
    GLOBathy's cone is least trustworthy (on the Caspian it claims 155 m where the truth is
    under 20 m, measured), so it also maximises the visibility of the layer's worst
    error. SQRT (median -> 0.08) is the conservative middle. Judge on renders, not in the
    abstract.
    """
    if curve == "log1p":
        # Clamped like the others: LAKE_MAX_M is Baikal, so nothing should exceed it today,
        # but an unclamped log1p returns >1 for anything that does -- one re-tune of
        # LAKE_MAX_M to a shallower cap away from indexing off the end of the ramp.
        return (np.log1p(np.clip(depth, 0.0, palette.LAKE_MAX_M))
                / math.log1p(palette.LAKE_MAX_M))
    if curve == "sqrt":
        return np.sqrt(np.clip(depth, 0.0, palette.LAKE_MAX_M) / palette.LAKE_MAX_M)
    if curve == "linear":
        return np.clip(depth, 0.0, palette.LAKE_MAX_M) / palette.LAKE_MAX_M
    raise ValueError(f"unknown lake_curve {curve!r} (log1p | sqrt | linear)")


# Greenland's interior spans light 1.017-1.052 while Alpine snow spans 0.50-1.11 -- a 17x
# dynamic-range mismatch, and the ranges are NESTED (Greenland sits inside the Alps' top). The
# snow window is the only channel relief has over full snow, because base_rgb is multiplied by
# (1 - alpha) = 0 there. So a LINEAR window is forced to choose: wide enough for the Alps hands
# Greenland 7% of its travel (2.87 DN delivered, i.e. blank); narrow enough for Greenland is a
# threshold for the Alps. A curve is the only single global knob that can serve both, exactly as
# `lake_curve` answers the pond-vs-Baikal version of this.
KNEE_X = 0.93      # where Greenland's band starts on the normalised window
KNEE_SHARE = 0.45  # fraction of the ramp handed to everything above KNEE_X


def apply_ambient_floor(raw, ambient: float, hi: float, knee: float):
    """Land the raw `hs/flat` light on its floor — hard-clipped, or over a soft knee.

    `ambient` has always been a `np.clip` lower bound, which makes it a CLIFF rather than a floor:
    every pixel below it collapses to exactly one value. Measured on Iran, **18.07% of
    land already sits there** carrying no hillshade information, and a cast shadow pushed a further
    6.21% under — pixels whose control spread was 36 DN, all flattened to the same number. That is
    what "the details are gone in the mountains" looked like from inside the arithmetic.

    `knee` > 0 replaces the clip with a softplus, which is the SAME shape everywhere it matters and
    differs only near the floor: far above it the output is `raw` to within float error, and far
    below it approaches `ambient` asymptotically while still VARYING. So shadowed terrain keeps its
    form instead of becoming a flat plate, and open ground is untouched.

    **This is not the rejected `ambient` raise.** Lifting the floor was swept and rejected twice
    (once as washed rosy and flat; once where every metric said otherwise and every metric was
    wrong). This leaves the floor exactly where it is and changes only how terrain ARRIVES at it.

    `knee = 0.0` is the hard clip, bit-identical — not an approximation of it.
    """
    if knee <= 0.0:
        return np.clip(raw, ambient, hi)
    # logaddexp, not log1p(exp(...)): the naive form overflows for raw >> ambient, which is most of
    # the planet. Softplus is >= max(raw, ambient), so the knee lifts slightly AT the floor (by
    # knee*ln2) and vanishes away from it.
    softened = ambient + knee * np.logaddexp(0.0, (raw - ambient) / knee)
    return np.minimum(softened, hi)


# The hero's shadow is WARMER IN HUE, not merely darker: Cycles fills it with warm sky
# (WORLD_RGBA F2E7D5 @ WORLD_STRENGTH 0.3) plus bounce off the rosy land, while our `light` is a
# single scalar that multiplies all three channels equally and therefore cannot move hue at all.
# Measured on heroes/raw/switzerland.png, inside narrow elevation bands so the ramp
# colour is constant: linear R/B is 1.61-1.98x higher in the darkest quartile than the brightest,
# monotonic across all ten luminance deciles. Ours is exactly 1.00x. -> ART.md "Hero -> tile map".
#
# DERIVATION: the sky's own chromaticity only accounts for 1.334x of that, so the tint is the world
# colour DEEPENED to the measured 1.80x mid-band ratio (world ** 2.0373), the residual being warm
# GI bounce off the land ramp -- which our greyscale SVF stand-in structurally cannot carry.
# Then normalised to luminance 1.0, so this knob moves HUE ONLY and cannot re-create the
# brightness wash that got `ambient` raises rejected twice. That is the point of the design.
SHADOW_TINT = (1.205239, 0.972347, 0.669577)


def shadow_tint(light: np.ndarray, strength: float,
                ambient: float) -> "np.ndarray | np.floating":
    """Per-channel multiplier warming shaded land toward `SHADOW_TINT`, unlit ground untouched.

    `shadowness` is 0 on flat-lit ground (light 1.0) and 1 at the ambient floor, so the tint
    fades in exactly where the sun stops reaching. Under `ambient_knee` nothing lands AT the floor
    (darkest light 0.5519), so the practical maximum is ~0.90 of full strength.

    Returns a (3, 1, 1)-broadcastable array; at `strength` 0.0 it returns exactly 1.0 so the
    caller's multiply is bit-identical to not calling it.
    """
    if strength == 0.0:
        return np.float32(1.0)
    shadowness = np.clip((1.0 - light) / (1.0 - ambient), 0.0, 1.0).astype(np.float32)
    tint = np.array(SHADOW_TINT, dtype=np.float32).reshape(3, 1, 1)
    return 1.0 + shadowness[None] * strength * (tint - 1.0)


def snow_position(light, curve):
    """Hillshade light -> 0..1 along the snow_shadow->snow_lit ramp.

    The budget is fixed: snow_shadow B0C7DB to snow_lit E8F1F6 is 43.9 DN of luminance, and that
    is ALL the contrast any fully-snow pixel can receive. A curve cannot create range, only
    redistribute it -- so a gain for flat ice is in principle paid for by rugged snow. MEASURED,
    the bill is small: rugged snow's light is bimodal (62-65% pinned at the `ambient` floor, a few
    % at the top), so it barely occupies the midtones the curve borrows from. Under gamma8 only
    ~34% of Alpine snow pixels move at all (mean 6.99 DN) against 99% of Greenland's (mean 13.03).

    LINEAR is retained as the A/B control and is what shipped before. GAMMA8 delivers
    Greenland Summit 3.14 -> 18.84 DN (6.0x) and north 4.35 -> 24.12 DN (5.5x). KNEE matches it at
    Summit but is weaker in the north (4.3x) for two more constants, so it was not chosen.

    `position ** 8` is deliberately left as a pow: repeated squaring is 1.7x faster on it but saves
    6.8 s of a ~2,980 s composite (0.23%) and is not bit-identical (1.8e-7). Measured:
    not assumed -- this is the fast-stage trap the gdaladdo entry records.
    """
    position = np.clip((light - KNOBS["snow_lo"]) / (KNOBS["snow_hi_pt"] - KNOBS["snow_lo"]),
                       0.0, 1.0)
    if curve == "linear":
        return position  # the pre-curve look, bit-identical -- a real control, not an approximation
    if curve == "gamma4":
        return position ** 4
    if curve == "gamma8":
        return position ** 8
    if curve == "knee":
        return np.where(position <= KNEE_X,
                        position / KNEE_X * (1.0 - KNEE_SHARE),
                        (1.0 - KNEE_SHARE) + (position - KNEE_X) / (1.0 - KNEE_X) * KNEE_SHARE)
    raise ValueError(f"unknown snow_curve {curve!r} (linear | gamma4 | gamma8 | knee)")


def composite(heights, ocean, water, snow_a, hs, occ, occ_shape, grid, depth=None, ice_a=None):
    """Composite one window of the planet/region from ELEVATION, not pre-coloured rasters.

    `heights` is metres on the fused heightfield; the land and sea ramps are applied here via
    `palette.relief_lut`, which replaced two `gdaldem color-relief` passes.
    Those cost **28:19 and 24.4% of all pass CPU**, single-threaded, each reading the full 31 GB
    height raster to write 1 GB. Profiled: `libgdal 19.37%` (a per-pixel SEARCH over 241 ramp
    rows) vs `libdeflate 4.33%` -- so no threading flag could fix it. Our ramp rows are uniformly
    spaced, so the index is a divide, not a search; gdaldem cannot know that, numpy can. Verified
    against gdaldem's own output over all 12.19 G px, 6/6 bands: 96.7% identical, 3.3% at exactly
    1 DN, **zero beyond the uint8 contract**, and 2.5x faster in one read instead of two.

    Applying the ramps HERE rather than in each caller is deliberate: a per-call-site copy of a
    shared decision is precisely how the float32 window fix reached `composite` and never reached
    `hillshade` (11.6 GB). One implementation, both shade paths.
    """
    height, width = grid
    # float32 throughout — the output is 8-bit, and on the full-width planet windows float64
    # doubled peak RAM (~18 GB) and OOM-killed the box. asarray is a no-op when already float32.
    heights = np.asarray(heights, dtype=np.float32)
    land = palette.lut_lookup(palette.relief_lut("land"), "land", heights).astype(np.float32)
    sea = palette.lut_lookup(palette.relief_lut("sea"), "sea", heights).astype(np.float32)
    hs = np.asarray(hs, dtype=np.float32)
    snow_a = np.asarray(snow_a, dtype=np.float32)
    occ = np.asarray(occ, dtype=np.float32)
    lum = 0.299 * land[0] + 0.587 * land[1] + 0.114 * land[2]
    land = np.clip((lum[None] + (land - lum[None]) * KNOBS["saturation"])
                   * np.array([1.0, 1.0 - 0.5 * KNOBS["warmth"], 1.0 - KNOBS["warmth"]],
                              dtype=np.float32).reshape(3, 1, 1),
                   0, 255)
    sea_lum = 0.299 * sea[0] + 0.587 * sea[1] + 0.114 * sea[2]
    sea = np.clip(sea_lum[None] + (sea - sea_lum[None]) * KNOBS["sea_saturation"], 0, 255)
    color = np.where(ocean[None], sea, land)
    # Inland water: flat WATER_RGB by default. Where a lake carries GLOBathy depth, ramp it
    # instead -- on ABSOLUTE depth, never normalised per lake, since a per-lake normalisation
    # is the artificial gradient the prototype was rejected for (a pond would read
    # like Baikal). `depth` is already zeroed off watermask class 2 by the caller, so rivers
    # and the (class 1) Caspian cannot reach this branch.
    flat_water = np.array(palette.WATER_RGB, dtype=np.float32).reshape(3, 1, 1)
    if depth is None or KNOBS["lake_curve"] == "off":
        lake_color = flat_water  # 'off' is the A/B control: today's flat inland water
    else:
        depth = np.asarray(depth, dtype=np.float32)
        lut = np.array(palette.lake_lut(), dtype=np.float32).T  # (3, size)
        index = np.clip(lake_position(depth, KNOBS["lake_curve"]) * (lut.shape[1] - 1),
                        0, lut.shape[1] - 1).astype(np.int32)
        lake_color = np.where((depth > 0.0)[None], lut[:, index], flat_water)
    color = np.where(water[None], lake_color, color)

    flat = 255.0 * math.sin(math.radians(KNOBS["alt"]))
    light = apply_ambient_floor(hs / flat, KNOBS["ambient"], KNOBS["hi"], KNOBS["ambient_knee"])
    burn = KNOBS["svf_strength"] * np.clip(
        (occ - KNOBS["svf_threshold"]) / (1 - KNOBS["svf_threshold"]), 0, 1) ** 1.4
    sh, sw = occ_shape
    svf_factor = np.clip(np.asarray(zoom(1.0 - burn, (height / sh, width / sw), order=1)), 0, 1)
    # Inland water stays flat; ocean gets a fraction (sea_svf) of the land-style occlusion
    # so basins and shelf edges read as recessed instead of a flat sheet.
    svf_factor = np.where(water, 1.0, svf_factor)
    svf_factor = np.where(ocean, 1.0 - (1.0 - svf_factor) * KNOBS["sea_svf"], svf_factor)
    light = np.where(water, np.clip(light, 0.85, KNOBS["hi"]), light)
    light = np.where(ocean, KNOBS["sea_lift"] + (light - 1.0) * KNOBS["sea_shade"], light)
    light = np.where(ocean | water, light,
                     KNOBS["ambient"] + (light - KNOBS["ambient"]) * KNOBS["exposure"])
    base_rgb = color * (light * svf_factor)
    if KNOBS["shadow_warmth"] != 0.0:
        # Land only: the sea has its own light model (`sea_lift`/`sea_shade`) and snow its own
        # two-colour ramp below, which already carries a deliberate BLUE shadow. Warming those
        # would fight decisions that were made on their own evidence.
        land_tint = shadow_tint(light, KNOBS["shadow_warmth"], KNOBS["ambient"])
        base_rgb = np.where((ocean | water)[None], base_rgb, base_rgb * land_tint)

    # soft-alpha snow: blend snow over land by the ramped persistence alpha (no snow on water).
    # Snow colour is keyed to the hillshade light: glacial blue-white in shadow -> bright white
    # in sun (a two-colour ramp, not a neutral multiply), so snow keeps relief form instead of
    # muddying to grey on rugged terrain the way SNOW_RGB*light did.
    alpha = np.where(ocean | water, 0.0, snow_a)
    snow_t = snow_position(light, KNOBS["snow_curve"])
    snow_shadow = np.array(palette.SNOW_SHADOW_RGB, dtype=np.float32).reshape(3, 1, 1)
    snow_lit = np.array(palette.SNOW_RGB, dtype=np.float32).reshape(3, 1, 1)
    snow_rgb = snow_shadow + (snow_lit - snow_shadow) * snow_t[None]
    final = base_rgb * (1.0 - alpha)[None] + snow_rgb * alpha[None]

    # soft-alpha sea ice: the sea-side mirror of the snow blend above. Gated on `ocean` (the mirror
    # of snow's ~(ocean|water) land gate) so ice paints ONLY over open sea -- never land, never the
    # inland-water branch (the disc-glow trap). Reuses the same light-keyed white `snow_rgb`: one
    # white family for both cryosphere layers. `ice_a` is already zero off the ice edge (the
    # frequency field), so ice fades to the bathymetry at the margin -- the intended pole look. None
    # on the region path (and any caller that passes no ice), which then behaves exactly as before.
    if ice_a is not None:
        # Sea ice is a cooler/dimmer white than snow (palette.ICE_*), light-keyed by the same snow_t
        # so it still takes the hillshade on pressure ridges / shelf edges. Distinct from land snow
        # without a hard colour split -- the coastline and relief carry the rest.
        ice_shadow = np.array(palette.ICE_SHADOW_RGB, dtype=np.float32).reshape(3, 1, 1)
        ice_lit = np.array(palette.ICE_RGB, dtype=np.float32).reshape(3, 1, 1)
        gated_ice = np.where(ocean, np.asarray(ice_a, dtype=np.float32), 0.0)
        ice_light_key = snow_t
        if KNOBS["ice_relief_damp"] > 0.0:
            # Thick ice conceals the floor's SHADING (this key), never its COLOUR (the (1 - alpha)
            # translucency above): pull the key toward its flat-ocean value in proportion to ice
            # cover. `flat_light` replays the flat-terrain light (hs == flat -> 1.0) through the
            # same ambient-knee and sea transforms the per-pixel light took, so damp 1.0 at full
            # alpha lands exactly on "what a featureless seafloor would have looked like".
            flat_light = apply_ambient_floor(np.float32(1.0), KNOBS["ambient"], KNOBS["hi"],
                                             KNOBS["ambient_knee"])
            flat_sea_light = KNOBS["sea_lift"] + (float(flat_light) - 1.0) * KNOBS["sea_shade"]
            flat_key = snow_position(np.float32(flat_sea_light), KNOBS["snow_curve"])
            ice_light_key = snow_t + (flat_key - snow_t) * (KNOBS["ice_relief_damp"] * gated_ice)
        ice_rgb = ice_shadow + (ice_lit - ice_shadow) * ice_light_key[None]
        final = final * (1.0 - gated_ice)[None] + ice_rgb * gated_ice[None]
    return np.clip(final, 0, 255).astype("uint8")


if __name__ == "__main__":
    raise SystemExit(main())
