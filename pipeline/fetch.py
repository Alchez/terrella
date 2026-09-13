"""The pipeline's HTTP identity — one home for the header every acquisition must send.

THIS MODULE EXISTS BECAUSE AN ANONYMOUS CLIENT IS A BLOCKED CLIENT. `urllib.request` sends
`User-Agent: Python-urllib/3.x` unless told otherwise, and that string is on the default block list
of every bot-protection edge. Measured against the Mars blend on 2026-08-04: the USGS mosaic host
sits behind Cloudflare and answers `Python-urllib/3.14` with **HTTP 403** while serving the identical
URL to any named agent. The failure is total — not a slow path, not a partial read — and it lands at
the first byte of a 10.6 GiB acquisition.

WHY A MODULE RATHER THAN A HEADER AT EACH CALL SITE. Nine call sites across seven modules reach for
HTTP, and a string that a second module needs is a string that gets copied. `open_url` is therefore
the only spelling: it takes the timeout the caller already had and returns the same context manager
`urlopen` did, so adopting it is a one-line change and *forgetting* it is what the scan in
`tests/test_fetch.py` refuses. A helper that merely offers the header would be a helper each new
acquisition is free to skip, and the skip is invisible until a host turns protection on.

WHY THE FAILURE IS WORSE THAN A 403 LOOKS. A blocked acquisition is discovered at the moment someone
tries to build a body, which is the least convenient moment there is, and it is indistinguishable at
a glance from the URL having rotted. Sending an identity also makes us legible to the publishers
whose bandwidth this pipeline spends in multi-gigabyte units — the polite reading of the same rule.

The agent string carries no contact URL yet, deliberately: inventing one would be a claim the project
cannot honour. When the repository is public, the URL belongs here, in this constant, and nowhere
else.
"""

import hashlib
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

#: Sent on every request this pipeline makes. Any descriptive value clears the default-agent block
#: lists; the version is here so a future block can be attributed to a change we made.
USER_AGENT = "terrella-pipeline/1.0"


def build_request(url: str, *, method: str = "GET") -> urllib.request.Request:
    """The request every caller should send, carrying the pipeline's identity.

    Separate from `open_url` only so a caller that must add its own headers has somewhere to start
    that is not a bare `Request`; nothing needs that today.
    """
    return urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})


def open_url(url: str, *, method: str = "GET", timeout: float) -> Any:
    """Open `url` with the pipeline's User-Agent, returning what `urlopen` returns.

    `timeout` is keyword-only and REQUIRED, which is the second half of what this module is for: the
    default is no timeout at all, so an unadorned `urlopen` against a stalled host hangs a pipeline
    stage forever rather than failing it. Every existing call site already passed one — making it
    required means the next one cannot quietly not.
    """
    return urllib.request.urlopen(build_request(url, method=method), timeout=timeout)


def download_one(url: str, dest: Path, *, timeout: float = 60,
                 absent_on_404: bool = False) -> str:
    """Stream `url` to `dest` atomically. Returns 'ok', 'skipped', 'absent' or 'failed: <reason>'.

    The one home for "stream to .part, size-check against Content-Length, atomically rename", so a
    file under its final name is always complete and `exists()` is a valid resume.

    `absent_on_404` MUST STAY DEFAULT-OFF. Most callers test `status.startswith("failed")`, so
    returning 'absent' to one of them turns a missing file into a silent success. It is passed only
    where a 404 is a real answer about the data rather than a fault: WorldCover's ocean cells, and
    the components Natural Earth ships for some layers and not others.
    """
    if dest.exists():
        return "skipped"
    part = dest.with_suffix(".part")
    try:
        with open_url(url, timeout=timeout) as response:
            expected = int(response.headers.get("Content-Length", -1))
            with open(part, "wb") as sink:
                shutil.copyfileobj(response, sink)
        actual = part.stat().st_size
        if expected != -1 and actual != expected:
            part.unlink()
            return f"failed: size mismatch ({actual} of {expected} bytes)"
        os.replace(part, dest)
        return "ok"
    except urllib.error.HTTPError as exc:
        part.unlink(missing_ok=True)
        if absent_on_404 and exc.code == 404:
            return "absent"
        return f"failed: {exc}"
    except Exception as exc:  # noqa: BLE001 — one tile's failure must not kill the pool
        part.unlink(missing_ok=True)
        return f"failed: {exc}"


def file_md5(path: Path) -> str:
    """md5 of a file on disk, streamed a megabyte at a time.

    md5 rather than something modern because it is what publishers ship, and the digest has to
    compare against theirs: a sha256 here makes every pin uncheckable. It guards against a truncated
    or substituted file, not an attacker.
    """
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def published_md5(url: str, name: str) -> str:
    """The digest a publisher ships in an `md5sum`-format sidecar, `<digest>  <name>`, or exit.

    The sidecar names its subject and the name is checked, so a rotted URL is reported as one rather
    than as a republished product.
    """
    with open_url(url, timeout=60) as response:
        text = response.read().decode("ascii").strip()
    fields = text.split()
    if len(fields) != 2 or fields[1] != name:
        sys.exit(f"{url}: expected '<md5>  {name}', got {text!r}: the checksum sidecar does not "
                 f"describe this product, so its digest cannot be compared to ours")
    return fields[0]


def assert_digest(path: Path, expected: str) -> str:
    """Assert the file on disk carries the pinned digest, returning it, or exit."""
    digest = file_md5(path)
    if digest != expected:
        sys.exit(f"{path.name}: md5 {digest} != pinned {expected}: the bytes on disk are not the "
                 f"published edition. Delete the file and re-run rather than re-pinning, since a "
                 f"truncated or substituted file looks exactly like this.")
    return digest
