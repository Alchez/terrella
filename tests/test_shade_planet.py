"""Tests for the freshness guard that decides which planet-shading stages re-run.

The load-bearing case is `test_refused_cell_makes_the_warp_stale`: it reproduces the
2026-07-15 Caspian miss, where re-fusing 4 of 540 chunks left every derived raster
silently stale because the old guard only asked whether the output existed.
"""

import os
import time

import pytest

from pipeline.render import palette
from pipeline.tile import shade_planet


def _age(path, seconds):
    """Backdate a file's mtime by `seconds` (mtimes are the guard's whole input)."""
    stamp = os.stat(path).st_mtime - seconds
    os.utime(path, (stamp, stamp))


def _at(path, seconds_ago):
    """Set a file's mtime to exactly `seconds_ago` before now, and its .done marker with it.

    Absolute, unlike `_age`: stacking relative backdates silently inverts an intended
    ordering, which is how the rerun-economics fixture first mis-fired.
    """
    stamp = time.time() - seconds_ago
    os.utime(path, (stamp, stamp))
    marker = shade_planet.done_marker(path)
    if marker.exists():
        os.utime(marker, (stamp, stamp))


def _built(tmp_path, name="height_3857.tif"):
    """An output that completed 100 s ago: the raster plus its .done marker."""
    out = tmp_path / name
    out.write_text("raster")
    shade_planet.mark_done(out)
    _age(out, 100)
    _age(shade_planet.done_marker(out), 100)
    return out


class TestIsStale:
    def test_missing_output_is_stale(self, tmp_path):
        assert shade_planet.is_stale(tmp_path / "nope.tif") is True

    def test_completed_output_with_older_inputs_is_fresh(self, tmp_path):
        out = _built(tmp_path)
        source = tmp_path / "chunk.tif"
        source.write_text("x")
        _age(source, 500)
        assert shade_planet.is_stale(out, source) is False

    def test_refused_cell_makes_the_warp_stale(self, tmp_path):
        """The Caspian case: an input rewritten after the output completed."""
        out = _built(tmp_path)
        source = tmp_path / "chunk.tif"
        source.write_text("re-fused")  # written now, i.e. after the output's marker
        assert shade_planet.is_stale(out, source) is True

    def test_crashed_run_leaves_no_marker_and_stays_stale(self, tmp_path):
        """GDAL stamps its target at the START, so a half-written raster looks current.
        Only the .done marker distinguishes 'finished' from 'died mid-write'."""
        out = tmp_path / "height_3857.tif"
        out.write_text("half-written")
        assert shade_planet.is_stale(out) is True

    def test_directory_input_sees_a_rewritten_child(self, tmp_path):
        """Depending on the chunk DIR, not its VRT, is the point: re-fusing a cell never
        touches the VRT's own mtime, which is how the Caspian re-fuse hid."""
        out = _built(tmp_path)
        chunks = tmp_path / "chunks"
        (chunks / "e050_n40").mkdir(parents=True)
        cell = chunks / "e050_n40" / "heightfield_10s.tif"
        cell.write_text("re-fused")
        assert shade_planet.is_stale(out, chunks) is True


class TestWriteIfChanged:
    def test_identical_content_leaves_mtime_alone(self, tmp_path):
        """Load-bearing: an unchanged palette must NOT invalidate a 31 GB raster."""
        path = tmp_path / "ramp_sea.txt"
        path.write_text("0.00 133 185 183\n")
        _age(path, 500)
        before = path.stat().st_mtime
        shade_planet.write_if_changed(path, "0.00 133 185 183\n")
        assert path.stat().st_mtime == before

    def test_changed_content_moves_mtime(self, tmp_path):
        path = tmp_path / "ramp_sea.txt"
        path.write_text("0.00 133 185 183\n")
        _age(path, 500)
        before = path.stat().st_mtime
        shade_planet.write_if_changed(path, "0.00 142 198 196\n")
        assert path.stat().st_mtime > before

    def test_absent_file_is_written(self, tmp_path):
        path = shade_planet.write_if_changed(tmp_path / "new.json", "{}")
        assert path.read_text() == "{}"


class TestCompositeParams:
    def test_water_rgb_change_is_recorded(self, monkeypatch):
        """WATER_RGB reaches no file of its own; the sidecar is what tracks it."""
        before = shade_planet.composite_params({None: None})
        monkeypatch.setattr(palette, "WATER_RGB", (1, 2, 3))
        assert shade_planet.composite_params({None: None}) != before

    def test_none_variant_key_survives_json(self):
        """The production path keys variants by None, which JSON cannot use as a key."""
        assert "null" in shade_planet.composite_params({None: None})

    def test_lake_ramp_change_is_recorded(self, monkeypatch):
        """LAKE_STOPS reaches no file of its own either. Without this, re-tuning the lake
        ramp would leave a stale planet_rgb looking fresh -- the same silent drift that hit
        WATER_RGB, which is what started the whole inland-water thread."""
        before = shade_planet.composite_params({None: None})
        monkeypatch.setattr(palette, "LAKE_STOPS",
                            [(0.0, (0.0, 0.0, 0.0)), (1.0, (1.0, 1.0, 1.0))])
        assert shade_planet.composite_params({None: None}) != before

    def test_lake_curve_change_is_recorded(self, monkeypatch):
        """lake_curve rides in KNOBS, so it is already covered -- pin that it stays so."""
        before = shade_planet.composite_params({None: None})
        monkeypatch.setitem(shade_planet.KNOBS, "lake_curve", "sqrt")
        assert shade_planet.composite_params({None: None}) != before

    def test_fill_strength_is_NOT_recorded_here(self, monkeypatch):
        """The deliberate exception, and the only one. `fill_strength` rides in KNOBS (beside
        `alt`, likewise consumed by the hillshade) but composite() never reads it -- it reaches
        planet_rgb through composite_deps' dependency on `hs`. Recording it here too would restage
        a 53.8 min composite + 3:44 tile cut for byte-identical pixels merely because the knob
        exists at strength 0. Caught 2026-07-17 when the fill port first landed it in KNOBS."""
        before = shade_planet.composite_params({None: None})
        monkeypatch.setitem(shade_planet.KNOBS, "fill_strength", 0.15)
        assert shade_planet.composite_params({None: None}) == before

    def test_the_exclusion_is_narrow(self, monkeypatch):
        """Companion: the filter must drop `fill_strength` and nothing else. `alt` is the one that
        would be wrongly caught by a lazy 'hillshade knobs' rule -- composite reads it too
        (`flat = 255*sin(alt)`), so a change to it MUST still be recorded here."""
        before = shade_planet.composite_params({None: None})
        monkeypatch.setitem(shade_planet.KNOBS, "alt", 46.0)
        assert shade_planet.composite_params({None: None}) != before

    def test_a_land_ramp_retune_changes_the_params(self, monkeypatch):
        """The trap opened by deleting color-relief on 2026-07-16. LAND_STOPS/SEA_STOPS used to
        be tracked by ramp_{land,sea}.txt, whose only reason to exist was gating the gdaldem
        stages. With those gone, if the stops did not move in here, a ramp re-tune would leave
        planet_rgb looking fresh and the pass would skip the composite -- silently rendering the
        planet with the OLD palette. This is the same class as WATER_RGB drifting untracked."""
        before = shade_planet.composite_params({None: None})
        monkeypatch.setattr(palette, "LAND_STOPS",
                            [(0.0, (0.1, 0.1, 0.1)), (1.0, (0.9, 0.9, 0.9))])
        assert shade_planet.composite_params({None: None}) != before

    def test_a_sea_ramp_retune_changes_the_params(self, monkeypatch):
        before = shade_planet.composite_params({None: None})
        monkeypatch.setattr(palette, "SEA_STOPS",
                            [(0.0, (0.2, 0.3, 0.4)), (1.0, (0.0, 0.1, 0.2))])
        assert shade_planet.composite_params({None: None}) != before

    def test_the_lut_step_is_tracked(self, monkeypatch):
        """LUT_STEP_M sets how finely the ramp is sampled -- a real colour input now."""
        before = shade_planet.composite_params({None: None})
        monkeypatch.setattr(palette, "LUT_STEP_M", 25.0)
        assert shade_planet.composite_params({None: None}) != before


class TestCompositeDeps:
    """planet_rgb's freshness inputs. A raster missing from here is a raster whose change
    silently does nothing -- the guard reports fresh and the pass skips the composite."""

    def _deps(self, tmp_path):
        return shade_planet.composite_deps(
            tmp_path, tmp_path / "hs_3857.tif", tmp_path / "composite_params.json")

    @pytest.mark.parametrize("name", [
        # height_3857 replaced land_3857/sea_3857 on 2026-07-16: composite() applies the ramps
        # itself now, so ELEVATION is the colour input and the height raster is what it must be
        # newer than. The ramp constants ride in composite_params.json.
        "height_3857.tif", "hs_3857.tif",
        "ocean_3857.tif", "water_3857.tif", "lakedepth_3857.tif",
        "composite_params.json",
    ])
    def test_every_composite_input_is_a_dependency(self, tmp_path, name):
        assert name in {path.name for path in self._deps(tmp_path)}

    def test_a_refreshed_depth_raster_makes_planet_rgb_stale(self, tmp_path):
        """The end-to-end point of wiring depth into deps: re-extracting GLOBathy must
        force a re-composite rather than reprinting the old flat-lake planet."""
        planet_rgb = _built(tmp_path, "planet_rgb.tif")
        deps = self._deps(tmp_path)
        for path in deps:  # everything older than the output -> fresh
            path.write_text("x")
            _age(path, 500)
        assert shade_planet.is_stale(planet_rgb, *deps) is False
        (tmp_path / "lakedepth_3857.tif").write_text("re-extracted")  # now newer
        assert shade_planet.is_stale(planet_rgb, *deps) is True

    def test_a_rebuilt_hillshade_makes_planet_rgb_stale(self, tmp_path):
        """What makes it SAFE to keep `fill_strength` out of composite_params: a fill change
        restages the hillshade (hs_params.json tracks it), and this is the link that carries that
        through to the composite and the tiles. Break this and the exclusion becomes the very
        untracked-constant bug composite_params exists to prevent."""
        planet_rgb = _built(tmp_path, "planet_rgb.tif")
        deps = self._deps(tmp_path)
        for path in deps:
            path.write_text("x")
            _age(path, 500)
        assert shade_planet.is_stale(planet_rgb, *deps) is False
        (tmp_path / "hs_3857.tif").write_text("re-shaded with the fill sun")  # now newer
        assert shade_planet.is_stale(planet_rgb, *deps) is True


class TestRerunEconomics:
    """What a SECOND pass re-does. This is the difference between a lake-ramp tweak costing
    ~one composite and costing a 31 GB re-warp plus a 7.9 GB hillshade, so it is worth
    pinning rather than assuming.
    """

    def test_ramp_retune_recomposites_without_rewarping(self, tmp_path, monkeypatch):
        chunks = tmp_path / "chunks"
        chunks.mkdir()
        (chunks / "cell.tif").write_text("dem")
        heightfield_vrt = tmp_path / "planet_heightfield.vrt"
        heightfield_vrt.write_text("vrt")
        lake_vrt = tmp_path / "lakedepth.vrt"
        lake_vrt.write_text("vrt")

        # A completed pass, layered oldest-first: raw inputs (1000s) -> derived rasters
        # (500s) -> planet_rgb (100s). Anything else and the guard is right to cry stale.
        params = shade_planet.write_if_changed(
            tmp_path / "composite_params.json", shade_planet.composite_params({None: None}))
        deps = shade_planet.composite_deps(tmp_path, tmp_path / "hs_3857.tif", params)
        height = _built(tmp_path, "height_3857.tif")
        planet_rgb = _built(tmp_path, "planet_rgb.tif")
        for path in deps:
            if path != params:
                _built(tmp_path, path.name)

        for path in (chunks / "cell.tif", heightfield_vrt, lake_vrt, params):
            _at(path, 1000)
        for path in deps:
            if path != params:
                _at(path, 500)
        _at(height, 500)
        _at(planet_rgb, 100)
        assert shade_planet.is_stale(planet_rgb, *deps) is False, "unchanged rerun must skip"

        # Now re-tune the lake ramp and re-write the params exactly as a rerun would.
        monkeypatch.setattr(palette, "LAKE_STOPS",
                            [(0.0, (0.1, 0.2, 0.3)), (1.0, (0.4, 0.5, 0.6))])
        shade_planet.write_if_changed(params, shade_planet.composite_params({None: None}))

        assert shade_planet.is_stale(planet_rgb, *deps) is True, "ramp change must recomposite"
        assert shade_planet.is_stale(height, heightfield_vrt, chunks) is False, \
            "a ramp change must NOT trigger the 31 GB height re-warp"
        assert shade_planet.is_stale(tmp_path / "lakedepth_3857.tif", lake_vrt) is False, \
            "a ramp change must NOT re-warp the 83k-source GLOBathy VRT"


class TestPaletteTextRefactor:
    @pytest.mark.parametrize("kind", ["land", "sea"])
    def test_text_matches_the_written_file_byte_for_byte(self, tmp_path, kind):
        """color_relief_text was split out of write_color_relief; if it drifts, every
        ramp comparison silently re-colours the planet on every run."""
        path = tmp_path / f"ramp_{kind}.txt"
        palette.write_color_relief(path, kind)
        assert path.read_text() == palette.color_relief_text(kind)
