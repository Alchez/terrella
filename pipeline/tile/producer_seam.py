"""Which producer made a body's planet raster, declared by the producer that made it.

THE SAME SEAM AS `planet_seam`, ONE TIER DOWN. That one exists because a downstream stage cannot
learn from a directory listing whether a body HAS an ocean mask; this one exists because it cannot
learn from the raster whether the pixels in it were composited or raytraced. Both answers are
declarations rather than inferences, for the same reason: what is on disk cannot say.

WHY THE QUESTION IS LOAD-BEARING AT ALL. `freshness.done_marker(output)` is
`output.with_suffix(".done")`, derived from the OUTPUT alone. Two producers writing one raster
therefore share one completion marker, so each one's staleness question is answered by the other's
work — in BOTH directions, silently, with every gate green:

  * raytrace then composite: `composite_params.json` never moved and the raster is newer than every
    warp source, so the composite prints *"planet_rgb fresh -> skip composite"* and the cut
    publishes raytraced pixels under a composite recipe.
  * composite then raytrace: `write_if_changed` leaves `raytrace_params.json` alone, so the block
    runner prints *"fresh -> skip render"* over composited ones.

Separate recipes do not close this. The hazard is the shared OUTPUT, not a shared dependency list,
which is why `block_render`'s docstring could claim coverage in good faith and be describing a
different failure. The fix is a file whose mtime moves when and only when the producer changes,
named by BOTH dependency lists: naming it in one detects nothing, because detection has to be
symmetric.

IT RECORDS WHAT WROTE THE RASTER, NEVER WHAT THE BODY DECLARED, and the two differ in exactly the
case this exists for. `bodies.Body.planet_producer` is what a body ASKS for; a run of
`block_render` against a body still registered as `"composite"` puts raytraced bytes on disk
whatever the registry says. Recording the caller's intent there would leave the stamp agreeing with
a registry that the pixels disagree with. So each producer names ITSELF, as its own first action.

A DISPATCHER CANNOT OWN THIS, which is the shape the first version got wrong. `planet_pass` wrote
the stamp before dispatching, and `block_render.main` is a second shipped door into the raytrace
producer — the `--only`/`--limit` path used to re-render one block for judging. That door never
reaches the dispatcher, so the stamp stayed on whatever the last pass wrote. A missing stamp is
worse than a stale one: `freshness.newest_mtime` scores an absent path 0.0, so the dependency both
recipes name contributes nothing at all and the whole mechanism is inert.

Stdlib-only apart from `bodies`, so any producer can import it without pulling in rasterio.
"""

import json
from pathlib import Path

from pipeline import bodies, freshness

#: The stamp's basename, beside the raster it describes. One spelling, imported by both producers
#: and by the pass, because a second spelling would leave each producer watching its own file —
#: which cannot detect a switch in either direction.
STAMP_NAME = "planet_producer.json"


def stamp_path(work: Path) -> Path:
    """Where the producer declaration for `work`'s CANONICAL planet raster lives.

    Keyed on the work directory because that is its subject: one raster, which two producers can
    both write. A run pointed at a second raster declares nothing — `block_render.sidecars_for` and
    `composite_planet` each guard their own call on that — so no stamp here ever names a producer
    for bytes written elsewhere.
    """
    return work / STAMP_NAME


def declare(work: Path, producer: str) -> Path:
    """Record that `producer` made `work`'s planet raster, and return the stamp.

    Call this FIRST, before asking any freshness question, because the answer depends on it: the
    stamp is in both producers' dependency lists, so a producer that stamped itself after its own
    `is_stale` call would be answering against the previous run's declaration.

    `write_if_changed` is what makes this a dependency rather than a restage. The mtime moves if and
    only if the recorded producer actually changed, so re-running an unchanged body rebuilds
    nothing, while a switch moves one mtime and both producers go stale together.

    Raises on a producer outside the vocabulary rather than writing it. A typo here is otherwise
    perfectly silent: it would differ from whatever is on disk, so the raster would restage once,
    look correct, and leave a stamp that no dispatcher can ever match again.
    """
    if producer not in bodies.PLANET_PRODUCERS:
        raise ValueError(f"unknown planet producer {producer!r}; "
                         f"the vocabulary is {', '.join(bodies.PLANET_PRODUCERS)}")
    return freshness.write_if_changed(stamp_path(work),
                                      json.dumps({"producer": producer}, indent=2) + "\n")


def declared(work: Path) -> str | None:
    """Which producer made `work`'s planet raster, or None if nothing has declared one.

    None is a real answer and not an error: it is what every work directory says until the first
    pass after this seam existed. Returning it rather than raising is what lets a caller tell
    "produced by the other one" from "produced before anyone was recording", which are different
    facts and want different handling.
    """
    try:
        return json.loads(stamp_path(work).read_text())["producer"]
    except (OSError, ValueError, KeyError):
        return None
