#!/usr/bin/env python3
"""Measure composite()'s peak RSS on ONE production-shaped planet window.

The planet composite is the stage that has actually OOM-killed this box: windows are the full
131072 px width, so window HEIGHT is the only RAM lever, and shade_planet.py records ~6 GB at
WINDOW_ROWS=256 in float32 (384 rows in float64 peaked ~18 GB and died). The lake-depth branch
adds arrays to exactly that hot spot -- lut[:, index] alone is ~400 MB at this shape -- so the
question is whether it still fits under the cgroup cap.

Measured, not estimated, because estimating this from pixel count is the specific mistake that
OOM-killed the box on 2026-07-15: the intermediates, not the inputs, are what blow up.

Reports ru_maxrss: the process high-water mark, which is what a cgroup MemoryMax accounts
against. Run the two arms in SEPARATE processes -- ru_maxrss never decreases, so a single
process would report the larger arm for both.

Usage:
  python3 -m pipeline.experiments.composite_ram --depth
  python3 -m pipeline.experiments.composite_ram --no-depth
"""

import argparse
import resource
import sys

import numpy as np

from pipeline.tile import shade

WIDTH = 131072       # the planet grid's full width -- windows are always full-width
ROWS = 256           # shade_planet.WINDOW_ROWS
SVF_SHAPE = (2, 4096)  # the global SVF downsample slice a window sees


def peak_gib() -> float:
    """Process high-water RSS in GiB (ru_maxrss is KiB on Linux)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--depth", dest="depth", action="store_true", default=True)
    parser.add_argument("--no-depth", dest="depth", action="store_false")
    parser.add_argument("--rows", type=int, default=ROWS)
    args = parser.parse_args()

    shape = (args.rows, WIDTH)
    inputs_gib = (4 + 4 + 4 + 1 + 1 + (4 if args.depth else 0)) * \
        shape[0] * shape[1] / 1024**3
    print(f"window {shape[1]:,} x {shape[0]}  depth={args.depth}  "
          f"(inputs alone ~{inputs_gib:.2f} GiB)", flush=True)

    heights = np.random.rand(*shape).astype(np.float32) * 6000.0
    hillshade = np.random.rand(*shape).astype(np.float32) * 255
    snow_alpha = np.zeros(shape, dtype=np.float32)
    occlusion = np.random.rand(*SVF_SHAPE).astype(np.float32)
    # A realistic water mix: mostly land, a strip of ocean, a strip of lake.
    watercode = np.zeros(shape, dtype=np.uint8)
    watercode[: args.rows // 4] = 1
    watercode[args.rows // 4: args.rows // 2] = 2
    ocean = watercode == 1
    water = (watercode == 2) | (watercode == 3)
    depth = None
    if args.depth:
        depth = np.where(watercode == 2,
                         np.random.rand(*shape).astype(np.float32) * 1642.0, 0.0
                         ).astype(np.float32)

    after_inputs = peak_gib()
    print(f"  peak after allocating inputs : {after_inputs:6.2f} GiB", flush=True)

    rgb = shade.composite(heights, ocean, water, snow_alpha, hillshade, occlusion,
                          SVF_SHAPE, shape, depth=depth)
    peak = peak_gib()
    print(f"  PEAK through composite()     : {peak:6.2f} GiB", flush=True)
    print(f"  composite's own working set  : {peak - after_inputs:6.2f} GiB", flush=True)
    print(f"  output {rgb.shape} {rgb.dtype}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
