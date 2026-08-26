"""Sweep ONE cap parameter across a ladder of values and archive each rung, for judging by eye.

The polar caps are the one surface with no cheap preview. A region can be re-composited from cached
layers in milliseconds, but a cap rung is a full composite per pole (~21 s each), and the only
honest way to pick a value is to look at the pair at full scale. This is the harness for that — the
browser-free pole loop behind `ice_relief_damp` and the cap's 8192 px texture size.

WHAT IT SWEEPS, one axis per run:
  * any `shade.KNOBS` key — the composite tunables the tiles and the caps share;
  * `quality` — the WebP encoder setting (`cap_render.CAP_WEBP_QUALITY`);
  * `px` — the NATIVE render size, which is a different question from the shipped rung ladder.
    `CAP_RUNGS` downsamples every rung from one 8192 render precisely so that `coast_dilate`,
    measured in pixels, bakes one coastline width at every size. A native `px` sweep re-bakes that
    line per rung, so coastlines across it are not like-for-like — which is the comparison the
    sweep is usually for.

THE INVARIANT, and the whole reason the two scripts this replaces were merged rather than kept: a
rung writes to the LIVE served path, so the tool must leave the shipped textures and their freshness
sidecars describing the same render. Both predecessors failed that, in opposite directions and both
without a symptom:

  * the knob ladder ended on a literal `0.0` that was the shipped value the day it was written and
    was `0.75` by the time anyone ran it again. A run therefore left damp-0.0 pixels on disk under a
    sidecar that still matched the shipped recipe — so `cap_is_fresh` reported them CURRENT, and the
    next production pass skipped rather than repairing them.
  * the size ladder relied on its last rung *being* the default, which is a comment rather than a
    mechanism. Its two rungs were `(8192, 85)` and `(CAP_PX, 85)`; when CAP_PX became 8192 the sweep
    silently collapsed into rendering the same cap twice.

So here the restore is a `finally`, and the shipped state is re-rendered and re-stamped explicitly
at the end rather than inferred from where the ladder happened to stop. Neither the ordering nor the
contents of a ladder can leave production lying.

Usage: GDAL_CACHEMAX=512 uv run python -m pipeline.tile.cap_ladder --body earth \
           --axis ice_relief_damp --values 1.0,0.75,0.5,0.0
"""
import argparse
import dataclasses
import os
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from pipeline import bodies, planet_seam
from pipeline.tile import cap_render, shade

os.environ.setdefault("GDAL_CACHEMAX", "512")

#: Axes that live on the grid rather than in a module, so a rung varies them by rebuilding the grid
#: instead of patching anything. Kept as a set so `sweepable_axes` can describe them uniformly.
GRID_AXES = frozenset({"px"})
#: Axes whose values are whole numbers. Everything in KNOBS is a float except the curve names, which
#: are not sweepable here — a curve is a branch, not a ladder.
INTEGER_AXES = frozenset({"px", "quality"})


def sweepable_axes() -> list[str]:
    """Every parameter this harness can ladder.

    DERIVED from KNOBS rather than listed, so a knob added to the composite becomes sweepable the day
    it lands — the alternative is a second list that goes stale exactly when someone needs it. The
    string-valued knobs are excluded because a ladder over `snow_curve` is a set of branches, and
    nothing here would interpolate or order them meaningfully.
    """
    numeric = [name for name, value in cast(dict[str, Any], shade.KNOBS).items()
               if isinstance(value, (int, float))]
    return sorted([*numeric, "quality", *GRID_AXES])


def parse_values(axis: str, raw: str) -> list[float]:
    """The `--values` list for one axis, typed by the axis rather than by how it was spelled.

    `px=4096.0` would be accepted by a bare `float()` and then reach `dataclasses.replace` as a
    float, giving a grid whose pixel count is not an integer — which gdalwarp's `-ts` would stringify
    into a command that fails halfway through a sweep rather than at the CLI.

    A fractional rung on an integer axis is REFUSED rather than rounded. Rounding would render at a
    size the caller did not ask for and archive it under the name they did, which is the one outcome
    a judging harness must never produce: the picture and its label disagreeing.
    """
    values = [part.strip() for part in raw.split(",") if part.strip()]
    if not values:
        raise ValueError(f"--values is empty; give at least one rung for {axis}")
    parsed = [float(value) for value in values]
    if axis in INTEGER_AXES:
        fractional = [value for value in parsed if not value.is_integer()]
        if fractional:
            raise ValueError(f"{axis} rungs must be whole numbers; got {fractional}")
    return parsed


@contextmanager
def swapped(axis: str, value: float) -> Iterator[None]:
    """Hold one shipped constant at `value` for the body of the `with`, and put it back afterwards.

    A CONTEXT MANAGER RATHER THAN AN ASSIGNMENT, which is the fix for the failure described at the
    top of this module: both predecessors assigned to the module and relied on a later rung to undo
    it, so a crash, a Ctrl-C, or simply a ladder that no longer ended on the default left the process
    — and the pixels it went on to write — running under a value nobody chose.

    Grid axes are a no-op here; they are varied by `grid_for_rung`, which builds a new frozen grid
    and so has nothing to restore.
    """
    if axis in GRID_AXES:
        yield
        return
    if axis == "quality":
        previous = cap_render.CAP_WEBP_QUALITY
        cap_render.CAP_WEBP_QUALITY = int(value)
        try:
            yield
        finally:
            cap_render.CAP_WEBP_QUALITY = previous
        return
    knobs = cast(dict[str, Any], shade.KNOBS)  # a TypedDict: indexable by a variable key only as dict
    if axis not in knobs:
        raise KeyError(f"unknown axis {axis!r}; sweepable: {', '.join(sweepable_axes())}")
    previous_knob = knobs[axis]
    knobs[axis] = value
    try:
        yield
    finally:
        knobs[axis] = previous_knob


def grid_for_rung(grid: cap_render.CapGrid, axis: str, value: float) -> cap_render.CapGrid:
    """This rung's grid — the shipped one, unless the axis is a grid field."""
    return dataclasses.replace(grid, px=int(value)) if axis == "px" else grid


def ladder_dir(body: bodies.Body, axis: str) -> Path:
    """Where a sweep's rungs are archived: under the body's cap work tree, one directory per axis.

    An intermediate, so it follows the (relocatable) data store rather than the checkout — the same
    split `cap_work_dir` and `caps_public_dir` make.
    """
    return cap_render.cap_work_dir(body) / "ladder" / axis


def render_rung(body: bodies.Body, axis: str, value: float) -> list[Path]:
    """Render both caps at one rung and archive the pair; return the archived files.

    The archived name carries the axis and the value, because a directory of `cap_north.webp` copies
    is unjudgeable — and the extension is the one the encoder actually wrote. The predecessor copied
    a WebP to a `.png` name, which most viewers sniff past and no tool complains about.
    """
    out = ladder_dir(body, axis)
    out.mkdir(parents=True, exist_ok=True)
    # The seam's own answer, not an assumed full planet: a ladder run on a body with no masks must
    # paint the same all-land cap the production pass would, or the rung being judged is not the
    # picture that ships.
    rasters = planet_seam.declared(body)
    archived: list[Path] = []
    with swapped(axis, value):
        for grid, render in ((cap_render.north_grid(body), cap_render.render_cap_north),
                             (cap_render.south_grid(body), cap_render.render_cap_south)):
            rung_grid = grid_for_rung(grid, axis, value)
            started = time.monotonic()
            asset = render(rung_grid, rasters)
            seconds = time.monotonic() - started
            copy = out / f"cap_{grid.name}_{axis}_{value:g}{asset.suffix}"
            shutil.copy2(asset, copy)
            archived.append(copy)
            print(f"{grid.name} {axis}={value:g}: {seconds:5.1f} s, "
                  f"{asset.stat().st_size / 1e6:.2f} MB -> {copy}", flush=True)
    return archived


def restore_live_caps(body: bodies.Body) -> None:
    """Put the served textures and their sidecars back to the SHIPPED look, unconditionally.

    Re-rendered rather than assumed: a rung writes straight into `caps_public_dir`, so whatever the
    ladder painted last is what the site would serve. Costs one extra pair (~42 s) against a sweep
    that already runs for minutes, and in exchange the tool is correct for any ladder rather than
    only for one that remembers to end on the default.

    The sidecars are stamped AFTER that render, so the recipe on disk describes the pixels beside it,
    and the next production pass skips a ~14 GB composite instead of repeating it.
    """
    rasters = planet_seam.declared(body)
    for grid, render in ((cap_render.north_grid(body), cap_render.render_cap_north),
                         (cap_render.south_grid(body), cap_render.render_cap_south)):
        render(grid, rasters)
        sidecar = cap_render.cap_work_dir(body) / f"cap_{grid.name}_params.json"
        sidecar.write_text(cap_render.cap_recipe(grid, rasters))
    served = cap_render.caps_public_dir(body)
    served.mkdir(parents=True, exist_ok=True)
    (served / "caps.json").write_text(cap_render.caps_manifest(body) + "\n")
    print("restored: live caps re-rendered at the shipped values, sidecars stamped", flush=True)


def build_parser() -> argparse.ArgumentParser:
    """The CLI, split out of `main` so its contract is testable without rendering a cap — the same
    split `cap_pass.build_parser` makes, and for the same reason."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    # Required and defaultless, matching the cap and planet passes. A ladder writes into a body's
    # served directory, so an omitted body here would sweep one planet's knob onto another's assets.
    parser.add_argument("--body", required=True,
                        help=f"which planet's caps to sweep ({', '.join(sorted(bodies.BODIES))})")
    parser.add_argument("--axis", required=True,
                        help="the parameter to ladder; one of: " + ", ".join(sweepable_axes()))
    parser.add_argument("--values", required=True,
                        help="comma-separated rungs, e.g. 1.0,0.75,0.5,0.0")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    body = bodies.get(args.body)  # raises on an unknown name; never falls back to Earth
    if args.axis not in sweepable_axes():
        raise SystemExit(f"unknown axis {args.axis!r}; sweepable: {', '.join(sweepable_axes())}")
    values = parse_values(args.axis, args.values)

    try:
        for value in values:
            render_rung(body, args.axis, value)
    finally:
        # In the `finally` so an interrupted sweep still hands production back a consistent pair.
        # This is the half both predecessors left to chance.
        restore_live_caps(body)
    print(f"ladder archived under {ladder_dir(body, args.axis)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
