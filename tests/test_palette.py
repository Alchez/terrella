"""Tests for the shared hypsometric palette — the single source of truth for the
land/sea color ramps used by both the Cycles heroes and the raster tile shading.

The load-bearing test is `test_color_relief_matches_locked_hero_hex`: an independent
oracle (the frozen hex values recorded in PLAN.md § "Locked global constants") that
fails loudly if the linear ramp stops ever drift off the approved hero look.
"""

from pathlib import Path

import pytest

from pipeline.render import palette

REPO_ROOT = Path(__file__).resolve().parents[1]


def _hex(code: str) -> tuple[int, int, int]:
    return (int(code[0:2], 16), int(code[2:4], 16), int(code[4:6], 16))


# The frozen hero ramp endpoints (PLAN.md § Locked global constants → Color).
LAND_COAST = _hex("E9D9C0")   # land ramp @ 0 m
LAND_PEAK = _hex("E9DCC8")    # land ramp @ 6000 m
SEA_SHALLOW = _hex("85B9B7")  # sea ramp @ 0 m (shallowest; deepened ~15% from 8FC7C5)
SEA_DEEP = _hex("3A6E7D")     # sea ramp @ -6000 m (deepest; depth extended from -3000)


class TestScalarHelpers:
    def test_smoothstep_endpoints_and_midpoint(self):
        assert palette.smoothstep(0.0) == 0.0
        assert palette.smoothstep(1.0) == 1.0
        assert palette.smoothstep(0.5) == pytest.approx(0.5)

    def test_smoothstep_is_monotonic(self):
        samples = [palette.smoothstep(i / 10) for i in range(11)]
        assert samples == sorted(samples)

    def test_lin2srgb_endpoints(self):
        assert palette.lin2srgb(0.0) == pytest.approx(0.0)
        assert palette.lin2srgb(1.0) == pytest.approx(1.0)

    def test_lin2srgb_known_midpoint(self):
        # linear 0.5 encodes to ~0.735 in sRGB
        assert palette.lin2srgb(0.5) == pytest.approx(0.7353569, abs=1e-6)

    def test_lin2srgb_clamps(self):
        assert palette.lin2srgb(-0.2) == pytest.approx(0.0)
        assert palette.lin2srgb(1.5) == pytest.approx(1.0)


class TestRampColor:
    @pytest.mark.parametrize("stops_name", ["LAND_STOPS", "SEA_STOPS"])
    def test_returns_exact_color_at_each_stop(self, stops_name):
        stops = getattr(palette, stops_name)
        for pos, color in stops:
            assert palette.ramp_color(pos, stops) == pytest.approx(color)

    def test_interpolates_between_stops(self):
        # halfway (in position) between two land stops must lie strictly between them
        (p0, c0), (p1, c1) = palette.LAND_STOPS[0], palette.LAND_STOPS[1]
        mid = palette.ramp_color((p0 + p1) / 2, palette.LAND_STOPS)
        for channel in range(3):
            lo, hi = sorted((c0[channel], c1[channel]))
            assert lo <= mid[channel] <= hi

    def test_clamps_below_and_above_range(self):
        assert palette.ramp_color(-1.0, palette.SEA_STOPS) == pytest.approx(palette.SEA_STOPS[0][1])
        assert palette.ramp_color(2.0, palette.SEA_STOPS) == pytest.approx(palette.SEA_STOPS[-1][1])


class TestColorRelief:
    def test_land_rows_span_zero_to_max(self):
        rows = palette.color_relief_rows("land")
        assert rows[0][0] == 0.0
        assert rows[-1][0] == pytest.approx(palette.LAND_MAX_M)

    def test_sea_rows_span_min_to_zero(self):
        rows = palette.color_relief_rows("sea")
        assert rows[0][0] == pytest.approx(palette.SEA_MIN_M)
        assert rows[-1][0] == 0.0

    def test_elevations_are_monotonic(self):
        for kind in ("land", "sea"):
            elevs = [elev for elev, _ in palette.color_relief_rows(kind)]
            assert elevs == sorted(elevs)

    def test_color_relief_matches_locked_hero_hex(self):
        """Independent oracle: generated endpoints == the frozen PLAN.md hex."""
        land = palette.color_relief_rows("land")
        sea = palette.color_relief_rows("sea")
        assert land[0][1] == LAND_COAST
        assert land[-1][1] == LAND_PEAK
        assert sea[-1][1] == SEA_SHALLOW   # shallowest is at elevation 0 (last sea row)
        assert sea[0][1] == SEA_DEEP       # deepest is at -6000 (first sea row)


class TestSharedConstants:
    """The relational pins that stop the copy-drift class of bug (the sea-sync).

    WATER_RGB went stale against SEA_STOPS[0] once on the tiles and once
    on the heroes (98C5C8) because nothing tied the tint to the sea
    surface. These freeze the value AND the relationship."""

    def test_water_rgb_exact(self):
        assert palette.WATER_RGB == (142, 198, 196)  # 8EC6C4

    def test_water_rgb_is_sea_surface_lightened(self):
        """The lake convention: the sea surface tone lightened ~7%. A ramp rework that
        moves SEA_STOPS[0] and forgets the flat tint fails here, not on a render."""
        surface = palette._srgb8(palette.SEA_STOPS[0][1])
        assert surface == SEA_SHALLOW  # the frozen 85B9B7 anchor
        for tint_channel, surface_channel in zip(palette.WATER_RGB, surface):
            assert abs(tint_channel - round(surface_channel * 1.07)) <= 1

    def test_lake_shore_is_the_flat_tint(self):
        assert palette.LAKE_STOPS[0][1] == palette.srgb8_to_linear(palette.WATER_RGB)

    def test_sun_altitude_is_shared(self):
        """Tile KNOBS["alt"] sources palette.SUN_ALT_DEG; the hero derives its
        SUN_ROTATION X-tilt from the same constant (test_scene_build_sync)."""
        from pipeline.tile import shade

        assert palette.SUN_ALT_DEG == 45.0
        assert shade.KNOBS["alt"] == palette.SUN_ALT_DEG

    def test_exaggeration_is_shared(self):
        """render_prep's displacement_scale and shade_planet's EXAG both source
        palette.EXAGGERATION — the last copy-pair, collapsed to one constant."""
        from pipeline.render import render_prep
        from pipeline.tile import shade_planet

        assert palette.EXAGGERATION == 15.0
        assert render_prep.EXAGGERATION == palette.EXAGGERATION
        assert shade_planet.EXAG == palette.EXAGGERATION

    def test_web_palette_matches_the_ramp_it_copies(self):
        """web/src/lib/palette.ts restates pipeline colours for the browser, which cannot
        import Python. This recomputes each one through _srgb8 and fails on drift — the
        same class of bug WATER_RGB hit twice, in the one place an import cannot reach.

        Adding a colour to that file means adding its stop here in the same edit."""
        web_palette = (REPO_ROOT / "web/src/lib/palette.ts").read_text()

        # name in the TS file -> the ramp stop it encodes
        derived = {
            "DEEP_SEA": palette.SEA_STOPS[4][1],  # -3800 m abyssal plain
        }
        for name, linear in derived.items():
            red, green, blue = palette._srgb8(linear)
            expected = f'export const {name} = "#{red:02X}{green:02X}{blue:02X}";'
            assert expected in web_palette, (
                f"web/src/lib/palette.ts must declare {name} as "
                f"#{red:02X}{green:02X}{blue:02X} — the palette moved, the copy did not"
            )


class TestWriteColorRelief:
    def test_writes_gdaldem_format_with_nodata(self, tmp_path):
        out = tmp_path / "ramp_land.txt"
        palette.write_color_relief(out, "land")
        lines = out.read_text().splitlines()
        assert lines[-1] == "nv 0 0 0"
        first = lines[0].split()
        assert len(first) == 4                       # elevation R G B
        assert first[0] == "0.00"
        assert all(0 <= int(v) <= 255 for v in first[1:])
