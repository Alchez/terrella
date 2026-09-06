"""What the look layers actually compute, on a fixture, so a changed curve cannot pass unnoticed.

`render_fingerprint` records the constants a stage was authored with, which answers "did a setting
move" and can never answer "did a pixel move": the curve those constants are fed into is not a
constant. Its own docstring measures the hole, `seaice.ice_alpha` from smoothstep to linear moving
every sea-ice pixel on Earth by up to 20.3 DN of white coverage while leaving that file identical.

This closes most of that hole by running the shipped code instead of describing it. Production does
the calling: the producer comes out of `producer_for`, so the function, its arguments, its defaults
and the branch that selects it are all the shipped ones. That is what makes it immune to the defect
that deleted the curve fingerprint, where a hand-written sample was free to call a transform
differently from production and eight rows recorded a law nobody ships.
→ HISTORY, *the curve fingerprint is deleted the day it landed*.

A contributor with no data store, no GPU and no Blender can run this: 44 of the 45 entry-point
stages import no `bpy` at all, and this layer is folded into a PNG before Cycles is ever launched.

What it does not reach, stated so nobody reads a green as more than it is:

  * `scene_build.py`, the one stage that does import `bpy`. The rig, the ramps, the sun and the
    exposure live there and no venv-side instrument sees them. → FUTURE.md, *a freshness recipe
    could be derived from the built scene*, which is the parked answer and hashes the built graph.
  * A rendered frame. Cycles is not bit-deterministic, so no golden over its output can exist.
  * Everything upstream of the look: `pipeline/fuse/`, the warp and the encoders. Same technique
    reaches them and each needs its own fixture; this file is the first subject, not the last.

Values are rounded before hashing, because a committed baseline is read on machines this was not
generated on and the last bits of a float are not portable. The margin is enormous either way: the
change this exists to catch moves alpha by 0.0797 and the rounding absorbs 1e-9.

Run it as a module, from the repo root. A script under `scripts/` that imports `pipeline` cannot be
run by path: Python puts the script's own directory on `sys.path`, not the root.

    uv run python -m scripts.pixel_baseline            # print it
    uv run python -m scripts.pixel_baseline --write    # regenerate the committed baseline
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from pipeline import bodies, layers
from pipeline.look import layer_producers

BASELINE = Path(__file__).resolve().parents[1] / "tests" / "pixel_baseline.json"

#: The one spelling of how to regenerate, because the test's failure message ends with it.
REGENERATE = "uv run python -m scripts.pixel_baseline --write"

#: Where the measured cost of a moved pixel lives, cited by heading and never by copying a duration.
#: Here rather than in the test, because `test_doc_pointers` scans `scripts` and not `tests`, so a
#: renamed heading would go unnoticed by the guard built to catch exactly that.
OWED_PASS = "PROCESS.md § The planet tile pipeline"

#: Square, and small enough that the whole baseline stays readable in a diff.
FIXTURE_SIZE = 32

#: Decimal places kept before hashing. See the module docstring: portability, not tolerance.
ROUNDING = 9

#: The producers whose answer is `None` on every window by design, so a `None` from anything else is
#: a fixture that stopped reaching its subject rather than a producer with nothing to say. Listed as
#: exceptions rather than the subjects being listed, so a new producer is covered by default, and
#: pinned as a value so the day one starts contributing this goes red instead of quietly widening.
#:
#: `antarctic_rock` builds a raster and contributes nothing: `fold_white` takes it back out of the
#: finished union as a `WHITE_EXCLUSIONS` member, and returning an array here paints the outcrop the
#: very white the layer exists to remove.
DECLARED_SILENT = frozenset({"earth/antarctic_rock"})


def fixture(latitude_top: float, latitude_bottom: float) -> layer_producers.LayerWindow:
    """One window whose every mask band sees the whole input range.

    The input varies across columns and the masks down rows. Varying both down rows leaves the
    ocean band on the ramp's low end alone, where `gated_alpha` collapses an all-zero sea-ice
    result to a `None` indistinguishable from `antarctic_rock`'s declared one.
    """
    size = FIXTURE_SIZE
    rows = np.arange(size)[:, None]
    latitude = np.linspace(latitude_top, latitude_bottom, size)
    raw = np.broadcast_to(np.linspace(0.0, 10000.0, size)[None, :], (size, size)).copy()
    watercode = np.broadcast_to(np.where(rows < size // 4, 2, 0).astype(np.uint8),
                                (size, size)).copy()
    land = np.broadcast_to(rows >= size // 2, (size, size)).copy()
    return layer_producers.LayerWindow(
        raw=raw,
        watercode=watercode,
        land=land,
        ocean=~land & (watercode == 0),
        latitude=latitude,
        ground_metres_per_px=np.full(size, 600.0),
        top=float(latitude[0]),
        bottom=float(latitude[-1]),
    )


#: Both hemispheres, because `_earth_sea_ice` selects a different tuning per row and a single
#: northern window would record one of the two curves and call it the layer.
WINDOWS = {"arctic": (82.0, 62.0), "antarctic": (-62.0, -85.0)}


def _describe(value: "np.ndarray | None") -> dict[str, Any]:
    """A digest that decides, and the statistics that tell a reader how far it moved.

    The digest is the authority; the summary exists because "sea_ice/arctic moved" is not actionable
    and "its mean alpha went from 0.0548 to 0.0731" is. Two arrays could share a summary, so nothing
    is asserted on it alone.
    """
    if value is None:
        return {"result": "none"}
    array = np.ascontiguousarray(np.round(np.asarray(value, dtype=float), ROUNDING))
    finite = array[np.isfinite(array)]
    return {
        "digest": hashlib.sha256(array.tobytes()).hexdigest()[:16],
        "shape": list(array.shape),
        "distinct": int(np.unique(array).size),
        "min": round(float(finite.min()), ROUNDING) if finite.size else None,
        "max": round(float(finite.max()), ROUNDING) if finite.size else None,
        "mean": round(float(finite.mean()), ROUNDING) if finite.size else None,
    }


def _paint_digest(paint: "tuple[Any, Any] | None") -> dict[str, Any]:
    """The `(sunlit, shadowed)` white, each end a bare triple or an array shaped per row."""
    if paint is None:
        return {"result": "none"}
    ends = [np.ascontiguousarray(np.round(np.asarray(end, dtype=float), ROUNDING)) for end in paint]
    hasher = hashlib.sha256()
    for end in ends:
        hasher.update(end.tobytes())
    return {"digest": hasher.hexdigest()[:16],
            "ends": [list(end.shape) or ["scalar"] for end in ends]}


def subjects() -> list[tuple[str, bodies.Body, layers.Layer]]:
    """Every (body, layer) the code actually has a producer for, derived and never listed.

    A hand-maintained list goes stale the day a layer is added, and silently: the missing subject
    has no row to read short. `producer_for` raising KeyError is how a body says it has no answer
    for a layer, which is a code fact rather than an omission.
    """
    found = []
    for body in bodies.BODIES.values():
        for layer in layers.LAYERS:
            try:
                layer_producers.producer_for(body, layer)
            except KeyError:
                continue
            found.append((f"{body.name}/{layer.name}", body, layer))
    return sorted(found)


def baseline() -> dict[str, dict[str, Any]]:
    recorded: dict[str, dict[str, Any]] = {}
    for key, body, layer in subjects():
        producer = layer_producers.producer_for(body, layer)
        entry: dict[str, Any] = {}
        for name, (top, bottom) in WINDOWS.items():
            window = fixture(top, bottom)
            entry[name] = {"contribution": _describe(producer.contribution(window)),
                           "paint": _paint_digest(producer.paint(window))}
        recorded[key] = entry
    return recorded


def serialise(recorded: dict[str, dict[str, Any]]) -> str:
    """Stable bytes: sorted keys and a trailing newline, so a diff shows only real movement."""
    return json.dumps(recorded, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true",
                        help=f"regenerate tests/{BASELINE.name} instead of printing")
    args = parser.parse_args(argv)
    text = serialise(baseline())
    if not args.write:
        print(text, end="")
        return 0
    unchanged = BASELINE.exists() and BASELINE.read_text(encoding="utf-8") == text
    BASELINE.write_text(text, encoding="utf-8")
    print(f"{BASELINE.relative_to(BASELINE.parents[1])}: "
          f"{'unchanged' if unchanged else 'REWRITTEN — commit it with this change'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
