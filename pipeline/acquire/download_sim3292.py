"""Download the SIM 3292 polar map units — the EXTENT of Mars's ice, and only the extent.

WHAT THIS IS AND IS NOT. The white on Mars's poles is two fields from two sources: an extent (where
white is drawn at all) and an alpha (how white each pixel inside it is). This module acquires the
extent. The alpha would come from OMEGA, whose licence is undocumented rather than permitted, and
nothing here depends on it — the two are independent, which is why one being blocked does not block
the other.

WHY A MAPPED SOURCE RATHER THAN A MEASURED ONE, since Earth's ice comes from a measured field.
NSIDC-0791 is a *classification* — how many years out of N a pixel was snow — so on Earth the extent
and the alpha fall out of one number. Mars publishes no equivalent; a scout over the PDS4 registry
and Astropedia found none, and that was a census rather than a sample. TES bolometric albedo is the
obvious substitute and is a trap twice over: it is hard-clipped to 0.06-0.32, destroying every
gradation inside the ice, and its polar holes are FILLED at the floor value rather than flagged
nodata, which makes "nothing was measured" and "the darkest surface on the planet" the same number.

  THE MAPPED BOUNDARY IS NOT A MEASUREMENT OF ICE, and the source says so in its own metadata:
  linework drawn while viewing at 1:5,000,000, vertex spacing 5 km, minimum mappable outcrop 40 km
  wide by 100 km long. Against a 651 m z6 pixel that is ~8 pixels per vertex, so a hard edge reads
  as faceted. Any feather over this boundary is therefore DRAWN, and must be described as drawn --
  a distance transform wearing a measurement's clothes is the `antarctic_snow_mask` mistake.

LICENCE: attribution-only, and read at the product rather than at the publisher. The FGDC metadata
states `Access_Constraints: None`, `Use_Constraints: please cite authors.`, `Distribution_Liability:
None`, `Fees: None`. The citation the use constraint asks for is the metadata's own
`Data_Set_Credit`, reproduced in ATTRIBUTIONS.md and pinned by `tests/test_attributions.py` -- not
composed by us, so there is no guessed string anywhere in the chain. This composes with the site's
CC BY-SA 4.0 without an argument, which is the whole reason this source outranks OMEGA.

WHICH DISTRIBUTION, AND WHY NOT THE PUBLISHED ZIP. The same geometry ships two ways. The
Publications Warehouse offers `sim3292_database.zip` at 808,910,442 bytes, and its shapefile is
Robinson on the Mars 2000 sphere in METRES, carrying a `.prj` that makes PROJ refuse outright:
"Source and target ellipsoid do not belong to the same celestial body". Working with it needs
`Robinson(Mars) -> longlat(Mars) -> -a_srs EPSG:4326 -> EPSG:3857`, where `-a_srs` is the CURE.
(The same flag used INSTEAD of reprojecting is the classic bug, whose failure is a silent all-zero
raster. Any guard over this has to tell the two apart.)

  This module takes the pygeoapi route instead: ~4.3 MB against 809 MB, verified byte-equal on
  `features` and `links` against copies fetched independently. Its GeoJSON declares NO CRS, so GDAL
  assumes CRS84 and the Mars degrees pass through as Earth degrees -- which is CORRECT here by
  design rather than by luck, because the master grid is Earth-radius Web Mercator and the
  heightfield is warped into it identically. It stops being correct the moment a consumer declares
  the Mars sphere, which is exactly what the zip does.

THE RESPONSE IS NOT BYTE-STABLE, AND THIS IS THE TRAP THE MODULE IS SHAPED AROUND. pygeoapi stamps
every response with a `timeStamp` field carrying the request time. It is fixed-width ISO-8601, so
two fetches of identical data have the SAME byte length and a DIFFERENT hash -- the one shape that
defeats a size check and a content hash simultaneously. An acquirer pinning raw bytes would read
"the source changed" on every single run and re-acquire forever, which is precisely the idempotency
this pipeline requires. So freshness is keyed on `geometry_digest`, over `features` alone.

Output (data/raw/mars/sim3292/):
  lapc_sim3292.json    Late Amazonian polar cap unit, 2 features (one per pole)
  apu_sim3292.json     Amazonian polar undivided unit, 5 features, both hemispheres
  sim3292_params.json  the recipe: host, query, and each unit's digest and feature count

Idempotency: a unit whose file is on disk and whose recorded digest still matches the module's pin
is skipped. `--verify` re-reads the files without touching the network; `--check` reaches the host
and compares digests without writing.

Usage:
  python3 -m pipeline.acquire.download_sim3292 --verify   # re-check what is on disk, no network
  python3 -m pipeline.acquire.download_sim3292 --check    # fetch and compare, write nothing
  python3 -m pipeline.acquire.download_sim3292            # fetch what is missing or drifted
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from pipeline import fetch, paths

DATA_DIR = paths.DATA / "raw/mars/sim3292"

#: The pygeoapi instance. RECORDED HERE BECAUSE THE DATA CANNOT RECORD IT: every `links[].href` in
#: a response comes back RELATIVE, so a file re-fetched from this host still does not name it. That
#: gap is what made the scout copies unreproducible until it was probed.
HOST = "https://astrogeology.usgs.gov/pygeoapi"
COLLECTION = "mars/sim3292_global_geologic_map/units"

#: `limit` is the SOURCE's paging control, not a cap of ours — it must exceed every unit's feature
#: count or a fetch truncates silently, the response carrying no `numberMatched` to notice with.
#: `FEATURE_COUNTS` below is what actually refuses a truncated fetch.
QUERY_LIMIT = 200

#: The units this pipeline draws, and what each one is. `Apu` is in the NORTH extent only, on
#: measurement rather than symmetry: OMEGA puts it +0.13 to +0.16 over ordinary ground at matched
#: latitude in the north and within ±0.04 in the south, where it covers 68.7% of the disc — so
#: painting it there would whiten two-thirds of the view on no evidence. That decision belongs to
#: the consumer; this module acquires both and takes no view.
UNITS = ("lApc", "Apu")

#: Feature counts, pinned so a truncated or re-published response is an error rather than a smaller
#: ice cap. The map is `Maintenance_and_Update_Frequency: None planned`, so drift here means the
#: distribution changed and every extent figure downstream needs re-measuring.
FEATURE_COUNTS = {"lApc": 2, "Apu": 5}

#: sha256 over `features` alone, canonically serialised — the freshness key, and the answer to the
#: `timeStamp` trap in the module docstring. Pinned to the edition every extent measurement on
#: record was taken over.
GEOMETRY_DIGESTS = {
    "lApc": "12c66f17fa53722d02f0b23e94f8e8f857ab6f418bd80f0ae5deb118795b55ad",
    "Apu": "b1eb2a86a12b5cdf704fd0bc0a28b1be69157d13c4b7126c91a9c52f02887bd2",
}

#: The publisher's own geodesic areas, summed per unit, in km². An INDEPENDENT oracle over the
#: digest: a digest proves the bytes are what we saw, and this proves they describe the polygons the
#: publisher measured. `spharea_km` is computed by USGS on the Mars sphere, so it also catches a
#: response that parsed cleanly into the wrong geometry.
SPHERE_AREAS_KM2 = {"lApc": 700_535.0, "Apu": 2_005_394.2}

#: The property schema, lowercased. The FGDC metadata declares the layer's fields as
#: `Unit` / `UnitDesc` / `SphArea_km`; pygeoapi serves them lowercased, and that correspondence is
#: what identifies these bytes as the published SIM 3292 product rather than a lookalike.
REQUIRED_PROPERTIES = frozenset({"unit", "unitdesc", "spharea_km"})


def unit_path(unit: str) -> Path:
    """Where one unit's GeoJSON lives once fetched.

    A function rather than a constant so `MAPS_DATA` is read at CALL time — a relocated data store
    must move this too, and a module-level join freezes it at import.
    """
    return DATA_DIR / f"{unit.lower()}_sim3292.json"


def recipe_path() -> Path:
    """The recipe sidecar, beside the outputs it describes."""
    return DATA_DIR / "sim3292_params.json"


def unit_url(unit: str) -> str:
    """The query for one unit — the same one the scout files record in their own `links[].href`."""
    return f"{HOST}/collections/{COLLECTION}/items?f=json&limit={QUERY_LIMIT}&unit={unit}"


def geometry_digest(document: dict[str, Any]) -> str:
    """sha256 over `features` alone, canonically serialised.

    EXCLUDES `timeStamp` DELIBERATELY, and that exclusion is the point of the function. pygeoapi
    stamps each response with the request time in fixed-width ISO-8601, so a re-fetch of unchanged
    data differs in hash while matching in length — a raw-bytes pin would re-acquire forever and a
    size check would agree that nothing was wrong.

    `links` is excluded too, for a weaker reason: it carries paging hrefs that describe the request
    rather than the data. Nothing downstream reads them, and they are relative in every response.
    """
    canonical = json.dumps(document["features"], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def assert_document(unit: str, document: dict[str, Any]) -> None:
    """Assert a parsed response is the SIM 3292 unit this pipeline was measured against, or exit.

    FOUR INDEPENDENT CHECKS, because each can pass while another fails. The digest proves the bytes
    are the edition on record; the feature count refuses a truncated page, which nothing else can
    see since the response carries no `numberMatched`; the property schema identifies the product
    against its own FGDC field list; and the summed `spharea_km` is the publisher's own geodesic
    measurement, so it catches a document that parsed cleanly into geometry we did not expect.
    """
    if document.get("type") != "FeatureCollection":
        sys.exit(f"{unit}: response type is {document.get('type')!r}, expected 'FeatureCollection'")

    features = document.get("features", [])
    expected_count = FEATURE_COUNTS[unit]
    if len(features) != expected_count:
        sys.exit(f"{unit}: {len(features)} features, pinned to {expected_count} — a short count is "
                 f"a TRUNCATED page (the response carries no numberMatched to say so), and a long "
                 f"one is a republished map. Every extent figure on record assumes this count.")

    for index, feature in enumerate(features):
        missing = REQUIRED_PROPERTIES - set(feature.get("properties", {}))
        if missing:
            sys.exit(f"{unit}: feature {index} is missing {sorted(missing)} — the FGDC layer "
                     f"SIM3292_Global_Geology declares Unit/UnitDesc/SphArea_km, so this is not "
                     f"the published product's schema")
        if feature.get("geometry", {}).get("type") != "MultiPolygon":
            sys.exit(f"{unit}: feature {index} is a "
                     f"{feature.get('geometry', {}).get('type')!r}, expected 'MultiPolygon' — the "
                     f"ice extent is areal, and a point or line here would rasterise to nothing")

    total_area = sum(feature["properties"]["spharea_km"] for feature in features)
    expected_area = SPHERE_AREAS_KM2[unit]
    if abs(total_area - expected_area) > 1.0:
        sys.exit(f"{unit}: geodesic area sums to {total_area:,.1f} km², pinned to "
                 f"{expected_area:,.1f} — the publisher's own measurement disagrees, so this is a "
                 f"different map even if it parsed")

    digest = geometry_digest(document)
    if digest != GEOMETRY_DIGESTS[unit]:
        sys.exit(f"{unit}: geometry digest {digest} != pinned {GEOMETRY_DIGESTS[unit]} — the "
                 f"polygons changed. This is NOT a timeStamp difference (the digest excludes it); "
                 f"re-measure the extents before re-pinning.")


def fetch_unit(unit: str) -> dict[str, Any]:
    """GET one unit and parse it. Network only; every assertion lives in `assert_document`."""
    with fetch.open_url(unit_url(unit), timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def read_unit(unit: str) -> dict[str, Any]:
    """Parse the copy already on disk, or exit saying which file is missing."""
    path = unit_path(unit)
    if not path.exists():
        sys.exit(f"nothing to verify: {path} is not on disk")
    return json.loads(path.read_text(encoding="utf-8"))


def build_recipe() -> str:
    """Everything the outputs depend on besides the source itself, serialised for the sidecar.

    A PRODUCER DECLARES WHAT IT EMITTED. The host and query are here because a file on disk cannot
    say where it came from — pygeoapi's own `links` are relative — so without this the outputs are
    exactly as unreproducible as the hand-fetched scout copies they replace.
    """
    return json.dumps({
        "host": HOST,
        "collection": COLLECTION,
        "query_limit": QUERY_LIMIT,
        "units": {unit: {"features": FEATURE_COUNTS[unit],
                         "geometry_sha256": GEOMETRY_DIGESTS[unit],
                         "spharea_km2": SPHERE_AREAS_KM2[unit]}
                  for unit in UNITS},
    }, indent=2, sort_keys=True) + "\n"


def is_fresh(unit: str) -> bool:
    """Whether this unit can be skipped: on disk, parseable, and matching the pinned digest.

    Reads the FILE rather than the sidecar. The sidecar records what the producer meant to emit; the
    file is what a consumer will actually read, and a half-written or hand-edited one must not be
    called fresh because a JSON note beside it agrees with the module.
    """
    path = unit_path(unit)
    if not path.exists() or not recipe_path().exists():
        return False
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return geometry_digest(document) == GEOMETRY_DIGESTS[unit]


def write_unit(unit: str, document: dict[str, Any]) -> Path:
    """Write one unit's GeoJSON atomically, `timeStamp` stripped.

    The stamp is dropped rather than kept because it is the only part of the response that is not
    about Mars: keeping it would make two byte-identical acquisitions differ on disk, which is the
    same trap one layer down. What lands is stable, so a plain `diff` between runs means something.

    Written to `.part` and renamed, so a file under its final name is always complete — a crashed
    fetch must not leave a truncated document that parses.
    """
    stable = {key: value for key, value in document.items() if key != "timeStamp"}
    path = unit_path(unit)
    part = path.with_suffix(".json.part")
    part.write_text(json.dumps(stable, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    part.replace(path)
    return path


def build_parser() -> argparse.ArgumentParser:
    """The CLI, split out of `main` so its contract is testable without touching the network."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="fetch and assert, but write nothing")
    parser.add_argument("--verify", action="store_true",
                        help="re-assert the files already on disk; touches no network")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.verify:
        for unit in UNITS:
            assert_document(unit, read_unit(unit))
            print(f"verified {unit_path(unit)} ({FEATURE_COUNTS[unit]} features)", flush=True)
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for unit in UNITS:
        if not args.check and is_fresh(unit):
            print(f"{unit} fresh -> skip", flush=True)
            continue
        document = fetch_unit(unit)
        assert_document(unit, document)
        if args.check:
            print(f"{unit} ok: {FEATURE_COUNTS[unit]} features, digest matches", flush=True)
            continue
        print(f"wrote {write_unit(unit, document)}", flush=True)

    if not args.check:
        recipe_path().write_text(build_recipe(), encoding="utf-8")  # AFTER the units, so a crash
        print(f"wrote {recipe_path()}", flush=True)                 # leaves them stale not fresh
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
