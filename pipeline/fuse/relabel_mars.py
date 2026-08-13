"""Publish the MOLA/HRSC blend as Mars's planet heightfield — a CRS relabel, and nothing else.

THE FUSE TIER'S COUNTERPART FOR A BODY THAT NEEDS NO FUSION. `fuse_planet` turns ~26,000 Copernicus
tiles, a void-fill edition and a bathymetry grid into 648 fused cells and indexes them; Mars arrives
as one pre-blended global raster, so the same job is a few lines. It lives beside that driver because
a tier is defined by what it PRODUCES — a body's planet rasters, and the declaration naming them —
not by how much work it takes to produce them.

WHAT THE RELABEL IS, AND WHY IT IS AN IDENTITY. The source is lon/lat degrees on an unflattened
sphere of 3,396,190 m; we declare that grid to be EPSG:4326. Every pixel keeps the longitude and
latitude it already had — only the label naming which body those angles belong to changes. Nothing
is resampled, nothing moves, and the output is a VRT, so no copy of 10.6 GiB is made.

  IT IS ONLY HONEST BECAUSE THE SOURCE IS A TRUE SPHERE. On an ellipsoid the same declaration would
  silently shift every latitude, because a geodetic latitude on one figure is a different angle on
  another. `download_mars_dem.assert_grid` is what holds that precondition, and `main` runs it
  before this module writes anything.

WHY RELABEL AT ALL, rather than projecting Mars on its own sphere: PROJ refuses to build an
operation between two celestial bodies, and the tiler reprojects into WebMercatorQuad. A
Mars-radius Mercator raster therefore cannot be cut into tiles without disabling that guard
globally. Every projection downstream is Earth-sphered for every body, and `bodies.MARS.ground_
radius_m` is the single fact that converts the resulting map units back into Martian ground metres.

MARS DECLARES A HEIGHTFIELD AND NOTHING ELSE. No ocean mask, no water mask — not empty ones, none
at all. A raster of zeros on disk cannot be told apart from one produced by measuring Mars's oceans
and finding none, and it would be the only body fact in this project written as a fabricated
dataset. The consumers build all-land selectors in memory from the declaration instead
(`pipeline/planet_seam.py`), and a sea at a chosen contour later is a change HERE plus a registry
line — which is what makes that question answerable by rendering rather than by arguing.

KNOWN AND UNANSWERED UNTIL THE FILE IS ON DISK: the blend declares nodata -32768, where Earth's
fused heightfield declares none. If the mosaic actually contains nodata pixels they will pass
through this VRT, survive the warp, and land at the bottom of the sea ramp as deep blue. Whether it
contains any is not knowable from the header — the first z6 pyramid answers it, unmissably.

Output (data/work/mars/planet/):
  planet_heightfield.vrt    the blend, CRS declared EPSG:4326
  planet_rasters.json       the seam declaration, written last

Idempotent, and free to re-run: the VRT is replaced only when its XML actually changes, so a second
run does not move the mtime that gates a 3857 warp.

Usage:
  python3 -m pipeline.fuse.relabel_mars
"""

import subprocess
import sys
from pathlib import Path

from pipeline import bodies, planet_seam
from pipeline.acquire import download_mars_dem


def relabel(source: Path) -> Path:
    """Write Mars's planet heightfield VRT over `source`, declaring its CRS to be EPSG:4326.

    `-a_srs` ASSIGNS rather than reprojects, which is the whole point: `-t_srs` would ask PROJ for
    an operation between two celestial bodies and be refused, and any resampling here would cost a
    5.7 Gpx pass to move pixels that are already where they belong.
    """
    def build(target: Path) -> None:
        subprocess.run(["gdal_translate", "-q", "-of", "VRT", "-a_srs", "EPSG:4326",
                        str(source), str(target)], check=True)

    vrt = planet_seam.vrt_path(bodies.MARS, "heightfield")
    changed = planet_seam.write_vrt_if_changed(vrt, build)
    print(f"{vrt}{'' if changed else ' (unchanged)'}", flush=True)
    return vrt


def main() -> int:
    blend = download_mars_dem.blend_path()
    if not blend.exists():
        sys.exit(f"{blend} is not on disk — run `python3 -m pipeline.acquire.download_mars_dem` "
                 f"first (~10.6 GiB)")
    # BEFORE the relabel, not after, and not skipped because the file was verified at download time.
    # The relabel's honesty rests on the source being a true sphere in degrees; a re-published mosaic
    # on an ellipsoid would make it a silent latitude shift, and this is the one check that sees it.
    download_mars_dem.assert_grid(blend)
    relabel(blend)
    print(f"declared {planet_seam.declare(bodies.MARS, ['heightfield'])}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
