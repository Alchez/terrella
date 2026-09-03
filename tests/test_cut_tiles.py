"""Tests for the tile cut: its freshness decision, and the recipe that feeds its command line.

The cut is the second of the two planet stages. It reads a finished `planet_rgb.tif` and knows
nothing about how that raster was filled, which is why these tests never build one.
"""

import json
import os
import time

from pipeline import bodies, freshness
from pipeline.tile import cut_tiles


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


def _built(tmp_path, name="planet_rgb.tif"):
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


class TestBuildTilesGuard:
    """build_tiles was the one unguarded stage -- it re-cut all 62k tiles on every --tiles run and
    resumed over truncated pngs. A tiles.done sentinel + tiles_are_fresh + a clean cut (no --resume)
    close both gaps. These lock the freshness decision the way TestIsStale locks is_stale.
    """

    def test_current_pyramid_is_fresh(self, tmp_path):
        planet = _built(tmp_path)
        _built_pyramid(tmp_path)
        _at(planet, 200)               # the raster finished 200 s ago...
        _at(tmp_path / "tiles", 100)   # ...tiles cut 100 s ago, so the pyramid is current
        assert cut_tiles.tiles_are_fresh(planet, tmp_path) is True

    def test_stale_when_the_raster_is_newer(self, tmp_path):
        planet = _built(tmp_path)
        _built_pyramid(tmp_path)
        _at(planet, 100)               # re-rendered 100 s ago...
        _at(tmp_path / "tiles", 200)   # ...over a pyramid cut 200 s ago -> must re-cut
        assert cut_tiles.tiles_are_fresh(planet, tmp_path) is False

    def test_stale_without_a_pyramid_marker(self, tmp_path):
        """A tiles/ dir with content but no tiles.done -- e.g. an interrupted swap -- is not fresh."""
        planet = _built(tmp_path)
        live = tmp_path / "tiles"
        (live / "0").mkdir(parents=True)
        (live / "0" / "0.png").write_text("png")
        assert cut_tiles.tiles_are_fresh(planet, tmp_path) is False

    def test_stale_when_pyramid_dir_is_empty(self, tmp_path):
        """An empty tiles/ (a half-finished swap) passes exists() but must still re-cut."""
        planet = _built(tmp_path)
        live = tmp_path / "tiles"
        live.mkdir()
        freshness.mark_done(live)
        assert cut_tiles.tiles_are_fresh(planet, tmp_path) is False

    def test_stale_when_the_raster_was_never_stamped(self, tmp_path):
        """planet_rgb.tif with no .done (a crashed render) must never read as fresh -- else the
        0.0 mtime of the missing marker would slip past is_stale and skip a needed cut."""
        planet = tmp_path / "planet_rgb.tif"
        planet.write_text("half-written")
        _built_pyramid(tmp_path)
        assert cut_tiles.tiles_are_fresh(planet, tmp_path) is False

    def test_tile_cmd_omits_resume(self, tmp_path):
        """No --resume: GDAL would skip a truncated tile by existence. --skip-blank is asserted too
        so a wrong or empty arg list would trip the check rather than pass vacuously."""
        cmd = cut_tiles._tile_cmd(tmp_path / "planet_rgb.tif", tmp_path / "tiles_new",
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
        cmd = " ".join(cut_tiles._tile_cmd(tmp_path / "planet_rgb.tif", tmp_path / "tiles_new",
                                           bodies.EARTH))
        cut = cut_tiles.tile_cut(bodies.EARTH)
        with subtests.test("format"):
            assert f"--format={cut['format']}" in cmd
        with subtests.test("quality"):
            assert f"QUALITY={cut['quality']}" in cmd
        with subtests.test("tile_size"):
            assert f"--tile-size={cut['tile_size']}" in cmd
        with subtests.test("min_zoom"):
            assert f"--min-zoom={cut['min_zoom']}" in cmd
        with subtests.test("max_zoom"):
            assert f"--max-zoom={cut['max_zoom']}" in cmd
        with subtests.test("resampling"):
            assert f"--resampling={cut['resampling']}" in cmd
        with subtests.test("overview_resampling"):
            assert f"--overview-resampling={cut['overview_resampling']}" in cmd
        with subtests.test("convention"):
            assert f"--convention={cut['convention']}" in cmd

    def test_params_serialise_the_whole_recipe(self):
        assert json.loads(cut_tiles.tile_params(bodies.EARTH)) == dict(
            cut_tiles.tile_cut(bodies.EARTH))

    def test_skip_blank_follows_the_recipe(self, tmp_path):
        """Asserted from the flag rather than the constant, so flipping it off is a real change and
        not a silently ignored field in the record."""
        cmd = cut_tiles._tile_cmd(tmp_path / "planet_rgb.tif", tmp_path / "tiles_new",
                                  bodies.EARTH)
        assert ("--skip-blank" in cmd) is cut_tiles.tile_cut(bodies.EARTH)["skip_blank"]

    def test_a_newer_recipe_restages_a_current_pyramid(self, tmp_path):
        """The whole point: raster untouched, pyramid present and stamped, recipe rewritten
        after the cut -> must re-cut. Without tile_params in the key this reads as fresh."""
        planet = _built(tmp_path)
        _built_pyramid(tmp_path)
        _at(planet, 300)
        _at(tmp_path / "tiles", 200)
        params = cut_tiles.tile_params_path(tmp_path)
        params.write_text(cut_tiles.tile_params(bodies.EARTH))
        _at(params, 100)                # recipe changed after the cut
        assert cut_tiles.tiles_are_fresh(planet, tmp_path) is False

    def test_an_older_recipe_leaves_the_pyramid_fresh(self, tmp_path):
        """The control that stops the check passing vacuously: an unchanged recipe (write_if_changed
        never moves its mtime) must NOT restage a 4:19 cut."""
        planet = _built(tmp_path)
        _built_pyramid(tmp_path)
        params = cut_tiles.tile_params_path(tmp_path)
        params.write_text(cut_tiles.tile_params(bodies.EARTH))
        _at(params, 300)
        _at(planet, 200)
        _at(tmp_path / "tiles", 100)
        assert cut_tiles.tiles_are_fresh(planet, tmp_path) is True

    def test_write_if_changed_leaves_an_identical_recipe_alone(self, tmp_path):
        """build_tiles rewrites the recipe on every run, so an unchanged one must not move its
        mtime — otherwise every --tiles invocation would restage the pyramid."""
        params = cut_tiles.tile_params_path(tmp_path)
        freshness.write_if_changed(params, cut_tiles.tile_params(bodies.EARTH))
        _age(params, 500)
        before = params.stat().st_mtime
        freshness.write_if_changed(params, cut_tiles.tile_params(bodies.EARTH))
        assert params.stat().st_mtime == before
