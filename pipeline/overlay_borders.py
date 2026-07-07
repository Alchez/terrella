#!/usr/bin/env python3
"""Overlay Natural Earth vectors on a rendered hero image.

Modes:
  oracle  — draw the NE coastline in magenta over the render and measure how
            tightly it hugs the land/sea boundary of the ocean mask. Verifies
            the Albers→render-pixel mapping before any real border is drawn:
            a systematic offset here means the mapping below is wrong.
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
      --render blender/renders/india_hero_8k_candidate.png \
      --heightfield data/work/india/render/heightfield_aea.tif \
      --mask data/work/india/render/oceanmask_aea.tif \
      --ne-dir data/raw/naturalearth \
      --outdir data/work/india/render/overlay
"""

import argparse
import sys
from pathlib import Path

import cairo
import numpy as np
import pyproj
import rasterio
import shapefile

ORTHO_SCALE = 2.06
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
    """Derive the AEA→render-pixel mapping from the raster the plane displays."""
    with rasterio.open(heightfield) as src:
        b, crs = src.bounds, src.crs
    extent_w = b.right - b.left
    extent_h = b.top - b.bottom

    render_aspect = render_h / render_w
    raster_aspect = extent_h / extent_w
    if abs(render_aspect - raster_aspect) / raster_aspect > 0.005:
        sys.exit(f"render aspect {render_aspect:.4f} != raster aspect "
                 f"{raster_aspect:.4f} — wrong render or wrong heightfield")

    units_per_px = ORTHO_SCALE / max(render_w, render_h)
    m_per_px = units_per_px * extent_w / PLANE_WIDTH_UNITS
    cx = (b.left + b.right) / 2.0
    cy = (b.bottom + b.top) / 2.0

    def to_px(x, y):
        col = render_w / 2.0 + (np.asarray(x) - cx) / m_per_px
        row = render_h / 2.0 - (np.asarray(y) - cy) / m_per_px
        return col, row

    return to_px, crs, b


def frame_bbox_lonlat(bounds, crs, pad_deg=2.0):
    """Geographic bbox of the AEA frame, for cheap feature prefiltering."""
    inv = pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    n = 25
    xs = np.linspace(bounds.left, bounds.right, n)
    ys = np.linspace(bounds.bottom, bounds.top, n)
    ex = np.concatenate([xs, xs, np.full(n, bounds.left), np.full(n, bounds.right)])
    ey = np.concatenate([np.full(n, bounds.bottom), np.full(n, bounds.top), ys, ys])
    lon, lat = inv.transform(ex, ey)
    return (lon.min() - pad_deg, lat.min() - pad_deg,
            lon.max() + pad_deg, lat.max() + pad_deg)


def read_lines(shp_path, bbox):
    """Yield (record, [Nx2 lon/lat arrays, one per part]) for features
    whose bbox overlaps the frame's geographic bbox."""
    minx, miny, maxx, maxy = bbox
    sf = shapefile.Reader(str(shp_path))
    for sr in sf.iterShapeRecords():
        if not sr.shape.points:
            continue
        sb = sr.shape.bbox
        if sb[2] < minx or sb[0] > maxx or sb[3] < miny or sb[1] > maxy:
            continue
        pts = np.asarray(sr.shape.points)
        parts = list(sr.shape.parts) + [len(pts)]
        yield sr.record, [pts[parts[i]:parts[i + 1]] for i in range(len(parts) - 1)]


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
            x, y = fwd.transform(pts[:, 0], pts[:, 1])
            col, row = to_px(x, y)
            ctx.move_to(col[0], row[0])
            for c, r in zip(col[1:], row[1:]):
                ctx.line_to(c, r)
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
            x, y = fwd.transform(pts[:, 0], pts[:, 1])
            col, row = to_px(x, y)
            ctx.move_to(col[0], row[0])
            for c, r in zip(col[1:], row[1:]):
                ctx.line_to(c, r)
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
            x, y = fwd.transform(pts[:, 0], pts[:, 1])
            col, row = to_px(x, y)
            ctx.move_to(col[0], row[0])
            for c, r in zip(col[1:], row[1:]):
                ctx.line_to(c, r)
        ctx.stroke()
    return len(rivers)


def surface_alpha(surface):
    """Alpha channel of an ARGB32 surface as a (H, W) uint8 array."""
    surface.flush()
    h, stride = surface.get_height(), surface.get_stride()
    buf = np.ndarray((h, stride // 4, 4), dtype=np.uint8, buffer=surface.get_data())
    return buf[:, :surface.get_width(), 3].copy()


def coast_agreement(mask_path, drawn, to_px):
    """Percent of drawn coastline pixels within {2,5,10} px of the ocean-mask
    land/sea boundary. Low numbers = the mapping is systematically off."""
    with rasterio.open(mask_path) as src:
        m = src.read(1)
        t = src.transform
    edge = np.zeros(m.shape, bool)
    edge[:, 1:] |= m[:, 1:] != m[:, :-1]
    edge[1:, :] |= m[1:, :] != m[:-1, :]
    rr, cc = np.nonzero(edge)
    xs = t.c + (cc + 0.5) * t.a
    ys = t.f + (rr + 0.5) * t.e
    col, row = to_px(xs, ys)
    col = np.round(col).astype(np.int64)
    row = np.round(row).astype(np.int64)
    h, w = drawn.shape
    ok = (col >= 0) & (col < w) & (row >= 0) & (row < h)
    edge_img = np.zeros((h, w), bool)
    edge_img[row[ok], col[ok]] = True

    drawn_px = int(drawn.sum())
    if drawn_px == 0:
        sys.exit("oracle drew zero pixels — mapping or data is broken")
    stats, grown = {}, edge_img
    for n in range(1, 11):
        grown = (grown | np.roll(grown, 1, 0) | np.roll(grown, -1, 0)
                 | np.roll(grown, 1, 1) | np.roll(grown, -1, 1))
        if n in (2, 5, 10):
            stats[n] = 100.0 * int((drawn & grown).sum()) / drawn_px
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
        x, y = fwd.transform(lon, lat)
        col, row = to_px(x, y)
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
    ap.add_argument("--ne-dir", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    args = ap.parse_args()
    if args.mode == "oracle" and not args.mask:
        ap.error("--mask is required in oracle mode")
    args.outdir.mkdir(parents=True, exist_ok=True)

    comp = cairo.ImageSurface.create_from_png(str(args.render))
    w, h = comp.get_width(), comp.get_height()
    print(f"render: {w} x {h}", flush=True)

    to_px, crs, bounds = render_mapping(args.heightfield, w, h)
    fwd = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    bbox = frame_bbox_lonlat(bounds, crs)
    print(f"frame lon/lat bbox (padded): {['%.1f' % v for v in bbox]}", flush=True)

    overlay = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    octx = cairo.Context(overlay)

    def ne(name):
        return args.ne_dir / name / f"{name}.shp"

    if args.mode == "oracle":
        n = stroke(octx, fwd, to_px,
                   read_lines(ne("ne_10m_coastline"), bbox), **ORACLE_STYLE)
        print(f"coastline features drawn: {n}", flush=True)
        if n == 0:
            sys.exit("no coastline features in frame — prefilter or data broken")
        stats = coast_agreement(args.mask, surface_alpha(overlay) > 0, to_px)
        for k, v in stats.items():
            print(f"drawn coastline within {k:2d} px of mask boundary: {v:5.1f}%",
                  flush=True)
        if stats[5] < 90.0:
            print("WARNING: <90% within 5 px — suspect a systematic offset",
                  flush=True)
        tag = "oracle"
    elif args.mode == "hydro":
        rivers, centerlines = [], 0
        for rec, parts in read_lines(ne("ne_10m_rivers_lake_centerlines"),
                                     bbox):
            d = rec.as_dict()
            if "featurecla" not in d or "scalerank" not in d:
                sys.exit(f"expected lowercase featurecla/scalerank in rivers "
                         f"file; fields are {list(d)}")
            if d["featurecla"] == "Lake Centerline":
                centerlines += 1  # lake polygons cover these
                continue
            rivers.append((d["scalerank"], parts))
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
            d = rec.as_dict()
            if "FEATURECLA" not in d:
                sys.exit(f"FEATURECLA field missing; fields are {list(d)}")
            classes[d["FEATURECLA"]] = classes.get(d["FEATURECLA"], 0) + 1
        print(f"border classes in frame: {classes}", flush=True)

        solid = [(r, p) for r, p in read_lines(land, bbox)
                 if r.as_dict()["FEATURECLA"] in SOLID_CLASSES]
        dashed = [(r, p) for r, p in read_lines(land, bbox)
                  if r.as_dict()["FEATURECLA"] in DASHED_CLASSES]
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
