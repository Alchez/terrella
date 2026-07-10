#!/usr/bin/env python3
"""Generate the Tier-1 gallery manifest (src/data/countries.json).

Bridges the render pipeline to the frontend: it reads the in-scope country list
(and proper display names) from the pipeline's country_config, then scans the
hero WebP variant store to see which countries have been rendered and at what
sizes. Re-run it after a render + hero_variants pass to refresh the gallery.

Run with the *pipeline* venv (it imports country_config → geopandas/rasterio):
  /home/rohan/projects/maps/.venv/bin/python scripts/gen_manifest.py \
      --repo /home/rohan/projects/maps --out src/data/countries.json
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


def aspect_of(variants_dir: Path, slug: str, sizes: list[int]) -> float:
    """width/height from the smallest variant (accurate framing, no layout shift)."""
    if not sizes:
        return 1.5
    import rasterio
    with rasterio.open(variants_dir / f"{slug}-{sizes[0]}.webp") as im:
        return round(im.width / im.height, 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path("/home/rohan/projects/maps"),
                    help="pipeline repo (has country_config + the asset store)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    sys.path.insert(0, str(args.repo / "pipeline"))
    from country_config import (build_scope, load_config,  # noqa: E402
                                load_ne_rows, resolve)

    variants_dir = args.repo / "blender/renders/variants"
    cfg = load_config()
    _sf, rows = load_ne_rows()
    scope = build_scope(cfg, rows)

    countries = []
    for slug in sorted(scope):
        r = resolve(slug, scope[slug], cfg)
        if r is None:              # antimeridian-deferred (Kiribati)
            continue
        sizes = variant_sizes(variants_dir, slug)
        countries.append(dict(
            slug=slug,
            name=r["admin"],
            aspect=aspect_of(variants_dir, slug, sizes),
            sizes=sizes,
            native=sizes[-1] if sizes else None,
            rendered=bool(sizes),
            hasBorder=False,       # border-layer generation is a later pass
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
