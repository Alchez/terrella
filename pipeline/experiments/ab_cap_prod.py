#!/usr/bin/env python3
"""A/B ladder for cap productionisation: CAP_PX x WebP-quality rungs.

Each rung renders BOTH caps into the live web/public/caps/ path (what /globe reads), then
archives the pair into data/work/cap/ab_prod/px<px>_q<q>/ so any rung can be restored by
copying it back. The ladder ends on the DEFAULT rung so the served assets match the shipped
constants, and rewrites the freshness sidecars so the next cap_render run skips instead of
re-rendering what is already live (the ab_ice_damp restore-at-end pattern).

Usage: uv run python -m pipeline.experiments.ab_cap_prod
"""
import dataclasses
import os
import shutil
import time

from pipeline import bodies
from pipeline.tile import cap_render

os.environ.setdefault("GDAL_CACHEMAX", "512")

# Big rung first; the ladder must END on the default (CAP_PX, CAP_WEBP_QUALITY) so the live
# assets match cap_render's constants when the script exits.
RUNGS = [(8192, cap_render.CAP_WEBP_QUALITY),
         (cap_render.CAP_PX, cap_render.CAP_WEBP_QUALITY)]
# Earth by name, because this ladder is a record of a decision taken about Earth's caps. A second
# body wanting the same sweep names itself here rather than inheriting whatever the default was.
AB_DIR = cap_render.cap_work_dir(bodies.EARTH) / "ab_prod"


def render_rung(px: int, quality: int) -> None:
    cap_render.NORTH = dataclasses.replace(cap_render.NORTH, px=px)
    cap_render.SOUTH = dataclasses.replace(cap_render.SOUTH, px=px)
    cap_render.CAP_WEBP_QUALITY = quality
    rung_dir = AB_DIR / f"px{px}_q{quality}"
    rung_dir.mkdir(parents=True, exist_ok=True)
    for label, render in (("north", cap_render.render_cap_north),
                          ("south", cap_render.render_cap_south)):
        started = time.monotonic()
        asset = render()
        seconds = time.monotonic() - started
        size_mb = asset.stat().st_size / 1e6
        shutil.copy2(asset, rung_dir / asset.name)
        print(f"rung px{px} q{quality} {label}: {seconds:5.1f} s, {size_mb:.2f} MB", flush=True)


def main() -> int:
    for px, quality in RUNGS:
        render_rung(px, quality)
    # The final rung is the default: stamp the sidecars so production sees the live assets as
    # fresh (render_cap_* alone never writes them — that is main()'s job).
    for grid in (cap_render.NORTH, cap_render.SOUTH):
        sidecar = cap_render.cap_work_dir(grid.body) / f"cap_{grid.name}_params.json"
        sidecar.write_text(cap_render.cap_recipe(grid))
    served = cap_render.caps_public_dir(bodies.EARTH)
    (served / "caps.json").write_text(cap_render.caps_manifest() + "\n")
    print(f"ladder archived under {AB_DIR}; live = default rung", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
