"""cap_render's pure layer: grid geometry, the rotated-azimuth shade, and the caps.json
contract the web layer consumes.

The contract tests are the load-bearing ones: `edge_lat` (±78) and the feather ceiling
(±84 = shade_planet's Mercator plug boundary) were hand-duplicated as literals in
polarCaps.ts — the same copy-drift species as the hero/tile colour constants. caps.json
makes the pipeline the single author; these tests pin what it publishes.
"""

import json

import numpy as np
import pytest

from pipeline.tile import cap_render, shade_planet


class TestCapGridGeometry:
    def test_aeqd_is_pole_centred_spherical(self):
        assert "+proj=aeqd" in cap_render.NORTH.aeqd
        assert "+lat_0=90.0" in cap_render.NORTH.aeqd
        assert "+lat_0=-90.0" in cap_render.SOUTH.aeqd
        assert f"+a={cap_render.SPHERE_R}" in cap_render.NORTH.aeqd

    def test_edge_m_is_linear_in_colatitude(self):
        """AEQD from the pole: radius = R * colatitude(rad) — the linear law the
        frontend's UV mapping assumes."""
        expected = cap_render.SPHERE_R * np.radians(90.0 - 78.0)
        assert cap_render.NORTH.edge_m == pytest.approx(expected)
        assert cap_render.SOUTH.edge_m == pytest.approx(expected)  # |−78| — same disc


class TestLonlatGrid:
    def test_latitude_matches_the_linear_radius_law(self):
        """Independent oracle: on a spherical pole-centred AEQD, latitude at radius rho
        is exactly 90° − degrees(rho / R). Sample centre and edge pixels of a 9-px grid."""
        grid_9px = cap_render.CapGrid(lat_0=90.0, edge_lat=78.0, px=9, name="tiny", az_sign=-1.0)
        longitude, latitude = cap_render._lonlat_grid(grid_9px)
        cell = 2 * grid_9px.edge_m / 9
        for row, col in ((4, 4), (4, 8), (0, 4), (8, 8)):
            x = -grid_9px.edge_m + (col + 0.5) * cell
            y = grid_9px.edge_m - (row + 0.5) * cell
            rho = np.hypot(x, y)
            expected_lat = 90.0 - np.degrees(rho / cap_render.SPHERE_R)
            assert latitude[row, col] == pytest.approx(expected_lat, abs=0.01)

    def test_longitude_orientation(self):
        """x = rho*sin(lon), y = −rho*cos(lon) for the north grid (the convention
        polarCaps.ts mirrors in its UV math): the right-centre pixel sits at lon ≈ +90."""
        grid_9px = cap_render.CapGrid(lat_0=90.0, edge_lat=78.0, px=9, name="tiny", az_sign=-1.0)
        longitude, _latitude = cap_render._lonlat_grid(grid_9px)
        assert longitude[4, 8] == pytest.approx(90.0, abs=0.1)   # +x axis -> 90E
        assert longitude[8, 4] == pytest.approx(0.0, abs=0.1)    # bottom-centre (-y) -> lon 0
        assert longitude[0, 4] == pytest.approx(180.0, abs=0.1)  # top-centre (+y) -> the date line


class TestShade:
    def test_flat_ground_shades_uniformly_whatever_the_azimuth(self):
        """Zero slope makes the per-pixel rotated azimuth irrelevant — flat terrain must
        come out one constant DN across the whole disc (and deterministically so)."""
        grid_8px = cap_render.CapGrid(lat_0=90.0, edge_lat=78.0, px=8, name="tiny", az_sign=-1.0)
        heights = np.zeros((8, 8), dtype=np.float32)
        longitude = np.linspace(-180.0, 180.0, 64, dtype=np.float32).reshape(8, 8)
        shaded = cap_render._shade(grid_8px, heights, longitude)
        assert shaded.shape == (8, 8)
        assert np.allclose(shaded, shaded[0, 0])
        again = cap_render._shade(grid_8px, heights, longitude)
        assert np.array_equal(shaded, again)


class TestCapsManifest:
    def test_contract_fields_come_from_their_single_homes(self):
        manifest = json.loads(cap_render.caps_manifest())
        for name, grid in (("north", cap_render.NORTH), ("south", cap_render.SOUTH)):
            entry = manifest[name]
            assert entry["edge_lat"] == grid.edge_lat
            assert entry["px"] == grid.px
            assert entry["url"] == f"/caps/cap_{name}.webp"
        assert manifest["north"]["feather_hi"] == shade_planet.CAP_NORTH
        assert manifest["south"]["feather_hi"] == shade_planet.CAP_SOUTH

    def test_manifest_is_stable_json(self):
        assert cap_render.caps_manifest() == cap_render.caps_manifest()


class TestRecipeCoversTheAsset:
    def test_webp_quality_rides_in_the_recipe(self, monkeypatch):
        """The encoder setting changes the shipped pixels, so it must restage the cap —
        the same freshness rule that caught the stale caps on 2026-07-22."""
        before = cap_render.cap_recipe(cap_render.NORTH)
        assert '"webp"' in before
        monkeypatch.setattr(cap_render, "CAP_WEBP_QUALITY", 101)
        assert cap_render.cap_recipe(cap_render.NORTH) != before
