#!/usr/bin/env python3
"""Responsive WebP variants of the hero renders for the Tier-1 gallery srcset.

Each 8K hero PNG (~50 MB, RGBA) is far too heavy to serve directly. This emits
lossy WebP at three long-edge sizes — 1920 (2K), 3840 (4K), and the hero's
native long edge (full-res) — Lanczos-downscaled, alpha preserved, into
blender/renders/variants/<slug>-<longedge>.webp. The frontend builds
<img srcset> from these; the PNG stays the lossless master.

Uses the GDAL WebP driver (already present via GDAL) — no cwebp/Pillow needed.
Downscale-only: a target at or above the hero's native long edge collapses to
the single native variant (never upscales). Idempotent: existing variants are
skipped.

Usage:
  hero_variants.py                  # every hero in blender/renders/heroes/
  hero_variants.py --only srilanka  # one (or a comma list)
"""

import argparse
import subprocess
import sys
import warnings
from pathlib import Path

import rasterio
from rasterio.errors import NotGeoreferencedWarning

warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)  # PNGs

ROOT = Path(__file__).resolve().parents[2]
HEROES = ROOT / "blender/renders/heroes"
VARIANTS = ROOT / "blender/renders/variants"
TARGETS = (1920, 3840)   # plus each hero's native long edge (full-res WebP)
QUALITY = 85


def dims(path: Path) -> tuple[int, int]:
    with rasterio.open(path) as dataset:
        return dataset.width, dataset.height


def make_variant(src: Path, wide: bool, long_px: int, out: Path) -> None:
    """WebP at long_px on the long axis; the short axis follows aspect (0=auto)."""
    outsize = [str(long_px), "0"] if wide else ["0", str(long_px)]
    subprocess.run(["gdal_translate", "-q", "-of", "WEBP", "-r", "lanczos",
                    "-outsize", *outsize, "-co", f"QUALITY={QUALITY}",
                    str(src), str(out)], check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated slugs (default: all heroes)")
    args = ap.parse_args()

    VARIANTS.mkdir(parents=True, exist_ok=True)
    heroes = sorted(HEROES.glob("*.png"))
    if args.only:
        want = set(args.only.split(","))
        heroes = [hero for hero in heroes if hero.stem in want]
    if not heroes:
        sys.exit("no heroes to process (check blender/renders/heroes/ and --only)")

    made = skipped = 0
    for hero in heroes:
        width, height = dims(hero)
        native = max(width, height)
        for long_px in sorted({target for target in TARGETS if target < native} | {native}):
            out = VARIANTS / f"{hero.stem}-{long_px}.webp"
            if out.exists():
                skipped += 1
                continue
            make_variant(hero, width >= height, long_px, out)
            print(f"  {out.name}", flush=True)
            made += 1
    print(f"complete: {made} written, {skipped} skipped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
