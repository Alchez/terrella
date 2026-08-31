"""The single home for machine-specific filesystem roots.

Every pipeline module derives its locations from the three constants here, so a
different checkout (or a container, or another contributor's machine) relocates
everything by setting two environment variables — the open-source portability
seam. `tests/test_paths.py` enforces single-homing with a source scan: growing a
new `Path.home()` root anywhere else fails the suite.

- ROOT: the repository checkout. Source-tree-derived, never env-driven — outputs
  that live in the repo (web/public assets) must follow the checkout, not the
  data store.
- DATA: the asset/data store (DEM tiles, mosaics, render dirs, tile pyramid).
  `MAPS_DATA` overrides; defaults to `<repo>/data`. The shell twin of this seam
  is `build_mosaics.sh`, which reads the same variable.
- BLENDER: the Blender binary for hero renders. `MAPS_BLENDER` overrides;
  defaults to the documented tarball install (docs/pipeline.md § Environment setup).

DERIVE AT CALL TIME, NOT AT IMPORT — the rule every consumer of these three follows, stated here
rather than at each of them. A module-level `SOMEWHERE = DATA / "x/y"` freezes the root at import,
so redirecting `MAPS_DATA` moves some of a module's paths and not others. The failure has no error
in it: the frozen readers go stale together, so they still agree with each other and every
assertion between them still passes. It has already cost one run that isolated its working tree and
wrote its served output into the real `web/public/`. Write a function.

THE RULE IS GUARDED BY `TestNoNewPathFreezesTheStoreAtImport` for one FORM of it, not for the rule
entire: a module-level `Path` already under `DATA` was computed at import by construction, whatever
function produced it, and its list of known violations is pinned and only shrinks. A DEFAULT
ARGUMENT is the form it cannot see, being evaluated at import just the same and living where
`vars(module)` does not reach. Write a function there too, and pass `None`. The older
`STORE_PROBE` beside it asks a different question and cannot substitute, since it moves the store
BEFORE importing, which is the one condition under which a frozen constant looks correct.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATA = Path(os.environ["MAPS_DATA"]) if "MAPS_DATA" in os.environ else ROOT / "data"

BLENDER = (
    Path(os.environ["MAPS_BLENDER"])
    if "MAPS_BLENDER" in os.environ
    else Path.home() / "software/blender-5.1.2-linux-x64/blender"
)
