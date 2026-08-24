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
tiler, and finally the seam declaration naming which of the three were actually built
(`pipeline/planet_seam.py` — written last, so its presence means this stage finished).
Idempotent: a cell whose heightfield exists is skipped; delete to redo. Re-running
`--build-vrts` alone is free — a VRT is replaced only when its XML changes.

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
from rasterio.windows import from_bounds

from pipeline import bodies, planet_seam
from pipeline.acquire.download_glo30 import (
    DATA_DIR,
    TILE_LIST,
    in_extent,
    parse_tile_name,
)
from pipeline.fuse import fuse_heightfield

RES_ARCSEC = 10
CELL_DEG = 10
TAG = fuse_heightfield.grid_tag(RES_ARCSEC)

#: The masks alone are fused a second time at this LATITUDE resolution, leaving longitude at
#: `RES_ARCSEC`, and the finer pair is what the planet's mask VRTs index.
#:
#: WHY THE MASKS AND NOT THE HEIGHTFIELD. The high-latitude coastline staircase is a latitude
#: artefact — a source column and a Web-Mercator pixel both shrink by cos(lat), so the longitude
#: ratio is 1.011 everywhere and only ROWS replicate, 5.55x at 79.5N. Measured on the shipped
#: `ocean_3857.tif`, adjacent rows are byte-identical 82.5% of the time there; refused at 1 arcsec
#: it falls to 0.3%. GLO-30 is 1 arcsec in LATITUDE at every band, so this is the source's own
#: resolution rather than an upsample.
#:
#: THE HEIGHTFIELD DELIBERATELY STAYS SQUARE. `prep_block` reads it and the mask independently — the
#: mask picks the material, the heightfield drives displacement — so they may carry different
#: detail, and the disagreement this creates was measured at 0.123% of pixels, symmetric, at a
#: median elevation of +0.92 m against controls of +399 (land) and -397 (sea). It lands on the
#: ramps' shared endpoint. Refining the heightfield too would be ~140 GB retained against these
#: masks' ~810 MB, and it is the z9/z10 re-fuse FUTURE parks as blocked on disk.
#:
#: `planet_seam._require_nested_grids` is what keeps the pair honest: 10 is a whole multiple of 1,
#: so the fine rows nest inside the square ones and no consumer reads a mask off its terrain.
MASK_LAT_ARCSEC = 1
MASK_TAG = fuse_heightfield.grid_tag(RES_ARCSEC, MASK_LAT_ARCSEC)

#: The Copernicus water-body classes the land guard reads, from `fuse_heightfield`'s own recipe:
#: 0 is land, 255 is the mosaic's nodata — what a VRT returns where it indexes no source.
WBM_LAND = 0
WBM_NODATA = fuse_heightfield.WBM_NODATA
WBM_VRT = fuse_heightfield.WBM_VRT
#: EARTH BY CONSTRUCTION, AND DELIBERATELY WITHOUT A `--body`. This driver fuses Copernicus tiles
#: against GEBCO over a Natural-Earth-indexed land list; every input it reads describes one planet,
#: so parameterising it would produce a flag whose only legal value is `earth`. A second body enters
#: the same seam through its own producer (`planet_seam`), which is what makes them interchangeable
#: downstream. Resolved through the registry rather than spelled out so the seam has ONE path home.
EARTH_PLANET_DIR = planet_seam.planet_dir(bodies.EARTH)
CHUNKS_DIR = EARTH_PLANET_DIR / "chunks"
DEFAULT_WORKERS = 12
GIB_PER_WORKER = 1.5  # fuse_heightfield peak RSS incl. GDAL cache, rounded up

#: The same figure for a `--masks` cell, and it is LARGER for a reason that is not "more pixels".
#: `BLOCK` bounds a window's ROWS at 8192, so a square cell (3600 x 3600) is one window covering the
#: whole thing while a 1"-latitude cell (3600 x 36000) is five windows of 8192 x 3600 — 2.3x the
#: window, not 10x the cell. MEASURED at 2.19 GiB peak RSS on a dense cell (0-10E 40-50N, 72.9%
#: land) and rounded up, the same way its neighbour was.
#:
#: 16 GiB / 2.5 is SIX workers, which is what a run under this project's cgroup cap must pass as
#: `--workers`: `mem_available_gib` reads the host's MemAvailable and cannot see the cap.
MASK_GIB_PER_WORKER = 2.5

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


def tiles_are_served(listed_tiles, wbm_vrt: Path) -> bool:
    """True if the mosaic actually serves at least one of this cell's listed GLO-30 tiles.

    THE FACT THAT GOES STALE, ASKED DIRECTLY. A VRT enumerates its sources at build time, so tiles
    downloaded afterwards are on disk and invisible to every read through it — and what the mosaic
    returns over them is NODATA, which `fuse_heightfield` classifies as ocean. Sampling the middle
    of a listed tile therefore separates "this tile is not in the mosaic" from every other reason a
    cell might fuse to open water.

    A WINDOW RATHER THAN A POINT, because one stray nodata pixel inside a served tile would
    otherwise read as an unserved mosaic. Copernicus ships a complete raster per tile, so any real
    class code inside the square answers the question.

    PER LISTED TILE AND NOT OVER THE CELL, which is the distinction `w010_n80` forces: that cell is
    90% nodata because it is open ocean beyond its two tiles, so a whole-cell test for "any real
    pixel" would read the emptiness around them and refuse a cell whose tiles are perfectly fine.
    """
    with rasterio.open(wbm_vrt) as wbm:
        nodata = wbm.nodata if wbm.nodata is not None else WBM_NODATA
        for tile in listed_tiles:
            south, west = parse_tile_name(tile)
            window = from_bounds(west + 0.4, south + 0.4, west + 0.6,
                                                  south + 0.6, wbm.transform)
            served = wbm.read(1, window=window, boundless=True, fill_value=nodata)
            if served.size and (served != nodata).any():
                return True
    return False


def _mosaic_holds_land(listed_tiles, wbm_vrt: Path) -> bool:
    """True if any listed tile carries WBM land, i.e. the fusion had something to lose.

    THE OTHER HALF OF THE DISCRIMINATOR, and without it "the tiles are served" becomes a blanket
    excuse: a mosaic serving real land while the fused mask reads 100% ocean means something between
    the two dropped it, which is a defect wearing the same output as the landless case.

    Reads the tile's whole degree square rather than `tiles_are_served`'s centre window, because a
    coastline can be anywhere in it and one land pixel is the entire question.
    """
    with rasterio.open(wbm_vrt) as wbm:
        for tile in listed_tiles:
            south, west = parse_tile_name(tile)
            window = from_bounds(west, south, west + 1, south + 1, wbm.transform)
            served = wbm.read(1, window=window, boundless=True, fill_value=WBM_NODATA)
            if served.size and (served == WBM_LAND).any():
                return True
    return False


def enforce_land_guard(outdir: Path, tag: str = TAG, listed_tiles=(),
                       wbm_vrt: Path = WBM_VRT) -> bool:
    """True if this cell's all-ocean result is explicable; on an unexplained one, fail the cell.

    Closes the stale-mosaic route around the coverage oracle (found when the first Antarctic sweep
    fused the whole continent as ocean): every listed tile can be on disk while dem_mosaic.vrt /
    wbm_mosaic.vrt predate the download, so the tiles are invisible to fusion and the in-window gap
    check stays silent because its land definition reads the same stale mosaic. On failure, write
    error.log and delete the outputs so the resume contract retries the cell instead of trusting it.

    "TILES ARE LISTED, SO THERE IS LAND" WAS THE ORIGINAL TEST AND IT IS FALSE. GLO-30 publishes
    tiles over open water — they carry the water mask and 0 m elevation — so a cell can list tiles,
    have every one present and indexed, and hold no land at all. Two of Earth's 648 do: `w180_s70`
    and `w010_n80`. Neither had ever reached this function, because both chunks predate the guard
    and `fuse_cell` skips a cell whose output exists.

    SO THE ALL-OCEAN RESULT IS AMBIGUOUS AND THE INPUT IS NOT. A stale mosaic and a genuinely
    landless cell produce identical output; they differ in whether the cell's listed tiles are
    reachable through the mosaic at all, which is what `tiles_are_served` asks. Indexed-ness is not
    a blanket excuse either: a served tile that HOLDS land still fails, because then something
    between the mosaic and the mask dropped it.
    """
    with rasterio.open(outdir / f"oceanmask_{tag}.tif") as mask:
        for _block_index, window in mask.block_windows(1):
            if not (mask.read(1, window=window) == 1).all():
                return True
    if listed_tiles and tiles_are_served(listed_tiles, wbm_vrt) and not _mosaic_holds_land(
            listed_tiles, wbm_vrt):
        print(f"{outdir.name}: all ocean, and its listed tiles are served and hold no land — "
              f"genuinely landless, not a stale mosaic", flush=True)
        return True
    (outdir / "error.log").write_text(
        "LAND GUARD: tileList lists land tiles for this cell, but the fused ocean mask is "
        "100% ocean. The DEM/WBM mosaics are almost certainly stale (a VRT enumerates its "
        "sources at build time) — run pipeline/fuse/build_mosaics.sh, then re-run the "
        "sweep. Outputs were deleted so this cell retries.\n")
    for raster in planet_seam.PLANET_RASTERS:
        (outdir / f"{raster}_{tag}.tif").unlink(missing_ok=True)
    return False


def fuse_cell(name: str, bounds, listed_tiles, masks_only: bool = False) -> tuple[str, str]:
    """Fuse one cell in an isolated subprocess. Returns (name, status).

    TAKES THE TILE NAMES AND NOT A BOOLEAN, because the land guard needs them: whether an all-ocean
    result is a stale mosaic or a genuinely landless cell is decided by reading those tiles through
    the mosaic. A `bool(listed)` here would answer "should this be guarded" and throw away the only
    thing that can answer "and did it legitimately come back empty".

    THE SKIP PREDICATE IS THIS RUN'S OWN OUTPUT. A masks-only run emits no heightfield, so it must
    resume on its own ocean mask; keying both modes off the heightfield would make the fine pass
    re-run every already-finished cell, and keying the square pass off the mask would let a
    half-written cell read as complete.
    """
    outdir = CHUNKS_DIR / name
    tag = MASK_TAG if masks_only else TAG
    sentinel = f"oceanmask_{tag}.tif" if masks_only else f"heightfield_{tag}.tif"
    if (outdir / sentinel).exists():
        return name, "skipped"
    cmd = [sys.executable, "-m", "pipeline.fuse.fuse_heightfield",
           "--bounds", *map(str, bounds), "--res-arcsec", str(RES_ARCSEC),
           "--outdir", str(outdir), "--coverage-warn"]
    if masks_only:
        cmd += ["--lat-res-arcsec", str(MASK_LAT_ARCSEC), "--masks-only"]
    result = subprocess.run(cmd, env={**os.environ, **FUSE_ENV},
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "error.log").write_text(result.stdout + "\n" + result.stderr)
        return name, "failed"
    if listed_tiles and not enforce_land_guard(outdir, tag, listed_tiles):
        return name, "failed"
    if "WARNING: COVERAGE GAP" in result.stdout:
        return name, "warned"
    return name, "ok"


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def build_vrts(mask_tag: str = TAG):
    """Index the per-cell outputs into planet-wide VRTs, then declare what was built.

    `mask_tag` says which grid the two MASKS were fused on, the heightfield always being square.
    `planet_seam.declare` re-derives the grids from the VRTs and refuses a pair that does not nest
    inside the heightfield's, so a wrong tag here fails loudly rather than repointing the planet.

    THE DECLARATION IS WRITTEN LAST, and it is the reason this function ends where it does. Its
    presence is this stage's completion stamp, and its contents are what every consumer reads to
    learn whether Earth has an ocean mask at all — a question that cannot be answered by looking for
    the file, because a missing raster and an unfinished fusion are the same absence. See
    `pipeline/planet_seam.py`.

    The `continue` below is why the declaration carries content rather than just existing: this
    function has always been able to emit fewer than three rasters, and until now nothing recorded
    which.
    """
    built = []
    for raster in planet_seam.PLANET_RASTERS:
        # PASSED IN RATHER THAN PROBED FOR. Choosing the fine tag because fine chunks happen to be
        # on disk would make a half-finished mask pass silently repoint the planet at it, and would
        # make deleting one chunk a silent revert to the coarse grid. The caller ran the pass, so
        # the caller is the one that can say which grid it produced.
        tag = mask_tag if raster.endswith("mask") else TAG
        sources = sorted(CHUNKS_DIR.glob(f"*/{raster}_{tag}.tif"))
        if not sources:
            print(f"no {raster} chunks yet — skipping {raster} VRT", flush=True)
            continue
        vrt = planet_seam.vrt_path(bodies.EARTH, raster)
        changed = planet_seam.write_vrt_if_changed(vrt, lambda target, sources=sources: _run(
            ["gdalbuildvrt", "-overwrite", str(target), *[str(path) for path in sources]]))
        built.append(raster)
        print(f"{vrt.name}: {len(sources)} chunks{'' if changed else ' (unchanged)'}", flush=True)
    print(f"declared {planet_seam.declare(bodies.EARTH, built)}", flush=True)


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
    ap.add_argument("--masks", action="store_true",
                    help=f"fuse the two MASKS only, at {MASK_LAT_ARCSEC}\" latitude by "
                         f"{RES_ARCSEC}\" longitude, writing *_{MASK_TAG}.tif beside the square "
                         f"chunks. Takes the high-latitude coastline staircase out of the "
                         f"delivered pixels; the heightfield is untouched. Combine with "
                         f"--build-vrts to index the fine masks instead of the square ones.")
    args = ap.parse_args()

    if args.build_vrts:
        build_vrts(MASK_TAG if args.masks else TAG)
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

    pending = [(name, bounds, listed) for name, bounds, listed, _missing in selected]

    # A masks-only cell is TALLER, so its windows are bigger: `BLOCK` bounds rows, and at 1" the
    # cell is 36000 of them against 3600, so the window goes from the whole cell to 8192 x 3600.
    # Measured peak RSS is the constant's authority either way, and the fine budget is the measured
    # one rather than the square one scaled by a guess.
    per_worker = MASK_GIB_PER_WORKER if args.masks else GIB_PER_WORKER
    need = args.workers * per_worker
    avail = mem_available_gib()
    if need > avail:
        sys.exit(f"{args.workers} workers need ~{need:.0f} GiB but only {avail:.0f} GiB "
                 f"available — lower --workers to {int(avail / per_worker)}")

    print(f"fusing {len(pending)} cells{' (masks only, ' + MASK_TAG + ')' if args.masks else ''}, "
          f"{args.workers}-wide (~{need:.0f} GiB of {avail:.0f} available)", flush=True)
    tally: dict[str, int] = {"ok": 0, "warned": 0, "skipped": 0, "failed": 0}
    flagged: list[str] = []
    with cf.ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(fuse_cell, name, bounds, listed, args.masks): name
                   for name, bounds, listed in pending}
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
        build_vrts(MASK_TAG if args.masks else TAG)
    return 1 if tally["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
