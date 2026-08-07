"""Download the MOLA/HRSC blended global DEM — the whole of Mars's elevation input.

ONE FILE, AND THAT IS THE POINT. Earth's heightfield is assembled from ~26,000 Copernicus tiles,
a void-fill edition, a bathymetry grid and a fusion pass; Mars arrives pre-blended as a single
raster, so there is no acquire tier to mirror and no fuse tier to run. Mirroring either would be
inventing work that has no input. What this module owes instead is everything the Earth machinery
gave us for free: proof that the bytes are the edition we designed against, and a loud failure when
they are not.

Source: the USGS Astrogeology `Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2` mosaic — MOLA (Mars Global
Surveyor) upsampled from its native 463 m/px, with Mars Express HRSC stereo DTMs blended in where
they exist. 200 m/px is a compromise between upsampling MOLA and downsampling HRSC, not a resolution
the whole planet actually carries.

  200 m/px IS NOT 200 m OF INFORMATION, and this is the most consequential fact about the product.
  HRSC covers roughly 44% of the surface; the other 56% is MOLA at 463 m, interpolated. Edges are
  feathered over ~5 km. So a straight edge or a texture change in this DEM is a provenance boundary,
  not a defect — do not smooth it reflexively, and verify at the data's own pixel scale first. It is
  also the argument against a z8 Mars pyramid: z8 would buy four times the disk for a 2.8x upsample
  over most of the planet.

LICENCE: read the product page's own CONSTRAINT FIELDS, never the publisher's organisational status.
This block once said "none to satisfy", reasoning that a USGS Astrogeology PDS Annex product is a US
government work. That is true and it is not the answer: the page states Access Constraints of "MOLA
(CC0) and HRSC (CC BY-SA 3.0 IGO)" and Use Constraints of "Please cite authors" — the publisher
labelling its own inputs, about this exact file, one page load away the whole time. Whether the
share-alike half binds is a legal question; the site answers it by licensing its renders CC BY-SA
4.0, which complies either way. Note where this had to be caught: the obligation attaches to what is
PUBLISHED, so fetching and rendering succeed regardless and no pipeline gate can ever see it. The
constraint-field read belongs here, at acquisition, not months later when a page needs a credit.
ATTRIBUTIONS.md carries both readings and the citation the use constraint asks for.

A separate trap, unchanged: ESA's published HRSC *pictures* — the colour perspective views — are a
different product under ESA's own terms. Take HRSC from the archive, never from the picture gallery.
Nothing here needs the gallery.

WHAT WAS MEASURED, rather than read off a landing page (every number below is pinned in code):
  106694 x 53347 px, Int16, nodata -32768, 11,384,463,908 bytes on the wire. It is UNCOMPRESSED and
  STRIPED ONE ROW PER BLOCK, with no overviews, and the byte count accounts for itself exactly:
  106694 x 53347 x 2 = 11,383,609,636 bytes of pixels, and the remaining 854,272 is the per-strip
  directory that layout costs -- 53347 rows x 16 bytes of BigTIFF offset and byte-count entries =
  853,552, plus a 720-byte header. One row per strip also means it is read SEQUENTIALLY: a windowed
  read is not cheap here, and neither is a second pass over it.
  Its CRS is `GCS_Mars_2000_Sphere` on a SPHERE of 3,396,190 m — flattening exactly 0, and the same
  number `bodies.MARS.ground_radius_m` carries, which `assert_grid` below ties together.

WHY THE SPHERE MATTERS MORE THAN IT LOOKS. The pipeline projects every body on Earth's spheres
because PROJ refuses to build an operation between two celestial bodies, so this file enters by
having its CRS DECLARED as EPSG:4326 — an identity on the angles, since the grid is already
degrees on an unflattened sphere and only the body label changes. That relabel is only honest while
the source really is a sphere: on an ellipsoid the same declaration would silently shift latitudes.

THE URL IS A FRONT DOOR, NOT THE ORIGIN, and both halves of that cost a failed run to learn. It is
served through Cloudflare, which 302s to an S3 bucket (`asc-pds-services`, us-west-2) and refuses
the default Python user agent with a 403 before the redirect is ever followed — hence `pipeline
.fetch`, and hence a 403 here means the agent, not a rotted URL. The S3 leg advertises
`Accept-Ranges`, so a resumable fetch is possible if this transfer ever proves unreliable; it is not
built, because nothing has yet measured a need for it.

Output (data/raw/mars/):
  Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif    the blend, exactly as published

Idempotency: the file streams to a `.part` name, is size-checked against Content-Length and only
then atomically renamed (`fetch.download_one`, one home for that rule), so a file under its
final name is always complete and a re-run skips it.

Edition oracle: `preflight` HEADs the URL and refuses to download unless the size AND the
Last-Modified date still match the pin. USGS republishes mosaics in place under the same filename —
the `_v2` in the name is the product version, not an immutable release — so a same-name file with a
different date is a different planet's worth of pixels arriving under our recipe. `assert_grid`
then re-checks the raster itself, because a byte count is not a grid.

Usage:
  python3 -m pipeline.acquire.download_mars_dem --check     # preflight only, downloads nothing
  python3 -m pipeline.acquire.download_mars_dem             # preflight, then ~10.6 GiB
  python3 -m pipeline.acquire.download_mars_dem --verify    # re-check the file already on disk
"""

import argparse
import sys
from pathlib import Path

import pyproj
import rasterio

from pipeline import bodies, fetch, paths
from pipeline.fetch import download_one

DATA_DIR = paths.DATA / "raw/mars"

BLEND_NAME = "Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif"
BLEND_URL = ("https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/"
             f"{BLEND_NAME}")

#: The edition this pipeline was designed against, pinned so a republished mosaic cannot arrive
#: unannounced. Both fields, not just the size: a re-blend that happens to land on the same byte
#: count is unlikely but a re-upload of the same bytes is not, and only the date separates them.
EXPECTED_BYTES = 11_384_463_908
EXPECTED_LAST_MODIFIED = "Wed, 09 Nov 2022 14:59:19 GMT"

#: The grid the entry seam is built on. Restated here as a CONTRACT rather than derived at read
#: time: every one of these is a number some later stage assumes, and a source that quietly changed
#: shape would otherwise be discovered as a wrong-looking planet rather than as an error.
EXPECTED_WIDTH = 106_694
EXPECTED_HEIGHT = 53_347
EXPECTED_DTYPE = "int16"
EXPECTED_NODATA = -32768.0


def blend_path() -> Path:
    """Where the blend lives once fetched. A function, not a constant, per `paths`."""
    return DATA_DIR / BLEND_NAME


def preflight(url: str = BLEND_URL) -> None:
    """Assert the server still offers the exact edition this module is pinned to, or exit.

    A HEAD, so this costs no bandwidth and can be run before committing to ~10.6 GiB. It is the
    only check that can run BEFORE the download, which is precisely when a drifted edition is
    cheapest to discover.
    """
    with fetch.open_url(url, method="HEAD", timeout=60) as response:
        served_bytes = int(response.headers.get("Content-Length", -1))
        served_date = response.headers.get("Last-Modified", "")
    for field, served, expected in (("size", served_bytes, EXPECTED_BYTES),
                                    ("Last-Modified", served_date, EXPECTED_LAST_MODIFIED)):
        if served != expected:
            sys.exit(f"{BLEND_NAME}: the server now reports {field}={served!r}, pinned to "
                     f"{expected!r} — the mosaic was republished under the same name. Stop and "
                     f"re-check the product before re-pinning: the resolution ceiling, the "
                     f"provenance split and the ground radius all key off this edition.")


def assert_grid(path: Path) -> None:
    """Assert the raster on disk is the grid the rest of the pipeline assumes, or exit.

    SEPARATE FROM `preflight` BECAUSE A BYTE COUNT IS NOT A GRID. The size pin proves the transfer
    matched what was advertised; this proves the advertised thing is still shaped the way the entry
    seam, the zoom ceiling and the registry were all written against.

    The sphere check is the load-bearing one. `bodies.MARS.ground_radius_m` is what converts this
    pipeline's map units back into Martian ground metres — the hillshade z-factor, the sky-view
    search radius, the cap relief all divide by it — and it was taken FROM this product. Holding the
    two together here means a source published on the 3,389,500 m mean sphere instead of the
    3,396,190 m IAU sphere is an error at acquisition rather than a 0.2% relief error nobody sees.
    """
    with rasterio.open(path) as dataset:
        checks = [
            ("width", dataset.width, EXPECTED_WIDTH),
            ("height", dataset.height, EXPECTED_HEIGHT),
            ("dtype", dataset.dtypes[0], EXPECTED_DTYPE),
            ("nodata", dataset.nodata, EXPECTED_NODATA),
        ]
        crs = dataset.crs
        for field, actual, expected in checks:
            if actual != expected:
                sys.exit(f"{path.name}: {field} is {actual!r}, expected {expected!r} — this is not "
                         f"the grid the Mars entry seam was built against")
        # A geographic CRS in degrees is what makes the EPSG:4326 relabel an identity on the angles.
        if crs is None or not crs.is_geographic:
            sys.exit(f"{path.name}: CRS is {crs!r}, expected a geographic (degree) CRS — the entry "
                     f"seam RELABELS this to EPSG:4326, which only holds for lon/lat degrees")
        # VIA THE ELLIPSOID, NOT `to_dict()["a"]`, and the difference is not cosmetic: PROJ
        # serialises an unflattened body as `+R=`, so a sphere has no `a` key at all and the
        # tempting spelling reads None for exactly the products this check exists to inspect.
        ellipsoid = pyproj.CRS.from_user_input(crs.to_wkt()).ellipsoid
        semi_major = ellipsoid.semi_major_metre if ellipsoid is not None else None
        if semi_major is None or abs(semi_major - bodies.MARS.ground_radius_m) > 1.0:
            sys.exit(f"{path.name}: published on a sphere of {semi_major!r} m, but "
                     f"bodies.MARS.ground_radius_m is {bodies.MARS.ground_radius_m} — every ground "
                     f"metre this pipeline computes for Mars divides by that number, and it was "
                     f"taken from this product. Re-check the source before changing either.")


def build_parser() -> argparse.ArgumentParser:
    """The CLI, split out of `main` so its contract is testable without touching the network."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="run the edition preflight and stop; downloads nothing")
    parser.add_argument("--verify", action="store_true",
                        help="re-check the grid of the file already on disk; downloads nothing")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    destination = blend_path()

    if args.verify:
        if not destination.exists():
            sys.exit(f"nothing to verify: {destination} is not on disk")
        assert_grid(destination)
        print(f"verified {destination} ({destination.stat().st_size:,} bytes)", flush=True)
        return 0

    preflight()
    print(f"preflight ok: {BLEND_NAME} is the pinned edition "
          f"({EXPECTED_BYTES:,} bytes, {EXPECTED_LAST_MODIFIED})", flush=True)
    if args.check:
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"downloading {BLEND_URL} -> {destination} (~10.6 GiB) ...", flush=True)
    result = download_one(BLEND_URL, destination)
    if result.startswith("failed"):
        sys.exit(f"{BLEND_NAME}: {result}")
    print(f"{result}: {destination}", flush=True)
    assert_grid(destination)
    print("grid verified against the Mars entry seam's contract", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
