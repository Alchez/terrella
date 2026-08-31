"""Render a body's polar caps: ask the freshness question, render, publish the manifest.

A DISC IS BUILT TO MATCH THE TILES IT FEATHERS INTO, so it is raytraced off the same rig. Anything
painting one differently is a visible step at the crossfade.

`cap_raytrace` holds the render and `cap_render` the grid, the warps, the meridian rotation and the
rung ladder that both it and this pass read.

    GDAL_CACHEMAX=512 uv run python -m pipeline.tile.cap_pass --body earth
"""
import argparse
import sys

from pipeline import bodies, planet_seam, progress
from pipeline.tile import cap_raytrace, cap_render


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
            recipe = cap_raytrace.params(grid, rasters)
            sidecar = work / f"cap_{grid.name}_params.json"
            if not args.force and cap_render.cap_is_fresh(
                    recipe, cap_render.cap_assets(grid), sidecar,
                    cap_render.cap_sources(grid, rasters)):
                progress.stage(f"cap {grid.name} fresh -> skip")
            else:
                progress.stage(f"wrote {cap_raytrace.render(grid, rasters)}")
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
