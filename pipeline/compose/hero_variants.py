#!/usr/bin/env python3
"""Responsive WebP variants of the hero renders for the Tier-1 gallery srcset.

Each 8K hero PNG (~50 MB, RGBA) is far too heavy to serve directly. This emits
lossy WebP at every rung in TARGETS plus the hero's native long edge,
Lanczos-downscaled, alpha preserved, into
blender/renders/variants/<slug>-<longedge>.webp. The frontend builds
<img srcset> from these; the PNG stays the lossless master.

Quality is a POLICY rather than one constant (2026-07-25). The small rungs are
thumbnails in a ~350 px masonry column and q85 is ample there; 3840 and native
are what a reader opens full-screen and zooms into, so they carry q95. The whole
climb q85 -> q98 costs 2.1x while the last step to lossless costs another 2.4x,
which is why the ladder stops where it does. quality_for() is the one place that
decides; everything else asks it.

Uses the GDAL WebP driver (already present via GDAL) — no cwebp/Pillow needed.
Downscale-only: a target at or above the hero's native long edge collapses to
the single native variant (never upscales).

Idempotent, and resumable ACROSS A QUALITY CHANGE, which plain existence cannot
be: a file re-encoded at q95 is indistinguishable from the q85 one it replaced.
RECIPE records the quality each rung was last written at, and a rung whose policy
has moved is deleted, then re-recorded, then rewritten — in that order, so a crash
at any point leaves the recipe and the files on disk agreeing with each other.

Usage:
  hero_variants.py                  # every hero in blender/renders/heroes/
  hero_variants.py --only srilanka  # one (or a comma list)
  hero_variants.py --force          # rewrite every rung, whatever RECIPE records
"""

import argparse
import json
import os
import subprocess
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import rasterio
from rasterio.errors import NotGeoreferencedWarning

warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)  # PNGs

ROOT = Path(__file__).resolve().parents[2]
HEROES = ROOT / "blender/renders/heroes"
VARIANTS = ROOT / "blender/renders/variants"
RECIPE = VARIANTS / "hero_variants_recipe.json"

# The srcset ladder, chosen against MEASURED layout rather than viewport guesses: the gallery is
# masonry (`columns: 320px`), so a card renders 324-516 CSS px at every viewport from 390 to 3440
# and device pixel ratio is the only real variable. That puts real demand in three bands —
# ~350 px (DPR-1 desktop), ~700-820 (DPR-2 laptops and tablets), ~1000-1100 (DPR-3 phones) —
# which 640 / 960 / 1280 serve exactly. 1920 stays as the country page's display rung.
TARGETS = (640, 960, 1280, 1920, 3840)   # plus each hero's native long edge (full-res WebP)
LARGE_RUNG_PX = 3840     # at or above this a variant is an inspection surface, not a thumbnail
SMALL_QUALITY = 85
LARGE_QUALITY = 95
# What the store was written at before RECIPE existed: this module carried a bare `QUALITY = 85`
# from its first commit until 2026-07-25, so an unrecorded rung is known, not unknown.
LEGACY_QUALITY = 85


def quality_for(long_px: int) -> int:
    """WebP quality for one rung — the single home of the small/large split."""
    return LARGE_QUALITY if long_px >= LARGE_RUNG_PX else SMALL_QUALITY


def rungs_for(width: int, height: int) -> list[int]:
    """Rung set for one hero: every TARGET strictly below its native long edge, plus native."""
    native = max(width, height)
    return sorted({target for target in TARGETS if target < native} | {native})


def read_recipe() -> dict[int, int]:
    """Rung -> the quality its files were last written at, empty when RECIPE does not exist yet.

    Callers must read a missing entry as LEGACY_QUALITY, not as "unknown": treating an absent
    recipe as unknown would re-encode 203 already-correct 1920 rungs on the first run after the
    policy landed, for byte-identical output.
    """
    if not RECIPE.exists():
        return {}
    recorded = json.loads(RECIPE.read_text())["quality"]
    return {int(rung): int(quality) for rung, quality in recorded.items()}


def write_recipe(recorded: dict[int, int]) -> None:
    """Persist the rung -> quality map. Called BEFORE a rung's files are rewritten, so that an
    interrupted rewrite resumes by existence instead of deleting what it has already produced."""
    payload = {"quality": {str(rung): quality for rung, quality in sorted(recorded.items())}}
    RECIPE.write_text(json.dumps(payload, indent=2) + "\n")


def dims(path: Path) -> tuple[int, int]:
    with rasterio.open(path) as dataset:
        return dataset.width, dataset.height


def make_variant(src: Path, wide: bool, long_px: int, quality: int, out: Path) -> None:
    """WebP at long_px on the long axis; the short axis follows aspect (0=auto).

    Staged under a .tmp name and renamed, because `out.exists()` is this module's whole resume
    oracle: gdal_translate writing in place leaves a TRUNCATED file behind after a kill or an
    interrupt, and every later run would skip it as finished. That is the same trap build_tiles
    documents for the tile cut, and this is the same .tmp + atomic-replace convention every other
    writer in the pipeline follows. GDAL's PAM sidecar rides along, or the store would accumulate
    `.webp.tmp.aux.xml` orphans next to correctly named variants.
    """
    outsize = [str(long_px), "0"] if wide else ["0", str(long_px)]
    staging = out.with_name(out.name + ".tmp")
    staging.unlink(missing_ok=True)
    subprocess.run(["gdal_translate", "-q", "-of", "WEBP", "-r", "lanczos",
                    "-outsize", *outsize, "-co", f"QUALITY={quality}",
                    str(src), str(staging)], check=True)
    staging_sidecar = staging.with_name(staging.name + ".aux.xml")
    os.replace(staging, out)
    if staging_sidecar.exists():
        os.replace(staging_sidecar, out.with_name(out.name + ".aux.xml"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated slugs (default: all heroes)")
    ap.add_argument("--force", action="store_true",
                    help="rewrite every rung, whatever RECIPE records")
    ap.add_argument("--jobs", type=int, default=1,
                    help="heroes encoded concurrently (default 1). Each gdal_translate peaks at "
                         "~525 MB, so this is bounded by cores rather than by the memory cap")
    args = ap.parse_args()
    if args.jobs < 1:
        sys.exit("--jobs must be at least 1")

    VARIANTS.mkdir(parents=True, exist_ok=True)
    heroes = sorted(HEROES.glob("*.png"))
    if args.only:
        want = set(args.only.split(","))
        heroes = [hero for hero in heroes if hero.stem in want]
    if not heroes:
        sys.exit("no heroes to process (check blender/renders/heroes/ and --only)")

    shapes = {hero: dims(hero) for hero in heroes}
    rungs = sorted({rung for hero in heroes for rung in rungs_for(*shapes[hero])})
    recorded = read_recipe()
    # A subset run must never claim a rung: it would record the whole rung as re-encoded while
    # 202 heroes still hold the old quality. --only therefore rewrites without recording, and a
    # later full run redoes that rung — wasteful, but it can never lie about the store.
    may_record = not args.only

    # Retire every rung whose policy moved BEFORE encoding anything, so the pass below can trust
    # existence again: after this, a file that is present was written under the current policy.
    for rung in rungs:
        quality = quality_for(rung)
        if args.force or recorded.get(rung, LEGACY_QUALITY) != quality:
            print(f"rung {rung}: quality -> q{quality}, retiring {len(heroes)} files", flush=True)
            for hero in heroes:
                (VARIANTS / f"{hero.stem}-{rung}.webp").unlink(missing_ok=True)
            if may_record:
                recorded[rung] = quality
                write_recipe(recorded)

    # Hero-major, so each ~60 MB master is decoded ONCE for all six of its rungs. Rung-major would
    # re-read every master per rung with 202 others read in between, defeating the page cache for
    # no gain — the retire pass above already gave this loop its per-rung correctness.
    def encode_hero(hero: Path) -> tuple[int, int]:
        width, height = shapes[hero]
        made = skipped = 0
        for rung in rungs_for(width, height):
            out = VARIANTS / f"{hero.stem}-{rung}.webp"
            if out.exists():
                skipped += 1
                continue
            make_variant(hero, width >= height, rung, quality_for(rung), out)
            print(f"  {out.name}", flush=True)
            made += 1
        return made, skipped

    # Threads, not processes: every worker spends its time inside gdal_translate, so the GIL is
    # released and there is nothing to pickle. Parallel over HEROES rather than over (hero, rung)
    # so one master's six rungs stay on one worker and the decode locality above survives.
    # Measured 523 MB peak per encode, so the ceiling is cores, not the 12 G cap — but the default
    # stays 1, as gen_spotlight's does: fan-out is a decision the caller makes with a known box.
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        counts = list(pool.map(encode_hero, heroes))
    made = sum(count[0] for count in counts)
    skipped = sum(count[1] for count in counts)
    # Only reached when every encode returned 0 (subprocess check=True), so this records rungs that
    # were skipped as well — the file then describes the whole store rather than just what moved.
    if may_record:
        for rung in rungs:
            recorded[rung] = quality_for(rung)
        write_recipe(recorded)
    print(f"complete: {made} written, {skipped} skipped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
