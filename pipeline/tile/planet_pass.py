"""Run one body's planet pass: warp the inputs, produce the colour raster, cut tiles, render caps.

WHY THIS IS NOT `shade_planet.main`. The pass is five stages and only ONE of them has two
implementations: the colour raster is either composited out of numpy or rendered out of Cycles, and
`bodies.Body.planet_producer` says which. Leaving the sequence inside the composite's own module
would make one producer the host of the other, and would leave the harness selecting a producer by
naming a module path in a shell script — which is what `run_pass.sh` did.

WHAT IS SHARED IS MOST OF IT, and that is why the fork is this small:

  1. `warp_inputs`   both — `prep_block` cuts from exactly the rasters the composite reads
  2. the hillshade   composite only — Cycles computes its own light
  3. the raster      THE FORK — `composite_planet` or `block_render.run`, same file, same directory
  4. the tile cut    both — the cut cannot tell which producer ran, which is the design
  5. the polar caps  both — `cap_render` composites its own discs whatever made the tiles

THE PRODUCER IS A DEPENDENCY AND NOT ONLY A CHOICE. Both producers stamp the same
`planet_rgb.done`, because `freshness.done_marker` derives from the output alone. So without the
stamp below each producer's freshness question is answered by the other's work, in both directions:
after a raytraced run the composite finds its own recipe unmoved and a newer raster and skips,
reporting raytraced pixels fresh; after a composited one an unchanged raytrace recipe does the same
in reverse. Separate recipes do not close this, because the hazard is the shared OUTPUT rather than
a shared dependency list. Both producers name the stamp, so a switch moves one mtime and both go
stale.

    python -m pipeline.tile.planet_pass --body earth            # produce only
    python -m pipeline.tile.planet_pass --body earth --tiles    # + cut tiles
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from pipeline import bodies, planet_seam
from pipeline.freshness import is_stale, write_if_changed
from pipeline.tile import block_render, shade_planet
from pipeline.tile.shade import KNOBS


def producer_stamp(work: Path) -> Path:
    """Where this pass records the producer, which both producers name as a dependency.

    The basename is `shade_planet.PRODUCER_STAMP`, beside the raster it describes rather than here,
    because the two dependency lists that read it cannot import this module without a cycle.
    """
    return work / shade_planet.PRODUCER_STAMP


def write_producer_stamp(work: Path, body: bodies.Body) -> Path:
    """Record the producer this body's raster is made by, and return the stamp.

    `write_if_changed` is what makes this a dependency rather than a restage: the mtime moves if and
    only if the recorded producer actually changed, so re-running an unchanged body rebuilds
    nothing. Written before either producer is asked its freshness question, per that function's own
    ordering rule.
    """
    return write_if_changed(producer_stamp(work),
                            json.dumps({"producer": body.planet_producer}, indent=2) + "\n")


def _composite(work: Path, body: bodies.Body, rasters: frozenset[str], height: Path) -> Path:
    """Shade the planet window by window out of numpy."""
    hillshade = shade_planet.build_hillshade(work, height, body)
    return shade_planet.composite_planet(
        work, hillshade, lambda: shade_planet.global_occlusion(height, body), body, rasters,
        window_rows=shade_planet.COMPOSITE_ROWS, max_workers=shade_planet.N_WORKERS)[None]


def _raytrace(work: Path, body: bodies.Body, rasters: frozenset[str], height: Path) -> Path:
    """Render the planet block by block out of Cycles. Resumable: stopping costs one block."""
    del rasters, height          # this producer re-reads both through its own input check
    mosaic = block_render.mosaic_in(work)
    block_render.run(body, work, mosaic)
    return mosaic


#: The producers, keyed by the value a body answers with.
#:
#: A REGISTRY RATHER THAN AN `if`, so that `bodies.PLANET_PRODUCERS` gaining a member is a red test
#: instead of a branch that silently falls through to the other one.
PRODUCERS: dict[str, Callable[[Path, bodies.Body, frozenset[str], Path], Path]] = {
    "composite": _composite,
    "raytrace": _raytrace,
}


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
    ap.add_argument("--knob", action="append", default=[], metavar="KEY=VALUE",
                    help="override a locked KNOBS entry (repeatable), as tile/shade.py does. "
                         "Look changes used to be made by EDITING the constant, which meant an "
                         "experiment and production shared one source of truth. Overrides are "
                         "safe for freshness by construction: composite_params/hs_params "
                         "serialise KNOBS, so an override restages exactly what it changes and "
                         "the recorded params always describe the pyramid that exists. Composite "
                         "bodies only — the raytraced producer reads none of them.")
    return ap


def resolve_body(args: argparse.Namespace) -> bodies.Body:
    """The body this run is for. Raises through the registry, which names the ones that exist."""
    return bodies.get(args.body)


def resolve_out(args: argparse.Namespace) -> Path:
    """Where this run writes: the explicit `--out`, else the body's own tile-work directory."""
    return args.out if args.out is not None else bodies.work_dir(resolve_body(args), "planet_tiles")


def producer_for(body: bodies.Body) -> Callable[[Path, bodies.Body, frozenset[str], Path], Path]:
    """The producer this body answers with, or raise naming the ones that exist.

    NO FALLBACK, on the rule `bodies.get` and `palette.look_for` already state: a body quietly
    borrowing another's producer spends a night making the wrong kind of planet.
    """
    try:
        return PRODUCERS[body.planet_producer]
    except KeyError:
        known = ", ".join(sorted(PRODUCERS))
        raise SystemExit(f"{body.name} names planet producer {body.planet_producer!r}, which this "
                         f"pass cannot run; known producers are: {known}") from None


def apply_knob_overrides(body: bodies.Body, overrides: list[str]) -> None:
    """Apply `--knob KEY=VALUE` to the locked KNOBS, refusing them on a body that reads none.

    THE REFUSAL IS THE POINT, not the applying. Every KNOBS entry is a composite constant, and the
    cap pass is a separate process with its own defaults, so on a raytraced body an override reaches
    no pixel anywhere. Silently accepted it would read as a look experiment that simply had no
    visible effect, which is indistinguishable from the look actually being insensitive to it.
    """
    if overrides and body.planet_producer != "composite":
        raise SystemExit(f"--knob tunes composite constants and {body.name} is produced by "
                         f"{body.planet_producer!r}, which reads none of them; the override would "
                         f"reach no pixel")
    # A key off argv is dynamic by construction, so a TypedDict cannot check it -- this view is
    # the honest escape hatch, and the membership test below is what actually validates the key.
    knobs = cast(dict[str, Any], KNOBS)
    for override in overrides:
        key, _, value = override.partition("=")
        if key not in knobs:
            raise SystemExit(f"unknown knob {key!r}; valid: {', '.join(sorted(knobs))}")
        knobs[key] = value if isinstance(knobs[key], str) else float(value)
        print(f"knob override: {key} = {knobs[key]}", flush=True)


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
    return [sys.executable, "-m", "pipeline.tile.cap_render", "--body", body.name]


def main() -> None:
    args = build_parser().parse_args()
    body = resolve_body(args)
    work = resolve_out(args)
    work.mkdir(parents=True, exist_ok=True)
    produce = producer_for(body)
    apply_knob_overrides(body, args.knob)

    # Read ONCE, at the top, and threaded down. The planet stage declares what it emitted and this
    # raises if it never finished, so a half-built planet stops here rather than being shaded into a
    # plausible-looking pyramid. Threading it (rather than each stage reading the file) keeps
    # `_compute_shared` a pure function of its arguments, which is what lets it run on workers.
    rasters = planet_seam.declared(body)
    height = shade_planet.warp_inputs(work, planet_seam.planet_dir(body), body, rasters)
    write_producer_stamp(work, body)
    planet_tif = produce(work, body, rasters, height)

    if args.tiles and not raster_is_complete(planet_tif):
        print(f"{planet_tif.name} is incomplete -> tiles NOT cut (re-run to resume the producer)",
              flush=True)
    elif args.tiles:
        shade_planet.build_tiles(planet_tif, work, body)

    # The polar caps are pass outputs too: they run the same composite over the same sources, so a
    # look change that restages the raster must restage them. Both caps once sat stale against the
    # tiles they feather into (the north -6.7 DN adrift) because nothing coupled them to the recipe.
    # cap_render guards itself (cap_is_fresh), so a fresh pass pays only the ~2 s import here.
    # Subprocess, not import: cap_render imports FROM shade_planet, and the caps' pyproj/scipy stack
    # stays out of the tile pass.
    if runs_cap_pass(body):
        print("polar caps ...", flush=True)
        subprocess.run(cap_pass_command(body), check=True)
    else:
        # SAID OUT LOUD, because the alternative is a pass that silently does less than the last one
        # did. The cap pass would otherwise run and SUCCEED here — it needs only the heightfield once
        # a body declares no surface layers — spending ~14 GB per pole to publish discs shaded by
        # ramps this body has not ratified.
        print(f"polar caps: {body.name} publishes none — skipped "
              f"(the globe carries a hole above the Mercator limit)", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
