"""Tests for the per-row-z hillshade — written to pin the float32 + window_rows change.

Context (measured 2026-07-16, instrumented planet pass): `per_row_zfactor_hillshade` ran
`window_rows=1024` in **float64** and peaked at **11.6 GB** of anon against a 12 G cap, driving
122,501 cgroup reclaims — to emit a **uint8** raster, so the float64 precision is thrown away on
the last line. `composite()` had the identical bug and was fixed on 2026-07-14 (float32 @ 256
rows, ~18 GB -> 6.93 GiB); the fix was never carried to its sibling. These tests are what make
carrying it safe.

Three things must hold, and each has a companion showing it can FAIL (HISTORY 2026-07-06: the
blind-oracle bug, a check whose filter deleted the very lines the bug was in):

  1. dtype does not silently upcast   -- the float32 saving is void if anything promotes back
  2. float32 == float64 to <=1 DN     -- the output is uint8; precision beyond that is waste
  3. window_rows does not change output -- the halo design's whole claim, and the thing the
                                          1024 -> 256 change would break if it were wrong
"""

import math

import numpy as np
import pytest
import rasterio
import rasterio.transform  # rasterio's __init__ pulls this in at runtime; name it for the checker

from pipeline.render.hillshade import (
    FILL_ALTITUDE,
    FILL_AZIMUTH,
    combine_fill,
    fill_scale,
    hillshade_array,
    per_row_zfactor_hillshade,
)

CELLSIZE = 305.7483  # the z8 planet grid
ALT, AZ = 46.0, 315.0


def synthetic_terrain(rows: int, cols: int, seed: int = 0) -> np.ndarray:
    """Mountain-scale relief: smooth ridges plus noise, in the real 0-8000 m range."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:rows, 0:cols]
    base = (2000.0 * np.sin(xx / 11.0) * np.cos(yy / 7.0)
            + 1500.0 * np.sin((xx + yy) / 23.0) + 3000.0)
    return (base + rng.normal(0, 60.0, size=(rows, cols))).clip(-500, 8848)


class TestDtypeDoesNotUpcast:
    """The whole point of the change. float32 in must mean float32 throughout."""

    def test_float32_heights_give_float32_output(self):
        heights = synthetic_terrain(18, 40).astype(np.float32)
        result = hillshade_array(heights, CELLSIZE, np.float32(15.0), ALT, AZ)
        assert result.dtype == np.float32

    def test_float64_zfactor_does_not_drag_float32_heights_up(self):
        """The trap: `zfactor` is built from np.cos(latitude) and is float64 by default.
        float32 array * float64 array -> float64 under NEP 50, which would silently restore
        every byte the change was meant to save while all the colour tests still passed."""
        heights = synthetic_terrain(18, 40).astype(np.float32)
        zfactor = np.full((16, 1), 15.0, dtype=np.float64)  # what the caller naturally builds
        result = hillshade_array(heights, CELLSIZE, zfactor, ALT, AZ)
        assert result.dtype == np.float32, "float64 zfactor upcast the whole computation"

    def test_float64_heights_still_give_float64(self):
        """The companion: the guard above must be detecting dtype, not asserting a constant."""
        heights = synthetic_terrain(18, 40).astype(np.float64)
        result = hillshade_array(heights, CELLSIZE, np.float64(15.0), ALT, AZ)
        assert result.dtype == np.float64


class TestFloat32MatchesFloat64:
    """Output is uint8. Anything finer than 1 DN is precision we pay for and then discard."""

    @pytest.mark.parametrize("zfactor", [15.0, 23.3])  # EXAG at the equator and at 50 deg
    def test_agreement_within_one_dn(self, zfactor):
        heights = synthetic_terrain(66, 200, seed=1)
        wide = hillshade_array(heights.astype(np.float64), CELLSIZE, np.float64(zfactor), ALT, AZ)
        narrow = hillshade_array(heights.astype(np.float32), CELLSIZE, np.float32(zfactor), ALT, AZ)
        delta = np.abs(np.rint(wide) - np.rint(narrow.astype(np.float64)))
        assert delta.max() <= 1.0, f"float32 drifts {delta.max()} DN from float64"

    def test_the_agreement_check_can_fail(self):
        """Companion: feed a deliberately wrong z-factor and the same assertion must break,
        proving it compares shading rather than rubber-stamping any two arrays."""
        heights = synthetic_terrain(66, 200, seed=1)
        reference = hillshade_array(heights, CELLSIZE, np.float64(15.0), ALT, AZ)
        wrong = hillshade_array(heights, CELLSIZE, np.float64(30.0), ALT, AZ)
        assert np.abs(np.rint(reference) - np.rint(wrong)).max() > 1.0


class TestWindowInvariance:
    """The module's core claim: full-width windows + a 1-row halo == a single in-RAM pass.
    Changing window_rows 1024 -> 256 is only safe because of this, so pin it on real I/O."""

    def _write_height(self, path, rows=300, cols=64):
        heights = synthetic_terrain(rows, cols, seed=2).astype(np.float32)
        transform = rasterio.transform.from_origin(-20037508.34, 20037508.34, CELLSIZE, CELLSIZE)
        with rasterio.open(path, "w", driver="GTiff", height=rows, width=cols, count=1,
                           dtype="float32", crs="EPSG:3857", transform=transform) as dst:
            dst.write(heights, 1)

    def _shade(self, tmp_path, name, window_rows):
        src = tmp_path / "h.tif"
        if not src.exists():
            self._write_height(src)
        out = tmp_path / name
        per_row_zfactor_hillshade(src, out, 15.0, ALT, AZ, window_rows=window_rows)
        with rasterio.open(out) as dataset:
            return dataset.read(1)

    def test_256_matches_1024(self, tmp_path):
        """The change under test: the new window size must be a no-op on the pixels."""
        assert np.array_equal(self._shade(tmp_path, "a.tif", 256),
                              self._shade(tmp_path, "b.tif", 1024))

    def test_odd_window_also_matches(self, tmp_path):
        """A size that does not divide the raster evenly exercises the ragged final window."""
        assert np.array_equal(self._shade(tmp_path, "c.tif", 97),
                              self._shade(tmp_path, "d.tif", 1024))

    def test_single_window_matches_streamed(self, tmp_path):
        """vs a window larger than the raster = one in-RAM pass, the docstring's claim."""
        assert np.array_equal(self._shade(tmp_path, "e.tif", 256),
                              self._shade(tmp_path, "f.tif", 4096))

    def test_window_invariance_still_holds_with_the_fill_on(self, tmp_path):
        """The fill adds a SECOND hillshade over the same haloed block. If it were ever computed
        from a different neighbourhood the halo guarantee would break silently -- and only at
        window edges, which is precisely where nobody looks."""
        src = tmp_path / "h.tif"
        self._write_height(src)
        outs = []
        for name, window_rows in (("g.tif", 256), ("h_out.tif", 97)):
            out = tmp_path / name
            per_row_zfactor_hillshade(src, out, 15.0, ALT, AZ, window_rows=window_rows,
                                      fill_strength=0.15)
            with rasterio.open(out) as dataset:
                outs.append(dataset.read(1))
        assert np.array_equal(outs[0], outs[1])


class TestFillSunPreservesTheFlatGroundContract:
    """`shade.composite` divides by `flat = 255*sin(alt)` and was NOT changed by the fill port.

    That claim rests entirely on flat ground still reading exactly 255*sin(alt) once the fill is
    mixed in -- if it drifts, `ambient`/`hi`/`exposure` quietly stop meaning what they say, because
    1.0 would no longer be "flat ground". This is the pin for the whole design.
    """

    @pytest.mark.parametrize("strength", [0.0, 0.10, 0.15, 0.20, 0.25])
    def test_flat_ground_is_unmoved_by_any_fill_strength(self, strength):
        flat = np.zeros((18, 40), dtype=np.float32)
        main = hillshade_array(flat, CELLSIZE, np.float32(15.0), ALT, AZ)
        fill = hillshade_array(flat, CELLSIZE, np.float32(15.0), FILL_ALTITUDE, FILL_AZIMUTH)
        combined = combine_fill(main, fill, strength, ALT)
        assert np.allclose(combined, 255.0 * math.sin(math.radians(ALT)), atol=1e-3)

    def test_the_contract_check_can_fail(self):
        """Companion: drop the rescale and flat ground moves. Proves the test measures the
        normalisation rather than observing that a constant array is constant."""
        flat = np.zeros((18, 40), dtype=np.float32)
        main = hillshade_array(flat, CELLSIZE, np.float32(15.0), ALT, AZ)
        fill = hillshade_array(flat, CELLSIZE, np.float32(15.0), FILL_ALTITUDE, FILL_AZIMUTH)
        naive = main + 0.15 * fill  # the blend without fill_scale
        assert not np.allclose(naive, 255.0 * math.sin(math.radians(ALT)), atol=1e-3)

    def test_fill_scale_is_exactly_one_at_zero(self):
        """Not approximately 1.0. `strength=0` is the bit-identical control the port rests on;
        a 0.9999999 factor would drift every pixel and make that control vacuous."""
        assert fill_scale(0.0, ALT) == 1.0


class TestFillStrengthZeroChangesNothing:
    """Landing the mechanism must not re-tune today's look. This is the control that says so."""

    def _write_height(self, path, rows=300, cols=64):
        heights = synthetic_terrain(rows, cols, seed=5).astype(np.float32)
        transform = rasterio.transform.from_origin(-20037508.34, 20037508.34, CELLSIZE, CELLSIZE)
        with rasterio.open(path, "w", driver="GTiff", height=rows, width=cols, count=1,
                           dtype="float32", crs="EPSG:3857", transform=transform) as dst:
            dst.write(heights, 1)

    def _shade(self, tmp_path, name, fill_strength):
        src = tmp_path / "h.tif"
        if not src.exists():
            self._write_height(src)
        out = tmp_path / name
        per_row_zfactor_hillshade(src, out, 15.0, ALT, AZ, fill_strength=fill_strength)
        with rasterio.open(out) as dataset:
            return dataset.read(1)

    def test_zero_fill_is_bit_identical_to_a_no_fill_pass(self, tmp_path):
        assert np.array_equal(self._shade(tmp_path, "a.tif", 0.0),
                              self._shade(tmp_path, "b.tif", 0.0))

    def test_a_real_fill_strength_does_change_pixels(self, tmp_path):
        """Companion: without this, the identity above would also pass if `fill_strength` were
        silently ignored -- which is the likeliest way this port fails."""
        assert not np.array_equal(self._shade(tmp_path, "c.tif", 0.0),
                                  self._shade(tmp_path, "d.tif", 0.15))


class TestFillSunDoesItsJob:
    """The behavioural claim the port exists for, and the uint8 bound the design rests on."""

    def test_fill_eliminates_pure_black(self):
        """Measured on the real planet 2026-07-17: a single 45-deg sun at EXAG 15 leaves 12.4% of
        Sri Lanka, 30.5% of the Himalaya and 43.7% of the Alps at hillshade 0 -- flat black slabs.
        Any fill >= 0.10 drove that to 0.00% on every site. Pin the mechanism on synthetic relief."""
        heights = synthetic_terrain(120, 200, seed=6)
        main = hillshade_array(heights, CELLSIZE, np.float64(15.0), ALT, AZ)
        fill = hillshade_array(heights, CELLSIZE, np.float64(15.0), FILL_ALTITUDE, FILL_AZIMUTH)
        assert (main == 0).mean() > 0.01, "synthetic terrain is too gentle to exercise the claim"
        assert (combine_fill(main, fill, 0.15, ALT) == 0).sum() == 0

    @pytest.mark.parametrize("strength", [0.10, 0.15, 0.20, 0.25, 1.0])
    def test_production_geometry_never_reaches_the_clip(self, strength):
        """The one way baking the fill into the existing single band could be wrong: exceed 255 and
        the writer's astype(uint8) WRAPS, silently. Safe here by proof, not by luck -- the bound
        255*(1+s)*sin(alt)/(sin(alt)+s*sin(fill_alt)) is <= 255 exactly when alt <= fill_alt, and
        45 < 60. Asserted pre-clip, so the clip cannot mask a failure."""
        heights = synthetic_terrain(120, 200, seed=7)
        main = hillshade_array(heights, CELLSIZE, np.float64(15.0), ALT, AZ)
        fill = hillshade_array(heights, CELLSIZE, np.float64(15.0), FILL_ALTITUDE, FILL_AZIMUTH)
        raw = (main + strength * fill) * fill_scale(strength, ALT)
        assert raw.max() < 255.0

    def test_the_clip_backstop_engages_for_a_fill_below_the_sun(self):
        """Companion, and the reason the clip stays. Move the fill BELOW the main sun and the proof
        above inverts: the blend can exceed 255, and combine_fill must clamp rather than wrap.

        Strength 2.0, not 1.0: the alt <= fill_alt bound assumes both suns hit 255 on the SAME
        pixel, which opposed azimuths make impossible, so it is a strict upper bound and never
        attained. At fill_alt 20 / s 1.0 the blend only reaches ~187 and this test was vacuous --
        caught by the first assertion, which is what it is here for.
        """
        heights = synthetic_terrain(120, 200, seed=7)
        main = hillshade_array(heights, CELLSIZE, np.float64(15.0), ALT, AZ)
        low = hillshade_array(heights, CELLSIZE, np.float64(15.0), 20.0, FILL_AZIMUTH)
        raw = (main + 2.0 * low) * fill_scale(2.0, ALT, 20.0)
        assert raw.max() > 255.0, "the check below would be vacuous without a real overflow"
        assert combine_fill(main, low, 2.0, ALT, fill_altitude=20.0).max() == 255.0
