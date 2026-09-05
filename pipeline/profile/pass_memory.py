"""How much memory a planet pass may take, sized from the body rather than from Earth.

Not one constant in the shell, because the peak stage is one a body can decline. The pass ends by
invoking `cap_render` as a subprocess, which inherits the scope's cgroup and is the heaviest stage
on both bodies. A body with `renders_polar_caps = False` never reaches it, so a flat 16 G is
unbacked rather than protective there, and `run_pass.sh`'s `MemAvailable` preflight then refuses a
pass the box could have run: available memory sits near 15 GiB here with a browser open.

The floor is a smaller planet's measurement, not a smaller stage's. That is the distinction to carry
away: `STANDING_GIB` is backed by Mars entire, not by picking Earth's lightest stage.

PROCESS.md § Memory is the authority for every stage figure and holds the method. Each constant below
carries only the one measurement that sizes it, pinned there by
`test_each_cap_cites_the_figure_PROCESS_sizes_it_from`.

No fallback, the rule `palette.look_for` states for the ramp: a body quietly inheriting Earth's cap
would run capped somewhere arbitrary with nothing naming it. `bodies.get` raises on an unknown name,
so this does too, by delegating.
"""

import sys

from pipeline import bodies
from pipeline.tile import planet_pass

#: The cap a pass needs when it will render polar caps, in GiB. Sized off `cap_render`'s measured
#: 14.41 GiB peak on Earth, so the headroom is 1.11x. Reached through the scope's cgroup, since the
#: pass invokes that stage as a subprocess which inherits it.
CAP_RENDERING_GIB = 16

#: The cap a pass needs when it will not, in GiB: a measured planet rather than a measured stage,
#: Mars's heaviest non-cap stage being the ice alpha at 5.91 GiB, so this leaves 2.0x there.
#:
#: It does not back a capless body at Earth's scale, and `renders_polar_caps` carries nothing about
#: scale. Read that as a measurement nobody has taken, never as room to lower a cap. Inert today,
#: since both registered bodies render caps, and the branch in `limit_gib` refuses the case rather
#: than guessing at it. `MEMORY_CAP_OVERRIDE_GIB` is the escape hatch meanwhile.
STANDING_GIB = 12

#: The deepest grid `STANDING_GIB` was measured on: Mars's z7, a 65536 square raster.
#:
#: A literal, not `bodies.MARS.tile_max_zoom`, and the difference is the whole guard: read off the
#: registry it would follow Mars wherever it went, so cutting Mars one level deeper would re-declare
#: 12 as backing four times the area with nobody measuring anything.
#: `test_the_measured_zoom_is_still_the_one_mars_actually_runs` holds the two together, so that
#: change lands as a request to re-measure.
#:
#: Zoom rather than `block_plan.grid_px`, which is the quantity actually meant, because this module
#: is the preflight `run_pass.sh` runs before any scope opens and `block_plan` imports numpy behind
#: it. `grid_px` is `CELL_PX << tile_max_zoom`, so the orderings match; the tests assert that.
STANDING_MEASURED_MAX_ZOOM = 7

#: The ceiling any heavy job on this box runs under, in GiB. A ratified policy, not a measurement,
#: which is what separates it from the two above: a maintainer's call about how much of a 30 GiB box
#: one job may take before the desktop is at risk, holding whatever that job happens to peak at.
#: Anything needing a cap with no measured pass behind it takes this one.
#:
#: Do not derive it from the host, as `0.85 * MemTotal` once did: that scales the blast radius with
#: the machine instead of bounding it, and it hides real regressions. The base grid needs 17.0 GB
#: for the largest hero and died loudly at 16 G here, where a bigger box would have passed silently.
HEAVY_JOB_GIB = 16


def limit_gib(body: bodies.Body) -> int:
    """The cgroup limit this body's pass may take, in GiB.

    Derived from `renders_polar_caps` rather than held as a per-body number, so a body that starts
    publishing caps gets the headroom by construction on the same commit that turns them on.

    The capless branch is split by scale, because `STANDING_GIB` is a measured planet and a body can
    be capless at any size. Mars's z7 is where the 5.91 GiB came from, so a capless body deeper than
    that is outside that measurement's range rather than inside it with less headroom. The arms fail
    in opposite directions: too high risks the box, too low kills the pass inside its own cgroup
    with nothing on record saying why, which reads as a bug in the stage.

    The unmeasured case therefore takes the ratified ceiling, a policy rather than a guess: nobody
    has measured this body, so take the most the box allows and let `run_pass.sh`'s `MemAvailable`
    preflight refuse honestly if it cannot back it. Returning `STANDING_GIB` would clear that
    preflight and hand the pass a cap sized for a quarter of its raster. Announced rather than
    raised, because `run_pass.sh` reads `MEMORY_CAP_OVERRIDE_GIB` after this resolver and raising
    would abort one line before that escape hatch.
    """
    if body.renders_polar_caps:
        return CAP_RENDERING_GIB
    if body.tile_max_zoom > STANDING_MEASURED_MAX_ZOOM:
        # Stderr, never stdout: `main` prints the cap on stdout and `run_pass.sh` reads that as the
        # number, so a note written there would be captured into the shell's `MEMORY_CAP_GIB`.
        print(f"\n  !! THIS BODY'S CAP IS UNMEASURED. {body.name} renders no polar caps, so the "
              f"standing\n     {STANDING_GIB} GiB would normally apply -- but that figure is "
              f"Mars's z{STANDING_MEASURED_MAX_ZOOM} grid, and this body\n     cuts to "
              f"z{body.tile_max_zoom}, whose raster is "
              f"{4 ** (body.tile_max_zoom - STANDING_MEASURED_MAX_ZOOM)}x the area. Falling back to "
              f"the ratified\n     ceiling of {HEAVY_JOB_GIB} GiB, which is a policy rather than a "
              f"measurement of this body.\n", file=sys.stderr, flush=True)
        return HEAVY_JOB_GIB
    return STANDING_GIB


def limit_for_argv(argv: list[str]) -> int:
    """The limit for a pass invoked with `argv`, parsed by the pass's OWN parser.

    Sharing `planet_pass.build_parser` rather than re-reading `--body` in shell is the point: the
    harness forwards this exact argv to that module moments later, so a second spelling of the
    grammar is a second thing to keep in step. It also makes the harness honour its own documented
    contract EARLIER — `--body` is required, and until now a run that omitted it cleared the
    preflight, opened a cgroup scope and only then died inside Python.
    """
    return limit_gib(bodies.get(planet_pass.build_parser().parse_args(argv).body))


def main() -> None:
    """Print the limit in GiB, for `run_pass.sh` to read. Errors go to stderr via argparse."""
    print(limit_for_argv(sys.argv[1:]))


if __name__ == "__main__":
    main()
