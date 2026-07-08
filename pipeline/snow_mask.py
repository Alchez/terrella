#!/usr/bin/env python3
"""Snow/ice mask stage for the hero shader (adopted 2026-07-08).

Produces snowmask_aea.png (0/255) on an existing render dir's grid from
ESA WorldCover 2021 v200 class 70 ("snow and ice") — a 10 m global
classification from a full-year Sentinel-1/2 composite, so class 70 means
*permanent* snow/glacier, not winter snowpack (the hero's editorial stance
everywhere: permanent water, perennial rivers, eternal snow). Same role as
the water-mask PNGs: a data-driven Mix switch for scene_build.py, warped
nearest onto the exact heightfield grid so it registers with the relief.
Runs after render_prep.py, once per country. Known gap: WorldCover stops
short of Antarctica (Sentinel-2 southern limit) — that hero is a special
case regardless.

Tiles are 3x3 degree COGs on a public S3 bucket, named by SW corner
(ESA_WorldCover_10m_2021_v200_N45E006_Map.tif), fetched with the
download_glo30.py conventions: stream to .part, size-check, atomic rename,
WORKERS at a time; finished files are skipped on re-runs. The bucket ships
land tiles only, so a 404 is a legitimate "ocean cell" (absent tile = no
snow there) — but if EVERY tile in the frame is absent the naming pattern
itself is broken, and the run aborts. Unlike GLO-30 the ETags are
multipart (no md5 oracle) — the pin is the versioned v200/2021 URL path.

License: CC-BY 4.0 — "(c) ESA WorldCover project 2021 / Contains modified
Copernicus Sentinel data (2021) processed by ESA WorldCover consortium".

Usage:
  snow_mask.py --render-dir data/work/switzerland/render_1s
"""

import argparse
import concurrent.futures as cf
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds
from rasterio.windows import Window

BUCKET_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
DATA_DIR = Path.home() / "projects/maps/data/raw/worldcover"
SNOW_CLASS = 70
TILE_DEG = 3
BLOCK = 4096
WORKERS = 6


def tile_name(lat: int, lon: int) -> str:
    """Bucket object name for the 3-degree tile with this SW corner."""
    ns = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"
    ew = f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
    return f"ESA_WorldCover_10m_2021_v200_{ns}{ew}_Map.tif"


def tiles_for_bounds(west, south, east, north) -> list[str]:
    """All 3-degree tiles overlapping a lon/lat window (SW corners on the
    3-degree grid; strict overlap, edge-touching tiles excluded)."""
    import math
    names = []
    for lat in range(math.floor(south / TILE_DEG) * TILE_DEG,
                     math.ceil(north / TILE_DEG) * TILE_DEG, TILE_DEG):
        for lon in range(math.floor(west / TILE_DEG) * TILE_DEG,
                         math.ceil(east / TILE_DEG) * TILE_DEG, TILE_DEG):
            names.append(tile_name(lat, lon))
    return names


def download_one(url: str, dest: Path) -> str:
    """download_glo30.py convention: .part + size check + atomic rename.
    404 -> 'absent': the bucket has no tile for all-ocean cells."""
    if dest.exists():
        return "skipped"
    part = dest.with_suffix(".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            expected = int(resp.headers.get("Content-Length", -1))
            with open(part, "wb") as out:
                shutil.copyfileobj(resp, out)
        actual = part.stat().st_size
        if expected != -1 and actual != expected:
            part.unlink()
            return f"failed: size mismatch ({actual} of {expected} bytes)"
        os.replace(part, dest)
        return "ok"
    except urllib.error.HTTPError as exc:
        part.unlink(missing_ok=True)
        if exc.code == 404:
            return "absent"
        return f"failed: {exc}"
    except Exception as exc:
        part.unlink(missing_ok=True)
        return f"failed: {exc}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-dir", type=Path, required=True,
                    help="existing render dir with heightfield_aea.tif")
    args = ap.parse_args()
    render_dir = args.render_dir.resolve()

    out_png = render_dir / "snowmask_aea.png"
    if out_png.exists():
        sys.exit(f"{out_png} already exists — delete it to redo")

    # grid + CRS from the existing heightfield (render_prep.py pattern):
    # the mask must land pixel-for-pixel on the grid the render was made from
    hf = render_dir / "heightfield_aea.tif"
    with rasterio.open(hf) as f:
        dst_crs, transform = f.crs, f.transform
        width, height = f.width, f.height
        frame = transform_bounds(f.crs, "EPSG:4326", *f.bounds, densify_pts=64)
    xres = transform.a  # pyright: ignore[reportAttributeAccessIssue] — affine untyped
    print(f"grid from {hf.name}: {width} x {height}, {xres:.0f} m/px; "
          f"lon/lat window {frame[0]:.2f} {frame[1]:.2f} "
          f"{frame[2]:.2f} {frame[3]:.2f}", flush=True)

    names = tiles_for_bounds(*frame)
    print(f"{len(names)} candidate WorldCover tiles in the frame", flush=True)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    counts = {"ok": 0, "skipped": 0, "absent": 0}
    failures = []
    with cf.ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(download_one, f"{BUCKET_URL}/{n}",
                               DATA_DIR / n): n for n in names}
        for i, fut in enumerate(cf.as_completed(futures), 1):
            status = fut.result()
            if status.startswith("failed"):
                failures.append(f"{futures[fut]}  {status}")
            else:
                counts[status] += 1
            if i % 10 == 0 or i == len(names):
                print(f"  [{i}/{len(names)}] ok={counts['ok']} "
                      f"skipped={counts['skipped']} "
                      f"absent(ocean)={counts['absent']} "
                      f"failed={len(failures)}", flush=True)
    if failures:
        sys.exit("downloads failed — rerun to retry (finished tiles skip):\n  "
                 + "\n  ".join(failures))
    if counts["ok"] + counts["skipped"] == 0:
        sys.exit("every tile in the frame is absent — the tile-name pattern "
                 "or bucket layout must have changed; stop and check")

    # VRT over every held tile (build_mosaics.sh pattern; instant XML index)
    vrt = DATA_DIR / "worldcover.vrt"
    subprocess.run(["gdalbuildvrt", "-overwrite", str(vrt)]
                   + [str(p) for p in sorted(DATA_DIR.glob("*.tif"))],
                   check=True, capture_output=True)
    print(f"rebuilt {vrt.name} over {len(list(DATA_DIR.glob('*.tif')))} tiles",
          flush=True)

    # nearest-warp the classification onto the render grid, then threshold:
    # uncovered pixels read 0 (WorldCover nodata) -> never class 70 -> no snow
    mask = np.zeros((height, width), dtype="uint8")
    with rasterio.open(vrt) as src, \
         WarpedVRT(src, crs=dst_crs, transform=transform, width=width,
                   height=height, resampling=Resampling.nearest) as wv:
        for row in range(0, height, BLOCK):
            for col in range(0, width, BLOCK):
                win = Window(col, row,  # pyright: ignore[reportCallIssue] — rasterio untyped, attrs init invisible
                             min(BLOCK, width - col), min(BLOCK, height - row))
                block = wv.read(1, window=win)
                mask[row:row + win.height, col:col + win.width] = \
                    (block == SNOW_CLASS).astype("uint8") * 255

    profile: dict[str, Any] = dict(driver="PNG", width=width, height=height,
                                   count=1, dtype="uint8", crs=dst_crs,
                                   transform=transform)
    with rasterio.open(out_png, "w", **profile) as out:
        out.write(mask, 1)

    px = int((mask > 0).sum())
    km2 = px * (xres * xres) / 1e6
    print(f"wrote {out_png}", flush=True)
    print(f"snow/ice: {px:,} px = {km2:,.0f} km^2 "
          f"({100.0 * px / (width * height):.2f}% of frame)", flush=True)


if __name__ == "__main__":
    main()
