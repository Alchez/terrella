#!/usr/bin/env python3
"""Resolution-bumping arm for the Switzerland small-country QA.

Patterson's remedy for over-detailed relief (shadedrelief.com): low-pass the
heightfield, then mix a fraction of the removed detail back in —
bumped = smooth + detail_frac * (original - smooth). Applied to an existing
warped render dir, producing a sibling dir with the bumped heightfield and
the untouched masks + frame.json copied over (same grid, same numbers).

Known softness: smoothing bleeds lake plates ~sigma into their shores; the
lake mask recolors the water so only the displaced shoreline blurs. Fine for
an A/B arm; a production version would smooth under a water-aware mask.

Usage:
  resolution_bump.py --src data/work/switzerland/render_1s \
                     --dst data/work/switzerland/render_1s_bumped \
                     [--sigma-px 3.0] [--detail 0.1]
"""

import argparse
import shutil
import sys
from pathlib import Path

import rasterio
from scipy.ndimage import gaussian_filter

COPY = ("oceanmask_aea.tif", "oceanmask_aea.png", "watermask_aea.tif",
        "inlandlake_aea.png", "river_aea.png", "frame.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--dst", type=Path, required=True)
    ap.add_argument("--sigma-px", type=float, default=3.0)
    ap.add_argument("--detail", type=float, default=0.1)
    args = ap.parse_args()

    out_h = args.dst / "heightfield_aea.tif"
    if out_h.exists():
        sys.exit(f"{out_h} already exists — delete the dir to redo")
    args.dst.mkdir(parents=True, exist_ok=True)

    with rasterio.open(args.src / "heightfield_aea.tif") as src:
        profile = src.profile
        dem = src.read(1)
    smooth = gaussian_filter(dem, sigma=args.sigma_px)
    bumped = smooth + args.detail * (dem - smooth)
    with rasterio.open(out_h, "w", **profile) as out:
        out.write(bumped, 1)
    print(f"wrote {out_h} (sigma {args.sigma_px} px, detail {args.detail:g})",
          flush=True)

    for name in COPY:
        shutil.copy2(args.src / name, args.dst / name)
        print(f"copied {name}", flush=True)
    print("complete", flush=True)


if __name__ == "__main__":
    main()
