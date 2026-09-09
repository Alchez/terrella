"""The one home for ESA WorldCover: the bucket, its tile naming, and the fetch.

WHY THIS MODULE EXISTS. WorldCover has two readers and neither is an acquirer, so it had no owner
and the second reader imported the first: `render/snow_mask.py` takes class 70 for a hero's snow
mask, and `fuse/build_void_wbm.py` takes class 80 to synthesise the watermask OpenTopography's void
DEM tiles ship without, reaching into the render stage for the bucket URL, the worker count and the
tile-selection rule. A fuse stage depending on a render stage is the shape that says the fact
belongs to neither. This is the module `naturalearth.py`'s own docstring predicts: when a raw source
gains a second reader it wants a home rather than a second constant.

WHAT IS DELIBERATELY NOT HERE: the class each caller wants, and the mosaic each builds. One reads
snow and one reads water, and they VRT over different sets (every held tile against only the ones
overlapping the void extent), so those are local decisions that belong beside the code making them.

WHY THE FETCH IS SHARED AND THE VERDICT IS NOT. Ocean cells legitimately 404, so the fetch asks for
'absent' rather than failing, and every tile coming back absent means the bucket layout moved. What
counts as "every" differs between a country frame and a void extent, so `fetch_tiles` reports the
counts and each caller decides what an empty result means.

Not an entry point: `acquire/` holds the runnable acquirers, and this is a shared fact two stages
read, which is why it sits here beside `naturalearth.py` rather than there.
"""

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
