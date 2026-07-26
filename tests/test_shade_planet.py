"""Tests for the freshness guard that decides which planet-shading stages re-run.

The load-bearing case is `test_refused_cell_makes_the_warp_stale`: it reproduces the
Caspian miss, where re-fusing 4 of 540 chunks left every derived raster
silently stale because the old guard only asked whether the output existed.
"""

import json
import os
import time

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from pipeline.render import palette, seaice
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


def _built_pyramid(tmp_path):
    """A completed tile pyramid: the tiles/ dir with a tile inside, plus its .done marker.

    Freshness turns on the .done markers, so callers set ages via `_at`; this only lays out the
    files (dir non-empty, sentinel present) that `tiles_are_fresh` inspects.
    """
    live = tmp_path / "tiles"
    (live / "0" / "0").mkdir(parents=True)
    (live / "0" / "0" / "0.png").write_text("png")
    shade_planet.mark_done(live)
    return live


def _raster(path, width, height, bounds):
    """A real 1-band 3857 GTiff on the given grid. grid_matches reads actual raster dimensions,
    so these tests need rasters, not the text stand-ins the mtime tests use."""
    transform = from_bounds(*bounds, width, height)  # pyright: ignore[reportCallIssue] — rasterio untyped, *bounds opaque
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=1,
                       dtype="uint8", crs="EPSG:3857", transform=transform) as dataset:
        dataset.write(np.zeros((height, width), "uint8"), 1)
    return path


# (width, height, bounds) reference grid the warp targets below are checked against.
GRID = (10, 10, (0.0, 0.0, 100.0, 100.0))


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


class TestGridMatches:
    """The dimension/bounds guard that keeps a same-source raster from sitting falsely fresh after a
    re-fuse GROWS the planet grid under it -- the Antarctica precondition (93009 -> 131072 rows). A
    plain mtime test cannot see this: the raster's SOURCE never moved."""

    def test_same_grid_matches(self, tmp_path):
        out = _raster(tmp_path / "ocean_3857.tif", 10, 10, (0.0, 0.0, 100.0, 100.0))
        assert shade_planet.grid_matches(out, *GRID) is True

    def test_fewer_rows_does_not_match(self, tmp_path):
        """The exact Antarctica case: the planet gained rows at the bottom, but this raster's source
        never changed, so it still sits at the old, shorter row count."""
        out = _raster(tmp_path / "lakedepth_3857.tif", 10, 9, (0.0, 10.0, 100.0, 100.0))
        assert shade_planet.grid_matches(out, *GRID) is False

    def test_different_width_does_not_match(self, tmp_path):
        out = _raster(tmp_path / "water_3857.tif", 9, 10, (0.0, 0.0, 90.0, 100.0))
        assert shade_planet.grid_matches(out, *GRID) is False

    def test_shifted_bounds_at_matching_dimensions_does_not_match(self, tmp_path):
        """Companion: same pixel count, shifted origin -- so the check cannot be dimensions alone.
        The 1 m tolerance sits far below a 305 m pixel, so a real grid shift always trips it."""
        out = _raster(tmp_path / "seaice_3857.tif", 10, 10, (5000.0, 5000.0, 105000.0, 105000.0))
        assert shade_planet.grid_matches(out, *GRID) is False

    def test_missing_file_does_not_match(self, tmp_path):
        assert shade_planet.grid_matches(tmp_path / "nope.tif", *GRID) is False


class TestWarpNeedsRebuild:
    """The composed decision warp_inputs uses for every 3857 raster below height: rebuild on a moved
    source (is_stale) OR a resized grid (grid_matches). The second is the Antarctica case and is
    invisible to mtimes alone -- pinned here so removing the grid term fails a test, not just a pass.
    """

    def _target(self, tmp_path, name, width, height, bounds, age=100):
        """A completed warp target `age` s ago: the real raster plus its .done marker, both aged."""
        out = _raster(tmp_path / name, width, height, bounds)
        shade_planet.mark_done(out)
        _age(out, age)
        _age(shade_planet.done_marker(out), age)
        return out

    def test_fresh_source_on_grid_skips(self, tmp_path):
        out = self._target(tmp_path, "ocean_3857.tif", 10, 10, (0.0, 0.0, 100.0, 100.0))
        source = tmp_path / "planet_oceanmask.vrt"
        source.write_text("vrt")
        _age(source, 500)  # older than the output -> not stale
        assert shade_planet.warp_needs_rebuild(out, GRID, source) is False

    def test_fresh_source_off_grid_rebuilds(self, tmp_path):
        """THE load-bearing case: the source is older than the output (is_stale is False), but the
        planet grew under it -- only the grid term catches it, so it MUST rebuild."""
        out = self._target(tmp_path, "lakedepth_3857.tif", 10, 9, (0.0, 10.0, 100.0, 100.0))
        source = tmp_path / "lakedepth.vrt"
        source.write_text("vrt")
        _age(source, 500)
        assert shade_planet.is_stale(out, source) is False, "the source alone must look fresh"
        assert shade_planet.warp_needs_rebuild(out, GRID, source) is True

    def test_moved_source_on_grid_rebuilds(self, tmp_path):
        """The is_stale half still fires: a re-released source newer than the output rebuilds even
        when the grid is unchanged."""
        out = self._target(tmp_path, "seaice_3857.tif", 10, 10, (0.0, 0.0, 100.0, 100.0))
        source = tmp_path / "seaice.nc"
        source.write_text("re-released")  # written now -> newer than the output's marker
        assert shade_planet.warp_needs_rebuild(out, GRID, source) is True


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

    def test_cap_rgb_change_is_recorded(self, monkeypatch):
        """CAP_RGB (the polar-cap fill) reaches no file of its own; the 'cap' sidecar entry is what
        tracks it. Without this, a cap recolour would leave a stale planet_rgb looking fresh -- the
        recompose that switched the cap to pale sea-ice relied on exactly this restage."""
        before = shade_planet.composite_params({None: None})
        monkeypatch.setattr(shade_planet, "CAP_RGB", (1, 2, 3))
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
        exists at strength 0. Caught when the fill port first landed it in KNOBS."""
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
        """The trap opened by deleting color-relief. LAND_STOPS/SEA_STOPS used to
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

    def test_a_sea_ice_alpha_retune_changes_the_params(self, monkeypatch):
        """ICE_LO/ICE_BAND run at composite time inside seaice.ice_alpha, so like the snow ramp
        they must ride in composite_params -- else a re-tune leaves a stale planet_rgb looking
        fresh (the untracked-input trap that let snow's RAMP_* slip)."""
        before = shade_planet.composite_params({None: None})
        monkeypatch.setattr(seaice, "ICE_LO", seaice.ICE_LO + 0.1)
        assert shade_planet.composite_params({None: None}) != before

    def test_the_toned_sh_sea_ice_is_recorded(self, monkeypatch):
        """SH_ICE_LO/SH_ICE_MAX_ALPHA tone the Antarctic pack at composite time (southern windows),
        so like the ICE_LO globals they must ride here -- else a re-tune leaves a stale planet_rgb
        looking fresh (the untracked-input trap that let snow's RAMP_* slip)."""
        before = shade_planet.composite_params({None: None})
        monkeypatch.setattr(seaice, "SH_ICE_LO", seaice.SH_ICE_LO + 0.05)
        assert shade_planet.composite_params({None: None}) != before

    def test_a_sea_ice_colour_change_is_recorded(self, monkeypatch):
        """ICE_RGB/ICE_SHADOW_RGB are the sea-ice white (a notch cooler than snow); a change must
        restage the composite, the same way the snow and water colours are tracked."""
        before = shade_planet.composite_params({None: None})
        monkeypatch.setattr(palette, "ICE_RGB", (200, 220, 235))
        assert shade_planet.composite_params({None: None}) != before

    def test_the_lut_step_is_tracked(self, monkeypatch):
        """LUT_STEP_M sets how finely the ramp is sampled -- a real colour input now."""
        before = shade_planet.composite_params({None: None})
        monkeypatch.setattr(palette, "LUT_STEP_M", 25.0)
        assert shade_planet.composite_params({None: None}) != before

    def test_composite_window_rows_is_recorded(self):
        """The composite window height slices the SVF per window, so it perturbs the output
        (the 256->128 A/B). It must be tracked, or switching the production window
        height leaves a stale planet_rgb looking fresh -- the WATER_RGB trap again."""
        assert (shade_planet.composite_params({None: None}, window_rows=256)
                != shade_planet.composite_params({None: None}, window_rows=128))

    def test_composite_window_rows_defaults_to_the_snow_band(self):
        """The default is WINDOW_ROWS so callers that don't pass it (tests, the region path)
        record the same height the serial default composites at."""
        assert (shade_planet.composite_params({None: None})
                == shade_planet.composite_params({None: None}, window_rows=shade_planet.WINDOW_ROWS))


class TestCompositeDeps:
    """planet_rgb's freshness inputs. A raster missing from here is a raster whose change
    silently does nothing -- the guard reports fresh and the pass skips the composite."""

    def _deps(self, tmp_path):
        return shade_planet.composite_deps(
            tmp_path, tmp_path / "hs_3857.tif", tmp_path / "composite_params.json")

    @pytest.mark.parametrize("name", [
        # height_3857 replaced land_3857/sea_3857: composite() applies the ramps
        # itself now, so ELEVATION is the colour input and the height raster is what it must be
        # newer than. The ramp constants ride in composite_params.json.
        "height_3857.tif", "hs_3857.tif",
        "ocean_3857.tif", "water_3857.tif", "lakedepth_3857.tif",
        # snow became a warp-once input (optimisation #4): the composite reads pre-warped
        # persistence + glacier rasters per window instead of forking gdalwarp in the loop. A
        # re-warp (new NSIDC/RGI, or a re-fuse changing the grid) must restage the composite.
        "snow_persistence_3857.tif", "glacier_3857.tif", "seaice_3857.tif",
        "composite_params.json",
    ])
    def test_every_composite_input_is_a_dependency(self, tmp_path, name):
        assert name in {path.name for path in self._deps(tmp_path)}

    def test_a_rewarped_snow_raster_makes_planet_rgb_stale(self, tmp_path):
        """The warp-once analog of the depth/hillshade tests: re-warping snow persistence (new
        NSIDC data, or a re-fuse to a new grid) must force a re-composite, not reprint stale snow."""
        planet_rgb = _built(tmp_path, "planet_rgb.tif")
        deps = self._deps(tmp_path)
        for path in deps:
            path.write_text("x")
            _age(path, 500)
        assert shade_planet.is_stale(planet_rgb, *deps) is False
        (tmp_path / "snow_persistence_3857.tif").write_text("re-warped")  # now newer
        assert shade_planet.is_stale(planet_rgb, *deps) is True

    def test_a_rewarped_seaice_raster_makes_planet_rgb_stale(self, tmp_path):
        """The sea-side twin: re-warping the ice-frequency climatology (new OSI SAF release, or a
        re-fuse to a new grid) must force a re-composite, not reprint stale ice."""
        planet_rgb = _built(tmp_path, "planet_rgb.tif")
        deps = self._deps(tmp_path)
        for path in deps:
            path.write_text("x")
            _age(path, 500)
        assert shade_planet.is_stale(planet_rgb, *deps) is False
        (tmp_path / "seaice_3857.tif").write_text("re-warped")  # now newer
        assert shade_planet.is_stale(planet_rgb, *deps) is True

    def test_snow_warps_are_NOT_hillshade_inputs(self, tmp_path):
        """Snow is consumed by composite(), not the hillshade -- so its warp rasters belong in
        composite_deps, never hs_params. Recording them there would restage an 11:48 hillshade
        that cannot see them. (The composite-vs-hillshade split, same as snow_curve.)"""
        hs_recorded = shade_planet.hs_params()
        assert "snow_persistence_3857" not in hs_recorded
        assert "glacier_3857" not in hs_recorded

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


class TestBuildTilesGuard:
    """build_tiles was the one unguarded stage -- it re-cut all 62k tiles on every --tiles run and
    resumed over truncated pngs. A tiles.done sentinel + tiles_are_fresh + a clean cut (no --resume)
    close both gaps. These lock the freshness decision the way TestIsStale locks is_stale.
    """

    def test_current_pyramid_is_fresh(self, tmp_path):
        planet = _built(tmp_path, "planet_rgb.tif")
        _built_pyramid(tmp_path)
        _at(planet, 200)               # composite finished 200 s ago...
        _at(tmp_path / "tiles", 100)   # ...tiles cut 100 s ago, so the pyramid is current
        assert shade_planet.tiles_are_fresh(planet, tmp_path) is True

    def test_stale_when_composite_is_newer(self, tmp_path):
        planet = _built(tmp_path, "planet_rgb.tif")
        _built_pyramid(tmp_path)
        _at(planet, 100)               # recomposited 100 s ago...
        _at(tmp_path / "tiles", 200)   # ...over a pyramid cut 200 s ago -> must re-cut
        assert shade_planet.tiles_are_fresh(planet, tmp_path) is False

    def test_stale_without_a_pyramid_marker(self, tmp_path):
        """A tiles/ dir with content but no tiles.done -- e.g. an interrupted swap -- is not fresh."""
        planet = _built(tmp_path, "planet_rgb.tif")
        live = tmp_path / "tiles"
        (live / "0").mkdir(parents=True)
        (live / "0" / "0.png").write_text("png")
        assert shade_planet.tiles_are_fresh(planet, tmp_path) is False

    def test_stale_when_pyramid_dir_is_empty(self, tmp_path):
        """An empty tiles/ (a half-finished swap) passes exists() but must still re-cut."""
        planet = _built(tmp_path, "planet_rgb.tif")
        live = tmp_path / "tiles"
        live.mkdir()
        shade_planet.mark_done(live)
        assert shade_planet.tiles_are_fresh(planet, tmp_path) is False

    def test_stale_when_composite_never_stamped(self, tmp_path):
        """planet_rgb.tif with no .done (a crashed composite) must never read as fresh -- else the
        0.0 mtime of the missing marker would slip past is_stale and skip a needed cut."""
        planet = tmp_path / "planet_rgb.tif"
        planet.write_text("half-written")
        _built_pyramid(tmp_path)
        assert shade_planet.tiles_are_fresh(planet, tmp_path) is False

    def test_tile_cmd_omits_resume(self, tmp_path):
        """No --resume: GDAL would skip a truncated tile by existence. --skip-blank is asserted too
        so a wrong or empty arg list would trip the check rather than pass vacuously."""
        cmd = shade_planet._tile_cmd(tmp_path / "planet_rgb.tif", tmp_path / "tiles_new")
        assert "--resume" not in cmd
        assert "--skip-blank" in cmd


class TestTileRecipe:
    """The cut's own settings are a freshness input, and the command is built from them.

    This stage was the one that could not see its own recipe: `tiles_are_fresh` keyed off
    `planet_rgb` alone, so changing the output format left the guard true and a `--tiles` run would
    have reported "tiles fresh -> skip cut" while shipping the previous encoding. These lock both
    halves — that TILE_CUT reaches the command line, and that changing it restages.
    """

    def test_every_setting_reaches_the_command(self, tmp_path):
        """The command and the recorded recipe cannot disagree, because one is built from the other.
        A setting recorded but never passed would restage the world for no pixel change."""
        cmd = " ".join(shade_planet._tile_cmd(tmp_path / "planet_rgb.tif", tmp_path / "tiles_new"))
        assert f"--format={shade_planet.TILE_CUT['format']}" in cmd
        assert f"QUALITY={shade_planet.TILE_CUT['quality']}" in cmd
        assert f"--tile-size={shade_planet.TILE_CUT['tile_size']}" in cmd
        assert f"--min-zoom={shade_planet.TILE_CUT['min_zoom']}" in cmd
        assert f"--max-zoom={shade_planet.TILE_CUT['max_zoom']}" in cmd
        assert f"--resampling={shade_planet.TILE_CUT['resampling']}" in cmd
        assert f"--overview-resampling={shade_planet.TILE_CUT['overview_resampling']}" in cmd
        assert f"--convention={shade_planet.TILE_CUT['convention']}" in cmd

    def test_params_serialise_the_whole_recipe(self):
        assert json.loads(shade_planet.tile_params()) == dict(shade_planet.TILE_CUT)

    def test_skip_blank_follows_the_recipe(self, tmp_path):
        """Asserted from the flag rather than the constant, so flipping it off is a real change and
        not a silently ignored field in the record."""
        cmd = shade_planet._tile_cmd(tmp_path / "planet_rgb.tif", tmp_path / "tiles_new")
        assert ("--skip-blank" in cmd) is shade_planet.TILE_CUT["skip_blank"]

    def test_a_newer_recipe_restages_a_current_pyramid(self, tmp_path):
        """The whole point: composite untouched, pyramid present and stamped, recipe rewritten
        after the cut -> must re-cut. Without tile_params in the key this reads as fresh."""
        planet = _built(tmp_path, "planet_rgb.tif")
        _built_pyramid(tmp_path)
        _at(planet, 300)
        _at(tmp_path / "tiles", 200)
        params = shade_planet.tile_params_path(tmp_path)
        params.write_text(shade_planet.tile_params())
        _at(params, 100)                # recipe changed after the cut
        assert shade_planet.tiles_are_fresh(planet, tmp_path) is False

    def test_an_older_recipe_leaves_the_pyramid_fresh(self, tmp_path):
        """The control that stops the check passing vacuously: an unchanged recipe (write_if_changed
        never moves its mtime) must NOT restage a 4:19 cut."""
        planet = _built(tmp_path, "planet_rgb.tif")
        _built_pyramid(tmp_path)
        params = shade_planet.tile_params_path(tmp_path)
        params.write_text(shade_planet.tile_params())
        _at(params, 300)
        _at(planet, 200)
        _at(tmp_path / "tiles", 100)
        assert shade_planet.tiles_are_fresh(planet, tmp_path) is True

    def test_write_if_changed_leaves_an_identical_recipe_alone(self, tmp_path):
        """build_tiles rewrites the recipe on every run, so an unchanged one must not move its
        mtime — otherwise every --tiles invocation would restage the pyramid."""
        params = shade_planet.tile_params_path(tmp_path)
        shade_planet.write_if_changed(params, shade_planet.tile_params())
        _age(params, 500)
        before = params.stat().st_mtime
        shade_planet.write_if_changed(params, shade_planet.tile_params())
        assert params.stat().st_mtime == before
