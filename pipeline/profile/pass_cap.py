"""How much memory a planet pass may take, sized from the body rather than from Earth.

WHY THIS IS NOT ONE CONSTANT IN THE SHELL. `run_pass.sh` capped every run at 16 G, and that number
is Earth's: the pass ENDS by invoking `cap_render` as a subprocess, which inherits the scope's
cgroup and peaks at 14.3 GB north / 13.9 GB south on 8192 squared float arrays. A body with
`renders_polar_caps = False` never reaches that stage at all, so on such a body the 16 G is
unbacked rather than protective — and the harness's own `MemAvailable` preflight then refuses to
start a pass the box could comfortably have run. That refusal is the failure this module exists to
remove: measured on this box with a browser open, `MemAvailable` sits near 15 GiB, which clears
every cap Mars actually needs and misses the one it does not.

THE FLOOR IS THE PROJECT'S STANDING CAP, NOT A NEW NUMBER. 12 G is what every heavy job here runs
under; the pass was raised above it for the caps stage and for nothing else. Dropping back to it
for a capless body also restores a tripwire the raise knowingly gave up — 12 G was an accidental
guard on composite footprint, and a regression there currently hides until 16 G.

WHAT THE MEASUREMENTS SAY, so the two numbers are traceable rather than chosen:

- Earth, z8, `--tiles`: the composite peaks at 10.55 GiB and the caps at ~14.3 GB. 16 G.
- Mars, z6, `--tiles`, cold and end to end: summed per-process `VmHWM` **4.01 GiB**, the composite
  worker holding 2.90 GiB of it. Read `VmHWM`, not the cgroup's `memory.peak` — that reported
  8.30 GiB for the same pass, of which 4.29 GiB was reclaimable page cache. 12 G leaves 3x.

THE TILING RUN'S OWN JUSTIFICATION IS WEAKER THAN THE CAPS ONE, AND IT IS WORTH SAYING SO. With
`--tiles` the peak stage becomes `gdal raster tile`, whose workers each inherit `GDAL_CACHEMAX`;
that arithmetic is Earth-shaped but has never actually been measured, where Mars's whole pass has.
So this returns one cap per body rather than one per run label: a measured planet is sized off its
measurement, and an unmeasured stage does not get to out-vote a number taken from a real run.

NO FALLBACK, and it is the same rule `palette.look_for` states for the ramp. A body that quietly
inherited Earth's cap would run — every pass would simply be capped somewhere arbitrary — and
nothing would ever name it. `bodies.get` raises on an unknown name, so this does too, by delegating.
"""

import sys

from pipeline import bodies
from pipeline.tile import shade_planet

#: The cap a pass needs when it will render polar caps, in GiB. Set by `cap_render`'s measured
#: 14.3 GB peak plus headroom, and reached through the scope's cgroup because `shade_planet`
#: invokes that stage as a subprocess.
CAP_RENDERING_GIB = 16

#: The cap a pass needs when it will not, in GiB. The project's standing cap for any heavy job.
STANDING_GIB = 12


def pass_memory_cap_gib(body: bodies.Body) -> int:
    """The cgroup cap this body's pass may take, in GiB.

    Derived from `renders_polar_caps` rather than held as a per-body number, because that field
    already answers the only question the cap turns on and a second field would be free to
    disagree with it. A body that starts publishing caps gets the headroom by construction, on the
    same commit that turns them on.
    """
    return CAP_RENDERING_GIB if body.renders_polar_caps else STANDING_GIB


def cap_for_argv(argv: list[str]) -> int:
    """The cap for a pass invoked with `argv`, parsed by the pass's OWN parser.

    Sharing `shade_planet.build_parser` rather than re-reading `--body` in shell is the point: the
    harness forwards this exact argv to that module moments later, so a second spelling of the
    grammar is a second thing to keep in step. It also makes the harness honour its own documented
    contract EARLIER — `--body` is required, and until now a run that omitted it cleared the
    preflight, opened a cgroup scope and only then died inside Python.
    """
    return pass_memory_cap_gib(bodies.get(shade_planet.build_parser().parse_args(argv).body))


def main() -> None:
    """Print the cap in GiB, for `run_pass.sh` to read. Errors go to stderr via argparse."""
    print(cap_for_argv(sys.argv[1:]))


if __name__ == "__main__":
    main()
