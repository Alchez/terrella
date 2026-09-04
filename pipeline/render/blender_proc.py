"""The one way this project launches Blender, and the one place that decides its environment.

WHY A MODULE RATHER THAN A KWARG AT EACH CALL. Two callers spelled the identical
`subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)`, and a third built
a Blender command for `batch` to run. Nothing was red, because each was correct on its own; what a
duplicated launch shape costs is that one of them can acquire a setting the others never hear about,
which is exactly how `TMPDIR` came to be missing from all three.

THE TEMPORARY DIRECTORY IS A MEMORY DECISION AND NOT A TIDINESS ONE. Cycles stages its tile buffer
in the system temp directory, which is tmpfs on this project's render box, so the buffer is held in
RAM rather than on disk. Blender removes that directory only on a CLEAN exit, and the cgroup cap
exists precisely to KILL a runaway render, so the protection is what strands the file. The leak is
then invisible to the mechanism that caused it: tmpfs is not charged to the render's cgroup, so a
memory limit cannot see it, and the space is reclaimed only by deleting the file by hand.

`stdlib only` is not required here, unlike `render_seam`: Blender's own interpreter never imports
this module, because this module is what starts Blender.
"""

import os
import subprocess
from pathlib import Path

from pipeline import paths


def temp_dir() -> Path:
    """Where Blender and Cycles may write, which must be a real filesystem.

    Derived at call time from `paths.DATA`, per that module's rule: a module-level constant would
    freeze the store at import and a relocated `MAPS_DATA` would move some paths and not this one.
    """
    return paths.DATA / "tmp" / "blender"


def env(**extra: str) -> dict[str, str]:
    """The environment a Blender subprocess is launched with.

    CREATED, NOT MERELY NAMED. A `TMPDIR` pointing at a directory that does not exist is not an
    error anywhere in the chain — Blender falls back to the system temp directory and renders
    perfectly — so naming it without creating it restores the defect in silence.

    `extra` is layered on top rather than replacing the inherited environment, because Blender needs
    the caller's PATH, HOME and GPU variables to find its devices at all.
    """
    directory = temp_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return {**os.environ, "TMPDIR": str(directory), **extra}


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Launch Blender and hand the whole result back, failures included.

    `check=False` and `capture_output=True` are the callers' contract rather than a default: both
    read `returncode`, `stdout` and `stderr` off the result to raise their own diagnosis, which is
    what turns an OOM kill into a named block rather than a bare traceback in the middle of a night.
    """
    return subprocess.run(command, cwd=paths.ROOT, capture_output=True, text=True,
                          check=False, env=env())
