"""cap_render's freshness guard: cap PNGs are shade-stage outputs, and unguarded outputs rot —
both caps sat a full day stale against the PR-#9 ambient-knee tiles (found 2026-07-22, the north
cap −6.7 DN against the tiles it feathers into). The guard is a recipe sidecar built on
shade_planet.composite_params (one recipe home) plus source-mtime comparison.
"""

import os

from pipeline.tile import cap_render
from pipeline.tile.shade import KNOBS

ANCIENT = (1_000_000, 1_000_000)
FUTURE = (4_000_000_000, 4_000_000_000)


def _fixture(tmp_path, recipe="the-recipe"):
    """A rendered cap: PNG newer than its one source, sidecar recording `recipe`."""
    source = tmp_path / "planet_heightfield.vrt"
    source.write_text("vrt")
    os.utime(source, ANCIENT)
    png = tmp_path / "cap_test.png"
    png.write_text("png")
    sidecar = tmp_path / "cap_test_params.json"
    sidecar.write_text(recipe)
    return png, sidecar, [source]


class TestCapIsFresh:
    def test_rendered_under_this_recipe_and_newer_than_sources_is_fresh(self, tmp_path):
        png, sidecar, sources = _fixture(tmp_path)
        assert cap_render.cap_is_fresh("the-recipe", png, sidecar, sources) is True

    def test_missing_png_is_stale(self, tmp_path):
        png, sidecar, sources = _fixture(tmp_path)
        png.unlink()
        assert cap_render.cap_is_fresh("the-recipe", png, sidecar, sources) is False

    def test_missing_sidecar_is_stale(self, tmp_path):
        """The pre-guard state: a PNG with no recorded recipe must read stale, never trusted."""
        png, sidecar, sources = _fixture(tmp_path)
        sidecar.unlink()
        assert cap_render.cap_is_fresh("the-recipe", png, sidecar, sources) is False

    def test_a_recipe_change_is_stale(self, tmp_path):
        """The PR-#9 failure mode: same PNG, same sources, but the look recipe moved on."""
        png, sidecar, sources = _fixture(tmp_path, recipe="the-OLD-recipe")
        assert cap_render.cap_is_fresh("the-NEW-recipe", png, sidecar, sources) is False

    def test_a_source_newer_than_the_png_is_stale(self, tmp_path):
        """The re-fuse failure mode: the planet VRTs moved under a still-current recipe."""
        png, sidecar, sources = _fixture(tmp_path)
        os.utime(sources[0], FUTURE)
        assert cap_render.cap_is_fresh("the-recipe", png, sidecar, sources) is False

    def test_a_missing_source_is_stale(self, tmp_path):
        """Fail toward re-rendering (which then errors loudly), never toward trusting."""
        png, sidecar, sources = _fixture(tmp_path)
        sources[0].unlink()
        assert cap_render.cap_is_fresh("the-recipe", png, sidecar, sources) is False


class TestCapRecipe:
    def test_a_composite_knob_change_restages_the_caps(self):
        """THE regression this guard exists for: ambient_knee shipped in PR #9 and no cap noticed."""
        before = cap_render.cap_recipe(cap_render.NORTH)
        saved = KNOBS["ambient_knee"]
        KNOBS["ambient_knee"] = saved + 0.05
        try:
            assert cap_render.cap_recipe(cap_render.NORTH) != before
        finally:
            KNOBS["ambient_knee"] = saved

    def test_fill_strength_rides_in_the_recipe(self):
        """composite_params filters fill_strength as hillshade-stage (hs_params tracks it for the
        tiles), but the caps consume it directly in _shade — the one knob that would slip through
        the shared recipe if not listed explicitly."""
        before = cap_render.cap_recipe(cap_render.SOUTH)
        saved = KNOBS["fill_strength"]
        KNOBS["fill_strength"] = saved + 0.05
        try:
            assert cap_render.cap_recipe(cap_render.SOUTH) != before
        finally:
            KNOBS["fill_strength"] = saved

    def test_the_two_caps_have_distinct_recipes(self):
        """Grid geometry (edge_lat, taper, ice overrides) rides in the recipe, so the poles never
        share a sidecar."""
        assert cap_render.cap_recipe(cap_render.NORTH) != cap_render.cap_recipe(cap_render.SOUTH)


class TestCapSources:
    def test_north_reads_the_snow_dataset_and_the_coastline(self):
        sources = cap_render.cap_sources(cap_render.NORTH)
        assert any("snow" in str(source).lower() or str(cap_render.snow.SP_NC) in str(source)
                   for source in sources)
        assert cap_render.COAST_SHP in sources

    def test_south_forced_snow_needs_no_dataset_and_bakes_no_coastline(self):
        sources = cap_render.cap_sources(cap_render.SOUTH)
        assert not any(str(cap_render.snow.SP_NC) in str(source) for source in sources)
        assert cap_render.COAST_SHP not in sources
