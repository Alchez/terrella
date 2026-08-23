"""The composite tier's surface-layer producers: who is registered, what they read, what they paint.

The tile-side twin of `test_perennial_ice.py`. Two questions dominate: whether the warp gate asks
the BODY before the disk, which is invisible on a box holding Earth's files; and whether each
producer's arithmetic is bit-for-bit what the same lines computed inline before they moved.
"""

import dataclasses
import os

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from pipeline import bodies, freshness, layers, mercator
from pipeline.acquire import download_add_rock
from pipeline.look import lake_depth, layer_producers, mars_ice, palette, seaice, snow
from pipeline.tile import shade_planet

#: A window well south of the Antarctic patch's -60, so the rule that has no dataset behind it is
#: live in every oracle below rather than sitting at zero.
SOUTHERN_TOP, SOUTHERN_BOTTOM = -11_000_000.0, -12_000_000.0
ROWS, COLS = 8, 16


def _triples(paint) -> "set[tuple[int, ...]]":
    """Every distinct RGB a paint can put on a pixel, whether it is one constant or one per row."""
    found: set[tuple[int, ...]] = set()
    for end in paint:
        array = np.asarray(end, dtype=int)
        flat = array.reshape(3, 1) if array.ndim == 1 else array.reshape(3, -1)
        found.update(tuple(int(channel) for channel in flat[:, column])
                     for column in range(flat.shape[1]))
    return found


def _ground_metres_per_px(top, bottom, rows=ROWS):
    """This fixture's per-row ground resolution, derived from its own span.

    Its own, and not Earth's z8 figure, because these windows are 8 rows over a megametre — the
    geometry has to be self-consistent with whatever the fixture declares rather than with the
    planet grid it stands in for.
    """
    return mercator.ground_metres_per_pixel(
        snow.latitude_per_row(top, bottom, rows), (top - bottom) / rows,
        bodies.ground_metres_per_mercator_unit(bodies.EARTH))


def _window(raw, *, land=None, watercode=None, top=SOUTHERN_TOP, bottom=SOUTHERN_BOTTOM):
    latitude = snow.latitude_per_row(top, bottom, ROWS)
    return layer_producers.LayerWindow(
        raw=raw,
        watercode=np.zeros((ROWS, COLS), dtype=np.uint8) if watercode is None else watercode,
        land=np.ones((ROWS, COLS), dtype=bool) if land is None else land,
        latitude=latitude, ground_metres_per_px=_ground_metres_per_px(top, bottom),
        top=top, bottom=bottom)


class TestTheRegistryAndTheLayerDeclarationsAgree:
    """Both directions, because each is silent on its own. A body declaring a layer with no producer
    raises at warp time — loud, but only for whoever runs the pass. A producer registered for a body
    that declares no layer is never called, so it reads as working code describing pixels nobody
    will ever see."""

    def test_every_body_declaring_a_built_layer_has_a_producer(self, subtests):
        declared = [(body, layer) for body in bodies.BODIES.values()
                    for layer in layers.WARPED_LAYERS if layer.name in body.surface_layers]
        assert declared, "no body declares a built layer — this sweep would pass vacuously"
        for body, layer in declared:
            with subtests.test(f"{body.name} {layer.name}"):
                assert layer_producers.producer_for(body, layer)

    def test_no_producer_is_registered_for_a_body_that_declares_no_such_layer(self, subtests):
        for body in bodies.BODIES.values():
            for layer in layers.WARPED_LAYERS:
                if layer.name in body.surface_layers:
                    continue
                with subtests.test(f"{body.name} {layer.name}"):
                    assert (body.name, layer.name) not in layer_producers.PRODUCER_BY_BODY_LAYER

    def test_a_body_with_no_producer_raises_and_names_itself(self):
        """A SYNTHETIC BODY, because both registered planets now hold a producer for this layer.

        Mars supplied the negative instance until its ice landed, and the assertion that used to
        guard that choice is exactly what fired — a guard reading its negative case out of a live
        registry field goes quiet the day the field moves, so the case has to be built here.
        """
        stranger = dataclasses.replace(
            bodies.EARTH, name="stranger", path_prefix="stranger",
            surface_layers=frozenset({layers.PERENNIAL_ICE.name}))
        with pytest.raises(KeyError, match="stranger declares the perennial_ice layer"):
            layer_producers.producer_for(stranger, layers.PERENNIAL_ICE)


class TestWhatAProducerDeclaresItReads:
    def test_the_composite_sources_are_read_at_CALL_time_so_a_redirect_reaches_them(
            self, monkeypatch, tmp_path):
        """The cap registry shipped this bug first and its suite caught it: a tuple literal in the
        registry evaluates its paths once, at import, so a caller that moves the data store is
        answered with the path from before the move. Every path here hangs off `paths.DATA`."""
        moved = tmp_path / "somewhere-else.nc"
        monkeypatch.setattr(snow, "SP_NC", moved)
        producer = layer_producers.producer_for(bodies.EARTH, layers.PERENNIAL_ICE)
        assert producer.sources() == (moved,)

    def test_every_earth_producer_declares_at_least_one_source(self, subtests):
        """Unlike the cap tier, where Earth's south genuinely reads nothing. Every layer here is
        built from a file, so an empty tuple would mean a warp with no dependency — a raster that
        can never go stale because nothing it reads is tracked."""
        for layer in layers.WARPED_LAYERS:
            with subtests.test(layer.name):
                assert layer_producers.producer_for(bodies.EARTH, layer).sources()

    def test_the_warp_consequence_covers_every_built_layer(self):
        """A layer added to the table and forgotten here would raise on the next pass of any body,
        which is the intent — pinned so the set is checked without waiting for a pass."""
        assert set(shade_planet.WARP_CONSEQUENCE) == {
            layer.name for layer in layers.WARPED_LAYERS}


class TestEarthsProducersComputeWhatTheyComputedInline:
    """The oracle for the move: each `contribution` against the expression it was lifted from,
    compared by BYTES rather than by closeness, since the claim is byte-identity and not agreement.
    """

    def test_lake_depth_is_the_old_lakes_only_call(self):
        depth = np.linspace(0.0, 80.0, ROWS * COLS, dtype="float32").reshape(ROWS, COLS)
        watercode = np.tile(np.array([0, 1, 2, 3], dtype=np.uint8), (ROWS, COLS // 4))
        inline = lake_depth.lakes_only(depth, watercode)
        got = layer_producers.producer_for(bodies.EARTH, layers.LAKE_DEPTH).contribution(
            _window(depth, watercode=watercode))
        assert got is not None and inline is not None
        assert got.tobytes() == inline.tobytes()

    def test_perennial_ice_is_the_feathered_snow_alpha_maxed_with_the_antarctic_patch(self):
        packed = np.linspace(0, 10_000, ROWS * COLS, dtype="float32").reshape(ROWS, COLS)
        land = np.ones((ROWS, COLS), dtype=bool)
        latitude = snow.latitude_per_row(SOUTHERN_TOP, SOUTHERN_BOTTOM, ROWS)
        inline = np.maximum(
            snow.soften_source_cells(
                snow.snow_alpha(snow.unpack_persistence(packed), SOUTHERN_TOP, SOUTHERN_BOTTOM),
                _ground_metres_per_px(SOUTHERN_TOP, SOUTHERN_BOTTOM)),
            snow.antarctic_snow_mask(land, latitude))
        got = layer_producers.producer_for(bodies.EARTH, layers.PERENNIAL_ICE).contribution(
            _window(packed, land=land))
        assert got is not None
        assert got.dtype == np.float64, "a float32 result would narrow every pixel composite blends"
        assert got.tobytes() == inline.tobytes()

    def test_perennial_ice_without_its_raster_is_still_the_antarctic_patch(self):
        """The half with no file behind it. `snow_a` used to start as float64 zeros and take the
        patch as a maximum, so the dtype is part of what this reproduces."""
        land = np.ones((ROWS, COLS), dtype=bool)
        latitude = snow.latitude_per_row(SOUTHERN_TOP, SOUTHERN_BOTTOM, ROWS)
        inline = np.maximum(np.zeros((ROWS, COLS), dtype=float),
                            snow.antarctic_snow_mask(land, latitude))
        got = layer_producers.producer_for(bodies.EARTH, layers.PERENNIAL_ICE).contribution(
            _window(None, land=land))
        assert got is not None
        assert got.tobytes() == inline.tobytes()

    def test_glaciers_is_the_old_astype_float(self):
        mask = np.tile(np.array([0, 1], dtype=np.uint8), (ROWS, COLS // 2))
        got = layer_producers.producer_for(bodies.EARTH, layers.GLACIERS).contribution(_window(mask))
        assert got is not None
        assert got.tobytes() == mask.astype(float).tobytes()

    def test_sea_ice_is_the_old_toned_smoothstep(self):
        packed = np.linspace(0, 10_000, ROWS * COLS, dtype="float32").reshape(ROWS, COLS)
        latitude = snow.latitude_per_row(SOUTHERN_TOP, SOUTHERN_BOTTOM, ROWS)
        frequency = seaice.unpack_seaice(packed)
        inline = np.where(
            (latitude < 0.0)[:, None],
            seaice.ice_alpha(frequency, ice_lo=seaice.SH_ICE_LO,
                             ice_max_alpha=seaice.SH_ICE_MAX_ALPHA),
            seaice.ice_alpha(frequency))
        got = layer_producers.producer_for(bodies.EARTH, layers.SEA_ICE).contribution(
            _window(packed))
        assert got is not None
        assert got.tobytes() == inline.tobytes()

    def test_a_northern_window_takes_the_untoned_alpha(self):
        """The companion that shows the hemisphere split above can FAIL rather than being a `where`
        that always picks one branch."""
        packed = np.full((ROWS, COLS), 9_000.0, dtype="float32")
        got = layer_producers.producer_for(bodies.EARTH, layers.SEA_ICE).contribution(
            _window(packed, top=8_000_000.0, bottom=7_000_000.0))
        assert got is not None
        assert got.tobytes() == seaice.ice_alpha(seaice.unpack_seaice(packed)).tobytes()


class TestTheSnowUnionIsUnchangedByTheMove:
    """`_compute_shared` used to chain three maxima in one order; the patch now rides inside the
    perennial-ice producer, so the order changed. `np.maximum` reorders freely and every
    contribution is non-negative, and this is that argument executed rather than asserted."""

    def _shared(self, persistence, glacier, top=SOUTHERN_TOP, bottom=SOUTHERN_BOTTOM):
        from rasterio.windows import Window

        raw: dict[str, np.ndarray | None] = {layer.name: None for layer in layers.WARPED_LAYERS}
        raw[layers.PERENNIAL_ICE.name] = persistence
        raw[layers.GLACIERS.name] = glacier
        return shade_planet._compute_shared(shade_planet._WindowInputs(
            win=Window(0, 0, COLS, ROWS),  # pyright: ignore[reportCallIssue]
            win_h=ROWS, win_top=top, win_bottom=bottom,
            height_win=np.zeros((ROWS, COLS), dtype=np.float32),
            ocean_raw=np.zeros((ROWS, COLS), dtype=np.uint8),
            watercode=np.zeros((ROWS, COLS), dtype=np.uint8),
            hs_raw=np.full((ROWS, COLS), 128, dtype=np.uint8),
            layer_raw=raw, occ_win=np.zeros((ROWS, COLS), dtype=np.float32),
            body=bodies.EARTH))

    def test_the_three_contributions_max_to_the_old_chained_expression(self):
        persistence = np.linspace(0, 10_000, ROWS * COLS, dtype="float32").reshape(ROWS, COLS)
        glacier = np.tile(np.array([0, 1], dtype=np.uint8), (ROWS, COLS // 2))
        land = np.ones((ROWS, COLS), dtype=bool)
        latitude = snow.latitude_per_row(SOUTHERN_TOP, SOUTHERN_BOTTOM, ROWS)
        # The pre-refactor order, verbatim: snow alpha, then glaciers, then the Antarctic patch.
        # The feather rides inside the perennial-ice producer and so inside the first term; the
        # ORDER is what this reproduces, and it is unchanged by softening one of the operands.
        inline = snow.soften_source_cells(
            snow.snow_alpha(snow.unpack_persistence(persistence),
                            SOUTHERN_TOP, SOUTHERN_BOTTOM),
            _ground_metres_per_px(SOUTHERN_TOP, SOUTHERN_BOTTOM))
        inline = np.maximum(inline, glacier.astype(float))
        inline = np.maximum(inline, snow.antarctic_snow_mask(land, latitude))
        assert self._shared(persistence, glacier).snow_a.tobytes() == inline.tobytes()

    def test_the_oracle_can_fail(self):
        """A comparison that cannot report a difference proves nothing. One glacier pixel moved,
        in a NORTHERN window: the Antarctic patch saturates the union above and would hide it."""
        persistence = np.zeros((ROWS, COLS), dtype="float32")
        glacier = np.zeros((ROWS, COLS), dtype=np.uint8)
        moved = glacier.copy()
        moved[0, 0] = 1
        northern = dict(top=8_000_000.0, bottom=7_000_000.0)
        assert (self._shared(persistence, glacier, **northern).snow_a.tobytes()
                != self._shared(persistence, moved, **northern).snow_a.tobytes())


def _age(path, seconds):
    stamp = os.stat(path).st_mtime - seconds
    os.utime(path, (stamp, stamp))


#: Every body these fixtures drive is Earth or a `dataclasses.replace` of it, and the warp gate now
#: asks the reference raster whether it is on that body's pixel size. Built at a made-up 100-units
#: extent the fixture described a grid the registry would re-warp on sight, which is a fixture
#: asserting against a state production can never be in.
_RESOLUTION = bodies.EARTH.map_units_per_pixel


def _height_raster(path):
    transform = from_bounds(0.0, 0.0, COLS * _RESOLUTION, ROWS * _RESOLUTION, COLS, ROWS)
    with rasterio.open(path, "w", driver="GTiff", width=COLS, height=ROWS, count=1,
                       dtype="float32", crs="EPSG:3857", transform=transform) as dataset:
        dataset.write(np.zeros((ROWS, COLS), dtype="float32"), 1)
    return path


class TestTheWarpGateAsksTheBodyFirst:
    """The hole this registry closes, driven through the real `warp_inputs`.

    EVERY SOURCE IN THIS FIXTURE EXISTS, exactly as Earth's do on the box that builds the pyramid,
    so the only thing that can refuse a layer is the body. That is what makes these tests able to
    see a gate that asks the disk first, and what makes them invisible to any output.
    """

    def _drive(self, monkeypatch, tmp_path, body):
        built: list[str] = []
        work, planet = tmp_path / "work", tmp_path / "planet"
        work.mkdir()
        (planet / "chunks").mkdir(parents=True)
        (planet / "planet_heightfield.vrt").write_text("vrt")
        _age(planet / "planet_heightfield.vrt", 500)
        _age(planet / "chunks", 500)
        height = _height_raster(work / "height_3857.tif")
        freshness.mark_done(height)
        for layer in layers.WARPED_LAYERS:
            source = tmp_path / f"{layer.name}.source"
            source.write_text("downloaded")
            monkeypatch.setitem(
                layer_producers.PRODUCER_BY_BODY_LAYER, ("earth", layer.name),
                layer_producers.LayerProducer(
                    sources=lambda source=source: (source,),
                    build=lambda request, name=layer.name: built.append(name),
                    contribution=lambda window: None, paint=lambda window: None,
                    recipe=dict, build_recipe=dict))
        shade_planet.warp_inputs(work, planet, body, frozenset())
        return built

    def test_earth_builds_every_layer_it_declares(self, monkeypatch, tmp_path):
        """The companion that shows the two below can fail: with the gate working, the body that
        declares everything gets everything."""
        assert self._drive(monkeypatch, tmp_path, bodies.EARTH) == [
            layer.name for layer in layers.WARPED_LAYERS]

    def test_a_body_with_no_layers_opens_none_of_earths_files(self, monkeypatch, tmp_path):
        """A SYNTHETIC body, because Mars now declares one and would drive its REAL producer here.

        It kept passing after Mars's ice landed, and for a reason nobody chose: on this box the
        Martian sources exist, so the gate let the real build through and the tiny synthetic grid
        happened to yield no band. On a clone with no data store it would have passed by the sources
        being absent instead. Two different accidents wearing one green tick — so the body under
        test is built here, and the claim is about the DECLARATION again.
        """
        layerless = dataclasses.replace(bodies.EARTH, name="layerless", path_prefix="layerless",
                                        surface_layers=frozenset())
        assert self._drive(monkeypatch, tmp_path, layerless) == []

    def test_a_body_declaring_a_layer_it_cannot_produce_opens_none_of_earths_files(
            self, monkeypatch, tmp_path):
        """The registry must refuse rather than reach for Earth's entry. Falling back renders
        perfectly — Earth's answer IS Earth's producer — and is wrong only on the planet nobody has
        built yet, which is why nothing but this raise reports it."""
        claimant = dataclasses.replace(
            bodies.EARTH, name="stranger", path_prefix="stranger",
            surface_layers=frozenset({layers.PERENNIAL_ICE.name}))
        with pytest.raises(KeyError, match="stranger declares the perennial_ice layer"):
            self._drive(monkeypatch, tmp_path, claimant)

    def test_a_missing_dataset_still_skips_the_layer_for_a_body_that_declares_it(
            self, monkeypatch, tmp_path):
        """Body first does not mean body only. Earth with a download absent must skip that layer
        rather than crash the pass, or a partial build stops being legal."""
        built: list[str] = []
        work, planet = tmp_path / "work", tmp_path / "planet"
        work.mkdir()
        (planet / "chunks").mkdir(parents=True)
        (planet / "planet_heightfield.vrt").write_text("vrt")
        _age(planet / "planet_heightfield.vrt", 500)
        _age(planet / "chunks", 500)
        freshness.mark_done(_height_raster(work / "height_3857.tif"))
        for layer in layers.WARPED_LAYERS:
            source = tmp_path / f"{layer.name}.source"
            if layer is not layers.PERENNIAL_ICE:  # this one was never downloaded
                source.write_text("downloaded")
            monkeypatch.setitem(
                layer_producers.PRODUCER_BY_BODY_LAYER, ("earth", layer.name),
                layer_producers.LayerProducer(
                    sources=lambda source=source: (source,),
                    build=lambda request, name=layer.name: built.append(name),
                    contribution=lambda window: None, paint=lambda window: None,
                    recipe=dict, build_recipe=dict))
        shade_planet.warp_inputs(work, planet, bodies.EARTH, frozenset())
        assert layers.PERENNIAL_ICE.name not in built
        assert layers.SEA_ICE.name in built, "the other layers must be unaffected"


class TestABuildTimeConstantReachesTheFreshnessGate:
    """The hole a `composite_deps` trace opened, closed and given a control.

    `warp_needs_rebuild` is closed over PATHS, so no Python value can reach it. That never mattered
    while every build was pure transport — Earth stores raw packed values and grades per window, and
    a per-window constant restages through `composite_params` because the rerun re-reads it. Mars's
    build grades BEFORE it writes, so its constants are frozen into the file, and recorded in
    `composite_params` alone a re-tune would restage the whole composite and then repaint from the
    unchanged raster: the same wrong pixels behind a restage that looks like it worked.
    """

    def _drive(self, monkeypatch, tmp_path, producer, body):
        """One `warp_inputs` pass for a single layer, returning how many times it built."""
        builds: list[str] = []
        work, planet = tmp_path / "work", tmp_path / "planet"
        work.mkdir(exist_ok=True)
        (planet / "chunks").mkdir(parents=True, exist_ok=True)
        (planet / "planet_heightfield.vrt").write_text("vrt")
        _age(planet / "planet_heightfield.vrt", 500)
        _age(planet / "chunks", 500)
        freshness.mark_done(_height_raster(work / "height_3857.tif"))
        for layer in layers.WARPED_LAYERS:
            registered = (
                # A REAL raster on the reference grid, not a stub: the gate also asks
                # `grid_matches`, which opens the target — a text file makes the second pass raise
                # rather than answer, and the control below would never run.
                dataclasses.replace(producer, build=lambda request: (
                    builds.append("built"), _height_raster(request.out))[0])
                if layer is layers.PERENNIAL_ICE else
                layer_producers.LayerProducer(
                    sources=lambda: (), build=lambda request: None,
                    contribution=lambda window: None, paint=lambda window: None, recipe=dict, build_recipe=dict))
            monkeypatch.setitem(layer_producers.PRODUCER_BY_BODY_LAYER,
                                (body.name, layer.name), registered)
        shade_planet.warp_inputs(work, planet, body, frozenset())
        return builds

    def _producer(self, tmp_path, tunables):
        source = tmp_path / "field.tif"
        source.write_text("a field")
        _age(source, 500)
        return layer_producers.LayerProducer(
            sources=lambda: (source,), build=lambda request: None,
            contribution=lambda window: None, paint=lambda window: None,
            recipe=dict, build_recipe=lambda: dict(tunables))

    def test_a_changed_build_constant_rebuilds_the_raster(self, monkeypatch, tmp_path):
        """THE POINT. Nothing on disk moved — only a number the build bakes in."""
        body = dataclasses.replace(bodies.EARTH, name="grader", path_prefix="grader",
                                   surface_layers=frozenset({layers.PERENNIAL_ICE.name}))
        assert self._drive(monkeypatch, tmp_path,
                           self._producer(tmp_path, {"levels": 1.0}), body) == ["built"]
        assert self._drive(monkeypatch, tmp_path,
                           self._producer(tmp_path, {"levels": 2.0}), body) == ["built"], (
            "a build-time constant moved and the raster stayed — the composite would restage and "
            "repaint from a file graded through the old value")

    def test_an_unchanged_build_constant_leaves_it_alone(self, monkeypatch, tmp_path):
        """The control, and the half that makes the test above mean something: if this rebuilt too,
        the first would pass on a gate that simply always rebuilds."""
        body = dataclasses.replace(bodies.EARTH, name="grader", path_prefix="grader",
                                   surface_layers=frozenset({layers.PERENNIAL_ICE.name}))
        assert self._drive(monkeypatch, tmp_path,
                           self._producer(tmp_path, {"levels": 1.0}), body) == ["built"]
        assert self._drive(monkeypatch, tmp_path,
                           self._producer(tmp_path, {"levels": 1.0}), body) == []

    def test_an_empty_build_recipe_writes_no_sidecar_at_all(self, monkeypatch, tmp_path):
        """WHY ADOPTING THIS RESTAGES NOTHING ON EARTH. Every Earth producer is pure transport, so
        an empty dict must leave the source list exactly as it was — a file appearing beside the
        raster would be a new dependency and would rebuild all four of Earth's layers once."""
        body = dataclasses.replace(bodies.EARTH, name="plain", path_prefix="plain",
                                   surface_layers=frozenset({layers.PERENNIAL_ICE.name}))
        self._drive(monkeypatch, tmp_path, self._producer(tmp_path, {}), body)
        work = tmp_path / "work"
        assert not list(work.glob("*_build.json")), (
            f"an empty build recipe still materialised {[p.name for p in work.glob('*_build.json')]}")

    def test_every_earth_producer_declares_no_build_time_constant(self):
        """The claim the paragraph above rests on, asserted rather than assumed — and it is what
        turns a future Earth producer that grades at build time into a red test rather than a
        silent stale raster."""
        for (body_name, layer_name), producer in \
                layer_producers.PRODUCER_BY_BODY_LAYER.items():
            if body_name != "earth":
                continue
            assert producer.build_recipe() == {}, (
                f"earth/{layer_name} grew a build-time constant; adopting it restages that layer "
                f"once, which is correct but must be a decision rather than a surprise")

    def test_mars_declares_the_two_constants_its_build_bakes_in(self):
        """Named exactly, because the failure of an under-full list is silent: a constant that
        reaches a pixel and reaches no recipe leaves a stale raster looking fresh forever."""
        recorded = layer_producers.producer_for(bodies.MARS, layers.PERENNIAL_ICE).build_recipe()
        assert recorded == {
            "mars_feather_km": mars_ice.FEATHER_KM,
            "mars_alpha_levels": {pole: list(levels)
                                  for pole, levels in sorted(mars_ice.ALPHA_LEVELS.items())}}

    def test_mars_grades_nothing_per_window_so_only_its_whites_reach_the_composite_recipe(self):
        """The other side of the split, and its recipe is no longer empty.

        `contribution` still returns the slice unchanged, so no GRADING constant belongs here — but
        what this producer is PAINTED in is re-tunable and read per window, which is exactly what
        `recipe` tracks. The build's two constants still stay out: putting them here would restage
        the composite without rebuilding the raster they are baked into.
        """
        recipe = layer_producers.producer_for(bodies.MARS, layers.PERENNIAL_ICE).recipe()
        assert set(recipe) == {"snow_rgb_north", "snow_shadow_rgb_north",
                               "snow_rgb_south", "snow_shadow_rgb_south"}
        assert not {key for key in recipe if key.startswith("mars_")}


class TestAProducerDeclaresTheWhiteItIsPaintedIn:
    """The white moved out of `shade.composite` and into the producer that computed the alpha.

    Both directions matter and each is silent alone: a producer that paints and declares nothing
    leaves a re-tune untracked, and one that declares a white it never paints with restages a body
    for pixels that cannot move.
    """

    def test_every_producer_feeding_the_white_union_declares_a_paint(self, subtests):
        feeding = [(body, layer) for body in bodies.BODIES.values()
                   for layer in (layers.PERENNIAL_ICE, layers.GLACIERS)
                   if layer.name in body.surface_layers]
        assert feeding, "no body feeds the union — this sweep would pass vacuously"
        for body, layer in feeding:
            with subtests.test(f"{body.name} {layer.name}"):
                paint = layer_producers.producer_for(body, layer).paint(_window(None))
                assert paint is not None, "a layer painted white must say which white"
                assert len(paint) == 2

    def test_lake_depth_declares_no_paint_because_its_number_is_not_a_white(self):
        """None is the answer rather than a gap: this producer's contribution is a DEPTH, graded by
        the lake ramp, so there is no white for it to name."""
        producer = layer_producers.producer_for(bodies.EARTH, layers.LAKE_DEPTH)
        assert producer.paint(_window(None)) is None

    def test_every_declared_white_reaches_that_bodys_recipe(self, subtests):
        """A white that paints a pixel and reaches no recipe leaves a stale composite looking fresh
        — the exact hole `recipe` exists to close, now applied to the values that moved into it.

        Evaluated at BOTH hemispheres and unioned, because a producer whose paint varies by row
        would otherwise be checked on whichever half the fixture happened to pick.
        """
        for body in bodies.BODIES.values():
            for layer in (layers.PERENNIAL_ICE, layers.GLACIERS):
                if layer.name not in body.surface_layers:
                    continue
                producer = layer_producers.producer_for(body, layer)
                painted: set[tuple[int, ...]] = set()
                for top, bottom in ((9_000_000.0, 8_000_000.0), (-8_000_000.0, -9_000_000.0)):
                    paint = producer.paint(_window(None, top=top, bottom=bottom))
                    assert paint is not None
                    painted |= _triples(paint)
                recorded = {tuple(int(channel) for channel in value)
                            for value in producer.recipe().values()
                            if isinstance(value, list | tuple) and len(value) == 3
                            and all(isinstance(channel, int) for channel in value)}
                with subtests.test(f"{body.name} {layer.name}"):
                    assert painted, "no white extracted — this check would pass vacuously"
                    assert painted <= recorded, f"{painted - recorded} paints but is not recorded"

    def test_earths_two_union_layers_declare_the_SAME_white(self):
        """They feed one `np.maximum`, so a disagreement would paint one layer's pixels in the
        other's colour wherever it won. Stated as an assertion because nothing else forces it."""
        ice = layer_producers.producer_for(bodies.EARTH, layers.PERENNIAL_ICE).paint(_window(None))
        glaciers = layer_producers.producer_for(bodies.EARTH, layers.GLACIERS).paint(_window(None))
        assert ice == glaciers

    def test_mars_paints_its_two_poles_in_DIFFERENT_whites(self):
        """The measurement that motivated the whole seam: 1.053 red:violet north against 1.291
        south. One producer spans both hemispheres, so the difference has to appear WITHIN a
        producer's answer rather than between two registry entries."""
        producer = layer_producers.producer_for(bodies.MARS, layers.PERENNIAL_ICE)
        northern = producer.paint(_window(None, top=9_000_000.0, bottom=8_000_000.0))
        southern = producer.paint(_window(None, top=-8_000_000.0, bottom=-9_000_000.0))
        assert northern is not None and southern is not None
        for north_end, south_end in zip(northern, southern, strict=True):
            assert not np.array_equal(np.asarray(north_end), np.asarray(south_end))

    def test_mars_does_not_paint_in_earths_white(self):
        """The failure this replaced, and it shipped: a module-global read gave Mars Earth's
        `E8F1F6` with nothing anywhere able to show a reader that a second planet existed."""
        recorded = layer_producers.producer_for(bodies.MARS, layers.PERENNIAL_ICE).recipe()
        assert list(palette.SNOW_RGB) not in [list(v) for v in recorded.values()]
        assert list(palette.SNOW_SHADOW_RGB) not in [list(v) for v in recorded.values()]


class TestARockLayerBuildsARasterAndContributesNothing:
    """Antarctic outcrop is the first layer whose raster is read by ANOTHER layer's producer.

    It has a row, a source, a build and a warped raster like the four before it, and then its own
    `contribution` is None on every window: what consumes it is `fold_white`, which takes it back
    OUT of the finished union as a `WHITE_EXCLUSIONS` member. That asymmetry is the whole design,
    and both halves of it are silent if they break. A rock layer that started contributing would be
    folded into `WHITE_UNION`'s maximum and paint the outcrop the very white it exists to remove —
    the exact inversion, and one that renders as a plausible ice sheet.

    The OUTCOME these plumbing claims are supposed to add up to is asserted separately, in
    `TestTheOutcropLosesItsWhiteWhateverElseClaimsThePixel` — every guard in this class passed while
    the outcrop still rendered solid white, which is the reason that class exists.
    """

    def _rock(self, rows=ROWS, cols=COLS) -> np.ndarray:
        """A rock mask covering the left half — enough that a fold would be unmistakable."""
        mask = np.zeros((rows, cols), dtype=np.uint8)
        mask[:, : cols // 2] = 1
        return mask

    def test_gather_returns_no_entry_for_it_however_much_rock_there_is(self):
        """`gather` skips a producer returning None, so the layer never reaches the fold at all.

        Asserted with the raster PRESENT and non-empty: a rock mask of zeros would satisfy this
        against a producer that folded its input, which is the arm that has to fail.
        """
        raw: dict[str, np.ndarray | None] = {layer.name: None for layer in layers.WARPED_LAYERS}
        raw[layers.ANTARCTIC_ROCK.name] = self._rock()
        contributions, paints, _ = layer_producers.gather(
            bodies.EARTH, raw, _window(None), layers.COMPOSITE_LAYERS)
        assert layers.ANTARCTIC_ROCK.name not in contributions
        assert layers.ANTARCTIC_ROCK.name not in paints

    def test_it_is_in_the_exclusions_and_not_in_the_union(self):
        """Both tuples, because membership of either one alone is half a claim.

        The union is where a contribution would become white and the exclusions are where a raster
        removes it; a layer in neither reaches no pixel at all, and a layer in both would fight
        itself. This is the guard against the tidy that adds every ice-ish layer to the union.
        """
        assert layers.ANTARCTIC_ROCK in layer_producers.WHITE_EXCLUSIONS
        assert layers.ANTARCTIC_ROCK not in layer_producers.WHITE_UNION

    def test_it_declares_no_paint_because_it_is_never_painted(self):
        """None rather than a white, for lake depth's reason and a stronger one: this layer's
        number reaches no pixel of its own at all."""
        producer = layer_producers.producer_for(bodies.EARTH, layers.ANTARCTIC_ROCK)
        assert producer.paint(_window(self._rock())) is None
        assert producer.contribution(_window(self._rock())) is None

    def _gathered(self, body=bodies.EARTH, vocabulary=None, rock=True):
        raw: dict[str, np.ndarray | None] = {layer.name: None for layer in layers.WARPED_LAYERS}
        raw[layers.ANTARCTIC_ROCK.name] = self._rock() if rock else None
        return layer_producers.gather(
            body, raw, _window(None),
            layers.COMPOSITE_LAYERS if vocabulary is None else vocabulary)

    def test_gather_returns_the_rock_as_an_exclusion_and_no_producer_sees_it(self):
        """Both halves, and the second is the one the placement before this got wrong.

        `gather` holds `layer_raw` and the body's declarations together, so the exclusion is read
        here. And the perennial-ice contribution must be BYTE-IDENTICAL with the rock present and
        absent: a producer that could still see the mask could still subtract it inside its own
        maximum, which is the arrangement that discarded 63% of the subtraction.
        """
        contributions, _, exclusions = self._gathered()
        assert (exclusions[layers.ANTARCTIC_ROCK.name] == self._rock()).all()
        blind, _, empty = self._gathered(rock=False)
        assert not empty
        assert (contributions[layers.PERENNIAL_ICE.name].tobytes()
                == blind[layers.PERENNIAL_ICE.name].tobytes())

    def test_a_body_that_declares_no_rock_layer_excludes_nothing(self):
        """The body gate, and it has to live in `gather` because one supplier does not apply it.

        `shade_planet` builds `layer_raw` off `path.exists()` alone — every per-layer declaration
        check is `gather`'s — so a rock slice can reach here for a body that declares no such layer.
        The answer must then be today's exactly, not a plausible one.
        """
        # Earth's NAME is kept and only its declaration dropped: both registries key on the slug,
        # so a renamed body would raise in `producer_for` before reaching the claim under test.
        rockless = dataclasses.replace(
            bodies.EARTH,
            surface_layers=bodies.EARTH.surface_layers - {layers.ANTARCTIC_ROCK.name})
        _, _, exclusions = self._gathered(body=rockless)
        assert not exclusions

    def test_a_stage_that_does_not_read_the_layer_excludes_nothing(self):
        """The vocabulary gate's own case. Both stage vocabularies carry the rock today, so only a
        deliberately narrow one can show the gate exists at all — and without it a stage would take
        an exclusion for a layer it never gathered, which is the block prep's disagreement in
        miniature.
        """
        _, _, exclusions = self._gathered(vocabulary=frozenset({layers.PERENNIAL_ICE.name}))
        assert not exclusions

    def test_no_producer_can_see_the_rock_at_all(self):
        """The field is GONE rather than handed over as None, and that is what makes the old
        placement unwritable rather than merely unwritten.

        A shared `rock` on the window is exactly what let a negative be smuggled inside a positive
        contribution. A producer cannot reach for a field its window does not have.
        """
        assert "rock" not in {field.name
                              for field in dataclasses.fields(layer_producers.LayerWindow)}

    def test_its_source_is_the_gpkg_the_acquirer_writes(self, monkeypatch, tmp_path):
        """One home for the path, read at CALL time — the acquirer owns it because it writes it.

        A second spelling here would be a path that agrees with the acquirer's until one of them
        moves, and the failure is an absent file read as "this body has no rock".
        """
        moved = tmp_path / "somewhere-else.gpkg"
        monkeypatch.setattr(download_add_rock, "GPKG", moved)
        producer = layer_producers.producer_for(bodies.EARTH, layers.ANTARCTIC_ROCK)
        assert producer.sources() == (moved,)


class TestTheOutcropLosesItsWhiteWhateverElseClaimsThePixel:
    """The tile tier's OUTCOME, asserted where no plumbing guard is able to assert it.

    Every other rock guard in this file names a MECHANISM — `gather` places the slice, the producer
    passes it, the rule subtracts it — and every one of them passes while the outcrop still renders
    solid white. The subtraction used to sit inside ONE TERM of `_earth_perennial_ice`'s maximum,
    and persistence is the other term: `max(persistence, rule - rock)` keeps the white wherever
    persistence claims the pixel independently. On the shipping rasters it claims almost all of it.

    SO THE FIXTURE SATURATES PERSISTENCE, and that is the whole design of these tests rather than a
    convenient extreme. Run against an all-zero persistence raster every assertion below passes on
    the broken placement and on the fixed one alike, which is the shape that let this ship.

    Taken through `shade_planet._compute_shared` rather than through `fold_white` directly, because
    the claim is about the alpha `shade.composite` paints and not about one function's return.
    """

    #: Packed persistence that `unpack_persistence` clips to 1.0, so `snow_alpha` saturates on every
    #: row of this window. NSIDC-0791's own median ON the outcrop is 0.9999, so this is the measured
    #: state of the other term rather than a stressor invented for the test.
    SATURATED = 10_000.0

    def _rock(self) -> np.ndarray:
        """Rock over the left half, ice over the right, so one window carries claim and control."""
        mask = np.zeros((ROWS, COLS), dtype=np.uint8)
        mask[:, : COLS // 2] = 1
        return mask

    def _snow_alpha(self, *, rock=None, persistence=None, glacier=None, body=bodies.EARTH):
        from rasterio.windows import Window

        raw: dict[str, np.ndarray | None] = {layer.name: None for layer in layers.WARPED_LAYERS}
        raw[layers.PERENNIAL_ICE.name] = persistence
        raw[layers.GLACIERS.name] = glacier
        raw[layers.ANTARCTIC_ROCK.name] = rock
        return shade_planet._compute_shared(shade_planet._WindowInputs(
            win=Window(0, 0, COLS, ROWS),  # pyright: ignore[reportCallIssue]
            win_h=ROWS, win_top=SOUTHERN_TOP, win_bottom=SOUTHERN_BOTTOM,
            height_win=np.zeros((ROWS, COLS), dtype=np.float32),
            ocean_raw=np.zeros((ROWS, COLS), dtype=np.uint8),
            watercode=np.zeros((ROWS, COLS), dtype=np.uint8),
            hs_raw=np.full((ROWS, COLS), 128, dtype=np.uint8),
            layer_raw=raw, occ_win=np.zeros((ROWS, COLS), dtype=np.float32),
            body=body)).snow_a

    def test_the_fixture_really_does_saturate_the_other_term(self):
        """The positive control, and it runs FIRST because every claim below is void without it.

        If `SATURATED` did not reach 1.0 the tests under it would pass for the wrong reason — the
        subtraction would be surviving a maximum against something smaller than itself rather than
        being applied after the union at all.
        """
        assert (self._snow_alpha(persistence=np.full((ROWS, COLS), self.SATURATED)) == 1.0).all()

    def test_saturated_persistence_does_not_rescue_the_white_on_rock(self):
        """THE DEFECT, stated as an outcome. Red on the placement that shipped."""
        white = self._snow_alpha(rock=self._rock(),
                                 persistence=np.full((ROWS, COLS), self.SATURATED))
        assert (white[:, : COLS // 2] == 0.0).all(), "the outcrop kept a white another term claimed"
        assert (white[:, COLS // 2:] == 1.0).all(), "the ice beside the outcrop lost its white"

    def test_a_glacier_over_the_outcrop_does_not_rescue_it_either(self):
        """The claim that makes this an EXCLUSION and not a bigger subtraction, and what RGI region
        19 is carried on.

        Region 19's polygons are invisible over Antarctica only because the forced rule already
        paints white there. Where rock comes out they are a second whitener landing on the same
        pixels — and a negative applied inside any one positive term cannot answer them.
        """
        white = self._snow_alpha(rock=self._rock(),
                                 glacier=np.ones((ROWS, COLS), dtype=np.uint8))
        assert (white[:, : COLS // 2] == 0.0).all(), "a glacier re-covered the outcrop"
        assert (white[:, COLS // 2:] == 1.0).all(), "the glacier beside it lost its white"

    def test_no_rock_leaves_the_white_untouched(self):
        """The instrument's own falsifier: the assertions above must be reporting the rock rather
        than a window that was never white to begin with."""
        assert (self._snow_alpha(persistence=np.full((ROWS, COLS), self.SATURATED),
                                 glacier=np.ones((ROWS, COLS), dtype=np.uint8)) == 1.0).all()

    def test_a_body_that_declares_no_rock_layer_keeps_every_pixel_white(self):
        """The declaration gate at the outcome level. `shade_planet` keys `layer_raw` on
        `path.exists()` alone, so a slice genuinely can arrive for a body that declares no such
        layer, and the answer must then be today's exactly rather than a plausible one.
        """
        rockless = dataclasses.replace(
            bodies.EARTH,
            surface_layers=bodies.EARTH.surface_layers - {layers.ANTARCTIC_ROCK.name})
        white = self._snow_alpha(rock=self._rock(), body=rockless,
                                 persistence=np.full((ROWS, COLS), self.SATURATED))
        assert (white == 1.0).all()

