"""cap_render's pure layer: grid geometry, the rotated-azimuth shade, and the caps.json
contract the web layer consumes.

The contract tests are the load-bearing ones: `edge_lat` (±78) and the feather ceiling
(±84 = shade_planet's Mercator plug boundary) were hand-duplicated as literals in
polarCaps.ts — the same copy-drift species as the hero/tile colour constants. caps.json
makes the pipeline the single author; these tests pin what it publishes.

The elevation texture (TestCapElevationTexture, below) is guarded harder than the colour, and
for a different reason: a wrong colour pixel is visible and a wrong METRE is not. The cap
displaces itself from these bytes while the tiles around it displace from the pyramid, so an
encoding that disagrees by one step lifts two surfaces to different heights across the alpha
crossfade — which reads as ghosting, not as an error.
"""

import dataclasses
import json
import re
import shutil
import subprocess
from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from pipeline import bodies, paths
from pipeline.tile import cap_render, shade_planet, terrain_rgb


class TestCapGridGeometry:
    def test_aeqd_is_pole_centred_spherical(self, subtests):
        """Subtests because these are four independent claims about one projection string, and a
        bad edit to it breaks the projection, both centres and the sphere together."""
        with subtests.test("projection is aeqd"):
            assert "+proj=aeqd" in cap_render.NORTH.aeqd
        with subtests.test("north is centred on the north pole"):
            assert "+lat_0=90.0" in cap_render.NORTH.aeqd
        with subtests.test("south is centred on the south pole"):
            assert "+lat_0=-90.0" in cap_render.SOUTH.aeqd
        with subtests.test("sphere radius"):
            assert f"+a={bodies.EARTH.aeqd_radius_m}" in cap_render.NORTH.aeqd

    def test_edge_m_is_linear_in_colatitude(self):
        """AEQD from the pole: radius = R * colatitude(rad) — the linear law the
        frontend's UV mapping assumes."""
        expected = bodies.EARTH.aeqd_radius_m * np.radians(90.0 - 78.0)
        assert cap_render.NORTH.edge_m == pytest.approx(expected)
        assert cap_render.SOUTH.edge_m == pytest.approx(expected)  # |−78| — same disc


class TestLonlatGrid:
    def test_latitude_matches_the_linear_radius_law(self):
        """Independent oracle: on a spherical pole-centred AEQD, latitude at radius rho
        is exactly 90° − degrees(rho / R). Sample centre and edge pixels of a 9-px grid."""
        grid_9px = cap_render.CapGrid(lat_0=90.0, edge_lat=78.0, px=9, name="tiny", az_sign=-1.0,
                                   body=bodies.EARTH)
        longitude, latitude = cap_render._lonlat_grid(grid_9px)
        cell = 2 * grid_9px.edge_m / 9
        for row, col in ((4, 4), (4, 8), (0, 4), (8, 8)):
            x = -grid_9px.edge_m + (col + 0.5) * cell
            y = grid_9px.edge_m - (row + 0.5) * cell
            rho = np.hypot(x, y)
            expected_lat = 90.0 - np.degrees(rho / bodies.EARTH.aeqd_radius_m)
            assert latitude[row, col] == pytest.approx(expected_lat, abs=0.01)

    def test_longitude_orientation(self):
        """x = rho*sin(lon), y = −rho*cos(lon) for the north grid (the convention
        polarCaps.ts mirrors in its UV math): the right-centre pixel sits at lon ≈ +90."""
        grid_9px = cap_render.CapGrid(lat_0=90.0, edge_lat=78.0, px=9, name="tiny", az_sign=-1.0,
                                   body=bodies.EARTH)
        longitude, _latitude = cap_render._lonlat_grid(grid_9px)
        assert longitude[4, 8] == pytest.approx(90.0, abs=0.1)   # +x axis -> 90E
        assert longitude[8, 4] == pytest.approx(0.0, abs=0.1)    # bottom-centre (-y) -> lon 0
        assert longitude[0, 4] == pytest.approx(180.0, abs=0.1)  # top-centre (+y) -> the date line


class TestShade:
    def test_flat_ground_shades_uniformly_whatever_the_azimuth(self):
        """Zero slope makes the per-pixel rotated azimuth irrelevant — flat terrain must
        come out one constant DN across the whole disc (and deterministically so)."""
        grid_8px = cap_render.CapGrid(lat_0=90.0, edge_lat=78.0, px=8, name="tiny", az_sign=-1.0,
                                   body=bodies.EARTH)
        heights = np.zeros((8, 8), dtype=np.float32)
        longitude = np.linspace(-180.0, 180.0, 64, dtype=np.float32).reshape(8, 8)
        shaded = cap_render._shade(grid_8px, heights, longitude)
        assert shaded.shape == (8, 8)
        assert np.allclose(shaded, shaded[0, 0])
        again = cap_render._shade(grid_8px, heights, longitude)
        assert np.array_equal(shaded, again)


class TestCapPathsFollowTheBody:
    """Every file a cap reads or writes is located by the grid's own body, not by a module constant.

    The first test is a CHARACTERISATION: it passed before the resolution moved onto the body and
    has to keep passing after. Earth's served names are a contract the frontend fetches by URL, and
    its intermediates are 1.3 GB that a moved directory would silently re-derive.
    """

    def test_earth_reads_and_writes_exactly_where_it_always_has(self, subtests):
        """Subtests because these are four independent locations, and a resolver that broke would
        break the served ones and the intermediate ones for different reasons."""
        with subtests.test("served colour rung"):
            assert (cap_render.cap_asset(cap_render.NORTH, 8192)
                    == paths.ROOT / "web/public/caps/cap_north_8192.webp")
        with subtests.test("served elevation texture"):
            assert (cap_render.cap_elev_asset(cap_render.SOUTH)
                    == paths.ROOT / "web/public/caps/cap_south_elev.webp")
        with subtests.test("intermediate height warp"):
            assert (cap_render.cap_height_warp(cap_render.NORTH)
                    == paths.DATA / "work/cap/capN_height.tif")
        with subtests.test("fused planet source"):
            assert (paths.DATA / "work/planet/planet_heightfield.vrt"
                    in cap_render.cap_sources(cap_render.NORTH))

    def test_a_second_body_cannot_land_its_caps_on_earths(self, subtests):
        """The failure this forbids is silent and destructive in one direction only: a Mars cap
        written to `web/public/caps/cap_north_8192.webp` overwrites Earth's shipped texture, and
        nothing downstream would report anything but a wrong-looking pole.

        Reading matters as much as writing — a Mars cap that sourced Earth's fused heightfield would
        render a perfectly clean Arctic and call it Mars.
        """
        mars = dataclasses.replace(bodies.EARTH, name="mars", path_prefix="mars")
        grid = dataclasses.replace(cap_render.NORTH, body=mars)
        with subtests.test("served colour rung"):
            assert (cap_render.cap_asset(grid, 8192)
                    == paths.ROOT / "web/public/caps/mars/cap_north_8192.webp")
        with subtests.test("served elevation texture"):
            assert (cap_render.cap_elev_asset(grid)
                    == paths.ROOT / "web/public/caps/mars/cap_north_elev.webp")
        with subtests.test("intermediate height warp"):
            assert (cap_render.cap_height_warp(grid)
                    == paths.DATA / "work/mars/cap/capN_height.tif")
        with subtests.test("fused planet source"):
            assert (paths.DATA / "work/mars/planet/planet_heightfield.vrt"
                    in cap_render.cap_sources(grid))


class TestCapsManifest:
    def test_contract_fields_come_from_their_single_homes(self):
        manifest = json.loads(cap_render.caps_manifest())
        for name, grid in (("north", cap_render.NORTH), ("south", cap_render.SOUTH)):
            entry = manifest[name]
            assert entry["edge_lat"] == grid.edge_lat
            assert [rung["px"] for rung in entry["rungs"]] == list(cap_render.CAP_RUNGS)
            for rung in entry["rungs"]:
                assert rung["url"] == f"/caps/cap_{name}_{rung['px']}.webp"
        assert manifest["north"]["feather_hi"] == shade_planet.CAP_NORTH
        assert manifest["south"]["feather_hi"] == shade_planet.CAP_SOUTH

    def test_rungs_are_ascending_and_topped_by_the_render_grid(self):
        """The largest rung IS the render grid — every smaller one is downsampled from it, so a
        rung above CAP_PX would silently be an upscale."""
        assert list(cap_render.CAP_RUNGS) == sorted(cap_render.CAP_RUNGS)
        assert cap_render.CAP_RUNGS[-1] == cap_render.CAP_PX
        for grid in (cap_render.NORTH, cap_render.SOUTH):
            assert cap_render.CAP_RUNGS[-1] == grid.px

    def test_manifest_is_stable_json(self):
        assert cap_render.caps_manifest() == cap_render.caps_manifest()


class TestRecipeCoversTheAsset:
    def test_webp_quality_rides_in_the_recipe(self, monkeypatch):
        """The encoder setting changes the shipped pixels, so it must restage the cap —
        the same freshness rule that caught the stale caps."""
        before = cap_render.cap_recipe(cap_render.NORTH)
        assert '"webp"' in before
        monkeypatch.setattr(cap_render, "CAP_WEBP_QUALITY", 101)
        assert cap_render.cap_recipe(cap_render.NORTH) != before

    def test_rung_set_rides_in_the_recipe(self, monkeypatch):
        """Adding a rung changes the shipped ASSET SET, so it must restage — otherwise the new
        rung's file would never be written and the manifest would advertise a 404."""
        before = cap_render.cap_recipe(cap_render.NORTH)
        monkeypatch.setattr(cap_render, "CAP_RUNGS", (2048, cap_render.CAP_PX))
        assert cap_render.cap_recipe(cap_render.NORTH) != before


# --- The elevation texture ----------------------------------------------------------------
#
# `write_cap_elevation` is short and every line of it is a place metres can go wrong silently:
# the nodata convention, the order of downsample-vs-encode, the imported step, the codec. What
# follows exercises the REAL function against synthetic warps small enough to reason about, with
# an oracle written as a second statement of the rule rather than a copy of the implementation.


def _write_warp(grid: cap_render.CapGrid, metres: np.ndarray) -> None:
    """Stand in for the gdalwarp output `write_cap_elevation` reads: a Float32 raster of metres.

    Georeferenced on the grid's own AEQD square even though the stage reads band 1 and nothing
    else. That is not decoration: a fixture that differs from the real warp in a way we have
    dismissed as irrelevant is how a stage grows a hidden dependency nobody notices."""
    edge = grid.edge_m
    profile: dict[str, Any] = dict(
        driver="GTiff", width=metres.shape[1], height=metres.shape[0], count=1, dtype="float32",
        crs=grid.aeqd,
        transform=from_bounds(-edge, -edge, edge, edge, metres.shape[1], metres.shape[0]))
    with rasterio.open(cap_render.cap_height_warp(grid), "w", **profile) as dataset:
        dataset.write(metres.astype(np.float32), 1)


def _block_means(metres: np.ndarray, out_px: int) -> np.ndarray:
    """Box-mean by explicit iteration.

    NOT the implementation's `reshape(...).mean(axis=(1, 3))` — an oracle that rearranges the code
    under test agrees with it by construction, including where both are wrong. This walks the
    blocks and divides a sum by a count, which is what "box mean" means."""
    factor = metres.shape[0] // out_px
    means = np.zeros((out_px, out_px), dtype=np.float64)
    for row in range(out_px):
        for col in range(out_px):
            block = metres[row * factor:(row + 1) * factor, col * factor:(col + 1) * factor]
            means[row, col] = float(np.sum(block)) / block.size
    return means


def _ramp(px: int) -> np.ndarray:
    """A deterministic elevation field with both signs and several low-byte wraps in it.

    Range is about -3.9 km to +2.8 km, so it crosses the 256*step = 2048 m period where the green
    byte wraps — the one place an encoding mistake is guaranteed to show."""
    rows = np.arange(px, dtype=np.float64)[:, None]
    cols = np.arange(px, dtype=np.float64)[None, :]
    return (rows * 611.0 - cols * 337.0 - 1500.0).astype(np.float32)


def _tiny_cap(monkeypatch, tmp_path, cap_px: int, elev_px: int) -> cap_render.CapGrid:
    """Point both output homes at tmp_path and shrink the grid. The grid keeps the real
    `edge_lat` so `edge_m` stays honest; only the pixel counts move.

    REDIRECTS THE TWO ROOTS, not the module's own path helpers. Both `paths.DATA` and `paths.ROOT`
    are read at call time, so moving them exercises the real derivation — registry lookup, prefix
    join and all — where stubbing `cap_work_dir` would have tested a lambda. It also keeps the two
    roots distinct here exactly as production keeps them: a body whose served and working
    directories collapsed onto one path would still pass a fixture that stubbed both to tmp_path.
    """
    monkeypatch.setattr(paths, "DATA", tmp_path / "data")
    monkeypatch.setattr(paths, "ROOT", tmp_path / "checkout")
    monkeypatch.setattr(cap_render, "CAP_PX", cap_px)
    monkeypatch.setattr(cap_render, "CAP_ELEV_PX", elev_px)
    grid = cap_render.CapGrid(lat_0=90.0, edge_lat=78.0, px=cap_px, name="tiny", az_sign=-1.0,
                              body=bodies.EARTH)
    cap_render.cap_work_dir(grid.body).mkdir(parents=True, exist_ok=True)
    return grid


#: WEBP write support in the GDAL this box has. The cap pipeline cannot run at all without it, so
#: skipping is honest rather than a drift guard that never fires: the two tests below are the only
#: ones here that touch the CLI, and everything they would have caught about the NUMBERS is also
#: covered by the CLI-free tests, which run everywhere.
def _gdal_can_write_webp() -> bool:
    if shutil.which("gdalinfo") is None:
        return False
    registry = subprocess.run(["gdalinfo", "--formats"], capture_output=True, text=True).stdout
    entry = re.search(r"^\s*WEBP\s+-raster-\s+\(([a-zA-Z+]*)\)", registry, re.MULTILINE)
    return bool(entry and "w" in entry.group(1))


HAS_WEBP_WRITE = _gdal_can_write_webp()


class TestCapElevationTexture:
    @pytest.mark.skipif(not HAS_WEBP_WRITE, reason="GDAL here cannot write WEBP")
    def test_the_shipped_texture_decodes_to_metres_within_half_a_step(self, tmp_path, monkeypatch):
        """The whole contract in one line: what MapLibre decodes out of this file is the true
        surface, to the quantiser's own resolution and no worse.

        Runs the real encoder AND the real gdal_translate, then decodes with
        `terrain_rgb.decode_array` — which is written as the style's own arithmetic, not as an
        inverse of the encode. step/2 is the exact bound a round-to-nearest quantiser can promise,
        so it is asserted as `<=` and not padded: a looser tolerance here would accept a genuine
        off-by-one-level bug."""
        grid = _tiny_cap(monkeypatch, tmp_path, cap_px=8, elev_px=4)
        metres = _ramp(8)
        _write_warp(grid, metres)

        asset = cap_render.write_cap_elevation(grid)
        with rasterio.open(asset) as dataset:
            encoded = dataset.read()
        decoded = terrain_rgb.decode_array(encoded, terrain_rgb.QUANTISATION_M)

        expected = _block_means(metres, 4)
        error = np.abs(decoded - expected)
        assert error.max() <= terrain_rgb.QUANTISATION_M / 2

        # Positive control: the assertion above must be able to fail. One red byte is one
        # 256*step = 2048 m level, so a single corrupted pixel has to break it — and the max
        # error has to land ON that pixel, not merely somewhere.
        corrupt = encoded.copy()
        corrupt[0, 1, 2] = np.uint8((int(corrupt[0, 1, 2]) + 1) % 256)
        broken = np.abs(terrain_rgb.decode_array(corrupt, terrain_rgb.QUANTISATION_M) - expected)
        assert broken.max() > terrain_rgb.QUANTISATION_M / 2
        assert np.unravel_index(int(np.argmax(broken)), broken.shape) == (1, 2)

    @pytest.mark.skipif(not HAS_WEBP_WRITE, reason="GDAL here cannot write WEBP")
    def test_the_webp_is_byte_exact_against_the_raster_it_encodes(self, tmp_path, monkeypatch):
        """`-co LOSSLESS=YES` is load-bearing, and its failure mode has no visual tell: a lossy
        elevation texture decodes to plausible bytes and therefore to wrong metres.

        The lossy arm is the point of this test. Without it "the bytes match" could pass on a
        codec that was never asked to compress anything."""
        grid = _tiny_cap(monkeypatch, tmp_path, cap_px=64, elev_px=32)
        _write_warp(grid, _ramp(64))

        asset = cap_render.write_cap_elevation(grid)
        source = cap_render.cap_work_dir(grid.body) / "cap_tiny_elev.tif"
        with rasterio.open(source) as dataset:
            authored = dataset.read()
        with rasterio.open(asset) as dataset:
            shipped = dataset.read()
        assert np.array_equal(authored, shipped)

        lossy = tmp_path / "lossy.webp"
        cap_render._run(["gdal_translate", "-q", "-of", "WEBP", "-co",
                         f"QUALITY={cap_render.CAP_WEBP_QUALITY}", str(source), str(lossy)])
        with rasterio.open(lossy) as dataset:
            assert not np.array_equal(authored, dataset.read())

    def test_the_downsample_happens_in_metres_and_not_in_encoded_bytes(self, tmp_path, monkeypatch):
        """Averaging encoded RGB is the mistake this stage is one line away from, and it is
        catastrophic exactly where it is invisible: only across a low-byte wrap.

        The two cells here straddle one — packed 4351 (R=16, G=255) and 4352 (R=17, G=0). Their
        true mean is 2044 m. Averaging the bytes and rounding to uint8 gives R=16, G=128, which
        decodes to 1024 m: a 1 km cliff invented out of a 8 m step. This asserts the shipped path
        lands on the truth AND that the byte path does not, so the test states the difference
        rather than merely pinning today's numbers."""
        monkeypatch.setattr(cap_render, "_run", lambda cmd: None)  # no codec needed; read the tif
        grid = _tiny_cap(monkeypatch, tmp_path, cap_px=2, elev_px=1)
        straddle = np.array([[2040.0, 2048.0], [2040.0, 2048.0]], dtype=np.float32)
        _write_warp(grid, straddle)

        cap_render.write_cap_elevation(grid)
        with rasterio.open(cap_render.cap_work_dir(grid.body) / "cap_tiny_elev.tif") as dataset:
            encoded = dataset.read()
        decoded = terrain_rgb.decode_array(encoded, terrain_rgb.QUANTISATION_M)
        assert abs(float(decoded[0, 0]) - 2044.0) <= terrain_rgb.QUANTISATION_M / 2

        per_cell = terrain_rgb.encode_array(straddle, terrain_rgb.QUANTISATION_M,
                                            terrain_rgb.SHIPPED_SEA_CLAMP)
        byte_mean = per_cell.mean(axis=(1, 2)).round().astype(np.uint8)[:, None, None]
        wrong = float(terrain_rgb.decode_array(byte_mean, terrain_rgb.QUANTISATION_M)[0, 0])
        assert abs(wrong - 2044.0) > 500.0

    def test_the_nodata_sentinel_reads_as_zero_and_real_bathymetry_survives(
            self, tmp_path, monkeypatch):
        """`raw < -1e4 -> 0` is the composite's convention, carried here so the texture and the
        cap's own hillshade describe one surface. Both halves matter: a sentinel left in place
        would drag its whole block kilometres below sea level, and a threshold that crept up to
        catch it would flatten the ocean the cap is supposed to displace."""
        monkeypatch.setattr(cap_render, "_run", lambda cmd: None)
        grid = _tiny_cap(monkeypatch, tmp_path, cap_px=4, elev_px=2)
        heights = np.array([[-32768.0, 0.0, -5000.0, -5000.0],
                            [0.0, 0.0, -5000.0, -5000.0],
                            [800.0, 800.0, 0.0, 0.0],
                            [800.0, 800.0, 0.0, 0.0]], dtype=np.float32)
        _write_warp(grid, heights)

        cap_render.write_cap_elevation(grid)
        with rasterio.open(cap_render.cap_work_dir(grid.body) / "cap_tiny_elev.tif") as dataset:
            decoded = terrain_rgb.decode_array(dataset.read(), terrain_rgb.QUANTISATION_M)
        half = terrain_rgb.QUANTISATION_M / 2
        assert abs(float(decoded[0, 0]) - 0.0) <= half        # sentinel neutralised, not averaged
        assert abs(float(decoded[0, 1]) - -5000.0) <= half    # abyssal plain still 5 km down
        assert abs(float(decoded[1, 0]) - 800.0) <= half

    def test_a_mesh_grid_that_does_not_divide_the_render_grid_is_refused(self, tmp_path,
                                                                        monkeypatch):
        """The box mean is a reshape, so a non-integer factor would raise deep inside numpy with a
        shape error about the wrong thing. Refuse it where the constants are stated."""
        grid = _tiny_cap(monkeypatch, tmp_path, cap_px=8, elev_px=3)
        with pytest.raises(ValueError, match="must divide"):
            cap_render.write_cap_elevation(grid)


class TestCapElevationContract:
    def test_the_encoding_is_imported_from_terrain_rgb_and_never_restated(self, monkeypatch):
        """The cap and the tiles are both drawn across the alpha crossfade, so they must encode
        identically — this is the tie that makes a copied literal fail. Both the recipe (which
        decides whether to re-render) and the manifest (which tells the browser how to decode) have
        to move when the pipeline's step does."""
        recipe_before = cap_render.cap_elev_recipe(cap_render.NORTH)
        manifest_before = json.loads(cap_render.caps_manifest())
        assert manifest_before["north"]["elev_step"] == terrain_rgb.QUANTISATION_M

        monkeypatch.setattr(terrain_rgb, "QUANTISATION_M", 3.0)
        assert cap_render.cap_elev_recipe(cap_render.NORTH) != recipe_before
        assert json.loads(cap_render.caps_manifest())["north"]["elev_step"] == 3.0

    def test_the_cap_carries_bathymetry_because_the_pyramid_does(self):
        """Sea treatment is not a per-product choice. The shipped archive was cut `--sea bathy`
        (terrain_params.json records sea_clamp false), so a cap that clamped the sea to zero would
        sit above the tiles everywhere the crossfade covers ocean — which at the north pole is all
        of it. Pinned rather than followed: if the pyramid is ever re-cut clamped, this should fail
        and be re-decided, not silently agree."""
        assert terrain_rgb.SHIPPED_SEA_CLAMP is False

    def test_the_elevation_stage_is_gated_apart_from_the_colour(self, monkeypatch):
        """Elevation depends on the height warp alone. Folding it into the colour asset set would
        make a step change demand the full composite re-render — the ~14 GB pass — so the texture
        is deliberately absent from `cap_assets`, and its recipe deliberately carries no look."""
        for grid in (cap_render.NORTH, cap_render.SOUTH):
            assert cap_render.cap_elev_asset(grid) not in cap_render.cap_assets(grid)
        recipe = json.loads(cap_render.cap_elev_recipe(cap_render.NORTH))
        assert set(recipe) == {"grid", "elev"}

        before = cap_render.cap_elev_recipe(cap_render.NORTH)
        monkeypatch.setattr(cap_render, "CAP_ELEV_PX", 256)
        assert cap_render.cap_elev_recipe(cap_render.NORTH) != before

    def test_the_manifest_names_the_texture_both_poles_ship(self):
        manifest = json.loads(cap_render.caps_manifest())
        for name, grid in (("north", cap_render.NORTH), ("south", cap_render.SOUTH)):
            assert manifest[name]["elev_url"] == f"/caps/cap_{name}_elev.webp"
            assert cap_render.cap_elev_asset(grid).name == f"cap_{name}_elev.webp"
