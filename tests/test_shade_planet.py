"""Tests for the freshness guard that decides which planet-shading stages re-run.

The load-bearing case is `test_refused_cell_makes_the_warp_stale`: it reproduces the
Caspian miss, where re-fusing 4 of 540 chunks left every derived raster
silently stale because the old guard only asked whether the output existed.
"""

import dataclasses
import json
import os
import sys
import time
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from pipeline import bodies, planet_seam
from pipeline.render import palette, seaice, snow
from pipeline.tile import cap_render, shade, shade_planet

#: A planet whose seam emitted all three rasters — what Earth declares, and the only
#: shape these tests care about unless they say otherwise.
WHOLE_PLANET = planet_seam.KNOWN_RASTERS


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


def _written(path, text):
    path.write_text(text)
    return path


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


class TestTheRampOriginIsTracked:
    """The origin is recorded CONDITIONALLY, and both halves of that need proving separately.

    Conditional records are how this module keeps Earth's shipped pyramid from restaging over a
    field it does not use, and every one of them buys that with a risk: a key that is absent when
    it should be present is an untracked input, which is the exact silent-stale failure this whole
    sidecar exists to prevent. So: absent for a ramp on the datum, present the moment one is not.

    Split into the RULE and the WIRING, and neither half patches anything. The rule is a pure
    function over a synthetic ramp; the wiring is the two real bodies, which between them already
    supply both branches — Earth on the datum, Mars off it. A second body is what made this
    testable without substituting one.
    """

    def test_earths_ramps_add_no_key_because_both_hinge_on_the_datum(self):
        recipe = json.loads(shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET))
        assert [key for key in recipe if key.endswith("_origin_m")] == []

    def test_a_ramp_off_the_datum_is_recorded(self):
        """Mars is the real instance; without it this rule would be unfalsifiable, since every
        Earth ramp starts at 0 and no Earth edit could ever move one.

        THE RASTER SET IS STATED, NOT READ OFF THE DISK, and the difference is the whole reason this
        went red in CI and green here. `planet_seam.declared` raises when a body's planet stage has
        not run — correctly, that is its job — so calling it made a unit test about a COLOUR RAMP
        depend on this machine having 3 GB of warped Mars sitting in `data/`. No raster influences
        `land_origin_m`; it comes from the look. The literal is what `fuse/relabel_mars.py` declares,
        and `tests/test_relabel_mars.py` is where that agreement is actually held.
        """
        recipe = json.loads(shade_planet.composite_params(
            {None: None}, bodies.MARS, frozenset({"heightfield"})))
        assert recipe["land_origin_m"] == palette.MARS_LOOK.land.origin_m
        assert recipe["land_origin_m"] != 0.0

    @pytest.mark.parametrize("origin,expected", [
        (-6000.0, {"land_origin_m": -6000.0}),   # off the datum -> tracked
        (0.0, {}),                               # on it -> absent, so Earth's sidecar cannot move
        (250.0, {"land_origin_m": 250.0}),       # a positive origin is off the datum too
    ])
    def test_the_rule_itself_over_a_synthetic_ramp(self, origin, expected):
        """`_ramp_origin` is a pure function of a `Surface`, so the rule is tested by CALLING it.

        This deliberately replaces a pair of tests that patched `LOOK_BY_BODY` to swing a body's
        look. Those covered the same rule and paid for it: a patch proves the code did what the
        patch said, and this repo has already had two composite_params tests go quietly vacuous
        because what they patched stopped being what the recipe read. Nothing is substituted here.
        """
        ramp = palette.Surface(stops=palette.LAND_STOPS, origin_m=origin, extreme_m=6100.0)
        assert shade_planet._ramp_origin("land", ramp) == expected


class TestCompositeParams:
    def test_water_rgb_change_is_recorded(self, monkeypatch):
        """WATER_RGB reaches no file of its own; the sidecar is what tracks it."""
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setattr(palette, "WATER_RGB", (1, 2, 3))
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != before

    def test_cap_rgb_change_is_recorded(self, monkeypatch):
        """CAP_RGB (the polar-cap fill) reaches no file of its own; the 'cap' sidecar entry is what
        tracks it. Without this, a cap recolour would leave a stale planet_rgb looking fresh -- the
        recompose that switched the cap to pale sea-ice relied on exactly this restage."""
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setattr(shade_planet, "CAP_RGB", (1, 2, 3))
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != before

    def test_none_variant_key_survives_json(self):
        """The production path keys variants by None, which JSON cannot use as a key."""
        assert "null" in shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)

    def test_lake_ramp_change_is_recorded(self, monkeypatch):
        """LAKE_STOPS reaches no file of its own either. Without this, re-tuning the lake
        ramp would leave a stale planet_rgb looking fresh -- the same silent drift that hit
        WATER_RGB, which is what started the whole inland-water thread."""
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setattr(palette, "LAKE_STOPS",
                            [(0.0, (0.0, 0.0, 0.0)), (1.0, (1.0, 1.0, 1.0))])
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != before

    def test_lake_curve_change_is_recorded(self, monkeypatch):
        """lake_curve rides in KNOBS, so it is already covered -- pin that it stays so."""
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setitem(shade_planet.KNOBS, "lake_curve", "sqrt")
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != before

    def test_fill_strength_is_NOT_recorded_here(self, monkeypatch):
        """The deliberate exception, and the only one. `fill_strength` rides in KNOBS (beside
        `alt`, likewise consumed by the hillshade) but composite() never reads it -- it reaches
        planet_rgb through composite_deps' dependency on `hs`. Recording it here too would restage
        a 53.8 min composite + 3:44 tile cut for byte-identical pixels merely because the knob
        exists at strength 0. Caught when the fill port first landed it in KNOBS."""
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setitem(shade_planet.KNOBS, "fill_strength", 0.15)
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) == before

    def test_the_exclusion_is_narrow(self, monkeypatch):
        """Companion: the filter must drop `fill_strength` and nothing else. `alt` is the one that
        would be wrongly caught by a lazy 'hillshade knobs' rule -- composite reads it too
        (`flat = 255*sin(alt)`), so a change to it MUST still be recorded here."""
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setitem(shade_planet.KNOBS, "alt", 46.0)
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != before

    def test_a_land_ramp_retune_changes_the_params(self, monkeypatch):
        """The trap opened by deleting color-relief. LAND_STOPS/SEA_STOPS used to
        be tracked by ramp_{land,sea}.txt, whose only reason to exist was gating the gdaldem
        stages. With those gone, if the stops did not move in here, a ramp re-tune would leave
        planet_rgb looking fresh and the pass would skip the composite -- silently rendering the
        planet with the OLD palette. This is the same class as WATER_RGB drifting untracked.

        RE-TUNED THROUGH THE LOOK, NOT THE MODULE GLOBAL, and the difference is the point. The
        recipe reads the ramp off the BODY'S look now, so `palette.LAND_STOPS` is no longer the
        input — it is one of the values Earth's look happens to be assembled from. Patching it
        passes through nothing, which is exactly the proxy-instead-of-entry-point mistake this
        suite has paid for before. A source re-tune still restages: editing the constant rebuilds
        `EARTH_LOOK` at import, which is what a real re-tune does."""
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setitem(palette.LOOK_BY_BODY, "earth", dataclasses.replace(
            palette.EARTH_LOOK, land=dataclasses.replace(
                palette.EARTH_LOOK.land,
                stops=[(0.0, (0.1, 0.1, 0.1)), (1.0, (0.9, 0.9, 0.9))])))
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != before

    def test_a_sea_ramp_retune_changes_the_params(self, monkeypatch):
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        assert palette.EARTH_LOOK.sea is not None
        monkeypatch.setitem(palette.LOOK_BY_BODY, "earth", dataclasses.replace(
            palette.EARTH_LOOK, sea=dataclasses.replace(
                palette.EARTH_LOOK.sea,
                stops=[(0.0, (0.2, 0.3, 0.4)), (1.0, (0.0, 0.1, 0.2))])))
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != before

    def test_a_sea_ice_alpha_retune_changes_the_params(self, monkeypatch):
        """ICE_LO/ICE_BAND run at composite time inside seaice.ice_alpha, so like the snow ramp
        they must ride in composite_params -- else a re-tune leaves a stale planet_rgb looking
        fresh (the untracked-input trap that let snow's RAMP_* slip)."""
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setattr(seaice, "ICE_LO", seaice.ICE_LO + 0.1)
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != before

    def test_the_toned_sh_sea_ice_is_recorded(self, monkeypatch):
        """SH_ICE_LO/SH_ICE_MAX_ALPHA tone the Antarctic pack at composite time (southern windows),
        so like the ICE_LO globals they must ride here -- else a re-tune leaves a stale planet_rgb
        looking fresh (the untracked-input trap that let snow's RAMP_* slip)."""
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setattr(seaice, "SH_ICE_LO", seaice.SH_ICE_LO + 0.05)
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != before

    def test_a_sea_ice_colour_change_is_recorded(self, monkeypatch):
        """ICE_RGB/ICE_SHADOW_RGB are the sea-ice white (a notch cooler than snow); a change must
        restage the composite, the same way the snow and water colours are tracked."""
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setattr(palette, "ICE_RGB", (200, 220, 235))
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != before

    def test_the_lut_step_is_tracked(self, monkeypatch):
        """LUT_STEP_M sets how finely the ramp is sampled -- a real colour input now."""
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setattr(palette, "LUT_STEP_M", 25.0)
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != before

    def test_composite_window_rows_is_recorded(self):
        """The composite window height slices the SVF per window, so it perturbs the output
        (the 256->128 A/B). It must be tracked, or switching the production window
        height leaves a stale planet_rgb looking fresh -- the WATER_RGB trap again."""
        assert (shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET, window_rows=256)
                != shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET, window_rows=128))

    def test_composite_window_rows_defaults_to_the_snow_band(self):
        """The default is WINDOW_ROWS so callers that don't pass it (tests, the region path)
        record the same height the serial default composites at."""
        assert (shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
                == shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET, window_rows=shade_planet.WINDOW_ROWS))


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
        hs_recorded = shade_planet.hs_params(bodies.EARTH)
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
            tmp_path / "composite_params.json", shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET))
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
        shade_planet.write_if_changed(params, shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET))

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
        palette.write_color_relief(path, kind, look=palette.EARTH_LOOK)
        assert path.read_text() == palette.color_relief_text(kind, look=palette.EARTH_LOOK)


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
        cmd = shade_planet._tile_cmd(tmp_path / "planet_rgb.tif", tmp_path / "tiles_new",
                                     bodies.EARTH)
        assert "--resume" not in cmd
        assert "--skip-blank" in cmd


class TestTileRecipe:
    """The cut's own settings are a freshness input, and the command is built from them.

    This stage was the one that could not see its own recipe: `tiles_are_fresh` keyed off
    `planet_rgb` alone, so changing the output format left the guard true and a `--tiles` run would
    have reported "tiles fresh -> skip cut" while shipping the previous encoding. These lock both
    halves — that the cut reaches the command line, and that changing it restages.
    """

    def test_every_setting_reaches_the_command(self, subtests, tmp_path):
        """The command and the recorded recipe cannot disagree, because one is built from the other.
        A setting recorded but never passed would restage the world for no pixel change.

        Subtests because the realistic regression is a rewritten `_tile_cmd`, which drops SEVERAL
        settings at once; a chain of asserts would name the first and hide the rest. `skip_blank`
        is the cut's ninth key and is asserted next door, from the flag rather than the constant,
        because its presence depends on its value.
        """
        cmd = " ".join(shade_planet._tile_cmd(tmp_path / "planet_rgb.tif", tmp_path / "tiles_new",
                                     bodies.EARTH))
        with subtests.test("format"):
            assert f"--format={shade_planet.tile_cut(bodies.EARTH)['format']}" in cmd
        with subtests.test("quality"):
            assert f"QUALITY={shade_planet.tile_cut(bodies.EARTH)['quality']}" in cmd
        with subtests.test("tile_size"):
            assert f"--tile-size={shade_planet.tile_cut(bodies.EARTH)['tile_size']}" in cmd
        with subtests.test("min_zoom"):
            assert f"--min-zoom={shade_planet.tile_cut(bodies.EARTH)['min_zoom']}" in cmd
        with subtests.test("max_zoom"):
            assert f"--max-zoom={shade_planet.tile_cut(bodies.EARTH)['max_zoom']}" in cmd
        with subtests.test("resampling"):
            assert f"--resampling={shade_planet.tile_cut(bodies.EARTH)['resampling']}" in cmd
        with subtests.test("overview_resampling"):
            assert f"--overview-resampling={shade_planet.tile_cut(bodies.EARTH)['overview_resampling']}" in cmd
        with subtests.test("convention"):
            assert f"--convention={shade_planet.tile_cut(bodies.EARTH)['convention']}" in cmd

    def test_params_serialise_the_whole_recipe(self):
        assert json.loads(shade_planet.tile_params(bodies.EARTH)) == dict(shade_planet.tile_cut(bodies.EARTH))

    def test_skip_blank_follows_the_recipe(self, tmp_path):
        """Asserted from the flag rather than the constant, so flipping it off is a real change and
        not a silently ignored field in the record."""
        cmd = shade_planet._tile_cmd(tmp_path / "planet_rgb.tif", tmp_path / "tiles_new",
                                     bodies.EARTH)
        assert ("--skip-blank" in cmd) is shade_planet.tile_cut(bodies.EARTH)["skip_blank"]

    def test_a_newer_recipe_restages_a_current_pyramid(self, tmp_path):
        """The whole point: composite untouched, pyramid present and stamped, recipe rewritten
        after the cut -> must re-cut. Without tile_params in the key this reads as fresh."""
        planet = _built(tmp_path, "planet_rgb.tif")
        _built_pyramid(tmp_path)
        _at(planet, 300)
        _at(tmp_path / "tiles", 200)
        params = shade_planet.tile_params_path(tmp_path)
        params.write_text(shade_planet.tile_params(bodies.EARTH))
        _at(params, 100)                # recipe changed after the cut
        assert shade_planet.tiles_are_fresh(planet, tmp_path) is False

    def test_an_older_recipe_leaves_the_pyramid_fresh(self, tmp_path):
        """The control that stops the check passing vacuously: an unchanged recipe (write_if_changed
        never moves its mtime) must NOT restage a 4:19 cut."""
        planet = _built(tmp_path, "planet_rgb.tif")
        _built_pyramid(tmp_path)
        params = shade_planet.tile_params_path(tmp_path)
        params.write_text(shade_planet.tile_params(bodies.EARTH))
        _at(params, 300)
        _at(planet, 200)
        _at(tmp_path / "tiles", 100)
        assert shade_planet.tiles_are_fresh(planet, tmp_path) is True

    def test_write_if_changed_leaves_an_identical_recipe_alone(self, tmp_path):
        """build_tiles rewrites the recipe on every run, so an unchanged one must not move its
        mtime — otherwise every --tiles invocation would restage the pyramid."""
        params = shade_planet.tile_params_path(tmp_path)
        shade_planet.write_if_changed(params, shade_planet.tile_params(bodies.EARTH))
        _age(params, 500)
        before = params.stat().st_mtime
        shade_planet.write_if_changed(params, shade_planet.tile_params(bodies.EARTH))
        assert params.stat().st_mtime == before


class TestTheBodyIsRequired:
    """`--body` has no default, and that is the point of it.

    A pipeline that assumes Earth when nobody said so is the most expensive failure mode this
    registry exists to prevent: it does not raise, it produces a complete, plausible, entirely wrong
    pyramid. Cheap to re-run, ruinous to discover late — so the argument is required rather than
    defaulted, and every documented invocation names the planet it means.
    """

    def test_omitting_the_body_is_an_error_rather_than_an_assumption(self):
        with pytest.raises(SystemExit):
            shade_planet.build_parser().parse_args([])

    def test_a_named_body_resolves_to_its_own_work_tree(self):
        args = shade_planet.build_parser().parse_args(["--body", "earth"])
        assert shade_planet.resolve_out(args) == bodies.work_dir(bodies.EARTH, "planet_tiles")

    def test_an_explicit_out_still_wins_over_the_body_s_default(self, tmp_path):
        """The override has to survive, because a look A/B is run by pointing --out elsewhere."""
        args = shade_planet.build_parser().parse_args(["--body", "earth", "--out", str(tmp_path)])
        assert shade_planet.resolve_out(args) == tmp_path

    def test_an_unknown_body_is_rejected_by_the_registry_not_silently_accepted(self):
        args = shade_planet.build_parser().parse_args(["--body", "pluto"])
        with pytest.raises(KeyError):
            shade_planet.resolve_body(args)

    def test_the_shade_pass_hands_its_own_body_down_to_the_cap_pass(self, subtests):
        """The caps run as a SUBPROCESS at the tail of this pass, so the body crosses a process
        boundary as a string on a command line — the one place the registry cannot protect it.

        Without this, a Mars pass composites Mars and then shells out to a cap render that renders
        EARTH, into Earth's directories, over Earth's shipped textures. Every stage reports success.

        Written as a round trip rather than as two pinned strings on purpose: it builds the real
        command and parses it with the real parser on the other side, so renaming the flag on either
        side fails here instead of at the next multi-body render.
        """
        for name in sorted(bodies.BODIES):
            with subtests.test(name):
                body = bodies.get(name)
                command = shade_planet.cap_pass_command(body)
                module = command.index("pipeline.tile.cap_render")
                parsed = cap_render.build_parser().parse_args(command[module + 1:])
                assert bodies.get(parsed.body) is body

        with subtests.test("a body the registry does not know yet"):
            # THE LOOP ABOVE CANNOT CATCH A HARDCODED "earth" while the registry holds one body —
            # every assertion in it would pass against a command that ignored its argument entirely.
            # This is the arm that says the command names the body it was GIVEN, and it is the arm
            # that will still be doing work on the day a second planet is added.
            other = dataclasses.replace(bodies.EARTH, name="other", path_prefix="other")
            command = shade_planet.cap_pass_command(other)
            assert command[command.index("--body") + 1] == "other"

    def test_a_body_publishing_no_caps_is_refused_by_the_cap_pass_itself(self, monkeypatch):
        """The SECOND gate, and it is not redundant with the shade pass declining to invoke this.

        Reaching `cap_render.main` means an operator ran it directly, and the answer has to be the
        same one. It matters because the render would otherwise SUCCEED: a body declaring no surface
        layers needs only the heightfield, so there is no missing file to stop it — it would spend
        ~14 GB a pole to publish discs shaded by ramps that body has never been given.

        Asserted through the real entry point with the real parser, because the refusal has to
        happen before anything reads a raster, and only running `main` proves the order.

        THE CAPLESS BODY IS SYNTHETIC AND HAS TO BE. It used to be found by scanning the registry,
        which held one while Mars's ramps were unratified; ratifying them turned Mars's caps on and
        took the last negative instance with it. A guard that sources its negative instance from a
        live field is a guard that quietly stops testing anything when that field flips. It goes
        INTO the registry for the call, because `main` resolves a name off argv.
        """
        capless = dataclasses.replace(bodies.EARTH, name="capless", path_prefix="capless",
                                      renders_polar_caps=False)
        monkeypatch.setitem(bodies.BODIES, capless.name, capless)
        with mock.patch.object(sys, "argv", ["cap_render", "--body", capless.name]), \
                pytest.raises(SystemExit) as refusal:
            cap_render.main()
        message = str(refusal.value)
        assert capless.name in message and "renders_polar_caps" in message, message

    def test_the_shade_pass_skips_the_cap_subprocess_for_a_body_that_publishes_none(self):
        """The FIRST gate, asserted on the branch rather than on the flag.

        A test reading `body.renders_polar_caps` back would pass against a shade pass that consulted
        it and then shelled out anyway. What must be true is that no cap subprocess is spawned, so
        the assertion is on the decision the pass makes with the field.

        The synthetic body is what keeps the loop from being one-sided: every registered planet
        renders caps now, so the registry alone would only ever exercise the True arm and a
        `runs_cap_pass` hardcoded to True would pass.
        """
        capless = dataclasses.replace(bodies.EARTH, name="capless", renders_polar_caps=False)
        for body in [bodies.get(name) for name in sorted(bodies.BODIES)] + [capless]:
            assert shade_planet.runs_cap_pass(body) is body.renders_polar_caps


class TestTheWarpPassAsksTheSeamBeforeTheDisk:
    """`warp_inputs`, driven for real with gdalwarp captured at the boundary.

    Recording the COMMANDS is the assertion. A mask that this planet never emitted must not reach
    `gdalwarp` at all — and a test that only inspected the resulting files would pass a version
    which warped Earth's masks onto another body's grid and then ignored them.
    """

    BARE = dataclasses.replace(bodies.EARTH, name="bare", path_prefix="bare",
                               surface_layers=frozenset())

    def _drive(self, tmp_path, monkeypatch, rasters):
        work, planet = tmp_path / "work", tmp_path / "planet"
        work.mkdir()
        planet.mkdir()
        height = _raster(work / "height_3857.tif", 10, 10, GRID[2])
        shade_planet.mark_done(height)
        for raster in planet_seam.PLANET_RASTERS:
            source = planet / f"planet_{raster}.vrt"
            source.write_text("vrt")
            _age(source, 500)  # older than the height marker -> nothing is stale
        commands: list[list[str]] = []
        monkeypatch.setattr(shade_planet, "_run", lambda cmd: commands.append([str(p) for p in cmd]))
        shade_planet.warp_inputs(work, planet, self.BARE, rasters)
        return commands

    def test_an_undeclared_mask_never_reaches_gdalwarp(self, tmp_path, monkeypatch):
        commands = self._drive(tmp_path, monkeypatch, frozenset({"heightfield"}))
        assert commands == [], "a planet that emitted only a heightfield warped something else"

    def test_a_declared_mask_is_warped_even_though_the_target_never_existed(
            self, tmp_path, monkeypatch):
        """The mirror arm. Without it the test above passes against a `warp_inputs` that warps
        nothing at all, which is the shape a broken gate would take."""
        commands = self._drive(tmp_path, monkeypatch, planet_seam.KNOWN_RASTERS)
        warped = {command[-1].rsplit("/", 1)[-1] for command in commands}
        assert warped == {"ocean_3857.tif", "water_3857.tif"}

    def test_the_two_masks_are_gated_separately(self, tmp_path, monkeypatch):
        """Not a pair: Phase 2's chosen shoreline contour gives a body an ocean mask while it still
        has no inland water, and that combination must not need a code change."""
        commands = self._drive(tmp_path, monkeypatch, frozenset({"heightfield", "oceanmask"}))
        warped = {command[-1].rsplit("/", 1)[-1] for command in commands}
        assert warped == {"ocean_3857.tif"}


class TestTheCompositeRecipeRecordsTheRastersThatAreOff:
    def test_a_whole_planet_records_nothing(self):
        """Earth emits every raster, so its recipe carries no `rasters_off` — adding one would
        restage the live composite and cut to reproduce pixels that are already correct."""
        assert "rasters_off" not in json.loads(
            shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET))

    def test_a_planet_with_no_masks_records_both(self):
        recorded = json.loads(shade_planet.composite_params(
            {None: None}, bodies.MARS, frozenset({"heightfield"})))
        assert recorded["rasters_off"] == ["oceanmask", "watermask"]

    def test_switching_a_mask_OFF_restages_where_no_mtime_could(self):
        """THE reason this key exists. Turning a mask ON is already covered — the warp builds a
        raster `composite_deps` lists, and its mtime moves. Turning one OFF moves nothing at all:
        the old warp is still on disk and the sea-painted composite reads fresh forever."""
        with_sea = shade_planet.composite_params({None: None}, bodies.MARS, WHOLE_PLANET)
        without = shade_planet.composite_params({None: None}, bodies.MARS,
                                                frozenset({"heightfield"}))
        assert with_sea != without

    def test_it_is_recorded_separately_from_the_surface_layers(self):
        """Two vocabularies, two keys. A raster is what the planet stage emitted; a layer is what
        the render paints over it, and collapsing them would tie a cap-only decision to the tiles."""
        recorded = json.loads(shade_planet.composite_params(
            {None: None}, bodies.MARS, frozenset({"heightfield"})))
        assert recorded["layers_off"] == sorted(bodies.COMPOSITE_LAYERS)
        assert recorded["rasters_off"] == ["oceanmask", "watermask"]


#: Each layer-gated group in the composite recipe: the layer whose paint reads it, one key it
#: contributes, and a constant behind that key with a value it does not already hold.
LAYER_GATED = [
    ("perennial_ice", "snow_rgb", palette, "SNOW_RGB", (1, 2, 3)),
    ("perennial_ice", "snow_shadow_rgb", palette, "SNOW_SHADOW_RGB", (1, 2, 3)),
    ("perennial_ice", "snow_ramp_band", snow, "RAMP_BAND", 0.99),
    ("perennial_ice", "snow_ramp_lat_lo", snow, "RAMP_LAT_LO", 1.0),
    ("perennial_ice", "snow_ramp_lat_hi", snow, "RAMP_LAT_HI", 89.0),
    ("perennial_ice", "snow_ramp_low_min", snow, "RAMP_LOW_MIN", 0.01),
    ("perennial_ice", "snow_ramp_low_max", snow, "RAMP_LOW_MAX", 0.99),
    ("sea_ice", "ice_rgb", palette, "ICE_RGB", (1, 2, 3)),
    ("sea_ice", "ice_shadow_rgb", palette, "ICE_SHADOW_RGB", (1, 2, 3)),
    ("sea_ice", "ice_lo", seaice, "ICE_LO", 0.99),
    ("sea_ice", "ice_band", seaice, "ICE_BAND", 0.99),
    ("sea_ice", "ice_max_alpha", seaice, "ICE_MAX_ALPHA", 0.99),
    ("sea_ice", "sh_ice_lo", seaice, "SH_ICE_LO", 0.99),
    ("sea_ice", "sh_ice_max_alpha", seaice, "SH_ICE_MAX_ALPHA", 0.99),
    ("lake_depth", "lake_max_m", palette, "LAKE_MAX_M", 99.0),
    ("lake_depth", "lake_stops", palette, "LAKE_STOPS", []),
]

GATED_CASE = ("layer", "key", "module", "attr", "value")


def _recipe(body, rasters=WHOLE_PLANET):
    return json.loads(shade_planet.composite_params({None: None}, body, rasters))


class TestABodyRecordsOnlyWhatItsOwnCompositeReads:
    """One body's re-tune must not restage another's composite.

    A recipe is compared whole, so a key a body cannot reach still restages it when that key's
    value moves — `Body.surface_layers` decides what the paint evaluates, so it decides what the
    record carries.
    """

    def test_the_table_is_not_vacuous(self):
        """Anti-vacuity, and the contract every parametrised case below leans on."""
        named = {layer for layer, *_ in LAYER_GATED}
        assert named, "the gated-group table is empty — every case below would pass on nothing"
        assert named <= bodies.COMPOSITE_LAYERS
        assert named <= bodies.EARTH.surface_layers, "Earth must paint every layer named here"
        assert not (named & bodies.MARS.surface_layers), "Mars must paint none of them"

    @pytest.mark.parametrize(GATED_CASE, LAYER_GATED)
    def test_the_body_that_paints_it_records_it(self, layer, key, module, attr, value):
        assert key in _recipe(bodies.EARTH)

    @pytest.mark.parametrize(GATED_CASE, LAYER_GATED)
    def test_the_body_that_does_not_paint_it_omits_it(self, layer, key, module, attr, value):
        assert key not in _recipe(bodies.MARS)

    @pytest.mark.parametrize(GATED_CASE, LAYER_GATED)
    def test_moving_it_restages_the_body_that_paints_it(self, layer, key, module, attr, value,
                                                        monkeypatch):
        """Conditional is not untracked: with the gate open every value behind it must still move
        the recipe, or the gating has traded one silent freshness bug for another."""
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setattr(module, attr, value)
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != before

    @pytest.mark.parametrize(GATED_CASE, LAYER_GATED)
    def test_moving_it_leaves_the_other_body_alone(self, layer, key, module, attr, value,
                                                   monkeypatch):
        """THE POINT. Tuning Earth's sea ice used to restage Mars, which declares no `sea_ice`."""
        before = shade_planet.composite_params({None: None}, bodies.MARS, WHOLE_PLANET)
        monkeypatch.setattr(module, attr, value)
        assert shade_planet.composite_params({None: None}, bodies.MARS, WHOLE_PLANET) == before


class TestTheFlatWaterColourFollowsTheWatermask:
    """Gated on a RASTER rather than a layer: inland water is filled with this colour, and the
    mask is what selects the pixels it fills."""

    def test_a_planet_with_a_watermask_records_it(self):
        assert "water_rgb" in _recipe(bodies.EARTH)

    def test_a_planet_without_one_does_not(self):
        assert "water_rgb" not in _recipe(bodies.MARS, frozenset({"heightfield"}))

    def test_moving_it_leaves_that_planet_alone(self, monkeypatch):
        rasters = frozenset({"heightfield"})
        before = shade_planet.composite_params({None: None}, bodies.MARS, rasters)
        monkeypatch.setattr(palette, "WATER_RGB", (1, 2, 3))
        assert shade_planet.composite_params({None: None}, bodies.MARS, rasters) == before


class TestTheShadowTintRidesInTheRecipe:
    """It multiplies shaded land on every body, so an edit reaching no recipe left the composite
    falsely fresh — the untracked-constant trap, not a body-scoped one."""

    def test_it_is_recorded_while_the_warmth_knob_is_open(self):
        assert shade.KNOBS["shadow_warmth"] != 0.0
        assert "shadow_tint" in _recipe(bodies.EARTH)
        assert "shadow_tint" in _recipe(bodies.MARS)

    def test_changing_it_restages(self, monkeypatch):
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setattr(shade, "SHADOW_TINT", (1.0, 1.0, 1.0))
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != before

    def test_it_is_omitted_where_it_cannot_reach_a_pixel(self, monkeypatch):
        """`shadow_tint` returns exactly 1.0 at warmth 0, bit-identical to not being called."""
        monkeypatch.setitem(shade.KNOBS, "shadow_warmth", 0.0)
        assert "shadow_tint" not in _recipe(bodies.EARTH)


class TestTheKneeConstantsFollowTheCurveThatReadsThem:
    """Gated on a KNOB value: they are one branch of `snow_position`, and the knob itself rides in
    `knobs`, so selecting the branch is already a change."""

    def test_the_production_curve_does_not_record_them(self):
        assert shade.KNOBS["snow_curve"] != "knee"
        assert "knee_x" not in _recipe(bodies.EARTH)

    def test_selecting_the_branch_records_them(self, monkeypatch):
        monkeypatch.setitem(shade.KNOBS, "snow_curve", "knee")
        assert "knee_x" in _recipe(bodies.EARTH)

    def test_a_body_that_paints_no_white_still_omits_them(self, monkeypatch):
        """`snow_position` keys the snow and the sea-ice whites; a body with neither never uses
        its output whatever the curve says."""
        monkeypatch.setitem(shade.KNOBS, "snow_curve", "knee")
        assert "knee_x" not in _recipe(bodies.MARS)

    def test_moving_one_restages_only_under_that_branch(self, monkeypatch):
        before = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setattr(shade, "KNEE_X", 0.5)
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) == before
        monkeypatch.setitem(shade.KNOBS, "snow_curve", "knee")
        with_knee = shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET)
        monkeypatch.setattr(shade, "KNEE_X", 0.6)
        assert shade_planet.composite_params({None: None}, bodies.EARTH, WHOLE_PLANET) != with_knee


class TestWhyTheTwoDependencyListsDisagree:
    """`composite_deps` names inputs this body may not have; `cap_sources` names only what it opens.

    THE EXECUTABLE FORM OF THE REASON, because the asymmetry reads as an oversight and the obvious
    tidy — making the composite's list exact too — trades a harmless imprecision for a chance to
    UNDER-track, which is the silent direction. The two lists feed different predicates, and the
    tests below are the difference rather than a description of it.
    """

    def test_the_two_freshness_predicates_disagree_on_a_missing_input(self, tmp_path):
        """`is_stale` shrugs at a path that is not there; `cap_is_fresh` refuses outright. That is
        the whole reason one list can over-name its inputs and the other cannot."""
        output = _raster(tmp_path / "planet_rgb.tif", 10, 10, GRID[2])
        shade_planet.mark_done(output)
        _age(output, 100)
        _age(shade_planet.done_marker(output), 100)
        never_built = tmp_path / "seaice_3857.tif"
        assert shade_planet.is_stale(output, never_built) is False, (
            "is_stale must tolerate an input this planet never built")
        assert cap_render.cap_is_fresh(
            "recipe", [output], _written(tmp_path / "sidecar.json", "recipe"),
            [never_built]) is False, "cap_is_fresh must refuse a source that does not exist"

    def test_the_composite_names_the_masks_whatever_the_planet_declared(self):
        """Pinned so the tidy fails loudly. The gate that matters is at the READ boundary — a mask
        this planet never declared is never opened — and `rasters_off` is what makes switching one
        off restage. This list is only ever asked "what is the newest of these"."""
        deps = shade_planet.composite_deps(Path("/w"), Path("/w/hs.tif"), Path("/w/params.json"))
        assert {"ocean_3857.tif", "water_3857.tif"} <= {path.name for path in deps}
