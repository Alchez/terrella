#!/usr/bin/env python3
"""A/B the sea look: shade the planet under two sea-knob sets in ONE composite pass,
then cut z0-7 tiles for each into tiles_v1/ tiles_v2/ WITHOUT touching the live tiles.

Reuses the cached shared inputs (height/land/hillshade/masks) and regenerates only the
sea colour (the palette ramp changed). The composite emits both variants per window so
the expensive per-window work (reads, snow warp, glacier rasterize) is paid once.

    # smoke test: composite the first 6 windows only, no tiles (prove it doesn't OOM)
    python -m pipeline.experiments.sea_ab --regen-sea --smoke 6
    # full run (background): regen sea once, dual composite, z0-7 tiles for both
    python -m pipeline.experiments.sea_ab --regen-sea

The winner gets the production z0-8 pass later via pipeline.tile.shade_planet.
"""

import argparse
import subprocess
from pathlib import Path

from pipeline.tile import shade_planet as sp

# The two candidates from the Red Sea prototype (sea_shade / sea_lift / sea_svf).
VARIANTS = {
    "v1": {"sea_shade": 0.55, "sea_lift": 1.00, "sea_svf": 0.5},  # calmer, water-like sheen
    "v2": {"sea_shade": 0.72, "sea_lift": 0.98, "sea_svf": 0.7},  # stronger seafloor relief
}


def tile_variant(planet_tif: Path, work: Path, name: str, max_zoom: int) -> None:
    """Overviews + z0..max_zoom 512px tiles into work/tiles_<name> (non-destructive)."""
    print(f"overviews ({name}) ...", flush=True)
    subprocess.run(["gdaladdo", "-r", "average", str(planet_tif),
                    "2", "4", "8", "16", "32", "64", "128"], check=True)
    out = work / f"tiles_{name}"
    print(f"cutting z0-{max_zoom} 512px tiles -> {out} ...", flush=True)
    subprocess.run(["gdal", "raster", "tile", "--min-zoom=0", f"--max-zoom={max_zoom}",
                    "--tile-size=512", "--resampling=cubic", "--convention=xyz",
                    "--skip-blank", "--resume", str(planet_tif), str(out)], check=True)
    print(f"tiles ready -> {out}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=sp.ROOT / "data/work/planet_tiles")
    ap.add_argument("--regen-sea", action="store_true",
                    help="delete stale sea_3857.tif so it re-colours from the current palette")
    ap.add_argument("--smoke", type=int, default=None, metavar="N",
                    help="composite only the first N windows and skip tiling (crash smoke test)")
    ap.add_argument("--window-rows", type=int, default=192,
                    help="composite window height — the RAM lever (192 leaves headroom)")
    ap.add_argument("--max-zoom", type=int, default=7,
                    help="tile pyramid ceiling for the comparison (z8 is deferred to the winner)")
    args = ap.parse_args()
    work = args.out

    if args.regen_sea:
        for stale in ("sea_3857.tif", "ramp_sea.txt"):
            (work / stale).unlink(missing_ok=True)
        print("removed stale sea colour -> will re-colour from the current palette", flush=True)

    height = sp.warp_inputs(work)                      # cached -> skip
    land, sea, hs = sp.color_and_hillshade(work, height)  # regens sea only; land/hs cached
    print("global sky-view factor ...", flush=True)
    occ = sp.global_occlusion(height)
    tifs = sp.composite_planet(work, land, sea, hs, occ, variants=VARIANTS,
                               window_rows=args.window_rows, max_windows=args.smoke)
    if args.smoke is not None:
        print(f"smoke composite of {args.smoke} windows done (partial rasters, no tiles)", flush=True)
        return 0
    for name, planet_tif in tifs.items():
        tile_variant(planet_tif, work, name, args.max_zoom)
    print("DONE — tiles_v1 / tiles_v2 ready (live tiles untouched)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
