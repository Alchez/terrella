#!/usr/bin/env python3
"""Per-country subject-spotlight overlay for the hero gallery (toggle asset).

Parallel to gen_borders.py: emits a standalone transparent overlay that, laid
over the plain hero, dims + desaturates everything OUTSIDE the subject country
and strokes its boundary — so a viewer can read the country's extent at a glance
without turning on the all-borders layer. Toggled on the web (body.spotlight-on),
never baked into the hero.

The subject region is DEM-land MINUS the neighbours' Natural Earth polygons:
  - its seaward edge is therefore the *rendered* 30 m coastline (pixel-exact
    against the hero), not NE's 1:10 m generalisation (which wanders ~250 m —
    see HISTORY § alignment oracle);
  - its landward edge is the NE political border (the only source there).
One rule, correct on both boundary kinds.

Overlay semantics (straight-alpha composite over the hero):
  outside subject -> opaque dimmed+desaturated hero pixels;
  inside subject  -> fully transparent (the hero shows through);
  boundary        -> white line over a dark halo, so it reads on land and sea.
Only where the hero has content (alpha>0): the transparent frame margin is left
untouched.

Each country is fully independent (own files in and out, no shared state), so the
whole-batch run can fan out across processes with --jobs. The work is pixel-bound and
scipy/gdal are single-threaded per call, so N workers use N idle cores near-linearly —
but the ceiling is memory, and it sits lower than the arithmetic suggests: the largest
countries hold several float arrays over a native (~42 MP) grid and peak near 8 GB each,
so the full 203-set OOMs at --jobs>1 under the standing 12 G cgroup cap. Serial is the
default for that reason; budget ~8 GB per job before raising it.

Usage:
  gen_spotlight.py --only saintlucia            # one (or a comma list)
  gen_spotlight.py                              # every hero, serial
  gen_spotlight.py --jobs 4                     # only with real headroom (~8 GB per job)
  gen_spotlight.py --dim 0.68 --desat 0.35      # retune the outside treatment
"""
import argparse
import multiprocessing
import os
import re
import subprocess
import sys
import tempfile
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cairo
import numpy as np
import pyproj
import rasterio
import shapefile
from rasterio.enums import Resampling
from rasterio.errors import NotGeoreferencedWarning
from rasterio.transform import from_origin
from rasterio.warp import reproject
from scipy.ndimage import binary_fill_holes, distance_transform_edt, gaussian_filter, label

from pipeline.compose.overlay_borders import render_mapping

warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)  # hero PNGs

ROOT = Path(__file__).resolve().parents[2]
HEROES = ROOT / "blender/renders/heroes"
VARIANTS = ROOT / "blender/renders/variants"
NE_COUNTRIES = (ROOT / "data/raw/naturalearth/ne_10m_admin_0_countries"
                / "ne_10m_admin_0_countries.shp")
WORK = ROOT / "data/work"
PLANE_WIDTH_UNITS = 2.0
# Must stay the same ladder as hero_variants.TARGETS: the gallery layers this overlay directly on
# the hero and gives both the same `sizes`, so a rung the overlay lacks makes the browser pull a
# larger file for the top layer than for the one underneath it.
TARGETS = (640, 960, 1280, 1920, 3840)   # plus each hero's native long edge
# Unchanged at q88 by the quality pass, and provably so: build_overlay sets
# overlay_alpha to 0 across the subject, so these pixels only ever cover the dimmed surroundings.
WEBP_QUALITY = 88
DIM_DEFAULT = 0.68       # outside brightness (Rohan's "subtle")
DESAT_DEFAULT = 0.35     # outside desaturation
OUTLINE_DIV_DEFAULT = 6000.0   # boundary hairline half-width = long_edge / this (~1.3px @7680)
HALO_ALPHA_DEFAULT = 0.30      # faint dark keyline under the white line, for light-coast legibility
WEBP_ALPHA_THRESHOLD = 0.5


def slugify(admin: str) -> str:
    return re.sub(r"[^a-z0-9]", "", admin.lower())


def dim_desaturate(rgb: np.ndarray, dim: float, desat: float) -> np.ndarray:
    """Blend toward luminance by `desat`, then scale brightness by `dim`. Pure."""
    luma = (rgb * [0.2126, 0.7152, 0.0722]).sum(axis=-1, keepdims=True)
    return (rgb * (1.0 - desat) + luma * desat) * dim


def resolve_subject(dem_land: np.ndarray, neighbours: np.ndarray,
                    subject_seed: np.ndarray) -> np.ndarray:
    """Subject land = DEM-land minus neighbours, keeping only the connected
    components that the subject's own NE polygon seeds. Pure, array-only:
      - the seaward edge falls on the DEM coast (dem_land),
      - the landward edge falls on the NE border (neighbours removed),
      - far unmapped land the seed never touches is dropped.
    """
    candidate = dem_land & ~neighbours
    labels, count = label(candidate)  # pyright: ignore[reportGeneralTypeIssues]  # scipy: (array, int)
    if count == 0:
        return np.zeros_like(candidate)
    seeded = set(np.unique(labels[subject_seed & (labels > 0)]))
    seeded.discard(0)
    if not seeded:
        return np.zeros_like(candidate)
    # Fill enclosed holes: aquaculture ponds / tidal-flat cells / internal lakes are
    # water surrounded by the subject's land, so each would otherwise get its own
    # boundary stroke (the Taiwan-west-coast speckle) AND be dimmed as if it were
    # foreign. The spotlight marks a country's OUTER extent, so close them.
    return np.asarray(binary_fill_holes(np.isin(labels, list(seeded))), dtype=bool)


def build_overlay(rgb, hero_alpha, subject, dim, desat, feather_px, outline_px,
                  halo_alpha=HALO_ALPHA_DEFAULT):
    """Compose the transparent spotlight overlay (H,W,4 float in 0..1). Pure.

    All edge geometry comes from two Euclidean distance transforms computed once:
    O(pixels) regardless of outline width (iterated morphology would dominate on
    8K frames), and the feather is derived from the same signed distance rather
    than a third large-sigma blur."""
    content = hero_alpha > 0.01
    subject = np.asarray(subject, dtype=bool)
    # float32, not the EDT's default float64: three 44 MP distance fields at native
    # res are ~1 GB in float64 and the precision is wasted (distances feed a clip/blur).
    dist_in = np.asarray(distance_transform_edt(subject), dtype=np.float32)    # >0 inside
    dist_out = np.asarray(distance_transform_edt(~subject), dtype=np.float32)  # >0 outside
    dist_edge = np.where(subject, dist_in, dist_out)         # distance to boundary, both sides

    # Linear feather across ~feather_px either side of the boundary (1 inside, 0 outside).
    feathered = np.clip(0.5 + (dist_in - dist_out) / (2.0 * max(feather_px, 1e-6)), 0.0, 1.0)
    overlay_rgb = dim_desaturate(rgb, dim, desat)
    overlay_alpha = (1.0 - feathered) * content

    # Boundary: a thin white hairline over a faint dark keyline. Both are only
    # AA-blurred (sigma<1, no fattening) — the old grow*2 halo blurred at sigma=grow
    # smeared into a ~24px ribbon that merged across convoluted coasts (skerries, tidal
    # flats) and washed the shoreline out. Thin + crisp keeps the coast readable.
    grow = max(1.0, outline_px)
    line_a = gaussian_filter((dist_edge <= grow).astype(np.float32), sigma=0.5)
    line_a = np.clip(line_a / max(line_a.max(), 1e-6), 0.0, 1.0)
    halo_a = gaussian_filter((dist_edge <= grow * 1.6).astype(np.float32), sigma=0.6) * halo_alpha

    # dark halo first, then the white line, painted only over hero content
    for stroke_rgb, stroke_a in (((0.0, 0.0, 0.0), halo_a), ((0.97, 0.96, 0.92), line_a)):
        stroke_a = stroke_a * content
        overlay_rgb = overlay_rgb * (1 - stroke_a[..., None]) + np.array(stroke_rgb) * stroke_a[..., None]
        overlay_alpha = overlay_alpha + stroke_a * (1 - overlay_alpha)

    return np.dstack([np.clip(overlay_rgb, 0, 1), np.clip(overlay_alpha, 0, 1)])


def rasterise_polygons(parts_by_feature, fwd, to_px, width, height):
    """Fill projected lon/lat polygon rings into a boolean mask via cairo."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    ctx.set_source_rgba(1, 1, 1, 1)
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    for parts in parts_by_feature:
        for ring in parts:
            xs, ys = fwd.transform(ring[:, 0], ring[:, 1])
            col, row = to_px(xs, ys)
            ctx.move_to(col[0], row[0])
            for c, r in zip(col[1:], row[1:]):
                ctx.line_to(c, r)
            ctx.close_path()
        ctx.fill()
    surface.flush()
    buf = np.ndarray((height, surface.get_stride() // 4, 4),
                     dtype=np.uint8, buffer=surface.get_data())[:, :width, :]
    return buf[:, :, 3] > 127


def frame_bbox_lonlat(bounds, crs, pad_deg=1.5):
    inv = pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    xs = np.linspace(bounds.left, bounds.right, 25)
    ys = np.linspace(bounds.bottom, bounds.top, 25)
    ex = np.concatenate([xs, xs, np.full(25, bounds.left), np.full(25, bounds.right)])
    ey = np.concatenate([np.full(25, bounds.bottom), np.full(25, bounds.top), ys, ys])
    lon, lat = inv.transform(ex, ey)
    return (lon.min() - pad_deg, lat.min() - pad_deg,
            lon.max() + pad_deg, lat.max() + pad_deg)


def load_parts(shp_path, bbox, want_slug, exclude=False):
    """Polygon rings per feature whose ADMIN slug (does not) match want_slug."""
    minx, miny, maxx, maxy = bbox
    out = []
    reader = shapefile.Reader(str(shp_path))
    for shape_record in reader.iterShapeRecords():
        shape, record = shape_record.shape, shape_record.record
        if shape is None or record is None or not shape.points:
            continue
        matches = slugify(str(record["ADMIN"])) == want_slug
        if matches == exclude:
            continue
        sb = shape.bbox
        if sb[2] < minx or sb[0] > maxx or sb[3] < miny or sb[1] > maxy:
            continue
        pts = np.asarray(shape.points)
        breaks = list(shape.parts) + [len(pts)]
        out.append([pts[breaks[i]:breaks[i + 1]] for i in range(len(breaks) - 1)])
    return out


def render_one(slug, dim, desat, force, outline_div=OUTLINE_DIV_DEFAULT, halo=HALO_ALPHA_DEFAULT):
    hero_path = HEROES / f"{slug}.png"
    render_dir = WORK / slug / "render"
    ocean_path = render_dir / "oceanmask_aea.tif"
    heightfield_path = render_dir / "heightfield_aea.tif"
    if not hero_path.exists() or not ocean_path.exists() or not heightfield_path.exists():
        print(f"  {slug}: skip (no hero / oceanmask / heightfield)", flush=True)
        return

    with rasterio.open(hero_path) as src:
        full_w, full_h = src.width, src.height
    with rasterio.open(ocean_path) as ods:
        bounds, crs = ods.bounds, ods.crs
        ocean_full = ods.read(1)
        ocean_transform = ods.transform
    bbox = frame_bbox_lonlat(bounds, crs)
    subject_parts = load_parts(NE_COUNTRIES, bbox, slug, exclude=False)
    neighbour_parts = load_parts(NE_COUNTRIES, bbox, slug, exclude=True)
    if not subject_parts:
        print(f"  {slug}: skip (no NE polygon)", flush=True)
        return
    fwd = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)

    sizes = sorted(set(list(TARGETS) + [max(full_w, full_h)]))
    for long_edge in sizes:
        if long_edge > max(full_w, full_h):
            continue
        out_path = VARIANTS / f"{slug}-spotlight-{long_edge}.webp"
        if out_path.exists() and not force:
            continue
        scale = long_edge / max(full_w, full_h)
        width, height = round(full_w * scale), round(full_h * scale)

        with rasterio.open(hero_path) as src:
            bands = src.read(out_shape=(src.count, height, width),
                             resampling=Resampling.bilinear)
        rgb = np.transpose(bands[:3].astype(np.float32) / 255.0, (1, 2, 0))
        hero_alpha = (bands[3] / 255.0) if bands.shape[0] >= 4 else np.ones((height, width), np.float32)

        # AEA->hero-pixel mapping (margin-aware, the SAME one gen_borders uses),
        # and the hero grid's own AEA affine so the oceanmask lands in register.
        to_px, m_per_px, _crs, hf_bounds = render_mapping(heightfield_path, width, height)
        center_x = (hf_bounds.left + hf_bounds.right) / 2.0
        center_y = (hf_bounds.bottom + hf_bounds.top) / 2.0
        hero_transform = from_origin(center_x - width / 2.0 * m_per_px,
                                     center_y + height / 2.0 * m_per_px, m_per_px, m_per_px)
        ocean = np.ones((height, width), dtype=ocean_full.dtype)  # margin fills as ocean(1)
        reproject(ocean_full, ocean, src_transform=ocean_transform, src_crs=crs,
                  dst_transform=hero_transform, dst_crs=crs, resampling=Resampling.nearest)
        dem_land = ocean == 0  # value 0 = land in oceanmask_aea (verified)

        subject_seed = rasterise_polygons(subject_parts, fwd, to_px, width, height)
        neighbours = rasterise_polygons(neighbour_parts, fwd, to_px, width, height) if neighbour_parts \
            else np.zeros((height, width), bool)
        subject = resolve_subject(dem_land, neighbours, subject_seed)
        if not subject.any():
            print(f"  {slug}@{long_edge}: subject mask empty — skipped", flush=True)
            continue

        overlay = build_overlay(rgb, hero_alpha, subject, dim, desat,
                                feather_px=long_edge / 900.0,
                                outline_px=max(1.0, long_edge / outline_div),
                                halo_alpha=halo)
        write_webp(overlay, out_path)
        print(f"  {slug}: wrote {out_path.name} ({width}x{height})", flush=True)


def write_webp(rgba: np.ndarray, out_path: Path) -> None:
    """RGBA float -> WebP with alpha, via a temp PNG + gdal_translate (the
    CreateCopy path hero_variants uses, which preserves the alpha channel)."""
    arr = (np.transpose(rgba, (2, 0, 1)) * 255).astype(np.uint8)
    # Uncompressed GTiff temp: writing a 44 MP PNG spends ~15 s in zlib for bytes
    # gdal immediately re-reads — a raw GTiff writes in ~1 s, and WebP (CreateCopy,
    # the only path that keeps the alpha channel) does the real compression once.
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        tmp_tif = Path(tmp.name)
    try:
        with rasterio.open(tmp_tif, "w", driver="GTiff", width=rgba.shape[1],
                           height=rgba.shape[0], count=4, dtype="uint8") as dst:
            dst.write(arr)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["gdal_translate", "-q", "-of", "WEBP",
                        "-co", f"QUALITY={WEBP_QUALITY}", str(tmp_tif), str(out_path)],
                       check=True)
    finally:
        tmp_tif.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated slugs (default: all heroes)")
    ap.add_argument("--dim", type=float, default=DIM_DEFAULT)
    ap.add_argument("--desat", type=float, default=DESAT_DEFAULT)
    ap.add_argument("--force", action="store_true", help="rewrite existing overlays")
    ap.add_argument("--outline-div", type=float, default=OUTLINE_DIV_DEFAULT,
                    help="boundary hairline half-width = long_edge / this (bigger = thinner)")
    ap.add_argument("--halo", type=float, default=HALO_ALPHA_DEFAULT,
                    help="dark keyline alpha under the white line (0 = none)")
    ap.add_argument("--jobs", type=int, default=1,
                    help="parallel worker processes over countries. The largest countries "
                         "peak at ~8 GB each at native res, so the full 203-set OOMs at "
                         "--jobs>1 under the 12 G cgroup cap; raise it only with real headroom "
                         "(budget ~8 GB per job).")
    args = ap.parse_args()

    if args.only:
        slugs = args.only.split(",")
    else:
        slugs = sorted(p.stem for p in HEROES.glob("*.png"))
    jobs = max(1, min(args.jobs, len(slugs)))
    print(f"spotlight: {len(slugs)} countries, dim={args.dim}, desat={args.desat}, "
          f"jobs={jobs}", flush=True)
    if jobs == 1:
        for slug in slugs:
            render_one(slug, args.dim, args.desat, args.force, args.outline_div, args.halo)
        return 0
    # Pin each worker's native libraries to one thread apiece: with `jobs` processes
    # already saturating the cores, letting numpy/OpenBLAS/GDAL each spawn their own
    # thread pool oversubscribes (jobs x cores). Set in the parent so workers AND the
    # gdal_translate subprocess inherit it (numpy reads these at import). setdefault so
    # an explicit override still wins.
    for thread_var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "GDAL_NUM_THREADS"):
        os.environ.setdefault(thread_var, "1")
    # forkserver, not the default fork: by pool-creation time the parent has imported
    # GDAL/PROJ/OpenBLAS (which spawn threads), and forking a multithreaded process can
    # deadlock (numpy's multi-core guidance). forkserver forks workers from a clean,
    # single-threaded server process instead.
    pool_context = multiprocessing.get_context("forkserver")
    # Fan out across countries — the loop is embarrassingly parallel. Progress lines
    # print from the workers (each carries its slug + flush), so they stay readable
    # interleaved; a worker that raises is reported here without sinking the batch.
    with ProcessPoolExecutor(max_workers=jobs, mp_context=pool_context) as pool:
        pending = {pool.submit(render_one, slug, args.dim, args.desat, args.force,
                               args.outline_div, args.halo): slug
                   for slug in slugs}
        for future in as_completed(pending):
            slug = pending[future]
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001 — one country failing must not kill the batch
                print(f"  {slug}: FAILED — {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
