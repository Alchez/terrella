"""How much memory a planet pass may take, sized from the body rather than from Earth.

WHY THIS IS NOT ONE CONSTANT IN THE SHELL. `run_pass.sh` capped every run at 16 G, and that number
is Earth's: the pass ENDS by invoking `cap_render` as a subprocess, which inherits the scope's
cgroup and peaks at 14.3 GB north / 13.9 GB south on 8192 squared float arrays. A body with
`renders_polar_caps = False` never reaches that stage at all, so on such a body the 16 G is
unbacked rather than protective — and the harness's own `MemAvailable` preflight then refuses to
start a pass the box could comfortably have run. That refusal is the failure this module exists to
remove: measured on this box with a browser open, `MemAvailable` sits near 15 GiB, which clears
every cap Mars actually needs and misses the one it does not.

THE FLOOR IS A SMALLER PLANET'S MEASUREMENT, NOT A SMALLER STAGE'S, and that distinction is the one
thing to carry away from this file. 12 G is backed by Mars, whose heaviest non-cap stage peaks at
5.91 GiB.

THE WITNESS THAT SAID EARTH NEEDS MORE IS DELETED, AND NOTHING HAS REPLACED IT. That sentence read
"it is NOT backed by Earth, whose composite alone peaks at 12.56 GiB", which made "the pass was
raised above 12 for the caps stage" false as stated. The compositor is gone and the raytraced
`block_render` that replaced it has NO memory figure in PROCESS on either body, so the claim is
unsupported rather than either true or false. **Read that as a measurement nobody has taken, never
as room to lower a cap.** See `STANDING_GIB`, which is inert today whichever way it resolves.

WHAT THE MEASUREMENTS SAY, so the two numbers are traceable rather than chosen. PROCESS.md § Memory
is the authority and holds the method; these are its figures, not a second reading:

- The metric is PEAK INSTANTANEOUS SUMMED RSS, which is the only one of the three that answers
  "did it fit". The cgroup's `memory.peak` is charged for reclaimable page cache, and summed
  `VmHWM` adds lifetime high-water marks across children that never coexisted (a Mars pass sums to
  19.03 GiB under a 16 G cap that never fired). Two figures this module used to carry were taken
  the wrong way and are retired there: Earth's composite at 10.55 GiB, and Mars at 4.01 GiB.
- Earth at z8: `cap_render` **14.41 GiB** · tile cut **3.74 GiB**, and the raytraced producer
  between them is unmeasured. The composite that stood at **12.56 GiB** here no longer runs.
- Mars at z7: caps **8.85 GiB** · ice alpha **5.91 GiB** · cut **2.95 GiB**, the deleted composite
  having been **4.37 GiB**.

THE CAPS ARE THE PEAK ON BOTH BODIES, which is what makes one field enough to size this. They are
also the only stage a body can decline entirely, so the field that says whether they run is the
field that says which number applies.

THE TILING RUN'S OWN JUSTIFICATION IS WEAKER THAN THE CAPS ONE, AND IT IS WORTH SAYING SO. With
`--tiles` the peak stage was expected to be `gdal raster tile`, whose workers each inherit
`GDAL_CACHEMAX`. Measured, it is the LIGHTEST of the three Earth stages at 3.74 GiB across the whole
cut, so that arithmetic is an upper bound the cut never reaches and is not what sizes anything. One
cap per body rather than one per run label follows: both labels run the caps stage.

NO FALLBACK, and it is the same rule `palette.look_for` states for the ramp. A body that quietly
inherited Earth's cap would run — every pass would simply be capped somewhere arbitrary — and
nothing would ever name it. `bodies.get` raises on an unknown name, so this does too, by delegating.
"""

import sys

from pipeline import bodies
from pipeline.tile import planet_pass

#: The cap a pass needs when it will render polar caps, in GiB. Sized off `cap_render`'s measured
#: 14.41 GiB peak, so the headroom is 1.11x rather than the 1.20x an older anon-RSS reading of the
#: same stage (14.3 GB north / 13.9 GB south) implied. Reached through the scope's cgroup because
#: the planet pass invokes that stage as a subprocess, which inherits it.
CAP_RENDERING_GIB = 16

#: The cap a pass needs when it will not, in GiB, and it is a MEASURED PLANET rather than a measured
#: stage: Mars's heaviest non-cap stage is the ice alpha at 5.91 GiB, so 12 G leaves 2.0x there.
#:
#: **IT MAY NOT BACK A CAPLESS BODY AT EARTH'S SCALE**, and the field this branch turns on carries
#: nothing about scale. The stage that once settled this was the composite at 12.56 GiB and it is
#: deleted, so the answer is now unmeasured rather than known. That is inert today, because both
#: registered bodies render caps and no run takes this branch, and it is the question to answer
#: before one does rather than a number to guess at now. `MEMORY_CAP_OVERRIDE_GIB` is the escape
#: hatch in the meantime, and it announces itself.
#:
#: THE BRANCH BELOW IS WHAT MAKES THAT PARAGRAPH ACT RATHER THAN WARN. It was a comment for as long
#: as it took `tests/test_run_pass_preflight` to pin `limit_gib` on a capless body built off EARTH,
#: which is precisely the case this paragraph calls unbacked -- so the file describing the gap and
#: the file asserting there was none were the same pair of hands.
STANDING_GIB = 12

#: The deepest grid `STANDING_GIB` was measured on: Mars's z7, a 65536 square raster.
#:
#: A LITERAL, NOT `bodies.MARS.tile_max_zoom`, and the difference is the whole guard. Read off the
#: registry it would follow Mars wherever it went, so cutting Mars one level deeper would re-declare
#: 12 as backing a grid four times the area without anyone measuring anything -- a number moving
#: because a different body moved. `test_the_measured_zoom_is_still_the_one_mars_actually_runs`
#: holds the two together, so that change lands as a request to re-measure.
#:
#: WHY ZOOM AND NOT `block_plan.grid_px`, which is the quantity actually meant. This module is the
#: preflight: `run_pass.sh` runs it as a subprocess before any scope opens, and `block_plan` imports
#: numpy behind it. `grid_px` is `CELL_PX << tile_max_zoom`, so the orderings are identical, and the
#: equivalence is asserted in the tests rather than assumed here.
STANDING_MEASURED_MAX_ZOOM = 7

#: The ceiling any heavy job on this box runs under, in GiB. **A RATIFIED POLICY, NOT A
#: MEASUREMENT**, which is what separates it from the two numbers above: those are sized off real
#: passes, this is Rohan's call about how much of a 30 GiB box a single job may take before the
#: desktop is at risk, and it holds whatever a given job happens to peak at. Anything that needs a
#: cap and has no measured pass behind it takes this one -- the hero batch is the first such caller,
#: and it previously derived `0.85 * MemTotal`, which scales the blast radius with the machine
#: instead of bounding it. A host-derived cap also hides a real regression: the base grid needs
#: 17.0 GB for the largest hero and died loudly at 16 G here, where a bigger box would have passed.
HEAVY_JOB_GIB = 16


def limit_gib(body: bodies.Body) -> int:
    """The cgroup limit this body's pass may take, in GiB.

    Derived from `renders_polar_caps` rather than held as a per-body number, so a body that starts
    publishing caps gets the headroom by construction on the same commit that turns them on.

    **THE ARGUMENT THAT USED TO SIT HERE WAS FALSIFIED BY THE COMMIT THAT ADDED `planet_producer`.**
    It said the field "already answers the only question the cap turns on, and a second field would
    be free to disagree with it" -- which was a reason not to add one, made while the registry had
    one field the cap could plausibly read. There are two now, so the useful statement is why this
    still reads only the first:

    - **The producer does not enter, because the caps stage is producer-independent.** `cap_render`
      is a separate subprocess compositing the same sources over the same AEQD discs whichever
      producer filled `planet_rgb.tif`, and on a capped body it is the peak (14.41 GiB on Earth,
      8.85 GiB on Mars). So a capped body wants 16 either way, and adding a producer branch would
      be a branch whose arms are equal.
    - **A capless RAYTRACED body is genuinely unmeasured**, and would be the first case where the
      producer could matter: the composite's footprint was this process's, while the raytrace's sits
      in a Blender subprocess with a mosaic writer beside it. Nothing has run one. That is a gap in
      the measurements rather than a missing branch, and `STANDING_GIB` records the other half of
      the same gap.

    THE CAPLESS BRANCH IS SPLIT BY SCALE, because `STANDING_GIB` is a measured PLANET and a body
    can be capless at any size. Mars's z7 is where the 5.91 GiB came from; a capless body deeper
    than that is outside the range of that measurement rather than inside it with less headroom,
    and the difference matters because the two arms fail in opposite directions. Too high risks the
    box; too low kills the pass inside its own cgroup with nothing on record saying why, which is
    the failure that reads as a bug in the stage.

    SO THE UNMEASURED CASE TAKES THE RATIFIED CEILING, WHICH IS A POLICY AND NOT A GUESS. It says
    "nobody has measured this body, so take the most the box allows", and `run_pass.sh`'s
    `MemAvailable` preflight then refuses honestly on a box that cannot back it. Returning
    `STANDING_GIB` there would instead clear that preflight and hand the pass a cap sized for a
    quarter of its raster. Announced rather than raised, so `MEMORY_CAP_OVERRIDE_GIB` -- which
    `run_pass.sh` reads AFTER this resolver -- stays reachable; raising would abort the run one line
    before the escape hatch this module's own note promises.
    """
    if body.renders_polar_caps:
        return CAP_RENDERING_GIB
    if body.tile_max_zoom > STANDING_MEASURED_MAX_ZOOM:
        # STDERR, NEVER STDOUT: `main` prints the cap on stdout and `run_pass.sh` reads that as the
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
