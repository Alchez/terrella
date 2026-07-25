#!/usr/bin/env python3
"""Pack the XYZ tile pyramid into an MBTiles file — the bridge to `pmtiles convert`.

The vendored go-pmtiles CLI reads only MBTiles (its GDAL driver counterpart is
vector-only), and our pyramid is a plain z/x/y directory, so packaging is
dir -> MBTiles (this module) -> `tools/pmtiles convert` -> planet.pmtiles.
Blobs are MOVED, never re-encoded: the archive must serve byte-identical tiles
to the directory the cut produced.

The tile encoding is READ OFF THE DIRECTORY, never assumed. Until 2026-07-25 the
glob said `*.png` and the metadata said `"png"` — two independent spellings of
one fact, either of which could have been changed alone, and mislabelled metadata
would make every reader decode the archive as the wrong image type.

The one real trap is the row flip: MBTiles stores TMS rows (origin bottom-left)
while `gdal raster tile --convention=xyz` wrote XYZ rows (origin top-left) —
`tms_row` is the single home of that conversion, pinned by tests either way
(a silent flip error would serve a vertically mirrored planet).

Usage: python -m pipeline.tile.pack_pmtiles \
           [--tiles data/work/planet_tiles/tiles] [--out data/work/planet_tiles/planet.mbtiles]
"""
import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TILES = ROOT / "data/work/planet_tiles/tiles"
DEFAULT_OUT = ROOT / "data/work/planet_tiles/planet.mbtiles"
# The pyramid's geographic extent since the Antarctica fill (2026-07-22): the full
# Web-Mercator square. Metadata only — pmtiles carries it through to the archive header.
BOUNDS = "-180.0,-85.0511,180.0,85.0511"
INSERT_BATCH = 2048
# File suffix -> the MBTiles `format` string for it. Also the filter that decides what counts as a
# tile at all, so a stray sidecar in a leaf directory cannot be packed as image data.
TILE_SUFFIXES = {".png": "png", ".webp": "webp", ".jpg": "jpg"}


def tms_row(zoom: int, xyz_row: int) -> int:
    """XYZ row (origin top-left) -> TMS row (origin bottom-left) at this zoom."""
    return (1 << zoom) - 1 - xyz_row


def iter_tiles(tiles_dir: Path):
    """Yield (zoom, column, xyz_row, path) for every tile, zoom-ordered."""
    for zoom_dir in sorted(tiles_dir.iterdir(), key=lambda p: int(p.name)):
        zoom = int(zoom_dir.name)
        for column_dir in sorted(zoom_dir.iterdir(), key=lambda p: int(p.name)):
            column = int(column_dir.name)
            for tile_path in sorted(column_dir.iterdir()):
                if tile_path.suffix in TILE_SUFFIXES:
                    yield zoom, column, int(tile_path.stem), tile_path


def pack_directory(tiles_dir: Path, out_mbtiles: Path, name: str) -> int:
    """Pack tiles_dir into out_mbtiles (.tmp + atomic replace). Returns the tile count."""
    if not tiles_dir.is_dir():
        sys.exit(f"{tiles_dir} is not a directory — cut the pyramid first "
                 f"(python -m pipeline.tile.shade_planet --tiles)")
    tmp = out_mbtiles.with_name(out_mbtiles.name + ".tmp")
    tmp.unlink(missing_ok=True)
    count = 0
    zooms: list[int] = []
    suffixes: set[str] = set()
    started = time.monotonic()
    with sqlite3.connect(tmp) as db:
        # Build-only pragmas: the .tmp + replace convention already makes a crash safe
        # (a partial file never carries the final name), so durability buys nothing here.
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("PRAGMA synchronous=OFF")
        db.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        db.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, "
                   "tile_row INTEGER, tile_data BLOB)")
        batch: list[tuple[int, int, int, bytes]] = []
        for zoom, column, xyz_row, tile_path in iter_tiles(tiles_dir):
            if not zooms or zooms[-1] != zoom:
                zooms.append(zoom)
                print(f"  z{zoom} ...", flush=True)
            suffixes.add(tile_path.suffix)
            if len(suffixes) > 1:
                sys.exit(f"{tiles_dir} mixes tile encodings {sorted(suffixes)} — one PMTiles "
                         f"archive declares ONE tile type, so packing this would mislabel part "
                         f"of it (first seen at z{zoom} on {tile_path})")
            batch.append((zoom, column, tms_row(zoom, xyz_row), tile_path.read_bytes()))
            if len(batch) >= INSERT_BATCH:
                db.executemany("INSERT INTO tiles VALUES (?, ?, ?, ?)", batch)
                count += len(batch)
                batch.clear()
        db.executemany("INSERT INTO tiles VALUES (?, ?, ?, ?)", batch)
        count += len(batch)
        if not suffixes:
            sys.exit(f"{tiles_dir} holds no tiles — expected {'/'.join(sorted(TILE_SUFFIXES))} "
                     f"files under z/x/y.ext")
        db.execute("CREATE UNIQUE INDEX tile_index ON tiles "
                   "(zoom_level, tile_column, tile_row)")
        db.executemany("INSERT INTO metadata VALUES (?, ?)", [
            ("name", name),
            ("format", TILE_SUFFIXES[suffixes.pop()]),
            ("minzoom", str(min(zooms))),
            ("maxzoom", str(max(zooms))),
            ("bounds", BOUNDS),
            ("type", "baselayer"),
        ])
    os.replace(tmp, out_mbtiles)
    print(f"packed {count:,} tiles (z{min(zooms)}-z{max(zooms)}) -> {out_mbtiles} "
          f"({out_mbtiles.stat().st_size / 1e9:.2f} GB) in {time.monotonic() - started:.0f} s",
          flush=True)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--tiles", type=Path, default=DEFAULT_TILES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--name", default="terrella-relief")
    args = parser.parse_args()
    pack_directory(args.tiles, args.out, name=args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
