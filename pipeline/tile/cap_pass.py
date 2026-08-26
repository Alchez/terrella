"""Render a body's polar caps: choose the arm, ask the freshness question, publish the manifest.

THE ARM IS KEYED ON `planet_producer` BECAUSE A DISC IS BUILT TO MATCH THE TILES IT FEATHERS INTO.
The two producers of `planet_rgb` do not agree on colour, so a composited disc against raytraced
tiles is a visible step at the crossfade — which is the seam this pass's own recipe already tracks
(`cap_render.cap_recipe`'s `planet_producer` key) and which this registry is what finally closes.

THE PASS AND THE ARMS ARE SEPARATE MODULES SO THE REGISTRY CAN SEE BOTH. `cap_raytrace` imports
`cap_render` for the grid, the warps, the meridian rotation and the rung ladder, so a registry
inside either one is a cycle. This is `planet_pass`' shape one tier down, for the same reason.

    GDAL_CACHEMAX=512 uv run python -m pipeline.tile.cap_pass --body earth
"""
import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pipeline import bodies, planet_seam, progress
from pipeline.tile import cap_raytrace, cap_render


@dataclass(frozen=True)
class CapProducer:
    """One way to paint a body's discs, together with what it painted them under.

    THE TWO HALVES SHARE A RECORD BECAUSE `cap_is_fresh` ASKS THEM AS ONE QUESTION. It compares a
    single sidecar per pole against the recipe of whichever arm is current, so a render and a recipe
    that could be registered apart would be free to disagree — and the disagreement is silent in the
    worst direction: a disc painted by one arm, declared fresh under the other's recipe, forever.

    NO `refusals_for`, unlike `planet_pass.Producer`, and that is a fact rather than a stub. Every
    precondition here is shared: both arms warp the same heightfield through the same
    `planet_seam.declared`, and `prep_cap` writes the rig's mandatory images for any seam — it
    collapses lake and river onto one boolean and writes the river empty, where `prep_block` cannot.
    So there is no declaration one arm can take and the other cannot.
    """

    #: Paint this pole's disc and return the top rung's path.
    render: Callable[[cap_render.CapGrid, frozenset[str]], Path]
    #: What that render baked in, serialised for the freshness sidecar.
    recipe: Callable[[cap_render.CapGrid, frozenset[str]], str]


#: The cap arms, keyed by the value a body's `planet_producer` answers with.
#:
#: A REGISTRY RATHER THAN AN `if`, so `bodies.PLANET_PRODUCERS` gaining a member is a red test rather
#: than a branch that silently falls through to the composite — which would be a body publishing
#: raytraced tiles with composited discs, the exact mismatch the key exists to prevent.
CAP_PRODUCERS: dict[str, CapProducer] = {
    "composite": CapProducer(cap_render.render_cap, cap_render.cap_recipe),
    "raytrace": CapProducer(cap_raytrace.render, cap_raytrace.params),
}


def producer_for(body: bodies.Body) -> CapProducer:
    """The cap arm this body's producer choice names, or raise naming the ones that exist."""
    try:
        return CAP_PRODUCERS[body.planet_producer]
    except KeyError:
        known = ", ".join(sorted(CAP_PRODUCERS))
        raise SystemExit(f"{body.name} names planet producer {body.planet_producer!r}, which no "
                         f"cap arm can paint discs for; known producers are: {known}") from None


def build_parser() -> argparse.ArgumentParser:
    """The CLI, split out of `main` so its contract is testable without rendering a cap."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    # REQUIRED, WITH NO DEFAULT, exactly as the planet pass requires it. A cap is the one output
    # where the wrong sphere leaves no trace: it projects, blends and downsamples to every rung, and
    # simply sits on a different parallel than the tiles it feathers into. `shade_planet` passes
    # this through when it invokes the cap pass — the flag name is stated in both places, and
    # `test_the_shade_pass_hands_its_own_body_down_to_the_cap_pass` is what stops the two drifting.
    parser.add_argument("--body", required=True,
                        help=f"which planet these caps are for "
                             f"({', '.join(sorted(bodies.BODIES))})")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--north", action="store_true", help="render only the north cap")
    group.add_argument("--south", action="store_true", help="render only the south cap")
    parser.add_argument("--force", action="store_true",
                        help="render even when the freshness sidecar says the cap is current")
    parser.add_argument("--elev-only", action="store_true",
                        help="rebuild only the displacement textures, skipping the colour render")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    body = bodies.get(args.body)  # raises on an unknown name; never falls back to Earth
    # THE BODY BEFORE ANYTHING ELSE, and a refusal rather than a quiet exit 0. The planet pass already
    # declines to invoke this for such a body, so reaching here means an operator asked directly —
    # and the honest answer to "render Mars's caps" is that this body publishes none, not a pair of
    # discs in a palette it has never been given. Same rule the layer gates follow: ask the body, then
    # the disk, because the disk cannot tell "publishes none" from "the render died".
    if not body.renders_polar_caps:
        sys.exit(f"{body.name} publishes no polar caps — nothing to render. Its relief would shade "
                 f"from the same ramps as the tiles, so turning this on is a look decision: set "
                 f"renders_polar_caps on the body in pipeline/bodies.py once they are ratified.")
    # THE ARM BEFORE THE FIRST WARP, so an unregistered producer stops the pass in a second rather
    # than after a disc has been prepped.
    producer = producer_for(body)
    # Read once and threaded, exactly as the planet pass does it. This raises when the planet stage
    # never finished, so a cap can never be rendered from half a fusion — which used to be
    # indistinguishable from a planet that genuinely has no masks.
    rasters = planet_seam.declared(body)

    for wanted, grid in ((not args.south, cap_render.north_grid(body)),
                         (not args.north, cap_render.south_grid(body))):
        if not wanted:
            continue
        work = cap_render.cap_work_dir(grid.body)
        if not args.elev_only:
            recipe = producer.recipe(grid, rasters)
            sidecar = work / f"cap_{grid.name}_params.json"
            if not args.force and cap_render.cap_is_fresh(
                    recipe, cap_render.cap_assets(grid), sidecar,
                    cap_render.cap_sources(grid, rasters)):
                progress.stage(f"cap {grid.name} fresh -> skip")
            else:
                progress.stage(f"wrote {producer.render(grid, rasters)}")
                sidecar.write_text(recipe)  # AFTER the render, so a crash leaves the cap stale

        # Gated separately, and NOT behind the colour stage's `continue`: the displacement texture
        # reads the height warp alone. A look change must not drag it along, and an encoding change
        # must not drag the ~14 GB composite behind it.
        elev_recipe = cap_render.cap_elev_recipe(grid)
        elev_sidecar = work / f"cap_{grid.name}_elev_params.json"
        if not args.force and cap_render.cap_is_fresh(
                elev_recipe, [cap_render.cap_elev_asset(grid)], elev_sidecar,
                [planet_seam.vrt_path(grid.body, "heightfield")]):
            progress.stage(f"cap {grid.name} elevation fresh -> skip")
        else:
            progress.stage(f"wrote {cap_render.write_cap_elevation(grid)}")
            elev_sidecar.write_text(elev_recipe)
    served = cap_render.caps_public_dir(body)  # both poles of one body publish to one directory
    served.mkdir(parents=True, exist_ok=True)
    # The web contract, always current.
    (served / "caps.json").write_text(cap_render.caps_manifest(body) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
