"""The composite's locked tunables, and the two curves that outlived the compositor.

THIS MODULE NO LONGER SHADES ANYTHING. It held `composite` — the per-pixel numpy shader every
composited pixel went through — and a `--cells` region preview that ran it over a few Copernicus
chunks. Both went with the composite planet producer: every planet is raytraced, so the shader had
no caller and the preview produced a look no body ships, which is worse than no preview.

WHAT STILL HAS A RUNTIME READER IS ONE KEY AND ONE FUNCTION. `render/lake_mask.py` reads
`KNOBS["lake_curve"]` and passes it to `lake_position`, both on the HERO path, which is a different
lane from the tiles entirely. `Z8_MERC_RES` is read by a resolution test.

NOTHING ELSE HERE REACHES A PIXEL. The record that serialised KNOBS wholesale was `composite_params`
and `SHADOW_TINT`'s only reader was that same record, so both went with it.

THE PRUNE IS NOW DUE AND IS NOT A COMMENT FIX. The reason these fields were kept was that their
serialiser was pending deletion; it is deleted. What is left is a deletion job with its own
consumers to walk — sabotage cases keyed to these names, and the ART.md rows that price them.
"""

import math
from typing import TypedDict

import numpy as np

from pipeline import paths
from pipeline.look import palette

DATA = paths.DATA
CHUNKS = DATA / "work/planet/chunks"
Z8_MERC_RES = 305.7483  # metres/pixel of a 512px WebMercatorQuad tile at zoom 8


class Knobs(TypedDict):
    """The locked composite tunables.

    A TypedDict, not a plain dict, because `lake_curve` is a str among fifteen floats: inferred
    as `dict[str, float | str]`, every one of the `KNOBS["..."]` reads became `float | str` and none
    of the arithmetic type-checked. Declaring it here types each key exactly, and turns a mistyped
    key into an error rather than a KeyError.

    It stayed ONE dict because `composite_params` serialised KNOBS wholesale, so a `lake_curve` that
    rode outside would have had to be remembered into that record by hand. That record is gone and
    the argument with it; the dict's shape is now a question for the prune, not a settled contract.
    TypedDict is a pure annotation: at runtime this is still a plain dict.
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
    snow_curve: str  # light->snow ramp mapping
    lake_curve: str  # depth->ramp mapping; see lake_position()


# `fill_strength` is the hero's fill sun as a fraction of the main sun (its FILL_STRENGTH 0.45 /
# SUN_STRENGTH 3.0 = 0.15). Nothing records it any more: `build_hillshade` and its `hs_params.json`
# went with the composite, and no raytraced recipe carries it.
#
# **0.15, chosen by eye** off a five-strength sweep on real tiles under production's own
# global SVF. It is the hero's own ratio, and any value >= 0.10 already drives pure black to 0.00%
# everywhere; past ~0.20 the compression starts reading flat rather than soft.
#
# `hi` 1.30 -> 1.12 lands with it, as ART.md § Fill sun — TILES demands (tune the pair, never each
# alone): the fill lowers peak light, so the old 1.30 ceiling no longer binds and only clips the
# pale ramp.
# `ambient` deliberately STAYS 0.50 -- the sweep tried 0.56/0.62 and both re-created the "washed
# rosy and flat" failure the hero's own A/B already rejected. The fill IS the shadow floor
# (ART.md § Fill sun — TILES); a second floor under it only hazes the pale high country. Every
# metric said 0.62 was best and every metric was wrong -- the eye decided it.
#
# `snow_curve` **"gamma8", chosen by eye** off a four-curve A/B rendered at Greenland Summit + north
# and the Alps + Himalaya. `snow_lo`/`snow_hi_pt` deliberately stay 0.55/1.05 -- the window is not
# the lever, the CURVE is; a window narrow enough for Greenland is a threshold for the Alps.
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
# `ambient_knee` **0.30, chosen by eye** on a full-planet pass judged on /earth. `ambient` is a
# CLIFF, not a floor -- measured, 18.07% of Iran's land sat under it carrying no hillshade
# information at all, and the knee is what gave that land its form back. My metric-based
# recommendation was 0.15 and the eye overruled it; the local-contrast std that argued for 0.15 is
# the same proxy that lost the fill-sun A/B, so it is now twice-failed as a stand-in for perceived
# softness.
# `shadow_warmth` **0.55, chosen by eye** on a full-planet pass judged on /earth, after
# 1.0 read too copper on Alpine crops. 1.0 would reproduce the hero's MEASURED shadow warmth (see
# SHADOW_TINT), so this is 55% of the hero -- the value is anchored to a measurement even where it
# departs from it. 0.0 is the pre-`shadow_warmth` look and is bit-identical when off.
# `ice_relief_damp` **0.75, chosen by eye** off a five-rung cap A/B (0/0.25/0.5/0.75/1.0): how much
# thick sea ice CONCEALS the seafloor's shading. The rungs measured linear (mean 2.8/5.2/7.6/10.0 DN
# at 0.25..1.0); 1.0 read soft but 0.75 kept a touch more surface life. The harness that swept them
# was `cap_ladder`, which is deleted -- every axis it offered was a key of this dict, and none of
# them reaches a cap pixel now.
KNOBS = Knobs(alt=palette.SUN_ALT_DEG, fill_strength=0.15, shadow_strength=0.0, shadow_reach=300.0,
              shadow_warmth=0.55,
              ambient=0.50, ambient_knee=0.30, hi=1.12, exposure=1.05, saturation=1.18,
              warmth=0.06, svf_strength=0.20, svf_threshold=0.45, sea_shade=0.55, sea_lift=1.00,
              sea_saturation=0.90, sea_svf=0.5, ice_relief_damp=0.75, snow_lo=0.55, snow_hi_pt=1.05,
              snow_curve="gamma8", lake_curve="log1p")


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


# The hero's shadow is WARMER IN HUE, not merely darker: Cycles fills it with sky plus bounce off
# the rosy land, while the composite's `light` was a single scalar that multiplied all three
# channels equally and therefore could not move hue at all. Measured on heroes/raw/switzerland.png,
# inside narrow elevation bands so the ramp colour is constant: linear R/B is 1.61-1.98x higher in
# the darkest quartile than the brightest, monotonic across all ten luminance deciles.
# -> ART.md "Hero -> tile map".
#
# DERIVATION: the sky's own chromaticity only accounts for 1.334x of that, so the tint is the world
# colour DEEPENED to the measured 1.80x mid-band ratio (world ** 2.0373), the residual being warm
# GI bounce off the land ramp -- which a greyscale SVF stand-in structurally cannot carry.
# Then normalised to luminance 1.0, so this knob moves HUE ONLY and cannot re-create the
# brightness wash that got `ambient` raises rejected twice.
#
# THE `world` IN THAT DERIVATION IS F2E7D5, WHICH THE RIG NO LONGER EMITS. Its ambient is achromatic
# now, and running the same derivation on a grey sky returns (1, 1, 1): the sky half of this tint's
# source is gone and only the GI bounce would survive a re-measurement. The number stands because
# nothing has re-measured a hero under the new sky, NOT because it was re-derived. Anyone re-tuning
# it needs that render first; `scene_build.RIG.world_rgba` cannot be substituted in here.
SHADOW_TINT = (1.205239, 0.972347, 0.669577)
