"""Fetch published data and reshape none of it: `data/raw/` is written here and nowhere else, and
`test_fetch.test_only_an_acquirer_reaches_a_server` makes that checkable rather than aspirational.

One module per source, owning that source's access quirks and the constraints its licence imposes.
Whether a fetch is even possible is a property of the publisher, not of us, which is why the awkward
cases (a keyless mirror, a token that authenticates one endpoint but not its file pool) are recorded
beside the download that needs them. `pipeline/__init__.py` has the rule for where a new module goes.

GROUPED BY BODY, WHICH IS TRUE HERE AND NOWHERE ELSE IN `pipeline/`. No source serves two planets,
so every acquirer answers for exactly one and `attribution.SOURCES` is flat for the same reason. The
stage packages stay grouped by stage because a body is data there: nothing under `fuse/`, `look/`,
`render/` or `tile/` branches on which planet it holds, and a directory cannot fail the way a
missing `bodies.Body` field does. Do not read this split as licence to repeat it upstream.

`install_geotools.sh` sits at this level and not under a body: it fetches a TOOL rather than a
dataset, so it answers for neither. Having several readers does not move a module out of here, and
`download_worldcover.py` and `download_glo30.py` are both read by two stages for their naming rules;
what sits above is the read side of a source nobody fetches there, which is `naturalearth.py`.
"""
