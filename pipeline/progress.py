"""One marker for every stage boundary a long pass crosses, so a watcher needs no vocabulary.

A planet pass runs for a night and reports itself by printing. Something has to decide which of
those lines are worth waking a reader for, and until this module that decision lived in the
WATCHER: `pipeline/profile/watchdog.py` held a regex of the phrasings it expected to see.

That is the wrong direction, and it failed in both of the ways this repo's seam rule predicts. The
markers are authored in six modules by whoever wrote each stage, in six phrasings, and one of them
carries a per-body number, so the regex went stale by construction: four of Earth's five surface
layers and both of the things Mars does that Earth does not were unreported for as long as they
have existed, silently, because an unmatched line looks exactly like a stage that has not started.
Then a second producer arrived printing nothing the regex knew at all.

So the pass DECLARES its stage boundaries and the watcher matches one marker. A new body, producer
or layer is reported the day it is written, because being reported is what `stage()` is for rather
than something a second file has to be taught. The marker is deliberately unlovely and typeable:
`grep '::stage::' pass.log` is the whole per-stage story of a night, and nothing else emits it.

WHAT IS NOT A STAGE is as much of the contract as what is. The watchdog EXITS on a match so the
harness can wake, so a marker inside a loop costs one wake-up per iteration: the composite's
every-20-windows row count fires ~18 times saying nothing new, and the raytrace's per-block line
would fire 4,096 times on Earth. Those stay ordinary prints, and progress WITHIN a stage is read
from the producer's own status document instead. A boundary is a stage; a step is not.

Stdlib-only and dependency-free on purpose: every module in the pass imports it, including ones
that run under Blender's interpreter.
"""

#: The one string a watcher matches. Prefixed rather than appended so a stage boundary is scannable
#: down the left edge of a log that also carries per-block lines and wall-clock stamps.
STAGE_MARKER = "::stage::"


def marked(message: str) -> str:
    """`message` with the stage marker on it, for a caller that does its own printing.

    `block_render` stamps its own lines with a local wall clock before printing them, so it needs
    the marked text rather than the print.
    """
    return f"{STAGE_MARKER} {message}"


def stage(message: str) -> None:
    """Announce a stage boundary.

    Flushed, because the pass is read live through a pipe: an unflushed marker arrives at the
    watcher whenever the buffer happens to fill, which on a stage that then runs for 62 minutes is
    indistinguishable from a stage that never started.
    """
    print(marked(message), flush=True)
