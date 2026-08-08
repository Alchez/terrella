"""Responsive WebP variants of the hero renders for the Tier-1 gallery srcset.

Each 8K hero PNG (~50 MB, RGBA) is far too heavy to serve directly. This emits
lossy WebP at every rung in TARGETS plus the hero's native long edge,
Lanczos-downscaled, alpha preserved, into
blender/renders/variants/<slug>-<longedge>.webp. The frontend builds
<img srcset> from these; the PNG stays the lossless master.

Quality is a POLICY rather than one constant. The small rungs are
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
import math
import os
import subprocess
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import rasterio
from rasterio.errors import NotGeoreferencedWarning

from pipeline import paths

warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)  # PNGs

# Checkout-rooted on purpose: hero products live in the repo tree, not in the relocatable data
# store. Taken from `paths` rather than re-derived, so this module cannot grow its own idea of where
# the root is — which is how three of its siblings acquired a data path that ignored `MAPS_DATA`.
HEROES = paths.ROOT / "blender/renders/heroes"
VARIANTS = paths.ROOT / "blender/renders/variants"
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

# A rung names the LONG EDGE, but `srcset` selects on WIDTH. For a landscape hero those are the same
# number and the ladder above lands where the comment says. For a PORTRAIT hero the width is
# `rung * aspect`, so the same five rungs deliver a compressed set of widths — Albania (aspect 0.465)
# gets 297/446/595/892/1786, where the last step DOUBLES. A DPR-3 phone asking for ~1,076 px of width
# falls straight through that gap onto 3840, which is also where quality steps q85 -> q95: the pixel
# jump and the quality jump compound and one card goes from 399 KiB to 2,252 KiB.
#
# So a portrait hero gets one extra rung, sized from its own aspect rather than shared. A single
# shared rung cannot work — checked: 2560 covers Albania and leaves Tonga and Israel exactly as
# broken, because a fixed long edge serves every aspect differently, which is the original defect one
# level down.
MOBILE_DEMAND_PX = 1187  # 430 CSS px viewport (the widest phone) x `sizes` 92vw x DPR 3
FILL_GRID = 512          # keeps the fill rungs to a handful of values instead of one per country
# What the store was written at before RECIPE existed: this module carried a bare `QUALITY = 85`
# for its whole life before that, so an unrecorded rung is known, not unknown.
LEGACY_QUALITY = 85


def quality_for(long_px: int) -> int:
    """WebP quality for one rung — the single home of the small/large split."""
    return LARGE_QUALITY if long_px >= LARGE_RUNG_PX else SMALL_QUALITY


def fill_rung(width: int, height: int) -> int | None:
    """The extra long-edge rung a portrait hero needs to serve a phone, or None.

    Returns the smallest FILL_GRID multiple whose DELIVERED WIDTH covers MOBILE_DEMAND_PX, and None
    when the existing thumbnail rungs already cover it (every landscape hero, and any portrait one
    wide enough) or when no rung below LARGE_RUNG_PX can.

    That last case is a real exclusion, not an oversight: Chile (0.307) and Maldives (0.234) need
    long edges of 3,867 and 5,064, so their fill rung would itself be an inspection-quality file
    delivered as a thumbnail — trading one form of the bug for the other. They wait for a ladder
    keyed to width rather than to long edge, which is the fix this one approximates.
    """
    aspect = min(1.0, width / height)
    thumbnail_targets = [target for target in TARGETS if target < LARGE_RUNG_PX]
    if any(round(target * aspect) >= MOBILE_DEMAND_PX for target in thumbnail_targets):
        return None
    wanted = math.ceil(MOBILE_DEMAND_PX / aspect)
    snapped = math.ceil(wanted / FILL_GRID) * FILL_GRID
    return snapped if snapped < LARGE_RUNG_PX else None


def rungs_for(width: int, height: int) -> list[int]:
    """Rung set for one hero: every TARGET strictly below its native long edge, plus native, plus
    the portrait fill rung when `fill_rung` calls for one."""
    native = max(width, height)
    targets: set[int] = set(TARGETS)
    fill = fill_rung(width, height)
    if fill is not None:
        targets.add(fill)
    return sorted({target for target in targets if target < native} | {native})


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
