"""A raytraced stage's recipe moves for what can reach its pixels, and for nothing else.

Each of the six recipes (both bodies' blocks, all four caps) records the layers its body has at that
stage, the textures its prep can write and the rig values its render builds a branch for. Both
directions are asserted by naming the exact set of stages a change moves: a stage left out re-renders
nothing it should, a stage let in re-renders a planet for identical pixels, and neither makes a test
red on its own.
"""

import dataclasses
import importlib
import sys
import types

import pytest
from conftest import DECLARED_RASTERS, declare_planet_rasters

from pipeline import bodies, layers, render_files
from pipeline.look import layer_producers
from pipeline.tile import block_render, cap_raytrace, cap_render

EVERY_CAP = ["earth north cap", "earth south cap", "mars north cap", "mars south cap"]


@pytest.fixture(scope="module")
def scene_build():
    """`scene_build` with bpy stubbed, the same module object `block_render.rig_recipe` reads."""
    stubbed = "bpy" not in sys.modules
    if stubbed:
        sys.modules["bpy"] = types.ModuleType("bpy")
    try:
        yield importlib.import_module("pipeline.render.scene_build")
    finally:
        if stubbed:
            del sys.modules["bpy"]


@pytest.fixture(autouse=True)
def _no_store(monkeypatch):
    declare_planet_rasters(monkeypatch)


def recipes(earth: bodies.Body = bodies.EARTH) -> dict[str, str]:
    """Every raytraced recipe, as the block runner and the cap pass write them."""
    written = {}
    for body in (earth, bodies.MARS):
        rasters = DECLARED_RASTERS[body.name]
        written[f"{body.name} blocks"] = block_render.recipe_for(body, rasters, [])
        for grid in (cap_render.north_grid(body), cap_render.south_grid(body)):
            written[f"{body.name} {grid.name} cap"] = cap_raytrace.params(grid, rasters)
    return written


def moved(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(stage for stage in before if before[stage] != after[stage])


def test_nothing_moves_when_nothing_changes():
    """The control every other test leans on: two reads of unchanged code are the same text."""
    assert moved(recipes(), recipes()) == []


def test_a_layer_only_earth_has_restages_earths_blocks_alone(monkeypatch):
    """A new Earth-only block layer, the salt flats' shape: Mars lacks it and no cap reads it."""
    crust = dataclasses.replace(layers.GLACIERS, name="test_crust",
                                warped_basename="test_crust_3857.tif")
    before = recipes()
    monkeypatch.setattr(layers, "LAYERS", (*layers.LAYERS, crust))
    for view in ("SURFACE_LAYERS", "PLANET_LAYERS", "BLOCK_LAYERS"):
        monkeypatch.setattr(layers, view, getattr(layers, view) | {crust.name})
    glaciers = layer_producers.PRODUCER_BY_BODY_LAYER[("earth", layers.GLACIERS.name)]
    monkeypatch.setitem(layer_producers.PRODUCER_BY_BODY_LAYER, ("earth", crust.name),
                        dataclasses.replace(glaciers, contribution_recipe=lambda: {"crust_level": 1}))
    earth = dataclasses.replace(bodies.EARTH,
                                surface_layers=bodies.EARTH.surface_layers | {crust.name})
    assert moved(before, recipes(earth)) == ["earth blocks"]


def test_a_texture_only_earths_blocks_load_restages_them_alone(monkeypatch, scene_build):
    """The salt mask's wiring: written by Earth's block prep, by no cap's and by nothing on Mars."""
    before = recipes()
    monkeypatch.setattr(scene_build, "TEXTURES", {
        name: (dataclasses.replace(spec, interpolation="Linear")
               if spec.filename == render_files.SALTMASK else spec)
        for name, spec in scene_build.TEXTURES.items()})
    assert moved(before, recipes()) == ["earth blocks"]


def test_a_texture_no_prep_writes_restages_nothing(monkeypatch, scene_build):
    before = recipes()
    monkeypatch.setattr(scene_build, "TEXTURES", {
        **scene_build.TEXTURES,
        "Test Crust": scene_build.TextureSpec("Test Crust", "testcrust.png", "Closest", "REPEAT",
                                              optional=True)})
    assert moved(before, recipes()) == []


def test_a_texture_every_stage_loads_restages_every_stage(monkeypatch, scene_build):
    """The heightfield: the control that the filter narrows the table rather than dropping it."""
    before = recipes()
    monkeypatch.setattr(scene_build, "TEXTURES", {
        name: (dataclasses.replace(spec, extension="EXTEND")
               if spec.filename == render_files.HEIGHTFIELD else spec)
        for name, spec in scene_build.TEXTURES.items()})
    assert moved(before, recipes()) == ["earth blocks", *EVERY_CAP[:2], "mars blocks", *EVERY_CAP[2:]]


def _move_rig(monkeypatch, scene_build, **changes):
    monkeypatch.setattr(scene_build, "RIG", dataclasses.replace(scene_build.RIG, **changes))


def test_a_lake_bed_colour_restages_earths_blocks_alone(monkeypatch, scene_build):
    """Only a block on a body with lake depth builds the lake ramp."""
    before = recipes()
    stops = [(position, (red, green, blue, 1.0)) for position, (red, green, blue, _)
             in scene_build.RIG.lake_stops]
    stops[0] = (stops[0][0], (0.5, 0.5, 0.5, 1.0))
    _move_rig(monkeypatch, scene_build, lake_stops=stops)
    assert moved(before, recipes()) == ["earth blocks"]


def test_the_row_scale_restages_both_bodies_blocks_and_no_cap(monkeypatch, scene_build):
    """A cap is equidistant from its centre, so its prep writes no row scale."""
    before = recipes()
    _move_rig(monkeypatch, scene_build, rowscale_use_clamp=not scene_build.RIG.rowscale_use_clamp)
    assert moved(before, recipes()) == ["earth blocks", "mars blocks"]


def test_the_flat_water_colour_restages_what_draws_inland_water(monkeypatch, scene_build):
    """Mars declares no water mask, so neither its blocks nor its caps build the water colour."""
    before = recipes()
    _move_rig(monkeypatch, scene_build, water_rgba=(0.5, 0.5, 0.5, 1.0))
    assert moved(before, recipes()) == ["earth blocks", *EVERY_CAP[:2]]


def test_the_sea_ice_floor_restages_earths_blocks_and_caps(monkeypatch, scene_build):
    before = recipes()
    _move_rig(monkeypatch, scene_build, ice_flatten_floor=0.25)
    assert moved(before, recipes()) == ["earth blocks", *EVERY_CAP[:2]]


def test_a_value_every_render_reads_restages_every_stage(monkeypatch, scene_build):
    """The sun: the control that the filter narrows the rig rather than dropping it."""
    before = recipes()
    _move_rig(monkeypatch, scene_build, sun_strength=scene_build.RIG.sun_strength + 1.0)
    assert moved(before, recipes()) == ["earth blocks", *EVERY_CAP[:2], "mars blocks", *EVERY_CAP[2:]]
