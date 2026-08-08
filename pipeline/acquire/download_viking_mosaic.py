"""Download the Viking colour mosaic — the FIELD Mars's polar ice is graded against.

WHAT THIS IS AND IS NOT. The white on Mars's poles is two fields from two sources: an extent (where
white is drawn at all) and an alpha (how white each pixel inside it is). `download_sim3292` acquires
the extent; this module acquires the field the alpha is measured from. The two are independent, and
nothing in either one depends on the other's source.

WHY THE 925 m COLOUR MOSAIC AND NOT A FINER ONE. Two finer global Viking products sit in the same
directory and both are traps for this use, so reaching for one is a redo waiting to happen:
  `Mars_Viking_MDIM21_ClrMosaic_global_232m.tif` is RELIEF IMAGERY, not an albedo field — its base
  is high-pass filtered to strip regional albedo and emphasise topography, and its colour is this
  925 m mosaic warped on top. It buys registration and spends the very signal an ice ramp grades on.
  `Mars_Viking_MDIM21_Mosaic_global_232m.tif` is that same filtered base without the colour.
  This product is the one USGS built FOR albedo: Minnaert normalisation, condensate-haze modelling,
  and source frames chosen for least atmospheric obscuration and seasonal frost.

LICENCE: read at the product page's own CONSTRAINT FIELDS, per the rule `download_mars_dem` records.
`Access Constraints: public domain`, `Use Constraints: None` — no attribution obligation at all,
weaker than the Mars DEM's "please cite authors" and weaker than SIM 3292's. The operative reason is
17 U.S.C. §105 rather than age: Viking is NASA and the mosaic is USGS, both federal, and unlike the
MOLA/HRSC blend there is no non-federal contributor to carry terms in. ATTRIBUTIONS.md credits it
anyway, which no constraint requires and courtesy does.

  THE PRODUCT PAGE IS NOT READABLE BY THIS PIPELINE'S HTTP CLIENT, and it fails in the shape that
  looks like success. `astrogeology.usgs.gov` renders from JavaScript and serves the same shell for
  every slug INCLUDING ones that do not exist, so a fetch of it can neither read the constraints nor
  tell a real product from a typo. The reading above was taken in a browser. Do not add a licence
  check here that appears to work.

WHAT THE PUBLISHER SHIPS, enumerated rather than guessed: the bucket behind the mosaic host permits
anonymous listing, so the product's file set is known exactly, and it is four files — the `.tif`, a
detached ISIS `.lbl`, a `_pds3.lbl`, and `.tif.md5`. This module takes the GeoTIFF alone. It is
self-describing, and no stage reads either label.

  THE LABELS AND THE GEOTIFF DISAGREE ABOUT THE SHAPE OF MARS, and only one of them can be acted on.
  Both detached labels declare a flattened body — `PolarRadius = 3376200`, `C_AXIS_RADIUS = 3376.2
  <KILOMETERS>` — while the GeoTIFF's own CRS declares `SPHEROID["Mars",3396190,0]`, flattening
  exactly 0. The GeoTIFF governs, and its sphere is what makes the EPSG:4326 relabel every Mars
  raster passes through an identity on the angles; the labels' polar radius is the body's physical
  shape carried as metadata, and the latitudes are planetocentric, which is the same angle on any
  figure. `assert_grid` pins the sphere, so an edition published on the ellipsoid is an error here
  rather than a silent latitude shift downstream.

FRESHNESS IS KEYED ON THE PUBLISHER'S OWN DIGEST, which this product offers and a size pin cannot
match. `<name>.tif.md5` sits beside the mosaic, so `--check` proves the CONTENT is the edition on
record before spending ~761 MiB — where a size-and-date preflight can only prove that something of
the right length is on offer.

WHAT WAS MEASURED, rather than read off a landing page (every number below is pinned in code):
  23059 x 11530 px, 3 bands, UnsignedByte, nodata 0, 925.406 m/px at 64.05264 px/degree. Its CRS is
  SimpleCylindrical in METRES — PROJECTED, unlike the DEM's degrees, so a consumer warps out of map
  metres rather than relabelling in place.
  The byte count accounts for itself exactly: 23059 x 11530 x 3 = 797,610,810 bytes of pixels, and
  the remaining 277,367 is what the layout costs — it is STRIPED ONE ROW PER BAND-ROW with no
  overviews, so 34,590 strips x 8 bytes of classic-TIFF offset and byte-count entries = 276,720,
  plus 647 of header and IFD. One row per strip also means it is read SEQUENTIALLY: a windowed read
  is not cheap here, and neither is a second pass over it.

  NODATA IS 0 ON EVERY BAND AND THAT IS NOT A SCALAR SENTINEL. Invalidity is all three channels zero
  together; one channel reading 0 is black, not absent. `mars_ice.albedo_alpha` carries the same
  seam from the consumer's side.

Output (data/raw/mars/):
  Mars_Viking_ClrMosaic_global_925m.tif    the mosaic, exactly as published

Idempotency: the file streams to a `.part` name, is size-checked against Content-Length and only
then atomically renamed (`fetch.download_one`, one home for that rule), so a file under its final
name is always complete and a re-run skips the transfer — but still re-digests what it found.

Usage:
  python3 -m pipeline.acquire.download_viking_mosaic --check    # preflight only, downloads nothing
  python3 -m pipeline.acquire.download_viking_mosaic            # preflight, then ~761 MiB
  python3 -m pipeline.acquire.download_viking_mosaic --verify   # digest the file already on disk
"""

import argparse
import hashlib
import sys
from pathlib import Path

import pyproj
import rasterio

from pipeline import bodies, fetch, paths
from pipeline.fetch import download_one

DATA_DIR = paths.DATA / "raw/mars"

MOSAIC_NAME = "Mars_Viking_ClrMosaic_global_925m.tif"

#: Note the path: this product sits at the mosaic ROOT, where the Mars DEM is one directory deeper
#: under `Mars/HRSC_MOLA_Blend/`. The host's layout is per-product, not per-body.
MOSAIC_URL = f"https://planetarymaps.usgs.gov/mosaic/{MOSAIC_NAME}"

#: The publisher's checksum sidecar. Fetching it costs a few dozen bytes and is the only edition
#: check that can inspect CONTENT before the transfer is committed to.
CHECKSUM_URL = f"{MOSAIC_URL}.md5"

#: The edition every Mars ice level on record was measured over. The digest is the PUBLISHER's, so
#: this pin is checkable against the source itself rather than only against a previous download.
EXPECTED_MD5 = "a0e0bbf33ecb0ff65ece9cfa8e08813e"
EXPECTED_BYTES = 797_888_177
EXPECTED_LAST_MODIFIED = "Thu, 10 Nov 2022 04:35:38 GMT"

#: The grid, restated as a CONTRACT rather than derived at read time: each of these is a number some
#: later stage assumes, and a source that quietly changed shape would otherwise be discovered as a
#: wrong-looking pole rather than as an error.
EXPECTED_WIDTH = 23_059
EXPECTED_HEIGHT = 11_530
EXPECTED_BANDS = 3
EXPECTED_DTYPE = "uint8"
EXPECTED_NODATA = 0.0
EXPECTED_PIXEL_METRES = 925.406


def mosaic_path() -> Path:
    """Where the mosaic lives once fetched. A function, not a constant, per `paths`."""
    return DATA_DIR / MOSAIC_NAME


def file_md5(path: Path) -> str:
    """md5 of a file on disk, streamed a megabyte at a time.

    md5 RATHER THAN SOMETHING MODERN because the digest has to be comparable to the publisher's, and
    md5 is what they publish. It is an integrity check against a truncated or substituted download,
    not a security boundary, and choosing sha256 here would simply make the pin uncheckable.
    """
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def published_md5(url: str = CHECKSUM_URL) -> str:
    """The digest the publisher currently advertises, read from the `.md5` sidecar.

    THE SIDECAR NAMES ITS OWN SUBJECT AND THAT NAME IS CHECKED. The format is `<digest>  <filename>`,
    so a sidecar describing some other product would otherwise hand back a digest that fails the pin
    for a reason the error message would misreport — a rotted URL reading as a republished mosaic.
    """
    with fetch.open_url(url, timeout=60) as response:
        text = response.read().decode("ascii").strip()
    fields = text.split()
    if len(fields) != 2 or fields[1] != MOSAIC_NAME:
        sys.exit(f"{url}: expected '<md5>  {MOSAIC_NAME}', got {text!r} — the checksum sidecar does "
                 f"not describe this product, so its digest cannot be compared to ours")
    return fields[0]


def preflight(url: str = MOSAIC_URL) -> None:
    """Assert the server still offers the exact edition this module is pinned to, or exit.

    A HEAD plus a tiny GET, so this costs no meaningful bandwidth and can run before committing to
    ~761 MiB — which is precisely when a drifted edition is cheapest to discover. THE DIGEST IS THE
    LOAD-BEARING CHECK and the other two are cheap corroboration: size and date can both survive a
    re-render that moved pixels, and the digest cannot.
    """
    with fetch.open_url(url, method="HEAD", timeout=60) as response:
        served_bytes = int(response.headers.get("Content-Length", -1))
        served_date = response.headers.get("Last-Modified", "")
    checks: tuple[tuple[str, object, object], ...] = (
        ("size", served_bytes, EXPECTED_BYTES),
        ("Last-Modified", served_date, EXPECTED_LAST_MODIFIED),
        ("md5", published_md5(), EXPECTED_MD5),
    )
    for field, served, expected in checks:
        if served != expected:
            sys.exit(f"{MOSAIC_NAME}: the server now reports {field}={served!r}, pinned to "
                     f"{expected!r} — the mosaic was republished under the same name. Stop and "
                     f"re-check the product before re-pinning: every polar alpha level was measured "
                     f"over these pixels, and a re-render moves them.")


def assert_grid(path: Path) -> None:
    """Assert the raster on disk is the grid the ice levels were measured over, or exit.

    SEPARATE FROM `preflight`, AND NOT REDUNDANT WITH IT EVEN THOUGH A MATCHING DIGEST IMPLIES EVERY
    NUMBER BELOW. What this guards is the RE-PIN: when the mosaic is republished the cheap fix is to
    update `EXPECTED_MD5` and move on, and at that moment the digest check agrees with whatever
    arrived. This function is what still refuses a different planet's shape.

    The sphere check is the load-bearing one, and it is load-bearing for a reason the labels
    actively argue against — see this module's docstring. `bodies.MARS.ground_radius_m` is what
    converts map units back into Martian ground metres, and the EPSG:4326 relabel this raster passes
    through is an identity on the angles only while the source really is unflattened.
    """
    with rasterio.open(path) as dataset:
        checks: tuple[tuple[str, object, object], ...] = (
            ("width", dataset.width, EXPECTED_WIDTH),
            ("height", dataset.height, EXPECTED_HEIGHT),
            ("band count", dataset.count, EXPECTED_BANDS),
            ("dtype", dataset.dtypes[0], EXPECTED_DTYPE),
            ("nodata", dataset.nodata, EXPECTED_NODATA),
        )
        for field, actual, expected in checks:
            if actual != expected:
                sys.exit(f"{path.name}: {field} is {actual!r}, expected {expected!r} — this is not "
                         f"the mosaic the Mars ice levels were measured over")

        pixel_metres = abs(dataset.transform.a)
        if abs(pixel_metres - EXPECTED_PIXEL_METRES) > 0.001:
            sys.exit(f"{path.name}: {pixel_metres} m/px, expected {EXPECTED_PIXEL_METRES} — a "
                     f"resampled edition grades the same ice through a different filter")

        crs = dataset.crs
        # PROJECTED, not geographic: this product is SimpleCylindrical METRES where the Mars DEM is
        # degrees, so a consumer that relabels in place instead of warping gets Mars-sized numbers
        # read as degrees rather than an error.
        if crs is None or not crs.is_projected:
            sys.exit(f"{path.name}: CRS is {crs!r}, expected a PROJECTED (metre) CRS — consumers "
                     f"warp this out of SimpleCylindrical map metres, and a geographic edition "
                     f"would need a different chain entirely")

        # VIA THE ELLIPSOID, NOT `to_dict()["a"]`: PROJ serialises an unflattened body as `+R=`, so
        # a sphere has no `a` key at all and the tempting spelling reads None for exactly the
        # products this check exists to inspect.
        ellipsoid = pyproj.CRS.from_user_input(crs.to_wkt()).ellipsoid
        semi_major = ellipsoid.semi_major_metre if ellipsoid is not None else None
        semi_minor = ellipsoid.semi_minor_metre if ellipsoid is not None else None
        if semi_major is None or abs(semi_major - bodies.MARS.ground_radius_m) > 1.0:
            sys.exit(f"{path.name}: published on a body of semi-major {semi_major!r} m, but "
                     f"bodies.MARS.ground_radius_m is {bodies.MARS.ground_radius_m} — every ground "
                     f"metre this pipeline computes for Mars divides by that number. Re-check the "
                     f"source before changing either.")
        if semi_minor is None or abs(semi_minor - semi_major) > 1.0:
            sys.exit(f"{path.name}: published on an ELLIPSOID (semi-minor {semi_minor!r} m against "
                     f"semi-major {semi_major!r}), not the sphere this product has always carried. "
                     f"The EPSG:4326 relabel downstream is an identity on the angles only on a "
                     f"sphere; on an ellipsoid it shifts latitudes silently. The detached PDS "
                     f"labels declare a polar radius of 3376200 and are NOT the authority here.")


def build_parser() -> argparse.ArgumentParser:
    """The CLI, split out of `main` so its contract is testable without touching the network."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="run the edition preflight and stop; downloads nothing")
    parser.add_argument("--verify", action="store_true",
                        help="re-digest and re-check the file already on disk; downloads nothing")
    return parser


def assert_digest(path: Path) -> str:
    """Assert the file on disk carries the pinned digest, returning it, or exit."""
    digest = file_md5(path)
    if digest != EXPECTED_MD5:
        sys.exit(f"{path.name}: md5 {digest} != pinned {EXPECTED_MD5} — the bytes on disk are not "
                 f"the published edition. Delete the file and re-run rather than re-pinning: a "
                 f"truncated or substituted mosaic looks exactly like this.")
    return digest


def main() -> int:
    args = build_parser().parse_args()
    destination = mosaic_path()

    if args.verify:
        if not destination.exists():
            sys.exit(f"nothing to verify: {destination} is not on disk")
        digest = assert_digest(destination)
        assert_grid(destination)
        print(f"verified {destination} ({destination.stat().st_size:,} bytes, md5 {digest})",
              flush=True)
        return 0

    preflight()
    print(f"preflight ok: {MOSAIC_NAME} is the pinned edition ({EXPECTED_BYTES:,} bytes, "
          f"{EXPECTED_LAST_MODIFIED}, md5 {EXPECTED_MD5})", flush=True)
    if args.check:
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        print(f"{destination} is already on disk — re-checking, not re-fetching", flush=True)
    else:
        print(f"downloading {MOSAIC_URL} -> {destination} (~761 MiB) ...", flush=True)
    result = download_one(MOSAIC_URL, destination)
    if result.startswith("failed"):
        sys.exit(f"{MOSAIC_NAME}: {result}")
    if result == "ok":
        print(f"wrote {destination}", flush=True)
    # Re-digested even when the transfer was SKIPPED, which is the case that matters: a file already
    # under its final name is complete by construction but says nothing about which edition it is.
    assert_digest(destination)
    assert_grid(destination)
    print("digest matches the publisher's checksum; grid verified against the ice levels' contract",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
