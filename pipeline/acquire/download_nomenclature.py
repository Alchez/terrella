"""Download the IAU/USGS gazetteer geometries — the named features a visitor can point at.

WHY THIS FILE AND NOT THE ONE THE DOWNLOAD PAGE OFFERS. The gazetteer publishes Mars twice. The
`GIS_Downloads` page lists `MARS_nomenclature_center_pts.zip`, which is one point per name;
`MARS_nomenclature_geometries.zip` is not listed anywhere on it and carries the OUTLINES. Only the
second can answer "what is under this finger", because a point has no interior to hit-test against.
It was found by paging the bucket rather than by reading the page, and a bucket listing is the only
route that names it.

LICENCE: public domain, and read at the product rather than off a web page. The archive ships
`metadata_nomenclature_polygons_MARS.xml`, whose `useconst` is "Public domain." and whose `distliab`
is "none"; `assert_licence` re-reads that field on every acquisition rather than trusting this
sentence, so a republished archive with different terms stops the pipeline instead of flowing into a
CC BY-SA 4.0 site unnoticed. The access constraint is about tooling, not rights: "GIS software is
required to view these data."

THE ARCHIVE IS REGENERATED AND ITS BYTES ARE NOT THE THING TO PIN. The bucket rebuilds on a nightly
cadence, and a zip carries member timestamps, so two builds of identical nomenclature differ as
bytes while describing the same 1,717 features. Pinning the zip would re-acquire forever, which is
the `download_sim3292` timeStamp trap in a different costume. Freshness is keyed on the sha256 of
each EXTRACTED MEMBER instead: those are the shapefile's own bytes, and they hold still across a
rebuild that changed nothing. (Measured when this was written: the live object's `Last-Modified` was
the previous day's build and its `Content-Length` matched the copy on disk exactly.)

THE ENCODING FIX IS WRITTEN BESIDE THE DATA, NOT LEFT AS A RULE FOR EVERY READER. The DBF is UTF-8
and the archive ships no `.cpg`, so GDAL falls back to Latin-1 and 64 features decode as mojibake --
`Eugène` becomes `EugÃ¨ne` -- silently, in the strings that end up on screen. `SHAPE_ENCODING=UTF-8`
fixes it per reader; a `.cpg` file fixes it for every reader that will ever open this shapefile,
including ones nobody has written. So `extract` writes one, and that is the whole reason it does.

LONGITUDE: THE CENTRES AND THE GEOMETRY DO NOT SHARE A RANGE, and only the second is surprising.
Every `center_lon` is east-positive 0-360. The POLYGONS reach -180 to +360.34, because a feature
crossing the prime meridian is drawn with its vertices continuing past the seam rather than wrapped
-- so the outlines span 540 degrees of a 360-degree planet. A consumer that rasterises on either
convention alone silently drops the features that cross; span 540 and fold onto one window. The
publisher's own `min_lon`/`max_lon` fields reproduce that extent exactly, which is what
`assert_layer` checks rather than re-deriving it from geometry.

THE COORDINATES RIDE THE MDIM 2.1 CONTROL NETWORK, which is the FRAME and not the 232 m mosaic this
project declined for its filtered-away albedo -- the two share a name and nothing else. That the
frame agrees with the blend these outlines are drawn over is measured rather than assumed: over 477
named craters the median rim-minus-floor is 1208 m and holds for 98.1% of them, and it collapses to
chance when the centres are shifted 50 km, so the two frames agree well inside 25 km. The shifted
control is what makes the agreement mean anything; without it the test passes on any frame at all.

Output (data/raw/mars/nomenclature/):
  MARS_nomenclature_geometries.zip   the published archive, kept as fetched
  MARS_nomenclature_poly.{shp,shx,dbf,prj,cpg}   1,717 named areal features
  MARS_nomenclature_line.{shp,shx,dbf,prj,cpg}   203 named linear features
  metadata_nomenclature_polygons_MARS.xml        the FGDC record carrying the licence
  nomenclature_params.json                       the recipe: host, member digests, counts

Idempotency: an acquisition whose extracted members all match their pinned digests is skipped.
`--verify` re-asserts what is on disk without touching the network; `--check` reads the live
object's headers and compares them to the archive on disk, downloading nothing.

Usage:
  python3 -m pipeline.acquire.download_nomenclature --verify   # re-assert on-disk copy, no network
  python3 -m pipeline.acquire.download_nomenclature --check    # HEAD the source, write nothing
  python3 -m pipeline.acquire.download_nomenclature            # fetch and extract if not fresh
"""

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

from pipeline import datasets, fetch

#: The regional endpoint rather than the global alias. Both answer today; naming the region means a
#: recorded recipe says WHERE the bytes came from, which the global alias leaves ambiguous.
HOST = "https://asc-planetarynames-data.s3.us-west-2.amazonaws.com"
ARCHIVE = "MARS_nomenclature_geometries.zip"

#: The FGDC record, and the only member that is neither geometry nor its index. Shipped TWICE in the
#: archive under one name -- once per layer group -- and verified byte-identical, so extraction
#: overwrites it with itself and the duplicate is harmless rather than ambiguous.
METADATA_MEMBER = "metadata_nomenclature_polygons_MARS.xml"

#: sha256 of each extracted member. THE FRESHNESS KEY, and deliberately not the zip's own hash --
#: see the module note on regeneration. The two `.prj` members are byte-identical to each other,
#: which is why one digest appears twice.
MEMBER_DIGESTS = {
    "MARS_nomenclature_poly.shp": "551ab23cffae4891ac23d76645323c0f99a856a5358ae8056dbcecae70f86907",
    "MARS_nomenclature_poly.shx": "77e5b6d27433d1c3eaeb4d3502422419c0cb257d9d7e164d245286f6699999a1",
    "MARS_nomenclature_poly.dbf": "b3c2f701ef484cf7fd79e7cd59a5669e9265e6ff64a6fedd2601c7ed8706293b",
    "MARS_nomenclature_poly.prj": "50ddbbfcb902fe00f6cfe5be39c1f1e64d53ddb1102bfde75d587fc3c2ff91b3",
    "MARS_nomenclature_line.shp": "0c28f2e1403e0e5a0de3b4adb453fd2aa0913d7e990cd03990a9e4ddee5fa97c",
    "MARS_nomenclature_line.shx": "2da80097c91854fe2da4a5541bca2c58e324b17be99400d870d267e862a7ddf2",
    "MARS_nomenclature_line.dbf": "10b931cfc5903a9c347d6f18755dfe8a7c0218cf52991acd1ab46a6e6990d13d",
    "MARS_nomenclature_line.prj": "50ddbbfcb902fe00f6cfe5be39c1f1e64d53ddb1102bfde75d587fc3c2ff91b3",
    METADATA_MEMBER: "5e0c303fa94618f127e13ef02b3ca1b2da83f0fff8a436c0bbdf54b2c5cb6f1e",
}

#: The two layers, and what each is for. Areal features are what hit-testing lands on; the linear
#: ones (valles, fossae, catenae) carry names a search index wants and no interior to point at.
LAYERS = ("poly", "line")

#: Pinned so a truncated extraction or a republished catalogue is an error rather than a quietly
#: smaller map. Every feature is IAU-adopted, so this only moves when the IAU adopts names.
FEATURE_COUNTS = {"poly": 1717, "line": 203}

#: The publisher's own longitude bounds, summarised per layer as (min of `min_lon`, max of
#: `max_lon`). AN INDEPENDENT ORACLE OVER THE DIGEST, and the one that matters most: it is the
#: 540-degree span from the module note, so a republished file that normalised longitudes into
#: 0-360 would pass every digest-shaped check and silently break the fold every consumer does.
LONGITUDE_BOUNDS = {"poly": (-180.0000, 360.3366), "line": (-138.2220, 358.9187)}

#: Centres east of 180, per layer. A second, cheaper reading of the same convention question: the
#: centres are uniformly east-positive where the geometry is not, and a file that switched the
#: CENTRES to -180..180 would leave the bounds above untouched.
CENTRES_EAST_OF_180 = {"poly": 1047, "line": 118}

#: The DBF schema this pipeline reads. `origin` is here because it is the card's entire content on a
#: body with no heroes -- the IAU's own etymology, populated for every feature in both layers -- and
#: a schema change that dropped it would otherwise surface as blank panels.
REQUIRED_FIELDS = frozenset({
    "name", "clean_name", "origin", "diameter", "type", "code", "link",
    "center_lon", "center_lat", "min_lon", "max_lon", "approval",
})

#: The shape of the gazetteer's own per-feature page. PINNED BECAUSE THE SITE SENDS READERS THERE:
#: `web/scripts/gen_feature_index.py` copies this field verbatim into a tracked artifact, so a
#: republished catalogue that moved its host or its path would ship a dead link per feature -- and a
#: URL is the one field whose breakage is invisible to everything downstream of it, since a wrong
#: address serialises, type-checks and renders exactly like a right one.
FEATURE_URL = re.compile(r"^http://planetarynames\.wr\.usgs\.gov/Feature/\d+$")

#: The use constraint the FGDC record must still carry. Asserted rather than remembered, because a
#: licence claim in a docstring is exactly the kind that outlives its source.
USE_CONSTRAINT = "Public domain."


def archive_path() -> Path:
    """Where the published zip lives once fetched. A function rather than a constant, per `paths`."""
    return datasets.mars_nomenclature() / ARCHIVE


def layer_path(layer: str, suffix: str = "shp") -> Path:
    """One extracted layer's component, e.g. `MARS_nomenclature_poly.dbf`."""
    return datasets.mars_nomenclature() / f"MARS_nomenclature_{layer}.{suffix}"


def recipe_path() -> Path:
    """The recipe sidecar, beside the outputs it describes."""
    return datasets.mars_nomenclature() / "nomenclature_params.json"


def archive_url() -> str:
    """The object's URL. Recorded here because a zip on disk cannot say where it came from."""
    return f"{HOST}/{ARCHIVE}"


def digest_of(data: bytes) -> str:
    """sha256, hex."""
    return hashlib.sha256(data).hexdigest()


def extract(archive: Path) -> list[Path]:
    """Unpack every pinned member, then write the `.cpg` files the archive does not ship.

    EVERY DIGEST IS CHECKED BEFORE ANY MEMBER LANDS, in two passes, and the second pass is the
    point. Verifying and writing in one loop refuses the tampered archive just as loudly, but by
    then every member sorting ahead of the bad one has already overwritten a good extraction —
    measured, with a one-bit flip in `poly.dbf`: four `line` files landed before the guard fired.
    That leaves a directory holding half of one edition and half of another, which is the shape this
    repo has been bitten by before: a partial state that reads as a complete one.

    The `.cpg` is written LAST and is this function's only invention: everything else on disk is the
    publisher's, and the one file that is ours exists to stop every future reader of this shapefile
    from having to know about `SHAPE_ENCODING`. See the module note.
    """
    written: list[Path] = []
    with zipfile.ZipFile(archive) as bundle:
        members = {info.filename for info in bundle.infolist()}
        unexpected = members - set(MEMBER_DIGESTS)
        missing = set(MEMBER_DIGESTS) - members
        if missing or unexpected:
            sys.exit(f"{archive.name}: members are not the published set — missing "
                     f"{sorted(missing)}, unexpected {sorted(unexpected)}. The archive was "
                     f"restructured; re-scout it before re-pinning.")
        verified: dict[str, bytes] = {}
        for name, expected in sorted(MEMBER_DIGESTS.items()):
            data = bundle.read(name)
            actual = digest_of(data)
            if actual != expected:
                sys.exit(f"{name}: sha256 {actual} != pinned {expected} — the gazetteer was "
                         f"republished. Re-measure the counts and bounds in this module before "
                         f"re-pinning; every coverage figure on record assumes this edition. "
                         f"Nothing was extracted, so what is on disk is still the pinned edition.")
            verified[name] = data
    for name, data in verified.items():
        destination = datasets.mars_nomenclature() / name
        part = destination.with_suffix(destination.suffix + ".part")
        part.write_bytes(data)
        part.replace(destination)
        written.append(destination)
    for layer in LAYERS:
        codepage = layer_path(layer, "cpg")
        codepage.write_text("UTF-8", encoding="ascii")
        written.append(codepage)
    return written


def read_attributes(layer: str) -> list[dict[str, str]]:
    """The layer's DBF rows, decoded through the `.cpg` this module wrote.

    CSV rather than GeoJSON on purpose: every property checked here is an attribute, and asking OGR
    for geometry would serialise 1,717 outlines to answer questions none of them bear on.

    DECODED EXPLICITLY RATHER THAN BY `text=True`, because the failure this module exists to prevent
    is an encoding failure. Letting the subprocess wrapper decode raises `UnicodeDecodeError` from
    inside `subprocess.py`, pointing at a line of the standard library instead of at the missing
    `.cpg` that actually caused it -- which is precisely the diagnosis a reader needs here and the
    one a traceback destroys. Found by mutation: every layer guard below was reachable only after
    this, because a mutated shapefile crashed here first and exited non-zero for the wrong reason.
    """
    path = layer_path(layer)
    if not path.exists():
        sys.exit(f"nothing to read: {path} is not on disk")
    codepage = layer_path(layer, "cpg")
    if not codepage.exists():
        sys.exit(f"{codepage.name} is missing — without it GDAL reads this UTF-8 DBF as Latin-1 and "
                 f"64 features decode to mojibake. Re-run the acquirer; it writes this file.")
    # EVERY FIELD, NOT `-select REQUIRED_FIELDS`. Naming the fields makes OGR fail the whole read
    # when one is absent, which is the exact condition `assert_layer`'s schema check exists to
    # report -- so the guard could never fire, and a dropped field surfaced as a CalledProcessError
    # traceback instead of the sentence naming it. Reading everything costs one more column set and
    # leaves the diagnosis where it belongs.
    completed = subprocess.run(
        ["ogr2ogr", "-f", "CSV", "/vsistdout/", str(path)], capture_output=True, check=False,
    )
    if completed.returncode != 0:
        sys.exit(f"{path.name}: ogr2ogr could not read the layer "
                 f"({completed.stderr.decode('utf-8', 'replace').strip()[:300]})")
    raw = completed.stdout
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        sys.exit(f"{path.name}: OGR returned bytes that are not UTF-8 ({exc}) — the DBF's declared "
                 f"encoding disagrees with its contents, so every name and origin string read from "
                 f"it is suspect. Check {codepage.name} against the shapefile it sits beside.")
    return list(csv.DictReader(io.StringIO(decoded)))


def assert_layer(layer: str, rows: list[dict[str, str]]) -> None:
    """Assert one layer is the edition every downstream figure was measured over, or exit.

    FIVE CHECKS THAT CAN EACH PASS WHILE ANOTHER FAILS. The count refuses a truncated or grown
    catalogue; the schema identifies the product by its own field list; `origin` being populated
    everywhere is what a body with no heroes puts in its detail card, so an empty one is a blank
    panel rather than an error; `link` is where that card sends a reader next, and a URL is the one
    field whose breakage renders exactly like a working one; and the two longitude readings catch a
    re-projection that every byte-shaped check would wave through.
    """
    expected_count = FEATURE_COUNTS[layer]
    if len(rows) != expected_count:
        sys.exit(f"{layer}: {len(rows)} features, pinned to {expected_count} — a short count is a "
                 f"truncated extraction and a long one is a catalogue the IAU has added to. Either "
                 f"way the coverage measurements on record describe a different file.")

    missing = REQUIRED_FIELDS - set(rows[0])
    if missing:
        sys.exit(f"{layer}: DBF is missing {sorted(missing)} — this is not the gazetteer's "
                 f"published schema, so nothing downstream can trust the fields it does have")

    blank = [row["name"] for row in rows if not (row.get("origin") or "").strip()]
    if blank:
        sys.exit(f"{layer}: {len(blank)} feature(s) carry no `origin`, e.g. {blank[:3]} — that "
                 f"field is the entire content of Mars's detail card, and a blank one is a panel "
                 f"that opens saying nothing")

    astray = [row["name"] for row in rows if not FEATURE_URL.match((row.get("link") or "").strip())]
    if astray:
        sys.exit(f"{layer}: {len(astray)} feature(s) carry a `link` that is not a gazetteer feature "
                 f"page, e.g. {astray[:3]} — the detail card sends readers to that address, and a "
                 f"wrong one renders identically to a right one all the way to the click")

    low, high = min(float(row["min_lon"]) for row in rows), max(float(row["max_lon"]) for row in rows)
    pinned_low, pinned_high = LONGITUDE_BOUNDS[layer]
    if abs(low - pinned_low) > 0.001 or abs(high - pinned_high) > 0.001:
        sys.exit(f"{layer}: longitude bounds {low:.4f}..{high:.4f}, pinned to "
                 f"{pinned_low:.4f}..{pinned_high:.4f} — the outlines no longer span what they did. "
                 f"A file normalised into 0-360 reads as correct everywhere else and silently drops "
                 f"every feature that crosses the seam.")

    east = sum(1 for row in rows if float(row["center_lon"]) > 180.0)
    if east != CENTRES_EAST_OF_180[layer]:
        sys.exit(f"{layer}: {east} centres east of 180, pinned to {CENTRES_EAST_OF_180[layer]} — "
                 f"the centres have changed convention, which the bounds check above cannot see")


def assert_licence() -> None:
    """Re-read the shipped FGDC record's use constraint, or exit.

    THE TERMS COME FROM THE PRODUCT ON EVERY RUN, not from this module's docstring. A republished
    archive that changed its licence is otherwise indistinguishable from one that did not, and the
    consequence lands in the site's own CC BY-SA 4.0 rather than here.
    """
    path = datasets.mars_nomenclature() / METADATA_MEMBER
    if not path.exists():
        sys.exit(f"nothing to verify: {path} is not on disk")
    record = path.read_text(encoding="utf-8", errors="replace")
    found = re.search(r"<useconst>(.*?)</useconst>", record, re.DOTALL)
    if not found:
        sys.exit(f"{path.name}: no <useconst> element — the FGDC record no longer states its use "
                 f"constraints, so this archive's terms are undocumented rather than permissive")
    stated = found.group(1).strip()
    if stated != USE_CONSTRAINT:
        sys.exit(f"{path.name}: use constraint is {stated!r}, pinned to {USE_CONSTRAINT!r} — the "
                 f"gazetteer's terms changed. Nothing may be published from it until the new terms "
                 f"are read against the site's CC BY-SA 4.0.")


def build_recipe() -> str:
    """Everything the outputs depend on besides the source itself, serialised for the sidecar."""
    return json.dumps({
        "host": HOST,
        "archive": ARCHIVE,
        "url": archive_url(),
        "member_sha256": dict(sorted(MEMBER_DIGESTS.items())),
        "layers": {layer: {"features": FEATURE_COUNTS[layer],
                           "longitude_bounds": list(LONGITUDE_BOUNDS[layer]),
                           "centres_east_of_180": CENTRES_EAST_OF_180[layer]}
                   for layer in LAYERS},
        "dbf_encoding": "UTF-8, declared by a .cpg this pipeline writes; the archive ships none",
        "use_constraints": USE_CONSTRAINT,
    }, indent=2, sort_keys=True) + "\n"


def is_fresh() -> bool:
    """Whether the acquisition can be skipped: every pinned member on disk and matching its digest.

    Reads the FILES rather than the sidecar, for `download_sim3292`'s reason: the sidecar records
    what the producer meant to emit, the files are what a consumer will actually open, and a
    half-written extraction must not be called fresh because a JSON note beside it agrees.
    """
    if not recipe_path().exists():
        return False
    for name, expected in MEMBER_DIGESTS.items():
        member = datasets.mars_nomenclature() / name
        if not member.exists() or digest_of(member.read_bytes()) != expected:
            return False
    return all(layer_path(layer, "cpg").exists() for layer in LAYERS)


def check_source() -> int:
    """HEAD the live object and report it against the copy on disk. Downloads nothing."""
    with fetch.open_url(archive_url(), method="HEAD", timeout=60) as response:
        length = response.headers.get("Content-Length")
        modified = response.headers.get("Last-Modified")
    local = archive_path()
    local_size = local.stat().st_size if local.exists() else None
    print(f"source: {archive_url()}", flush=True)
    print(f"  Content-Length {length}, Last-Modified {modified}", flush=True)
    print(f"  on disk: {local_size if local_size is not None else 'absent'}", flush=True)
    # A size match is NOT proof the bytes are the same build -- the archive is regenerated and a
    # rebuild of unchanged nomenclature is the same length. It is only a cheap disagreement check.
    if local_size is not None and length is not None and int(length) != local_size:
        print("  DIFFERS in length — the catalogue changed; re-acquire and re-pin", flush=True)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The CLI, split out of `main` so its contract is testable without touching the network."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="read the live object's headers and compare; write nothing")
    parser.add_argument("--verify", action="store_true",
                        help="re-assert the files already on disk; touches no network")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.verify:
        # THE SEMANTIC CHECKS RUN EVEN WHEN A DIGEST HAS MOVED, and the order is the point. A digest
        # says "this is the edition we pinned"; the layer checks say "this edition still has the
        # properties everything downstream assumes". Exiting on the first drifted digest would make
        # the second question unanswerable exactly when it is being asked -- on a re-pin, where what
        # you need is the full delta rather than the first difference.
        assert_licence()
        for layer in LAYERS:
            assert_layer(layer, read_attributes(layer))
            print(f"verified {layer_path(layer)} ({FEATURE_COUNTS[layer]} features)", flush=True)
        drifted = [name for name, expected in sorted(MEMBER_DIGESTS.items())
                   if not (datasets.mars_nomenclature() / name).exists()
                   or digest_of((datasets.mars_nomenclature() / name).read_bytes()) != expected]
        if drifted:
            print(f"✗ {len(drifted)} member(s) do not match their pinned digest:", flush=True)
            for name in drifted:
                print(f"    {name}", flush=True)
            print("  The assertions above describe what is ON DISK, which is not the pinned "
                  "edition. Re-pin only after reading what moved.", flush=True)
            return 1
        print(f"✓ {len(MEMBER_DIGESTS)} member(s) match their pinned digest", flush=True)
        return 0

    if args.check:
        return check_source()

    datasets.mars_nomenclature().mkdir(parents=True, exist_ok=True)
    if is_fresh():
        print(f"{ARCHIVE} fresh -> skip", flush=True)
        return 0

    status = fetch.download_one(archive_url(), archive_path(), timeout=300)
    if status.startswith("failed"):
        sys.exit(f"{ARCHIVE}: {status}")
    print(f"{ARCHIVE}: {status}", flush=True)

    for path in extract(archive_path()):
        print(f"wrote {path}", flush=True)
    assert_licence()
    for layer in LAYERS:
        assert_layer(layer, read_attributes(layer))

    recipe_path().write_text(build_recipe(), encoding="utf-8")  # AFTER the members, so a crash
    print(f"wrote {recipe_path()}", flush=True)                 # leaves them stale rather than fresh
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
