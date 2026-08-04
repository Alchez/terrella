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
from pathlib import Path

import cairo

import pyproj  # noqa: E402
from pipeline import naturalearth, paths  # noqa: E402
from pipeline.frame.country_config import (build_scope, country_render_dir,  # noqa: E402
                                           country_work_dir, load_config, load_ne_rows)
from pipeline.compose.overlay_borders import (DASHED_CLASSES, DISPUTED_STYLE,  # noqa: E402
                             LAND_STYLE, MARITIME_STYLE, SOLID_CLASSES,
                             frame_bbox_lonlat, read_lines, render_mapping,
                             stroke)

# The rendered layers live in the CHECKOUT beside the heroes they overlay; the per-country inputs
# they read live in the DATA store, reached through `country_work_dir`. Two roots, two seams.
BORDERS = paths.ROOT / "blender/renders/borders"
VARIANTS = paths.ROOT / "blender/renders/variants"
# The globe's hero panel is the only surface that overlays this layer, and it declares a 420 px
# slot — so the rungs that matter are 420 px at DPR 1/2/3. 1920 alone left that panel pulling an
# 85 kB border PNG on top of a 48 kB hero, i.e. the border became the heavier half of the card
# (caught after the hero and spotlight ladders had already been extended past it).
# 3840 is deliberately absent: unlike the hero, this layer is never displayed larger than the
# panel, and each country's native long edge is added below regardless.
TARGETS = (640, 960, 1280, 1920)   # each country's native long edge added too




def find_render_dir(slug: str) -> Path | None:
    """work/<slug>/render, else the first render* dir with the prep outputs."""
    work = country_work_dir(slug)
    cand = [country_render_dir(slug), *sorted(work.glob("render*"))]
    for candidate in cand:
        if (candidate / "frame.json").exists() and (candidate / "heightfield_aea.tif").exists():
            return candidate
    return None


def draw_layer(rdir: Path):
    """Draw casing + white ink at the hero render resolution; return the surface."""
    meta = json.loads((rdir / "frame.json").read_text())
    width, height = int(meta["res_x"]), int(meta["res_y"])
    to_px, _m, crs, bounds = render_mapping(rdir / "heightfield_aea.tif", width, height)
    fwd = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    bbox = frame_bbox_lonlat(bounds, crs)

    land = list(read_lines(naturalearth.layer("ne_10m_admin_0_boundary_lines_land"), bbox))
    solid = [(record, parts) for record, parts in land if record.as_dict()["FEATURECLA"] in SOLID_CLASSES]
    dashed = [(record, parts) for record, parts in land if record.as_dict()["FEATURECLA"] in DASHED_CLASSES]
    maritime = list(read_lines(
        naturalearth.layer("ne_10m_admin_0_boundary_lines_maritime_indicator"), bbox))

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
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
    return surface, (width, height), len(solid) + len(dashed) + len(maritime)


def write_png(surface, long_px: int, out: Path) -> None:
    """Downscale the layer to long_px on its long edge (preserving alpha), atomic."""
    width, height = surface.get_width(), surface.get_height()
    sf = long_px / max(width, height)
    small = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                               max(1, round(width * sf)), max(1, round(height * sf)))
    context = cairo.Context(small)
    context.scale(sf, sf)
    context.set_source_surface(surface, 0, 0)
    context.paint()
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
        slugs = [slug for slug in slugs if slug in set(args.only.split(","))]

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
        variants = [VARIANTS / f"{slug}-border-{size}.png" for size in sizes]
        if full.exists() and all(variant.exists() for variant in variants) and not args.force:
            skipped += 1
            continue

        surface, (width, height), count = draw_layer(rdir)
        if count == 0:            # island with no land/maritime lines in frame
            empty += 1
            continue
        tmp = full.with_name(full.name + ".tmp")
        surface.write_to_png(str(tmp))
        tmp.replace(full)
        for size in sizes:
            write_png(surface, size, VARIANTS / f"{slug}-border-{size}.png")
        print(f"{slug:22} {width}x{height}  {count} features -> border + "
              f"{len(sizes)} variants {sizes}", flush=True)
        done += 1

    print(f"\nborders: {done} generated, {skipped} skipped, {empty} empty, "
          f"{nodir} no-render-dir", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
