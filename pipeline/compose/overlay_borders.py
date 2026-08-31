"""Overlay Natural Earth vectors on a rendered hero image.

Modes:
  oracle  — draw the NE coastline in magenta over the render and measure how
            tightly it hugs the land/sea boundary of the ocean mask. Verifies
            the Albers→render-pixel mapping before any real border is drawn:
            a systematic offset here means the mapping below is wrong.
            Tolerances are in ground METERS, not render pixels: NE's 1:10m
            line disagrees with the WBM-derived coast by up to ~1-2 km around
            lagoon spits and shifting sandbars (measured on Sri Lanka), so
            that is the noise floor regardless of how fine
            one country's m/px is. Mapping failures are uniform multi-km
            shifts — still unmissable at these tolerances.
  borders — draw the production overlay: solid white international borders,
            dashed disputed/LoC segments, dashed maritime indicator lines.
            Emits both a composited hero and a standalone transparent RGBA
            layer (the gallery border-toggle asset).
  hydro   — vector water (Route B of the inland-water A/B): NE lakes as
            filled polygons over scalerank-tapered river centerlines, in the
            same flat teal as the Route A material demo.

The AEA→pixel mapping models the ortho camera exactly: the displacement plane
is PLANE_WIDTH_UNITS wide (its height follows the raster aspect), the camera's
ortho scale spans the *larger* render dimension (Blender sensor fit Auto), so
the plane underfills the frame by a couple of pixels per side at 8K. Pixels
are square and the plane is centered, so the mapping is one isotropic
meters-per-pixel scale plus the frame center.

Usage:
  overlay_borders.py --mode oracle \
      --render blender/renders/india_hero_8k_v3_water.png \
      --heightfield data/work/india/render/heightfield.tif \
      --mask data/work/india/render/oceanmask.tif \
      --outdir data/work/india/render/overlay

`--ne-dir` defaults to the store's own vector directory and is only worth naming when pointing at
a different Natural Earth release.
"""

import argparse
import json
import sys
from pathlib import Path

import cairo
import numpy as np
import pyproj
import rasterio
import shapefile

from pipeline import datasets, naturalearth

PLANE_WIDTH_UNITS = 2.0

# Art levers (see ART.md): width in render pixels at 8K, dash = [on, off] px.
# casing = wider dark stroke drawn beneath the white ink so lines keep contrast
# over pale high terrain; dashed lines get identically-dashed casing.
# Widths are sized for fit-to-screen viewing of the 8K (≈ quarter scale): a line
# must survive 4x downscaling. Judge on the 2K preview, not the 1:1 crops.
ORACLE_STYLE = dict(rgba=(1.0, 0.0, 1.0, 1.0), width=3.0)
LAND_STYLE = dict(rgba=(1.0, 1.0, 1.0, 0.95), width=10.0,
                  casing=dict(rgba=(0.24, 0.17, 0.12, 0.35), width=14.0))
DISPUTED_STYLE = dict(rgba=(1.0, 1.0, 1.0, 0.95), width=10.0, dash=[30, 20],
                      casing=dict(rgba=(0.24, 0.17, 0.12, 0.35), width=14.0))
MARITIME_STYLE = dict(rgba=(1.0, 1.0, 1.0, 0.8), width=7.0, dash=[40, 25],
                      casing=dict(rgba=(0.24, 0.17, 0.12, 0.25), width=10.5))

# hydro: flat 98C5C8 to match the Route A demo teal. The current NE 10m file
# has no strokeweig field, so river width tapers by scalerank (1 = major):
# width = width_base + width_per_rank * (10 - scalerank), px at 8K.
WATER_RGBA = (0.596, 0.773, 0.784, 1.0)
LAKE_STYLE = dict(rgba=WATER_RGBA)
RIVER_STYLE = dict(rgba=WATER_RGBA, width_base=1.5, width_per_rank=0.65)

SOLID_CLASSES = {"International boundary (verify)"}
DASHED_CLASSES = {
    "Disputed (please verify)",
    "Line of control (please verify)",
    "Indefinite (please verify)",
    "Indeterminant frontier",
}

CROP_SITES = {  # lon, lat of 1:1 inspection crops
    "khambhat": (72.6, 21.5),
    "palk": (79.5, 9.6),
    "sundarbans": (89.0, 21.8),
    "kashmir": (76.0, 34.5),
    "tibet_lakes": (88.0, 31.5),
    "ganges": (82.5, 25.5),
    "brahmaputra": (91.0, 26.3),
}
CROP_SIZE = 900


def render_mapping(heightfield, render_w, render_h):
    """Derive the AEA→render-pixel mapping from the raster the plane displays.

    The camera's ortho scale comes from frame.json next to the heightfield —
    the same number scene_build.py framed the render with, so pinned frames
    (India v3's hand-rounded 2.06) keep compositing correctly."""
    frame_path = heightfield.parent / "frame.json"
    if not frame_path.exists():
        sys.exit(f"{frame_path} not found — render_prep.py emits it")
    ortho_scale = json.loads(frame_path.read_text())["ortho_scale"]

    with rasterio.open(heightfield) as src:
        bounds, crs = src.bounds, src.crs
    extent_w = bounds.right - bounds.left
    extent_h = bounds.top - bounds.bottom

    render_aspect = render_h / render_w
    raster_aspect = extent_h / extent_w
    if abs(render_aspect - raster_aspect) / raster_aspect > 0.005:
        sys.exit(f"render aspect {render_aspect:.4f} != raster aspect "
                 f"{raster_aspect:.4f} — wrong render or wrong heightfield")

    units_per_px = ortho_scale / max(render_w, render_h)
    m_per_px = units_per_px * extent_w / PLANE_WIDTH_UNITS
    cx = (bounds.left + bounds.right) / 2.0
    cy = (bounds.bottom + bounds.top) / 2.0

    def to_px(x_coord, y_coord):
        col = render_w / 2.0 + (np.asarray(x_coord) - cx) / m_per_px
        row = render_h / 2.0 - (np.asarray(y_coord) - cy) / m_per_px
        return col, row

    return to_px, m_per_px, crs, bounds


def frame_bbox_lonlat(bounds, crs, pad_deg=2.0):
    """Geographic bbox of the AEA frame, for cheap feature prefiltering."""
    inv = pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    sample_count = 25
    xs = np.linspace(bounds.left, bounds.right, sample_count)
    ys = np.linspace(bounds.bottom, bounds.top, sample_count)
    ex = np.concatenate([xs, xs, np.full(sample_count, bounds.left), np.full(sample_count, bounds.right)])
    ey = np.concatenate([np.full(sample_count, bounds.bottom), np.full(sample_count, bounds.top), ys, ys])
    lon, lat = inv.transform(ex, ey)
    return (lon.min() - pad_deg, lat.min() - pad_deg,
            lon.max() + pad_deg, lat.max() + pad_deg)


def read_lines(shp_path, bbox):
    """Yield (record, [Nx2 lon/lat arrays, one per part]) for features
    whose bbox overlaps the frame's geographic bbox."""
    minx, miny, maxx, maxy = bbox
    sf = shapefile.Reader(str(shp_path))
    for sr in sf.iterShapeRecords():
        if sr.shape is None or sr.record is None:  # spec allows null shapes
            continue
        if not sr.shape.points:
            continue
        sb = sr.shape.bbox
        if sb[2] < minx or sb[0] > maxx or sb[3] < miny or sb[1] > maxy:
            continue
        pts = np.asarray(sr.shape.points)
        parts = list(sr.shape.parts) + [len(pts)]
        yield sr.record, [pts[parts[part_index]:parts[part_index + 1]] for part_index in range(len(parts) - 1)]


def stroke(ctx, fwd, to_px, features, rgba, width, dash=None):
    """Stroke line features onto a cairo context; returns feature count."""
    ctx.set_source_rgba(*rgba)
    ctx.set_line_width(width)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_dash(dash or [])
    count = 0
    for _, parts in features:
        count += 1
        for pts in parts:
            x_coords, y_coords = fwd.transform(pts[:, 0], pts[:, 1])
            col, row = to_px(x_coords, y_coords)
            ctx.move_to(col[0], row[0])
            for col_val, row_val in zip(col[1:], row[1:]):
                ctx.line_to(col_val, row_val)
    ctx.stroke()
    return count


def fill_polys(ctx, fwd, to_px, features, rgba):
    """Fill polygon features; even-odd rule turns interior rings into holes.
    Filled per feature so overlapping features cannot cancel each other."""
    ctx.set_source_rgba(*rgba)
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    count = 0
    for _, parts in features:
        count += 1
        for pts in parts:
            x_coords, y_coords = fwd.transform(pts[:, 0], pts[:, 1])
            col, row = to_px(x_coords, y_coords)
            ctx.move_to(col[0], row[0])
            for col_val, row_val in zip(col[1:], row[1:]):
                ctx.line_to(col_val, row_val)
            ctx.close_path()
        ctx.fill()
    return count


def stroke_rivers(ctx, fwd, to_px, rivers, rgba, width_base, width_per_rank):
    """Stroke (scalerank, parts) river features, wider for lower scalerank."""
    ctx.set_source_rgba(*rgba)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_dash([])
    for rank, parts in rivers:
        ctx.set_line_width(width_base + width_per_rank * (10 - rank))
        for pts in parts:
            x_coords, y_coords = fwd.transform(pts[:, 0], pts[:, 1])
            col, row = to_px(x_coords, y_coords)
            ctx.move_to(col[0], row[0])
            for col_val, row_val in zip(col[1:], row[1:]):
                ctx.line_to(col_val, row_val)
        ctx.stroke()
    return len(rivers)


def surface_alpha(surface):
    """Alpha channel of an ARGB32 surface as a (H, W) uint8 array."""
    surface.flush()
    height, stride = surface.get_height(), surface.get_stride()
    buf = np.ndarray((height, stride // 4, 4), dtype=np.uint8, buffer=surface.get_data())
    return buf[:, :surface.get_width(), 3].copy()


def coast_agreement(mask_path, drawn, to_px, m_per_px):
    """Percent of drawn coastline pixels within {600, 1200, 2500} m of the
    ocean-mask land/sea boundary. Low numbers at 2500 m = the mapping is
    systematically off (per-country m/px is divided out; see docstring)."""
    with rasterio.open(mask_path) as src:
        mask = src.read(1)
        transform = src.transform
    edge = np.zeros(mask.shape, bool)
    edge[:, 1:] |= mask[:, 1:] != mask[:, :-1]
    edge[1:, :] |= mask[1:, :] != mask[:-1, :]
    rr, cc = np.nonzero(edge)  # pyright: ignore[reportGeneralTypeIssues, reportAssignmentType] — numpy stubs see a 1-tuple for unknown-dim input
    xs = transform.c + (cc + 0.5) * transform.a
    ys = transform.f + (rr + 0.5) * transform.e
    col, row = to_px(xs, ys)
    col = np.round(col).astype(np.int64)
    row = np.round(row).astype(np.int64)
    height, width = drawn.shape
    ok = (col >= 0) & (col < width) & (row >= 0) & (row < height)
    edge_img = np.zeros((height, width), bool)
    edge_img[row[ok], col[ok]] = True

    drawn_px = int(drawn.sum())
    if drawn_px == 0:
        sys.exit("oracle drew zero pixels — mapping or data is broken")
    px_buckets = {max(1, round(meters / m_per_px)): meters
                  for meters in (600, 1200, 2500)}
    stats, grown = {}, edge_img
    for radius in range(1, max(px_buckets) + 1):
        grown = (grown | np.roll(grown, 1, 0) | np.roll(grown, -1, 0)
                 | np.roll(grown, 1, 1) | np.roll(grown, -1, 1))
        if radius in px_buckets:
            stats[px_buckets[radius]] = (radius, 100.0 * int((drawn & grown).sum())
                                    / drawn_px)
    return stats


def save_scaled(surface, out_path, target_w=2048):
    sf = target_w / surface.get_width()
    small = cairo.ImageSurface(cairo.FORMAT_ARGB32, target_w,
                               round(surface.get_height() * sf))
    ctx = cairo.Context(small)
    ctx.scale(sf, sf)
    ctx.set_source_surface(surface, 0, 0)
    ctx.paint()
    small.write_to_png(str(out_path))


def save_crops(surface, fwd, to_px, outdir, tag):
    for name, (lon, lat) in CROP_SITES.items():
        x_coord, y_coord = fwd.transform(lon, lat)
        col, row = to_px(x_coord, y_coord)
        crop = cairo.ImageSurface(cairo.FORMAT_ARGB32, CROP_SIZE, CROP_SIZE)
        ctx = cairo.Context(crop)
        ctx.set_source_surface(surface, -(float(col) - CROP_SIZE // 2),
                               -(float(row) - CROP_SIZE // 2))
        ctx.paint()
        crop.write_to_png(str(outdir / f"{tag}_crop_{name}.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["oracle", "borders", "hydro"],
                    required=True)
    ap.add_argument("--render", type=Path, required=True)
    ap.add_argument("--heightfield", type=Path, required=True)
    ap.add_argument("--mask", type=Path)
    ap.add_argument("--ne-dir", type=Path, default=datasets.naturalearth(),
                    help="a different Natural Earth release; defaults to the store's own")
    ap.add_argument("--outdir", type=Path, required=True)
    args = ap.parse_args()
    if args.mode == "oracle" and not args.mask:
        ap.error("--mask is required in oracle mode")
    args.outdir.mkdir(parents=True, exist_ok=True)

    comp = cairo.ImageSurface.create_from_png(str(args.render))
    width, height = comp.get_width(), comp.get_height()
    print(f"render: {width} x {height}", flush=True)

    to_px, m_per_px, crs, bounds = render_mapping(args.heightfield, width, height)
    fwd = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    bbox = frame_bbox_lonlat(bounds, crs)
    print(f"frame lon/lat bbox (padded): {[f'{value:.1f}' for value in bbox]}", flush=True)

    overlay = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    octx = cairo.Context(overlay)

    def ne(name: str) -> Path:
        """This entry point takes its directory from the command line, so the ROOT is the caller's
        and only the naming RULE is shared. Both travel through `naturalearth.layer`, which also
        refuses a layer the acquirer never fetches — the failure this used to defer to a
        missing-file error several frames later."""
        return naturalearth.layer(name, directory=args.ne_dir)

    if args.mode == "oracle":
        count = stroke(octx, fwd, to_px,
                   read_lines(ne("ne_10m_coastline"), bbox), **ORACLE_STYLE)
        print(f"coastline features drawn: {count}", flush=True)
        if count == 0:
            sys.exit("no coastline features in frame — prefilter or data broken")
        stats = coast_agreement(args.mask, surface_alpha(overlay) > 0, to_px,
                                m_per_px)
        for meters, (px, pct) in stats.items():
            print(f"drawn coastline within {meters:4d} m ({px:2d} px): "
                  f"{pct:5.1f}%", flush=True)
        if stats[2500][1] < 90.0:
            print("WARNING: <90% within 2500 m — suspect a systematic offset",
                  flush=True)
        tag = "oracle"
    elif args.mode == "hydro":
        rivers, centerlines = [], 0
        for rec, parts in read_lines(ne("ne_10m_rivers_lake_centerlines"),
                                     bbox):
            record_dict = rec.as_dict()
            if "featurecla" not in record_dict or "scalerank" not in record_dict:
                sys.exit(f"expected lowercase featurecla/scalerank in rivers "
                         f"file; fields are {list(record_dict)}")
            if record_dict["featurecla"] == "Lake Centerline":
                centerlines += 1  # lake polygons cover these
                continue
            rivers.append((record_dict["scalerank"], parts))
        lakes = list(read_lines(ne("ne_10m_lakes"), bbox))
        if not rivers or not lakes:
            sys.exit("zero rivers or lakes in an India frame — data or "
                     "prefilter broken")
        lake_classes = {}
        for rec, _ in lakes:
            fc = rec.as_dict()["featurecla"]
            lake_classes[fc] = lake_classes.get(fc, 0) + 1
        print(f"rivers {len(rivers)} (skipped {centerlines} lake "
              f"centerlines), lakes {lake_classes}", flush=True)

        stroke_rivers(octx, fwd, to_px, rivers, **RIVER_STYLE)
        fill_polys(octx, fwd, to_px, lakes, **LAKE_STYLE)
        overlay.write_to_png(str(args.outdir / "hydro_layer_8k.png"))
        tag = "hydro"
    else:
        land = ne("ne_10m_admin_0_boundary_lines_land")
        classes = {}
        for rec, _ in read_lines(land, bbox):
            record_dict = rec.as_dict()
            if "FEATURECLA" not in record_dict:
                sys.exit(f"FEATURECLA field missing; fields are {list(record_dict)}")
            classes[record_dict["FEATURECLA"]] = classes.get(record_dict["FEATURECLA"], 0) + 1
        print(f"border classes in frame: {classes}", flush=True)

        solid = [(record, parts) for record, parts in read_lines(land, bbox)
                 if record.as_dict()["FEATURECLA"] in SOLID_CLASSES]
        dashed = [(record, parts) for record, parts in read_lines(land, bbox)
                  if record.as_dict()["FEATURECLA"] in DASHED_CLASSES]
        maritime = list(read_lines(
            ne("ne_10m_admin_0_boundary_lines_maritime_indicator"), bbox))
        if not solid:
            sys.exit("zero solid international borders in an India frame — broken")
        print(f"solid {len(solid)}, dashed {len(dashed)}, "
              f"maritime {len(maritime)}", flush=True)
        layer_sets = [(maritime, MARITIME_STYLE), (solid, LAND_STYLE),
                      (dashed, DISPUTED_STYLE)]
        for feats, style in layer_sets:
            casing = style.get("casing")
            if casing:
                stroke(octx, fwd, to_px, feats, casing["rgba"], casing["width"],
                       dash=style.get("dash"))
        for feats, style in layer_sets:
            stroke(octx, fwd, to_px, feats, style["rgba"], style["width"],
                   dash=style.get("dash"))
        overlay.write_to_png(str(args.outdir / "borders_layer_8k.png"))
        tag = "borders"

    cctx = cairo.Context(comp)
    cctx.set_source_surface(overlay, 0, 0)
    cctx.paint()
    comp.write_to_png(str(args.outdir / f"{tag}_composited_8k.png"))
    save_scaled(comp, args.outdir / f"{tag}_preview_2k.png")
    save_crops(comp, fwd, to_px, args.outdir, tag)
    print("complete", flush=True)


if __name__ == "__main__":
    main()
