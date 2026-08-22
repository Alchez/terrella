"""Fetch published data and reshape none of it: `data/raw/` is written here and nowhere else.

One module per source, owning that source's access quirks and the constraints its licence imposes.
Whether a fetch is even possible is a property of the publisher, not of us, which is why the awkward
cases (a keyless mirror, a token that authenticates one endpoint but not its file pool) are recorded
beside the download that needs them. `pipeline/__init__.py` has the rule for where a new module goes.
"""
