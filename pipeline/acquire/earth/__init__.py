"""Earth's sources: the two rasters that fuse into the heightfield, the four painted layers, and
the vectors.

Every module here answers for Earth alone, which is what the grouping asserts. `pipeline/acquire`
carries why that grouping is legitimate here and refused upstream.

WorldCover is Earth's and is NOT here: two stages read it for two different classes and neither is
an acquirer, so it has no module to own it and lives at `pipeline/worldcover.py` instead, next to
`naturalearth.py` under the same rule.
"""
