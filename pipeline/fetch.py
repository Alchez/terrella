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

import urllib.request
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
