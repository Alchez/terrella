"""Download Natural Earth 1:10m vectors at a pinned release: border overlays, camera-framing
polygons, disputed-area segments (worldview dashing), and the coastline used as the
overlay-alignment oracle.

Pinned to a release tag of the canonical repo (nvkelso/natural-earth-vector) because
naturalearthdata.com / naciscdn serve only an unversioned "latest" — a fresh machine must reproduce
this exact dataset, not whatever is current. Bumping TAG is a deliberate migration: bbox-diff the
country frames and re-check disputed-segment styling before adopting.

Each layer's VERSION.txt records when that LAYER itself last changed (the coastline says 5.0.0-pre9
inside the 5.1.2 release), which is not the release version.

Idempotent: a layer whose directory already exists is skipped, and a failed fetch leaves no
directory behind.

Usage: python -m pipeline.acquire.earth.download_naturalearth
"""

import shutil
import sys
from pathlib import Path

from pipeline import datasets
from pipeline.fetch import download_one

TAG = "v5.1.2"
BASE_URL = f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{TAG}"

#: Every layer this fetches, against the category directory it sits in upstream. The name is also
#: its directory name in the store and the stem of every component inside it, which is the rule
#: `pipeline/naturalearth.py` addresses a layer by; that module derives its vocabulary from these
#: keys rather than keeping a list of its own.
LAYERS = {
    "ne_10m_admin_0_boundary_lines_land": "10m_cultural",
    "ne_10m_admin_0_boundary_lines_maritime_indicator": "10m_cultural",
    "ne_10m_admin_0_countries": "10m_cultural",
    "ne_10m_admin_0_disputed_areas": "10m_cultural",
    "ne_10m_coastline": "10m_physical",
    "ne_10m_lakes": "10m_physical",
    "ne_10m_rivers_lake_centerlines": "10m_physical",
}

REQUIRED = ("shp", "shx", "dbf", "prj", "VERSION.txt")
OPTIONAL = ("cpg", "README.html")  # not every layer ships these


def fetch_layer(name: str, destination: Path) -> None:
    """Fetch one layer's components, or leave nothing behind.

    THE LAYER IS THE UNIT THAT LANDS, not the component: a shapefile is only readable with its
    siblings, so components stream into a `.part` directory that is renamed into place once the
    required ones have all arrived. That is what makes a directory under its final name a complete
    layer, and `exists()` a valid resume.
    """
    part = destination.with_name(destination.name + ".part")
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True)
    base = f"{BASE_URL}/{LAYERS[name]}/{name}"
    for component in REQUIRED + OPTIONAL:
        status = download_one(f"{base}.{component}", part / f"{name}.{component}",
                              absent_on_404=component in OPTIONAL)
        if status not in ("ok", "absent"):
            shutil.rmtree(part, ignore_errors=True)
            sys.exit(f"{name}.{component}: {status}")
    part.replace(destination)


def main() -> int:
    destination_root = datasets.naturalearth()
    destination_root.mkdir(parents=True, exist_ok=True)
    for name in LAYERS:
        layer_dir = destination_root / name
        if layer_dir.is_dir():
            print(f"skip {name} (exists)", flush=True)
            continue
        print(f"fetch {name} @ {TAG}", flush=True)
        fetch_layer(name, layer_dir)
    print(f"done: {destination_root} (pinned {TAG})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
