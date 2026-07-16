#!/usr/bin/env python3
"""Does `-co NUM_THREADS` actually speed up the composite's GTiff writer?

PLAN item 3 proposes `num_threads="ALL_CPUS"` on the two rasterio writers on the strength of one
number -- libdeflate = 9.93% of python-side CPU -- that lives nowhere but PLAN and has no surviving
perf artifact. The NUM_THREADS family has already been measured and REJECTED three times here
(HISTORY 2026-07-16: `-multi`, `-wm`/`-wo NUM_THREADS`, and `-co NUM_THREADS` for color-relief,
where libdeflate was only 4.33% of the stage). A fourth instance of a flag this project keeps
killing needs evidence, not a plausible percentage.

Two things would make a synthetic version of this lie, and both are avoided:
  * RANDOM data is incompressible -- DEFLATE would do maximum work for minimum gain and so
    OVERSTATE the flag. This reads REAL RGB from planet_rgb.tif, from a terrain band, not from
    the flat polar caps that compress to nothing.
  * The production pattern writes 256-row windows into 512-row TILES, so each write only
    half-fills a tile row and compression happens on cache FLUSH, not on write. Benchmarking
    whole-tile writes would measure a pattern the pipeline never uses.

Reads happen up front and are excluded from the timed section. The timer spans the writes AND the
close, because that is where the deferred compression actually lands.

Usage:
  python3 -m pipeline.experiments.writer_threads
"""

import argparse
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data/work/planet_tiles/planet_rgb.tif"
BENCH_DIR = ROOT / "data/work/_bench_writer"  # ext4: /tmp is a RAM-backed tmpfs here

WINDOW_ROWS = 256   # shade_planet.WINDOW_ROWS
BLOCK = 512         # shade_planet's blockxsize/blockysize
START_ROW = 34_000  # northern mid-latitudes: real terrain, not the flat caps


def timed_write(out_path: Path, blocks: list[np.ndarray], profile: dict,
                num_threads: str | None) -> float:
    """Write pre-read windows with the production profile; return wall seconds."""
    options = dict(profile)
    if num_threads is not None:
        options["num_threads"] = num_threads
    start = time.perf_counter()
    with rasterio.open(out_path, "w", **options) as dst:
        for index, block in enumerate(blocks):
            window = Window(0, index * WINDOW_ROWS,  # pyright: ignore[reportCallIssue] — rasterio untyped, attrs init invisible
                            block.shape[2], block.shape[1])
            dst.write(block, window=window)
    return time.perf_counter() - start


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--windows", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()

    if not SRC.exists():
        print(f"missing {SRC}", flush=True)
        return 1
    BENCH_DIR.mkdir(parents=True, exist_ok=True)

    rows = args.windows * WINDOW_ROWS
    with rasterio.open(SRC) as src:
        width = src.width
        print(f"source {src.width:,} x {src.height:,}  reading {args.windows} x "
              f"{WINDOW_ROWS} rows from row {START_ROW:,}", flush=True)
        blocks = []
        for index in range(args.windows):
            window = Window(0, START_ROW + index * WINDOW_ROWS,  # pyright: ignore[reportCallIssue] — rasterio untyped, attrs init invisible
                            width, WINDOW_ROWS)
            blocks.append(src.read(window=window))

    raw_mb = sum(block.nbytes for block in blocks) / 1024**2
    print(f"read {raw_mb:,.0f} MiB of real RGB", flush=True)

    profile: dict = dict(
        driver="GTiff", width=width, height=rows, count=3, dtype="uint8",
        tiled=True, blockxsize=BLOCK, blockysize=BLOCK,
        compress="deflate", photometric="RGB", BIGTIFF="YES")

    arms = {"no flag (today)": None, "num_threads=ALL_CPUS": "ALL_CPUS"}
    results: dict[str, list[float]] = {name: [] for name in arms}

    # Alternate the arms across repeats so page-cache warmth cannot favour either one.
    for repeat in range(args.repeats):
        for name, threads in arms.items():
            out_path = BENCH_DIR / f"bench_{repeat}_{'mt' if threads else 'st'}.tif"
            seconds = timed_write(out_path, blocks, profile, threads)
            results[name].append(seconds)
            size_mb = out_path.stat().st_size / 1024**2
            print(f"  repeat {repeat}  {name:22s} {seconds:6.2f} s  "
                  f"-> {size_mb:6.1f} MiB ({raw_mb / size_mb:.1f}x)", flush=True)
            out_path.unlink()

    print("\n--- best of each arm ---", flush=True)
    baseline = min(results["no flag (today)"])
    for name, times in results.items():
        best = min(times)
        print(f"  {name:22s} {best:6.2f} s   {baseline / best:5.2f}x", flush=True)

    shutil.rmtree(BENCH_DIR, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
