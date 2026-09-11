"""Mars's sources: the blended DEM that *is* the heightfield, the two rasters behind the polar ice,
and the gazetteer.

Every module here answers for Mars alone, which is what the grouping asserts. `pipeline/acquire`
carries why that grouping is legitimate here and refused upstream.

There is no fusion input in this package and that is not an omission: Mars arrives pre-fused, so
`download_mars_dem` writes the heightfield itself rather than something a fuse stage combines.
"""
