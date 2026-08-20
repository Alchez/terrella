"""Terrella's data pipeline: what turns published elevation data into the rasters the site serves.

HOW THIS PACKAGE IS LAID OUT, and why nothing in it is grouped by planet: docs/pipeline.md § How
`pipeline/` is laid out. It is stated there and deliberately not restated here, because a rule kept
in two places is a rule that goes stale in one of them: this docstring and that section each
described the package as holding TWO kinds of thing, and each was still saying it on the day the top
level turned out to hold four.

Each sub-package's own `__init__.py` states what that package holds, which is a fact about itself
and so has exactly one home by construction.
"""
