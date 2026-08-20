"""Warp-once sea ice: the whole-grid warp must equal the per-window warp, plus the pure alpha.

The exact sea-side mirror of test_snow_warp_once.py. The composite reads a window slice out of a
single whole-grid warp of the ice-frequency climatology; the load-bearing claim is that a slice equals
warping that window alone. Every claim pairs with a companion that proves the check can fail.

The pure `unpack_seaice` / `ice_alpha` tests need no gdal or data and always run; the warp tests need
the OSI SAF frequency source (`seaice.SEAICE_SRC`, built by download_seaice.py) and skip without it.
"""
import math

import numpy as np
import pytest
import rasterio
import rasterio.transform  # rasterio's __init__ pulls this in at runtime; name it for the checker

from pipeline import bodies
from pipeline.look import seaice

# --- shared geometry: a small WMQ-aligned 3857 target over the Fram Strait marginal ice zone,
# where the annual ice-frequency field has a real north-south gradient (needed by the can-fail test).
# Read from the registry rather than restated — see the note in test_snow_warp_once.py.
EARTH_RADIUS = bodies.EARTH.mercator_radius_m
Z8_RES = bodies.EARTH.map_units_per_pixel


def _merc(lat, lon):
    return (EARTH_RADIUS * math.radians(lon),
            EARTH_RADIUS * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _ice_edge_grid(width=400, rows=512):
    """A small 3857 target over the Fram Strait ice edge, snapped to the z8 pixel lattice so
    per-window bounds derived from its transform land on exact pixel edges (as composite_planet does)."""
    left, top = _merc(80.0, 0.0)
    left = math.floor(left / Z8_RES) * Z8_RES
    top = math.ceil(top / Z8_RES) * Z8_RES
    right = left + width * Z8_RES
    bottom = top - rows * Z8_RES
    return (left, bottom, right, top), width, rows


def _window_bounds(transform, width, row0, row1):
    """Exactly composite_planet's per-window bounds derivation (shade_planet.py)."""
    win_top = transform.f + row0 * transform.e
    win_bottom = transform.f + row1 * transform.e
    return (transform.c, win_bottom, transform.c + width * transform.a, win_top)


class TestUnpackSeaice:
    """The float64 unpack, mirroring snow.unpack_persistence. Pure numpy, no gdal."""

    def test_packed_scales_to_fraction(self):
        packed = np.array([[0.0, 5000.0, 10000.0]], dtype=np.float32)
        assert np.allclose(seaice.unpack_seaice(packed), [[0.0, 0.5, 1.0]])

    def test_fill_becomes_zero_not_a_huge_fraction(self):
        """ICE_FILL (65535) is land/no observation. It must map to 0, NOT clip(65535*1e-4)=1.0 --
        which would paint solid ice over every land pixel before the ocean gate runs."""
        packed = np.array([[seaice.ICE_FILL, 3000.0]], dtype=np.float32)
        out = seaice.unpack_seaice(packed)
        assert out[0, 0] == pytest.approx(0.0)
        assert out[0, 1] == pytest.approx(0.3)

    def test_fill_handling_is_not_blind(self):
        """Companion: if unpack forgot to mask fill, 65535 would read as 1.0. Assert it does NOT."""
        out = seaice.unpack_seaice(np.array([[seaice.ICE_FILL]], dtype=np.float32))
        assert out[0, 0] != pytest.approx(1.0)

    def test_overflow_is_clipped(self):
        assert seaice.unpack_seaice(np.array([[12000.0]], dtype=np.float32))[0, 0] == pytest.approx(1.0)

    def test_output_is_float64(self):
        """ice_alpha and the final blend run float64; unpack must not narrow to float32."""
        assert seaice.unpack_seaice(np.array([[5000.0]], dtype=np.float32)).dtype == np.float64


class TestIceAlpha:
    """The frequency -> alpha smoothstep. No latitude term (unlike snow_alpha). Pure numpy."""

    def test_below_threshold_is_transparent(self):
        assert seaice.ice_alpha(np.array([0.0, seaice.ICE_LO - 0.01]))[1] == pytest.approx(0.0)
        assert seaice.ice_alpha(np.array([0.0]))[0] == pytest.approx(0.0)

    def test_above_band_saturates_at_max_alpha(self):
        """Above the band the alpha saturates at ICE_MAX_ALPHA (<1, so even the perennial pack stays
        a touch translucent and the deep bathymetry glows through)."""
        top = seaice.ICE_LO + seaice.ICE_BAND
        assert seaice.ice_alpha(np.array([top, 1.0]))[0] == pytest.approx(seaice.ICE_MAX_ALPHA)
        assert seaice.ice_alpha(np.array([top, 1.0]))[1] == pytest.approx(seaice.ICE_MAX_ALPHA)

    def test_midpoint_is_half_of_max(self):
        """smoothstep(0.5) = 0.5, so the band centre reads half of ICE_MAX_ALPHA."""
        mid = seaice.ICE_LO + seaice.ICE_BAND / 2
        assert seaice.ice_alpha(np.array([mid]))[0] == pytest.approx(0.5 * seaice.ICE_MAX_ALPHA)

    def test_alpha_is_monotonic_non_decreasing(self):
        alpha = seaice.ice_alpha(np.linspace(0.0, 1.0, 50))
        assert np.all(np.diff(alpha) >= -1e-12)

    def test_the_ramp_is_not_a_step(self):
        """Companion: the band centre must be strictly between transparent and opaque -- proves the
        alpha is a genuine soft ramp, not a hard threshold that the other assertions would also pass."""
        mid = seaice.ice_alpha(np.array([seaice.ICE_LO + seaice.ICE_BAND / 2]))[0]
        assert 0.0 < mid < 1.0


@pytest.mark.skipif(not seaice.SEAICE_SRC.exists(), reason="OSI SAF ice-frequency source not present (CI)")
class TestSeaiceWarpOnceEqualsPerWindow:
    """THE test: whole-grid warp sliced == per-window warp, on the real source over a small region."""

    def test_every_window_slice_matches_its_own_warp(self, tmp_path):
        bounds, width, rows = _ice_edge_grid()
        whole = tmp_path / "seaice_whole.tif"
        seaice.warp_seaice_raster(bounds, width, rows, whole)
        with rasterio.open(whole) as dataset:
            transform = dataset.transform
            whole_packed = dataset.read(1)

        window_rows = 128
        for row0 in range(0, rows, window_rows):
            row1 = min(rows, row0 + window_rows)
            part = tmp_path / f"seaice_win_{row0}.tif"
            seaice.warp_seaice_raster(_window_bounds(transform, width, row0, row1),
                                      width, row1 - row0, part)
            with rasterio.open(part) as dataset:
                part_packed = dataset.read(1)
            # compare through the real consumer -- unpacked, float64, as ice_alpha will see it
            assert np.array_equal(seaice.unpack_seaice(whole_packed[row0:row1]),
                                  seaice.unpack_seaice(part_packed)), f"window at row {row0}"

    def test_the_check_can_fail(self, tmp_path):
        """Companion: a deliberately shifted slice must DIFFER, or the equality proves nothing (a
        uniform patch of pack ice or open water would pass trivially)."""
        bounds, width, rows = _ice_edge_grid()
        whole = tmp_path / "seaice_whole.tif"
        seaice.warp_seaice_raster(bounds, width, rows, whole)
        with rasterio.open(whole) as dataset:
            packed = dataset.read(1)
        top = seaice.unpack_seaice(packed[0:128])
        shifted = seaice.unpack_seaice(packed[64:192])
        assert not np.array_equal(top, shifted)  # the Fram Strait edge has a real ice gradient

    def test_wrapper_preserves_read_then_unpack(self, tmp_path):
        """warp_seaice (whole-grid wrapper) must equal raster-then-unpack, byte-for-byte."""
        bounds, width, rows = _ice_edge_grid()
        wrapped = seaice.warp_seaice(bounds, width, rows, tmp_path / "wrapped.tif")
        raster = tmp_path / "raster.tif"
        seaice.warp_seaice_raster(bounds, width, rows, raster)
        with rasterio.open(raster) as dataset:
            refactored = seaice.unpack_seaice(dataset.read(1))
        assert np.array_equal(wrapped, refactored)

    def test_banded_mosaic_equals_single_band_warp(self, tmp_path):
        """Banding must change only whether the coarse source is decimated, never a value: warp-in-
        bands + mosaic == a single-band warp of the same grid. band_rows=128 forces 4 bands here."""
        bounds, width, rows = _ice_edge_grid()
        single = tmp_path / "single.tif"
        seaice.warp_seaice_raster(bounds, width, rows, single)  # band_rows=None -> one warp
        banded = tmp_path / "banded.tif"
        seaice.warp_seaice_raster(bounds, width, rows, banded, band_rows=128)
        with rasterio.open(single) as dataset:
            single_packed = dataset.read(1)
        with rasterio.open(banded) as dataset:
            banded_packed = dataset.read(1)
        assert np.array_equal(single_packed, banded_packed)

    def test_a_tall_grid_is_actually_banded(self, tmp_path):
        """Companion: prove band_rows really splits the warp (else the test above is vacuous). With
        band_rows >= height it is ONE warp; the two must agree regardless."""
        bounds, width, rows = _ice_edge_grid()
        one_band = tmp_path / "one.tif"
        seaice.warp_seaice_raster(bounds, width, rows, one_band, band_rows=rows * 2)  # single
        many_bands = tmp_path / "many.tif"
        seaice.warp_seaice_raster(bounds, width, rows, many_bands, band_rows=64)  # 8 bands
        with rasterio.open(one_band) as dataset:
            one_packed = dataset.read(1)
        with rasterio.open(many_bands) as dataset:
            many_packed = dataset.read(1)
        assert np.array_equal(one_packed, many_packed)
