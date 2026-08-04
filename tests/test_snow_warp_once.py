"""Warp-once snow (optimisation #4): the whole-grid warp must equal the per-window warp.

The composite loop today forks `gdalwarp`/`gdal_rasterize` per window into fixed-path temps
(`_sp_win.tif`/`_rgi_win.tif`) -- shared paths that block threading (#5). #4 warps snow persistence
and glaciers ONCE to the planet grid, exactly as `warp_inputs` already does for lakedepth, then the
loop reads a slice per window.

The load-bearing claim is byte-identity: reading a window slice out of the whole-grid warp must equal
warping that window alone. It should be -- the source is global and the target sub-grid is an aligned
row-block, so bilinear samples the same source pixels -- but that is a gdalwarp property to VERIFY,
not assume. Every claim here pairs with a companion that proves the check can fail.

The persistence raster stores the RAW PACKED gdalwarp output (Float32), not the unpacked 0..1: today's
per-window path unpacks and runs snow_alpha in float64, and storing unpacked-as-float32 would silently
change that precision. `unpack_persistence` is the float64 unpack, kept per-window.
"""
import math

import numpy as np
import pytest
import rasterio
import rasterio.transform  # rasterio's __init__ pulls this in at runtime; name it for the checker

from pipeline import bodies
from pipeline.render import snow

# --- shared geometry: a small WMQ-aligned 3857 target over a snowy region (the Alps) ---
# READ FROM THE REGISTRY, not restated. Both of these were local literals with a comment claiming
# they matched the pipeline's, which is the copied-constant pattern the registry exists to end —
# and a comment is not a check.
EARTH_RADIUS = bodies.EARTH.mercator_radius_m
Z8_RES = bodies.EARTH.map_units_per_pixel


def _merc(lat, lon):
    return (EARTH_RADIUS * math.radians(lon),
            EARTH_RADIUS * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _alps_grid(width=400, rows=384):
    """A small 3857 target grid over the Alps, snapped to the z8 pixel lattice so per-window
    bounds derived from its transform land on exact pixel edges (as composite_planet does)."""
    left, top = _merc(48.0, 6.0)
    # snap the origin to the Z8_RES lattice so the grid is WMQ-consistent
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


class TestUnpackPersistence:
    """The float64 unpack, split out of warp_persistence and kept per-window. Pure numpy, no gdal."""

    def test_packed_scales_to_fraction(self):
        packed = np.array([[0.0, 5000.0, 10000.0]], dtype=np.float32)
        assert np.allclose(snow.unpack_persistence(packed), [[0.0, 0.5, 1.0]])

    def test_fill_becomes_zero_not_a_huge_fraction(self):
        """SP_FILL (65535) is ocean/no-MODIS. It must map to 0, NOT clip(65535*1e-4)=1.0 --
        that is the exact bug -srcnodata + the valid-mask exist to prevent."""
        packed = np.array([[snow.SP_FILL, 3000.0]], dtype=np.float32)
        out = snow.unpack_persistence(packed)
        assert out[0, 0] == pytest.approx(0.0)
        assert out[0, 1] == pytest.approx(0.3)

    def test_fill_handling_is_not_blind(self):
        """Companion: if unpack forgot to mask fill, 65535 would read as 1.0 (full snow over
        ocean). Assert it does NOT."""
        out = snow.unpack_persistence(np.array([[snow.SP_FILL]], dtype=np.float32))
        assert out[0, 0] != pytest.approx(1.0)

    def test_overflow_is_clipped(self):
        assert snow.unpack_persistence(np.array([[12000.0]], dtype=np.float32))[0, 0] == pytest.approx(1.0)

    def test_output_is_float64(self):
        """snow_alpha runs float64 today; unpack must not narrow to float32 or the composite's
        final blend shifts sub-DN and the byte-identity gate can fail."""
        assert snow.unpack_persistence(np.array([[5000.0]], dtype=np.float32)).dtype == np.float64


@pytest.mark.skipif(not snow.SP_NC.exists(), reason="NSIDC persistence .nc not present (CI)")
class TestPersistenceWarpOnceEqualsPerWindow:
    """THE test: whole-grid warp sliced == per-window warp, on the real source over a small region."""

    def test_every_window_slice_matches_its_own_warp(self, tmp_path):
        bounds, width, rows = _alps_grid()
        whole = tmp_path / "persistence_whole.tif"
        snow.warp_persistence_raster(bounds, width, rows, whole)
        with rasterio.open(whole) as dataset:
            transform = dataset.transform
            whole_packed = dataset.read(1)

        window_rows = 128
        for row0 in range(0, rows, window_rows):
            row1 = min(rows, row0 + window_rows)
            part = tmp_path / f"persistence_win_{row0}.tif"
            snow.warp_persistence_raster(_window_bounds(transform, width, row0, row1),
                                         width, row1 - row0, part)
            with rasterio.open(part) as dataset:
                part_packed = dataset.read(1)
            # compare through the real consumer -- unpacked, float64, as snow_alpha will see it
            assert np.array_equal(snow.unpack_persistence(whole_packed[row0:row1]),
                                  snow.unpack_persistence(part_packed)), f"window at row {row0}"

    def test_the_check_can_fail(self, tmp_path):
        """Companion: a deliberately shifted slice must DIFFER, or the equality above proves
        nothing (a uniform-snow region would pass trivially)."""
        bounds, width, rows = _alps_grid()
        whole = tmp_path / "persistence_whole.tif"
        snow.warp_persistence_raster(bounds, width, rows, whole)
        with rasterio.open(whole) as dataset:
            packed = dataset.read(1)
        top = snow.unpack_persistence(packed[0:128])
        shifted = snow.unpack_persistence(packed[64:192])
        assert not np.array_equal(top, shifted)  # the Alps have real spatial variation

    def test_wrapper_preserves_region_path_behaviour(self, tmp_path):
        """warp_persistence (region path) must still equal raster-then-unpack, byte-for-byte."""
        bounds, width, rows = _alps_grid()
        legacy = snow.warp_persistence(bounds, width, rows, tmp_path / "legacy.tif")
        raster = tmp_path / "raster.tif"
        snow.warp_persistence_raster(bounds, width, rows, raster)
        with rasterio.open(raster) as dataset:
            refactored = snow.unpack_persistence(dataset.read(1))
        assert np.array_equal(legacy, refactored)

    def test_banded_mosaic_equals_single_band_warp(self, tmp_path):
        """A's core: warp-in-bands + mosaic must equal a single-band warp of the same grid, so the
        only thing banding changes is dodging the whole-grid decimation of the coarse source -- never
        a value. band_rows=128 forces 3 bands over the 384-row grid; the whole-grid decimation itself
        is planet-scale (coarse source + global Mercator), so it is guarded by the full-pass gate, not
        reproducible here."""
        bounds, width, rows = _alps_grid()
        single = tmp_path / "single.tif"
        snow.warp_persistence_raster(bounds, width, rows, single)  # band_rows=None -> one warp
        banded = tmp_path / "banded.tif"
        snow.warp_persistence_raster(bounds, width, rows, banded, band_rows=128)  # 3 bands
        with rasterio.open(single) as dataset:
            single_packed = dataset.read(1)
        with rasterio.open(banded) as dataset:
            banded_packed = dataset.read(1)
        assert np.array_equal(single_packed, banded_packed)

    def test_a_tall_grid_is_actually_banded(self, tmp_path):
        """Companion: prove band_rows really splits the warp (else the test above is vacuous). With
        band_rows >= height it must be ONE warp (region path); the two must agree regardless."""
        bounds, width, rows = _alps_grid()
        one_band = tmp_path / "one.tif"
        snow.warp_persistence_raster(bounds, width, rows, one_band, band_rows=rows * 2)  # single
        many_bands = tmp_path / "many.tif"
        snow.warp_persistence_raster(bounds, width, rows, many_bands, band_rows=64)  # 6 bands
        with rasterio.open(one_band) as dataset:
            one_packed = dataset.read(1)
        with rasterio.open(many_bands) as dataset:
            many_packed = dataset.read(1)
        assert np.array_equal(one_packed, many_packed)


@pytest.mark.skipif(not snow.RGI_GPKG.exists(), reason="RGI glacier .gpkg not present (CI)")
class TestGlacierWarpOnceEqualsPerWindow:
    def test_every_window_slice_matches_its_own_rasterize(self, tmp_path):
        bounds, width, rows = _alps_grid()  # the Alps carry RGI glaciers
        whole = tmp_path / "glacier_whole.tif"
        assert snow.rasterize_glaciers_raster(bounds, width, rows, whole) is not None
        with rasterio.open(whole) as dataset:
            transform = dataset.transform
            whole_mask = dataset.read(1)

        window_rows = 128
        for row0 in range(0, rows, window_rows):
            row1 = min(rows, row0 + window_rows)
            part = tmp_path / f"glacier_win_{row0}.tif"
            snow.rasterize_glaciers_raster(_window_bounds(transform, width, row0, row1),
                                           width, row1 - row0, part)
            with rasterio.open(part) as dataset:
                part_mask = dataset.read(1)
            assert np.array_equal(whole_mask[row0:row1], part_mask), f"window at row {row0}"

    def test_absent_rgi_returns_none(self, tmp_path):
        """The persistence-only fallback: a missing .gpkg must not raise."""
        bounds, width, rows = _alps_grid()
        assert snow.rasterize_glaciers_raster(
            bounds, width, rows, tmp_path / "g.tif", rgi=tmp_path / "nonexistent.gpkg") is None
