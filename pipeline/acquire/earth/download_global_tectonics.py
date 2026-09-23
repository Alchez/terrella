"""Download the global tectonics plate-boundary vectors from their Zenodo deposit.

The deposit's licence is re-read on every run and refuses anything but CC-BY 4.0, because Zenodo
serves it as a machine-readable field and a deposit whose terms change would otherwise flow through
into a site that credits it wrongly.

Zenodo rather than the authors' GitHub tree, and taking the GitHub copy is the temptation to name:
it is the same data, it is easier to fetch, and it carries a verbatim GPLv3 `LICENSE`, a copyleft
software licence whose compatibility with the site's own share-alike output runs the other way.
Terms come from whoever publishes the product being downloaded.

The deposit is one archive holding rasters this project has no use for, so the run keeps `LAYER`
and discards the rest, paying the whole archive in transfer whenever the raw directory is absent.

Idempotent: a raw directory that already exists is skipped, and a failed fetch leaves no directory
behind.

Usage: python -m pipeline.acquire.earth.download_global_tectonics
"""

import json
import shutil
import sys
import zipfile
from pathlib import Path

from pipeline import datasets
from pipeline.fetch import assert_digest, download_one, open_url

RECORD = "6586972"
RECORD_URL = f"https://zenodo.org/api/records/{RECORD}"

#: The only licence this data may arrive under, as Zenodo spells it. Anything else is a decision
#: about what the site may publish rather than a download to retry, which is why this exits.
REQUIRED_LICENCE = "cc-by-4.0"

#: The layer this project draws, by the basename its components share inside the archive.
#:
#: The authors' GitHub tree calls the same layer `plate_boundaries` and this archive calls it
#: `boundaries`, at identical size. Reading the GitHub name here and "correcting" this is the
#: temptation: it makes every component vanish, which `members` reports rather than letting an
#: empty layer through. The name that matters is the one inside the product being downloaded.
LAYER = "boundaries"
REQUIRED = ("shp", "shx", "dbf", "prj")
OPTIONAL = ("cpg", "qmd")

#: The deposit's own readme, kept because the archive carries no licence file and this is where the
#: authors state how they want the data cited.
README = "readme.txt"

#: Kept beside the data because no licence file travels inside the archive, and a raw directory that
#: cannot say what it may be used for is one nobody can act on.
RECORD_SIDECAR = "zenodo-record.json"


def record() -> dict:
    """The deposit's metadata, or exit. Carries the licence, the DOI and the archive's digest."""
    with open_url(RECORD_URL, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def archive_entry(metadata: dict) -> dict:
    """The single archive file the deposit publishes, asserted to be single.

    A deposit that grows a second file is one whose layout has changed, and picking the first of two
    would silently take whichever Zenodo happened to list first.
    """
    files = metadata.get("files", [])
    if len(files) != 1:
        sys.exit(f"record {RECORD} publishes {len(files)} files, expected one archive: "
                 f"{[entry.get('key') for entry in files]}")
    return files[0]


def check_licence(metadata: dict) -> str:
    """The deposit's own licence id, asserted against the one this project may take."""
    licence = (metadata.get("metadata", {}).get("license") or {}).get("id")
    if licence != REQUIRED_LICENCE:
        sys.exit(f"record {RECORD} is published under {licence!r}, not {REQUIRED_LICENCE!r}: a "
                 f"changed licence is a decision about what the site may publish, not a download "
                 f"to retry.")
    return licence


def members(archive: zipfile.ZipFile) -> dict[str, str]:
    """Each wanted component against its path inside the archive, or exit.

    The archive's internal layout is not pinned, so components are found by basename rather than by
    a path this would have to guess. Exactly one match per component is the assertion that makes
    that safe: a second copy under another directory is an archive whose shape has changed, and
    taking either one of them would be a coin toss nothing downstream could see.
    """
    wanted = {f"{LAYER}.{component}": component for component in (*REQUIRED, *OPTIONAL)}
    wanted[README] = README
    found: dict[str, list[str]] = {}
    for name in archive.namelist():
        # `__MACOSX` holds an AppleDouble twin of every member, a few hundred bytes each under
        # `._<original>`. Those basenames do not collide with the ones below, and skipping the
        # directory keeps that a fact rather than a coincidence a changed comparison could undo.
        if name.startswith("__MACOSX/"):
            continue
        component = wanted.get(Path(name).name)
        if component is not None:
            found.setdefault(component, []).append(name)

    duplicated = {component: paths for component, paths in found.items() if len(paths) > 1}
    if duplicated:
        sys.exit(f"the archive holds one name under more than one path, so which is the layer is a "
                 f"guess: {duplicated}")
    missing = [component for component in REQUIRED if component not in found]
    if missing:
        sys.exit(f"the archive has no {LAYER} components {missing}: the deposit's layout has "
                 f"changed. This layer is `{LAYER}` here and `plate_boundaries` in the authors' "
                 f"GitHub tree, so check which name the archive carries before re-pinning.")
    return {component: paths[0] for component, paths in found.items()}


def extract(archive_path: Path, destination: Path) -> list[str]:
    """The wanted components out of the archive and into `destination`, flattened.

    Flattened deliberately: the archive's directory names are its own, and a raw layer addressed
    through `datasets.py` should not inherit them.
    """
    written = []
    with zipfile.ZipFile(archive_path) as archive:
        for component, inside in sorted(members(archive).items()):
            name = README if component == README else f"{LAYER}.{component}"
            with archive.open(inside) as source, open(destination / name, "wb") as sink:
                shutil.copyfileobj(source, sink)
            written.append(name)
    return written


def main() -> int:
    destination = datasets.global_tectonics()
    if destination.is_dir():
        print(f"skip {destination} (exists)", flush=True)
        return 0

    metadata = record()
    licence = check_licence(metadata)
    entry = archive_entry(metadata)
    digest = entry["checksum"].split(":", 1)[-1]
    print(f"record {RECORD} doi {metadata.get('doi')} licence {licence}", flush=True)
    print(f"fetch {entry['key']} ({entry['size']:,} B) — the archive is discarded after extraction",
          flush=True)

    part = destination.with_name(destination.name + ".part")
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir(parents=True)
    archive_path = part / entry["key"]
    status = download_one(entry["links"]["self"], archive_path, timeout=600)
    if status not in ("ok", "skipped"):
        shutil.rmtree(part, ignore_errors=True)
        sys.exit(f"{entry['key']}: {status}")
    assert_digest(archive_path, digest)

    written = extract(archive_path, part)
    archive_path.unlink()
    (part / RECORD_SIDECAR).write_text(json.dumps(
        {"record": RECORD, "doi": metadata.get("doi"), "licence": licence,
         "title": metadata.get("metadata", {}).get("title"),
         "publication_date": metadata.get("metadata", {}).get("publication_date"),
         "archive": entry["key"], "archive_md5": digest, "layer": LAYER,
         "components": written}, indent=1) + "\n")
    part.replace(destination)
    print(f"done: {destination} ({len(written)} files, {licence})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
