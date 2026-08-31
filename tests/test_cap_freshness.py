"""The cap's freshness guard: caps are pass outputs, and unguarded outputs rot — both caps once sat
a full day stale against the tiles they feather into, the north cap −6.7 DN adrift. The guard is
`cap_raytrace.params` in a sidecar plus source-mtime comparison.
"""

import json
import os
from pathlib import Path

import pytest

from pipeline import bodies, datasets, planet_seam
from pipeline.look import perennial_ice
from pipeline.tile import cap_raytrace, cap_render

#: A planet whose seam emitted all three rasters — what Earth declares, and the only
#: shape these tests care about unless they say otherwise.
WHOLE_PLANET = planet_seam.KNOWN_RASTERS

ANCIENT = (1_000_000, 1_000_000)
FUTURE = (4_000_000_000, 4_000_000_000)

#: Earth's two cap grids — fixtures, not the thing under test. The module builds grids per body now
#: (`north_grid`), so naming the body is how a test says which planet's recipe it is pinning.
EARTH_NORTH = cap_render.north_grid(bodies.EARTH)
EARTH_SOUTH = cap_render.south_grid(bodies.EARTH)


def _fixture(tmp_path, recipe="the-recipe"):
    """A rendered cap: every shipped rung newer than its one source, sidecar recording `recipe`."""
    source = tmp_path / "planet_heightfield.vrt"
    source.write_text("vrt")
    os.utime(source, ANCIENT)
    assets = []
    for px in cap_render.CAP_RUNGS:
        asset = tmp_path / f"cap_test_{px}.webp"
        asset.write_text("webp")
        assets.append(asset)
    sidecar = tmp_path / "cap_test_params.json"
    sidecar.write_text(recipe)
    return assets, sidecar, [source]


class TestCapIsFresh:
    def test_rendered_under_this_recipe_and_newer_than_sources_is_fresh(self, tmp_path):
        assets, sidecar, sources = _fixture(tmp_path)
        assert cap_render.cap_is_fresh("the-recipe", assets, sidecar, sources) is True

    def test_missing_asset_is_stale(self, tmp_path):
        assets, sidecar, sources = _fixture(tmp_path)
        assets[-1].unlink()
        assert cap_render.cap_is_fresh("the-recipe", assets, sidecar, sources) is False

    def test_a_missing_SMALLER_rung_is_stale_too(self, tmp_path):
        """Why the gate takes the whole rung set, not just the top one: adding a rung to
        CAP_RUNGS must restage even though the render itself is current and its recipe matches.
        A top-rung-only check would advertise the new rung in caps.json and serve a 404."""
        assets, sidecar, sources = _fixture(tmp_path)
        assets[0].unlink()
        assert cap_render.cap_is_fresh("the-recipe", assets, sidecar, sources) is False

    def test_the_oldest_rung_decides_not_the_newest(self, tmp_path):
        """A half-written rung set must not pass on the strength of its newest member."""
        assets, sidecar, sources = _fixture(tmp_path)
        os.utime(sources[0], ANCIENT)
        predates = ANCIENT[0] - 100
        os.utime(assets[0], (predates, predates))  # one rung predates the source
        assert cap_render.cap_is_fresh("the-recipe", assets, sidecar, sources) is False

    def test_missing_sidecar_is_stale(self, tmp_path):
        """The pre-guard state: an asset with no recorded recipe must read stale, never trusted."""
        assets, sidecar, sources = _fixture(tmp_path)
        sidecar.unlink()
        assert cap_render.cap_is_fresh("the-recipe", assets, sidecar, sources) is False

    def test_a_recipe_change_is_stale(self, tmp_path):
        """The observed failure mode: same assets, same sources, but the look recipe moved on."""
        assets, sidecar, sources = _fixture(tmp_path, recipe="the-OLD-recipe")
        assert cap_render.cap_is_fresh("the-NEW-recipe", assets, sidecar, sources) is False

    def test_a_source_newer_than_the_asset_is_stale(self, tmp_path):
        """The re-fuse failure mode: the planet VRTs moved under a still-current recipe."""
        assets, sidecar, sources = _fixture(tmp_path)
        os.utime(sources[0], FUTURE)
        assert cap_render.cap_is_fresh("the-recipe", assets, sidecar, sources) is False

    def test_a_missing_source_is_stale(self, tmp_path):
        """Fail toward re-rendering (which then errors loudly), never toward trusting."""
        assets, sidecar, sources = _fixture(tmp_path)
        sources[0].unlink()
        assert cap_render.cap_is_fresh("the-recipe", assets, sidecar, sources) is False


class TestCapRecipe:
    """NO COMPOSITE-KNOB CASES LEFT, and their absence is the composite's deletion reaching here.
    Two tests asked that `ambient_knee` and `fill_strength` restage the caps; the disc is raytraced
    now and reads neither, so keeping them would pin a coupling no pixel has."""

    def test_the_two_caps_have_distinct_recipes(self):
        """Grid geometry (edge_lat, taper, ice overrides) rides in the recipe, so the poles never
        share a sidecar."""
        assert (cap_raytrace.params(EARTH_NORTH, WHOLE_PLANET)
                != cap_raytrace.params(EARTH_SOUTH, WHOLE_PLANET))


class TestTheDisplacementTextureDoesNotFollowTheLook:
    """`cap_elev_recipe` encodes metres with no light in them, so a colour change must not drag both
    displacement textures through a re-encode. `grid_recipe_fields` is shared between the disc and
    the texture, which is what makes a look key landing there the trap rather than a tidy.
    """

    def test_a_look_change_moves_the_disc_recipe(self, monkeypatch):
        """The positive control. Without it the test below passes against a constant no recipe
        reads, which is indistinguishable from the separation actually holding."""
        grid = cap_render.north_grid(bodies.EARTH)
        before = cap_raytrace.params(grid, WHOLE_PLANET)
        monkeypatch.setattr(cap_render, "COAST_RGB", (1, 2, 3))
        assert cap_raytrace.params(grid, WHOLE_PLANET) != before

    def test_the_displacement_texture_does_not_follow_it(self, monkeypatch):
        grid = cap_render.north_grid(bodies.EARTH)
        before = cap_render.cap_elev_recipe(grid)
        monkeypatch.setattr(cap_render, "COAST_RGB", (1, 2, 3))
        assert cap_render.cap_elev_recipe(grid) == before


class TestCapSources:
    """Both of these run through `bakes_coastline`, whose third question is the disk — so the
    coastline has to be present for either assertion to be about the subject.

    IT IS A FILE THESE TESTS WRITE, not the real Natural Earth shapefile, and the reason is that
    reading the real one made both claims depend on whether this machine holds the download. The
    north's assertion failed on a checkout with no data store, which is the honest half. The
    south's PASSED there, which is the dangerous one: a missing file and a zero opacity produce
    the same empty answer, so the test could not tell its own subject from an absent input.
    """

    @pytest.fixture
    def coastline(self, monkeypatch, tmp_path) -> Path:
        """A present coastline, so the disk question answers yes and the look and body decide."""
        shapefile = tmp_path / "ne_10m_coastline.shp"
        shapefile.write_text("only its existence is read")
        monkeypatch.setattr(cap_render, "coast_shp", lambda: shapefile)
        return shapefile

    def test_north_reads_the_ice_producers_dataset_and_the_coastline(self, coastline):
        """Named off the PRODUCER's own declaration rather than off a path this test spells out.
        A literal here would pass while `cap_sources` listed a file the producer never opens, which
        is the drift the producer-declares-its-inputs rule exists to make impossible."""
        sources = cap_render.cap_sources(EARTH_NORTH, WHOLE_PLANET)
        declared = perennial_ice.cap_ice(bodies.EARTH, "north").sources()
        assert declared, "the north producer reads a dataset — an empty tuple makes this vacuous"
        assert all(source in sources for source in declared)
        assert coastline in sources

    def test_south_forced_ice_needs_no_dataset_and_bakes_no_coastline(self, coastline):
        sources = cap_render.cap_sources(EARTH_SOUTH, WHOLE_PLANET)
        assert perennial_ice.cap_ice(bodies.EARTH, "south").sources() == ()
        assert not any(str(datasets.snow_persistence()) in str(source) for source in sources)
        assert coastline not in sources


class TestTheRecipeTracksTheBodyNarrowly:
    """A cap's recipe must carry every body fact that moves a pixel and no body fact that cannot.

    BOTH DIRECTIONS ARE SILENT, which is why they need a guard rather than a convention.
    Under-tracking leaves the caps falsely fresh against a change that did move them — the AEQD
    radius was in exactly that state, a module constant that reached no recipe at all. Over-tracking
    binds a ~14 GB render to fields like `tile_max_zoom`, so an unrelated edit quietly buys a full
    re-render. Neither shows up as a failure; one ships a stale cap, the other burns an hour.
    """

    def test_the_projection_radius_is_recorded(self):
        recipe = json.loads(cap_raytrace.params(EARTH_NORTH, WHOLE_PLANET))
        assert recipe["grid"]["aeqd_radius_m"] == bodies.EARTH.aeqd_radius_m

    def test_the_whole_body_is_not_inlined(self):
        recipe = json.loads(cap_raytrace.params(EARTH_NORTH, WHOLE_PLANET))
        assert "body" not in recipe["grid"], (
            "the Body object is inlined in the cap recipe — a change to any of its fields, including "
            "ones that cannot move a cap pixel, would restage both caps"
        )
        for irrelevant in ("tile_max_zoom", "path_prefix", "mercator_radius_m"):
            assert irrelevant not in recipe["grid"], (
                f"{irrelevant} cannot change a cap pixel and must not gate a cap render"
            )

    def test_both_recipes_agree_on_how_a_grid_is_serialised(self):
        """They were briefly patched separately, which is how a fix lands in one and not the other."""
        elev = json.loads(cap_render.cap_elev_recipe(EARTH_NORTH))
        full = json.loads(cap_raytrace.params(EARTH_NORTH, WHOLE_PLANET))
        assert elev["grid"] == full["grid"]
