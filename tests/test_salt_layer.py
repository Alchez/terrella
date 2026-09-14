"""The salt-flat layer through every stage that reads it: its producer, the white it takes, the tile
prep's mask and paint, the warp's build, and the rig's texture."""

import dataclasses
import importlib
import os
import sys
import time
import types

import numpy as np
import pytest
import rasterio
from conftest import declare_planet_rasters
from PIL import Image
from rasterio.transform import from_bounds

from pipeline import (
    bodies,
    datasets,
    freshness,
    layers,
    naturalearth,
    paths,
    planet_seam,
    planet_warp,
    render_files,
)
from pipeline.block_plan import Block
from pipeline.look import layer_producers, palette, salt
from pipeline.render import prep_block, render_seam
from pipeline.tile import relief_scan


def salt_paint():
    return palette.SALT_RGB, palette.SALT_SHADOW_RGB


def window(rows: int = 4, cols: int = 4) -> layer_producers.LayerWindow:
    return layer_producers.LayerWindow(
        raw=None, watercode=np.zeros((rows, cols), np.uint8), land=np.ones((rows, cols), bool),
        ocean=np.zeros((rows, cols), bool), latitude=np.full(rows, -20.0), ground_metres_per_px=300.0)


class TestTheProducer:
    def test_earth_paints_its_salt_flats_in_the_palettes_salt(self):
        producer = layer_producers.producer_for(bodies.EARTH, layers.SALT_FLATS)
        assert producer.paint(window()) == salt_paint()
        assert producer.contribution(window()) is None
        assert producer.build_recipe() == salt.build_recipe()
        assert producer.paint_recipe() == {"salt_rgb": palette.SALT_RGB,
                                           "salt_shadow_rgb": palette.SALT_SHADOW_RGB}
        assert producer.grid_rasters == ("heightfield", "watermask")

    def test_it_reads_the_outlines_and_the_snow_persistence(self):
        sources = layer_producers.producer_for(bodies.EARTH, layers.SALT_FLATS).sources()
        assert set(sources) == {naturalearth.layer(salt.LAYER), datasets.snow_persistence()}

    def test_the_white_law_names_salt_where_a_stage_reads_it_and_nowhere_else(self):
        """Caps read no salt, so their recipes must not change for it."""
        assert layer_producers.white_law(bodies.EARTH, layers.BLOCK_LAYERS)["white_to_salt"] == ["salt_flats"]
        assert layer_producers.white_law(bodies.EARTH, layers.HERO_LAYERS)["white_to_salt"] == ["salt_flats"]
        assert "white_to_salt" not in layer_producers.white_law(bodies.EARTH, layers.CAP_LAYERS)
        assert "white_to_salt" not in layer_producers.white_law(bodies.MARS, layers.BLOCK_LAYERS)

    def test_the_salt_ground_arrives_with_its_paint_only_where_the_body_and_stage_have_salt(self):
        raw = salt.pack(np.ones((4, 4)), np.zeros((4, 4), bool))
        got = layer_producers.salt_ground(bodies.EARTH, {"salt_flats": raw}, window(), layers.BLOCK_LAYERS)
        assert got is not None
        np.testing.assert_array_equal(got[0], raw)
        assert got[1] == salt_paint()
        assert layer_producers.salt_ground(bodies.EARTH, {"salt_flats": None}, window(),
                                           layers.BLOCK_LAYERS) is None
        assert layer_producers.salt_ground(bodies.MARS, {"salt_flats": raw}, window(),
                                           layers.BLOCK_LAYERS) is None
        assert layer_producers.salt_ground(bodies.EARTH, {"salt_flats": raw}, window(),
                                           layers.CAP_LAYERS) is None


class TestTheTilePrepPaintsSalt:
    """The outcome on a real cut: saturated white everywhere, salt claiming two squares of it."""

    STORE_PX = 32
    BLOCK = Block(col0=8, row0=8, size_px=8, context_px=4)
    FULL = (slice(10, 13), slice(10, 13))
    GATE = (slice(14, 17), slice(14, 17))

    def _raster(self, path, array):
        with rasterio.open(path, "w", driver="GTiff", width=self.STORE_PX, height=self.STORE_PX,  # pyright: ignore[reportCallIssue]
                           count=1, dtype=array.dtype) as out:
            out.write(array, 1)

    def _cut(self, monkeypatch, tmp_path, salted: bool):
        monkeypatch.setattr(paths, "DATA", tmp_path / "store")
        declare_planet_rasters(monkeypatch)
        work = relief_scan.work_dir(bodies.EARTH)
        work.mkdir(parents=True)
        shape = (self.STORE_PX, self.STORE_PX)
        self._raster(work / planet_warp.HEIGHT_3857, np.full(shape, 1000.0, np.float32))
        self._raster(work / planet_warp.OCEAN_3857, np.zeros(shape, np.uint8))
        self._raster(work / planet_warp.WATER_3857, np.zeros(shape, np.uint8))
        self._raster(layers.PERENNIAL_ICE.warped_in(work), np.full(shape, 10000.0, np.float32))
        full, gate = np.zeros(shape), np.zeros(shape, bool)
        if salted:
            full[self.FULL] = 1.0
            gate[self.GATE] = True
        self._raster(layers.SALT_FLATS.warped_in(work), salt.pack(full, gate))
        outdir = tmp_path / "render"
        prep_block.cut(bodies.EARTH, self.BLOCK, outdir, work=work)
        return outdir

    def _plane(self, region):
        """A store region in the cut's plane coordinates."""
        offset = self.BLOCK.row0 - self.BLOCK.context_px
        return tuple(slice(part.start - offset, part.stop - offset) for part in region)

    def _mask(self, outdir, name):
        return np.asarray(Image.open(outdir / name), dtype=float) / 65535.0

    def test_the_salt_takes_the_white_and_gets_its_own_mask_and_paint(self, monkeypatch, tmp_path):
        outdir = self._cut(monkeypatch, tmp_path, salted=True)
        snow_alpha = self._mask(outdir, render_files.SNOWMASK)
        salt_alpha = self._mask(outdir, render_files.SALTMASK)
        claimed = np.zeros(snow_alpha.shape, bool)
        for region in (self.FULL, self.GATE):
            claimed[self._plane(region)] = True
        np.testing.assert_allclose(salt_alpha[claimed], 1.0, atol=1e-4)
        np.testing.assert_allclose(snow_alpha[claimed], 0.0, atol=1e-4)
        np.testing.assert_allclose(salt_alpha[~claimed], 0.0, atol=1e-4)
        np.testing.assert_allclose(snow_alpha[~claimed], 1.0, atol=1e-4)
        assert render_seam.paint_for(outdir, render_files.SALTMASK) == salt_paint()
        assert render_files.SALTMASK in render_seam.declared(outdir)

    def test_a_mask_the_recipe_cannot_see_stops_the_cut(self, monkeypatch, tmp_path):
        """A texture the block recipe does not record restages nothing when its wiring moves, so
        the prep refuses to write one rather than render a block its recipe is blind to."""
        shipped = prep_block.rig_images
        monkeypatch.setattr(prep_block, "rig_images",
                            lambda body, rasters: shipped(body, rasters) - {render_files.SALTMASK})
        with pytest.raises(ValueError, match=render_files.SALTMASK):
            self._cut(monkeypatch, tmp_path, salted=True)

    def test_no_salt_mask_is_written_where_the_raster_claims_nothing(self, monkeypatch, tmp_path):
        outdir = self._cut(monkeypatch, tmp_path, salted=False)
        assert not (outdir / render_files.SALTMASK).exists()
        np.testing.assert_allclose(self._mask(outdir, render_files.SNOWMASK), 1.0, atol=1e-4)


def _age(path, seconds):
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def salty() -> bodies.Body:
    """Earth's grid with the salt layer and nothing else, so the warp builds only it."""
    return dataclasses.replace(bodies.EARTH, name="salty", path_prefix="salty",
                               surface_layers=frozenset({layers.SALT_FLATS.name}))


class TestTheWarpBuildsTheSaltFromThePlanetsOwnRasters:
    def _grid_raster(self, path, dtype):
        span = 10 * bodies.EARTH.map_units_per_pixel
        with rasterio.open(path, "w", driver="GTiff", width=10, height=10, count=1, dtype=dtype,  # pyright: ignore[reportCallIssue]
                           crs="EPSG:3857", transform=from_bounds(0.0, 0.0, span, span, 10, 10)) as out:
            out.write(np.zeros((10, 10), dtype), 1)
        freshness.mark_done(path)

    def _drive(self, tmp_path, monkeypatch, seen):
        work, planet = tmp_path / "work", tmp_path / "planet"
        if not work.exists():
            work.mkdir()
            planet.mkdir()
            self._grid_raster(work / planet_warp.HEIGHT_3857, "float32")
            self._grid_raster(work / planet_warp.WATER_3857, "uint8")
            self._grid_raster(work / planet_warp.OCEAN_3857, "uint8")
            for raster in planet_seam.PLANET_RASTERS:
                source = planet / f"planet_{raster}.vrt"
                source.write_text("vrt")
                _age(source, 500)
            outline = tmp_path / "outlines.shp"
            outline.write_text("shp")
            _age(outline, 500)

        def build(request):
            seen.append(request)
            self._grid_raster(request.out, "uint8")

        fake = layer_producers.LayerProducer(
            sources=lambda: (tmp_path / "outlines.shp",), build=build,
            contribution=lambda _window: None, paint=lambda _window: None,
            contribution_recipe=dict, paint_recipe=dict, build_recipe=dict,
            grid_rasters=("heightfield", "watermask"))
        monkeypatch.setitem(layer_producers.PRODUCER_BY_BODY_LAYER, ("salty", layers.SALT_FLATS.name), fake)
        monkeypatch.setattr(planet_warp, "_run", lambda cmd: None)
        planet_warp.warp_inputs(work, planet, salty(), planet_seam.KNOWN_RASTERS)
        return work

    def test_the_build_is_handed_the_planet_rasters_it_reads(self, tmp_path, monkeypatch):
        seen = []
        work = self._drive(tmp_path, monkeypatch, seen)
        (request,) = seen
        assert request.grid_rasters == {"heightfield": work / planet_warp.HEIGHT_3857,
                                        "watermask": work / planet_warp.WATER_3857}

    def test_a_moved_water_mask_rebuilds_the_salt_and_an_unmoved_one_does_not(self, tmp_path, monkeypatch):
        seen = []
        work = self._drive(tmp_path, monkeypatch, seen)
        self._drive(tmp_path, monkeypatch, seen)
        assert len(seen) == 1, "the control: nothing moved, so the salt must not rebuild"
        # Re-warped as the warp stage would leave it: new bytes and a marker vouching for them.
        (work / planet_warp.WATER_3857).touch()
        freshness.mark_done(work / planet_warp.WATER_3857)
        self._drive(tmp_path, monkeypatch, seen)
        assert len(seen) == 2, "the water mask moved and the salt built from it kept its old pixels"


@pytest.fixture(scope="module")
def scene_build():
    stubbed = "bpy" not in sys.modules
    if stubbed:
        sys.modules["bpy"] = types.ModuleType("bpy")
    try:
        yield importlib.import_module("pipeline.render.scene_build")
    finally:
        if stubbed:
            del sys.modules["bpy"]


def test_the_rig_reads_the_salt_mask_as_an_optional_mask_with_its_edge_baked_in(scene_build):
    spec = scene_build.texture_for(render_files.SALTMASK)
    assert spec.optional
    assert spec.interpolation == "Closest"
    assert render_files.SALTMASK in render_seam.PAINTED_IMAGES
