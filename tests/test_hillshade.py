"""Tests for the per-row-z hillshade — written to pin the float32 + window_rows change.

Context (measured on the instrumented planet pass): `per_row_zfactor_hillshade` ran
`window_rows=1024` in **float64** and peaked at **11.6 GB** of anon against a 12 G cap, driving
122,501 cgroup reclaims — to emit a **uint8** raster, so the float64 precision is thrown away on
the last line. `composite()` had the identical bug and was fixed (float32 @ 256
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


class TestPerPixelAzimuth:
    """`azimuth` may be a per-pixel array, not just a scalar. The polar cap shades on a pole-centred
    AEQD grid where grid-north diverges from true-north with longitude, so matching the tiles' fixed
    true-NW light needs the grid azimuth to rotate per pixel (315 - longitude). The scalar path the
    Mercator tiles use must stay untouched, which the constant-array equality below is what pins."""

    def test_constant_array_azimuth_equals_scalar(self):
        """An array filled with the scalar value must reproduce the scalar result bit-for-bit --
        this proves the array branch computes the same thing AND that adding it left the scalar
        branch byte-identical (output rows = heights.shape[0]-2, so the array is that shape)."""
        heights = synthetic_terrain(40, 60, seed=3).astype(np.float32)
        scalar = hillshade_array(heights, CELLSIZE, np.float32(15.0), ALT, AZ)
        array_az = np.full((38, 60), AZ, dtype=np.float32)
        arrayed = hillshade_array(heights, CELLSIZE, np.float32(15.0), ALT, array_az)
        assert np.array_equal(scalar, arrayed)

    def test_varying_azimuth_changes_the_shading(self):
        """Companion: a light bearing that varies across the grid must actually move pixels, or the
        array would be silently ignored and the equality above would pass vacuously."""
        heights = synthetic_terrain(40, 60, seed=3).astype(np.float32)
        reference = hillshade_array(heights, CELLSIZE, np.float32(15.0), ALT, AZ)
        sweep = np.linspace(AZ - 90.0, AZ + 90.0, 60, dtype=np.float32)
        varying = np.repeat(sweep[None, :], 38, axis=0)
        result = hillshade_array(heights, CELLSIZE, np.float32(15.0), ALT, varying)
        assert not np.array_equal(reference, result)

    def test_float64_azimuth_does_not_upcast_float32_heights(self):
        """The zfactor NEP-50 trap again: a longitude-derived azimuth is naturally float64, and
        float32 * float64 -> float64 would silently restore the whole float32 saving. The array
        branch casts azimuth to heights' dtype to prevent it."""
        heights = synthetic_terrain(40, 60, seed=3).astype(np.float32)
        azimuth = np.full((38, 60), AZ, dtype=np.float64)
        result = hillshade_array(heights, CELLSIZE, np.float32(15.0), ALT, azimuth)
        assert result.dtype == np.float32, "float64 azimuth array upcast the whole computation"


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

    def _shade_with_shadow(self, tmp_path, name, window_rows, reach_px=40, strength=1.0):
        src = tmp_path / "h.tif"
        if not src.exists():
            self._write_height(src)
        out = tmp_path / name
        per_row_zfactor_hillshade(src, out, 15.0, ALT, AZ, window_rows=window_rows,
                                  fill_strength=0.15, shadow_strength=strength,
                                  shadow_reach_px=reach_px)
        with rasterio.open(out) as dataset:
            return dataset.read(1)

    def test_window_invariance_holds_with_cast_shadows_on(self, tmp_path):
        """The halo-widening claim, and the only thing that makes the shadow safe to stream.

        A cast shadow is NON-LOCAL: with the 1-row halo it inherited, every window's top rows
        would be lit by terrain the window cannot see, seaming the raster at each boundary. The
        windows here are deliberately SMALLER than reach_px (40), so a wrong halo cannot pass.
        """
        assert np.array_equal(self._shade_with_shadow(tmp_path, "i.tif", 16),
                              self._shade_with_shadow(tmp_path, "j.tif", 4096))

    def test_ragged_final_window_with_shadows(self, tmp_path):
        """300 rows / 97 is ragged, and the last window is the one whose halo runs off the end."""
        assert np.array_equal(self._shade_with_shadow(tmp_path, "k.tif", 97),
                              self._shade_with_shadow(tmp_path, "l.tif", 4096))

    def test_shadow_strength_zero_is_bit_identical(self, tmp_path):
        """Can-fail companion: the production default must provably change no pixel."""
        src = tmp_path / "h.tif"
        self._write_height(src)
        off = tmp_path / "m.tif"
        per_row_zfactor_hillshade(src, off, 15.0, ALT, AZ, fill_strength=0.15)
        with rasterio.open(off) as dataset:
            baseline = dataset.read(1)
        assert np.array_equal(
            baseline, self._shade_with_shadow(tmp_path, "n.tif", 256, strength=0.0))
        # ...and that the same comparison DOES fail once the shadow is switched on, or the
        # assertion above would be satisfied by a shadow term that never ran at all.
        assert not np.array_equal(
            baseline, self._shade_with_shadow(tmp_path, "o.tif", 256, strength=1.0))

    def test_shadow_only_ever_darkens(self, tmp_path):
        """Structural, and the cheapest catch for a sign error in the attenuation."""
        baseline = self._shade(tmp_path, "p.tif", 256)
        with rasterio.open(tmp_path / "h.tif") as dataset:  # same fixture, fill on for both
            assert dataset.count == 1
        shadowed = self._shade_with_shadow(tmp_path, "q.tif", 256, reach_px=60)
        unshadowed = self._shade_with_shadow(tmp_path, "r.tif", 256, reach_px=60, strength=0.0)
        assert np.all(shadowed <= unshadowed)
        assert baseline.shape == shadowed.shape


class TestFullShadowLandsOnTheFillFloor:
    """Fully occluded ground must land on the FILL's contribution, never on black.

    This is the fill-port invariant, extended to the term that can actually drive a
    face to zero. The shadow attenuates the MAIN sun only — the fill stays shadowless, exactly as
    `scene_build`'s fill lamp does with `use_shadow` off — so the floor is analytic:

        (fill_strength * 255*sin(FILL_ALTITUDE)) * fill_scale(fill_strength, alt, FILL_ALTITUDE)

    Applied after `combine_fill` instead of before, this would read 0 and the test would fail.

    Deliberately built at the EQUATOR, unlike TestWindowInvariance's fixture: that one sits at the
    top of Mercator where zfactor = 15/cos(85.05) ~= 174, which exaggerates terrain so hard that
    both suns read zero on ordinary slopes. Flat ground is used here for the same reason — the
    floor must be measured somewhere the geometry cannot confound it.
    """

    ROWS, COLS, WALL_COLUMN, WALL_HEIGHT = 8, 400, 150, 3000.0
    FILL_STRENGTH = 0.15

    def _wall_raster(self, path):
        heights = np.zeros((self.ROWS, self.COLS), dtype=np.float32)
        heights[:, self.WALL_COLUMN] = self.WALL_HEIGHT
        transform = rasterio.transform.from_origin(0.0, 0.0, CELLSIZE, CELLSIZE)  # y=0 => equator
        with rasterio.open(path, "w", driver="GTiff", height=self.ROWS, width=self.COLS, count=1,
                           dtype="float32", crs="EPSG:3857", transform=transform) as dst:
            dst.write(heights, 1)

    def test_shadowed_flat_ground_reads_the_analytic_fill_floor(self, tmp_path):
        src = tmp_path / "wall.tif"
        self._wall_raster(src)
        out = tmp_path / "wall_shaded.tif"
        # Sun from due west: the shadow falls east of the wall along a single row, no diagonal.
        per_row_zfactor_hillshade(src, out, 15.0, ALT, 270.0, fill_strength=self.FILL_STRENGTH,
                                  shadow_strength=1.0, shadow_reach_px=300)
        with rasterio.open(out) as dataset:
            shaded = dataset.read(1)

        floor = ((self.FILL_STRENGTH * 255.0 * math.sin(math.radians(FILL_ALTITUDE)))
                 * fill_scale(self.FILL_STRENGTH, ALT, FILL_ALTITUDE))
        just_east = shaded[0, self.WALL_COLUMN + 2]
        assert just_east == round(floor)
        assert just_east > 0     # the whole point: occluded, not black

    def test_unshadowed_flat_ground_is_far_brighter(self, tmp_path):
        """Can-fail companion: without it, a term that zeroed EVERYTHING would pass the floor test
        only if the floor happened to be zero — and would pass trivially if nothing ran at all."""
        src = tmp_path / "wall.tif"
        self._wall_raster(src)
        out = tmp_path / "wall_lit.tif"
        per_row_zfactor_hillshade(src, out, 15.0, ALT, 270.0, fill_strength=self.FILL_STRENGTH)
        with rasterio.open(out) as dataset:
            lit = dataset.read(1)
        # Flat ground unshadowed holds the module's contract: 255*sin(alt).
        assert lit[0, self.WALL_COLUMN + 2] == round(255.0 * math.sin(math.radians(ALT)))


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
        """Measured on the real planet: a single 45-deg sun at EXAG 15 leaves 12.4% of
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
