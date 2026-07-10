#!/usr/bin/env python3
"""Batch-generate standalone transparent border layers + gallery variants.

The gallery's border toggle overlays a per-country transparent PNG of the
Natural Earth international / disputed / maritime lines, registered
pixel-for-pixel with the hero. This draws that layer — reusing overlay_borders'
proven AEA->pixel mapping and 'borders' styling — at the hero render resolution
(frame.json res_x/res_y), then downscales it to the same long-edge sizes as the
hero WebP variants so the two srcset in lockstep.

It needs only the prep outputs (frame.json + heightfield_aea.tif), NOT the hero
render, so it can run any time after prep. Idempotent: existing outputs skip.
Line widths are tuned for the full 8K render and survive downscaling (see ART.md
/ overlay_borders), so the layer is always drawn at full res then scaled down.

  gen_borders.py --only srilanka,switzerland
  gen_borders.py                      # every in-scope country with a render dir
"""

import argparse
import json
import sys
from pathlib import Path

import cairo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import pyproj  # noqa: E402
from country_config import build_scope, load_config, load_ne_rows  # noqa: E402
from overlay_borders import (DASHED_CLASSES, DISPUTED_STYLE,  # noqa: E402
                             LAND_STYLE, MARITIME_STYLE, SOLID_CLASSES,
                             frame_bbox_lonlat, read_lines, render_mapping,
                             stroke)

NE = ROOT / "data/raw/naturalearth"
BORDERS = ROOT / "blender/renders/borders"
VARIANTS = ROOT / "blender/renders/variants"
WORK = ROOT / "data/work"
TARGETS = (1920,)   # gallery-card size; each country's native long edge added too


def ne(name: str) -> Path:
    return NE / name / f"{name}.shp"


def find_render_dir(slug: str) -> Path | None:
    """work/<slug>/render, else the first render* dir with the prep outputs."""
    cand = [WORK / slug / "render", *sorted((WORK / slug).glob("render*"))]
    for d in cand:
        if (d / "frame.json").exists() and (d / "heightfield_aea.tif").exists():
            return d
    return None


def draw_layer(rdir: Path):
    """Draw casing + white ink at the hero render resolution; return the surface."""
    meta = json.loads((rdir / "frame.json").read_text())
    w, h = int(meta["res_x"]), int(meta["res_y"])
    to_px, _m, crs, bounds = render_mapping(rdir / "heightfield_aea.tif", w, h)
    fwd = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    bbox = frame_bbox_lonlat(bounds, crs)

    land = list(read_lines(ne("ne_10m_admin_0_boundary_lines_land"), bbox))
    solid = [(r, p) for r, p in land if r.as_dict()["FEATURECLA"] in SOLID_CLASSES]
    dashed = [(r, p) for r, p in land if r.as_dict()["FEATURECLA"] in DASHED_CLASSES]
    maritime = list(read_lines(
        ne("ne_10m_admin_0_boundary_lines_maritime_indicator"), bbox))

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    ctx = cairo.Context(surface)
    layer_sets = [(maritime, MARITIME_STYLE), (solid, LAND_STYLE),
                  (dashed, DISPUTED_STYLE)]
    for feats, style in layer_sets:          # dark casing halo, drawn under
        casing = style.get("casing")
        if casing:
            stroke(ctx, fwd, to_px, feats, casing["rgba"], casing["width"],
                   dash=style.get("dash"))
    for feats, style in layer_sets:          # white ink on top
        stroke(ctx, fwd, to_px, feats, style["rgba"], style["width"],
               dash=style.get("dash"))
    return surface, (w, h), len(solid) + len(dashed) + len(maritime)


def write_png(surface, long_px: int, out: Path) -> None:
    """Downscale the layer to long_px on its long edge (preserving alpha), atomic."""
    w, h = surface.get_width(), surface.get_height()
    sf = long_px / max(w, h)
    small = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                               max(1, round(w * sf)), max(1, round(h * sf)))
    c = cairo.Context(small)
    c.scale(sf, sf)
    c.set_source_surface(surface, 0, 0)
    c.paint()
    tmp = out.with_name(out.name + ".tmp")
    small.write_to_png(str(tmp))
    tmp.replace(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated slugs")
    ap.add_argument("--force", action="store_true", help="redo existing layers")
    args = ap.parse_args()

    cfg = load_config()
    _sf, rows = load_ne_rows()
    scope = build_scope(cfg, rows)
    slugs = sorted(scope)
    if args.only:
        slugs = [s for s in slugs if s in set(args.only.split(","))]

    BORDERS.mkdir(parents=True, exist_ok=True)
    VARIANTS.mkdir(parents=True, exist_ok=True)
    done = skipped = nodir = empty = 0
    for slug in slugs:
        rdir = find_render_dir(slug)
        if rdir is None:
            nodir += 1
            continue
        meta = json.loads((rdir / "frame.json").read_text())
        native = max(int(meta["res_x"]), int(meta["res_y"]))
        sizes = sorted(set(TARGETS) | {native})
        full = BORDERS / f"{slug}.png"
        variants = [VARIANTS / f"{slug}-border-{s}.png" for s in sizes]
        if full.exists() and all(v.exists() for v in variants) and not args.force:
            skipped += 1
            continue

        surface, (w, h), n = draw_layer(rdir)
        if n == 0:                # island with no land/maritime lines in frame
            empty += 1
            continue
        tmp = full.with_name(full.name + ".tmp")
        surface.write_to_png(str(tmp))
        tmp.replace(full)
        for s in sizes:
            write_png(surface, s, VARIANTS / f"{slug}-border-{s}.png")
        print(f"{slug:22} {w}x{h}  {n} features -> border + "
              f"{len(sizes)} variants {sizes}", flush=True)
        done += 1

    print(f"\nborders: {done} generated, {skipped} skipped, {empty} empty, "
          f"{nodir} no-render-dir", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
