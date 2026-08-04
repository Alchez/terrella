#!/usr/bin/env python3
"""Generate the Tier-1 gallery manifest (src/data/countries.json).

Bridges the render pipeline to the frontend: it reads the in-scope country list
(and proper display names) from the pipeline's country_config, then scans the
hero WebP variant store to see which countries have been rendered and at what
sizes. Re-run it after a render + hero_variants pass to refresh the gallery.

Run from web/ with the *pipeline* venv (it imports country_config → geopandas/rasterio);
--repo defaults to the checkout this script lives in:
  ../.venv/bin/python scripts/gen_manifest.py --out src/data/countries.json
"""

import argparse
import json
import re
import sys
from pathlib import Path


def variant_sizes(variants_dir: Path, slug: str) -> list[int]:
    """Long-edge sizes present for a slug, e.g. [1920, 3840, 7680]."""
    sizes = []
    for p in variants_dir.glob(f"{slug}-*.webp"):
        m = re.fullmatch(rf"{re.escape(slug)}-(\d+)\.webp", p.name)
        if m:
            sizes.append(int(m.group(1)))
    return sorted(set(sizes))


def continent_by_admin(shp: Path) -> dict:
    """ADMIN -> CONTINENT from the Natural Earth countries shapefile.

    Takes the shapefile rather than deriving it, because `--repo` is the CHECKOUT and Natural Earth
    lives in the DATA store — two roots that are equal by default and diverge the moment `MAPS_DATA`
    is set. The caller has the pipeline on its path by then and asks the pipeline where its own
    vectors are.
    """
    import shapefile
    reader = shapefile.Reader(str(shp))
    out = {}
    for record in reader.iterRecords():
        fields = record.as_dict()
        out[str(fields.get("ADMIN"))] = str(fields.get("CONTINENT", ""))
    return out


def border_sizes(variants_dir: Path, slug: str) -> list[int]:
    """Long-edge sizes of the standalone border layer, e.g. [1920, 7680]."""
    sizes = []
    for p in variants_dir.glob(f"{slug}-border-*.png"):
        m = re.fullmatch(rf"{re.escape(slug)}-border-(\d+)\.png", p.name)
        if m:
            sizes.append(int(m.group(1)))
    return sorted(set(sizes))


def spotlight_sizes(variants_dir: Path, slug: str) -> list[int]:
    """Long-edge sizes of the subject-spotlight overlay (dims neighbours + strokes
    the subject boundary), e.g. [1920, 3840, 7680]."""
    sizes = []
    for p in variants_dir.glob(f"{slug}-spotlight-*.webp"):
        m = re.fullmatch(rf"{re.escape(slug)}-spotlight-(\d+)\.webp", p.name)
        if m:
            sizes.append(int(m.group(1)))
    return sorted(set(sizes))


def aspect_of(variants_dir: Path, slug: str, sizes: list[int]) -> float:
    """width/height from the LARGEST variant (accurate framing, no layout shift).

    Read off the largest rather than the smallest because aspect feeds both the CSS
    `aspect-ratio` and the srcset w-descriptors, and a 640-wide variant quantises the ratio ~12x
    more coarsely than the native one. It used to read sizes[0] because the ladder's floor was
    1920; adding rungs beneath that would have silently coarsened every country's framing.
    """
    if not sizes:
        return 1.5
    import rasterio
    with rasterio.open(variants_dir / f"{slug}-{sizes[-1]}.webp") as im:
        return round(im.width / im.height, 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2],
                    help="pipeline repo (has country_config + the asset store)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    sys.path.insert(0, str(args.repo))  # repo root: country_config uses pipeline.* imports
    from pipeline import naturalearth  # noqa: E402
    from pipeline.frame.country_config import (build_scope, load_config,  # noqa: E402
                                               load_ne_rows, resolve)

    variants_dir = args.repo / "blender/renders/variants"
    cfg = load_config()
    _sf, rows = load_ne_rows()
    scope = build_scope(cfg, rows)
    continents = continent_by_admin(naturalearth.layer("ne_10m_admin_0_countries"))

    countries = []
    for slug in sorted(scope):
        r = resolve(slug, scope[slug], cfg)
        if r is None:              # antimeridian-deferred (Kiribati)
            continue
        sizes = variant_sizes(variants_dir, slug)
        bsizes = border_sizes(variants_dir, slug)
        ssizes = spotlight_sizes(variants_dir, slug)
        countries.append(dict(
            slug=slug,
            name=r["admin"],
            continent=continents.get(r["admin"], ""),
            # Authored (w,s,e,n) EPSG:4326 hero frame — the globe's fly-to target.
            # Same framing as the hero renders, so overrides (France→metropolitan,
            # US/Chile/Russia) already fix the far-flung multipolygon cases that a
            # raw country bbox would frame badly.
            bbox=[round(v, 5) for v in r["frame"]],
            aspect=aspect_of(variants_dir, slug, sizes),
            sizes=sizes,
            native=sizes[-1] if sizes else None,
            rendered=bool(sizes),
            hasBorder=bool(bsizes),
            borderSizes=bsizes,
            hasSpotlight=bool(ssizes),
            spotlightSizes=ssizes,
        ))

    payload = dict(
        count=len(countries),
        rendered=sum(c["rendered"] for c in countries),
        countries=countries,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {args.out}: {payload['count']} countries, "
          f"{payload['rendered']} rendered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
