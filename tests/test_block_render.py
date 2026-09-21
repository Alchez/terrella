"""The block runner: what its resume trusts, what its recipe can see, and what it refuses to do.

Every guard here is about a claim that is silent when it is wrong. A resume that trusts the wrong
markers re-renders nothing and republishes last week's pixels; a recipe that cannot see a constant
leaves a stale planet reading fresh forever; a mosaic stamped complete while it is half written
sends the tile cut at a planet that is half one producer and half the other. None of those raise.
"""

import dataclasses
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import numpy as np
import pytest
import rasterio
from conftest import declare_planet_rasters
from rasterio.transform import from_bounds

from pipeline import (
    block_plan,
    bodies,
    freshness,
    layers,
    mercator,
    planet_seam,
    planet_warp,
)
from pipeline.block_plan import Block
from pipeline.look import layer_producers, palette, seaice, snow
from pipeline.raster_io import GTIFF_CREATE
from pipeline.render import prep_block
from pipeline.tile import (
    block_freshness,
    block_render,
    cut_tiles,
    relief_scan,
)


def _block(row_index, col_index, context=block_plan.DENOISE_BAND_PX):
    edge = block_plan.RENDER_BLOCK_PX
    return Block(col0=col_index * edge, row0=row_index * edge, size_px=edge, context_px=context)


def _stale_by_a_second(path):
    """Age `path` so a later touch is unambiguously newer than it.

    Whole seconds because a filesystem's mtime granularity is not promised finer, and a same-second
    write is exactly the case that made a sabotage verdict flip-flop once already.
    """
    stamp = time.time() - 2
    os.utime(path, (stamp, stamp))


class TestTheInternalTilingDividesTheBlock:
    """THE ALIGNMENT THAT MAKES THE SHARED-MOSAIC WRITE SAFE, pinned instead of left a coincidence.

    Two independent 512s make it true — the render block's edge and the GTiff's internal tile — and
    nothing tied them. Straddling internal tiles means every block write decompresses, modifies and
    recompresses pixels its neighbours own, and a rewritten tile that grows cannot go back in place,
    so a random-order pass fragments an eleven-gigabyte raster. It stops being a performance
    question and becomes a correctness one the moment two blocks are written concurrently.
    """

    def test_a_render_block_is_a_whole_number_of_internal_tiles(self):
        assert GTIFF_CREATE["blockxsize"] == GTIFF_CREATE["blockysize"]
        assert block_plan.RENDER_BLOCK_PX % GTIFF_CREATE["blockxsize"] == 0

    def test_the_mosaic_takes_its_tiling_from_the_one_owner(self):
        """The runner must not spell its own 512: a creation option written here would be a third
        copy, free to drift from the two the alignment above is between."""
        source = (block_render.__file__).replace(".pyc", ".py")
        with open(source) as handle:
            text = handle.read()
        assert "blockxsize" not in text
        assert "GTIFF_CREATE" in text


class TestTheBlockNameIsItsPlaceOnTheGrid:

    def test_the_name_is_the_block_index_and_not_the_pixel_origin(self):
        assert block_render.block_name(_block(0, 0)) == "r00c00"
        assert block_render.block_name(_block(63, 63)) == "r63c63"

    def test_every_block_of_a_grid_gets_its_own_name(self):
        """A collision would silently let one block's marker vouch for another's pixels."""
        blocks = [_block(row, column) for row in range(8) for column in range(8)]
        assert len({block_render.block_name(block) for block in blocks}) == len(blocks)


class TestAMarkerSaysWhatItsBlockWasRenderedFrom:
    """A marker is not an mtime test, and this is what would go wrong if it were.

    `is_stale`'s load-bearing clause is that an output rewritten since its stamp is stale, which
    catches a crashed half-written raster. Every block lands in one shared mosaic whose mtime
    advances with every later block, so that clause calls a healthy resume stale on its second block
    and re-renders the planet from the top, every time. What a marker carries instead is a digest of
    the ground and the settings its block was rendered from, about which no mtime can be wrong.
    """

    def test_a_marker_carrying_no_digest_vouches_for_nothing(self, tmp_path):
        """A marker from before the digest existed, and the direction this has to fail in: it
        cannot say what it was rendered from, so its block renders again rather than shipping."""
        (tmp_path / "r00c00").write_text("context 128 traced 4224 plane 4352 BASE_GRID fitted\n")
        assert block_freshness.marker_digest(tmp_path / "r00c00") is None

    def test_a_missing_marker_vouches_for_nothing_either(self, tmp_path):
        assert block_freshness.marker_digest(tmp_path / "r00c00") is None

    def test_what_a_render_writes_is_what_a_resume_reads(self, tmp_path):
        """One writer and one reader, because a second writer would be free to leave the digest off
        and every block it wrote would re-render for good."""
        block_render.write_marker(tmp_path, _block(0, 0), "abc123", "BASE_GRID fitted")
        assert block_freshness.marker_digest(tmp_path / "r00c00") == "abc123"

    def test_the_widths_the_block_rendered_at_are_still_recorded(self, tmp_path):
        """The three widths are not interchangeable, and the marker is the only record of which one
        a finished block used, so the digest is added to that line rather than replacing it."""
        block = _block(0, 0)
        block_render.write_marker(tmp_path, block, "abc123", "BASE_GRID fitted")
        written = (tmp_path / "r00c00").read_text()
        assert f"context {block.context_px}" in written
        assert f"plane {block.plane_edge_px}" in written
        assert f"traced {block.traced_edge_px}" in written

    def test_is_stale_would_call_a_healthy_resume_stale(self, tmp_path):
        """The positive control for the paragraph above: the rejected predicate on the state a
        resume is actually in. Without it that paragraph is an assertion about code nobody ran."""
        markers, dependency = tmp_path / "blocks", tmp_path / "recipe.json"
        markers.mkdir()
        dependency.write_text("{}")
        _stale_by_a_second(dependency)
        freshness.mark_done(markers)
        _stale_by_a_second(freshness.done_marker(markers))
        (markers / "r00c00").write_text("margin 0\n")
        assert freshness.is_stale(markers, dependency)


class TestASettingsMoveStillRestagesEveryBlock:
    """Narrowing a setting to the blocks it reaches is a separate act with its own evidence, and a
    run that guessed at the reach would skip blocks on a guess. So the recipe reaches every block's
    digest whole, and a look change is still a whole planet."""

    def test_a_look_constant_moving_restages_the_whole_grid(self, tmp_path, monkeypatch):
        _drive_small_planet(tmp_path, monkeypatch)
        _age_everything(tmp_path)
        monkeypatch.setattr(palette, "SNOW_RGB", (1, 2, 3))
        assert len(_drive_small_planet(tmp_path, monkeypatch)) == 16

    def test_the_recipe_reaches_a_digest_even_with_no_rasters_at_all(self):
        """The mechanism on its own, so a fix that satisfied the run-level test by moving a raster
        cannot leave this in place."""
        block = _block(0, 0)
        assert (block_freshness.block_digest(block, "one", {})
                != block_freshness.block_digest(block, "two", {}))


class TestARunUnstampsTheMosaicBeforeItWritesAPixel:
    """The order the pyramid depends on. `tiles_are_fresh` keys on the mosaic's `.done` marker, so a
    mosaic left stamped while it is rewritten block by block would let a cut run against a planet
    that is part one pass and part the next, with every gate green."""

    def test_the_stamp_is_gone_while_blocks_are_being_written(self, tmp_path, monkeypatch):
        _drive_small_planet(tmp_path, monkeypatch)
        _age_everything(tmp_path)
        _paint(tmp_path / planet_warp.HEIGHT_3857, 96, 96)
        stamped: list[bool] = []
        _drive_small_planet(tmp_path, monkeypatch,
                            observe=lambda mosaic, markers: stamped.append(
                                freshness.done_marker(mosaic).exists()))
        assert stamped == [False]

    def test_a_finished_run_stamps_it_again(self, tmp_path, monkeypatch):
        """The control. A run that merely stopped stamping would satisfy the test above and leave
        every later cut refusing a planet that is complete."""
        _drive_small_planet(tmp_path, monkeypatch)
        assert freshness.done_marker((tmp_path / cut_tiles.PLANET_RGB).resolve()).exists()

    def test_a_block_that_failed_leaves_the_planet_unstamped(self, tmp_path, monkeypatch):
        """A failed block keeps whatever marker its last render wrote, and that marker describes
        ground that has since moved.

        Counting markers rather than comparing them stamps a planet complete with a stale block in
        it, which no later run re-renders and no gate can see. The whole-set clear this replaced
        could count them safely, having just deleted every one.
        """
        _drive_small_planet(tmp_path, monkeypatch)
        _age_everything(tmp_path)
        _paint(tmp_path / planet_warp.HEIGHT_3857, 96, 96)
        mosaic = (tmp_path / cut_tiles.PLANET_RGB).resolve()
        assert _drive_small_planet(tmp_path, monkeypatch, fails={"r01c01"}) == ["r01c01"]
        assert not freshness.done_marker(mosaic).exists()


class TestTheMarkersFollowTheMosaicTheyDescribe:
    """A run pointed at a second raster keeps its own markers, or the two resume over each other —
    which is how an A/B silently inherits the production run's finished blocks."""

    def test_two_mosaics_do_not_share_a_marker_directory(self, tmp_path):
        first = block_render.markers_in(tmp_path / "planet_rgb.tif")
        second = block_render.markers_in(tmp_path / "planet_rgb_raytrace.tif")
        assert first != second

    def test_the_markers_sit_beside_the_raster(self, tmp_path):
        assert block_render.markers_in(tmp_path / "planet_rgb.tif").parent == tmp_path


class TestASecondMosaicOwnsEverySidecarThatDescribesIt:
    """The markers above follow the mosaic; the recipe, the progress document and the producer
    declaration do not, and they decide whether the raster they are keyed on is still correct.

    The price is the whole planet, and it is silent. The recipe reaches every block's digest, so an
    A/B moves it, the next production pass moves it back, and every marker disagrees with the block
    it describes: a night of Cycles to emit the pixels already on disk. The line the runner logs for
    that is true and reads as ordinary operation.

    So `--mosaic` protects a shipping planet's PIXELS and nothing else, while its own help text
    offers it for "an A/B, or a first pass that must not overwrite a shipping planet".
    """

    def _ab(self, tmp_path):
        return tmp_path / "planet_rgb_ab.tif"

    def test_the_shipping_planet_re_renders_nothing_after_an_ab(self, tmp_path, monkeypatch):
        """The oracle for the whole seam, and the only one priced in hours.

        The A/B plans a different grid because a run with nothing different about it is not an A/B;
        that difference reaches `params`, which is what moves the recipe. Aged between runs so the
        verdict comes from what a run WROTE rather than from the order the fixture happened to
        create files in.
        """
        first = _drive_planet(tmp_path, monkeypatch, blocks=3)
        assert first.rendered == 3 and freshness.done_marker(first.mosaic).exists()
        _age_everything(tmp_path)
        _drive_planet(tmp_path, monkeypatch, mosaic=self._ab(tmp_path), blocks=4)
        _age_everything(tmp_path)
        again = _drive_planet(tmp_path, monkeypatch, blocks=3)
        assert again.rendered == 0 and again.attempted == []

    def test_an_ab_does_not_move_the_shipping_planets_recipe(self, tmp_path, monkeypatch):
        """The direct cause of the test above, asserted on its own so that a fix which satisfies
        the oracle some other way cannot leave this in place."""
        _drive_planet(tmp_path, monkeypatch, blocks=3)
        _age_everything(tmp_path)
        recipe = tmp_path / block_render.PARAMS_NAME
        before = recipe.read_text(), recipe.stat().st_mtime
        _drive_planet(tmp_path, monkeypatch, mosaic=self._ab(tmp_path), blocks=4)
        assert (recipe.read_text(), recipe.stat().st_mtime) == before

    def test_each_run_reports_its_own_progress(self, tmp_path, monkeypatch):
        """`raytrace_status.json` is the point of contact for a night's watcher, and two runs
        sharing one leaves the second answering for the first. Nothing gates on its mtime, so this
        costs no render either way; what it costs is a wrong answer to "how is the pass going".
        """
        first = _drive_planet(tmp_path, monkeypatch, blocks=3)
        status = tmp_path / block_render.STATUS_NAME
        assert json.loads(status.read_text())["mosaic"] == str(first.mosaic)
        _drive_planet(tmp_path, monkeypatch, mosaic=self._ab(tmp_path), blocks=4)
        assert json.loads(status.read_text())["mosaic"] == str(first.mosaic)

    def test_the_scratch_sits_beside_the_raster_it_fills(self, tmp_path, monkeypatch):
        """The disk guard already assumes it does. `free_bytes(mosaic.parent)` measures the
        mosaic's filesystem, while the scratch it is sizing was opened in the work directory, so a
        `--mosaic` on another volume leaves the run guarding the wrong one."""
        elsewhere = tmp_path / "ab"
        run = _drive_planet(tmp_path, monkeypatch, blocks=2,
                            mosaic=elsewhere / "planet_rgb_ab.tif")
        assert {scratch.parent for scratch in run.scratches} == {elsewhere.resolve()}

    def test_the_canonical_raster_is_canonical_however_it_is_spelled(self, tmp_path):
        """A run handed the shipping raster by another name is still the shipping run, and the arm
        worktrees can hand it one: they drive against a symlinked work directory.

        Read as a second raster it would take a recipe of its own while sharing the markers and the
        bytes, which leaves the shipping planet fresh under a recipe describing nothing — the same
        failure as the tests above, arriving from the opposite direction.
        """
        (tmp_path / "sub").mkdir()
        spelled = tmp_path / "sub" / ".." / cut_tiles.PLANET_RGB
        sidecars = block_render.sidecars_for(tmp_path, spelled)
        assert sidecars.canonical
        assert sidecars.recipe == tmp_path.resolve() / block_render.PARAMS_NAME
        assert sidecars.markers == block_render.markers_in(block_render.mosaic_in(tmp_path))

    def test_the_shipping_raster_keeps_the_bare_sidecar_names(self, tmp_path, monkeypatch):
        """A PIN ON THE NAMING RATHER THAN A DEFECT, and the reason the fix above costs nothing.

        Naming every mosaic's sidecar after its stem is the tidier rule and renames the two files
        the finished Earth pass left on disk, which moves an mtime — the same night this class
        exists to prevent, paid once on the way in. So the canonical raster's name elides, as
        the compositor's default variant and `capsManifestUrl`'s empty prefix both already did.
        """
        _drive_planet(tmp_path, monkeypatch, blocks=2)
        assert (tmp_path / block_render.PARAMS_NAME).exists()
        assert (tmp_path / block_render.STATUS_NAME).exists()


class TestTheWorkDirectoryReachesTheBlocksAndNotJustTheChecks:
    """`--mosaic`'s defect one flag over, and this one moved the READS rather than the sidecars.

    `run` validates its inputs, plans its blocks and stamps its freshness under the directory it was
    handed, then handed the renderer nothing: the prep resolved this body's default stage directory
    itself and cut every block's pixels from there. So a run pointed at a second store checks one
    planet and renders another, and the mosaic records it complete.

    The prep's own half of this seam is `test_prep_block`'s; this is the half that carries it.
    """

    def test_the_renderer_is_handed_the_directory_the_run_was_given(self, tmp_path, monkeypatch):
        """Discriminating because the harness never patches `paths.DATA`: the default this used to
        re-derive is the real store, which is not `tmp_path` under any run of this suite."""
        run = _drive_planet(tmp_path, monkeypatch, blocks=2)
        assert run.cut_from == {tmp_path}

    def test_the_default_is_resolved_through_the_stages_one_owner(self, monkeypatch):
        """The CLI's half. `--work` absent must land on the same directory the relief scan, the
        pack and the terrain cut all resolve, or the flag's default and the pipeline's disagree."""
        captured = {}
        monkeypatch.setattr(block_render, "run",
                            lambda body, work, mosaic, **kwargs: captured.update(work=work))
        block_render.main(["--body", "earth"])
        assert captured["work"] == relief_scan.work_dir(bodies.EARTH)


class TestTheInputSetIsExactlyWhatTheRaytraceReads:
    """The set must name what Cycles actually consumes and nothing it merely inherited.

    A sibling test was deleted here and its absence is the point. It asserted that
    `composite_params.json` was not a dependency, which no longer distinguishes anything: the
    compositor is gone, so nothing can put that name in the set and the assertion passes for a
    reason that has nothing to do with the claim. The hillshade test below survives it because a
    mutation case still plants `hs_3857` back into this set and this is what catches it.
    """

    def _inputs(self, tmp_path, body=bodies.EARTH):
        return block_freshness.inputs_for(tmp_path, body, planet_seam.KNOWN_RASTERS)

    def test_the_hillshade_is_not_an_input(self, tmp_path):
        """Cycles computes its own light; `hs_3857` reaches no raytraced pixel."""
        assert not any(name == "hs" or name.startswith("hs_")
                       for name in self._inputs(tmp_path))

    def test_the_warped_inputs_the_prep_cuts_from_are_all_tracked(self, tmp_path):
        """The block prep reads exactly these, so a re-warp, a re-fuse, a new NSIDC or RGI, moves
        the ground under every block that reads it."""
        inputs = set(self._inputs(tmp_path).values())
        for name in (planet_warp.HEIGHT_3857, planet_warp.OCEAN_3857, planet_warp.WATER_3857):
            assert tmp_path / name in inputs
        for layer in layers.warped_for(layers.BLOCK_LAYERS):
            if layer.name in bodies.EARTH.surface_layers:
                assert layer.warped_in(tmp_path) in inputs
        # The other direction, and it is the one that is silent: a set built from the composite's
        # would move every block's digest when a layer this tier cannot read moves.
        for layer in layers.LAYERS:
            if layer.warped_basename and layer.name not in layers.BLOCK_LAYERS:
                assert layer.warped_in(tmp_path) not in inputs

    def test_a_layer_this_body_does_not_paint_is_not_one_of_its_inputs(self, tmp_path):
        """The narrowing, which the mtime set did not have and could afford not to have: an
        over-inclusive list cost nothing against a newest-mtime, and against a digest it re-renders
        a planet for a raster the prep never opens."""
        painted = {layer.warped_in(tmp_path)
                   for layer in layers.warped_for(layers.BLOCK_LAYERS)
                   if layer.name not in bodies.MARS.surface_layers}
        assert painted, "Earth and Mars paint the same layers, so this test measures nothing"
        assert not painted & set(self._inputs(tmp_path, bodies.MARS).values())

    def test_a_raster_the_seam_does_not_declare_is_not_an_input(self, tmp_path):
        """A body with no inland water is never asked for a water mask, which is the seam's own
        rule rather than a `Path.exists()` sweep."""
        thin = block_freshness.inputs_for(tmp_path, bodies.MARS, frozenset({"heightfield"}))
        assert planet_warp.WATER_3857 not in thin and planet_warp.OCEAN_3857 not in thin
        assert planet_warp.HEIGHT_3857 in thin


class TestTheRecipeSeesWhatNoMtimeCan:

    BLOCKS: ClassVar[list] = [_block(0, 0, context=128), _block(0, 1, context=128),
                              _block(0, 2, context=320)]

    @pytest.fixture(autouse=True)
    def _no_store(self, monkeypatch):
        """Every test here builds a recipe, and a recipe names the rasters the planet stage
        declared — which on a machine with no store is a raised FileNotFoundError, not an empty
        answer. The seam is answered from the registry so these run in a bare checkout."""
        declare_planet_rasters(monkeypatch)

    def _params(self, body=bodies.EARTH, blocks=None):
        return block_render.recipe_for(body, planet_seam.declared(body),
                                       self.BLOCKS if blocks is None else blocks)

    def test_a_rig_constant_moving_moves_the_recipe(self):
        """The whole reason the rig's constants are serialised rather than left to source mtimes:
        a look change has to restage the render, and a checkout must not."""
        rig = block_render.rig_recipe(
            bodies.EARTH, prep_block.rig_images(bodies.EARTH, planet_seam.declared(bodies.EARTH)))
        moved = {**rig, "rig": {**rig["rig"], "samples": rig["rig"]["samples"] // 2}}
        arguments = (bodies.EARTH, planet_seam.declared(bodies.EARTH), palette.look_for("earth"))
        assert (block_render.params(*arguments, moved, self.BLOCKS)
                != block_render.params(*arguments, rig, self.BLOCKS))

    def test_the_recipe_records_the_contexts_produced_and_not_the_law(self):
        """THE HAND-ENUMERATION'S REPLACEMENT, and it exists because that list failed three times.

        Twice it went SHORT — a floor added to the law and not to the list, then a shortcut deleted
        from the law and reflected nowhere — each leaving the recipe text unmoved, the generation
        reading as current, and a resume about to keep blocks rendered under the old rule. Once it
        went LONG, recording a ceiling no block on this body reaches. A census is measured from the
        plan rather than described, so it cannot go short.
        """
        recorded = json.loads(self._params())["contexts"]
        assert recorded == {"128": 2, "320": 1}
        assert "ratio" not in json.dumps(recorded), "the law's constants are not what is recorded"

    def test_the_two_fixed_widths_are_recorded_as_the_constants_they_are(self):
        """THE CENSUS COVERS ONE WIDTH OF THREE, and the other two still have to be seen.

        Delivered and traced are the same for every block on a body, so a census of them would be a
        one-entry dictionary saying nothing. They are constants, so they are recorded as constants —
        but recorded, because moving either restages the planet and no mtime can see a constant.
        """
        recorded = json.loads(self._params())
        assert recorded["block_px"] == block_plan.RENDER_BLOCK_PX
        assert recorded["denoise_band_px"] == block_plan.DENOISE_BAND_PX
        assert recorded["traced_px"] == (block_plan.RENDER_BLOCK_PX
                                         + 2 * block_plan.DENOISE_BAND_PX)

    def test_a_context_moving_moves_the_recipe_and_a_law_change_that_moves_none_does_not(self):
        """Both directions, which is the property the constants list could not hold.

        The first arm is the under-tracking failure that nearly shipped a seamed planet; the second
        is the over-tracking one that would restage a finished Earth for another planet's benefit.
        """
        widened = [*self.BLOCKS[:2], _block(0, 2, context=384)]
        assert self._params(blocks=widened) != self._params()
        renamed = [_block(0, 1, context=128), _block(0, 0, context=128), _block(0, 2, context=320)]
        assert self._params(blocks=renamed) == self._params(), \
            "the census must not move when the same contexts are merely planned in another order"

    def test_the_bodys_exaggeration_is_in_the_recipe(self):
        assert json.loads(self._params())["exaggeration"] == bodies.EARTH.baked_exaggeration
        assert json.loads(self._params(bodies.MARS))["exaggeration"] == bodies.MARS.baked_exaggeration

    def test_a_layer_switched_off_is_recorded_rather_than_merely_absent(self):
        """The direction that is silent without a record: a path that is not there scores 0.0 in
        an mtime comparison, so turning sea ice off would otherwise leave a planet painted with it
        looking perfectly current."""
        earth = json.loads(self._params())
        assert earth["layers_on"] == layers.layers_on(bodies.EARTH, layers.BLOCK_LAYERS)
        without_ice = dataclasses.replace(
            bodies.EARTH, surface_layers=bodies.EARTH.surface_layers - {layers.SEA_ICE.name})
        assert json.loads(self._params(without_ice))["layers_on"] == sorted(
            set(earth["layers_on"]) - {layers.SEA_ICE.name})


class TestTheShippingPlannerSizesFromTheSharedSunAltitude:
    """EVERY OTHER TEST IN THIS FILE STUBS `plan_blocks`, so the one line choosing the sizing
    altitude has no other guard, and getting it wrong truncates every shadow reaching into a block
    with no error and no edge to notice.

    It moves the shared constant rather than asserting the number, because the failure this can
    actually see is a DRIFT: `palette.SUN_ALT_DEG` is what the rig and the tile shader are lit by
    too, so a local copy here sizes the planet for a sun nothing else uses. Sizing anywhere BELOW
    that altitude is rejected rather than open, and `block_plan.context_for` says why.
    """

    def test_it_sizes_from_the_shared_sun_altitude(self, monkeypatch, tmp_path):
        seen = {}

        def _capture(relief, window, body, *, altitude_deg):
            seen["altitude"] = altitude_deg
            return []

        monkeypatch.setattr(relief_scan, "scan", lambda body, **kwargs: None)
        monkeypatch.setattr(relief_scan, "read_relief",
                            lambda work: (np.zeros((32, 32)), np.zeros((32, 32))))
        monkeypatch.setattr(block_plan, "plan", _capture)
        monkeypatch.setattr(palette, "SUN_ALT_DEG", palette.SUN_ALT_DEG - 5.0)
        block_render.plan_blocks(bodies.EARTH, tmp_path)
        assert seen["altitude"] == palette.SUN_ALT_DEG, \
            "the planner carries its own altitude, so the rig's sun and the ring's sun can drift"


class TestTheWhiteLawReachesTheRecipeAndNotOnlyTheCode:
    """WHICH SIDE OF THE FOLD A LAYER SITS ON MOVES PIXELS AND MOVED NO RECIPE.

    `fold_white` is a maximum over `WHITE_UNION` with `WHITE_EXCLUSIONS` subtracted after it, and
    the two tuples are the law rather than any producer's constant. Nothing else in this recipe can
    stand in for them: `producers_for` walks `warped_for` and so records a layer's producer
    whichever tuple it sits in, and `glaciers` and `antarctic_rock` both declare an EMPTY
    `contribution_recipe`, so a layer changing side moves no other entry at all.
    """

    BLOCKS: ClassVar[list] = [_block(0, 0, context=128)]

    @pytest.fixture(autouse=True)
    def _no_store(self, monkeypatch):
        declare_planet_rasters(monkeypatch)

    def _params(self, body=bodies.EARTH):
        return block_render.recipe_for(body, planet_seam.declared(body), self.BLOCKS)

    def test_a_layer_moving_from_the_exclusions_into_the_union_moves_the_recipe(self, monkeypatch):
        """The shipped defect's own shape, run forwards: the outcrop stops being subtracted and is
        painted the very white it exists to remove."""
        before = self._params()
        monkeypatch.setattr(layer_producers, "WHITE_UNION",
                            layer_producers.WHITE_UNION + (layers.ANTARCTIC_ROCK,))
        monkeypatch.setattr(layer_producers, "WHITE_EXCLUSIONS", ())
        assert self._params() != before

    def test_a_layer_leaving_the_union_moves_the_recipe(self, monkeypatch):
        """The arm no test pins from the other direction either: every membership assertion in the
        suite is negative, so glaciers silently ceasing to be white is caught by nothing."""
        before = self._params()
        monkeypatch.setattr(layer_producers, "WHITE_UNION", (layers.PERENNIAL_ICE,))
        assert self._params() != before

    def test_reordering_the_union_moves_the_recipe(self, monkeypatch):
        """Order is part of the law, not presentation: `fold_white`'s maximum commutes and the
        `merge` caller folded alongside it does not."""
        before = self._params()
        monkeypatch.setattr(layer_producers, "WHITE_UNION",
                            tuple(reversed(layer_producers.WHITE_UNION)))
        assert self._params() != before

    def test_the_recorded_law_is_read_from_the_tuples_rather_than_spelled_here(self):
        """Derived on both sides, so this cannot pass by two hand-written lists agreeing."""
        recipe = json.loads(self._params())
        assert recipe == {**recipe,
                          **layer_producers.white_law(bodies.EARTH, layers.BLOCK_LAYERS)}

    def test_the_law_a_body_does_not_declare_is_not_recorded(self):
        """Mars folds one white and subtracts nothing, and the recipe says so rather than
        repeating Earth's."""
        mars = json.loads(self._params(bodies.MARS))
        assert mars["white_exclusions"] == []
        assert mars["white_union"] != json.loads(self._params())["white_union"]


class TestTheCropTakesTheBandAndNeverTheContext:
    """TRACED IS NOT PLANE, and getting the two the wrong way round is the silent failure.

    The frame Cycles hands back is the TRACED rectangle: the delivered block plus `DENOISE_BAND_PX`
    on every side. The context is a different and far larger number — off-camera geometry that
    never reaches a frame at all. Cropping by the context takes a correctly SHAPED square out of
    the wrong place, and the mosaic records it as done: right size, right dtype, wrong ground, no
    exception anywhere. On Earth's widest blocks it would be 1,856 px off true.

    A SHAPE ASSERTION ALONE CANNOT SEE IT, which is why the crop is checked against pixels here
    rather than against `crop.shape`, and why the second test exists to prove the first one is
    discriminating at all.
    """

    def _traced_frame(self, block, bands=4):
        edge = block.traced_edge_px
        return np.arange(bands * edge * edge, dtype=np.uint8).reshape(bands, edge, edge)

    def test_the_denoise_band_is_cut_back_off(self, tmp_path, monkeypatch):
        band = block_plan.DENOISE_BAND_PX
        block = _block(0, 0, context=1024)
        frame = self._traced_frame(block)
        monkeypatch.setattr(block_render, "rasterio", _FakeRasterio(frame))
        crop = block_render.cropped(tmp_path / "r00c00.png", block)
        assert crop.shape == (3, block.size_px, block.size_px)
        assert np.array_equal(crop, frame[:3, band:band + block.size_px,
                                          band:band + block.size_px])

    def test_the_two_offsets_select_different_pixels_so_the_pin_above_can_fail(self):
        """The positive control. `context_px` defaults to the band, and where the two are equal a
        crop written against the wrong one passes every assertion — so the block above is given a
        context deliberately unequal to the band, and this is what proves that matters."""
        block = _block(0, 0, context=1024)
        assert block.context_px != block_plan.DENOISE_BAND_PX
        frame = self._traced_frame(block)
        band, wrong, edge = block_plan.DENOISE_BAND_PX, block.context_px, block.size_px
        assert not np.array_equal(frame[:3, band:band + edge, band:band + edge],
                                  frame[:3, wrong:wrong + edge, wrong:wrong + edge])

    def test_a_frame_the_size_of_the_PLANE_rather_than_the_traced_rectangle_raises(
            self, tmp_path, monkeypatch):
        """A rig that photographed its whole plane would hand back a frame this size. It is the
        other half of the same confusion, and it must not be cropped as though it were correct."""
        block = _block(0, 0, context=1024)
        plane = block.plane_edge_px
        frame = np.zeros((4, plane, plane), dtype=np.uint8)
        monkeypatch.setattr(block_render, "rasterio", _FakeRasterio(frame))
        with pytest.raises(RuntimeError, match="traced frame"):
            block_render.cropped(tmp_path / "r00c00.png", block)

    def test_a_frame_smaller_than_the_traced_rectangle_raises(self, tmp_path, monkeypatch):
        """The frame numbers and the rig disagreeing, which would otherwise write a wrongly-offset
        block into the planet and mark it done."""
        block = _block(0, 0)
        short = block.traced_edge_px - 2 * block_plan.DENOISE_BAND_PX
        monkeypatch.setattr(block_render, "rasterio",
                            _FakeRasterio(np.zeros((4, short, short), dtype=np.uint8)))
        with pytest.raises(RuntimeError, match="traced frame"):
            block_render.cropped(tmp_path / "r00c00.png", block)


class _FakeRasterio:
    """Stands in for the module, so a frame and the mosaic it is written into are both provable
    without a raster on disk. `written` collects the crops, in call order."""

    def __init__(self, frame):
        self._frame = frame
        self.written = []

    def open(self, *args, **kwargs):
        frame, written = self._frame, self.written

        class _Reader:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return frame

            def write(self, data, window=None):
                written.append((data, window))

        return _Reader()


def _render_one_block(tmp_path, monkeypatch, **kwargs):
    """`render_block` end to end with Blender and the rasters stood in for.

    Everything it does on disk still happens: the prep fills a render directory, the stand-in
    Blender writes the frame and the scene beside it, and the cleanup at the end is what is under
    test. The block is small because the frame is allocated for real and nothing here reads ground.
    """
    block = Block(col0=0, row0=0, size_px=64, context_px=block_plan.DENOISE_BAND_PX)
    name = block_render.block_name(block)
    scratch, markers = tmp_path / "scratch", tmp_path / "blocks"
    scratch.mkdir(parents=True)
    markers.mkdir(parents=True)
    frame, scene = scratch / f"{name}.png", scratch / f"{name}.blend"

    def _cut(body, block, render_dir, *, work):
        render_dir.mkdir(parents=True, exist_ok=True)
        (render_dir / "heightfield.tif").write_bytes(b"")

    def _blender(command):
        frame.write_bytes(b"")
        scene.write_bytes(b"")
        return SimpleNamespace(
            returncode=0, stderr="",
            stdout=f"DENOISE_DEVICE {block_render.BLOCK_DENOISE_DEVICE}\n"
                   f"BASE_GRID {block_render.BLOCK_BASE_GRID} BASE_PATCHES 1\n")

    edge = block.traced_edge_px
    monkeypatch.setattr(prep_block, "cut", _cut)
    monkeypatch.setattr(block_render.blender_proc, "run", _blender)
    monkeypatch.setattr(block_render, "rasterio",
                        _FakeRasterio(np.zeros((4, edge, edge), dtype=np.uint8)))
    block_render.render_block(bodies.EARTH, block, tmp_path / "planet_rgb.tif", scratch, markers,
                              tmp_path, digest="0" * 32, **kwargs)
    return SimpleNamespace(frame=frame, scene=scene, render_dir=scratch / name,
                           marker=markers / name)


class TestTheFrameCanBeKeptForADiagnosis:
    """The Cycles frame is the only thing that can say whether an artifact is in the render or
    arrived after it, and every block deletes its own.

    THE FRAME IS UNLINKED SEPARATELY FROM THE DIRECTORY BESIDE IT, so keeping one is not keeping
    the other: a diagnosis that suppresses only `shutil.rmtree` gets the prep inputs and loses the
    pixels it was run for. Both are asserted, and in both directions, because a `render_block` that
    stopped cleaning up at all would satisfy the keeping half on its own.
    """

    def test_a_kept_render_leaves_the_frame_where_it_was_written(self, tmp_path, monkeypatch):
        kept = _render_one_block(tmp_path, monkeypatch, keep_intermediates=True)
        assert kept.frame.exists(), "the frame is what a render diagnosis reads"
        assert kept.scene.exists() and kept.render_dir.is_dir()

    def test_the_default_deletes_all_three_so_the_pin_above_can_fail(self, tmp_path, monkeypatch):
        """The control. A pass leaves 4,096 of these behind, so keeping them is the exception and
        the flag has to be what makes the difference rather than a cleanup that stopped running."""
        swept = _render_one_block(tmp_path, monkeypatch)
        assert not swept.frame.exists()
        assert not swept.scene.exists() and not swept.render_dir.exists()

    def test_the_block_is_rendered_and_marked_either_way(self, tmp_path, monkeypatch):
        """Keeping is a cleanup decision and nothing else. A flag that also skipped the write would
        leave the mosaic short with a marker claiming otherwise, which no later run re-renders."""
        for keep in (True, False):
            done = _render_one_block(tmp_path / f"k{keep}", monkeypatch, keep_intermediates=keep)
            assert done.marker.exists()

    def test_the_run_hands_its_answer_to_every_block(self, tmp_path, monkeypatch):
        """The flag arrives at the CLI and the deletion happens per block, so the two are joined by
        an argument that nothing else asserts: the tests above call the block directly."""
        kept = _drive_planet(tmp_path, monkeypatch, blocks=3, keep_intermediates=True)
        assert kept.handed == [{"keep_intermediates": True}] * 3

    def test_a_finished_planet_does_not_sweep_away_what_it_was_asked_to_keep(
            self, tmp_path, monkeypatch):
        """`run` empties the scratch tree on the pass that completes the planet, so without this
        the flag would hold or not hold depending on which block a diagnosis happened to ask for."""
        kept = _drive_planet(tmp_path, monkeypatch, blocks=2, keep_intermediates=True)
        assert kept.rendered == 2 and all(scratch.is_dir() for scratch in kept.scratches)

    def test_a_finished_planet_sweeps_it_by_default(self, tmp_path, monkeypatch):
        """The control for the test above, and the behaviour a night's pass depends on."""
        swept = _drive_planet(tmp_path, monkeypatch, blocks=2)
        assert swept.rendered == 2 and not any(scratch.exists() for scratch in swept.scratches)


class TestTheDiskFloorIsSizedForWhatIsLeft:
    """A floor sized for a whole planet would abort a nearly finished pass that needs megabytes,
    which costs a night in the direction nobody checks for."""

    def test_the_floor_relaxes_as_the_run_progresses(self):
        total = 4096
        early = block_render.disk_floor_bytes(bodies.EARTH, total, total)
        late = block_render.disk_floor_bytes(bodies.EARTH, 8, total)
        assert late < early

    def test_a_finished_run_asks_for_nothing(self):
        assert block_render.disk_floor_bytes(bodies.EARTH, 0, 4096) == 0.0

    def test_the_floor_assumes_compression_buys_nothing(self):
        """Stated as the closed form rather than as a measured size: the DEFLATE ratio is not
        knowable before the pixels exist, and a floor derived from the last planet's ratio would be
        a measurement standing in for a guarantee."""
        edge = block_plan.grid_px(bodies.EARTH)
        assert block_render.disk_floor_bytes(bodies.EARTH, 4096, 4096) == edge * edge * 3


class TestABlockTooBigToRenderStopsTheRun:

    def test_a_plan_that_fits_is_returned_unchanged(self):
        blocks = [_block(0, 0, context=block_plan.CONTEXT_CEILING_PX)]
        assert block_render.check_fits(blocks, bodies.EARTH) == blocks

    def test_the_widest_context_on_the_registry_does_not_make_a_block_unrenderable(self):
        """WHAT THE CEILING BOUNDS CHANGED, and this is the assertion that says so. The context is
        plane geometry now, not frame, so no context however wide can push a block past the GPU's
        frame envelope; the only thing that can is the block edge itself."""
        widest = _block(0, 0, context=block_plan.CONTEXT_CEILING_PX)
        assert widest.plane_edge_px >= block_plan.TRACED_CEILING_PX
        assert widest.fits

    def test_one_oversized_block_refuses_the_whole_plan(self):
        """Not skipped: an unwritten block reads as black in the mosaic rather than as missing,
        so a hole would ship as a look decision."""
        oversized = Block(col0=0, row0=0, size_px=block_plan.TRACED_CEILING_PX, context_px=128)
        with pytest.raises(SystemExit, match="exceed"):
            block_render.check_fits([_block(0, 0), oversized], bodies.EARTH)


class TestARunThatOwesNothingRendersNothing:
    """A planet whose blocks all match what they were rendered from must cost a plan and a digest
    pass, never a night.

    The mosaic's own completion stamp is not what makes it cheap any more, and that is a correction
    rather than a regression: a stamp says a pass finished and nothing about which ground each block
    read, so a mosaic stamped over blocks nobody rendered is a claim with no evidence under it.
    """

    def test_a_second_run_over_an_untouched_store_renders_nothing(self, tmp_path, monkeypatch):
        _drive_small_planet(tmp_path, monkeypatch)
        assert _drive_small_planet(tmp_path, monkeypatch) == []

    def test_a_stamped_mosaic_with_no_markers_renders_everything(self, tmp_path, monkeypatch):
        """The other direction, so the test above cannot pass by never rendering. The old early
        return read the stamp and skipped the planet on the strength of it."""
        mosaic = tmp_path / cut_tiles.PLANET_RGB
        mosaic.write_bytes(b"")
        freshness.mark_done(mosaic)
        assert len(_drive_small_planet(tmp_path, monkeypatch)) == 16


class TestTheLoopStampsOnlyAWholePlanet:
    """What `_drive_planet` is checking here is `run`'s own arithmetic — which blocks are
    attempted, and whether the mosaic ends up stamped — not the stand-in renderer's. The stamp is
    the dangerous one: `tiles_are_fresh` keys on it, so a partial planet that stamps itself is a
    pyramid cut from half a producer.
    """

    def test_a_whole_planet_stamps_the_mosaic(self, tmp_path, monkeypatch):
        run = _drive_planet(tmp_path, monkeypatch)
        assert run.rendered == 3 and run.attempted == ["r00c00", "r00c01", "r00c02"]
        assert freshness.done_marker(run.mosaic).exists()

    def test_a_limited_run_renders_but_does_not_stamp(self, tmp_path, monkeypatch):
        run = _drive_planet(tmp_path, monkeypatch, limit=2)
        assert run.rendered == 2 and len(run.attempted) == 2
        assert not freshness.done_marker(run.mosaic).exists()

    def test_limit_zero_renders_nothing_at_all(self, tmp_path, monkeypatch):
        """`--limit 0` MUST mean none, and it is the falsy value: a truthiness test reads it as no
        limit and starts the whole planet. That exact shape has breached this project's one-heavy-
        job rule before, from a different flag."""
        run = _drive_planet(tmp_path, monkeypatch, limit=0)
        assert run.rendered == 0 and run.attempted == []
        assert not freshness.done_marker(run.mosaic).exists()

    def test_a_named_subset_never_stamps_even_when_all_of_it_renders(self, tmp_path, monkeypatch):
        """The subset finished; the planet did not. Completion is asked of the grid, never of the
        selection, or `--only` on one block would declare a planet done."""
        run = _drive_planet(tmp_path, monkeypatch, only=frozenset({"r00c01"}))
        assert run.rendered == 1 and run.attempted == ["r00c01"]
        assert not freshness.done_marker(run.mosaic).exists()

    def test_a_block_that_is_not_on_the_grid_is_refused(self, tmp_path, monkeypatch):
        """A typo in `--only` would otherwise render nothing and report success."""
        with pytest.raises(SystemExit, match="no such block"):
            _drive_planet(tmp_path, monkeypatch, only=frozenset({"r99c99"}))


class TestARunRefusesToStartWithoutItsInputs:
    """The failure this converts from slow and misattributed into immediate and named.

    Without it a missing heightfield raises on the first block and on the next seven, and the run
    stops on the consecutive-failure counter — whose message says the GPU is gone, about a stage
    that never ran. On an unattended night that reads as a hardware fault.
    """

    #: A seam that CAN feed the rig, so the file checks below are reached at all.
    FEEDS_THE_RIG = frozenset({"heightfield", "watermask"})

    def test_a_missing_heightfield_stops_the_run_by_name(self, tmp_path):
        with pytest.raises(SystemExit, match=planet_warp.HEIGHT_3857):
            block_render.check_inputs(tmp_path, bodies.EARTH, self.FEEDS_THE_RIG)

    def test_the_error_names_the_stage_that_builds_them(self, tmp_path):
        """An error that says what is missing and not how to fix it costs the reader two tiers."""
        with pytest.raises(SystemExit, match="planet_pass"):
            block_render.check_inputs(tmp_path, bodies.EARTH, self.FEEDS_THE_RIG)

    def test_a_body_that_declares_no_ocean_is_not_asked_for_an_oceanmask(self, tmp_path):
        """The declaration decides, never the disk: asking every body for every raster would make
        a sea-less planet unrenderable, and sniffing the disk cannot tell 'has none' from 'died'.

        EVERY MANDATORY IMAGE NOW WORKS THIS WAY, and the oceanmask used to be the only one:
        `scene_build.textures_for` loads what the render directory declared, so a block missing any
        of them is a scene the rig will build rather than one it refuses.
        """
        (tmp_path / planet_warp.HEIGHT_3857).write_bytes(b"")
        (tmp_path / planet_warp.WATER_3857).write_bytes(b"")
        block_render.check_inputs(tmp_path, bodies.EARTH, self.FEEDS_THE_RIG)

    def test_a_body_that_does_declare_one_may_not_start_without_it(self, tmp_path):
        (tmp_path / planet_warp.HEIGHT_3857).write_bytes(b"")
        with pytest.raises(SystemExit, match=planet_warp.WATER_3857):
            block_render.check_inputs(tmp_path, bodies.EARTH, self.FEEDS_THE_RIG)


class TestATHinSeamNoLongerStopsTheProducer:
    """The refusal this replaces was correct about the rig and is what the rig stopped needing.

    A planet declaring no watermask was refused before its first block, because the rig loaded
    `inlandlake.png` and `river.png` for every look while `prep_block` wrote them only where the
    seam declared one. Since `scene_build.textures_for` reads the render directory's own
    declaration, there is no image a thin seam fails to supply and nothing left to refuse.

    THE REPLACEMENT IS NOT NOTHING, and it is a different question in a different place: a LOOK
    with a sea over a directory with no oceanmask still refuses, in `scene_build`, because that
    pair renders a planet of land. It is not askable here — this interpreter cannot import a
    module that imports `bpy`, which is why the old refusal deliberately skipped the oceanmask.
    """

    def test_mars_seam_starts_where_it_used_to_be_refused(self, tmp_path):
        """The oracle for unit 10's code blocker: the thin seam gets past the door."""
        _stage_warped_inputs(tmp_path)
        block_render.check_inputs(tmp_path, bodies.MARS, frozenset({"heightfield"}))

    def test_the_raster_checks_below_it_still_fire(self, tmp_path):
        """The control. A `check_inputs` that returned early would satisfy the test above for the
        wrong reason, so the check it must still be doing is asserted on the same body."""
        with pytest.raises(SystemExit, match="height_3857"):
            block_render.check_inputs(tmp_path, bodies.MARS, frozenset({"heightfield"}))

    def test_a_thin_seam_is_asked_for_no_water_raster(self, tmp_path):
        """The other half of that control: refusing Mars for a missing `water_3857.tif` would be
        the same defect wearing the other hat, since its seam declares no watermask."""
        (tmp_path / planet_warp.HEIGHT_3857).write_bytes(b"")
        block_render.check_inputs(tmp_path, bodies.MARS, frozenset({"heightfield"}))


def _stage_warped_inputs(tmp_path):
    """The warped rasters the block prep cuts from, as rasters rather than as empty files.

    Empty files are cheaper and `check_inputs` accepts them, since it asks only whether they are
    there. A run digests the ground each block reads out of them, so an unopenable file is a run
    that cannot start.

    One that is already there is left alone, because a test that drives two runs over one work
    directory would otherwise move an input's mtime between them and restage the second by its own
    setup, which reads exactly like the defect such a test is looking for.
    """
    for name in (planet_warp.HEIGHT_3857, planet_warp.OCEAN_3857, planet_warp.WATER_3857):
        if not (tmp_path / name).exists():
            _write_small_raster(tmp_path / name)


def _age_everything(root):
    """Set every mtime under `root` back, so anything written after this call is unambiguously
    newer than everything the runs before it left.

    Whole seconds for `_stale_by_a_second`'s reason. Aging to ONE instant is the point rather than a
    shortcut: it leaves every existing file tied, and both freshness predicates read a tie as fresh,
    so the only thing that can make a later run rebuild is a file that run actually wrote.
    """
    stamp = time.time() - 2
    for path in [root, *root.rglob("*")]:
        os.utime(path, (stamp, stamp))


def _drive_planet(tmp_path, monkeypatch, *, mosaic=None, blocks=3, **kwargs):
    """`run` driven over a stand-in renderer, so the ordering and the paths it owns are provable
    without a GPU. Returns what the run attempted, the raster it filled, the count it reported and
    every scratch directory it handed the renderer.

    `mosaic` is an argument, defaulting to the canonical raster, because the A/B route is a SECOND
    raster in the same work directory: every guard about what one run may touch needs both.

    NEITHER THE MOSAIC NOR THE WARPED INPUTS ARE REWRITTEN WHEN THEY EXIST. `is_stale` calls an
    output rewritten-since-completed stale, so re-creating a stamped mosaic here would restage the
    second run from the fixture rather than from anything the code did.
    """
    declare_planet_rasters(monkeypatch)
    # The disk floor is sized for a whole planet and these blocks stand in for one, so on any
    # ordinary scratch filesystem it would abort before the loop. It has its own guards above; here
    # it is held out of the way rather than left to fire.
    monkeypatch.setattr(block_render, "free_bytes", lambda path: 1 << 60)
    planned = [_block(0, column) for column in range(blocks)]
    attempted: list[str] = []
    scratches: set[Path] = set()
    cut_from: set[Path] = set()
    handed: list[dict] = []

    def _fake_render(body, block, mosaic, scratch, markers, work, *, digest, **passed):
        attempted.append(block_render.block_name(block))
        scratches.add(scratch)
        cut_from.add(work)
        handed.append(passed)
        block_render.write_marker(markers, block, digest, "BASE_GRID fitted BASE_PATCHES 1")

    monkeypatch.setattr(block_render, "plan_blocks", lambda body, work: planned)
    monkeypatch.setattr(block_render, "ensure_mosaic", lambda mosaic, body: None)
    monkeypatch.setattr(block_render, "render_block", _fake_render)
    _stage_warped_inputs(tmp_path)
    mosaic = tmp_path / "planet_rgb.tif" if mosaic is None else mosaic
    mosaic.parent.mkdir(parents=True, exist_ok=True)
    if not mosaic.exists():
        mosaic.write_bytes(b"")
    mosaic = mosaic.resolve()          # the spelling `run` itself uses, so a caller can compare
    rendered = block_render.run(bodies.EARTH, tmp_path, mosaic, **kwargs)
    return SimpleNamespace(attempted=attempted, mosaic=mosaic, rendered=rendered,
                           scratches=scratches, cut_from=cut_from, handed=handed)


class TestTheDenoiseDeviceIsTheCallersAndIsRecorded:
    """OIDN on the GPU is ~8x faster and the heroes must not have it, so it is an argument.

    The whole point of the shape is that the two callers of `scene_build` disagree about one Cycles
    setting while sharing everything else, so the tests that matter are the two directions of that
    disagreement plus the recipe that has to be able to see it move.
    """

    def _command(self, tmp_path):
        return block_render.blender_command(
            bodies.EARTH, tmp_path / "rd", tmp_path / "b.blend", tmp_path / "b.png")

    def test_the_block_runner_opts_in(self, tmp_path):
        command = self._command(tmp_path)
        assert "--denoise-device" in command
        assert command[command.index("--denoise-device") + 1] == block_render.BLOCK_DENOISE_DEVICE
        assert block_render.BLOCK_DENOISE_DEVICE == "gpu"

    def test_the_block_runner_opts_into_the_base_grid_too(self, tmp_path):
        """The blocks' half of the pair `TestTheHeroRenderStaysOnTheSingleQuad` guards. Blocks are
        the caller that can AFFORD one micropolygon per pixel, because most of their plane is
        off-camera; pinned to `fitted` by name so a silent revert to the hero default is caught."""
        command = self._command(tmp_path)
        assert "--base-grid" in command
        assert command[command.index("--base-grid") + 1] == block_render.BLOCK_BASE_GRID
        assert block_render.BLOCK_BASE_GRID == "fitted"

    def test_the_recipe_records_the_base_grid(self):
        recipe = json.loads(block_render.params(
            bodies.EARTH, frozenset(planet_seam.KNOWN_RASTERS), palette.EARTH_LOOK,
            {"SAMPLES": 4096}, [Block(col0=0, row0=0, size_px=2048, context_px=128)]))
        assert recipe["base_grid"] == block_render.BLOCK_BASE_GRID

    def test_the_recipe_records_the_mask_depth(self):
        """The mask writer's depth is `prep_block`'s constant, and only this recipe can carry it.

        A re-cut mask does not restage a rendered block: a block's digest covers the planet rasters
        the prep reads, not the per-block directory it writes. So without this key, changing the
        depth reaches only the blocks that were going to render anyway and leaves every finished one
        carrying whatever the old depth produced.
        """
        recipe = json.loads(block_render.params(
            bodies.EARTH, frozenset(planet_seam.KNOWN_RASTERS), palette.EARTH_LOOK,
            {"SAMPLES": 4096}, [Block(col0=0, row0=0, size_px=2048, context_px=128)]))
        assert recipe["mask_full_scale"] == prep_block.MASK_FULL_SCALE

    def test_the_recipe_records_the_pole_side_edge_policy(self):
        """What a plane overhanging the grid at a pole reads there, which only this recipe carries.

        THE SAME ARGUMENT AS THE DEPTH ABOVE, aimed at the two block rows a marker is most likely to
        have already called done. It is here because the policy that shipped before it was a zero
        FILL, and the datum is not a neutral elevation: Mars's grid ends at -3,565 m and Earth's at
        -2,732, so the fill stood a wall of invented geometry along each pole-side plane. Without
        this key the replacement would restage nothing and every finished edge block would keep it.
        """
        recipe = json.loads(block_render.params(
            bodies.EARTH, frozenset(planet_seam.KNOWN_RASTERS), palette.EARTH_LOOK,
            {"SAMPLES": 4096}, [Block(col0=0, row0=0, size_px=2048, context_px=128)]))
        assert recipe["row_edge_mode"] == prep_block.ROW_EDGE_MODE

    def test_moving_the_edge_policy_moves_the_recipe(self, monkeypatch):
        """The freshness arm, and the reason the constant is named rather than spelled inline.

        A literal in `_read_cyclic` would render differently and record identically, which is the
        exact shape of "a fix behind a freshness gate never reaches what is already on disk".
        """
        blocks = [Block(col0=0, row0=0, size_px=2048, context_px=128)]
        args = (bodies.EARTH, frozenset(planet_seam.KNOWN_RASTERS), palette.EARTH_LOOK,
                {"SAMPLES": 4096}, blocks)
        before = block_render.params(*args)
        monkeypatch.setattr(prep_block, "ROW_EDGE_MODE", "constant")
        assert block_render.params(*args) != before, (
            "the recipe must move with the policy, or the planet on disk goes on claiming to be "
            "current under a rule it was not rendered with")

    def test_the_recipe_records_it(self):
        recipe = json.loads(block_render.params(
            bodies.EARTH, frozenset(planet_seam.KNOWN_RASTERS), palette.EARTH_LOOK,
            {"SAMPLES": 4096}, [Block(col0=0, row0=0, size_px=2048, context_px=128)]))
        assert recipe["denoise_device"] == block_render.BLOCK_DENOISE_DEVICE

    def test_moving_it_moves_the_recipe(self, monkeypatch):
        """The freshness arm. The two denoisers do not agree to the last DN, so a pass resumed
        across a change of this must restage rather than blend both into one mosaic."""
        blocks = [Block(col0=0, row0=0, size_px=2048, context_px=128)]
        args = (bodies.EARTH, frozenset(planet_seam.KNOWN_RASTERS), palette.EARTH_LOOK,
                {"SAMPLES": 4096}, blocks)
        before = block_render.params(*args)
        monkeypatch.setattr(block_render, "BLOCK_DENOISE_DEVICE", "cpu")
        assert block_render.params(*args) != before


class TestTheRecipeRecordsWhatThePrepGradesWith:
    """`prep_block` runs the same producers the composite does, and only one tier recorded them.

    A block generation is compared ONCE at pass start against markers skipped by existence, so a
    re-tune landed after a planet renders moves nothing and leaves every marker reading current.

    BOTH DIRECTIONS ARE TESTED because both are silent. Recording a constant the prep never reads
    is not the safe side: the whites are the rig's, so recording them here would restage a night of
    GPU for pixels that cannot move.
    """

    BLOCKS: ClassVar[list] = [Block(col0=0, row0=0, size_px=2048, context_px=128)]

    def _params(self, body=bodies.EARTH):
        return block_render.params(body, frozenset(planet_seam.KNOWN_RASTERS),
                                   palette.look_for(body.name), {"SAMPLES": 4096}, self.BLOCKS)

    def _in_block_producers(self, body=bodies.EARTH):
        """The producers this body's block prep actually runs, derived from the same two facts
        `gather` is given: the stage's own vocabulary and the body's declarations."""
        return [(layer, layer_producers.producer_for(body, layer)) for layer in layers.LAYERS
                if layer.name in layers.BLOCK_LAYERS and layer.name in body.surface_layers]

    def test_the_ice_softening_moving_moves_the_recipe(self, monkeypatch):
        """`SOFTEN_FRACTION` reaches a pixel and reaches no file: the warped persistence raster is
        unchanged by it, so every block's digest over the ground is unchanged too."""
        before = self._params()
        monkeypatch.setattr(snow, "SOFTEN_FRACTION", snow.SOFTEN_FRACTION * 2)
        assert self._params() != before

    def test_the_sea_ice_ramp_moving_moves_the_recipe(self, monkeypatch):
        """A SECOND producer, grading by a different mechanism into a different image, so a fix
        reaching only the snow path passes the test above and leaves this one red."""
        before = self._params()
        monkeypatch.setattr(seaice, "ICE_LO", seaice.ICE_LO / 2)
        assert self._params() != before

    def test_every_constant_an_in_block_producer_grades_with_reaches_the_recipe(self, subtests):
        """Derived rather than listed, so a producer that GROWS a constant goes red. A hand-written
        list of today's keys is the shape that went short three times in the context census."""
        recorded = json.loads(self._params())
        graded = {f"{layer.name}.{key}": (key, value)
                  for layer, producer in self._in_block_producers()
                  for key, value in producer.contribution_recipe().items()}
        assert len(graded) >= 12, \
            f"only {len(graded)} graded constants swept; a short read would pass this vacuously"
        for name, (key, value) in sorted(graded.items()):
            with subtests.test(name):
                assert key in recorded, f"{name} grades a block pixel and reaches no recipe"
                assert recorded[key] == value

    def test_a_white_the_PREP_declares_reaches_the_recipe(self, monkeypatch):
        """INVERTED WHEN THE RIG STOPPED HOLDING ITS OWN ALBEDO, and the old assertion was right
        until then: while `RIG.snow_rgba` painted every mask, `palette.SNOW_RGB` could not move a
        block pixel and recording it would have put a night of GPU behind a cap re-tune.

        The rig now reads the colour the prep resolved from the body's registry, so the white moves
        a block pixel, and reaches freshness only here. A block's digest covers the planet rasters
        the prep reads and not the directory it writes, so without this a re-tuned white would leave
        every finished block wearing the old colour with every gate green.
        """
        before = self._params()
        monkeypatch.setattr(palette, "SNOW_RGB", (1, 2, 3))
        assert self._params() != before, \
            "a white the rig now paints from must restage the blocks that were painted with it"

    def test_a_body_whose_producers_grade_nothing_still_records_its_white(self):
        """Mars: nothing to GRADE and a white to PAINT, which are separate halves of the recipe.

        Its `contribution_recipe` is empty on the conditional-record idiom, while its paint is a
        pair per pole. A raytraced Mars that recorded Earth's shape here would be recording a white
        no Martian pixel is painted in.

        BOTH KEYS STAY REQUIRED NOW THAT THE TWO VALUES AGREE, and that is the whole point of this
        assertion rather than a leftover. The ratified white is one white on both poles, so an
        implementation that collapsed the pair to a single `snow_rgb` key would record every pixel
        it paints today and still be wrong: the day either pole is re-split, half the planet's
        restage would go untracked and the pass would call stale blocks fresh. The previous version
        of this test asserted the two values DIFFER, which pinned a look decision that has since
        been re-taken.
        """
        graded = {key for _layer, producer in self._in_block_producers(bodies.MARS)
                  for key in producer.contribution_recipe()}
        assert not graded, f"Mars grades with {graded}; this test's premise has moved"
        recorded = json.loads(self._params(bodies.MARS))
        assert "snow_rgb_north" in recorded and "snow_rgb_south" in recorded, \
            "Mars paints its polar ice per pole, so both keys must be tracked even while they agree"


#: The planet the ground tests below drive: four blocks across, on rasters small enough to write per
#: test. Real pixels rather than the empty files the rest of this file stages, because what is being
#: asked is which ground each block reads, which no `exists()` can answer.
SMALL_GRID_PX = 256
SMALL_BLOCK_PX = 64
SMALL_CONTEXT_PX = 16

#: The digest cell for these tests, scaled down with the grid. Production's is the rasters' own
#: internal tile, which is wider than this whole planet and would put every block in one cell.
SMALL_CELL_PX = 16


def _small_block(row_index, column_index):
    return Block(col0=column_index * SMALL_BLOCK_PX, row0=row_index * SMALL_BLOCK_PX,
                 size_px=SMALL_BLOCK_PX, context_px=SMALL_CONTEXT_PX)


def _write_small_raster(path, fill=0):
    half = mercator.MERCATOR_HALF_M
    with rasterio.open(path, "w", driver="GTiff", width=SMALL_GRID_PX,  # pyright: ignore[reportCallIssue]
                       height=SMALL_GRID_PX, count=1, dtype="uint8", crs="EPSG:3857",
                       transform=from_bounds(-half, -half, half, half,
                                             SMALL_GRID_PX, SMALL_GRID_PX)) as out:
        out.write(np.full((SMALL_GRID_PX, SMALL_GRID_PX), fill, dtype="uint8"), 1)


def _paint(path, row, column, value=200):
    """Move one pixel of a planet raster, leaving every other pixel as it was."""
    with rasterio.open(path, "r+") as raster:  # pyright: ignore[reportCallIssue]
        band = raster.read(1)
        band[row, column] = value
        raster.write(band, 1)


def _an_earth_block_layer():
    """One surface layer Earth declares and the block prep reads, derived rather than named: a
    hardcoded layer would go quietly inert the day that layer left `BLOCK_LAYERS`."""
    for layer in layers.warped_for(layers.BLOCK_LAYERS):
        if layer.name in bodies.EARTH.surface_layers:
            return layer
    raise AssertionError("Earth declares no block layer, so this file's premise has moved")


def _drive_small_planet(tmp_path, monkeypatch, *, across=4, observe=None, sample=None,
                        sampled=None, fails=None, **kwargs):
    """`run` over the small planet, returning the block names it attempted.

    The stand-in renderer writes the marker production writes, because what these tests measure is
    which blocks a SECOND run decides it owes. A fake that wrote its own marker format would be
    measuring the fake.
    """
    declare_planet_rasters(monkeypatch)
    monkeypatch.setattr(block_render, "free_bytes", lambda path: 1 << 60)
    monkeypatch.setattr(block_freshness, "CELL_PX", SMALL_CELL_PX)

    def _fake_sample(body, picked, mosaic, scratch, work):
        """The sample needs Blender, so what it renders is stood in for. What is under test here is
        whether the run consults it at all and what it does with the answer."""
        if sampled is not None:
            sampled.append([block_render.block_name(block) for block in picked])
        return list(sample or [])

    monkeypatch.setattr(block_render, "sample_disagreements", _fake_sample)
    planned = [_small_block(row, column) for row in range(across) for column in range(across)]
    attempted: list[str] = []

    def _fake_render(body, block, mosaic, scratch, markers, work, *, digest, **passed):
        if observe is not None:
            observe(mosaic, markers)
        attempted.append(block_render.block_name(block))
        if block_render.block_name(block) in (fails or ()):
            raise RuntimeError(f"{block_render.block_name(block)} was asked to fail")
        block_render.write_marker(markers, block, digest, "BASE_GRID fitted BASE_PATCHES 1")

    monkeypatch.setattr(block_render, "plan_blocks", lambda body, work: planned)
    monkeypatch.setattr(block_render, "ensure_mosaic", lambda mosaic, body: None)
    monkeypatch.setattr(block_render, "render_block", _fake_render)
    for name in (planet_warp.HEIGHT_3857, planet_warp.OCEAN_3857, planet_warp.WATER_3857):
        if not (tmp_path / name).exists():
            _write_small_raster(tmp_path / name)
    mosaic = tmp_path / cut_tiles.PLANET_RGB
    if not mosaic.exists():
        mosaic.write_bytes(b"")
    block_render.run(bodies.EARTH, tmp_path, mosaic.resolve(), **kwargs)
    return attempted


class TestABlockOwesOnTheGroundItReadsAndNotOnThePlanet:
    """Which blocks a second run re-renders, which today is all of them or none of them.

    A block's pixels are a function of its own plane window of each input raster, the recipe and the
    code. The first of those is per block and nothing reads it: a marker is an existence test, and
    the only thing that clears markers clears every one of them, so a layer reaching 69 blocks costs
    1,024. What each test below names is the ground one block reads, and the failure it guards is
    the other direction: a block whose ground moved being skipped.

    The plane window is the subject rather than the delivered block, and the two differ by the
    context ring. Ground just outside a block casts shadows into it, so a check over the delivered
    window alone skips a block whose light changed. That is the silent one.
    """

    def test_a_change_inside_one_block_restages_that_block_alone(self, tmp_path, monkeypatch):
        """The saving, stated as the smallest case: a pixel no other block's plane window reaches."""
        _drive_small_planet(tmp_path, monkeypatch)
        _age_everything(tmp_path)
        _paint(tmp_path / planet_warp.HEIGHT_3857, 96, 96)
        assert _drive_small_planet(tmp_path, monkeypatch) == ["r01c01"]

    def test_a_change_in_a_blocks_context_ring_restages_it(self, tmp_path, monkeypatch):
        """The silent one. Column 124 belongs to r01c01 and lies inside r01c02's context ring, so it
        can cast into r01c02 while r01c02 owns no pixel of it. A check over each block's delivered
        window passes the test above and leaves this one shipping a stale shadow.

        Neither block wraps, so what this measures is the ring rather than the antimeridian below.
        """
        _drive_small_planet(tmp_path, monkeypatch)
        _age_everything(tmp_path)
        _paint(tmp_path / planet_warp.HEIGHT_3857, 96, 124)
        attempted = _drive_small_planet(tmp_path, monkeypatch)
        assert "r01c02" in attempted, "the block whose ring reaches the change must re-render"
        assert set(attempted) == {"r01c01", "r01c02"}

    def test_a_change_across_the_antimeridian_restages_the_first_column(self, tmp_path, monkeypatch):
        """The planet joins itself in longitude, and `prep_block._read_cyclic` wraps for it, so
        r01c00's ring reads the far side of the grid. A cover that clipped at the edge instead would
        skip column 0 for a change it actually renders, and nothing on the frame would show it."""
        _drive_small_planet(tmp_path, monkeypatch)
        _age_everything(tmp_path)
        _paint(tmp_path / planet_warp.HEIGHT_3857, 96, 244)
        attempted = _drive_small_planet(tmp_path, monkeypatch)
        assert "r01c00" in attempted, "a plane window wraps in longitude and must be read wrapped"
        assert set(attempted) == {"r01c00", "r01c03"}

    def test_a_change_at_the_south_edge_does_not_restage_the_north_row(self, tmp_path, monkeypatch):
        """The control for the wrap above, and the asymmetry it rests on: rows CLAMP where columns
        wrap, because a Mercator planet does not join itself at the poles. A cover that wrapped both
        axes alike passes the antimeridian test and re-renders the far pole for nothing."""
        _drive_small_planet(tmp_path, monkeypatch)
        _age_everything(tmp_path)
        _paint(tmp_path / planet_warp.HEIGHT_3857, 250, 96)
        attempted = _drive_small_planet(tmp_path, monkeypatch)
        assert "r00c01" not in attempted, "the north row reads no ground from the south row"
        assert set(attempted) == {"r03c01"}

    def test_an_identical_rewrite_restages_nothing(self, tmp_path, monkeypatch):
        """A re-warp that lands the same pixels moves an mtime and no ground, and today it costs a
        whole night of Cycles to emit the planet already on disk."""
        _drive_small_planet(tmp_path, monkeypatch)
        _age_everything(tmp_path)
        _write_small_raster(tmp_path / planet_warp.HEIGHT_3857)
        assert _drive_small_planet(tmp_path, monkeypatch) == []

    def test_a_declared_layers_raster_going_missing_restages_its_readers(self, tmp_path,
                                                                        monkeypatch):
        """The one no mtime can see, and it fails in the direction that ships.

        `newest_mtime` scores an absent path 0.0, so deleting a warped layer moves nothing at all
        and every marker goes on vouching for pixels painted with it. The prep reads a layer only
        where its raster is on disk, so the next render of any block would drop it silently.
        """
        layer = _an_earth_block_layer()
        _write_small_raster(layer.warped_in(tmp_path), fill=40)
        _drive_small_planet(tmp_path, monkeypatch)
        _age_everything(tmp_path)
        layer.warped_in(tmp_path).unlink()
        assert len(_drive_small_planet(tmp_path, monkeypatch)) == 16, \
            f"{layer.name}'s raster left the store and no block noticed"


class TestAPartialRunProvesWhatItIsAboutToSkip:
    """Nothing in a file can see the render code, Blender, the driver or Cycles' own noise, so the
    only instrument that can is a skipped block rendered again against the planet on disk.

    A disagreement stops the run and reports it rather than falling back to rendering the planet. A
    fallback spends a night hiding the fact that the cheap check was wrong about something, and the
    planet that then ships is the one nobody looked at.
    """

    def _partial(self, tmp_path, monkeypatch, **kwargs):
        """A run owing one block and skipping fifteen, which is the state the sample exists for."""
        _drive_small_planet(tmp_path, monkeypatch)
        _age_everything(tmp_path)
        _paint(tmp_path / planet_warp.HEIGHT_3857, 96, 96)
        return _drive_small_planet(tmp_path, monkeypatch, **kwargs)

    def test_a_run_that_would_skip_blocks_samples_them_first(self, tmp_path, monkeypatch):
        sampled: list[list[str]] = []
        assert self._partial(tmp_path, monkeypatch, sampled=sampled) == ["r01c01"]
        assert len(sampled) == 1 and sampled[0] and "r01c01" not in sampled[0], \
            "the sample is of what the run would skip, so the block it owes is not one of them"

    def test_a_disagreeing_sample_stops_the_run_before_any_block(self, tmp_path, monkeypatch):
        assert self._partial(tmp_path, monkeypatch,
                             sample=["r00c00 p99 9 DN, worst 40 DN"]) == []

    def test_a_stopped_run_leaves_the_planet_exactly_as_it_was(self, tmp_path, monkeypatch):
        """Stop and report means change nothing. A run that unstamped the mosaic on its way out
        would leave every later cut refusing a planet no worse than before it started."""
        self._partial(tmp_path, monkeypatch, sample=["r00c00 p99 9 DN, worst 40 DN"])
        assert freshness.done_marker((tmp_path / cut_tiles.PLANET_RGB).resolve()).exists()

    def test_a_first_pass_has_nothing_to_sample(self, tmp_path, monkeypatch):
        """It disarms itself on a full pass rather than needing a flag: with no block skipped there
        is nothing whose skipping could be wrong, and the sample would be GPU spent on nothing."""
        sampled: list[list[str]] = []
        _drive_small_planet(tmp_path, monkeypatch, sampled=sampled)
        assert sampled == []

    def test_a_named_subset_is_the_operators_and_is_not_sampled(self, tmp_path, monkeypatch):
        """`--only` never stamps the mosaic, so it cannot ship a planet at all, and its blocks were
        picked by hand rather than by the digest."""
        _drive_small_planet(tmp_path, monkeypatch)
        _age_everything(tmp_path)
        _paint(tmp_path / planet_warp.HEIGHT_3857, 96, 96)
        sampled: list[list[str]] = []
        _drive_small_planet(tmp_path, monkeypatch, sampled=sampled, only=frozenset({"r01c01"}))
        assert sampled == []


class TestTheSampleIsPickedByWhatEachBlockHolds:
    """A change that moves only the polar rows is invisible to every mid-latitude block, and a
    sample picked by convenience proves nothing about the planet it lets through."""

    def _blocks(self):
        return [_small_block(row, column) for row in range(4) for column in range(4)]

    def _cells(self, reach) -> dict[str, "block_freshness.InputCells | None"]:
        """One input reaching exactly the cells named, on the small planet's own cell grid."""
        edge = SMALL_GRID_PX // SMALL_CELL_PX
        nonzero = np.zeros((edge, edge), dtype=bool)
        for row, column in reach:
            nonzero[row, column] = True
        return {"ice.tif": block_freshness.InputCells(
            "ice.tif", SMALL_GRID_PX, SMALL_GRID_PX, SMALL_CELL_PX,
            np.zeros((edge, edge), dtype=np.uint64), nonzero)}

    def test_both_edge_rows_are_represented(self, ):
        """The plane overhangs the grid only at the poles, so those two rows are the ones a change
        to the overhang moves and every other block is blind to it."""
        blocks = self._blocks()
        picked = block_render.sample_for(blocks, blocks, self._cells([]), 4)
        assert {0, 3} <= {block.row0 // block.size_px for block in picked}

    def test_a_block_holding_a_layer_is_not_stood_in_for_by_one_that_does_not(self):
        blocks = self._blocks()
        picked = block_render.sample_for(blocks, blocks, self._cells([(6, 6)]), 3)
        assert "r01c01" in {block_render.block_name(block) for block in picked}

    def test_the_sample_is_capped_at_what_was_asked_for(self):
        blocks = self._blocks()
        assert len(block_render.sample_for(blocks, blocks, self._cells([]), 5)) == 5

    def test_a_sample_wider_than_what_is_skipped_is_what_is_skipped(self):
        """A run skipping three blocks samples three, rather than looping on empty groups."""
        blocks = self._blocks()
        assert len(block_render.sample_for(blocks, blocks[:3], self._cells([]), 12)) == 3
