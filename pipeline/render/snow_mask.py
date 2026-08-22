"""Snow/ice mask stage for the hero shader.

Produces snowmask.png (0/255) on an existing render dir's grid from
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
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.warp import transform_bounds

from pipeline import paths
from pipeline.fetch import download_one
from pipeline.render import render_seam

BUCKET_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
DATA_DIR = paths.DATA / "raw/worldcover"
SNOW_CLASS = 70
TILE_DEG = 3
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-dir", type=Path, required=True,
                    help=f"existing render dir with {render_seam.HEIGHTFIELD}")
    args = ap.parse_args()
    render_dir = args.render_dir.resolve()

    out_png = render_dir / render_seam.SNOWMASK
    if out_png.exists():
        print(f"{out_png} exists — skipping", flush=True)
        render_seam.declare(render_dir, render_seam.SNOW, [render_seam.SNOWMASK])
        return

    # grid + CRS from the existing heightfield (render_prep.py pattern):
    # the mask must land pixel-for-pixel on the grid the render was made from
    hf = render_dir / render_seam.HEIGHTFIELD
    with rasterio.open(hf) as heightfield_dataset:
        dst_crs, transform = heightfield_dataset.crs, heightfield_dataset.transform
        width, height = heightfield_dataset.width, heightfield_dataset.height
        aea_bounds = heightfield_dataset.bounds
    xres = transform.a  # pyright: ignore[reportAttributeAccessIssue] — affine untyped

    # WorldCover tile window = the geographic footprint of the AEA raster. For
    # most countries transform_bounds of the AEA bounds is exactly right (and
    # slightly wider than the input frame, correctly covering neighbouring land
    # visible in the frame corners). But for a large, high-latitude or
    # antimeridian frame (Canada, NZ, Fiji) the AEA rectangle's corners fan past
    # the pole/dateline, so transform_bounds returns a wrapped/degenerate window
    # (west >= east) -> tiles_for_bounds selects zero tiles -> a false "every
    # tile absent" abort. Only in that case fall back to render_prep's
    # frame_lonlat (the country's true bbox, written before this stage). Normal
    # frames are unchanged, so their snow coverage is byte-identical.
    west, south, east, north = transform_bounds(dst_crs, "EPSG:4326",
                                                 *aea_bounds, densify_pts=64)
    if not (west < east and south < north):
        west, south, east, north = json.loads(
            (render_dir / "frame.json").read_text())["frame_lonlat"]
        print("  AEA footprint wraps the pole/dateline — using geographic "
              "frame_lonlat for WorldCover tile selection", flush=True)
    print(f"grid from {hf.name}: {width} x {height}, {xres:.0f} m/px; "
          f"lon/lat window {west:.2f} {south:.2f} {east:.2f} {north:.2f}",
          flush=True)

    names = tiles_for_bounds(west, south, east, north)
    print(f"{len(names)} candidate WorldCover tiles in the frame", flush=True)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    counts = {"ok": 0, "skipped": 0, "absent": 0}
    failures = []
    with cf.ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(download_one, f"{BUCKET_URL}/{name}", DATA_DIR / name,
                               timeout=120, absent_on_404=True): name for name in names}
        for index, fut in enumerate(cf.as_completed(futures), 1):
            status = fut.result()
            if status.startswith("failed"):
                failures.append(f"{futures[fut]}  {status}")
            else:
                counts[status] += 1
            if index % 10 == 0 or index == len(names):
                print(f"  [{index}/{len(names)}] ok={counts['ok']} "
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
                   + [str(path) for path in sorted(DATA_DIR.glob("*.tif"))],
                   check=True, capture_output=True)
    print(f"rebuilt {vrt.name} over {len(list(DATA_DIR.glob('*.tif')))} tiles",
          flush=True)

    # nearest-warp the classification onto the render grid, then threshold:
    # uncovered pixels read 0 (WorldCover nodata) -> never class 70 -> no snow.
    # Use gdalwarp (streaming, warp-memory-capped) rather than an in-process
    # WarpedVRT block read: on a continent-scale frame a single destination block
    # spans a huge lon/lat source window (russia covers 161 deg of longitude =
    # thousands of 10 m tiles), and materialising that window in one read OOMs
    # (~29 GB, killed russia+canada). gdalwarp chunks the warp to the -wm cap and
    # reads only the source tiles each chunk needs. -te/-ts reproduce the
    # heightfield grid exactly, so the mask still registers pixel-for-pixel.
    tmp_cls = out_png.with_name(out_png.name + ".cls.tif.tmp")
    left, bottom, right, top = aea_bounds
    subprocess.run(
        ["gdalwarp", "-overwrite", "-q", "-of", "GTiff",
         "-t_srs", dst_crs.to_wkt(),
         "-te", repr(left), repr(bottom), repr(right), repr(top),
         "-ts", str(width), str(height),
         "-r", "near", "-ot", "Byte",
         "-wm", "512", "-multi", "-wo", "NUM_THREADS=ALL_CPUS",
         "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
         str(vrt), str(tmp_cls)],
        check=True, capture_output=True)
    with rasterio.open(tmp_cls) as cls:
        mask = np.where(cls.read(1) == SNOW_CLASS, 255, 0).astype("uint8")
    tmp_cls.unlink(missing_ok=True)

    profile: dict[str, Any] = dict(driver="PNG", width=width, height=height,
                                   count=1, dtype="uint8", crs=dst_crs,
                                   transform=transform)
    # Crash-safety: write to .tmp and os.replace on success (with the PNG's
    # GDAL .aux.xml sidecar), so a kill mid-write never leaves a partial
    # snowmask that batch resume would trust as the prep-complete marker.
    tmp = out_png.with_name(out_png.name + ".tmp")
    with rasterio.open(tmp, "w", **profile) as out:
        out.write(mask, 1)
    aux = tmp.with_name(tmp.name + ".aux.xml")
    if aux.exists():
        os.replace(aux, out_png.with_name(out_png.name + ".aux.xml"))
    os.replace(tmp, out_png)

    render_seam.declare(render_dir, render_seam.SNOW, [render_seam.SNOWMASK])
    px = int((mask > 0).sum())
    km2 = px * (xres * xres) / 1e6
    print(f"wrote {out_png}", flush=True)
    print(f"snow/ice: {px:,} px = {km2:,.0f} km^2 "
          f"({100.0 * px / (width * height):.2f}% of frame)", flush=True)


if __name__ == "__main__":
    main()
