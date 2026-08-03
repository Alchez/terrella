#!/usr/bin/env python3
"""Threading the planet composite (optimisation #5): the threaded pass must be byte-identical
to the serial one, and only the single-variant production path may thread.

The whole justification for #5 is a measured speedup and its whole risk is that a worker sees
different bytes than the serial loop would. So the load-bearing test runs the SAME synthetic
planet through `composite_planet` serial and threaded at the SAME `window_rows`, and asserts
`compare_rasters(tolerance=0)` over all three bands -- the exact gate the real pass will use.

`window_rows` is held fixed on purpose: it is look-affecting (each window's sky-view slice is
`occ[sr0:sr1]` upsampled by `zoom`, and a different window height selects a different slice), so
thread-count invariance is only meaningful at one window height. Varying threads must change
NOTHING; varying `window_rows` legitimately may.

Companion tests prove the guard can fail (a corrupted pixel is caught) and that the serial and
multi-variant paths never even construct a thread pool.
"""
import dataclasses
import math
import shutil
from typing import Any, cast

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds

from pipeline import bodies
from pipeline.render import snow
from pipeline.tile import shade
from pipeline.tile import shade_planet
from pipeline.verify import compare_rasters

# Read from the registry rather than restated — see the note in test_snow_warp_once.py.
EARTH_RADIUS = bodies.EARTH.mercator_radius_m
WIDTH, HEIGHT = 40, 64          # a few windows tall so the in-flight throttle actually fires
WINDOW_ROWS = 8                 # -> 8 windows; > max_workers + INFLIGHT_BUFFER, so writes drain mid-loop
N_WINDOWS = len(range(0, HEIGHT, WINDOW_ROWS))


@pytest.fixture(autouse=True)
def _restore_knobs():
    """Every test here may drive KNOBS through a variant; snapshot and restore so a mutation
    cannot leak into the next test (the composite reads KNOBS globally)."""
    saved = dict(shade.KNOBS)
    yield
    knobs = cast(dict[str, Any], shade.KNOBS)  # TypedDict has no clear/update overload for a plain dict
    knobs.clear()
    knobs.update(saved)


def _merc(lat, lon):
    return (EARTH_RADIUS * math.radians(lon),
            EARTH_RADIUS * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _write(path, data, dtype, transform, nodata=None):
    # dict[str, Any] for the same reason shade_planet's profile is: **profile otherwise hands
    # rasterio.open's bool-typed sharing/thread_safe an inferred str | int.
    profile: dict[str, Any] = dict(driver="GTiff", width=WIDTH, height=HEIGHT, count=1, dtype=dtype,
                                   crs=CRS.from_epsg(3857), transform=transform)
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(np.asarray(data).astype(dtype), 1)


@pytest.fixture
def planet(tmp_path):
    """A tiny but complete planet_tiles dir: every raster `composite_planet` reads, on a mid-
    latitude 3857 grid, with deterministic values that exercise land/ocean/lake/snow/glacier."""
    work = tmp_path / "planet_tiles"
    work.mkdir()
    left, top = _merc(47.0, 6.0)
    transform = from_bounds(left, top - HEIGHT * bodies.EARTH.map_units_per_pixel,
                            left + WIDTH * bodies.EARTH.map_units_per_pixel, top, WIDTH, HEIGHT)
    rng = np.random.default_rng(0)

    height = rng.uniform(-3000.0, 5000.0, (HEIGHT, WIDTH))
    ocean = (height < 0.0)
    watercode = np.where(ocean, 0, rng.integers(0, 4, (HEIGHT, WIDTH)))
    packed = rng.integers(0, 10001, (HEIGHT, WIDTH)).astype(float)
    packed[ocean] = snow.SP_FILL  # fill (65535) over ocean, as the real warp emits

    _write(work / "height_3857.tif", height, "float32", transform)
    _write(work / "hs_3857.tif", rng.integers(0, 256, (HEIGHT, WIDTH)), "uint8", transform)
    _write(work / "ocean_3857.tif", ocean, "uint8", transform)
    _write(work / "water_3857.tif", watercode, "uint8", transform)
    _write(work / "lakedepth_3857.tif", rng.uniform(0.0, 80.0, (HEIGHT, WIDTH)),
           "float32", transform, nodata=0)
    _write(work / "snow_persistence_3857.tif", packed, "float32", transform,
           nodata=snow.SP_FILL)
    _write(work / "glacier_3857.tif", rng.integers(0, 2, (HEIGHT, WIDTH)), "uint8", transform)
    return work


def _occ():
    """A deterministic global sky-view stand-in (smaller than the grid, full width)."""
    return np.random.default_rng(1).random((16, WIDTH))


def _run(work, max_workers, variants=None):
    """Composite the synthetic planet. `max_windows=N_WINDOWS` covers every window while bypassing
    the freshness early-return, so a second run re-composites instead of skipping as fresh."""
    return shade_planet.composite_planet(
        work, work / "hs_3857.tif", _occ, bodies.EARTH, variants=variants,
        window_rows=WINDOW_ROWS, max_windows=N_WINDOWS, max_workers=max_workers)


@pytest.mark.parametrize("workers", [2, 4])
def test_threaded_is_byte_identical_to_serial(planet, workers):
    """THE test: threads must change wall time, never a pixel."""
    _run(planet, max_workers=1)
    serial = planet / "planet_rgb_serial.tif"
    shutil.copy(planet / "planet_rgb.tif", serial)

    _run(planet, max_workers=workers)
    for band in (1, 2, 3):
        result = compare_rasters(serial, planet / "planet_rgb.tif",
                                 tolerance=0, band=band, window_rows=16)
        assert result.control_passed, result.report()
        assert result.within_tolerance, result.report()


def test_the_byte_identity_check_can_fail(planet):
    """Companion: corrupt ONE pixel of an otherwise-identical copy and the oracle must report it.
    Without this the equality above could pass on a check that cannot fail (the blind-oracle trap
    verify.py exists to refuse)."""
    _run(planet, max_workers=1)
    corrupt = planet / "planet_rgb_corrupt.tif"
    shutil.copy(planet / "planet_rgb.tif", corrupt)
    with rasterio.open(corrupt, "r+") as dataset:
        band = dataset.read(1)
        band[0, 0] = 255 - band[0, 0]  # flip one pixel far from mid-grey
        dataset.write(band, 1)
    result = compare_rasters(planet / "planet_rgb.tif", corrupt, tolerance=0, band=1)
    assert not result.within_tolerance
    assert result.worst > 0


def test_threaded_single_variant_engages_the_pool(planet, monkeypatch):
    """Prove the speedup path is actually taken (not a silent fall-through to serial): a
    single-variant pass with max_workers>1 must construct exactly one pool of that size."""
    constructed = []
    real = shade_planet.ThreadPoolExecutor

    def spy(*args, **kwargs):
        constructed.append(kwargs.get("max_workers", args[0] if args else None))
        return real(*args, **kwargs)

    monkeypatch.setattr(shade_planet, "ThreadPoolExecutor", spy)
    _run(planet, max_workers=4)
    assert constructed == [4]


def test_serial_path_never_constructs_a_pool(planet, monkeypatch):
    """max_workers=1 is the untouched production default: it must not touch the pool at all."""
    monkeypatch.setattr(shade_planet, "ThreadPoolExecutor", _forbidden)
    _run(planet, max_workers=1)  # must not raise


def test_multivariant_stays_serial_even_with_workers(planet, monkeypatch):
    """The A/B path mutates the shared KNOBS between variants, so it must NEVER thread -- even when
    max_workers>1. Forbidding the pool proves it stayed serial, and both variants still emit."""
    monkeypatch.setattr(shade_planet, "ThreadPoolExecutor", _forbidden)
    outs = _run(planet, max_workers=4, variants={None: None, "warm": {"sea_lift": 1.05}})
    assert set(outs) == {None, "warm"}
    assert (planet / "planet_rgb.tif").exists()
    assert (planet / "planet_rgb_warm.tif").exists()


def _forbidden(*args, **kwargs):
    raise AssertionError("ThreadPoolExecutor must not be constructed on this path")


def test_a_body_with_no_snow_layer_composites_without_the_raster(planet):
    """The whole composite must survive a layer its body does not have — driven end to end, because
    the guard that was missing lives in `read_window`, which no unit test reaches.

    `snow_persistence_3857.tif` was the one read of four with no `.exists()` check, so a body whose
    snow layer is off died here on a raster nothing ever built. Its three siblings have always read
    `... if p.exists() else None`; this is snow joining them.

    The fixture WRITES that raster, which is why deleting it is the whole setup: a test run against
    the complete planet exercises only the present-file branch and would pass with the guard gone.

    Only `surface_layers` is varied. That is the one field this path reads — `work` is passed
    explicitly, so no path is derived from the body — and varying more would suggest otherwise.
    """
    (planet / "snow_persistence_3857.tif").unlink()
    no_snow = dataclasses.replace(bodies.EARTH, surface_layers=frozenset())

    out = shade_planet.composite_planet(
        planet, planet / "hs_3857.tif", _occ, no_snow,
        window_rows=WINDOW_ROWS, max_windows=N_WINDOWS, max_workers=1)

    with rasterio.open(out[None]) as dataset:
        rgb = dataset.read()
    assert rgb.shape[0] == 3 and rgb.any(), "the composite produced no pixels without a snow raster"
