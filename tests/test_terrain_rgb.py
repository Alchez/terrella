"""Terrain-RGB encode/decode, the polar feather, and the resampler that must never change.

The load-bearing test here is `test_cut_zoom_never_resamples_encoded_bytes`. Every other property
would survive someone "optimising" the cut to `average` or `cubic`; that one is the whole reason
the module exists, and nothing else in the suite would go red.
"""

import inspect
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


def test_each_zoom_is_cut_from_its_own_elevation(monkeypatch, tmp_path):
    """No zoom may be built from the tiles of another — that is the overview trap by a
    different route. Asserts one cut AND one encode per zoom, on that zoom's own grid."""
    cuts, encodes = [], []
    monkeypatch.setattr(terrain_rgb, "cut_zoom",
                        lambda src, staging, zoom: cuts.append((src.name, zoom)))
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
                        lambda src, staging, zoom: cuts.append(src.name))
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


def test_gdal_accepts_the_cut_command():
    """The command shape is only a guess until GDAL parses it — a wrong flag would surface as an
    empty pyramid at the end of a long run, not as an error here."""
    help_text = subprocess.run(["gdal", "raster", "tile", "--help"],
                               capture_output=True, text=True, check=True).stdout
    for flag in ("--min-zoom", "--max-zoom", "--tile-size", "--resampling",
                 "--overview-resampling", "--convention", "--webviewer"):
        assert flag in help_text
    assert "nearest" in help_text
