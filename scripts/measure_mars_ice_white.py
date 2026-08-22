"""Re-measure the colour of Mars's polar ice from the Viking mosaic, on the LIVE cap grids.

THE ONLY REPRODUCER OF `palette.MARS_ICE_WHITE`, which is why it is tracked. Those four values decide
what colour each pole renders and no unit test can re-derive them: the target is an alpha-weighted
mean over the shipped ice, so producing one means building the cap grids, burning the mapped units
and grading the field exactly as the renderer does.

A TARGET IS VOID WHEN ANYTHING UNDER IT MOVES, and two things already have: `ALPHA_LEVELS` was
re-pinned once when the original pair turned out to be percentiles of a scaffold rather than of the
shipped field, and `edge_lat` went 78 to 80. Either changes which pixels the mean runs over. Nothing
else in the repo can notice — the hex values keep reading as measured, because they were, against a
subject that has since moved.

RED AND VIOLET ARE EVIDENCE; GREEN IS NOT AND CANNOT BE. The mosaic's green band is a fixed linear
combination of its own red and violet, so it carries no independent information and this script
measures a RATIO, never a colour. Turning that ratio into a colour is the second half below, and it
is a stated design rule rather than a measurement.

THE RATIO AND THE WEIGHT COME OFF THE SAME PIXELS, which is the reason for one warp rather than two.
The alpha is graded from luma and the luma is collapsed from the very RGB being averaged, so no
resampling difference can creep between the weight and the thing it weights.

WHAT IS DELIBERATELY NOT RESPELLED HERE. The extent rule, the levels, the grading curve, the feather
and the luma weights each have an owner in `look/mars_ice`, and this script is the INSTRUMENT that
produces the target — so it is exactly the copy whose drift would be invisible, agreeing with itself
while measuring something the renderer no longer paints.

Usage, from the repo root:
  systemd-run --user --scope -q -p MemoryMax=16G -p MemorySwapMax=0 \
      --working-directory="$PWD" -E PYTHONPATH="$PWD" -E GDAL_CACHEMAX=512 \
      .venv/bin/python scripts/measure_mars_ice_white.py [--compare]

  --compare is the standing oracle: it re-measures, re-derives, and exits non-zero if the pinned
  constants stop reproducing.
"""

import subprocess
import sys
from pathlib import Path

import numpy as np
import rasterio

from pipeline import bodies, freshness
from pipeline.acquire import download_sim3292, download_viking_mosaic
from pipeline.look import mars_ice, palette, viking_luma
from pipeline.tile import cap_render

#: Degrees of latitude kept either side of the pole. Imported rather than restated: the levels script
#: crops the same band for the same reason, and the two held a copy each tied together by a comment.
BAND_DEGREES = cap_render.CAP_MEASURE_BAND_DEGREES

#: Rec709, the same weights the luminance of a white is judged by everywhere else on this site.
REC709 = (0.2126, 0.7152, 0.0722)

#: EARTH'S OWN WHITE IS THE UNIT OF MEASURE, not an arbitrary brightness. Holding these makes the
#: change from Earth's pair to a body's own a pure hue rotation, so nothing but colour moves.
LIT_LUMINANCE = 239.4
SHADOW_LUMINANCE = 195.6

#: Earth's sunlit white sits this far above its own (R+B)/2. Green is unmeasurable, so it follows
#: Earth's rule rather than the data; this offset IS that rule, read off the reference body.
LOCUS_OFFSET = 2.0

#: HOW EACH POLE'S RATIO IS SPENT, and the south's is not a preference. sRGB cannot hold Earth's
#: luminance at the south's warmth — red pins at 255 and the locus arm falls to 231.6 — so the south
#: buys the brightness back by lifting green off the locus. That was ratified by eye, and it is the
#: one step here that a measurement did not decide.
STYLE_BY_POLE = {"north": "locus", "south": "cream"}

#: How far a pinned pair's own red:violet may sit from the measured target before this is drift.
#:
#: THE TOLERANCE IS ON THE RATIO BECAUSE THE RATIO IS WHAT IS MEASURED. Comparing the four rounded
#: bytes instead makes the oracle fire on the last bit of an 8-bit channel: the first run of this
#: script reproduced the pinned north sunlit exactly and missed three other values by one DN, on
#: ratios agreeing to 0.004. An oracle that is red on arithmetic noise gets ignored, which is worse
#: than not having one.
#:
#: 0.02 is set against both ends of the range it must separate. Two measurement paths over the same
#: ice agree to about 0.004, and the two poles differ from each other by 0.242 — so this sits five
#: times above the noise and twelve times below the smallest difference that means anything.
RATIO_TOLERANCE = 0.02


def out_dir() -> Path:
    """Scratch for the warps and masks, resolved at call time so a redirected data root moves it."""
    return bodies.work_dir(bodies.get("mars"), "_ice_white")


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def luminance(rgb) -> float:
    return sum(weight * channel for weight, channel in zip(REC709, rgb, strict=True))


def on_locus(ratio: float, target: float, offset: float) -> tuple[float, float, float]:
    """The (R, G, B) with this red:violet ratio, this Rec709 luminance, and green on the locus.

    CLIPS BY PINNING RED AT 255, which spends luminance rather than hue. Past a certain warmth the
    sRGB cube simply cannot hold Earth's brightness, and that is a fact about the colour space rather
    than a decision — the caller sees it as a luminance that came out below `target`.
    """
    red_weight, green_weight, blue_weight = REC709
    blue = ((target - green_weight * offset)
            / (red_weight * ratio + green_weight * (ratio + 1) / 2 + blue_weight))
    red = ratio * blue
    if red > 255.0:
        red, blue = 255.0, 255.0 / ratio
    return red, (red + blue) / 2 + offset, blue


def cream(ratio: float, target: float) -> tuple[float, float, float]:
    """The same hue at full red, buying back the luminance the locus loses by lifting green."""
    red, blue = 255.0, 255.0 / ratio
    green = (target - REC709[0] * red - REC709[2] * blue) / REC709[1]
    return red, green, blue


def arm(ratio: float, style: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """One pole's `(sunlit, shadowed)` pair.

    THE SHADOW INHERITS THE LIT END'S REALISED GREEN OFFSET rather than the nominal one, so both ends
    sit on a single locus and the pair reads as one white under a light. Deriving the shadow
    independently gives two whites that happen to share a ratio, which is visible as a hue shift
    across the terminator.
    """
    lit = (cream(ratio, LIT_LUMINANCE) if style == "cream"
           else on_locus(ratio, LIT_LUMINANCE, LOCUS_OFFSET))
    realised_offset = lit[1] - (lit[0] + lit[2]) / 2
    shadow = on_locus(ratio, SHADOW_LUMINANCE, realised_offset)
    return tuple(round(channel) for channel in lit), tuple(round(channel) for channel in shadow)


def earth_control() -> bool:
    """Derive Earth's shipped pair from Earth's own ratio and luminance, and say whether it lands.

    THE RUN IS REFUSED IF THIS FAILS. Every number below comes out of the same two functions, so a
    derivation that cannot reproduce a pair we have looked at for months has no standing on a pair
    nobody has seen. The shadow's offset is Earth's own realised one, for the reason `arm` gives.
    """
    lit = tuple(round(channel) for channel in
                on_locus(palette.SNOW_RGB[0] / palette.SNOW_RGB[2], LIT_LUMINANCE, LOCUS_OFFSET))
    shadow_offset = (palette.SNOW_SHADOW_RGB[1]
                     - (palette.SNOW_SHADOW_RGB[0] + palette.SNOW_SHADOW_RGB[2]) / 2)
    shadow = tuple(round(channel) for channel in
                   on_locus(palette.SNOW_SHADOW_RGB[0] / palette.SNOW_SHADOW_RGB[2],
                            SHADOW_LUMINANCE, shadow_offset))
    ok = lit == palette.SNOW_RGB and shadow == palette.SNOW_SHADOW_RGB
    print("CONTROL  Earth's pair, re-derived from its own ratio and luminance")
    print(f"           lit {lit} vs shipped {tuple(palette.SNOW_RGB)}"
          f"   {'OK' if lit == palette.SNOW_RGB else 'MISMATCH'}")
    print(f"        shadow {shadow} vs shipped {tuple(palette.SNOW_SHADOW_RGB)}"
          f"   {'OK' if shadow == palette.SNOW_SHADOW_RGB else 'MISMATCH'}")
    return ok


def viking_rgb_on_cap(grid: cap_render.CapGrid) -> np.ndarray:
    """The mosaic's three colours on this cap's AEQD grid, as float32 `(3, px, px)`.

    CROPPED TO A POLAR BAND BEFORE THE CAP WARP, and that is correctness rather than speed. Warping
    the global mosaic straight onto an AEQD disc makes GDAL read the source at the disc's
    pole-inflated average scale and silently decimate it — no error, a plausible raster, and an
    ice edge made of exactly the structure that decimation erases.

    `viking_luma.degrees_vrt` owns the two-step relabel out of SimpleCylindrical metres and carries
    why it cannot be one step; only the window is local to this script.

    THE CACHE IS GATED ON THE DISC, NOT ON THE FILENAME. This name carries the pole and nothing else,
    so an `edge_lat` or `CAP_PX` that moved would be answered with the previous disc's pixels and the
    run would report a hue for ice it never looked at — the one failure this script cannot survive,
    since it exists to notice exactly that class of drift in the constants it reproduces.
    """
    warped = out_dir() / f"viking_rgb_{grid.name}_cap.tif"
    mosaic = download_viking_mosaic.mosaic_path()
    if freshness.warp_needs_rebuild(warped, cap_render.cap_reference_grid(grid), mosaic):
        whole = viking_luma.degrees_vrt(mosaic, out_dir() / "viking_degrees.vrt")
        northern = grid.name == "north"
        lat_lo, lat_hi = ((90.0 - BAND_DEGREES, 90.0) if northern
                          else (-90.0, BAND_DEGREES - 90.0))
        band = out_dir() / f"viking_rgb_{grid.name}_band.tif"
        run(["gdal_translate", "-q", "-projwin", "-180", str(lat_hi), "180", str(lat_lo),
             "-co", "TILED=YES", str(whole), str(band)])
        run(["gdalwarp", "-q", "-overwrite", "-t_srs", grid.aeqd,
             "-te", str(-grid.edge_m), str(-grid.edge_m), str(grid.edge_m), str(grid.edge_m),
             "-ts", str(grid.px), str(grid.px), "-r", "bilinear",
             "-co", "TILED=YES", str(band), str(warped)])
        band.unlink()
        freshness.mark_done(warped)

    with rasterio.open(warped) as dataset:
        return dataset.read().astype(np.float32)


def shipped_alpha(grid: cap_render.CapGrid, rgb: np.ndarray) -> np.ndarray:
    """This pole's ice alpha, composed exactly as `perennial_ice._mars_cap_ice` composes it.

    Graded field times feathered extent, every term through its owner in `mars_ice`. The field is the
    luma of the RGB passed in rather than the shipped raster, so the weight and the colour it weights
    are the same pixels; `measure_viking_levels.py --compare` is what separately holds that luma to
    the one the renderer reads.
    """
    field = mars_ice.luma(rgb)
    graded = mars_ice.albedo_alpha(field, mars_ice.ALPHA_LEVELS[grid.name], viking_luma.NODATA)
    width, height, bounds = cap_render.cap_reference_grid(grid)
    masks: dict[str, np.ndarray] = {}
    for unit in mars_ice.NORTH_UNITS:
        burnt = out_dir() / f"{unit.lower()}_{grid.name}.tif"
        if freshness.warp_needs_rebuild(burnt, cap_render.cap_reference_grid(grid),
                                        download_sim3292.unit_path(unit)):
            mars_ice.burn_unit(
                unit, grid.aeqd, bounds, width, height,
                projected=out_dir() / f"{unit.lower()}_{grid.name}_aeqd.geojson", out=burnt,
                must_draw=f"{unit} must reach the {grid.name} cap disc at edge_lat {grid.edge_lat}")
            freshness.mark_done(burnt)
        with rasterio.open(burnt) as dataset:
            masks[unit] = dataset.read(1).astype(bool)

    extent = mars_ice.extent_for(masks, grid.name == "north")
    feather = mars_ice.feather_alpha(extent, cap_render.cap_ground_metres_per_px(grid))
    return graded * feather


def paint_target(grid: cap_render.CapGrid) -> float:
    """This pole's alpha-weighted red:violet, over the ice as it is actually painted.

    WEIGHTED, NOT MASKED, because the ice does not have an edge — it has a grading. A threshold would
    make the answer a function of where the threshold was put, and the dim tail is a large part of
    the north's extent.
    """
    rgb = viking_rgb_on_cap(grid)
    alpha = shipped_alpha(grid, rgb)
    weight = alpha.sum()
    red, blue = float((alpha * rgb[0]).sum()), float((alpha * rgb[2]).sum())
    ratio = red / blue

    print(f"\n{grid.name.upper()}  (edge_lat {grid.edge_lat}, {grid.px} px, "
          f"{cap_render.cap_ground_metres_per_px(grid):.2f} ground m/px)")
    print(f"  painted ice: {100 * (alpha > 0).mean():5.2f}% of the disc, "
          f"mean alpha where painted {alpha[alpha > 0].mean():.3f}")
    print(f"  alpha-weighted   red {red / weight:7.2f}   violet {blue / weight:7.2f}"
          f"   ratio {ratio:.3f}")
    return ratio


def report():
    """Measure and derive both poles as `(ratios, pairs)`, or None if the control refused."""
    if not earth_control():
        print("\nREFUSING: the derivation does not reproduce Earth's shipped pair", flush=True)
        return None

    mars = bodies.get("mars")
    measured, derived = {}, {}
    for grid in (cap_render.north_grid(mars), cap_render.south_grid(mars)):
        ratio = paint_target(grid)
        style = STYLE_BY_POLE[grid.name]
        lit, shadow = arm(ratio, style)
        measured[grid.name], derived[grid.name] = ratio, (lit, shadow)
        print(f"  {style:>6} arm -> #{lit[0]:02X}{lit[1]:02X}{lit[2]:02X} {lit}"
              f"  /  #{shadow[0]:02X}{shadow[1]:02X}{shadow[2]:02X} {shadow}"
              f"   luminance {luminance(lit):.1f}")
    return measured, derived


def compare(measured, derived) -> int:
    """Hold the SHIPPED whites to the hue the ice now measures.

    THE TEST IS THAT EACH PINNED PAIR STILL DESCRIBES ITS OWN ICE, which is a question about hue and
    not about bytes. Both ends of a pair are checked because a pair is one white under two lights: if
    the shadow's ratio drifted alone, the terminator would shift hue and nothing about the sunlit end
    would say so.

    The derived pair is printed rather than asserted. It is what a re-pin would copy, but a re-pin is
    a look decision — the eye ratified these, and a ratio has no standing to overrule it.
    """
    print("\n--- do the shipped whites still describe this ice? ---")
    worst = 0.0
    for pole, target in sorted(measured.items()):
        for end, pinned in (("sunlit", palette.MARS_ICE_WHITE[pole][0]),
                            ("shadow", palette.MARS_ICE_WHITE[pole][1])):
            ratio = pinned[0] / pinned[2]
            deviation = abs(ratio - target)
            worst = max(worst, deviation)
            print(f"  {pole:>5} {end}: pinned {tuple(pinned)} is red:violet {ratio:.3f} "
                  f"against a measured {target:.3f}   off by {deviation:.3f}"
                  f"   {'OK' if deviation <= RATIO_TOLERANCE else 'DRIFT'}")

    print(f"\nworst deviation of a shipped white from its measured hue: {worst:.3f} "
          f"(tolerance {RATIO_TOLERANCE})")
    if worst > RATIO_TOLERANCE:
        print("\nThe subject moved. What this run derives from the current data:")
        for pole, (lit, shadow) in sorted(derived.items()):
            print(f'    "{pole}": ({tuple(lit)}, {tuple(shadow)}),')
        print("Re-judge on the globe before re-pinning.")
    return 0 if worst <= RATIO_TOLERANCE else 1


def main() -> int:
    out_dir().mkdir(parents=True, exist_ok=True)
    result = report()
    if result is None:
        return 1
    if "--compare" in sys.argv:
        return compare(*result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
