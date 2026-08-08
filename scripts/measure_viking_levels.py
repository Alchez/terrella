"""Re-measure Mars's ice alpha levels from the Viking brightness field, on the LIVE cap grids.

THE ONLY REPRODUCER OF `mars_ice.ALPHA_LEVELS`, which is why it is tracked. Those four numbers
decide how white Mars's poles render and no unit test can re-derive them: a level is a percentile
over a pixel set, so producing one means building the polar cap grids and burning the mapped units
onto them. It is tracked so the constants in shipped code have a reachable owner — a pointer a
reader cannot follow asserts that an explanation exists somewhere, which is worse than none.

A LEVEL IS VOID WHEN EITHER THE FIELD OR THE GRID MOVES, and both have moved before. Re-run this
after any change to `render/viking_luma`'s output or to `cap_render`'s `edge_lat` — the last such
change moved the north's cap level by 11.4% while leaving the south's at 0.03 DN, so neither
direction of "it probably did not matter" is safe.

THE TWO DEFINITIONS BELOW ARE THE RATIFIED ARM'S AND MUST NOT BE IMPROVED HERE:

  ground = valid & ~lApc & ~Apu      median -> alpha 0
  cap    = valid &  lApc             median -> alpha 1

Two subtleties that a re-derivation gets wrong by being reasonable. `ground` excludes BOTH units at
BOTH poles, including the south where `Apu` is not part of the extent — so it is not `~extent`. And
`cap` is `lApc` ALONE at both poles, including the north where the extent is `lApc | Apu` — so it is
not `extent` either. Using the extent for either one changes the levels and therefore the look.
`mars_ice.albedo_alpha` owns what is done with them; these two lines are the part that lives here.

Grade on LUMA, never the blue/red ratio: that discriminant inverts at the north pole.

Usage, from the repo root:
  systemd-run --user --scope -q -p MemoryMax=12G -p MemorySwapMax=0 \
      --working-directory="$PWD" -E PYTHONPATH="$PWD" -E GDAL_CACHEMAX=512 \
      .venv/bin/python scripts/measure_viking_levels.py [--pipeline|--compare]

  --compare is the standing oracle: it measures both ways and exits non-zero if the shipped field
  stops reproducing the pinned levels.
"""

import subprocess
import sys
from pathlib import Path

import numpy as np
import rasterio

from pipeline import bodies
from pipeline.acquire import download_viking_mosaic
from pipeline.render import mars_ice, viking_luma
from pipeline.tile import cap_render

#: Degrees of latitude kept either side of the pole. The square cap FRAME reaches sqrt(2) * 10
#: degrees from the pole at its corners, i.e. ~75.9, so 20 clears it with room for the ground ring
#: the `ground` percentile is taken over.
BAND_DEGREES = 20.0

#: Neither the mosaic path, the sphere, nor the luma weights are respelled here. Each has an owner
#: — `download_viking_mosaic`, `viking_luma`, `mars_ice` — and this script is the INSTRUMENT that
#: produces the levels, so it is exactly the copy whose drift would be invisible: it would keep
#: agreeing with itself while measuring a field the renderer no longer reads.


def out_dir() -> Path:
    """Scratch for the warps and masks, resolved at call time so a redirected data root moves it."""
    return bodies.work_dir(bodies.get("mars"), "_ice_levels")


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def viking_band(northern: bool) -> Path:
    """Viking's polar band as EPSG:4326-labelled degrees, rebuilt from the raw mosaic.

    THE INFORMATIONAL ARM, kept because `--compare` needs a second opinion that does not come from
    the stage under test. It rebuilds the band on its own square-degree grid, which is NOT the grid
    the pipeline ships; the difference between the two is the measurement `--compare` reports.

    REBUILT RATHER THAN REUSED. Equivalent bands were left behind by an earlier pass with no record
    of how they were made, which is the provenance gap the acquirers exist to close.

    THE RELABEL IS AN IDENTITY ON THE ANGLES, not a reprojection. Once out of SimpleCylindrical
    metres the grid is already degrees on an unflattened sphere; PROJ refuses to warp between
    celestial bodies, so declaring EPSG:4326 is what lets the cap's Earth-sphered AEQD read it.
    `fuse/relabel_mars.py` carries the full argument.
    """
    mosaic = download_viking_mosaic.mosaic_path()
    name = "north" if northern else "south"
    out = out_dir() / f"viking_{name}_4326.tif"
    if out.exists():
        return out

    with rasterio.open(mosaic) as dataset:
        degrees_per_px = 360.0 / dataset.width

    lat_lo, lat_hi = (90.0 - BAND_DEGREES, 90.0) if northern else (-90.0, BAND_DEGREES - 90.0)
    degrees = out_dir() / f"viking_{name}_marsdeg.tif"
    run(["gdalwarp", "-q", "-overwrite", "-t_srs", viking_luma.MARS_LONGLAT,
         "-te", "-180", str(lat_lo), "180", str(lat_hi),
         "-tr", str(degrees_per_px), str(degrees_per_px), "-r", "bilinear",
         "-co", "TILED=YES", str(mosaic), str(degrees)])
    run(["gdal_translate", "-q", "-a_srs", "EPSG:4326", str(degrees), str(out)])
    degrees.unlink()
    return out


def viking_on_cap(grid: cap_render.CapGrid,
                  from_pipeline: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Viking luma on this cap's AEQD grid, and the validity mask, as `(luma, valid)`.

    `from_pipeline` READS `render/viking_luma`'s SHIPPED RASTER INSTEAD OF REBUILDING THE BAND, and
    that is what makes this script an oracle over the pipeline rather than a parallel implementation
    of it. The levels are percentiles of a particular field; if the stage that ships that field
    resamples it even slightly differently from the chain the levels were taken through, the four
    pinned numbers stop describing what gets rendered. Running both modes and comparing is the only
    thing that can say so.
    """
    if from_pipeline:
        band = viking_luma.luma_path()
        warped = out_dir() / f"viking_{grid.name}_cap_pipeline.tif"
    else:
        band = viking_band(grid.name == "north")
        warped = out_dir() / f"viking_{grid.name}_cap.tif"
    if not warped.exists():
        run(["gdalwarp", "-q", "-overwrite", "-t_srs", grid.aeqd,
             "-te", str(-grid.edge_m), str(-grid.edge_m), str(grid.edge_m), str(grid.edge_m),
             "-ts", str(grid.px), str(grid.px), "-r", "bilinear",
             "-co", "TILED=YES", str(band), str(warped)])

    with rasterio.open(warped) as dataset:
        raw = dataset.read().astype(np.float32)
    # The pipeline raster is ALREADY the collapse; the band is still three colours. Both arrive here
    # as the same quantity, which is the comparison's whole premise.
    values = raw[0] if from_pipeline else mars_ice.luma(raw)
    # `values > 0` IS the all-bands-nonzero test the earlier spelling wrote out by hand, and it is
    # identical rather than merely close: the weights are positive and the channels non-negative, so
    # the sum vanishes exactly where all three do. `mars_ice.luma` carries the argument.
    return values, values > 0


def unit_masks(grid: cap_render.CapGrid) -> dict[str, np.ndarray]:
    """`lApc` and `Apu` burnt onto this cap grid, both poles, both units.

    BOTH UNITS AT BOTH POLES even though the south's extent is `lApc` alone, because the `ground`
    percentile excludes `Apu` everywhere and would otherwise take dusty layered deposits as bare
    ground in the one hemisphere where they cover most of the disc.
    """
    bounds = (-grid.edge_m, -grid.edge_m, grid.edge_m, grid.edge_m)
    masks: dict[str, np.ndarray] = {}
    for unit in ("lApc", "Apu"):
        out = out_dir() / f"{unit.lower()}_{grid.name}.tif"
        if not out.exists():
            mars_ice.burn_unit(
                unit, grid.aeqd, bounds, grid.px, grid.px,
                projected=out_dir() / f"{unit.lower()}_{grid.name}_aeqd.geojson", out=out,
                must_draw=f"{unit} must reach the {grid.name} cap disc at edge_lat "
                          f"{grid.edge_lat}")
        with rasterio.open(out) as dataset:
            masks[unit] = dataset.read(1).astype(bool)
    return masks


def measure(grid: cap_render.CapGrid, from_pipeline: bool = False) -> tuple[float, float]:
    """This pole's `(ground, cap)` levels, plus the numbers that say whether they are sane."""
    luma, valid = viking_on_cap(grid, from_pipeline)
    masks = unit_masks(grid)
    lapc, apu = masks["lApc"], masks["Apu"]

    ground_pixels = valid & ~lapc & ~apu
    cap_pixels = valid & lapc
    ground_level = float(np.percentile(luma[ground_pixels], 50))
    cap_level = float(np.percentile(luma[cap_pixels], 50))

    print(f"\n{grid.name.upper()}  (edge_lat {grid.edge_lat}, {grid.px} px, "
          f"{cap_render.cap_ground_metres_per_px(grid):.2f} ground m/px)")
    print(f"  valid {100 * valid.mean():5.2f}%   lApc {100 * lapc.mean():5.2f}%   "
          f"Apu {100 * apu.mean():5.2f}%   ground {100 * ground_pixels.mean():5.2f}%")
    print(f"  ground p50 {ground_level:8.2f}  -> alpha 0")
    print(f"  cap    p50 {cap_level:8.2f}  -> alpha 1   (separation "
          f"{cap_level - ground_level:.2f} DN)")

    alpha = mars_ice.albedo_alpha(luma, (ground_level, cap_level), nodata=-1.0)
    alpha[~valid] = 0.0
    extent = (lapc | apu) if grid.name == "north" else lapc
    print(f"  ground above half alpha: {100 * (alpha[ground_pixels] > 0.5).mean():5.2f}%"
          f"   mean alpha inside extent: {alpha[extent].mean():.3f}")
    for label, region in (("lApc", lapc), ("Apu only", apu & ~lapc)):
        if region.any():
            print(f"    {label:>9}: mean alpha {alpha[region].mean():.3f}")
    return ground_level, cap_level


def sweep(grid: cap_render.CapGrid, from_pipeline: bool = False) -> None:
    """Mean alpha over `lApc` against the percentile chosen for the alpha-1 level, WITH ITS COST.

    THE TWO COLUMNS MOVE TOGETHER AND THAT IS THE WHOLE POINT. A lower percentile shrinks the
    denominator, so the cap saturates — and the same change pushes bare ground up the ramp.
    Reporting saturation without the spill beside it would make the choice look free, which is how a
    look gets picked on one number.

    `ground` stays the p50 throughout: it is the level read from ice-free ground and nothing about
    the alpha-1 choice argues with it.
    """
    luma, valid = viking_on_cap(grid, from_pipeline)
    masks = unit_masks(grid)
    lapc, apu = masks["lApc"], masks["Apu"]
    ground_pixels = valid & ~lapc & ~apu
    cap_pixels = valid & lapc
    ground_level = float(np.percentile(luma[ground_pixels], 50))
    extent = (lapc | apu) if grid.name == "north" else lapc

    print(f"\n{grid.name.upper()} — alpha-1 level against saturation and spill "
          f"(ground p50 {ground_level:.2f} fixed)")
    print("  pct   cap DN   mean a(lApc)   mean a(extent)   ground>half")
    for percentile in (5, 10, 15, 20, 25, 30, 40, 50):
        cap_level = float(np.percentile(luma[cap_pixels], percentile))
        if cap_level <= ground_level:
            print(f"  {percentile:3d}   {cap_level:6.2f}   (below ground level — degenerate)")
            continue
        alpha = mars_ice.albedo_alpha(luma, (ground_level, cap_level), nodata=-1.0)
        alpha[~valid] = 0.0
        print(f"  {percentile:3d}   {cap_level:6.2f}   {alpha[lapc].mean():10.3f}   "
              f"{alpha[extent].mean():12.3f}   {100 * (alpha[ground_pixels] > 0.5).mean():8.2f}%")


def compare_against_the_pipeline() -> int:
    """Measure the levels BOTH ways and refuse any disagreement at the pinned precision.

    THE ONE CHECK THAT SAYS THE SHIPPED FIELD IS THE MEASURED FIELD. `ALPHA_LEVELS` is four
    percentiles of a particular set of numbers; `render/viking_luma` builds those numbers on a grid
    stated rather than inherited, so nothing but running both and subtracting can establish that the
    stage ships what the instrument measured.
    """
    mars = bodies.get("mars")
    worst = 0.0
    for grid in (cap_render.north_grid(mars), cap_render.south_grid(mars)):
        from_band = measure(grid, from_pipeline=False)
        from_stage = measure(grid, from_pipeline=True)
        pinned = mars_ice.ALPHA_LEVELS[grid.name]
        print(f"\n{grid.name.upper()}  pinned {pinned}")
        print(f"  viking_luma   {tuple(round(value, 2) for value in from_stage)}   <- the authority")
        print(f"  rebuilt band  {tuple(round(value, 2) for value in from_band)}   "
              f"(prototype grid, informational)")
        for index, name in enumerate(("ground", "cap")):
            worst = max(worst, abs(from_stage[index] - pinned[index]))
            if round(from_stage[index], 2) != pinned[index]:
                print(f"  MISMATCH {name}: stage {from_stage[index]:.4f} vs pinned {pinned[index]}")
            print(f"  band-vs-stage {name}: {from_band[index] - from_stage[index]:+.4f} DN")
    print(f"\nworst deviation of the SHIPPED field from the pinned levels: {worst:.6f} DN")
    return 0 if worst < 0.005 else 1


def main() -> int:
    out_dir().mkdir(parents=True, exist_ok=True)
    if "--compare" in sys.argv:
        return compare_against_the_pipeline()

    mars = bodies.get("mars")
    from_pipeline = "--pipeline" in sys.argv
    levels = {}
    for grid in (cap_render.north_grid(mars), cap_render.south_grid(mars)):
        levels[grid.name] = measure(grid, from_pipeline)
    for grid in (cap_render.north_grid(mars), cap_render.south_grid(mars)):
        sweep(grid, from_pipeline)

    print("\nALPHA_LEVELS: dict[str, tuple[float, float]] = {")
    for pole, (ground_level, cap_level) in levels.items():
        print(f'    "{pole}": ({ground_level:.2f}, {cap_level:.2f}),')
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
