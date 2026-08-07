"""Download the OMEGA R1080 albedo map — the field that says how icy each pixel inside the extent is.

WHAT THIS IS AND IS NOT. Mars's polar white is an extent and an alpha. `download_sim3292.py`
acquires the extent, a geologic map; this acquires the alpha, a measured albedo field. They are
independent sources with independent terms, which is why one can move while the other waits.

LICENCE: UNDOCUMENTED, WHICH IS NOT THE SAME AS PERMITTED, and nothing here should be read as
settling it. The PDS3 label carries no rights field — PDS3 has no such field at all — and the
volume's `catalog/dataset.cat` records `CITATION_DESC = "N/A"`. The label's own DESCRIPTION says the
map "corresponds to the map that was produced and published by Ody et al. ([ODY_JGR2012], figure
7a)", i.e. a PI-team reproduction of a journal figure, which is the third-party-rights class ESA's
CC BY-SA 3.0 IGO release explicitly excludes rather than a borderline case. **Acquiring and
recording provenance is correct under every reading of those terms; publishing pixels derived from
it is the step that is not.** That step is `ATTRIBUTIONS.md`, the About page and the visitor note,
and none of them may cite this product until the terms are answered in writing.

THE PUBLISHER SHIPS HASHES, WHICH IS BETTER THAN ANYTHING THE OTHER ACQUIRERS HAD. The volume root
carries an md5 manifest over all 95 files, so freshness is keyed on the publisher's own digest
rather than on a byte count (`download_mars_dem`, forced to pin a size) or on a hash we compute of a
response that is not byte-stable (`download_sim3292`, defeated by a request timestamp). Two
independent oracles come out of it: our pinned digest says the bytes are the edition every ice
measurement was taken over, and the served manifest says the archive has not been re-published
underneath us.

THE MANIFEST IS A DOS-STYLE LISTING and must be parsed as one — backslash separators and uppercase
hex, because it was generated on Windows in 2014. A parser assuming `/` and lowercase silently
matches nothing, which reads exactly like a file that is not in the archive.

Output (data/raw/mars/omega/):
  albedo_r1080_equ_map.img   the raw PDS3 image, 207,360,000 bytes of LSB int16
  albedo_r1080_equ_map.lbl   its detached label — the scaling, the geometry and the sphere
  omega_params.json          the recipe: host, volume, manifest name and each product's digest

Idempotency: a product whose file is on disk and whose md5 matches the pin is skipped. `--verify`
re-hashes what is on disk without touching the network; `--check` fetches the manifest alone and
compares, downloading no image.

Usage:
  python3 -m pipeline.acquire.download_omega --verify   # re-hash what is on disk, no network
  python3 -m pipeline.acquire.download_omega --check    # fetch the manifest only, write nothing
  python3 -m pipeline.acquire.download_omega            # fetch what is missing or drifted
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from pipeline import fetch, paths

#: The PDS Geosciences node (NASA/WashU), NOT ESA's PSA. Which host served the bytes is part of the
#: licence question rather than a detail, so it is recorded here and in the sidecar.
HOST = "https://pds-geosciences.wustl.edu"
VOLUME = "mex/mex-m-omega-5-ddr-global-maps-v1"
#: The manifest's name carries its own release date, so a re-published archive arrives under a
#: different name rather than silently replacing this one.
MANIFEST = "mexomg_2000_140325.md5"

#: Each product's path INSIDE the volume, and the manifest key it appears under. The two differ only
#: in separator, and that difference is the whole reason `parse_manifest` exists.
PRODUCTS = ("albedo_r1080_equ_map.img", "albedo_r1080_equ_map.lbl")
VOLUME_SUBDIR = "mexomg_2000/data/albedo"

#: md5 as published by USGS/PDS, verified against the copies this project measured its ice on.
#: Lowercased here; the manifest serves them uppercase.
MD5 = {
    "albedo_r1080_equ_map.img": "3d61d54a2fda024cb27fb837694bd552",
    "albedo_r1080_equ_map.lbl": "9caa0e027ff40587983cbac123859c3d",
}

#: What the label must say for the extract's EPSG:4326 relabel to be honest. Read from the label
#: rather than transcribed into the extract, so a re-published product is an error here.
EXPECTED_LABEL = {
    "LINES": "7200",
    "LINE_SAMPLES": "14400",
    "SAMPLE_TYPE": "LSB_INTEGER",
    "SAMPLE_BITS": "16",
    "MAP_PROJECTION_TYPE": "SIMPLE CYLINDRICAL",
    "MAP_RESOLUTION": "40.0",
}


def data_dir() -> Path:
    """Where the volume's products land. A function rather than a constant, per `paths`."""
    return paths.DATA / "raw/mars/omega"


def product_path(name: str) -> Path:
    return data_dir() / name


def recipe_path() -> Path:
    return data_dir() / "omega_params.json"


def manifest_url() -> str:
    return f"{HOST}/{VOLUME}/{MANIFEST}"


def product_url(name: str) -> str:
    return f"{HOST}/{VOLUME}/{VOLUME_SUBDIR}/{name}"


def md5_of(path: Path) -> str:
    """md5 of a file, read in chunks — the image is 207 MB and need not be resident to be hashed."""
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_manifest(text: str) -> dict[str, str]:
    """`{basename: lowercase md5}` from the volume's DOS-style manifest.

    KEYED ON THE BASENAME, not the path, because the path is the part that is written in a foreign
    dialect: entries read `mexomg_2000\\data\\albedo\\albedo_r1080_equ_map.img`, with backslashes and
    uppercase hex. Matching on a POSIX path finds nothing at all, and finding nothing is
    indistinguishable from a file the archive does not carry.

    Basenames repeat across the volume's directories — the same product appears under `data`,
    `browse` and `extras` — so a caller must only ask about names it also knows the subdirectory of.
    The last entry for a name wins, and `assert_manifest` is what refuses a digest that disagrees
    with the pin, so an ambiguous name cannot pass silently.
    """
    digests: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        digest, path = parts
        digests[path.replace("\\", "/").rsplit("/", 1)[-1]] = digest.lower()
    return digests


def parse_label(text: str) -> dict[str, str]:
    """The PDS3 detached label as a flat `{KEY: value}`, units and quotes stripped.

    FLAT IS SAFE HERE AND IS CHECKED RATHER THAN ASSUMED: every data key in this label is unique,
    only `OBJECT`/`END_OBJECT` repeating, so nesting carries no information a consumer needs. A
    duplicate key would make one silently shadow the other, which is why `assert_label` refuses one.

    `3396.0 <KM>` becomes `3396.0` and `"SIMPLE CYLINDRICAL"` loses its quotes; a value continued on
    the next line (the DESCRIPTION block) keeps only its first line, which no caller here reads.
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key or key in ("OBJECT", "END_OBJECT") or key.startswith("^"):
            continue
        value = value.split("<")[0].strip().strip('"').strip()
        if key in values and values[key] != value:
            raise ValueError(f"{key} appears twice in the label with different values")
        values[key] = value
    return values


def assert_label(text: str) -> dict[str, str]:
    """Assert the label describes the product the extract and the ice grading were built on.

    THE SPHERE CHECK IS THE LOAD-BEARING ONE, AND IT IS NOT `download_mars_dem`'s. That acquirer
    holds its product's radius equal to `bodies.MARS.ground_radius_m`, because every Martian ground
    metre this pipeline computes divides by that number and it was taken from the DEM. OMEGA is
    published on a 3396.0 km sphere where the DEM uses 3396.19 km, and copying the equality check
    would refuse a correct product. Nothing here converts albedo to metres — the field is sampled by
    ANGLE — and on two SPHERES planetographic and planetocentric latitude coincide, so the two grids
    register exactly despite the 190 m difference in radius.

    What must hold is therefore weaker and different: the body is a true sphere (all three radii
    equal) on a simple-cylindrical degree grid. That is what makes the extract's EPSG:4326 relabel an
    identity on the angles, exactly as `fuse/relabel_mars` requires of the DEM. On an ellipsoid the
    same declaration would silently shift every latitude.
    """
    label = parse_label(text)
    for key, expected in EXPECTED_LABEL.items():
        if label.get(key) != expected:
            sys.exit(f"label {key} is {label.get(key)!r}, expected {expected!r} — this is not the "
                     f"product the ice alpha was measured on")
    radii = {axis: label.get(f"{axis}_AXIS_RADIUS") for axis in ("A", "B", "C")}
    if len(set(radii.values())) != 1 or None in radii.values():
        sys.exit(f"label declares radii {radii} — the EPSG:4326 relabel is an identity on the "
                 f"angles only for a TRUE SPHERE; on an ellipsoid it shifts every latitude silently")
    return label


def assert_manifest(text: str) -> None:
    """Assert the served manifest still agrees with the digests pinned here, or exit.

    The SECOND oracle, and it answers a question our own pin cannot: our digest says the bytes on
    disk are what we measured, and this says the archive still publishes those bytes. A re-published
    volume would otherwise be invisible until someone re-downloaded.
    """
    served = parse_manifest(text)
    for name, pinned in MD5.items():
        if name not in served:
            sys.exit(f"{name} is absent from {MANIFEST} — the volume was reorganised; re-derive the "
                     f"paths before trusting anything else here")
        if served[name] != pinned:
            sys.exit(f"{name}: the archive publishes md5 {served[name]}, pinned {pinned} — the "
                     f"product was re-published, so every ice level on record needs re-measuring")


def is_fresh(name: str) -> bool:
    """Whether this product can be skipped: on disk and hashing to the pin.

    Hashes the FILE rather than trusting the sidecar, on `download_sim3292.is_fresh`'s reasoning: the
    sidecar records what the producer meant to emit, and a truncated or hand-edited file must not be
    called fresh because a JSON note beside it agrees with the module.
    """
    path = product_path(name)
    return path.exists() and recipe_path().exists() and md5_of(path) == MD5[name]


def build_recipe() -> str:
    """Where these bytes came from, which no PDS product records about itself."""
    return json.dumps({
        "host": HOST,
        "volume": VOLUME,
        "manifest": MANIFEST,
        "subdir": VOLUME_SUBDIR,
        "products": {name: MD5[name] for name in PRODUCTS},
    }, indent=2, sort_keys=True) + "\n"


def fetch_manifest() -> str:
    with fetch.open_url(manifest_url(), timeout=120) as response:
        return response.read().decode("utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="fetch the manifest and compare; download no image")
    parser.add_argument("--verify", action="store_true",
                        help="re-hash the files already on disk; touches no network")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.verify:
        for name in PRODUCTS:
            path = product_path(name)
            if not path.exists():
                sys.exit(f"nothing to verify: {path} is not on disk")
            digest = md5_of(path)
            if digest != MD5[name]:
                sys.exit(f"{name}: md5 {digest} != pinned {MD5[name]}")
            print(f"verified {path} ({digest})", flush=True)
        assert_label(product_path("albedo_r1080_equ_map.lbl").read_text(encoding="utf-8"))
        print("label describes the product the ice alpha was measured on", flush=True)
        return 0

    assert_manifest(fetch_manifest())
    print(f"{MANIFEST}: both products match their pinned md5", flush=True)
    if args.check:
        return 0

    data_dir().mkdir(parents=True, exist_ok=True)
    for name in PRODUCTS:
        if is_fresh(name):
            print(f"{name} fresh -> skip", flush=True)
            continue
        result = fetch.download_one(product_url(name), product_path(name), timeout=600)
        if result.startswith("failed"):
            sys.exit(f"{name}: {result}")
        digest = md5_of(product_path(name))
        if digest != MD5[name]:
            sys.exit(f"{name}: downloaded md5 {digest} != pinned {MD5[name]}")
        # `download_one` resumes by EXISTENCE, so it reports 'skipped' for a file already on disk —
        # which is the ordinary path here when only the sidecar is missing. Say which happened
        # rather than "wrote": a stage that claims a transfer it did not make is how a hand-placed
        # file gets mistaken for an acquired one, and that is the whole defect this module closes.
        print(f"{'wrote' if result == 'ok' else 'kept'} {product_path(name)} ({digest})", flush=True)

    assert_label(product_path("albedo_r1080_equ_map.lbl").read_text(encoding="utf-8"))
    recipe_path().write_text(build_recipe(), encoding="utf-8")  # AFTER the products, so a crash
    print(f"wrote {recipe_path()}", flush=True)                 # leaves them stale not fresh
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
