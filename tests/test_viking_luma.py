"""The Viking brightness stage's recipe and freshness, checked without building a 215 MB raster.

WHAT IS TESTABLE WITHOUT THE PASS. The build itself is a GDAL warp and a streamed collapse, and its
correctness is established by an oracle that cannot live in a suite: `scripts/measure_viking_levels
.py --compare` re-measures `ALPHA_LEVELS` over the shipped raster and refuses a disagreement. What
belongs here is everything around that — which facts reach the recipe, and which of them may not.

The freshness rule carries the sharpest trap. `valid_fraction` is an OUTPUT of the build, so a
recipe comparison that included it would ask the stage to predict its own result before running and
would rebuild forever; the two constants that reach a pixel, on the other hand, must be in there or
a changed field leaves a stale raster looking fresh.
"""

import json

import numpy as np
import pytest

from pipeline import bodies, paths
from pipeline.acquire import download_viking_mosaic
from pipeline.render import mars_ice, viking_luma


@pytest.fixture
def relocated(tmp_path, monkeypatch):
    """Move the whole data store, so nothing here can touch the real one."""
    monkeypatch.setattr(paths, "DATA", tmp_path)
    viking_luma.work_dir().mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write(valid_fraction=1.0, **overrides):
    """A recipe on disk, optionally with one field bent."""
    recorded = json.loads(viking_luma.build_recipe(valid_fraction))
    recorded.update(overrides)
    viking_luma.recipe_path().write_text(json.dumps(recorded, indent=2, sort_keys=True) + "\n")
    viking_luma.luma_path().write_bytes(b"not really a raster")


class TestTheRecipeCarriesWhatReachesAPixel:
    def test_it_records_the_luma_weights(self):
        """A field rebuilt through different weights is a different field. Recorded here because the
        raster on disk cannot say which weights produced it, and existence cannot see a constant."""
        recorded = json.loads(viking_luma.build_recipe(1.0))
        assert recorded["luma_weights"] == list(mars_ice.LUMA_WEIGHTS)

    def test_it_records_the_source_EDITION_and_not_merely_the_source_path(self):
        """The acquirer's whole point is that this mosaic can be republished under the same name.
        Keying on the publisher's digest is what carries that catch through to the derived raster
        instead of stopping at the download."""
        recorded = json.loads(viking_luma.build_recipe(1.0))
        assert recorded["source_md5"] == download_viking_mosaic.EXPECTED_MD5
        assert recorded["source"] == download_viking_mosaic.MOSAIC_NAME

    def test_the_grid_covers_the_whole_sphere_at_the_publishers_pixel_count(self):
        """The stage states its grid rather than inheriting the source's, because the publisher's
        rounded pixel size puts the mosaic's own transform at -180.008..180.008 degrees."""
        grid = json.loads(viking_luma.build_recipe(1.0))["grid"]
        assert grid["bounds"] == [-180.0, -90.0, 180.0, 90.0]
        assert (grid["width"], grid["height"]) == (download_viking_mosaic.EXPECTED_WIDTH,
                                                   download_viking_mosaic.EXPECTED_HEIGHT)

    def test_the_nodata_is_zero_because_the_collapse_preserves_it(self):
        """`mars_ice.luma` vanishes exactly where all three source bands do, which is the only
        reason one scalar can stand for a three-band absence."""
        assert json.loads(viking_luma.build_recipe(1.0))["nodata"] == 0.0
        assert mars_ice.luma(np.zeros((3, 1, 1), dtype=np.float32))[0, 0] == 0.0


class TestFreshnessComparesInputsAndNeverOutputs:
    def test_a_matching_recipe_is_fresh(self, relocated):
        _write()
        assert viking_luma.is_fresh()

    def test_a_different_measured_share_is_STILL_fresh(self, relocated):
        """THE TRAP THIS RULE EXISTS FOR. `valid_fraction` is produced BY the build, so comparing it
        would require predicting the result before running — a recipe that can never match makes an
        idempotent stage rebuild forever, which is the opposite of what a freshness gate is for."""
        _write(valid_fraction=0.5)
        assert viking_luma.is_fresh()

    def test_changed_weights_are_STALE(self, relocated):
        """The constant that reaches every pixel. Fresh here would ship a field graded through one
        set of weights against levels measured through another, with nothing raising."""
        _write(luma_weights=[0.3, 0.6, 0.1])
        assert not viking_luma.is_fresh()

    def test_a_republished_source_edition_is_STALE(self, relocated):
        _write(source_md5="0" * 32)
        assert not viking_luma.is_fresh()

    def test_a_missing_raster_is_STALE_even_with_a_perfect_recipe(self, relocated):
        """The sidecar records what the producer MEANT to emit; the raster is what a consumer reads.
        A recipe agreeing with the module says nothing about a file that was deleted."""
        _write()
        viking_luma.luma_path().unlink()
        assert not viking_luma.is_fresh()

    def test_a_corrupt_recipe_is_STALE_rather_than_an_exception(self, relocated):
        viking_luma.luma_path().write_bytes(b"x")
        viking_luma.recipe_path().write_text("{not json")
        assert not viking_luma.is_fresh()

    @pytest.mark.parametrize("literal", ["5", "[]", '"a string"', "null"])
    def test_a_recipe_that_PARSES_into_a_non_object_is_STALE(self, literal, relocated):
        """The case the one above cannot reach. `{not json` fails to parse and was caught; a bare
        `5` parses, was handed back as the recorded recipe, and reached `.items()` — an
        `AttributeError` raised from inside a question whose only honest answers are yes and no."""
        viking_luma.luma_path().write_bytes(b"x")
        viking_luma.recipe_path().write_text(literal)
        assert not viking_luma.is_fresh()


class TestItWritesWhereTheBodyLives:
    def test_both_paths_follow_a_relocated_data_store(self, relocated):
        """Resolved at call time, not frozen at import: `MAPS_DATA` moves the whole store, and a
        module-level join would leave the raster landing back inside the checkout."""
        assert viking_luma.luma_path().is_relative_to(relocated)
        assert viking_luma.recipe_path().is_relative_to(relocated)

    def test_it_nests_under_mars_rather_than_the_shared_work_root(self, relocated):
        """The body goes in the PATH, never in the recipe — `bodies.work_dir` holds why, and the
        consequence here is that this sidecar is body-specific for free."""
        assert viking_luma.work_dir() == bodies.work_dir(bodies.get("mars"), "ice")
        assert "mars" in viking_luma.luma_path().parts

    def test_check_reports_without_building(self, relocated, monkeypatch, capsys):
        built: list[str] = []
        monkeypatch.setattr(viking_luma, "build", lambda *a, **k: built.append("build"))
        monkeypatch.setattr("sys.argv", ["viking_luma", "--check"])
        assert viking_luma.main() == 0
        assert built == [], "--check reached the build"
        assert "STALE" in capsys.readouterr().out
