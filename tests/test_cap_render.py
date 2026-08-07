"""cap_render's pure layer: grid geometry, the rotated-azimuth shade, and the caps.json
contract the web layer consumes.

The contract tests are the load-bearing ones: `edge_lat` and the feather ceiling
(= shade_planet's Mercator plug boundary) were hand-duplicated as literals in
polarCaps.ts — the same copy-drift species as the hero/tile colour constants. caps.json
makes the pipeline the single author; these tests pin what it publishes.

`test_the_cap_latitude_ladder_holds` pins the one relationship caps.json cannot carry, because
two of its four latitudes are frontend aesthetics that never reach the manifest.

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
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from pipeline import bodies, paths, planet_seam
from pipeline.render import palette, perennial_ice, seaice, snow
from pipeline.tile import cap_render, shade_planet, terrain_rgb

#: A planet whose seam emitted all three rasters — what Earth declares, and the only
#: shape these tests care about unless they say otherwise.
WHOLE_PLANET = planet_seam.KNOWN_RASTERS

#: Earth's two cap grids. The module no longer exposes them as constants — see `north_grid` — so a
#: test that means "the shipped north cap" has to name the body it is talking about, which is the
#: point. Built once here because these are fixtures, not the thing under test.
EARTH_NORTH = cap_render.north_grid(bodies.EARTH)
EARTH_SOUTH = cap_render.south_grid(bodies.EARTH)


class TestCapGridGeometry:
    def test_aeqd_is_pole_centred_spherical(self, subtests):
        """Subtests because these are four independent claims about one projection string, and a
        bad edit to it breaks the projection, both centres and the sphere together."""
        with subtests.test("projection is aeqd"):
            assert "+proj=aeqd" in EARTH_NORTH.aeqd
        with subtests.test("north is centred on the north pole"):
            assert "+lat_0=90.0" in EARTH_NORTH.aeqd
        with subtests.test("south is centred on the south pole"):
            assert "+lat_0=-90.0" in EARTH_SOUTH.aeqd
        with subtests.test("sphere radius"):
            assert f"+a={bodies.EARTH.aeqd_radius_m}" in EARTH_NORTH.aeqd

    def test_edge_m_is_linear_in_colatitude(self):
        """AEQD from the pole: radius = R * colatitude(rad) — the linear law the
        frontend's UV mapping assumes."""
        expected = bodies.EARTH.aeqd_radius_m * np.radians(90.0 - cap_render.CAP_EDGE_LAT)
        assert EARTH_NORTH.edge_m == pytest.approx(expected)
        assert EARTH_SOUTH.edge_m == pytest.approx(expected)  # the mirrored disc, same radius

    def test_the_cap_latitude_ladder_holds(self, subtests):
        """Four latitudes decide where a cap is drawn, and they live in three files and two
        languages. Only two of them reach caps.json, so nothing else can pin the ordering.

        Read as NUMBERS out of the TypeScript rather than matched as literal declarations: the
        invariant is the ordering, not the spelling, and a guard that asserts more than its
        invariant fails on edits that move no pixel.

        `|edge_lat| <= MESH_EDGE_LAT` is the load-bearing one — the mesh spans MESH_EDGE_LAT to
        the pole and samples the texture by the linear AEQD law above, so a mesh reaching further
        equatorward than the disc reads outside the texture and the cap's rim goes to whatever
        the clamp returns.
        """
        source = (paths.ROOT / "web/src/lib/polarCaps.ts").read_text()
        found = {
            name: float(match.group(1))
            for name in ("MESH_EDGE_LAT", "FEATHER_LO")
            if (match := re.search(rf"^export const {name} = (-?[\d.]+);", source, re.MULTILINE))
        }
        assert set(found) == {"MESH_EDGE_LAT", "FEATHER_LO"}, (
            f"polarCaps.ts must export both as plain number literals; parsed {found}"
        )

        with subtests.test("both grids sit at the shared edge latitude"):
            assert abs(EARTH_NORTH.edge_lat) == cap_render.CAP_EDGE_LAT
            assert abs(EARTH_SOUTH.edge_lat) == cap_render.CAP_EDGE_LAT
        with subtests.test("the mesh never reaches outside the texture disc"):
            assert cap_render.CAP_EDGE_LAT <= found["MESH_EDGE_LAT"]
        with subtests.test("the visible feather opens inside the mesh"):
            assert found["MESH_EDGE_LAT"] <= found["FEATHER_LO"]
        with subtests.test("the feather closes below the plug boundary"):
            assert found["FEATHER_LO"] < abs(shade_planet.CAP_NORTH)


class TestLonlatGrid:
    def test_latitude_matches_the_linear_radius_law(self):
        """Independent oracle: on a spherical pole-centred AEQD, latitude at radius rho
        is exactly 90° − degrees(rho / R). Sample centre and edge pixels of a 9-px grid."""
        grid_9px = cap_render.CapGrid(lat_0=90.0, edge_lat=78.0, px=9, name="tiny", az_sign=-1.0,
                                   body=bodies.EARTH)
        _longitude, latitude = cap_render._lonlat_grid(grid_9px)
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


#: Both poles as they shipped, field for field — the golden this module's grids are held to.
#:
#: EVERY FIELD, not the interesting ones. The grids stopped being module constants and became
#: factories, and a factory can quietly answer a question the constant was never asked: a dropped
#: `ice_lo` leaves the southern pack at the NH threshold, a dropped `coast_opacity` draws a dark
#: outline around Antarctica. Both render, and neither raises. This is also the exact block that
#: rides in the freshness sidecar, so a change here is a ~14 GB re-render either way — worth stating
#: once, in full, rather than trusting eight separate assertions to stay complete.
SHIPPED_GRIDS = {
    "north": {"aeqd_radius_m": 6371000.0, "az_sign": -1.0, "coast_dilate": 1,
              "coast_opacity": 0.55, "edge_lat": 80.0, "ice_lo": None, "ice_max_alpha": None,
              "lat_0": 90.0, "name": "north", "px": 8192},
    "south": {"aeqd_radius_m": 6371000.0, "az_sign": 1.0, "coast_dilate": 0,
              "coast_opacity": 0.0, "edge_lat": -80.0, "ice_lo": 0.62, "ice_max_alpha": 0.55,
              "lat_0": -90.0, "name": "south", "px": 8192},
}


#: A second body, deliberately NOT Mars's real figures — the plan has not ratified a radius, and a
#: plausible one here would read as a decision. What matters is that every number differs visibly
#: from Earth's, so a factory that ignored its argument cannot pass by coincidence.
OTHER_BODY = dataclasses.replace(bodies.EARTH, name="other", path_prefix="other",
                                 aeqd_radius_m=1234567.0)


#: The synthetic bodies this file invents, each to prove one field threads somewhere. Not "mars",
#: which is a real registered planet even where a test builds an Earth-shaped stand-in under that
#: name — and which therefore correctly resolves the real Mars look.
SYNTHETIC_BODY_NAMES = ("other", "layerless", "identity", "smaller", "noice", "snowy")


@pytest.fixture(autouse=True)
def _the_synthetic_bodies_have_looks(monkeypatch):
    """A synthetic body needs a look, for the same reason it needs a name and a radius.

    Every cap recipe embeds `composite_params`, which resolves the body's ramp — and `look_for`
    refuses an unregistered body rather than falling back to Earth's, so without this the file
    raises. That refusal is the guard working rather than an inconvenience: a planet inheriting
    Earth's ramp by omission renders a complete, plausible pyramid in another planet's colours.

    The lookup deliberately lives inside `composite_params` rather than being threaded in beside
    the body; `palette.look_for` carries the reasoning, since that is where a reader meets it.

    Scoped to this module's tests rather than registered at import, so the real registry stays
    exactly the two planets `test_palette.py` holds it to.
    """
    for name in SYNTHETIC_BODY_NAMES:
        monkeypatch.setitem(palette.LOOK_BY_BODY, name, palette.EARTH_LOOK)


@pytest.fixture(autouse=True)
def _the_synthetic_bodies_have_ice_producers(monkeypatch):
    """A synthetic body that DECLARES perennial ice needs a producer for it, and `cap_ice` refuses
    an unregistered one rather than reaching for Earth's.

    THE NAME LIST IS THE LOOK FIXTURE'S PLUS `mars`, and that asymmetry is the registries being
    different in kind rather than an oversight. Every real body has a look, so the stand-in named
    `mars` above correctly resolves the real planet's ramp and must stay out of that list. Not every
    real body has ice: Mars declares no surface layers, so it registers no producer and never asks
    for one — while an Earth-SHAPED stand-in wearing the name `mars` inherits Earth's layer set and
    does ask. The stand-in is what needs the entry, not the planet.

    Earth's own producers, because these bodies are Earth with one field replaced. What that buys is
    a test that can vary the layer declaration, the disk and the seam independently while the
    machinery painting the ice is the machinery that ships.
    """
    for name in (*SYNTHETIC_BODY_NAMES, "mars"):
        for pole in ("north", "south"):
            monkeypatch.setitem(perennial_ice.CAP_ICE_BY_BODY, (name, pole),
                                perennial_ice.CAP_ICE_BY_BODY[("earth", pole)])


class TestTheGridsAreBuiltPerBody:
    def test_earths_grids_are_field_for_field_what_they_shipped(self, subtests):
        for name, grid in (("north", EARTH_NORTH), ("south", EARTH_SOUTH)):
            with subtests.test(name):
                assert json.loads(cap_render.cap_recipe(grid, WHOLE_PLANET))["grid"] == SHIPPED_GRIDS[name]

    def test_a_factory_carries_the_body_it_was_given_all_the_way_through(self, subtests):
        """A factory that pinned Earth would be invisible everywhere it mattered: the cap would
        project on Earth's sphere (landing on the wrong parallel), read Earth's fused heightfield,
        and overwrite Earth's shipped textures — all while rendering a perfectly clean disc.

        Asserted at three depths on purpose. The body reaching the dataclass is not the claim; the
        claim is that the projection string, the served location and the recipe all follow it.
        """
        for label, grid in (("north", cap_render.north_grid(OTHER_BODY)),
                            ("south", cap_render.south_grid(OTHER_BODY))):
            with subtests.test(label):
                assert grid.body is OTHER_BODY
                assert f"+a={OTHER_BODY.aeqd_radius_m}" in grid.aeqd
                assert (cap_render.cap_asset(grid, 8192).parent
                        == paths.ROOT / "web/public/caps/other")
                assert (json.loads(cap_render.cap_recipe(grid, WHOLE_PLANET))["grid"]["aeqd_radius_m"]
                        == OTHER_BODY.aeqd_radius_m)

    def test_the_served_url_matches_where_the_texture_is_actually_written(self, subtests):
        """caps.json is fetched by the browser, so a URL that disagrees with the file's location is
        a 404 that no pipeline gate can see — the pyramid renders, the manifest validates, and the
        pole is simply missing. Earth's URLs are pinned as the contract they already are.
        """
        with subtests.test("earth"):
            manifest = json.loads(cap_render.caps_manifest(bodies.EARTH))
            assert manifest["north"]["rungs"][0]["url"] == "/caps/cap_north_1024.webp"
            assert manifest["south"]["elev_url"] == "/caps/cap_south_elev.webp"
        with subtests.test("a nesting body"):
            manifest = json.loads(cap_render.caps_manifest(OTHER_BODY))
            assert manifest["north"]["rungs"][0]["url"] == "/caps/other/cap_north_1024.webp"
            assert manifest["south"]["elev_url"] == "/caps/other/cap_south_elev.webp"
        with subtests.test("every url resolves back to its own file"):
            for body in (bodies.EARTH, OTHER_BODY):
                manifest = json.loads(cap_render.caps_manifest(body))
                for name, grid in (("north", cap_render.north_grid(body)),
                                   ("south", cap_render.south_grid(body))):
                    for rung in manifest[name]["rungs"]:
                        assert (bodies.public_root() / rung["url"].lstrip("/")
                                == cap_render.cap_asset(grid, rung["px"]))
                    assert (bodies.public_root() / manifest[name]["elev_url"].lstrip("/")
                            == cap_render.cap_elev_asset(grid))


class TestTheCapPassRequiresABody:
    """`--body` has no default here for the same reason the shade pass has none.

    A cap is the one output where the wrong sphere is entirely invisible: it projects, it blends,
    it downsamples to every rung — and it sits on the wrong parallel, feathering into tiles drawn on
    a different globe. Nothing in the pipeline can report that, and nothing in the picture shows it.
    """

    def test_omitting_the_body_is_an_error_rather_than_an_assumption(self):
        with pytest.raises(SystemExit):
            cap_render.build_parser().parse_args([])

    def test_a_named_body_still_parses_the_pole_and_force_flags(self):
        """The required argument must not have displaced the flags a pole-look loop actually uses."""
        args = cap_render.build_parser().parse_args(["--body", "earth", "--north", "--force"])
        assert (args.body, args.north, args.south, args.force) == ("earth", True, False, True)

    def test_an_unknown_body_is_rejected_by_the_registry_not_silently_accepted(self):
        args = cap_render.build_parser().parse_args(["--body", "pluto"])
        with pytest.raises(KeyError):
            bodies.get(args.body)


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
            assert (cap_render.cap_asset(EARTH_NORTH, 8192)
                    == paths.ROOT / "web/public/caps/cap_north_8192.webp")
        with subtests.test("served elevation texture"):
            assert (cap_render.cap_elev_asset(EARTH_SOUTH)
                    == paths.ROOT / "web/public/caps/cap_south_elev.webp")
        with subtests.test("intermediate height warp"):
            # Both poles, because the N/S prefix is DERIVED from the grid: one pole alone would
            # pass just as happily against a hardcoded prefix, which is a north renderer and a
            # south renderer sharing one set of warps.
            assert (cap_render.cap_height_warp(EARTH_NORTH)
                    == paths.DATA / "work/cap/capN_height.tif")
            assert (cap_render.cap_height_warp(EARTH_SOUTH)
                    == paths.DATA / "work/cap/capS_height.tif")
            assert (cap_render.cap_warp(EARTH_SOUTH, "seaice")
                    == paths.DATA / "work/cap/capS_seaice.tif")
        with subtests.test("fused planet source"):
            assert (paths.DATA / "work/planet/planet_heightfield.vrt"
                    in cap_render.cap_sources(EARTH_NORTH, WHOLE_PLANET))

    def test_a_second_body_cannot_land_its_caps_on_earths(self, subtests):
        """The failure this forbids is silent and destructive in one direction only: a Mars cap
        written to `web/public/caps/cap_north_8192.webp` overwrites Earth's shipped texture, and
        nothing downstream would report anything but a wrong-looking pole.

        Reading matters as much as writing — a Mars cap that sourced Earth's fused heightfield would
        render a perfectly clean Arctic and call it Mars.
        """
        mars = dataclasses.replace(bodies.EARTH, name="mars", path_prefix="mars")
        grid = dataclasses.replace(EARTH_NORTH, body=mars)
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
                    in cap_render.cap_sources(grid, WHOLE_PLANET))


class TestCapsManifest:
    def test_contract_fields_come_from_their_single_homes(self):
        manifest = json.loads(cap_render.caps_manifest(bodies.EARTH))
        for name, grid in (("north", EARTH_NORTH), ("south", EARTH_SOUTH)):
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
        for grid in (EARTH_NORTH, EARTH_SOUTH):
            assert cap_render.CAP_RUNGS[-1] == grid.px

    def test_manifest_is_stable_json(self):
        assert cap_render.caps_manifest(bodies.EARTH) == cap_render.caps_manifest(bodies.EARTH)


class TestRecipeCoversTheAsset:
    def test_webp_quality_rides_in_the_recipe(self, monkeypatch):
        """The encoder setting changes the shipped pixels, so it must restage the cap —
        the same freshness rule that caught the stale caps."""
        before = cap_render.cap_recipe(EARTH_NORTH, WHOLE_PLANET)
        assert '"webp"' in before
        monkeypatch.setattr(cap_render, "CAP_WEBP_QUALITY", 101)
        assert cap_render.cap_recipe(EARTH_NORTH, WHOLE_PLANET) != before

    def test_rung_set_rides_in_the_recipe(self, monkeypatch):
        """Adding a rung changes the shipped ASSET SET, so it must restage — otherwise the new
        rung's file would never be written and the manifest would advertise a 404."""
        before = cap_render.cap_recipe(EARTH_NORTH, WHOLE_PLANET)
        monkeypatch.setattr(cap_render, "CAP_RUNGS", (2048, cap_render.CAP_PX))
        assert cap_render.cap_recipe(EARTH_NORTH, WHOLE_PLANET) != before


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
    # check=False: this is a CAPABILITY probe, so a non-zero exit is an answer ("no WEBP") rather
    # than an error — raising here would turn a missing format into a collection-time crash.
    registry = subprocess.run(["gdalinfo", "--formats"],
                              capture_output=True, text=True, check=False).stdout
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
        recipe_before = cap_render.cap_elev_recipe(EARTH_NORTH)
        manifest_before = json.loads(cap_render.caps_manifest(bodies.EARTH))
        assert manifest_before["north"]["elev_step"] == terrain_rgb.QUANTISATION_M

        monkeypatch.setattr(terrain_rgb, "QUANTISATION_M", 3.0)
        assert cap_render.cap_elev_recipe(EARTH_NORTH) != recipe_before
        assert json.loads(cap_render.caps_manifest(bodies.EARTH))["north"]["elev_step"] == 3.0

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
        for grid in (EARTH_NORTH, EARTH_SOUTH):
            assert cap_render.cap_elev_asset(grid) not in cap_render.cap_assets(grid)
        recipe = json.loads(cap_render.cap_elev_recipe(EARTH_NORTH))
        assert set(recipe) == {"grid", "elev"}

        before = cap_render.cap_elev_recipe(EARTH_NORTH)
        monkeypatch.setattr(cap_render, "CAP_ELEV_PX", 256)
        assert cap_render.cap_elev_recipe(EARTH_NORTH) != before

    def test_the_manifest_names_the_texture_both_poles_ship(self):
        manifest = json.loads(cap_render.caps_manifest(bodies.EARTH))
        for name, grid in (("north", EARTH_NORTH), ("south", EARTH_SOUTH)):
            assert manifest[name]["elev_url"] == f"/caps/cap_{name}_elev.webp"
            assert cap_render.cap_elev_asset(grid).name == f"cap_{name}_elev.webp"


#: A body that declares no layers at all — the whole of what a second planet costs the cap pass.
#:
#: Built from Earth so that geometry, exaggeration and grid are held fixed and `surface_layers` is
#: the only thing varying. A synthetic body with several fields changed cannot say WHICH one a gate
#: responded to.
LAYERLESS_BODY = dataclasses.replace(bodies.EARTH, name="layerless", path_prefix="layerless",
                                     surface_layers=frozenset())


def _drive_cap(monkeypatch, tmp_path, body, pole, missing=(), rasters=None):
    """Run one REAL cap renderer with its two GDAL edges recorded rather than executed.

    `_warp` and `_write_cap` are the boundaries of the code under test — one shells out to gdalwarp,
    the other writes a texture — so they are captured. Everything between them, which is every layer
    gate, is the real function. Recording `_warp` IS the assertion: a layer that is off must never
    reach it, and a test that only inspected the composite's arguments would pass a version that
    warped Earth's climatology and then discarded it.

    Every Earth source is redirected onto a file that DOES exist here, and that is the point rather
    than a convenience — it reproduces the build box, where each of these is one global path to an
    Earth dataset present whatever planet is being rendered. A gate that consulted the disk before
    the body would pass on all of them.

    `missing` names sources to point at a path that does NOT exist, so the disk half of the gate can
    be exercised on a body that does declare the layer — body-first is not body-only.

    `rasters` is the planet seam's declaration, defaulting to a whole planet because most of these
    tests vary the SURFACE LAYERS and want the masks held fixed. The mask-less case has its own
    class below, where it is the subject rather than the background.

    The coastline is deliberately not exercised here: it is baked inside `_write_cap`, which this
    replaces. `TestTheCoastlineIsABodyFact` drives that gate directly.
    """
    monkeypatch.setattr(paths, "DATA", tmp_path / "data")
    monkeypatch.setattr(paths, "ROOT", tmp_path / "checkout")
    present = tmp_path / "an-earth-dataset-this-box-already-has"
    present.write_text("")
    absent = tmp_path / "never-downloaded"
    for attribute, module in (("SP_NC", snow), ("SEAICE_SRC", seaice)):
        monkeypatch.setattr(module, attribute,
                            str(absent if attribute in missing else present))
    monkeypatch.setattr(cap_render, "COAST_SHP",
                        absent if "COAST_SHP" in missing else present)

    warped: list[str] = []

    def fake_warp(grid, src, out, resampling, dtype, srcnodata=None):
        warped.append(Path(out).stem.split("_", 1)[1])
        return np.zeros((grid.px, grid.px), dtype=np.float32)

    painted: dict[str, Any] = {}

    def fake_write(grid, heights, ocean, water, snow_a, ice_a, hillshade_dn):
        painted.update(snow_a=snow_a, ice_a=ice_a)
        return tmp_path / f"cap_{grid.name}.webp"

    monkeypatch.setattr(cap_render, "_warp", fake_warp)
    monkeypatch.setattr(cap_render, "_write_cap", fake_write)

    factory, render = ((cap_render.north_grid, cap_render.render_cap_north) if pole == "north"
                       else (cap_render.south_grid, cap_render.render_cap_south))
    render(dataclasses.replace(factory(body), px=8),
           WHOLE_PLANET if rasters is None else rasters)
    return sorted(warped), painted


class TestTheCapPassAsksTheBodyBeforeTheDisk:
    """The layer gates, driven through the real renderers.

    The failure these close has no symptom: a Mars cap wearing Earth's Arctic renders cleanly, at the
    same latitudes, and simply describes another planet. So each test asserts on what was OPENED, not
    on how the picture looked.
    """

    def test_earth_warps_its_cryosphere_at_both_poles(self, tmp_path, monkeypatch, subtests):
        """The positive control, and the reason the negatives below mean anything: with the layers
        declared, both climatologies are read exactly as they always were."""
        north, painted_n = _drive_cap(monkeypatch, tmp_path, bodies.EARTH, "north")
        with subtests.test("north"):
            assert north == ["height", "ocean", "seaice", "sp", "water"]
            assert painted_n["ice_a"] is not None

        south, painted_s = _drive_cap(monkeypatch, tmp_path, bodies.EARTH, "south")
        with subtests.test("south"):
            # No `sp`: the south's snow is forced, never read from a dataset.
            assert south == ["height", "ocean", "seaice", "water"]
            assert painted_s["ice_a"] is not None
            # Antarctica forced white — the whole disc is land below -60 in this fixture.
            assert np.all(painted_s["snow_a"] == 1.0)

    def test_a_body_with_no_layers_opens_none_of_earths_files(self, tmp_path, monkeypatch,
                                                             subtests):
        """The bug this commit exists to close. Every source is present on disk in this fixture, so
        the only thing that can refuse them is the body — and it must, at both poles."""
        for pole in ("north", "south"):
            with subtests.test(pole):
                warped, painted = _drive_cap(monkeypatch, tmp_path, LAYERLESS_BODY, pole)
                assert warped == ["height", "ocean", "water"]
                assert painted["ice_a"] is None
                assert np.all(painted["snow_a"] == 0.0)

    def test_the_forced_antarctic_patch_is_refused_for_a_body_with_no_ice_layer(
            self, tmp_path, monkeypatch):
        """The one rule with no file behind it, and therefore the one nothing on disk could ever
        switch off. It is pure latitude and land, so on a sea-less body it would whiten every scrap
        of ground below 60 degrees south and call it an ice cap.

        Asserted against Earth's own south cap in the same fixture, which forces the whole disc
        white: the two runs differ in `surface_layers` and in nothing else.
        """
        _, earths = _drive_cap(monkeypatch, tmp_path, bodies.EARTH, "south")
        _, layerless = _drive_cap(monkeypatch, tmp_path, LAYERLESS_BODY, "south")
        assert np.all(earths["snow_a"] == 1.0)
        assert np.all(layerless["snow_a"] == 0.0)

    def test_a_missing_dataset_still_skips_the_layer_for_a_body_that_declares_it(
            self, tmp_path, monkeypatch):
        """Body first does not mean body only. Earth with the download absent must skip the layer
        rather than crash the pass — that half of the gate predates this commit and has to survive
        it, or a partial build stops being legal."""
        warped, painted = _drive_cap(monkeypatch, tmp_path, bodies.EARTH, "north",
                                     missing={"SP_NC"})
        assert warped == ["height", "ocean", "seaice", "water"]  # no `sp`
        assert np.all(painted["snow_a"] == 0.0)
        assert painted["ice_a"] is not None  # the OTHER layer is unaffected


class TestTheCoastlineIsABodyFact:
    """`COAST_SHP` is one global path to a Natural Earth product. Its presence answers "did we
    download Earth's vectors", which is yes for every planet on this box."""

    def test_earth_bakes_it_in_the_north_and_declines_it_in_the_south(self, subtests, monkeypatch,
                                                                     tmp_path):
        present = tmp_path / "ne_10m_coastline.shp"
        present.write_text("")
        monkeypatch.setattr(cap_render, "COAST_SHP", present)
        with subtests.test("north"):
            assert cap_render.bakes_coastline(cap_render.north_grid(bodies.EARTH)) is True
        with subtests.test("south"):
            # A look decision, unchanged: white ice on teal ocean separates itself.
            assert cap_render.bakes_coastline(cap_render.south_grid(bodies.EARTH)) is False

    def test_a_body_without_the_layer_declines_it_though_earths_file_is_right_there(
            self, monkeypatch, tmp_path):
        present = tmp_path / "ne_10m_coastline.shp"
        present.write_text("")
        monkeypatch.setattr(cap_render, "COAST_SHP", present)
        grid = cap_render.north_grid(LAYERLESS_BODY)
        assert present.exists()
        assert grid.coast_opacity == 0.55  # the LOOK still says draw it; the body says there is none
        assert cap_render.bakes_coastline(grid) is False

    def test_the_opacity_stays_a_look_constant_rather_than_a_second_copy_of_the_body_fact(self):
        """Deriving `coast_opacity` from the body would record the same fact twice — as a 0.0 in the
        grid block and as an entry in `layers_off` — which is the copy-drift the registry removes."""
        assert cap_render.north_grid(LAYERLESS_BODY).coast_opacity == 0.55
        recipe = json.loads(cap_render.cap_recipe(cap_render.north_grid(LAYERLESS_BODY), WHOLE_PLANET))
        assert recipe["grid"]["coast_opacity"] == 0.55
        assert "coastline" in recipe["layers_off"]


class TestCapSourcesFollowTheLayers:
    def test_a_source_for_an_absent_layer_is_not_a_dependency(self, subtests):
        """`cap_is_fresh` demands every source EXIST and be older than the oldest rung, so listing
        Earth's climatology for a body that paints no ice ties that body's caps to the mtime of a
        file whose contents can never reach a pixel of them."""
        for pole, factory in (("north", cap_render.north_grid),
                              ("south", cap_render.south_grid)):
            with subtests.test(pole):
                earth = cap_render.cap_sources(factory(bodies.EARTH), WHOLE_PLANET)
                bare = cap_render.cap_sources(factory(LAYERLESS_BODY), WHOLE_PLANET)
                assert Path(seaice.SEAICE_SRC) in earth
                assert not any(source.name == Path(seaice.SEAICE_SRC).name for source in bare)
                assert len(bare) == 3  # heightfield, oceanmask, watermask — the body's own relief

    def test_a_caps_sources_are_exactly_what_its_own_producer_declares(self, monkeypatch, subtests,
                                                                       tmp_path):
        """The two halves of the seam cannot drift: what a producer READS and what makes its cap
        STALE are one declaration, asked of the body rather than of Earth.

        A SECOND, GENUINELY DIFFERENT PRODUCER IS WHAT MAKES THIS FALSIFIABLE. Asked of Earth alone
        the claim passes against a `cap_sources` that consults Earth's registry entry directly and
        ignores the body — Earth's answer IS Earth's producer, at both poles, so the wrong lookup
        returns the right list. The synthetic body below reads a file Earth never opens, at the pole
        where Earth reads none, so only a body-derived lookup can produce it.
        """
        elsewhere = tmp_path / "another-worlds-ice.gpkg"
        for pole, factory in (("north", cap_render.north_grid), ("south", cap_render.south_grid)):
            monkeypatch.setitem(perennial_ice.CAP_ICE_BY_BODY, ("other", pole),
                                perennial_ice.CapIce(sources=lambda: (elsewhere,),
                                                     alpha=lambda inputs: np.zeros(())))
            with subtests.test(pole):
                other = dataclasses.replace(bodies.EARTH, name="other", path_prefix="other")
                sources = cap_render.cap_sources(factory(other), WHOLE_PLANET)
                assert elsewhere in sources
                assert not any(source == Path(snow.SP_NC) for source in sources)


class TestTheCapIsShadedInGroundMetres:
    """The cap's map units are metres on `aeqd_radius_m`, its heights are ground metres on the body.
    Divide one by the other without converting and the slope is a number in neither unit."""

    def _zfactors(self, monkeypatch, body):
        seen: list[float] = []
        real = cap_render.hillshade.hillshade_array

        def spy(heights, cell, zfactor, altitude, azimuth):
            seen.append(zfactor)
            return real(heights, cell, zfactor, altitude, azimuth)

        monkeypatch.setattr(cap_render.hillshade, "hillshade_array", spy)
        grid = cap_render.CapGrid(lat_0=90.0, edge_lat=78.0, px=8, name="tiny", az_sign=-1.0,
                                  body=body)
        cap_render._shade(grid, np.zeros((8, 8), dtype=np.float32),
                          np.zeros((8, 8), dtype=np.float32))
        return seen

    def test_both_lights_are_driven_at_the_ground_scaled_z_factor(self, monkeypatch):
        """Main and fill, not just the main one: they are two calls, and a correction applied to one
        of them tilts the fill against the light it is meant to soften."""
        expected = bodies.EARTH.exaggeration / bodies.ground_metres_per_aeqd_unit(bodies.EARTH)
        assert self._zfactors(monkeypatch, bodies.EARTH) == [expected, expected]
        assert expected != bodies.EARTH.exaggeration  # Earth's cap ratio is 1.0011202, not 1.0

    def test_a_body_whose_spheres_coincide_is_driven_at_its_bare_exaggeration(self, monkeypatch):
        """The discriminator that a wrong-way division cannot pass: with ground and AEQD radius
        equal the ratio is exactly 1, so the z-factor must be the exaggeration itself — inverting
        the quotient leaves this case identical and every other case wrong."""
        identity = dataclasses.replace(bodies.EARTH, name="identity",
                                       ground_radius_m=bodies.EARTH.aeqd_radius_m)
        assert self._zfactors(monkeypatch, identity) == [15.0, 15.0]

    def test_a_smaller_body_is_shaded_more_steeply_for_the_same_exaggeration(self, monkeypatch):
        """A body half Earth's size fits the same angle into half the ground distance, so the same
        physical exaggeration needs roughly twice the z-factor. Direction AND magnitude, because a
        correction applied backwards is still monotonic in the body's radius."""
        smaller = dataclasses.replace(bodies.EARTH, name="smaller", ground_radius_m=3396190.0)
        got = self._zfactors(monkeypatch, smaller)
        assert got[0] == pytest.approx(15.0 / (3396190.0 / 6371000.0))
        assert got[0] == pytest.approx(28.14, abs=0.01)
        assert got[0] > self._zfactors(monkeypatch, bodies.EARTH)[0]

    def test_the_ground_scale_rides_in_the_recipe_that_gates_the_render(self, monkeypatch):
        """Unconditionally, unlike the Mercator one: no body's cap ratio is the identity, so a
        conditional would never fire and would only read as though it might. Untracked, a body
        change would leave a cap falsely fresh at another planet's relief."""
        recipe = json.loads(cap_render.cap_recipe(EARTH_NORTH, WHOLE_PLANET))
        assert recipe["light"]["ground_scale"] == bodies.ground_metres_per_aeqd_unit(bodies.EARTH)
        smaller = dataclasses.replace(bodies.EARTH, name="smaller", ground_radius_m=3396190.0)
        other = cap_render.cap_recipe(dataclasses.replace(EARTH_NORTH, body=smaller), WHOLE_PLANET)
        assert json.loads(other)["light"]["ground_scale"] != recipe["light"]["ground_scale"]

    def test_the_elevation_texture_is_not_dragged_through_the_ground_scale(self):
        """It encodes true metres and contains no slope at all, so a ground scale in the shared grid
        block would re-encode both displacement textures for a number they never read."""
        assert "ground_scale" not in json.dumps(
            cap_render.grid_recipe_fields(EARTH_NORTH))
        assert "ground_scale" not in cap_render.cap_elev_recipe(EARTH_NORTH)


class TestTheCapRecipeRecordsWhatIsOff:
    def test_earth_records_no_layers_off_so_its_caps_keep_their_recipe_shape(self):
        assert "layers_off" not in json.loads(cap_render.cap_recipe(EARTH_NORTH, WHOLE_PLANET))
        assert "layers_off" not in json.loads(cap_render.cap_recipe(EARTH_SOUTH, WHOLE_PLANET))

    def test_a_bare_body_records_exactly_the_cap_layers_it_lacks(self):
        """The cap vocabulary, not the whole one: `lake_depth` and `glaciers` never reach a cap, so
        recording them would restage a 14 GB render on a decision it cannot contain."""
        recipe = json.loads(cap_render.cap_recipe(cap_render.north_grid(LAYERLESS_BODY), WHOLE_PLANET))
        assert recipe["layers_off"] == ["coastline", "perennial_ice", "sea_ice"]

    def test_turning_a_layer_off_restages_although_its_source_stops_being_a_dependency(self):
        """The two halves have to move together. Switching a layer off REMOVES its file from
        `cap_sources`, so the mtime that would have noticed disappears along with the layer — the
        recipe is the only thing left that can tell the cap it is stale."""
        with_ice = cap_render.north_grid(bodies.EARTH)
        without = cap_render.north_grid(
            dataclasses.replace(bodies.EARTH, name="noice",
                                surface_layers=bodies.EARTH.surface_layers - {"sea_ice"}))
        assert Path(seaice.SEAICE_SRC) in cap_render.cap_sources(with_ice, WHOLE_PLANET)
        assert Path(seaice.SEAICE_SRC) not in cap_render.cap_sources(without, WHOLE_PLANET)
        assert cap_render.cap_recipe(with_ice, WHOLE_PLANET) != cap_render.cap_recipe(without, WHOLE_PLANET)


class TestTheCapPassAsksTheSeamBeforeTheDisk:
    """The planet-seam gate on the cap path — the mask half of what the layer gates do for snow.

    Same failure shape, one tier up: `planet_oceanmask.vrt` is a path under a body's own directory,
    so its absence really can mean "this planet has no sea" — but it can equally mean the fusion
    died two rasters in, and a cap rendered from that is a clean, confident, half-built pole.
    """

    HEIGHTFIELD_ONLY = frozenset({"heightfield"})

    def test_an_undeclared_mask_is_never_warped(self, monkeypatch, tmp_path, subtests):
        for pole in ("north", "south"):
            with subtests.test(pole):
                warped, _painted = _drive_cap(monkeypatch, tmp_path, LAYERLESS_BODY, pole,
                                              rasters=self.HEIGHTFIELD_ONLY)
                assert "ocean" not in warped and "water" not in warped
                assert "height" in warped, "the cap must still warp the heightfield"

    def test_a_declared_mask_is_warped(self, monkeypatch, tmp_path, subtests):
        """The mirror arm, without which the test above passes against a cap that warps nothing."""
        for pole in ("north", "south"):
            with subtests.test(pole):
                warped, _painted = _drive_cap(monkeypatch, tmp_path, LAYERLESS_BODY, pole)
                assert "ocean" in warped and "water" in warped

    def test_the_forced_antarctic_patch_sees_a_planet_of_pure_land(self, monkeypatch, tmp_path):
        """A body with no sea AND a snow layer is the composed case: `land = ~(ocean | water)` is
        everything, so the patch whitens the whole disc. That is the honest consequence of the two
        declarations, and it is pinned so nobody re-derives it as a bug in the mask gate."""
        snowy = dataclasses.replace(bodies.EARTH, name="snowy", path_prefix="snowy",
                                    surface_layers=frozenset({"perennial_ice"}))
        _warped, painted = _drive_cap(monkeypatch, tmp_path, snowy, "south",
                                      rasters=self.HEIGHTFIELD_ONLY)
        assert painted["snow_a"].all()

    def test_cap_sources_drops_a_mask_the_planet_never_emitted(self, subtests):
        """`cap_is_fresh` requires every source to EXIST, so a listed raster that was never built
        pins the cap to a file whose contents can never reach a pixel of it."""
        for name, factory in (("north", cap_render.north_grid), ("south", cap_render.south_grid)):
            with subtests.test(name):
                grid = factory(LAYERLESS_BODY)
                bare = cap_render.cap_sources(grid, self.HEIGHTFIELD_ONLY)
                assert [path.name for path in bare] == ["planet_heightfield.vrt"]
                assert (cap_render.cap_sources(grid, WHOLE_PLANET)
                        == [cap_render.planet_seam.vrt_path(LAYERLESS_BODY, raster)
                            for raster in cap_render.planet_seam.PLANET_RASTERS])

    def test_the_cap_recipe_records_the_rasters_that_are_off(self, subtests):
        with subtests.test("earth records nothing"):
            assert "rasters_off" not in json.loads(
                cap_render.cap_recipe(EARTH_NORTH, WHOLE_PLANET))["composite"]
        with subtests.test("a maskless planet records both"):
            recipe = json.loads(cap_render.cap_recipe(
                cap_render.north_grid(LAYERLESS_BODY), self.HEIGHTFIELD_ONLY))
            assert recipe["composite"]["rasters_off"] == ["oceanmask", "watermask"]
        with subtests.test("so switching one off restages the cap"):
            grid = cap_render.north_grid(LAYERLESS_BODY)
            assert (cap_render.cap_recipe(grid, WHOLE_PLANET)
                    != cap_render.cap_recipe(grid, self.HEIGHTFIELD_ONLY))
