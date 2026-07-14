#!/usr/bin/env python3
"""Shade the whole (non-Antarctic) planet as RAM-safe blocks, then mosaic (+ optionally tile).

shade.py shades one bounded cell-group in a single whole-region-in-RAM pass; the planet is far
too big for that. This groups the fused cells into horizontal strips (one latitude band each)
under a per-block pixel budget and shades each strip via shade.py with:
  * a SINGLE GLOBAL z-factor (--zfactor) so the hillshade is seamless across strips, and
  * SVF off (--knob svf_strength=0) because SVF's per-block min/max normalisation would seam.
Strips are pixel-aligned to the WebMercatorQuad grid (shade.py's -tap), so the VRT mosaic and the
tiles are seamless. Resumable and fault-tolerant: a strip whose region_rgb.tif already exists is
skipped, and a strip that errors is logged and skipped (re-run to retry — completed strips skip).

    python -m pipeline.tile.tile_planet --out data/work/planet_tiles           # shade + mosaic
    python -m pipeline.tile.tile_planet --out data/work/planet_tiles --tiles    # + cut z0-8 tiles
    python -m pipeline.tile.tile_planet --limit 4                               # first 4 strips (test)
    python -m pipeline.tile.tile_planet --cells e000_n40 e010_n40               # one explicit strip
"""

import argparse
import math
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.home() / "projects/maps"
CHUNKS = ROOT / "data/work/planet/chunks"
Z8_RES = 305.7483          # metres/pixel of a 512px WebMercatorQuad tile at zoom 8
EARTH_R = 6378137.0
LAT_CLAMP = 85.05          # Web-Mercator latitude limit
GLOBAL_ZFACTOR = 20.0      # single global hillshade z (~lat 41); per-latitude banding is a refinement
PIXEL_BUDGET = 80_000_000  # per-block composite pixels — ~South-Asia-sized, safe for the float64 composite


def merc_y(lat):
    lat = max(-LAT_CLAMP, min(LAT_CLAMP, lat))
    return EARTH_R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def cell_lonlat(name):
    lon_str, lat_str = name.split("_")
    lon = int(lon_str[1:]) * (1 if lon_str[0] == "e" else -1)
    lat = int(lat_str[1:]) * (1 if lat_str[0] == "n" else -1)
    return lon, lat


def build_blocks():
    """Group cells into horizontal strips (one 10-deg latitude band each) under the pixel budget."""
    cells = sorted(path.name for path in CHUNKS.iterdir() if path.is_dir())
    by_lat = {}
    for cell in cells:
        _, lat = cell_lonlat(cell)
        by_lat.setdefault(lat, []).append(cell)
    cell_w_px = (10.0 * 2 * math.pi * EARTH_R / 360.0) / Z8_RES  # 10-deg lon width in px (constant)
    blocks = []
    for lat in sorted(by_lat):
        band_h_px = (merc_y(lat + 10) - merc_y(lat)) / Z8_RES
        per_block = max(1, int(PIXEL_BUDGET / (cell_w_px * band_h_px)))
        row = sorted(by_lat[lat], key=lambda c: cell_lonlat(c)[0])
        for start in range(0, len(row), per_block):
            blocks.append(row[start:start + per_block])
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "data/work/planet_tiles")
    ap.add_argument("--limit", type=int, default=None, help="only the first N strips (for testing)")
    ap.add_argument("--cells", nargs="+", default=None, help="one explicit strip (for testing)")
    ap.add_argument("--tiles", action="store_true", help="also cut z0-8 tiles from the mosaic")
    args = ap.parse_args()
    blocks_dir = args.out / "blocks"
    blocks_dir.mkdir(parents=True, exist_ok=True)

    blocks = [args.cells] if args.cells else build_blocks()
    if args.limit:
        blocks = blocks[:args.limit]
    total_cells = sum(len(b) for b in blocks)
    print(f"{len(blocks)} strips, {total_cells} cells, global z-factor {GLOBAL_ZFACTOR}", flush=True)

    region_rgbs, failures = [], []
    for index, cells in enumerate(blocks):
        out = blocks_dir / f"block_{index:03d}"
        rgb = out / "region_rgb.tif"
        if rgb.exists():
            print(f"[{index + 1}/{len(blocks)}] skip {out.name} ({len(cells)} cells)", flush=True)
            region_rgbs.append(rgb)
            continue
        print(f"[{index + 1}/{len(blocks)}] shading {out.name}: {len(cells)} cells", flush=True)
        try:
            subprocess.run(
                ["python", "-m", "pipeline.tile.shade", "--cells", *cells, "--out", str(out),
                 "--zfactor", str(GLOBAL_ZFACTOR), "--knob", "svf_strength=0"],
                check=True, cwd=ROOT)
            for item in out.iterdir():  # keep only region_rgb.tif; drop shade intermediates
                if item.name != "region_rgb.tif":
                    shutil.rmtree(item) if item.is_dir() else item.unlink()
            region_rgbs.append(rgb)
        except subprocess.CalledProcessError as exc:
            print(f"  !! FAILED {out.name}: {exc}", flush=True)
            failures.append((out.name, cells))

    if failures:
        print(f"\n{len(failures)} strips FAILED (re-run to retry):", flush=True)
        for name, cells in failures:
            print(f"  {name}: {' '.join(cells)}", flush=True)

    if not region_rgbs:
        sys.exit("no strips produced — nothing to mosaic")
    mosaic = args.out / "planet_rgb.vrt"
    subprocess.run(["gdalbuildvrt", "-overwrite", "-addalpha", str(mosaic), *map(str, region_rgbs)],
                   check=True, capture_output=True)
    print(f"\nmosaic ({len(region_rgbs)} strips) -> {mosaic}", flush=True)

    if args.tiles:
        # materialise the VRT mosaic to a tiled GTiff + overviews first — tiling a 194-source
        # VRT re-reads every block for each low-zoom tile and is far too slow; one GTiff is fast.
        planet_tif = args.out / "planet_rgb.tif"
        if not planet_tif.exists():
            print("materialising mosaic -> GTiff + overviews ...", flush=True)
            subprocess.run(["gdal_translate", "-q", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
                            "-co", "BIGTIFF=YES", "-co", "NUM_THREADS=ALL_CPUS",
                            str(mosaic), str(planet_tif)], check=True)
            subprocess.run(["gdaladdo", "-r", "average", str(planet_tif),
                            "2", "4", "8", "16", "32", "64", "128", "256"], check=True)
        tiles = args.out / "tiles"
        print(f"cutting z0-8 512px tiles -> {tiles} ...", flush=True)
        subprocess.run(["gdal", "raster", "tile", "--min-zoom=0", "--max-zoom=8",
                        "--tile-size=512", "--resampling=cubic", "--convention=xyz",
                        "--skip-blank", "--resume", str(planet_tif), str(tiles)], check=True)
        print(f"tiles -> {tiles}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
