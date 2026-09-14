"""Extract GWL_FCS30's saline class into 0/1 tiles and build their mosaic VRT.

Only the tiles holding saline are written, and a GDAL average of the VRT onto any grid is the saline
share of each cell.

Two tile edges carry a band of rows the wetland classes stop short of, across saline ground the
tile to the north carries up to the edge. `STRIPS` names them, and an unclassified cell in such a
band counts as saline where saline lies on both sides of it in its column. A bridge at every seam
is the temptation, and it fills ground at seams whose two tiles were classified differently.

A run whose recipe and files agree does nothing. The recipe is written last, and removed before a
rebuild writes anything.

    python -m pipeline.acquire.earth.extract_gwl
"""

import argparse
import json
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
from rasterio.errors import RasterioIOError
from rasterio.windows import Window

from pipeline import datasets, paths
from pipeline.acquire.earth import download_gwl

SALINE = 184
NOT_WETLAND = 0
DEFAULT_WORKERS = 8

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


def extract_tile(archive: Path, member: str) -> int:
    """Write `member`'s saline cells as a 0/1 tile under `tile_dir()`, bridged where `STRIPS` names
    it, and return how many there are. A tile with none writes nothing."""
    with rasterio.open(f"/vsizip/{archive}/{member}") as source:
        values = source.read(1)
        profile = source.profile
    saline = values == SALINE
    if member in STRIPS:
        north, deepest_row = STRIPS[member]
        with rasterio.open(f"/vsizip/{archive}/{north}") as neighbour:
            last_row = Window(0, neighbour.height - 1, neighbour.width, 1)  # pyright: ignore[reportCallIssue]
            edge = neighbour.read(1, window=last_row)[0]
        filled = bridged(values, edge == SALINE, deepest_row)
        saline[:deepest_row + 1] |= filled
        print(f"  {member}: {int(filled.sum()):,} cells bridged", flush=True)
    count = int(saline.sum())
    if count:
        profile.update(driver="GTiff", compress="deflate", tiled=True, blockxsize=256,
                       blockysize=256, nodata=None)
        dest = tile_dir() / member
        part = dest.with_suffix(".part")
        with rasterio.open(part, "w", **profile) as sink:
            sink.write(saline.view(np.uint8), 1)
        part.replace(dest)
    return count


def build_vrt(tiles: list[str]) -> None:
    subprocess.run(["gdalbuildvrt", "-q", "-overwrite", str(saline_vrt())]
                   + [str(tile_dir() / tile) for tile in tiles], check=True)


def build_recipe() -> str:
    """Everything the tiles depend on besides the archives' bytes, which their md5s stand for."""
    return json.dumps({
        "saline_class": SALINE,
        "bridged_class": NOT_WETLAND,
        "archive_md5": {name: md5 for name, (_size, md5) in download_gwl.ARCHIVES.items()},
        "strips": {tile: {"north": north, "deepest_row": deepest_row}
                   for tile, (north, deepest_row) in STRIPS.items()},
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
    saline = []
    with ThreadPoolExecutor(args.workers) as pool:
        for done, (member, count) in enumerate(zip(names, pool.map(extract_tile, archives, names)), 1):
            if count:
                saline.append(member)
            if done % 100 == 0:
                print(f"  {done}/{len(tasks)}", flush=True)
    build_vrt(sorted(saline))
    recipe_path().write_text(build_recipe(), encoding="utf-8")
    print(f"{len(saline)} tiles hold saline -> {saline_vrt()}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
