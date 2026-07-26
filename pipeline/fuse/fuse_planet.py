#!/usr/bin/env python3
"""Fuse the whole planet into a 10-arcsecond heightfield, one 10-degree cell at a time.

Phase 2, step 1: the seamless global land+bathymetry heightfield the tile pyramid is
shaded and cut from. The tile-pyramid ceiling is z8 (~306 m/px); a 10-arcsecond EPSG:4326
grid matches z8 at every latitude (a constant-degree grid and WebMercator both scale
ground resolution by cos(lat), so 10" feeds z8 1:1 with no polar oversampling), so we fuse
the analysis-ready master in plain lon/lat and leave the WebMercator reprojection (and its
latitude-varying hillshade z-factor) to the later shading stage.

Why chunk, given fuse_heightfield is already windowed and memory-flat? Not for memory —
for three things a single whole-planet invocation can't give: parallelism (one serial
window loop uses 1 of 16 cores), resumable-at-cell-granularity (a crash re-runs only the
unfinished cells, not the planet), and per-cell coverage correctness (below). Cells are
10x10 degree, whole-degree aligned so their edges fall on exact output-pixel boundaries
(1 deg = 360 px at 10") — adjacent cells then share bit-identical seam columns, because the
fusion mask reads only co-located pixels (no neighbour lookup). 36 x 18 = 648 cells.

THE COVERAGE ORACLE (the reason this file exists rather than one fuse_heightfield call):
at fusion time an un-downloaded 1x1 land cell (DEM and WBM both absent -> dem=-9999,
wbm=255) is PIXEL-IDENTICAL to genuine open ocean, and fuse_heightfield routes it to
min(gebco,-1) -- silently flooding real land as sea, uncounted by its in-window gap check.
The only thing that can tell "land we haven't downloaded" from "sea" is tileList.txt, the
bucket's authoritative land index. So before fusing, we assert every listed tile that
intersects a land cell is on disk, and fail loudly (naming the cell + missing keys) if not.
--allow-incomplete skips that gate for driver validation on partial coverage.

Output: per-cell tiled GTiffs with overviews under data/work/planet/chunks/<cell>/, then
`gdalbuildvrt` three planet VRTs over them (heightfield / oceanmask / watermask) for the
tiler. Idempotent: a cell whose heightfield exists is skipped; delete to redo.

Memory budget: fuse_heightfield holds ~1-1.5 GB per process; --workers W costs ~W*1.5 GB
against MemAvailable. Default 12 (~14 GB) suits this 16-core / 18-GiB-free box -- CPU-bound
at 10-degree cells, not RAM-bound.

Usage:
  python -m pipeline.fuse.fuse_planet --dry-run                 # classify, no fusion
  python -m pipeline.fuse.fuse_planet --cells w010_n40 e120_s10 --allow-incomplete
  python -m pipeline.fuse.fuse_planet                           # full sweep (gated on coverage)
"""

import argparse
import concurrent.futures as cf
import os
import subprocess
import sys
from pathlib import Path

import rasterio

from pipeline.acquire.download_glo30 import DATA_DIR, TILE_LIST, in_extent, parse_tile_name

RES_ARCSEC = 10
CELL_DEG = 10
TAG = "10s"  # must equal fuse_heightfield's f"{RES_ARCSEC:g}s"
PLANET_DIR = DATA_DIR.parent.parent / "work/planet"  # data/work/planet
CHUNKS_DIR = PLANET_DIR / "chunks"
DEFAULT_WORKERS = 12
GIB_PER_WORKER = 1.5  # fuse_heightfield peak RSS incl. GDAL cache, rounded up

FUSE_ENV = {
    "GDAL_CACHEMAX": "384",          # MB, per process -> multiplies by --workers
    "GDAL_NUM_THREADS": "1",         # parallelism is across cells, not within a warp
    "GDAL_MAX_DATASET_POOL_SIZE": "150",
}


def cell_bounds(west: int, south: int) -> tuple[int, int, int, int]:
    """(W, S, E, N) of the CELL_DEG cell with this SW corner."""
    return (west, south, west + CELL_DEG, south + CELL_DEG)


def cell_name(west: int, south: int) -> str:
    """Filesystem-safe SW-corner label, e.g. (-10, 40) -> 'w010_n40', (120, -10) -> 'e120_s10'."""
    lon = f"{'e' if west >= 0 else 'w'}{abs(west):03d}"
    lat = f"{'n' if south >= 0 else 's'}{abs(south):02d}"
    return f"{lon}_{lat}"


def enumerate_cells() -> list[tuple[int, int]]:
    """SW corners of every CELL_DEG cell tiling the globe (lon -180..180, lat -90..90)."""
    return [(west, south)
            for south in range(-90, 90, CELL_DEG)
            for west in range(-180, 180, CELL_DEG)]


def load_tile_index() -> list[tuple[str, int, int]]:
    """(name, lat, lon) for every land tile in the bucket index."""
    if not TILE_LIST.exists():
        sys.exit(f"{TILE_LIST} not found — run download_glo30 first to fetch the tile index")
    names = TILE_LIST.read_text().split()
    return [(name, *parse_tile_name(name)) for name in names]


def classify_cell(corner: tuple[int, int], tile_index):
    """Return (name, bounds, listed_tiles, missing_tiles) for one cell.

    listed = index tiles intersecting the cell (land iff non-empty); missing = those
    listed tiles whose DEM .tif is not on disk (the coverage gap the sweep must not cross).
    """
    west, south = corner
    bounds = cell_bounds(west, south)
    listed = [name for (name, lat, lon) in tile_index if in_extent(lat, lon, bounds)]
    missing = [name for name in listed
               if not (DATA_DIR / "dem" / f"{name}.tif").exists()]
    return cell_name(west, south), bounds, listed, missing


def mem_available_gib() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / (1024 * 1024)
    return 0.0


def enforce_land_guard(outdir: Path) -> bool:
    """True if the fused ocean mask holds at least one land pixel; on pure ocean, fail the cell.

    Closes the stale-mosaic route around the coverage oracle (found when the
    first Antarctic sweep fused the whole continent as ocean): every listed tile can be on
    disk while dem_mosaic.vrt / wbm_mosaic.vrt predate the download — a VRT enumerates its
    sources at build time, so the tiles are invisible to fusion, and the in-window gap
    check stays silent because its land definition reads the same stale mosaic. The one
    input that cannot go stale is the OUTPUT: a cell tileList calls land must fuse to at
    least one land pixel. On zero, write error.log and delete the outputs so the resume
    contract retries the cell instead of trusting it.
    """
    with rasterio.open(outdir / f"oceanmask_{TAG}.tif") as mask:
        for _block_index, window in mask.block_windows(1):
            if not (mask.read(1, window=window) == 1).all():
                return True
    (outdir / "error.log").write_text(
        "LAND GUARD: tileList lists land tiles for this cell, but the fused ocean mask is "
        "100% ocean. The DEM/WBM mosaics are almost certainly stale (a VRT enumerates its "
        "sources at build time) — run pipeline/fuse/build_mosaics.sh, then re-run the "
        "sweep. Outputs were deleted so this cell retries.\n")
    for layer in ("heightfield", "oceanmask", "watermask"):
        (outdir / f"{layer}_{TAG}.tif").unlink(missing_ok=True)
    return False


def fuse_cell(name: str, bounds, expect_land: bool) -> tuple[str, str]:
    """Fuse one cell in an isolated subprocess. Returns (name, status)."""
    outdir = CHUNKS_DIR / name
    if (outdir / f"heightfield_{TAG}.tif").exists():
        return name, "skipped"
    cmd = [sys.executable, "-m", "pipeline.fuse.fuse_heightfield",
           "--bounds", *map(str, bounds), "--res-arcsec", str(RES_ARCSEC),
           "--outdir", str(outdir), "--coverage-warn"]
    result = subprocess.run(cmd, env={**os.environ, **FUSE_ENV},
                            capture_output=True, text=True)
    if result.returncode != 0:
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "error.log").write_text(result.stdout + "\n" + result.stderr)
        return name, "failed"
    if expect_land and not enforce_land_guard(outdir):
        return name, "failed"
    if "WARNING: COVERAGE GAP" in result.stdout:
        return name, "warned"
    return name, "ok"


def build_vrts():
    """Index the per-cell outputs into three planet-wide VRTs for the tiler."""
    for layer in ("heightfield", "oceanmask", "watermask"):
        sources = sorted(CHUNKS_DIR.glob(f"*/{layer}_{TAG}.tif"))
        if not sources:
            print(f"no {layer} chunks yet — skipping {layer} VRT", flush=True)
            continue
        vrt = PLANET_DIR / f"planet_{layer}.vrt"
        subprocess.run(["gdalbuildvrt", "-overwrite", str(vrt),
                        *[str(path) for path in sources]], check=True)
        print(f"{vrt.name}: {len(sources)} chunks", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                    help=f"concurrent fuse subprocesses (default {DEFAULT_WORKERS}; "
                         f"budget ~{GIB_PER_WORKER} GiB each)")
    ap.add_argument("--dry-run", action="store_true",
                    help="classify cells and report coverage, run no fusion")
    ap.add_argument("--cells", nargs="+", metavar="NAME",
                    help="run only these named cells (e.g. w010_n40) — for validation")
    ap.add_argument("--limit", type=int,
                    help="run at most N pending cells (land cells first)")
    ap.add_argument("--skip-south", type=float, metavar="DEG",
                    help="skip cells whose southern edge is below DEG (e.g. -60 defers "
                         "Antarctica; its ~7,000 tiles are 92%% of the download and PLAN "
                         "handles it as a special case). Ignored when --cells is given.")
    ap.add_argument("--emit-missing", action="store_true",
                    help="print the missing tile names for the selected cells (one per "
                         "line) and exit — the exact download list for `download_glo30 "
                         "--tiles`. No fusion, no gate.")
    ap.add_argument("--allow-incomplete", action="store_true",
                    help="skip the tileList completeness gate (validate on partial coverage)")
    ap.add_argument("--build-vrts", action="store_true",
                    help="(re)build the planet VRTs over existing chunks and exit")
    args = ap.parse_args()

    if args.build_vrts:
        build_vrts()
        return 0

    tile_index = load_tile_index()
    classified = [classify_cell(corner, tile_index) for corner in enumerate_cells()]
    land = [item for item in classified if item[2]]
    ocean = [item for item in classified if not item[2]]
    incomplete = [item for item in land if item[3]]

    print(f"{len(classified)} cells: {len(land)} land, {len(ocean)} ocean-only; "
          f"{len(incomplete)} land cells missing tiles", flush=True, file=sys.stderr)

    if args.dry_run:
        for name, _bounds, listed, missing in sorted(incomplete):
            print(f"  {name}: {len(missing)}/{len(listed)} tiles missing "
                  f"(e.g. {missing[0]})", flush=True)
        return 0

    # Select first (land cells first — the interesting, slower work), then gate on the
    # coverage of exactly what we're about to run, so validating one complete cell needs
    # no --allow-incomplete and a full sweep still gates on the whole planet.
    selected = land + ocean
    if args.skip_south is not None and not args.cells:
        selected = [item for item in selected if item[1][1] >= args.skip_south]
    if args.cells:
        wanted = set(args.cells)
        selected = [item for item in selected if item[0] in wanted]
        unknown = wanted - {item[0] for item in selected}
        if unknown:
            sys.exit(f"unknown cell name(s): {', '.join(sorted(unknown))}")
    if args.limit:
        selected = selected[:args.limit]

    if args.emit_missing:
        for name in sorted({tile for item in selected for tile in item[3]}):
            print(name)
        return 0

    selected_incomplete = [item for item in selected if item[3]]
    if selected_incomplete and not args.allow_incomplete:
        print("COVERAGE INCOMPLETE — refusing to fuse (un-downloaded land would flood as "
              "ocean). Download the missing tiles, then rerun. Offending cells:", flush=True)
        for name, _bounds, listed, missing in sorted(selected_incomplete):
            print(f"  {name}: {len(missing)}/{len(listed)} missing (e.g. {missing[0]})",
                  flush=True)
        return 1
    if selected_incomplete:
        print(f"--allow-incomplete: proceeding with {len(selected_incomplete)} partial land "
              f"cells (their un-downloaded interiors will render as ocean)", flush=True)

    pending = [(name, bounds, bool(listed)) for name, bounds, listed, _missing in selected]

    need = args.workers * GIB_PER_WORKER
    avail = mem_available_gib()
    if need > avail:
        sys.exit(f"{args.workers} workers need ~{need:.0f} GiB but only {avail:.0f} GiB "
                 f"available — lower --workers to {int(avail / GIB_PER_WORKER)}")

    print(f"fusing {len(pending)} cells, {args.workers}-wide "
          f"(~{need:.0f} GiB of {avail:.0f} available)", flush=True)
    tally: dict[str, int] = {"ok": 0, "warned": 0, "skipped": 0, "failed": 0}
    flagged: list[str] = []
    with cf.ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(fuse_cell, name, bounds, expect_land): name
                   for name, bounds, expect_land in pending}
        for done, fut in enumerate(cf.as_completed(futures), 1):
            name, status = fut.result()
            tally[status] += 1
            if status in ("failed", "warned"):
                flagged.append(f"{name} [{status}]")
            print(f"[{done}/{len(pending)}] {name} {status}", flush=True)

    print(f"complete: {tally}", flush=True)
    if flagged:
        print("flagged cells (inspect chunks/<cell>/error.log or the coverage warning):",
              flush=True)
        for entry in sorted(flagged):
            print(f"  {entry}", flush=True)
    if tally["failed"] == 0:
        build_vrts()
    return 1 if tally["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
