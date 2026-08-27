"""The block runner: what its resume trusts, what its recipe can see, and what it refuses to do.

Every guard here is about a claim that is silent when it is wrong. A resume that trusts the wrong
markers re-renders nothing and republishes last week's pixels; a recipe that cannot see a constant
leaves a stale planet reading fresh forever; a mosaic stamped complete while it is half written
sends the tile cut at a planet that is half one producer and half the other. None of those raise.
"""

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import numpy as np
import pytest
from conftest import declare_planet_rasters

from pipeline import block_plan, bodies, freshness, layers, planet_seam
from pipeline.block_plan import Block
from pipeline.look import layer_producers, palette, seaice, snow
from pipeline.raster_io import GTIFF_CREATE
from pipeline.render import prep_block, render_seam
from pipeline.tile import block_render, producer_seam, relief_scan, shade_planet


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


class TestTheGenerationStampIsNotAFreshnessMarker:
    """`is_stale` is the wrong predicate here and this is what would go wrong if it were used.

    Its load-bearing clause is that an output REWRITTEN since its stamp is stale, which catches a
    crashed half-written raster. The marker directory is written into after its stamp on purpose —
    that is what a resume IS — so the same clause would call a healthy run stale on its second
    block and re-render the planet from the top, every time, forever.
    """

    def test_a_directory_written_into_after_its_stamp_is_still_current(self, tmp_path):
        markers, dependency = tmp_path / "blocks", tmp_path / "recipe.json"
        dependency.write_text("{}")
        _stale_by_a_second(dependency)
        block_render.start_generation(markers, tmp_path / "planet_rgb.tif")
        (markers / "r00c00").write_text("margin 0\n")
        assert block_render.generation_is_current(markers, (dependency,))

    def test_is_stale_would_have_called_that_same_state_stale(self, tmp_path):
        """The positive control for the paragraph above: the rejected predicate, on the state the
        accepted one just passed. Without this the docstring is an assertion about code nobody ran.
        """
        markers, dependency = tmp_path / "blocks", tmp_path / "recipe.json"
        dependency.write_text("{}")
        _stale_by_a_second(dependency)
        block_render.start_generation(markers, tmp_path / "planet_rgb.tif")
        freshness.mark_done(markers)
        _stale_by_a_second(freshness.done_marker(markers))
        (markers / "r00c00").write_text("margin 0\n")
        assert freshness.is_stale(markers, dependency)

    def test_an_input_moving_after_the_stamp_ends_the_generation(self, tmp_path):
        markers, dependency = tmp_path / "blocks", tmp_path / "recipe.json"
        dependency.write_text("{}")
        block_render.start_generation(markers, tmp_path / "planet_rgb.tif")
        _stale_by_a_second(block_render.generation_stamp(markers))
        assert not block_render.generation_is_current(markers, (dependency,))

    def test_no_stamp_at_all_is_not_a_generation(self, tmp_path):
        markers = tmp_path / "blocks"
        markers.mkdir()
        (markers / "r00c00").write_text("margin 0\n")
        assert not block_render.generation_is_current(markers, ())


class TestStartingAGenerationUnstampsTheMosaic:
    """THE ORDER THE PYRAMID DEPENDS ON. `tiles_are_fresh` keys on the mosaic's `.done` marker, so
    a mosaic left stamped while it is rewritten block by block would let a cut run against a planet
    that is part composite and part raytrace, with every gate green."""

    def test_the_mosaics_completion_marker_is_removed(self, tmp_path):
        mosaic = tmp_path / "planet_rgb.tif"
        mosaic.write_bytes(b"")
        freshness.mark_done(mosaic)
        block_render.start_generation(tmp_path / "blocks", mosaic)
        assert not freshness.done_marker(mosaic).exists()

    def test_every_marker_of_the_previous_generation_is_cleared(self, tmp_path):
        markers = tmp_path / "blocks"
        markers.mkdir()
        (markers / "r00c00").write_text("margin 0\n")
        block_render.start_generation(markers, tmp_path / "planet_rgb.tif")
        assert not (markers / "r00c00").exists()
        assert block_render.generation_stamp(markers).exists()


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

    THE PRICE IS THE WHOLE PLANET, and it is silent. The recipe is in `raytrace_deps`, so an A/B
    moves it, the next production pass moves it back, `generation_is_current` reads False and
    `start_generation` clears every marker: a night of Cycles to emit the pixels already on disk.
    The line the runner logs for that is true and reads as ordinary operation.

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

    def test_an_ab_does_not_claim_the_raster_it_did_not_write(self, tmp_path, monkeypatch):
        """The declaration's subject is the work directory's CANONICAL raster, and an A/B does not
        produce it. `composite_planet` already guards its own on exactly this question, writing one
        only when `planet_rgb.tif` is among its outputs.

        THE BODY THAT WILL BE IN THIS STATE IS MARS, whose canonical raster is composited and
        shipping while the raytrace is being judged against it. Earth stands in because Mars's seam
        is refused before any block until the rig reads `render_seam.declared`; the assertion is
        about the declaration, which is the same on either body.

        NOTHING DECLARES THE A/B'S OWN RASTER AND NOTHING SHOULD. The stamp exists because two
        producers share one output; a second mosaic has one producer, and its own recipe beside it
        names which.
        """
        producer_seam.declare(tmp_path, "composite")
        _drive_planet(tmp_path, monkeypatch, mosaic=self._ab(tmp_path), blocks=3)
        assert producer_seam.declared(tmp_path) == "composite"

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
        spelled = tmp_path / "sub" / ".." / shade_planet.PLANET_RGB
        sidecars = block_render.sidecars_for(tmp_path, spelled)
        assert sidecars.canonical
        assert sidecars.recipe == tmp_path.resolve() / block_render.PARAMS_NAME
        assert sidecars.markers == block_render.markers_in(block_render.mosaic_in(tmp_path))

    def test_the_shipping_raster_keeps_the_bare_sidecar_names(self, tmp_path, monkeypatch):
        """A PIN ON THE NAMING RATHER THAN A DEFECT, and the reason the fix above costs nothing.

        Naming every mosaic's sidecar after its stem is the tidier rule and renames the two files
        the finished Earth pass left on disk, which moves an mtime — the same night this class
        exists to prevent, paid once on the way in. So the canonical raster's name elides, as
        `composite_planet`'s default variant and `capsManifestUrl`'s empty prefix both already do.
        """
        _drive_planet(tmp_path, monkeypatch, blocks=2)
        assert (tmp_path / block_render.PARAMS_NAME).exists()
        assert (tmp_path / block_render.STATUS_NAME).exists()


class TestTheDependencySetIsTheRaytracesAndNotTheComposites:
    """The switch replaces one raster's producer, so the two producers' dependency lists must
    differ in exactly the terms the switch removes. Sharing `composite_deps` would leave a body
    moved between producers with its old pixels looking fresh against inputs it no longer reads."""

    def test_the_hillshade_is_not_a_raytrace_dependency(self, tmp_path):
        """Cycles computes its own light; `hs_3857` reaches no raytraced pixel."""
        deps = block_render.raytrace_deps(tmp_path, tmp_path / block_render.PARAMS_NAME)
        assert not any("hs" == path.stem or path.name.startswith("hs_") for path in deps)

    def test_the_composites_recipe_is_not_a_raytrace_dependency(self, tmp_path):
        deps = block_render.raytrace_deps(tmp_path, tmp_path / block_render.PARAMS_NAME)
        assert not any(path.name == "composite_params.json" for path in deps)

    def test_the_warped_inputs_the_prep_cuts_from_are_all_tracked(self, tmp_path):
        """The block prep reads exactly these, so a re-warp — a re-fuse, a new NSIDC or RGI —
        has to restage the planet."""
        deps = set(block_render.raytrace_deps(tmp_path, tmp_path / block_render.PARAMS_NAME))
        for name in (shade_planet.HEIGHT_3857, shade_planet.OCEAN_3857, shade_planet.WATER_3857):
            assert tmp_path / name in deps
        for layer in layers.warped_for(layers.BLOCK_LAYERS):
            assert layer.warped_in(tmp_path) in deps
        # THE OTHER DIRECTION, and it is the one that is silent: a dependency list built from the
        # composite's set would restage every block when a layer this tier cannot read moves.
        for layer in layers.LAYERS:
            if layer.warped_basename and layer.name not in layers.BLOCK_LAYERS:
                assert layer.warped_in(tmp_path) not in deps

    def test_the_recipe_itself_is_a_dependency(self, tmp_path):
        recipe = tmp_path / block_render.PARAMS_NAME
        assert recipe in block_render.raytrace_deps(tmp_path, recipe)


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
        return block_render.params(body, planet_seam.declared(body),
                                   palette.look_for(body.name), block_render.rig_recipe(body),
                                   self.BLOCKS if blocks is None else blocks)

    def test_a_rig_constant_moving_moves_the_recipe(self):
        """The whole reason the rig's constants are serialised rather than left to source mtimes:
        a look change has to restage the render, and a checkout must not."""
        rig = block_render.rig_recipe(bodies.EARTH)
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
        assert json.loads(self._params())["exaggeration"] == bodies.EARTH.exaggeration
        assert json.loads(self._params(bodies.MARS))["exaggeration"] == bodies.MARS.exaggeration

    def test_a_layer_switched_off_is_recorded_rather_than_merely_absent(self):
        """The conditional-record idiom, and the direction that is silent without it: a path that
        is not there scores 0.0 in an mtime comparison, so turning sea ice off would otherwise
        leave a planet painted with it looking perfectly current."""
        mars = json.loads(self._params(bodies.MARS))
        assert mars["layers_off"] == layers.layers_off(bodies.MARS, layers.BLOCK_LAYERS)
        assert mars["layers_off"], "Mars declares fewer block layers than Earth; if this is empty "\
                                   "the assertion above can no longer tell a read from a constant"


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
        return block_render.params(body, planet_seam.declared(body),
                                   palette.look_for(body.name), block_render.rig_recipe(body),
                                   self.BLOCKS)

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
    """Stands in for the module, so the crop is provable without a PNG on disk."""

    def __init__(self, frame):
        self._frame = frame

    def open(self, *args, **kwargs):
        frame = self._frame

        class _Reader:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return frame

        return _Reader()


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


class TestTheRunnerStopsWhenTheMosaicIsAlreadyCurrent:
    """The shipping path's early return, exercised rather than assumed: a fresh planet must cost a
    plan and a stat, never a night. Planning is what the recipe is computed FROM, so it runs first
    now; what must not run is a single Blender invocation."""

    def test_a_fresh_mosaic_renders_nothing(self, tmp_path, monkeypatch):
        """The recipe is already on disk holding exactly what this run would write, which is the
        second-run state: `write_if_changed` moves no mtime, so the stamp stays the newest thing.

        THE PRODUCER DECLARATION IS PART OF THAT STATE and has to be staged with the rest of it.
        `run` declares the raytrace before asking its freshness question, so a work directory that
        has never been declared is a FIRST run however fresh everything else looks — the declaration
        lands newer than the marker and every block correctly re-renders."""
        declare_planet_rasters(monkeypatch)
        planned = [_block(0, column) for column in range(3)]
        monkeypatch.setattr(block_render, "plan_blocks", lambda body, work: planned)
        _stage_warped_inputs(tmp_path)
        (tmp_path / block_render.PARAMS_NAME).write_text(block_render.params(
            bodies.EARTH, planet_seam.declared(bodies.EARTH), palette.look_for("earth"),
            block_render.rig_recipe(bodies.EARTH), planned))
        producer_seam.declare(tmp_path, "raytrace")
        mosaic = tmp_path / "planet_rgb.tif"
        mosaic.write_bytes(b"")
        freshness.mark_done(mosaic)
        assert block_render.run(bodies.EARTH, tmp_path, mosaic) == 0

    def test_a_mosaic_the_other_producer_made_is_not_fresh(self, tmp_path, monkeypatch):
        """The switch, from this side, and the reason the declaration is a dependency at all.

        Everything is identical to the test above except who last claimed the raster. A composited
        planet is newer than every warp source and newer than this producer's recipe, so without the
        stamp this run would report it fresh and publish composited pixels under a raytrace recipe.
        """
        declare_planet_rasters(monkeypatch)
        monkeypatch.setattr(block_render, "plan_blocks", _stop_here)
        _stage_warped_inputs(tmp_path)
        producer_seam.declare(tmp_path, "composite")
        mosaic = tmp_path / "planet_rgb.tif"
        mosaic.write_bytes(b"")
        freshness.mark_done(mosaic)
        with pytest.raises(SystemExit, match="reached the plan"):
            block_render.run(bodies.EARTH, tmp_path, mosaic)

    def test_a_moved_input_is_not_fresh(self, tmp_path, monkeypatch):
        """The other direction, so the test above cannot pass by the predicate always saying yes."""
        declare_planet_rasters(monkeypatch)
        monkeypatch.setattr(block_render, "plan_blocks", _stop_here)
        mosaic = tmp_path / "planet_rgb.tif"
        mosaic.write_bytes(b"")
        freshness.mark_done(mosaic)
        _stale_by_a_second(freshness.done_marker(mosaic))
        _stale_by_a_second(mosaic)
        _stage_warped_inputs(tmp_path)
        with pytest.raises(SystemExit, match="reached the plan"):
            block_render.run(bodies.EARTH, tmp_path, mosaic)


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
        with pytest.raises(SystemExit, match=shade_planet.HEIGHT_3857):
            block_render.check_inputs(tmp_path, bodies.EARTH, self.FEEDS_THE_RIG)

    def test_the_error_names_the_stage_that_builds_them(self, tmp_path):
        """An error that says what is missing and not how to fix it costs the reader two tiers."""
        with pytest.raises(SystemExit, match="planet_pass"):
            block_render.check_inputs(tmp_path, bodies.EARTH, self.FEEDS_THE_RIG)

    def test_a_body_that_declares_no_ocean_is_not_asked_for_an_oceanmask(self, tmp_path):
        """The declaration decides, never the disk: asking every body for every raster would make
        a sea-less planet unrenderable, and sniffing the disk cannot tell 'has none' from 'died'.

        THE OCEANMASK IS THE ONE THIS STILL HOLDS FOR, and the watermask is not: `images_for` drops
        the sea image for a look with no sea, so a block without one is a scene the rig will build.
        """
        (tmp_path / shade_planet.HEIGHT_3857).write_bytes(b"")
        (tmp_path / shade_planet.WATER_3857).write_bytes(b"")
        block_render.check_inputs(tmp_path, bodies.EARTH, self.FEEDS_THE_RIG)

    def test_a_body_that_does_declare_one_may_not_start_without_it(self, tmp_path):
        (tmp_path / shade_planet.HEIGHT_3857).write_bytes(b"")
        with pytest.raises(SystemExit, match=shade_planet.WATER_3857):
            block_render.check_inputs(tmp_path, bodies.EARTH, self.FEEDS_THE_RIG)


class TestASeamThatCannotFeedTheRigIsRefusedBeforeAnyBlock:
    """The same misattributed failure one tier up, and the one a producer switch actually hits.

    A planet declaring no watermask is not asked for a file it never had, so every raster check
    passes — and then every block fails inside Blender on `inlandlake.png`, eight times, under the
    message that says the GPU is gone. Mars is that planet today.
    """

    def test_mars_seam_is_refused_by_name(self, tmp_path):
        _stage_warped_inputs(tmp_path)
        with pytest.raises(SystemExit, match="watermask"):
            block_render.check_inputs(tmp_path, bodies.MARS, frozenset({"heightfield"}))

    def test_the_refusal_names_both_images_no_block_can_carry(self):
        assert block_render.unsuppliable_rig_images(frozenset({"heightfield"})) == [
            render_seam.INLANDLAKE, render_seam.RIVER]

    def test_a_seam_with_a_watermask_supplies_them_all(self):
        """The anti-vacuity half: a refusal that fired for every seam would prove nothing."""
        assert block_render.unsuppliable_rig_images(frozenset({"heightfield", "watermask"})) == []

    def test_the_oceanmask_is_not_among_them(self):
        """It is the one mandatory image a LOOK answers for, and that rule lives in `scene_build`,
        which this interpreter cannot import. Demanding it here would refuse every sea-less body."""
        assert render_seam.OCEANMASK not in block_render.unsuppliable_rig_images(
            frozenset({"heightfield"}))


def _stage_warped_inputs(tmp_path):
    """The warped rasters the block prep cuts from, as empty files: `check_inputs` asks only
    whether they are there, and a test that wrote real ones would be testing rasterio.

    ONE THAT IS ALREADY THERE IS LEFT ALONE, because a test that drives two runs over one work
    directory would otherwise move an input's mtime between them and restage the second by its own
    setup — which reads exactly like the defect such a test is looking for.
    """
    for name in (shade_planet.HEIGHT_3857, shade_planet.OCEAN_3857, shade_planet.WATER_3857):
        if not (tmp_path / name).exists():
            (tmp_path / name).write_bytes(b"")


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

    def _fake_render(body, block, mosaic, scratch, markers):
        attempted.append(block_render.block_name(block))
        scratches.add(scratch)
        (markers / block_render.block_name(block)).write_text("margin 0\n")

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
                           scratches=scratches)


def _stop_here(*args, **kwargs):
    raise SystemExit("reached the plan")


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

        A re-cut mask does not restage a rendered block: blocks are skipped by marker existence and
        `raytrace_deps` tracks planet rasters rather than the per-block prep directory. So without
        this key, changing the depth reaches only the blocks that were going to render anyway and
        leaves every finished one carrying whatever the old depth produced.
        """
        recipe = json.loads(block_render.params(
            bodies.EARTH, frozenset(planet_seam.KNOWN_RASTERS), palette.EARTH_LOOK,
            {"SAMPLES": 4096}, [Block(col0=0, row0=0, size_px=2048, context_px=128)]))
        assert recipe["mask_full_scale"] == prep_block.MASK_FULL_SCALE

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
        unchanged by it, so `raytrace_deps` sees nothing move."""
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
        a block pixel — and reaches freshness only here. `raytrace_deps` tracks planet rasters, not
        the prep directory, and blocks skip on marker existence, so without this a re-tuned white
        would leave every finished block wearing the old colour with every gate green.
        """
        before = self._params()
        monkeypatch.setattr(palette, "SNOW_RGB", (1, 2, 3))
        assert self._params() != before, \
            "a white the rig now paints from must restage the blocks that were painted with it"

    def test_a_body_whose_producers_grade_nothing_still_records_its_white(self):
        """Mars: nothing to GRADE and a white to PAINT, which are separate halves of the recipe.

        Its `contribution_recipe` is empty on the conditional-record idiom, while its paint is two
        measured pairs — one per pole, since the deposits are different colours. A raytraced Mars
        that recorded Earth's shape here would be recording a white no Martian pixel is painted in.
        """
        graded = {key for _layer, producer in self._in_block_producers(bodies.MARS)
                  for key in producer.contribution_recipe()}
        assert not graded, f"Mars grades with {graded}; this test's premise has moved"
        recorded = json.loads(self._params(bodies.MARS))
        assert "snow_rgb_north" in recorded and "snow_rgb_south" in recorded, \
            "Mars paints its polar ice from its own registry, so both whites must be tracked"
        assert recorded["snow_rgb_north"] != recorded["snow_rgb_south"], \
            "the two poles were measured separately; one value here means the pair collapsed"
