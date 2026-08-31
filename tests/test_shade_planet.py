"""Tests for the freshness guard that decides which planet-shading stages re-run.

The load-bearing case is `test_refused_cell_makes_the_warp_stale`: it reproduces the
Caspian miss, where re-fusing 4 of 540 chunks left every derived raster
silently stale because the old guard only asked whether the output existed.
"""

import dataclasses
import json
import os
import time
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from pipeline import bodies, freshness, mercator, planet_seam
from pipeline.look import palette
from pipeline.tile import shade_planet

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
    marker = freshness.done_marker(path)
    if marker.exists():
        os.utime(marker, (stamp, stamp))


def _built(tmp_path, name="height_3857.tif"):
    """An output that completed 100 s ago: the raster plus its .done marker."""
    out = tmp_path / name
    out.write_text("raster")
    freshness.mark_done(out)
    _age(out, 100)
    _age(freshness.done_marker(out), 100)
    return out


def _built_pyramid(tmp_path):
    """A completed tile pyramid: the tiles/ dir with a tile inside, plus its .done marker.

    Freshness turns on the .done markers, so callers set ages via `_at`; this only lays out the
    files (dir non-empty, sentinel present) that `tiles_are_fresh` inspects.
    """
    live = tmp_path / "tiles"
    (live / "0" / "0").mkdir(parents=True)
    (live / "0" / "0" / "0.png").write_text("png")
    freshness.mark_done(live)
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
        assert freshness.is_stale(tmp_path / "nope.tif") is True

    def test_completed_output_with_older_inputs_is_fresh(self, tmp_path):
        out = _built(tmp_path)
        source = tmp_path / "chunk.tif"
        source.write_text("x")
        _age(source, 500)
        assert freshness.is_stale(out, source) is False

    def test_refused_cell_makes_the_warp_stale(self, tmp_path):
        """The Caspian case: an input rewritten after the output completed."""
        out = _built(tmp_path)
        source = tmp_path / "chunk.tif"
        source.write_text("re-fused")  # written now, i.e. after the output's marker
        assert freshness.is_stale(out, source) is True

    def test_crashed_run_leaves_no_marker_and_stays_stale(self, tmp_path):
        """GDAL stamps its target at the START, so a half-written raster looks current.
        Only the .done marker distinguishes 'finished' from 'died mid-write'."""
        out = tmp_path / "height_3857.tif"
        out.write_text("half-written")
        assert freshness.is_stale(out) is True

    def test_directory_input_sees_a_rewritten_child(self, tmp_path):
        """Depending on the chunk DIR, not its VRT, is the point: re-fusing a cell never
        touches the VRT's own mtime, which is how the Caspian re-fuse hid."""
        out = _built(tmp_path)
        chunks = tmp_path / "chunks"
        (chunks / "e050_n40").mkdir(parents=True)
        cell = chunks / "e050_n40" / "heightfield_10s.tif"
        cell.write_text("re-fused")
        assert freshness.is_stale(out, chunks) is True


class TestGridMatches:
    """The dimension/bounds guard that keeps a same-source raster from sitting falsely fresh after a
    re-fuse GROWS the planet grid under it -- the Antarctica precondition (93009 -> 131072 rows). A
    plain mtime test cannot see this: the raster's SOURCE never moved."""

    def test_same_grid_matches(self, tmp_path):
        out = _raster(tmp_path / "ocean_3857.tif", 10, 10, (0.0, 0.0, 100.0, 100.0))
        assert freshness.grid_matches(out, *GRID) is True

    def test_fewer_rows_does_not_match(self, tmp_path):
        """The exact Antarctica case: the planet gained rows at the bottom, but this raster's source
        never changed, so it still sits at the old, shorter row count."""
        out = _raster(tmp_path / "lakedepth_3857.tif", 10, 9, (0.0, 10.0, 100.0, 100.0))
        assert freshness.grid_matches(out, *GRID) is False

    def test_different_width_does_not_match(self, tmp_path):
        out = _raster(tmp_path / "water_3857.tif", 9, 10, (0.0, 0.0, 90.0, 100.0))
        assert freshness.grid_matches(out, *GRID) is False

    def test_shifted_bounds_at_matching_dimensions_does_not_match(self, tmp_path):
        """Companion: same pixel count, shifted origin -- so the check cannot be dimensions alone.
        The 1 m tolerance sits far below a 305 m pixel, so a real grid shift always trips it."""
        out = _raster(tmp_path / "seaice_3857.tif", 10, 10, (5000.0, 5000.0, 105000.0, 105000.0))
        assert freshness.grid_matches(out, *GRID) is False

    def test_missing_file_does_not_match(self, tmp_path):
        assert freshness.grid_matches(tmp_path / "nope.tif", *GRID) is False


class TestWarpNeedsRebuild:
    """The composed decision warp_inputs uses for every 3857 raster below height: rebuild on a moved
    source (is_stale) OR a resized grid (grid_matches). The second is the Antarctica case and is
    invisible to mtimes alone -- pinned here so removing the grid term fails a test, not just a pass.
    """

    def _target(self, tmp_path, name, width, height, bounds, age=100):
        """A completed warp target `age` s ago: the real raster plus its .done marker, both aged."""
        out = _raster(tmp_path / name, width, height, bounds)
        freshness.mark_done(out)
        _age(out, age)
        _age(freshness.done_marker(out), age)
        return out

    def test_fresh_source_on_grid_skips(self, tmp_path):
        out = self._target(tmp_path, "ocean_3857.tif", 10, 10, (0.0, 0.0, 100.0, 100.0))
        source = tmp_path / "planet_oceanmask.vrt"
        source.write_text("vrt")
        _age(source, 500)  # older than the output -> not stale
        assert freshness.warp_needs_rebuild(out, GRID, source) is False

    def test_fresh_source_off_grid_rebuilds(self, tmp_path):
        """THE load-bearing case: the source is older than the output (is_stale is False), but the
        planet grew under it -- only the grid term catches it, so it MUST rebuild."""
        out = self._target(tmp_path, "lakedepth_3857.tif", 10, 9, (0.0, 10.0, 100.0, 100.0))
        source = tmp_path / "lakedepth.vrt"
        source.write_text("vrt")
        _age(source, 500)
        assert freshness.is_stale(out, source) is False, "the source alone must look fresh"
        assert freshness.warp_needs_rebuild(out, GRID, source) is True

    def test_moved_source_on_grid_rebuilds(self, tmp_path):
        """The is_stale half still fires: a re-released source newer than the output rebuilds even
        when the grid is unchanged."""
        out = self._target(tmp_path, "seaice_3857.tif", 10, 10, (0.0, 0.0, 100.0, 100.0))
        source = tmp_path / "seaice.nc"
        source.write_text("re-released")  # written now -> newer than the output's marker
        assert freshness.warp_needs_rebuild(out, GRID, source) is True


class TestAMarkerMustBeNewerThanTheBytesItVouchesFor:
    """The third freshness question, and the one that shipped a planet with an empty ice layer.

    A `.done` marker from an EARLIER successful run keeps vouching after a later run overwrites the
    output and dies. Mars's ice alpha was rebuilt onto the z7 grid, crashed in its first unit burn,
    and the next pass skipped it: the marker existed, and `grid_matches` passed precisely BECAUSE
    the crash had created a full-size target on the new grid. The result was 0 non-zero pixels in
    4.29 billion, with every gate green.
    """

    def _completed(self, tmp_path, age=100):
        out = tmp_path / "snow_persistence_3857.tif"
        out.write_text("the run that finished")
        freshness.mark_done(out)
        _age(out, age)
        _age(freshness.done_marker(out), age)
        return out

    def test_an_output_rewritten_after_its_marker_is_stale(self, tmp_path):
        """THE CASE ITSELF: a completed output, overwritten later by a run that never finished."""
        out = self._completed(tmp_path)
        source = tmp_path / "viking.tif"
        source.write_text("source")
        _age(source, 500)
        assert freshness.is_stale(out, source) is False, "the setup must start out fresh"
        out.write_text("a crashed rewrite, full size and empty")  # newer than the marker now
        assert freshness.is_stale(out, source) is True

    def test_equal_stamps_are_fresh(self, tmp_path):
        """The boundary, and it has to fall this way: a stage marks done AFTER it writes, so on a
        coarse-granularity clock the two land on the same stamp and that is the SUCCESS case."""
        out = self._completed(tmp_path)
        stamped = freshness.done_marker(out).stat().st_mtime
        os.utime(out, (stamped, stamped))
        assert freshness.is_stale(out) is False

    def test_a_marker_older_than_its_output_beats_a_matching_grid(self, tmp_path):
        """Why the other two guards did not save it: `warp_needs_rebuild` ORs them, and the crash
        left the geometry correct, so the grid term voted fresh exactly when it mattered."""
        out = _raster(tmp_path / "snow_persistence_3857.tif", 10, 10, GRID[2])
        freshness.mark_done(out)
        _age(freshness.done_marker(out), 100)
        assert freshness.grid_matches(out, *GRID) is True, "the crash leaves the grid RIGHT"
        assert freshness.warp_needs_rebuild(out, GRID, tmp_path / "src.vrt") is True


class TestReferenceNeedsRebuild:
    """The mirror of the class above, for the raster every one of those takes its grid FROM.

    `warp_needs_rebuild` catches a raster left behind when the grid moved. Nothing caught the
    reverse: `height_3857.tif` unchanged at the wrong SCALE. Its inputs are a VRT and a chunk
    directory, and neither moves when a body's tile ceiling does, so raising Mars z6 -> z7 left a
    32768 square grid reading fresh and the pass began cutting a z7 pyramid out of z6 pixels.
    """

    #: The pixel size of `GRID` — 100 map units across 10 pixels. Named rather than inlined so a
    #: reader can see the mismatched values below are a doubling and a halving of one number.
    RESOLUTION = 10.0

    def _reference(self, tmp_path, width, height, bounds, age=100):
        """A completed reference raster `age` s ago: the real raster plus its .done marker, aged."""
        out = _raster(tmp_path / "height_3857.tif", width, height, bounds)
        freshness.mark_done(out)
        _age(out, age)
        _age(freshness.done_marker(out), age)
        return out

    def test_a_matching_pixel_size_is_a_match(self, tmp_path):
        out = self._reference(tmp_path, 10, 10, (0.0, 0.0, 100.0, 100.0))
        assert freshness.resolution_matches(out, self.RESOLUTION) is True

    def test_a_doubled_pixel_size_is_not(self, tmp_path):
        """A ceiling raised by one rung halves the pixel; the raster on disk still holds the old one."""
        out = self._reference(tmp_path, 5, 5, (0.0, 0.0, 100.0, 100.0))
        assert freshness.resolution_matches(out, self.RESOLUTION) is False

    def test_a_raster_square_in_pixels_but_not_in_scale_is_not(self, tmp_path):
        """Both axes are asked, so a target that is square in COUNT but not in SCALE cannot pass."""
        out = self._reference(tmp_path, 10, 10, (0.0, 0.0, 100.0, 50.0))
        assert freshness.resolution_matches(out, self.RESOLUTION) is False

    def test_an_absent_raster_is_not(self, tmp_path):
        assert freshness.resolution_matches(tmp_path / "nope.tif", self.RESOLUTION) is False

    def test_fresh_source_at_the_right_scale_skips(self, tmp_path):
        out = self._reference(tmp_path, 10, 10, (0.0, 0.0, 100.0, 100.0))
        source = tmp_path / "planet_heightfield.vrt"
        source.write_text("vrt")
        _age(source, 500)  # older than the output -> not stale
        assert freshness.reference_needs_rebuild(out, self.RESOLUTION, source) is False

    def test_fresh_source_at_the_wrong_scale_rebuilds(self, tmp_path):
        """THE load-bearing case, and the bug itself: the source is older than the output, so
        `is_stale` says fresh, and only the resolution term sees that the ceiling moved."""
        out = self._reference(tmp_path, 5, 5, (0.0, 0.0, 100.0, 100.0))
        source = tmp_path / "planet_heightfield.vrt"
        source.write_text("vrt")
        _age(source, 500)
        assert freshness.is_stale(out, source) is False, "the source alone must look fresh"
        assert freshness.reference_needs_rebuild(out, self.RESOLUTION, source) is True

    def test_moved_source_at_the_right_scale_rebuilds(self, tmp_path):
        """The is_stale half still fires, so the new term added a reason rather than replacing one."""
        out = self._reference(tmp_path, 10, 10, (0.0, 0.0, 100.0, 100.0))
        source = tmp_path / "planet_heightfield.vrt"
        source.write_text("re-fused")  # written now -> newer than the output's marker
        assert freshness.reference_needs_rebuild(out, self.RESOLUTION, source) is True


def test_the_reference_raster_is_not_gated_on_mtimes_alone() -> None:
    """A scan, because the call site reverting is invisible to every test above.

    The functions can be perfect and the pass still wrong: what produced the z6-grid-at-z7 defect
    was one call asking the cheaper question. `TestReferenceNeedsRebuild` pins the decision;
    this pins that `warp_inputs` is the thing making it.
    """
    source = Path(shade_planet.__file__).read_text(encoding="utf-8")  # pyright: ignore[reportArgumentType]
    assert "reference_needs_rebuild(height" in source, (
        "the height warp is gated on mtimes alone again — its inputs do not move when a body's "
        "ceiling does, so the pass will cut the new pyramid out of the old grid and raise nothing"
    )


class TestWriteIfChanged:
    def test_identical_content_leaves_mtime_alone(self, tmp_path):
        """Load-bearing: an unchanged palette must NOT invalidate a 31 GB raster."""
        path = tmp_path / "ramp_sea.txt"
        path.write_text("0.00 133 185 183\n")
        _age(path, 500)
        before = path.stat().st_mtime
        freshness.write_if_changed(path, "0.00 133 185 183\n")
        assert path.stat().st_mtime == before

    def test_changed_content_moves_mtime(self, tmp_path):
        path = tmp_path / "ramp_sea.txt"
        path.write_text("0.00 133 185 183\n")
        _age(path, 500)
        before = path.stat().st_mtime
        freshness.write_if_changed(path, "0.00 142 198 196\n")
        assert path.stat().st_mtime > before

    def test_absent_file_is_written(self, tmp_path):
        path = freshness.write_if_changed(tmp_path / "new.json", "{}")
        assert path.read_text() == "{}"


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
        freshness.mark_done(live)
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
        freshness.write_if_changed(params, shade_planet.tile_params(bodies.EARTH))
        _age(params, 500)
        before = params.stat().st_mtime
        freshness.write_if_changed(params, shade_planet.tile_params(bodies.EARTH))
        assert params.stat().st_mtime == before


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
        # On THIS body's pixel size, not GRID's: the warp gate asks the reference raster its own
        # scale, so a fixture at a made-up resolution would re-warp height and record a gdalwarp
        # call these tests read as a mask being warped.
        span = 10 * self.BARE.map_units_per_pixel
        height = _raster(work / "height_3857.tif", 10, 10, (0.0, 0.0, span, span))
        freshness.mark_done(height)
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

    def test_the_wrap_seam_is_closed_on_a_height_the_warp_did_not_rebuild(
            self, tmp_path, monkeypatch):
        """THE GUARD AGAINST THE FILL BEING GATED ON A RE-WARP.

        Every planet already on disk was warped before this stage learned to close the seam, so the
        one case that matters is the one where `reference_needs_rebuild` says no. A fill placed
        inside that branch is invisible in every test that lets the warp run, passes review, and
        leaves every existing body exactly as broken while the code reads as fixed.

        The re-stamp is asserted with it, because filling the raster and NOT restaging is the same
        defect wearing a different hat: the hillshade and the composite both key on this marker, so
        without it they keep the cliff and the darkest-stop column they derived from the hole.
        """
        work, planet = tmp_path / "work", tmp_path / "planet"
        work.mkdir()
        planet.mkdir()
        # THE BODY IS DERIVED FROM THE FIXTURE, not the other way round. The fill needs global
        # bounds and the warp gate needs the raster to be at the body's own pixel size, and at any
        # real body's resolution those two together mean a 131072-wide raster. A body whose pixel is
        # an eighth of the world satisfies both at 8 px, and neither condition is weakened by it.
        side = 8
        span = 2 * mercator.MERCATOR_HALF_M
        body = dataclasses.replace(self.BARE, map_units_per_pixel=span / side)
        height = work / "height_3857.tif"
        array = np.zeros((side, side), dtype=np.float32)
        array[:, 0] = 1000.0
        array[:, -2] = -4000.0
        array[:, -1] = -32768.0
        with rasterio.open(height, "w", driver="GTiff", width=side, height=side, count=1,
                           dtype="float32", crs="EPSG:3857", nodata=-32768.0,
                           transform=from_bounds(-span / 2, -span / 2, span / 2, span / 2,
                                                 side, side)) as dataset:  # pyright: ignore[reportCallIssue]
            dataset.write(array, 1)
        freshness.mark_done(height)
        marker_before = freshness.done_marker(height).stat().st_mtime_ns
        for raster in planet_seam.PLANET_RASTERS:
            source = planet / f"planet_{raster}.vrt"
            source.write_text("vrt")
            _age(source, 500)
        commands: list[list[str]] = []
        monkeypatch.setattr(shade_planet, "_run", lambda cmd: commands.append([str(p) for p in cmd]))

        shade_planet.warp_inputs(work, planet, body, frozenset({"heightfield"}))

        assert commands == [], "the warp re-ran, so this fixture never exercised the skip path"
        with rasterio.open(height) as dataset:
            assert dataset.nodata is None
            closed = dataset.read(1)
        assert closed[:, -1] == pytest.approx(-1500.0), (
            "the seam was left at its sentinel because the fill was gated on a re-warp"
        )
        assert freshness.done_marker(height).stat().st_mtime_ns != marker_before, (
            "the height changed and nothing downstream was told to rebuild"
        )

    def test_the_two_masks_are_gated_separately(self, tmp_path, monkeypatch):
        """Not a pair: Phase 2's chosen shoreline contour gives a body an ocean mask while it still
        has no inland water, and that combination must not need a code change."""
        commands = self._drive(tmp_path, monkeypatch, frozenset({"heightfield", "oceanmask"}))
        warped = {command[-1].rsplit("/", 1)[-1] for command in commands}
        assert warped == {"ocean_3857.tif"}


#: EVERY COMPOSITE-RECIPE CLASS BELOW THIS POINT WENT WITH `composite_params` AND `composite_deps`.
#: They pinned which look constants a body's own recipe recorded, which it omitted, and why the two
#: dependency lists disagree — all of it about a producer that no longer exists. The rules they
#: encoded are not lost: `block_render.params` and `cap_raytrace.params` make the same claims for
#: the producers that ship, and `test_block_render` and `test_cap_raytrace` hold them.



