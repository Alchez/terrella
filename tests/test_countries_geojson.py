"""countries_geojson: the NE admin-0 polygons behind the globe's country layers.

The file was born as an invisible click-target layer and simplified accordingly
(0.05 deg Douglas-Peucker, ~5.5 km of allowed deviation). When the hover
highlight began stroking its rings as the visible gold outline
(web/src/lib/countryHighlight.ts), that premise silently died: at z8 the chords
cut ~18 px straight across bays (the blocky-coast report). The guard
here pins the successor premise — simplification error stays below one z8 pixel
at the equator — so nobody re-coarsens the file for size without meeting the
display requirement head-on.
"""

from pathlib import Path

from pipeline.compose import countries_geojson
from pipeline.tile.shade_planet import Z8_RES

# Metres per degree of latitude (equatorial circumference / 360): converts the
# Douglas-Peucker tolerance (degrees) into worst-case ground deviation.
METERS_PER_DEGREE = 40_075_016.686 / 360


class TestSimplifyTolerance:
    def test_error_stays_subpixel_at_the_top_zoom(self):
        """The hover outline traces the raster coastline, so its worst-case
        deviation must sit under one pixel of the sharpest tiles it overlays."""
        worst_case_deviation_m = countries_geojson.SIMPLIFY_DEG * METERS_PER_DEGREE
        assert worst_case_deviation_m <= Z8_RES


class TestOgrCommand:
    def test_command_carries_the_contract(self, subtests):
        """Subtests over one built command: the regression that matters is an edited flag list,
        which drops more than one pair at a time."""
        command = countries_geojson.ogr_command(Path("src.shp"), Path("out.tmp"))
        adjacent_pairs = set(zip(command, command[1:]))
        with subtests.test("simplify"):
            assert ("-simplify", str(countries_geojson.SIMPLIFY_DEG)) in adjacent_pairs
        with subtests.test("select ADMIN — the frontend join key"):
            assert ("-select", "ADMIN") in adjacent_pairs
        with subtests.test("RFC7946 — WGS84 lon/lat GeoJSON"):
            assert ("-lco", "RFC7946=YES") in adjacent_pairs
        with subtests.test("coordinate precision"):
            assert ("-lco", "COORDINATE_PRECISION=4") in adjacent_pairs

    def test_destination_precedes_source(self):
        """ogr2ogr's argument order is [options] DESTINATION SOURCE — swapped,
        it would happily overwrite the Natural Earth shapefile."""
        command = countries_geojson.ogr_command(Path("src.shp"), Path("out.tmp"))
        assert command[-2:] == ["out.tmp", "src.shp"]
