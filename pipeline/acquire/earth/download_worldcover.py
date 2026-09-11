"""ESA WorldCover 2021 v200: the bucket, its tile naming, and the fetch.

Two stages read different classes of the same rasters, `render/snow_mask.py` class 70 for a hero's
snow mask and `fuse/build_void_wbm.py` class 80 for the watermask OpenTopography's void DEM tiles
ship without. Each one's class and its mosaic stay beside the code choosing them: they VRT over
different sets, every held tile against only the ones overlapping the void extent.

Ocean cells legitimately 404, so the fetch asks for 'absent' rather than failing. What counts as
"every tile absent" differs between a country frame and a void extent, so `fetch_tiles` returns the
counts and each caller decides what an empty result means.

`--extent` is required, as it is on `download_glo30`: the global land set is ~114 GB and no caller
wants it, so there is no shape of this command that fetches a planet by default.
"""

import argparse
import concurrent.futures as cf
import math
import sys
from pathlib import Path

from pipeline import datasets
from pipeline.fetch import download_one

BUCKET_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"

#: The bucket's tile size in degrees, which is also the grid its SW corners sit on.
TILE_DEG = 3

WORKERS = 6


def tile_name(lat: int, lon: int) -> str:
    """Bucket object name for the tile with this SW corner."""
    ns = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"
    ew = f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
    return f"ESA_WorldCover_10m_2021_v200_{ns}{ew}_Map.tif"


def tiles_for_bounds(west, south, east, north) -> list[str]:
    """Every tile overlapping a lon/lat window (SW corners on the tile grid; strict overlap, so an
    edge-touching tile is excluded)."""
    names = []
    for lat in range(math.floor(south / TILE_DEG) * TILE_DEG,
                     math.ceil(north / TILE_DEG) * TILE_DEG, TILE_DEG):
        for lon in range(math.floor(west / TILE_DEG) * TILE_DEG,
                         math.ceil(east / TILE_DEG) * TILE_DEG, TILE_DEG):
            names.append(tile_name(lat, lon))
    return names


def fetch_tiles(names: list[str], *, progress_every: int = 0) -> dict[str, int]:
    """Fetch `names` into the WorldCover store, returning counts by status.

    Exits on a real failure, since a partial mosaic renders as terrain that is simply wrong rather
    than as an error. An absent tile is not a failure: it is the bucket saying ocean.

    `progress_every` prints a running tally every N completions, for the caller whose window is
    large enough that silence reads as a hang.
    """
    store = datasets.worldcover()
    store.mkdir(parents=True, exist_ok=True)
    counts = {"ok": 0, "skipped": 0, "absent": 0}
    failures: list[str] = []
    with cf.ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(download_one, f"{BUCKET_URL}/{name}", store / name,
                               timeout=120, absent_on_404=True): name for name in names}
        for index, future in enumerate(cf.as_completed(futures), 1):
            status = future.result()
            if status.startswith("failed"):
                failures.append(f"{futures[future]}  {status}")
            else:
                counts[status] += 1
            if progress_every and (index % progress_every == 0 or index == len(names)):
                print(f"  [{index}/{len(names)}] ok={counts['ok']} skipped={counts['skipped']} "
                      f"absent(ocean)={counts['absent']} failed={len(failures)}", flush=True)
    if failures:
        sys.exit("WorldCover downloads failed — rerun to retry (finished tiles skip):\n  "
                 + "\n  ".join(failures))
    return counts


def held(names: list[str]) -> list[Path]:
    """The subset of `names` actually on disk, as paths, for a caller mosaicking only its own
    window rather than the whole store."""
    store = datasets.worldcover()
    return [store / name for name in names if (store / name).exists()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extent", nargs=4, type=float, required=True,
                        metavar=("W", "S", "E", "N"),
                        help="lon/lat window; overlapping 3x3 degree tiles are fetched")
    args = parser.parse_args()

    names = tiles_for_bounds(*args.extent)
    print(f"{len(names)} candidate tiles in extent", flush=True)
    counts = fetch_tiles(names, progress_every=25)
    print(f"ok={counts['ok']} skipped={counts['skipped']} absent(ocean)={counts['absent']}",
          flush=True)
    print("complete", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
