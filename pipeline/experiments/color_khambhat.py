#!/usr/bin/env python3
"""Two-ramp color test over the Khambhat window.

Approximates the target aesthetic in 2D: warm sand land ramp + desaturated teal
depth ramp, keyed by sign of elevation, modulated by the multidirectional
hillshade. Rendered for both fusion variants — if the naive variant's
above-zero ocean pixels matter anywhere, it is here.
"""

import numpy as np
import rasterio

from pipeline import paths

WORK = paths.DATA / "work/khambhat"

SEA = [  # depth-keyed, stops ascending for np.interp
    (-3000, (72, 125, 138)),
    (-1000, (100, 155, 164)),
    (-200, (128, 180, 186)),
    (-75, (152, 197, 200)),
    (-20, (178, 214, 214)),
    (0, (198, 228, 226)),
]
LAND = [
    (0, (233, 217, 192)),
    (50, (229, 206, 176)),
    (200, (223, 190, 158)),
    (500, (215, 172, 142)),
    (1000, (206, 152, 128)),
    (2000, (198, 138, 118)),
]


def ramp(values, stops):
    xs = [s[0] for s in stops]
    rgb = [np.interp(values, xs, [s[1][c] for s in stops]).astype("float32")
           for c in range(3)]
    return np.stack(rgb, axis=0)


def main():
    for variant in ("naive", "hard"):
        with rasterio.open(f"{WORK}/fused_{variant}.tif") as f:
            elev = f.read(1)
            profile = f.profile
        with rasterio.open(f"{WORK}/hs_{variant}.tif") as h:
            shade = h.read(1).astype("float32") / 255.0

        sea = elev < 0
        rgb = np.where(sea[None], ramp(elev, SEA), ramp(elev, LAND))
        rgb *= (0.45 + 0.55 * shade)[None]

        profile.update(count=3, dtype="uint8", compress="deflate", predictor=2)
        with rasterio.open(f"{WORK}/color_{variant}.tif", "w", **profile) as out:
            out.write(rgb.clip(0, 255).astype("uint8"))
        print(f"wrote color_{variant}.tif")


if __name__ == "__main__":
    main()
