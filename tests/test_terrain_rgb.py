"""Terrain-RGB encode/decode, the polar feather, and the resampler that must never change.

The load-bearing test here is `test_cut_zoom_never_resamples_encoded_bytes`. Every other property
would survive someone "optimising" the cut to `average` or `cubic`; that one is the whole reason
the module exists, and nothing else in the suite would go red.
"""

import inspect
import json
import re
import shutil
import subprocess

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from pipeline.raster_io import band_window
from pipeline.tile import terrain_rgb

MERCATOR_HALF = 20037508.342789244


def encode_decode(metres, step=1.0, sea_clamp=False, latitudes=None):
    """Round-trip a 2-D array of metres through the shipped pair."""
    array = np.asarray(metres, dtype=np.float64)
    return terrain_rgb.decode_array(
        terrain_rgb.encode_array(array, step, sea_clamp, latitudes), step)


# --- The encoding -------------------------------------------------------------------


@pytest.mark.parametrize("step", [1.0, 2.0, 4.0, 8.0])
def test_round_trip_is_within_half_a_quantisation_step(step):
    metres = np.linspace(-11000.0, 8900.0, 400).reshape(20, 20)
    error = np.abs(encode_decode(metres, step=step) - metres)
    assert error.max() <= step / 2 + 1e-9


def test_the_round_trip_oracle_can_actually_fail():
    """A check that cannot fail is indistinguishable from one that passed."""
    metres = np.linspace(-11000.0, 8900.0, 400).reshape(20, 20)
    encoded = terrain_rgb.encode_array(metres, 1.0, False)
    encoded[1, 5, 5] = (int(encoded[1, 5, 5]) + 40) % 256  # one byte, one pixel
    error = np.abs(terrain_rgb.decode_array(encoded, 1.0) - metres)
    assert error.max() > 0.5


def test_blue_channel_is_always_zero():
    """It carries terrarium's sub-metre fraction, which a 305 m/px grid cannot hold — and it
    measured 2.5x larger for that noise."""
    encoded = terrain_rgb.encode_array(
        np.random.default_rng(0).uniform(-9000, 8800, (32, 32)), 1.0, False)
    assert not encoded[2].any()


def test_step_one_is_exactly_mapzen_terrarium():
    """At the default step the style needs no `custom` factors at all — so pin the equality."""
    metres = np.linspace(-11000.0, 8800.0, 256).reshape(16, 16)
    red, green, _ = terrain_rgb.encode_array(metres, 1.0, False)
    terrarium = red.astype(np.float64) * 256.0 + green.astype(np.float64) - 32768.0
    assert np.abs(terrarium - np.round(metres)).max() == 0


def test_encoding_saturates_instead_of_wrapping():
    """Out-of-range must clamp: a wrap would put Everest at the bottom of the ocean."""
    decoded = encode_decode([[-40000.0, 40000.0]], step=1.0)
    assert decoded[0, 0] == pytest.approx(-32768.0)
    assert decoded[0, 1] == pytest.approx(65535.0 - 32768.0)


# --- Sea treatment ------------------------------------------------------------------


def test_sea_clamp_flattens_the_seafloor_and_leaves_land_alone():
    metres = np.array([[-5656.0, -200.0, 0.0, 1500.0]])
    clamped = encode_decode(metres, sea_clamp=True)
    assert clamped.tolist() == [[0.0, 0.0, 0.0, 1500.0]]


def test_bathymetry_survives_when_not_clamped():
    metres = np.array([[-5656.0, -200.0, 0.0, 1500.0]])
    assert encode_decode(metres, sea_clamp=False) == pytest.approx(metres, abs=0.5)


def test_a_clamped_ocean_encodes_to_one_repeated_value():
    """This is what collapses an abyssal tile from 162 KiB to 1.5 KiB — most of the archive."""
    encoded = terrain_rgb.encode_array(
        np.random.default_rng(1).uniform(-6000, -100, (64, 64)), 1.0, True)
    assert len(np.unique(encoded.reshape(3, -1), axis=1)[0]) == 1


# --- The polar feather --------------------------------------------------------------


def test_feather_is_one_equatorward_and_zero_poleward():
    factors = terrain_rgb.feather_factor(np.array([0.0, 60.0, 78.0, 85.0, 88.0, -85.0, -60.0]))
    assert factors[:3] == pytest.approx(1.0)
    assert factors[3:6] == pytest.approx(0.0)
    assert factors[6] == pytest.approx(1.0)


def test_feather_is_monotonic_and_flat_at_both_ends():
    """Smoothstep, not linear: this multiplies geometry, and a slope break is a visible crease."""
    latitudes = np.linspace(78.0, 85.0, 200)
    factors = terrain_rgb.feather_factor(latitudes)
    assert np.all(np.diff(factors) <= 1e-12)
    slope = np.diff(factors)
    assert abs(slope[0]) < abs(slope[len(slope) // 2])
    assert abs(slope[-1]) < abs(slope[len(slope) // 2])


def test_feather_drives_antarctic_ice_to_zero_at_the_cap_seam():
    """The south cap sits over 2-3 km of ice; undamped, that is the geometric step it would open."""
    latitudes = np.array([-70.0, -81.5, -86.0])
    decoded = encode_decode(np.full((3, 4), 3000.0), latitudes=latitudes)
    assert decoded[0].tolist() == pytest.approx([3000.0] * 4)
    assert 0.0 < decoded[1, 0] < 3000.0
    assert decoded[2].tolist() == pytest.approx([0.0] * 4)


def test_row_latitudes_are_inverse_mercator_not_linear():
    """Linear interpolation would put the feather on the wrong parallels by degrees."""
    latitudes = terrain_rgb.row_latitudes(0, 4, 4, MERCATOR_HALF, -MERCATOR_HALF)
    assert latitudes[0] > 70.0            # top row is deep in the Arctic
    assert latitudes[1] == pytest.approx(-latitudes[2], abs=1e-9)   # symmetric about the equator
    linear = np.linspace(85.05, -85.05, 4)
    assert abs(latitudes[1] - linear[1]) > 5.0


# --- Downsampling: in metres, never in bytes ----------------------------------------


def _write_elevation(path, array):
    height, width = array.shape
    with rasterio.open(
            path, "w", driver="GTiff", height=height, width=width, count=1, dtype="float32",
            crs="EPSG:3857",
            transform=from_bounds(-MERCATOR_HALF, -MERCATOR_HALF, MERCATOR_HALF, MERCATOR_HALF,
                                  width, height)) as sink:
        sink.write(array.astype(np.float32), 1)


def test_downsample_is_a_box_mean_in_metres(tmp_path):
    source, target = tmp_path / "in.tif", tmp_path / "out.tif"
    array = np.arange(64, dtype=np.float32).reshape(8, 8)
    _write_elevation(source, array)
    terrain_rgb.downsample_elevation(source, target, 2, band_rows=2)
    with rasterio.open(target) as ds:
        assert ds.shape == (4, 4)
        assert ds.read(1) == pytest.approx(array.reshape(4, 2, 4, 2).mean(axis=(1, 3)))


def test_downsample_streams_rather_than_reading_the_raster(tmp_path):
    """Band-by-band and whole-raster must agree, because the master is 46 GB and only one of
    those two ever runs in production."""
    source = tmp_path / "in.tif"
    array = np.random.default_rng(2).uniform(-8000, 8000, (16, 16)).astype(np.float32)
    _write_elevation(source, array)
    results = []
    for band_rows in (1, 8):
        target = tmp_path / f"out{band_rows}.tif"
        terrain_rgb.downsample_elevation(source, target, 2, band_rows=band_rows)
        with rasterio.open(target) as ds:
            results.append(ds.read(1))
    assert results[0] == pytest.approx(results[1])


def test_band_rows_are_budgeted_on_the_source_side(tmp_path):
    """A fixed OUTPUT band scales peak RAM with the factor: at the master's width, 256 output rows
    at factor 64 is 8.6 GB against a 12 G cap. The budget must shrink as the factor grows."""
    source, target = tmp_path / "in.tif", tmp_path / "out.tif"
    array = np.arange(4096, dtype=np.float32).reshape(64, 64)
    _write_elevation(source, array)
    captured = []
    original = terrain_rgb.band_window
    monkey = lambda width, row0, row1: (captured.append(row1 - row0), original(width, row0, row1))[1]
    try:
        terrain_rgb.band_window = monkey  # pyright: ignore[reportAttributeAccessIssue]
        terrain_rgb.downsample_elevation(source, target, 16)
    finally:
        terrain_rgb.band_window = original  # pyright: ignore[reportAttributeAccessIssue]
    assert max(captured) <= terrain_rgb.SOURCE_ROW_BUDGET


def test_encode_raster_matches_the_array_encoder(tmp_path):
    """The windowed writer and the in-memory encoder must not drift — one is the other's oracle."""
    source, target = tmp_path / "in.tif", tmp_path / "rgb.tif"
    array = np.random.default_rng(3).uniform(-6000, 6000, (16, 16)).astype(np.float32)
    _write_elevation(source, array)
    terrain_rgb.encode_raster(source, target, 1.0, True, feather=False, band_rows=4)
    with rasterio.open(target) as ds:
        written = ds.read(window=band_window(ds.width, 0, ds.height))
    assert (written == terrain_rgb.encode_array(array, 1.0, True)).all()


# --- The guard the module exists for ------------------------------------------------


def test_cut_zoom_never_resamples_encoded_bytes(monkeypatch):
    """Cubic/average/bilinear interpolate ACROSS the green byte's 256 m wrap and invent cliffs.

    `shade_planet.TILE_CUT` uses cubic for both its cut and its overviews — correct for colour,
    catastrophic here — so the risk is a well-meaning port, not a typo. Every other test in this
    file passes with `--resampling=cubic`.
    """
    captured = []
    monkeypatch.setattr(terrain_rgb, "_run", lambda cmd: captured.append(cmd))
    terrain_rgb.cut_zoom(terrain_rgb.ROOT / "nowhere.tif", terrain_rgb.ROOT / "staging", 5)
    command = " ".join(str(part) for part in captured[0])
    assert "--resampling=nearest" in command
    assert "--overview-resampling=nearest" in command
    assert "--min-zoom=5" in command and "--max-zoom=5" in command


def test_webp_is_cut_losslessly_or_not_at_all(monkeypatch):
    """WebP is here to entropy-code identical pixels, nothing more.

    Elevation is not an image: drop LOSSLESS and every tile still decodes, to wrong metres, with no
    blur to notice. That makes a well-meaning `-co QUALITY=90` the exact analogue of the resampler
    trap above — which is why this asserts the creation option rather than trusting the driver's
    default, and why the check fails the same way for any lossy option name.
    """
    captured = []
    monkeypatch.setattr(terrain_rgb, "_run", lambda cmd: captured.append(cmd))
    terrain_rgb.cut_zoom(terrain_rgb.ROOT / "nowhere.tif", terrain_rgb.ROOT / "staging", 5, "webp")
    command = " ".join(str(part) for part in captured[0])
    assert "--format=WEBP" in command
    assert "--co LOSSLESS=YES" in command
    assert "QUALITY" not in command
    assert all("LOSSLESS=YES" in " ".join(str(part) for part in options)
               for _, options in [terrain_rgb.TILE_FORMATS["webp"]])


def test_build_threads_one_codec_through_every_zoom(monkeypatch, tmp_path):
    """A pyramid half PNG and half WebP would serve 404s for the zooms cut in the other format,
    and only at the zooms nobody looked at."""
    formats = []
    monkeypatch.setattr(terrain_rgb, "cut_zoom",
                        lambda src, staging, zoom, fmt="png": formats.append(fmt))
    monkeypatch.setattr(terrain_rgb, "encode_raster",
                        lambda level, dst, *a, **k: dst.touch())
    monkeypatch.setattr(terrain_rgb, "downsample_elevation",
                        lambda src, dst, factor, **k: dst.touch())
    terrain_rgb.build(tmp_path, 3, 8.0, False, True, tmp_path / "master.tif", tile_format="webp")
    assert formats == ["webp"] * 4


def test_each_zoom_is_cut_from_its_own_elevation(monkeypatch, tmp_path):
    """No zoom may be built from the tiles of another — that is the overview trap by a
    different route. Asserts one cut AND one encode per zoom, on that zoom's own grid."""
    cuts, encodes = [], []
    monkeypatch.setattr(terrain_rgb, "cut_zoom",
                        lambda src, staging, zoom, fmt="png": cuts.append((src.name, zoom)))
    monkeypatch.setattr(terrain_rgb, "encode_raster",
                        lambda level, dst, *a, **k: (encodes.append(level.name), dst.touch()))
    monkeypatch.setattr(terrain_rgb, "downsample_elevation",
                        lambda src, dst, factor, **k: dst.touch())
    terrain_rgb.build(tmp_path, 3, 1.0, True, True, tmp_path / "master.tif")
    assert [zoom for _, zoom in cuts] == [3, 2, 1, 0]
    assert encodes == [f"elev_z{zoom}.tif" for zoom in (3, 2, 1, 0)]
    assert [name for name, _ in cuts] == [f"rgb_sea0_s1_z{zoom}.tif" for zoom in (3, 2, 1, 0)]


def test_variants_sharing_a_work_dir_do_not_collide(monkeypatch, tmp_path):
    """The elevation chain is shared so the 46 GB master is read once — which is only safe if the
    ENCODED intermediates are named per variant. Identical names would let the second build cut
    the first one's bytes and call it a different sea treatment."""
    cuts = []
    monkeypatch.setattr(terrain_rgb, "cut_zoom",
                        lambda src, staging, zoom, fmt="png": cuts.append(src.name))
    monkeypatch.setattr(terrain_rgb, "encode_raster",
                        lambda level, dst, *a, **k: dst.touch())
    monkeypatch.setattr(terrain_rgb, "downsample_elevation",
                        lambda src, dst, factor, **k: dst.touch())
    work = tmp_path / "elev"
    for sea_clamp in (True, False):
        terrain_rgb.build(tmp_path / str(sea_clamp), 1, 1.0, sea_clamp, True,
                          tmp_path / "master.tif", work=work)
    assert len(set(cuts)) == len(cuts)
    assert sorted(path.name for path in work.glob("elev_*.tif")) == ["elev_z0.tif", "elev_z1.tif"]


def test_grid_matches_the_colour_pyramids_master():
    """height_3857.tif is 131072^2; if that stops being 512 x 2^8 the downsample factor is wrong."""
    assert terrain_rgb.grid_size(terrain_rgb.MASTER_ZOOM) == 131072


def test_module_does_not_reach_for_a_smooth_resampler():
    """Source guard: no smooth resampler name may appear in a command this module builds."""
    source = inspect.getsource(terrain_rgb.cut_zoom)
    for resampler in ("average", "cubic", "bilinear", "lanczos", "rms"):
        assert f"={resampler}" not in source


#: GDAL's single-binary entry point — `gdal raster tile`, what `cut_zoom` shells out to — landed
#: in **GDAL 3.11**. Ubuntu 24.04, which is what `ubuntu-latest` runs, ships gdal-bin **3.8.4**:
#: `gdalbuildvrt` and friends are there, `gdal` is not. So this probe cannot run on CI, and there
#: is nothing to gain by making it — the machines that cut tiles (this box, rohome) are on 3.12.x,
#: and a 3.8 answer about our command shape would be about a GDAL that will never see the command.
#: Contrast `tests/test_build_mosaics.py`, which drives the *old* CLI and therefore does run on CI;
#: `.github/workflows/ci.yml` records why that one must never be skipif'd.
HAS_UNIFIED_GDAL_CLI = shutil.which("gdal") is not None


@pytest.mark.skipif(not HAS_UNIFIED_GDAL_CLI,
                    reason="no `gdal` entry point — needs GDAL >= 3.11 (CI's noble ships 3.8.4)")
def test_gdal_accepts_the_cut_command():
    """The command shape is only a guess until GDAL parses it — a wrong flag would surface as an
    empty pyramid at the end of a long run, not as an error here."""
    help_text = subprocess.run(["gdal", "raster", "tile", "--help"],
                               capture_output=True, text=True, check=True).stdout
    for flag in ("--min-zoom", "--max-zoom", "--tile-size", "--resampling",
                 "--overview-resampling", "--convention", "--webviewer", "--co"):
        assert flag in help_text
    assert "nearest" in help_text
    # `--help` names no output driver beyond its default, so the registry is the surface to ask:
    # a GDAL built without WebP would otherwise fail four minutes into a cut, not here.
    registry = subprocess.run(["gdalinfo", "--formats"],
                              capture_output=True, text=True, check=True).stdout
    for driver, _ in terrain_rgb.TILE_FORMATS.values():
        entry = re.search(rf"^\s*{driver}\s+-raster-\s+\(([a-zA-Z+]*)\)", registry, re.MULTILINE)
        assert entry, f"GDAL has no {driver} driver"
        assert "w" in entry.group(1), f"GDAL cannot WRITE {driver} (capabilities {entry.group(1)})"


# --- Freshness: the guard stage T did not have --------------------------------------
#
# PROCESS called this out as the one stage with no output guard: `tiles/` was unconditionally
# rmtree'd and every zoom re-encoded, so a rerun paid ~4 min (41 min at z0-8) where every other
# stage skips in ~0 s. There was also no recipe, which is the half that could ship wrong bytes
# rather than merely waste time.


def _fake_pipeline(monkeypatch, cuts=None):
    """Stand in for the three expensive steps, so a build is pure bookkeeping.

    `cut_zoom` must actually CREATE a tile: an empty pyramid is one of the states
    `tiles_are_fresh` has to reject, so a mock that wrote nothing would let every freshness
    assertion below pass for the wrong reason.
    """
    def cut(src, staging, zoom, fmt="png"):
        staging.mkdir(parents=True, exist_ok=True)
        (staging / f"{zoom}.{fmt}").write_bytes(b"tile")
        if cuts is not None:
            cuts.append(zoom)

    monkeypatch.setattr(terrain_rgb, "cut_zoom", cut)
    monkeypatch.setattr(terrain_rgb, "encode_raster", lambda level, dst, *a, **k: dst.touch())
    monkeypatch.setattr(terrain_rgb, "downsample_elevation",
                        lambda src, dst, factor, **k: dst.touch())


def _stamped_master(tmp_path):
    """A master with its completion marker — freshness keys off the marker, never the raster."""
    master = tmp_path / "height_3857.tif"
    master.touch()
    terrain_rgb.mark_done(master)
    return master


SETTINGS = {"max_zoom": 2, "step": 8.0, "sea_clamp": False, "feather": True,
            "tile_format": "webp"}


def test_an_unchanged_rerun_skips_the_cut_entirely(monkeypatch, tmp_path):
    """The debt this closes, and the control for every restage test below: if this ever fails to
    skip, `test_a_recipe_change_restages` passes vacuously for all five of its cases."""
    cuts = []
    _fake_pipeline(monkeypatch, cuts)
    master = _stamped_master(tmp_path)
    terrain_rgb.build(tmp_path / "out", master=master, **SETTINGS)
    assert cuts == [2, 1, 0]
    cuts.clear()
    terrain_rgb.build(tmp_path / "out", master=master, **SETTINGS)
    assert cuts == [], "an unchanged rerun must not re-cut a single zoom"


@pytest.mark.parametrize("changed", [
    {"step": 4.0},
    {"tile_format": "png"},
    {"max_zoom": 1},
    {"sea_clamp": True},
    {"feather": False},
])
def test_a_recipe_change_restages(monkeypatch, tmp_path, changed):
    """The variant DIRECTORY name carries sea, step and feather — but NOT format and NOT max_zoom.
    Without a sidecar those two are invisible to every guard, so a pyramid re-cut at a new codec is
    indistinguishable by existence from the one it replaced. Its control is the skip test above.
    """
    cuts = []
    _fake_pipeline(monkeypatch, cuts)
    master = _stamped_master(tmp_path)
    out = tmp_path / "out"
    terrain_rgb.build(out, master=master, **SETTINGS)
    cuts.clear()
    terrain_rgb.build(out, master=master, **{**SETTINGS, **changed})
    assert cuts, f"changing {changed} must re-cut, and nothing but the recipe can see it"


def test_an_identical_recipe_does_not_move_its_mtime(tmp_path):
    """`write_if_changed` is what makes the skip possible at all. Rewriting identical JSON would
    stamp the recipe newer than tiles.done on every run and restage a pyramid that is correct."""
    path = terrain_rgb.terrain_params_path(tmp_path)
    recipe = terrain_rgb.terrain_params(**SETTINGS)
    terrain_rgb.write_if_changed(path, recipe)
    stamped = path.stat().st_mtime_ns
    terrain_rgb.write_if_changed(path, recipe)
    assert path.stat().st_mtime_ns == stamped


def test_the_recipe_records_what_the_directory_name_cannot():
    """`bathy_s8_webp` states the codec by convention and the depth by nothing at all — the z6
    build sits beside the z8 one under names differing by a suffix somebody chose by hand."""
    recipe = json.loads(terrain_rgb.terrain_params(8, 8.0, False, True, "webp"))
    assert recipe["max_zoom"] == 8
    assert recipe["format"] == "WEBP"
    assert recipe["creation_options"] == ["LOSSLESS=YES"]
    # Module constants have no other file to move an mtime, so they must ride here or be invisible.
    assert recipe["feather_lat_lo"] == terrain_rgb.FEATHER_LAT_LO
    assert recipe["feather_lat_hi"] == terrain_rgb.FEATHER_LAT_HI


def test_an_empty_pyramid_is_never_fresh(tmp_path):
    """A half-swapped directory: marker present, recipe matching, no tiles. Existence alone would
    serve 404s at every zoom while reporting the stage complete."""
    out = tmp_path / "out"
    (out / "tiles").mkdir(parents=True)
    terrain_rgb.write_if_changed(terrain_rgb.terrain_params_path(out),
                                 terrain_rgb.terrain_params(**SETTINGS))
    terrain_rgb.mark_done(out / "tiles")
    assert terrain_rgb.tiles_are_fresh(out, _stamped_master(tmp_path)) is False


def test_an_unstamped_master_is_never_fresh(monkeypatch, tmp_path):
    """"Cannot know" must read as stale, not as fresh: a master with no .done marker is one
    shade_planet did not finish writing. Asserted in BOTH directions so the check can fail."""
    _fake_pipeline(monkeypatch)
    master = _stamped_master(tmp_path)
    out = tmp_path / "out"
    terrain_rgb.build(out, master=master, **SETTINGS)
    assert terrain_rgb.tiles_are_fresh(out, master) is True
    terrain_rgb.done_marker(master).unlink()
    assert terrain_rgb.tiles_are_fresh(out, master) is False


def test_a_half_written_elevation_level_is_rebuilt_not_reused(monkeypatch, tmp_path):
    """THE crash this guard exists for. rasterio creates its target at write-start, so the BigTIFF
    failure of 2026-07-28 left a full-sized, freshly-stamped, truncated elev_z8.tif — which an
    exists() guard accepts. A truncated float32 raster reads as a very flat planet, not an error.
    """
    built = []
    _fake_pipeline(monkeypatch)
    monkeypatch.setattr(terrain_rgb, "downsample_elevation",
                        lambda src, dst, factor, **k: (built.append(dst.name), dst.touch()))
    master = _stamped_master(tmp_path)
    work = tmp_path / "work"
    terrain_rgb.build(tmp_path / "a", master=master, work=work, **SETTINGS)
    assert built == ["elev_z2.tif", "elev_z1.tif", "elev_z0.tif"]

    # The partial: the raster is on disk, but the stage never stamped it complete.
    built.clear()
    terrain_rgb.done_marker(work / "elev_z1.tif").unlink()
    terrain_rgb.build(tmp_path / "b", master=master, work=work, **SETTINGS)
    assert built == ["elev_z1.tif", "elev_z0.tif"], \
        "an unstamped level must be rebuilt, and everything derived from it must follow"


def test_the_master_is_read_in_place_at_its_native_zoom(tmp_path):
    """`--max-zoom 8` used to write a 47 GB byte-for-value copy of the 46 GB master, because a
    box-mean by a factor of 1 is the identity and NaN -> 0 (its only other effect) is applied
    again by encode_array regardless. Measured against the real rasters at exactly 0.0000 m over
    six windows from Everest to the Pacific abyss, shifted-window controls differing by 240-1660 m.
    """
    master = tmp_path / "height_3857.tif"
    work = tmp_path / "work"
    native = terrain_rgb.MASTER_ZOOM
    assert terrain_rgb.elevation_source(work, native, master) == master
    assert terrain_rgb.elevation_source(work, native - 1, master) == work / f"elev_z{native - 1}.tif"


def test_a_native_zoom_build_never_materialises_the_master(monkeypatch, tmp_path):
    """The build-level half of the test above: nothing may write the top level when it IS the
    master, and the descent must start from the master itself."""
    built = []
    _fake_pipeline(monkeypatch)
    monkeypatch.setattr(terrain_rgb, "downsample_elevation",
                        lambda src, dst, factor, **k: (built.append(dst.name), dst.touch()))
    master = _stamped_master(tmp_path)
    work = tmp_path / "work"
    native = terrain_rgb.MASTER_ZOOM
    terrain_rgb.build(tmp_path / "out", master=master, work=work,
                      **{**SETTINGS, "max_zoom": native})
    assert not (work / f"elev_z{native}.tif").exists()
    assert built[0] == f"elev_z{native - 1}.tif", "the descent must start from the master itself"


def test_a_failed_cut_leaves_the_live_pyramid_intact(monkeypatch, tmp_path):
    """The swap is the point: `tiles/` used to be rmtree'd BEFORE the cut, so a crash at zoom 3 of
    8 left the site serving nothing at all — from a pyramid that had been fine minutes earlier."""
    _fake_pipeline(monkeypatch)
    master = _stamped_master(tmp_path)
    out = tmp_path / "out"
    terrain_rgb.build(out, master=master, **SETTINGS)
    survivors = sorted(path.name for path in (out / "tiles").iterdir())

    def explode(src, staging, zoom, fmt="png"):
        staging.mkdir(parents=True, exist_ok=True)
        if zoom == 1:
            raise RuntimeError("gdal died mid-cut")
        (staging / f"{zoom}.{fmt}").write_bytes(b"tile")

    monkeypatch.setattr(terrain_rgb, "cut_zoom", explode)
    with pytest.raises(RuntimeError):
        terrain_rgb.build(out, master=master, **{**SETTINGS, "step": 4.0})
    assert sorted(path.name for path in (out / "tiles").iterdir()) == survivors


def test_the_previous_generation_is_kept_for_rollback(monkeypatch, tmp_path):
    """One generation back, same as the colour pyramid's `tiles_old`. Doubles as the concrete
    demonstration that a codec change really does restage."""
    _fake_pipeline(monkeypatch)
    master = _stamped_master(tmp_path)
    out = tmp_path / "out"
    terrain_rgb.build(out, master=master, **{**SETTINGS, "max_zoom": 1})
    terrain_rgb.build(out, master=master, **{**SETTINGS, "max_zoom": 1, "tile_format": "png"})
    assert sorted(path.name for path in (out / "tiles_old").iterdir()) == ["0.webp", "1.webp"]
    assert sorted(path.name for path in (out / "tiles").iterdir()) == ["0.png", "1.png"]
