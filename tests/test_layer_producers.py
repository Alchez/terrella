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

from pipeline import bodies, freshness, layers
from pipeline.render import lake_depth, layer_producers, seaice, snow
from pipeline.tile import shade_planet

#: A window well south of the Antarctic patch's -60, so the rule that has no dataset behind it is
#: live in every oracle below rather than sitting at zero.
SOUTHERN_TOP, SOUTHERN_BOTTOM = -11_000_000.0, -12_000_000.0
ROWS, COLS = 8, 16


def _window(raw, *, land=None, watercode=None, top=SOUTHERN_TOP, bottom=SOUTHERN_BOTTOM):
    latitude = snow.latitude_per_row(top, bottom, ROWS)
    return layer_producers.LayerWindow(
        raw=raw,
        watercode=np.zeros((ROWS, COLS), dtype=np.uint8) if watercode is None else watercode,
        land=np.ones((ROWS, COLS), dtype=bool) if land is None else land,
        latitude=latitude, top=top, bottom=bottom)


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
        assert "perennial_ice" not in bodies.MARS.surface_layers, (
            "this test needs a body the registry does NOT hold — pick another if Mars registers")
        with pytest.raises(KeyError, match="mars declares the perennial_ice layer"):
            layer_producers.producer_for(bodies.MARS, layers.PERENNIAL_ICE)


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

    def test_perennial_ice_is_snow_alpha_maxed_with_the_antarctic_patch(self):
        packed = np.linspace(0, 10_000, ROWS * COLS, dtype="float32").reshape(ROWS, COLS)
        land = np.ones((ROWS, COLS), dtype=bool)
        latitude = snow.latitude_per_row(SOUTHERN_TOP, SOUTHERN_BOTTOM, ROWS)
        inline = np.maximum(
            snow.snow_alpha(snow.unpack_persistence(packed), SOUTHERN_TOP, SOUTHERN_BOTTOM),
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
        inline = snow.snow_alpha(snow.unpack_persistence(persistence),
                                 SOUTHERN_TOP, SOUTHERN_BOTTOM)
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


def _height_raster(path):
    transform = from_bounds(0.0, 0.0, 100.0, 100.0, COLS, ROWS)
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
                    contribution=lambda window: None,
                    recipe=dict))
        shade_planet.warp_inputs(work, planet, body, frozenset())
        return built

    def test_earth_builds_every_layer_it_declares(self, monkeypatch, tmp_path):
        """The companion that shows the two below can fail: with the gate working, the body that
        declares everything gets everything."""
        assert self._drive(monkeypatch, tmp_path, bodies.EARTH) == [
            layer.name for layer in layers.WARPED_LAYERS]

    def test_a_body_with_no_layers_opens_none_of_earths_files(self, monkeypatch, tmp_path):
        assert self._drive(monkeypatch, tmp_path, bodies.MARS) == []

    def test_a_body_declaring_a_layer_it_cannot_produce_opens_none_of_earths_files(
            self, monkeypatch, tmp_path):
        """The registry must refuse rather than reach for Earth's entry. Falling back renders
        perfectly — Earth's answer IS Earth's producer — and is wrong only on the planet nobody has
        built yet, which is why nothing but this raise reports it."""
        claimant = dataclasses.replace(
            bodies.MARS, surface_layers=frozenset({layers.PERENNIAL_ICE.name}))
        with pytest.raises(KeyError, match="mars declares the perennial_ice layer"):
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
                    contribution=lambda window: None,
                    recipe=dict))
        shade_planet.warp_inputs(work, planet, bodies.EARTH, frozenset())
        assert layers.PERENNIAL_ICE.name not in built
        assert layers.SEA_ICE.name in built, "the other layers must be unaffected"
