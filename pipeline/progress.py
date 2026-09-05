"""One marker for every stage boundary a long pass crosses, so a watcher needs no vocabulary.

The pass declares its boundaries and `profile/watchdog.py` matches the one marker, rather than
holding a list of the phrasings six modules happen to use. `grep '::stage::' pass.log` is the whole
per-stage story of a night, and nothing else emits it.

What is not a stage is as much of the contract as what is. The watchdog exits on a match so the
harness can wake, so a marker inside a loop costs one wake-up per iteration, and the raytrace's
per-block line would fire 4,096 times on Earth. Those stay ordinary prints, and progress within a
stage is read from the producer's own status document. A boundary is a stage; a step is not.

Stdlib-only on purpose: every module in the pass imports it, including ones that run under
Blender's interpreter.
"""

#: The one string a watcher matches. Prefixed rather than appended so a stage boundary is scannable
#: down the left edge of a log that also carries per-block lines and wall-clock stamps.
STAGE_MARKER = "::stage::"


def marked(message: str) -> str:
    """`message` with the stage marker on it, for a caller that prints for itself.

    `block_render` stamps its lines with a local wall clock first, so it needs the text not the print.
    """
    return f"{STAGE_MARKER} {message}"


def stage(message: str) -> None:
    """Announce a stage boundary.

    Flushed: the pass is read live through a pipe, and an unflushed marker on a stage that then runs
    for an hour is indistinguishable from a stage that never started.
    """
    print(marked(message), flush=True)
