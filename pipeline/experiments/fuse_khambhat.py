#!/usr/bin/env python3
"""Seam experiment: fuse GLO-30 land with GEBCO bathymetry over the Gulf of Khambhat.

Produces two fused heightfields over the same window for visual comparison:
  fused_naive.tif  ocean pixels take upsampled GEBCO as-is
  fused_hard.tif   ocean pixels take min(GEBCO, -1) — sea forced below land zero

Ocean = WBM class 1 only; lakes (2) and rivers (3) keep the land surface.
Inputs are the pre-cut window rasters from data/work/khambhat/.
"""

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

from pipeline import paths

WORK = paths.DATA / "work/khambhat"
GEBCO = paths.DATA / "raw/gebco/gebco_2026_n40.0_s0.0_w60.0_e100.0_geotiff.tif"


def main():
    with rasterio.open(f"{WORK}/dem_win.tif") as d:
        dem = d.read(1)
        profile = d.profile
        transform, crs = d.transform, d.crs
    with rasterio.open(f"{WORK}/wbm_win.tif") as w:
        wbm = w.read(1)

    gebco_up = np.empty_like(dem)
    with rasterio.open(GEBCO) as g:
        reproject(
            source=rasterio.band(g, 1),
            destination=gebco_up,
            dst_transform=transform,
            dst_crs=crs,
            resampling=Resampling.cubic_spline,
        )

    ocean = wbm == 1
    print(f"window: {dem.shape}, ocean fraction {ocean.mean():.1%}")
    print(f"gebco under ocean mask: min {gebco_up[ocean].min():.0f}, "
          f"max {gebco_up[ocean].max():.0f}")
    print(f"ocean pixels where upsampled gebco >= 0: "
          f"{(gebco_up[ocean] >= 0).mean():.2%}")

    profile.update(dtype="float32", compress="deflate", predictor=3)
    for name, sea in [
        ("fused_naive", gebco_up),
        ("fused_hard", np.minimum(gebco_up, -1.0)),
    ]:
        fused = np.where(ocean, sea, dem).astype("float32")
        with rasterio.open(f"{WORK}/{name}.tif", "w", **profile) as out:
            out.write(fused, 1)
        print(f"wrote {name}.tif")


if __name__ == "__main__":
    main()
