"""The one way this project launches Blender, and the one place that decides its environment.

One launch shape rather than a kwarg at each call site. Duplicated launches are each correct alone
and nothing goes red, so one can acquire a setting the others never hear about: that is how `TMPDIR`
came to be missing from all three.

The temp directory is a memory decision, not a tidiness one. Cycles stages its tile buffer in the
system temp directory, which is tmpfs on the render box, so the buffer is held in RAM. Blender
removes that directory only on a clean exit, and the cgroup cap exists to kill a runaway render, so
the protection is what strands the file. The leak is invisible to the mechanism that caused it:
tmpfs is not charged to the render's cgroup, and the space comes back only by deleting the file.

Stdlib-only is not required here, unlike `render_seam`: Blender's interpreter never imports this
module, because this module is what starts it.
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

    Created, not merely named: a `TMPDIR` pointing at a directory that does not exist is an error
    nowhere in the chain, since Blender falls back to the system temp directory and renders
    perfectly, so naming it without creating it restores the defect in silence.

    `extra` layers on top of the inherited environment rather than replacing it, because Blender
    needs the caller's PATH, HOME and GPU variables to find its devices.
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
