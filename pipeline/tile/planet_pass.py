"""Run one body's planet pass: warp the inputs, produce the colour raster, cut tiles, render caps.

WHY THIS IS NOT `block_render.main`. The pass is four stages and the raster is only one of them, so
the sequence lives outside whichever module fills it; hosting it inside one stage is what left
`run_pass.sh` naming a module path to pick behaviour.

  1. `warp_inputs`   `prep_block` cuts from exactly these rasters
  2. the raster      `block_render.run`
  3. the tile cut    cannot tell what filled the raster, which is the design
  4. the polar caps  raytraced off the same rig

    python -m pipeline.tile.planet_pass --body earth            # produce only
    python -m pipeline.tile.planet_pass --body earth --tiles    # + cut tiles
"""

import argparse
import subprocess
import sys
from pathlib import Path

from pipeline import bodies, planet_seam, planet_warp, progress
from pipeline.freshness import is_stale
from pipeline.tile import block_render, cut_tiles, relief_scan


def _raytrace(work: Path, body: bodies.Body, rasters: frozenset[str], height: Path) -> Path:
    """Render the planet block by block out of Cycles. Resumable: stopping costs one block."""
    del rasters, height          # this producer re-reads both through its own input check
    mosaic = block_render.mosaic_in(work)
    block_render.run(body, work, mosaic)
    return mosaic


def build_parser() -> argparse.ArgumentParser:
    """The CLI, split out of `main` so its contract is testable without running a pass."""
    ap = argparse.ArgumentParser()
    # REQUIRED, WITH NO DEFAULT, and that is the whole point. A pass that assumes Earth because
    # nobody said otherwise does not fail — it produces a complete, plausible, entirely wrong
    # pyramid, and the cost of discovering that late is a planet. Naming it costs one word.
    ap.add_argument("--body", required=True,
                    help=f"which planet this pass is for ({', '.join(sorted(bodies.BODIES))})")
    # Optional override. Left unset it follows the body, which also honours the MAPS_DATA seam its
    # checkout-rooted default used to bypass; set, it is how a look A/B is pointed elsewhere. The
    # old spelling is described rather than quoted — `tests/test_paths.py` scans for it, and a
    # comment reproducing it re-creates the needle the scan exists to find.
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--tiles", action="store_true",
                    help="also cut tiles from the raster, z0 to the body's own ceiling")
    # No `--knob`: every constant it tuned belonged to the compositor, and `tests/test_bodies.py`
    # holds them deleted rather than merely unused.
    return ap


def resolve_body(args: argparse.Namespace) -> bodies.Body:
    """The body this run is for. Raises through the registry, which names the ones that exist."""
    return bodies.get(args.body)


def resolve_out(args: argparse.Namespace) -> Path:
    """Where this run writes: the explicit `--out`, else the body's own tile-work directory."""
    return args.out if args.out is not None else relief_scan.work_dir(resolve_body(args))


def raster_is_complete(planet_tif: Path) -> bool:
    """Whether the raster is a whole planet, and therefore safe to cut tiles from.

    NOT THE QUESTION `build_tiles` ASKS, and that is why this exists. That stage compares the tiles
    against the raster, which a HALF-rendered raster passes: it is newer than the tiles, so the cut
    runs and publishes a planet with holes in it. Stopping a raytraced pass part-way is normal —
    resume is its whole design — so the partial state is expected rather than a crash, and the
    completion marker is the only thing that tells the two apart.

    `is_stale` with no inputs is exactly that question: never completed, or rewritten since it was.
    """
    return not is_stale(planet_tif)


def runs_cap_pass(body: bodies.Body) -> bool:
    """Whether a pass for this body ends by rendering polar caps.

    A named predicate rather than the field read inline, so the DECISION is testable without
    spawning a subprocess. Inline, the only way to prove the pass respects the registry is to run it
    and watch what it shells out to — which needs a produced planet on disk, so in practice it would
    be proven by nothing.
    """
    return body.renders_polar_caps


def cap_pass_command(body: bodies.Body) -> list[str]:
    """The command that renders this body's polar caps at the tail of a pass.

    Built here rather than spelled inline because the body crosses a PROCESS boundary as a string
    on a command line, which is the one hop the registry cannot type-check. Left off, the cap pass
    would refuse to start (its `--body` is required too) — which is the failure this shape converts
    into a hard stop instead of a Mars pass quietly re-rendering Earth's poles.
    """
    return [sys.executable, "-m", "pipeline.tile.cap_pass", "--body", body.name]


def main() -> None:
    args = build_parser().parse_args()
    body = resolve_body(args)
    work = resolve_out(args)
    work.mkdir(parents=True, exist_ok=True)

    # Read ONCE, at the top, and threaded down. The planet stage declares what it emitted and this
    # raises if it never finished, so a half-built planet stops here rather than being shaded into a
    # plausible-looking pyramid.
    rasters = planet_seam.declared(body)

    height = planet_warp.warp_inputs(work, planet_seam.planet_dir(body), body, rasters)
    planet_tif = _raytrace(work, body, rasters, height)

    if args.tiles and not raster_is_complete(planet_tif):
        progress.stage(f"{planet_tif.name} is incomplete -> tiles NOT cut "
                       f"(re-run to resume the producer)")
    elif args.tiles:
        cut_tiles.build_tiles(planet_tif, work, body)

    # The polar caps are pass outputs too: they run the same look over the same sources, so a
    # look change that restages the raster must restage them. Both caps once sat stale against the
    # tiles they feather into (the north -6.7 DN adrift) because nothing coupled them to the recipe.
    # cap_render guards itself (cap_is_fresh), so a fresh pass pays only the ~2 s import here.
    # Subprocess, not import: cap_render imports FROM this package, and the caps' pyproj/scipy stack
    # stays out of the tile pass.
    if runs_cap_pass(body):
        progress.stage("polar caps ...")
        subprocess.run(cap_pass_command(body), check=True)
    else:
        # SAID OUT LOUD, because the alternative is a pass that silently does less than the last one
        # did. The cap pass would otherwise run and SUCCEED here — it needs only the heightfield once
        # a body declares no surface layers — spending ~14 GB per pole to publish discs shaded by
        # ramps this body has not ratified.
        progress.stage(f"polar caps: {body.name} publishes none — skipped "
                       f"(the globe carries a hole above the Mercator limit)")
    progress.stage("DONE")


if __name__ == "__main__":
    sys.exit(main())
