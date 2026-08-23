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
5.91 GiB; it is NOT backed by Earth, whose composite alone peaks at 12.56 GiB. So "the pass was
raised above 12 for the caps stage" is false as stated: Earth exceeds 12 before the caps are
reached. See `STANDING_GIB` for what that costs, which today is nothing.

WHAT THE MEASUREMENTS SAY, so the two numbers are traceable rather than chosen. PROCESS.md § Memory
is the authority and holds the method; these are its figures, not a second reading:

- The metric is PEAK INSTANTANEOUS SUMMED RSS, which is the only one of the three that answers
  "did it fit". The cgroup's `memory.peak` is charged for reclaimable page cache, and summed
  `VmHWM` adds lifetime high-water marks across children that never coexisted (a Mars pass sums to
  19.03 GiB under a 16 G cap that never fired). Two figures this module used to carry were taken
  the wrong way and are retired there: Earth's composite at 10.55 GiB, and Mars at 4.01 GiB.
- Earth at z8: `cap_render` **14.41 GiB** · composite **12.56 GiB** · tile cut **3.74 GiB**.
- Mars at z7: caps **8.85 GiB** · ice alpha **5.91 GiB** · composite **4.37 GiB** · cut **2.95 GiB**.

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
#: **IT WOULD NOT BACK A CAPLESS BODY AT EARTH'S SCALE**, whose composite peaks 12.56 GiB, and the
#: field this branch turns on carries nothing about scale. That is inert today, because both
#: registered bodies render caps and no run takes this branch, and it is the question to answer
#: before one does rather than a number to guess at now. `MEMORY_CAP_OVERRIDE_GIB` is the escape
#: hatch in the meantime, and it announces itself.
STANDING_GIB = 12

#: The ceiling any heavy job on this box runs under, in GiB. **A RATIFIED POLICY, NOT A
#: MEASUREMENT**, which is what separates it from the two numbers above: those are sized off real
#: passes, this is Rohan's call about how much of a 30 GiB box a single job may take before the
#: desktop is at risk, and it holds whatever a given job happens to peak at. Anything that needs a
#: cap and has no measured pass behind it takes this one -- the hero batch is the first such caller,
#: and it previously derived `0.85 * MemTotal`, which scales the blast radius with the machine
#: instead of bounding it. A host-derived cap also hides a real regression: the base grid needs
#: 17.0 GB for the largest hero and died loudly at 16 G here, where a bigger box would have passed.
HEAVY_JOB_GIB = 16


def pass_memory_cap_gib(body: bodies.Body) -> int:
    """The cgroup cap this body's pass may take, in GiB.

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
      producer could matter: the composite's footprint is this process's, while the raytrace's sits
      in a Blender subprocess with a mosaic writer beside it. Nothing has run one. That is a gap in
      the measurements rather than a missing branch, and `STANDING_GIB` records the other half of
      the same gap.
    """
    return CAP_RENDERING_GIB if body.renders_polar_caps else STANDING_GIB


def cap_for_argv(argv: list[str]) -> int:
    """The cap for a pass invoked with `argv`, parsed by the pass's OWN parser.

    Sharing `planet_pass.build_parser` rather than re-reading `--body` in shell is the point: the
    harness forwards this exact argv to that module moments later, so a second spelling of the
    grammar is a second thing to keep in step. It also makes the harness honour its own documented
    contract EARLIER — `--body` is required, and until now a run that omitted it cleared the
    preflight, opened a cgroup scope and only then died inside Python.
    """
    return pass_memory_cap_gib(bodies.get(planet_pass.build_parser().parse_args(argv).body))


def main() -> None:
    """Print the cap in GiB, for `run_pass.sh` to read. Errors go to stderr via argparse."""
    print(cap_for_argv(sys.argv[1:]))


if __name__ == "__main__":
    main()
