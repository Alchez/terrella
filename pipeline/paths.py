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
  defaults to the documented tarball install (CLAUDE.md § Environment).
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
