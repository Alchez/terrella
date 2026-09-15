"""Extract GWL_FCS30's saline class into 0/1 tiles and build their mosaic VRT.

Only the tiles holding saline are written, and a VRT indexes them. The published tiles fall a quarter
cell short of 5 degrees, so no one grid holds them all, and the VRT places each to its nearest cell,
up to half a cell off.

Two tile edges carry a band of rows the wetland classes stop short of, across saline ground the
tile to the north carries up to the edge. `STRIPS` names them, and an unclassified cell in such a
band counts as saline where saline lies on both sides of it in its column. A bridge at every seam
is the temptation, and it fills ground at seams whose two tiles were classified differently.

A saline cell stays saline only where ESA WorldCover calls the ground under its centre one of
`WORLDCOVER_KEEPS`, or names no class there: GWL's saline class takes in plants. The WorldCover tiles
under the saline cells are fetched first, through `download_worldcover`.

A run whose recipe and files agree does nothing. The recipe is written last, and removed before a
rebuild writes anything.

    python -m pipeline.acquire.earth.extract_gwl
"""

import argparse
import itertools
import json
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.errors import RasterioIOError
from rasterio.windows import Window

from pipeline import datasets, paths
from pipeline.acquire.earth import download_gwl, download_worldcover

SALINE = 184
NOT_WETLAND = 0
DEFAULT_WORKERS = 8

#: The WorldCover classes a saline cell's ground may be.
WORLDCOVER_KEEPS = {60: "bare or sparse vegetation", 70: "snow and ice", 80: "permanent water bodies"}
#: WorldCover's value where it names no class.
WORLDCOVER_NODATA = 0
#: Saline rows held against WorldCover at once, which bounds the WorldCover window read for them.
FILTER_ROWS = 1024

#: The edges where the wetland classes stop short of a tile's north edge over saline: the tile, the
#: tile to its north, and the deepest row the band reaches there.
STRIPS = {
    "GWL_FCS30_2020_W70S20.tif": ("GWL_FCS30_2020_W70S15.tif", 66),
    "GWL_FCS30_2020_W70S25.tif": ("GWL_FCS30_2020_W70S20.tif", 63),
}
#: The archive both strips were measured in, and its md5 then: re-pinning it means measuring them again.
STRIPS_MEASURED_ON = ("GWL_FCS30_2020_W65_W90.zip", "40a06a1be51714db4500798a74f877c1")


def tile_dir() -> Path:
    return paths.DATA / "work/gwl/saline"


def saline_vrt() -> Path:
    """The mosaic VRT over every saline tile, and the one place its location is spelled."""
    return paths.DATA / "work/gwl/saline.vrt"


def recipe_path() -> Path:
    return paths.DATA / "work/gwl/saline_recipe.json"


def members() -> list[tuple[Path, str]]:
    """(archive, member) for every tile in every pinned archive."""
    found = []
    for name in download_gwl.ARCHIVES:
        archive = datasets.gwl() / name
        if not archive.exists():
            sys.exit(f"{archive} missing: run pipeline.acquire.earth.download_gwl")
        with zipfile.ZipFile(archive) as bundle:
            found += [(archive, info.filename) for info in bundle.infolist()
                      if info.filename.endswith(".tif")]
    return found


def bridged(values: np.ndarray, above: np.ndarray, deepest_row: int) -> np.ndarray:
    """The cells a strip leaves unclassified across saline, over the tile's first `deepest_row + 1`
    rows: above the column's first saline cell, where the tile to the north is saline at the edge
    (`above`)."""
    band = values[:deepest_row + 1]
    saline = band == SALINE
    first = np.argmax(saline, axis=0)
    across = above & saline.any(axis=0)
    return across & (np.arange(len(band))[:, None] < first) & (band == NOT_WETLAND)


def saline_cells(archive: Path, member: str) -> tuple[np.ndarray, dict]:
    """`member`'s saline cells, bridged where `STRIPS` names it, and the tile's profile."""
    with rasterio.open(f"/vsizip/{archive}/{member}") as source:
        values = source.read(1)
        profile = source.profile
    saline = values == SALINE
    if member in STRIPS:
        north, deepest_row = STRIPS[member]
        with rasterio.open(f"/vsizip/{archive}/{north}") as neighbour:
            last_row = Window(0, neighbour.height - 1, neighbour.width, 1)  # pyright: ignore[reportCallIssue]
            edge = neighbour.read(1, window=last_row)[0]
        saline[:deepest_row + 1] |= bridged(values, edge == SALINE, deepest_row)
    return saline, profile


def _centres(transform: Affine, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Each row's latitude and each column's longitude, at the cell centre."""
    rows, cols = shape
    return (transform.f + (np.arange(rows) + 0.5) * transform.e,
            transform.c + (np.arange(cols) + 0.5) * transform.a)


def _runs(centres: np.ndarray) -> list[tuple[int, slice]]:
    """`centres` split where they cross into another WorldCover tile: each run's tile edge on this
    axis, the south or west one, and the run."""
    edges = np.floor(centres / download_worldcover.TILE_DEG).astype(int) * download_worldcover.TILE_DEG
    breaks = [0, *(np.flatnonzero(np.diff(edges)) + 1).tolist(), len(edges)]
    return [(int(edges[start]), slice(start, stop)) for start, stop in itertools.pairwise(breaks)]


def _blocks(saline: np.ndarray, transform: Affine) -> list[tuple[str, slice, slice]]:
    """The WorldCover tile under each block of `saline` holding any, beside the block's rows and
    columns."""
    lats, lons = _centres(transform, saline.shape)
    return [(download_worldcover.tile_name(lat, lon), rows, cols)
            for (lat, rows), (lon, cols) in itertools.product(_runs(lats), _runs(lons))
            if saline[rows, cols].any()]


def worldcover_under(archive: Path, member: str) -> set[str]:
    """The WorldCover tiles holding the centre of any of `member`'s saline cells."""
    saline, profile = saline_cells(archive, member)
    return {name for name, _rows, _cols in _blocks(saline, profile["transform"])}


def filter_by_worldcover(saline: np.ndarray, transform: Affine) -> int:
    """Clear every saline cell whose centre WorldCover calls neither one of `WORLDCOVER_KEEPS` nor
    unclassified, and return how many. A cell under a tile the store does not hold keeps its call."""
    lats, lons = _centres(transform, saline.shape)
    passing = np.array([*WORLDCOVER_KEEPS, WORLDCOVER_NODATA], np.uint8)
    cleared = 0
    for name, rows, cols in _blocks(saline, transform):
        path = datasets.worldcover() / name
        if not path.exists():
            continue
        with rasterio.open(path) as worldcover:
            for start in range(rows.start, rows.stop, FILTER_ROWS):
                block = saline[start:min(start + FILTER_ROWS, rows.stop), cols]
                held_rows, held_cols = np.flatnonzero(block.any(axis=1)), np.flatnonzero(block.any(axis=0))
                if not len(held_rows):
                    continue
                at = worldcover.transform
                source_rows = np.clip(np.floor((lats[start + held_rows] - at.f) / at.e).astype(int),
                                      0, worldcover.height - 1)
                source_cols = np.clip(np.floor((lons[cols.start + held_cols] - at.c) / at.a).astype(int),
                                      0, worldcover.width - 1)
                top, left = int(source_rows.min()), int(source_cols.min())
                window = Window(left, top, int(source_cols.max()) - left + 1,  # pyright: ignore[reportCallIssue]
                                int(source_rows.max()) - top + 1)
                classes = worldcover.read(1, window=window)[np.ix_(source_rows - top, source_cols - left)]
                cells = np.ix_(start + held_rows, cols.start + held_cols)
                held = saline[cells]
                kept = held & np.isin(classes, passing)
                cleared += int(held.sum() - kept.sum())
                saline[cells] = kept
    return cleared


def extract_tile(archive: Path, member: str) -> tuple[int, int]:
    """Write `member`'s saline cells as a 0/1 tile under `tile_dir()`, filtered by WorldCover, and
    return how many it holds and how many the filter cleared. A tile with none writes nothing."""
    saline, profile = saline_cells(archive, member)
    cleared = filter_by_worldcover(saline, profile["transform"])
    count = int(saline.sum())
    if count:
        profile.update(driver="GTiff", compress="deflate", tiled=True, blockxsize=256,
                       blockysize=256, nodata=None)
        dest = tile_dir() / member
        part = dest.with_suffix(".part")
        with rasterio.open(part, "w", **profile) as sink:
            sink.write(saline.view(np.uint8), 1)
        part.replace(dest)
    return count, cleared


def build_vrt(tiles: list[str]) -> None:
    subprocess.run(["gdalbuildvrt", "-q", "-overwrite", str(saline_vrt())]
                   + [str(tile_dir() / tile) for tile in tiles], check=True)


def build_recipe() -> str:
    """Everything the tiles depend on besides the archives' bytes, which their md5s stand for, and
    WorldCover's, which its edition's bucket stands for."""
    return json.dumps({
        "saline_class": SALINE,
        "bridged_class": NOT_WETLAND,
        "archive_md5": {name: md5 for name, (_size, md5) in download_gwl.ARCHIVES.items()},
        "strips": {tile: {"north": north, "deepest_row": deepest_row}
                   for tile, (north, deepest_row) in STRIPS.items()},
        "worldcover": download_worldcover.BUCKET_URL,
        "worldcover_keeps": sorted(WORLDCOVER_KEEPS),
        "worldcover_nodata": WORLDCOVER_NODATA,
    }, indent=2, sort_keys=True) + "\n"


def is_fresh() -> bool:
    """Whether the run can be skipped: the recorded recipe is today's, and every file the VRT
    indexes is on disk."""
    try:
        recorded = recipe_path().read_text(encoding="utf-8")
    except OSError:
        return False
    if recorded != build_recipe():
        return False
    try:
        with rasterio.open(saline_vrt()) as mosaic:
            return all(Path(name).exists() for name in mosaic.files)
    except RasterioIOError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"tiles read at once (default {DEFAULT_WORKERS})")
    args = parser.parse_args()

    if is_fresh():
        print(f"{saline_vrt()} fresh -> skip", flush=True)
        return 0
    tasks = members()
    recipe_path().unlink(missing_ok=True)
    tile_dir().mkdir(parents=True, exist_ok=True)
    print(f"{len(tasks)} tiles in {len(download_gwl.ARCHIVES)} archives -> {tile_dir()}", flush=True)
    archives, names = zip(*tasks)
    with ThreadPoolExecutor(args.workers) as pool:
        under = sorted(set().union(*pool.map(worldcover_under, archives, names)))
    print(f"{len(under)} WorldCover tiles under the saline class", flush=True)
    fetched = download_worldcover.fetch_tiles(under, progress_every=25)
    print(f"  fetched {fetched['ok']}, held {fetched['skipped']}, absent {fetched['absent']}", flush=True)
    saline, cleared = [], 0
    with ThreadPoolExecutor(args.workers) as pool:
        for done, (member, (count, gone)) in enumerate(zip(names, pool.map(extract_tile, archives, names)), 1):
            cleared += gone
            if count:
                saline.append(member)
            if done % 100 == 0:
                print(f"  {done}/{len(tasks)}", flush=True)
    for stale in {tile.name for tile in tile_dir().glob("*.tif")} - set(saline):
        (tile_dir() / stale).unlink()
    build_vrt(sorted(saline))
    recipe_path().write_text(build_recipe(), encoding="utf-8")
    print(f"{cleared:,} saline cells cleared on WorldCover's word; {len(saline)} tiles hold saline "
          f"-> {saline_vrt()}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
