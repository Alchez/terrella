"""The block runner: what its resume trusts, what its recipe can see, and what it refuses to do.

Every guard here is about a claim that is silent when it is wrong. A resume that trusts the wrong
markers re-renders nothing and republishes last week's pixels; a recipe that cannot see a constant
leaves a stale planet reading fresh forever; a mosaic stamped complete while it is half written
sends the tile cut at a planet that is half one producer and half the other. None of those raise.
"""

import json
import os
import time
from typing import ClassVar

import numpy as np
import pytest

from pipeline import block_plan, bodies, freshness, layers, planet_seam
from pipeline.block_plan import Block
from pipeline.look import palette
from pipeline.raster_io import GTIFF_CREATE
from pipeline.render import render_seam
from pipeline.tile import block_render, producer_seam, shade_planet


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
        for layer in layers.WARPED_LAYERS:
            assert layer.warped_in(tmp_path) in deps

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
        _declare_planet_rasters(monkeypatch)

    def _params(self, body=bodies.EARTH, blocks=None):
        return block_render.params(body, planet_seam.declared(body),
                                   palette.look_for(body.name), block_render.rig_recipe(body),
                                   self.BLOCKS if blocks is None else blocks)

    def test_a_rig_constant_moving_moves_the_recipe(self):
        """The whole reason the rig's constants are serialised rather than left to source mtimes:
        a look change has to restage the render, and a checkout must not."""
        rig = block_render.rig_recipe(bodies.EARTH)
        moved = {**rig, "SAMPLES": rig["SAMPLES"] // 2}
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
        _declare_planet_rasters(monkeypatch)
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
        _declare_planet_rasters(monkeypatch)
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
        _declare_planet_rasters(monkeypatch)
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
    """`run` driven over a stand-in renderer, so the ordering it owns is provable without a GPU.

    What is being checked is `run`'s own arithmetic — which blocks are attempted, and whether the
    mosaic ends up stamped — not the stand-in's. The stamp is the dangerous one: `tiles_are_fresh`
    keys on it, so a partial planet that stamps itself is a pyramid cut from half a producer.
    """

    def _drive(self, tmp_path, monkeypatch, *, blocks=3, **kwargs):
        _declare_planet_rasters(monkeypatch)
        # The disk floor is sized for a whole planet and these blocks stand in for one, so on any
        # ordinary scratch filesystem it would abort before the loop this class is about. It has
        # its own guards above; here it is held out of the way rather than left to fire.
        monkeypatch.setattr(block_render, "free_bytes", lambda path: 1 << 60)
        planned = [_block(0, column) for column in range(blocks)]
        attempted: list[str] = []

        def _fake_render(body, block, mosaic, scratch, markers):
            attempted.append(block_render.block_name(block))
            (markers / block_render.block_name(block)).write_text("margin 0\n")

        monkeypatch.setattr(block_render, "plan_blocks", lambda body, work: planned)
        monkeypatch.setattr(block_render, "ensure_mosaic", lambda mosaic, body: None)
        monkeypatch.setattr(block_render, "render_block", _fake_render)
        _stage_warped_inputs(tmp_path)
        mosaic = tmp_path / "planet_rgb.tif"
        mosaic.write_bytes(b"")
        return attempted, mosaic, block_render.run(bodies.EARTH, tmp_path, mosaic, **kwargs)

    def test_a_whole_planet_stamps_the_mosaic(self, tmp_path, monkeypatch):
        attempted, mosaic, rendered = self._drive(tmp_path, monkeypatch)
        assert rendered == 3 and attempted == ["r00c00", "r00c01", "r00c02"]
        assert freshness.done_marker(mosaic).exists()

    def test_a_limited_run_renders_but_does_not_stamp(self, tmp_path, monkeypatch):
        attempted, mosaic, rendered = self._drive(tmp_path, monkeypatch, limit=2)
        assert rendered == 2 and len(attempted) == 2
        assert not freshness.done_marker(mosaic).exists()

    def test_limit_zero_renders_nothing_at_all(self, tmp_path, monkeypatch):
        """`--limit 0` MUST mean none, and it is the falsy value: a truthiness test reads it as no
        limit and starts the whole planet. That exact shape has breached this project's one-heavy-
        job rule before, from a different flag."""
        attempted, mosaic, rendered = self._drive(tmp_path, monkeypatch, limit=0)
        assert rendered == 0 and attempted == []
        assert not freshness.done_marker(mosaic).exists()

    def test_a_named_subset_never_stamps_even_when_all_of_it_renders(self, tmp_path, monkeypatch):
        """The subset finished; the planet did not. Completion is asked of the grid, never of the
        selection, or `--only` on one block would declare a planet done."""
        attempted, mosaic, rendered = self._drive(tmp_path, monkeypatch,
                                                 only=frozenset({"r00c01"}))
        assert rendered == 1 and attempted == ["r00c01"]
        assert not freshness.done_marker(mosaic).exists()

    def test_a_block_that_is_not_on_the_grid_is_refused(self, tmp_path, monkeypatch):
        """A typo in `--only` would otherwise render nothing and report success."""
        with pytest.raises(SystemExit, match="no such block"):
            self._drive(tmp_path, monkeypatch, only=frozenset({"r99c99"}))


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
    whether they are there, and a test that wrote real ones would be testing rasterio."""
    for name in (shade_planet.HEIGHT_3857, shade_planet.OCEAN_3857, shade_planet.WATER_3857):
        (tmp_path / name).write_bytes(b"")


#: What each body's planet producer really declares, keyed by body name.
#:
#: A LITERAL, and the one place in this file that spells it. `planet_seam.declared` reads the
#: producer's own declaration off disk, so there is no registry answer to derive this from — the set
#: is a production fact. Stating it once means a body whose producer starts emitting more raster is
#: one edit here, rather than a hunt through every class that builds a recipe.
_DECLARED_RASTERS = {
    "earth": frozenset(planet_seam.KNOWN_RASTERS),
    # `relabel_mars` declares the heightfield alone: Mars has no sea, so no mask classifies one.
    "mars": frozenset({"heightfield"}),
}


def _declare_planet_rasters(monkeypatch):
    """Answer the planet seam from the table above rather than from this machine's store, so these
    guards run in a checkout with no data at all.

    THE MODE THIS FILE IS ACTUALLY RUN IN BY ANYONE BUT THE MAINTAINER, and the reason it is a
    helper rather than a line: five recipe tests called `declared` directly, passed on the box that
    has the store, and went red on CI where `data/` is empty. A store read is invisible locally.
    """
    monkeypatch.setattr(block_render.planet_seam, "declared",
                        lambda body: _DECLARED_RASTERS[body.name])


class TestTheFakeDeclarationMatchesTheRealOne:
    """The stand-in above is a hand-written copy of a production fact, so it can drift — and drift
    here is silent in the worst direction: every recipe test would keep passing against a set no
    producer emits any more.

    SKIPPED RATHER THAN FAKED WHERE THE STORE IS ABSENT, which is the pattern this file should have
    followed to begin with: on a machine with no `data/` there is nothing to compare against, and a
    test that invented one would be checking the copy against itself. On the maintainer's box, and
    on any machine that has run the planet stage, it is a real comparison.
    """

    @pytest.mark.parametrize("body", [bodies.EARTH, bodies.MARS])
    def test_the_table_is_what_the_producer_declared(self, body):
        if not planet_seam.declaration_path(body).exists():
            pytest.skip(f"{body.name}'s planet stage has not run on this machine (CI)")
        assert _DECLARED_RASTERS[body.name] == planet_seam.declared(body)

    def test_every_registered_body_has_an_entry(self):
        """Derived from the registry, not listed: a third planet must fail here rather than at
        whichever recipe test happens to name it first."""
        assert set(_DECLARED_RASTERS) == set(bodies.BODIES)


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
