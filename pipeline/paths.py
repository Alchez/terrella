"""The single home for machine-specific filesystem roots.

Every pipeline module derives its locations from the three constants here, so a different checkout,
container or contributor's machine relocates everything by setting two environment variables. That
is the open-source portability seam, and `tests/test_paths.py` enforces it with a source scan: a new
`Path.home()` root anywhere else fails the suite.

- ROOT is source-tree-derived and never env-driven, because outputs that live in the repo
  (`web/public` assets) must follow the checkout rather than the data store.
- DATA takes `MAPS_DATA`, defaulting to `<repo>/data`. Its shell twin is `build_mosaics.sh`, which
  reads the same variable.
- BLENDER takes `MAPS_BLENDER`, defaulting to the tarball install in docs/pipeline.md § Environment
  setup.

Derive at call time, not at import. A module-level `SOMEWHERE = DATA / "x/y"` freezes the root at
import, so redirecting `MAPS_DATA` moves some of a module's paths and not others, with no error in
it: the frozen readers go stale together, still agree with each other, and every assertion between
them still passes. It has already cost one run that isolated its working tree and wrote its served
output into the real `web/public/`. Write a function.

`TestNoNewPathFreezesTheStoreAtImport` guards one form of that, not the rule entire. It catches a
module-level `Path` under `DATA`, whatever produced it, against a pinned list that only shrinks. A
default argument is the form it cannot see: evaluated at import just the same, but living where
`vars(module)` does not reach. Write a function there too and pass `None`. The older `STORE_PROBE`
cannot substitute, since it moves the store before importing, the one condition under which a frozen
constant looks correct.
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
