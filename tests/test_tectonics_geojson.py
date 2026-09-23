"""tectonics_geojson: the plate-boundary lines behind the globe's tectonics overlay.

Every guard here exists because its failure is silent. A respelt `inferred` ships unconstrained
segments as ordinary boundaries, and a changed `level` moves what the globe's zoom fade hides, and
both reach a visitor as a different globe rather than as anything a log would show.
"""

import itertools
import re
from pathlib import Path

import pytest
import shapefile

from pipeline import bodies, paths
from pipeline.compose import countries_pmtiles, tectonics_geojson

#: Metres per degree of latitude, for turning a coordinate precision into ground error.
METERS_PER_DEGREE = 40_075_016.686 / 360


class TestCoordinatePrecision:
    def test_rounding_error_stays_subpixel_at_the_top_zoom(self):
        """The lines are drawn over the relief, so the coordinates they are rounded to must not
        move them by a pixel of the sharpest tiles they overlay."""
        worst_case_deviation_m = 10 ** -tectonics_geojson.COORDINATE_PRECISION * METERS_PER_DEGREE
        assert worst_case_deviation_m <= bodies.EARTH.map_units_per_pixel


class TestOgrCommand:
    def test_command_carries_the_contract(self, subtests):
        command = tectonics_geojson.ogr_command(Path("src.shp"), Path("out.tmp"))
        adjacent_pairs = set(itertools.pairwise(command))
        with subtests.test("select — the styling attribute and the zoom lever"):
            assert ("-select", "type,level") in adjacent_pairs
        with subtests.test("RFC7946 — WGS84 lon/lat GeoJSON"):
            assert ("-lco", "RFC7946=YES") in adjacent_pairs
        with subtests.test("coordinate precision"):
            assert ("-lco", f"COORDINATE_PRECISION={tectonics_geojson.COORDINATE_PRECISION}") in adjacent_pairs

    def test_no_simplification_is_requested(self):
        """The source is schematic already and the globe's own `tolerance` thins per zoom. A
        `-simplify` added here would move the lines at every zoom rather than the far ones."""
        assert "-simplify" not in tectonics_geojson.ogr_command(Path("s.shp"), Path("o.tmp"))

    def test_destination_precedes_source(self):
        """ogr2ogr's order is [options] DESTINATION SOURCE. Swapped, it overwrites the shapefile."""
        command = tectonics_geojson.ogr_command(Path("src.shp"), Path("out.tmp"))
        assert command[-2:] == ["out.tmp", "src.shp"]

    def test_inferred_segments_are_left_out_of_the_output(self, subtests):
        """The globe draws only boundaries the source states as observed.

        A `-where` rather than a style filter, so the 19 unconstrained segments are absent from the
        served file instead of fetched and then hidden.
        """
        command = tectonics_geojson.ogr_command(Path("src.shp"), Path("out.tmp"))
        adjacent_pairs = set(itertools.pairwise(command))
        clause = next(value for flag, value in adjacent_pairs if flag == "-where")
        with subtests.test("the clause is built from the two names, not from their spellings"):
            assert tectonics_geojson.TYPE_FIELD in clause
            assert tectonics_geojson.INFERRED in clause
        with subtests.test("it excludes rather than selects"):
            assert "!=" in clause or "NOT" in clause.upper()


class TestTheVocabularyTheFilterDependsOn:
    def test_the_excluded_value_is_one_the_source_declares(self):
        """`INFERRED` has two jobs and they must agree.

        `check_vocabulary` refuses a value declared but absent from the data, so dropping it from
        `TYPES` on the grounds that the globe no longer draws it stops the pipeline; leaving `TYPES`
        alone while respelling `INFERRED` makes the `-where` exclude nothing, and that one is
        silent.
        """
        assert tectonics_geojson.INFERRED in tectonics_geojson.TYPES

    def test_the_vocabulary_is_not_empty(self):
        """The anti-vacuity arm: the assertion above passes over an empty tuple."""
        assert len(tectonics_geojson.TYPES) == 7

    def test_the_globe_fades_the_level_this_module_calls_minor(self):
        """The browser styles on `level` by value, so a minor level respelt on one side leaves every
        minor boundary drawn at the opening view with no error."""
        source = (paths.ROOT / "web/src/lib/tectonicBoundaries.ts").read_text(encoding="utf-8")
        found = re.search(r"export const MINOR_LEVEL = (\d+);", source)
        assert found is not None, "MINOR_LEVEL is no longer readable from tectonicBoundaries.ts"
        assert int(found.group(1)) == tectonics_geojson.MINOR_LEVEL
        assert tectonics_geojson.MINOR_LEVEL in tectonics_geojson.LEVELS


def write_source(path: Path, rows: list[tuple[str, int]]) -> Path:
    """A shapefile with the two carried fields, one short line per row."""
    writer = shapefile.Writer(str(path), shapeType=shapefile.POLYLINE)
    try:
        # pyshp wraps `field` in `functools.wraps`, which pyright reads as an unbound call.
        writer.field("type", "C", size=100)  # pyright: ignore[reportArgumentType]
        writer.field("level", "N", size=1)  # pyright: ignore[reportArgumentType]
        for type_value, level in rows:
            writer.line([[(0.0, 0.0), (1.0, 1.0)]])
            writer.record(type_value, level)
    finally:
        writer.close()
    return path.with_suffix(".shp")


class TestCheckVocabulary:
    """Read against a written shapefile, so each refusal is shown to fire on the data it names."""

    @staticmethod
    def every_value(extra: list[tuple[str, int]] | None = None) -> list[tuple[str, int]]:
        levels = itertools.cycle(tectonics_geojson.LEVELS)
        rows = [(type_value, next(levels)) for type_value in tectonics_geojson.TYPES]
        return rows + (extra or [])

    def test_a_source_carrying_exactly_the_vocabulary_passes(self, tmp_path):
        counts = tectonics_geojson.check_vocabulary(write_source(tmp_path / "ok", self.every_value()))
        assert set(counts) == set(tectonics_geojson.TYPES)

    def test_an_unknown_type_is_refused(self, tmp_path):
        src = write_source(tmp_path / "type", self.every_value([("spreading centre", 1)]))
        with pytest.raises(SystemExit, match="spreading centre"):
            tectonics_geojson.check_vocabulary(src)

    def test_an_unknown_level_is_refused(self, tmp_path):
        """The globe would draw it as major, which is visible but still not what the source says."""
        src = write_source(tmp_path / "level", self.every_value([("subduction zone", 3)]))
        with pytest.raises(SystemExit, match="level"):
            tectonics_geojson.check_vocabulary(src)

    def test_a_level_declared_but_absent_is_refused(self, tmp_path):
        """No minor boundary in the data leaves the fade matching nothing."""
        rows = [(type_value, tectonics_geojson.MAJOR_LEVEL) for type_value in tectonics_geojson.TYPES]
        with pytest.raises(SystemExit, match="level"):
            tectonics_geojson.check_vocabulary(write_source(tmp_path / "absent", rows))


class TestTheOutputLandsInTheServedStore:
    def test_the_module_spells_no_store_path_of_its_own(self):
        """`borders_dir()` is the one speller of that stage directory, and a second spelling here
        would go red in `test_paths` for a reason that reads as unrelated."""
        source = Path(tectonics_geojson.__file__).read_text(encoding="utf-8")
        assert 'work_dir(' not in source
        assert '"borders"' not in source

    @pytest.mark.parametrize("attribute", ["TYPE_FIELD", "LEVEL_FIELD"])
    def test_the_carried_fields_are_the_ones_named(self, attribute):
        """`CARRIED` is what reaches the browser and the two named fields are what it must hold, so
        a field renamed in one place and not the other cannot ship."""
        assert getattr(tectonics_geojson, attribute) in tectonics_geojson.CARRIED


def test_the_output_name_is_not_the_border_file():
    """Both land in one directory, so a collision would overwrite the border overlay in place."""
    assert tectonics_geojson.OUTPUT_NAME != "boundary_lines.geojson"
    assert countries_pmtiles.borders_dir().name == "borders"
