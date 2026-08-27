"""The two ice instruments cache their warps, and the cache has to know which disc it is on.

`measure_mars_ice_white.py` and `measure_viking_levels.py` are the only reproducers of
`palette.MARS_ICE_WHITE` and `mars_ice.ALPHA_LEVELS` — the numbers that decide what colour Mars's
poles render. No unit test can re-derive those: the targets are percentiles and alpha-weighted means
over the shipped ice, so producing one means building the cap grids and grading the field exactly as
the renderer does. Each script's `--compare` is therefore the ONLY thing that can notice a pinned
constant going stale, which makes it a standing oracle rather than a convenience.

WHAT IS GUARDED HERE IS THE ORACLE'S RIGHT TO ANSWER. Every intermediate is cached under a name
carrying the pole and nothing else, so a moved `edge_lat` or `CAP_PX` used to be answered with the
previous disc's pixels — `--compare` reporting that the shipped whites still describe ice it never
looked at. Both script headers name that failure for the CONSTANTS and then reintroduced it one level
down, against the instrument itself; `edge_lat` has already moved once.

NO GDAL RUNS HERE. Every builder is recorded rather than executed and every grid is eight pixels
wide, because what is under test is the DECISION to rebuild, not the warp it guards. The recorder is
the assertion: a site that rebuilt appears in the log, and a site that reused its cache does not.

THE MIDDLE CLAIM IS THE LOAD-BEARING ONE. "A wrong grid rebuilds" passes trivially against a cache
that was simply deleted, so every site also asserts that a MATCHING artifact is reused — without
that pair, adopting the freshness gate and adopting `rm -rf` would look identical from in here.
"""

import dataclasses
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from pipeline import bodies, freshness, paths
from pipeline.acquire import download_sim3292, download_viking_mosaic
from pipeline.look import mars_ice, viking_luma
from pipeline.tile import cap_render
from scripts import measure_cap_tile_agreement as agreement
from scripts import measure_mars_ice_white as ice_white
from scripts import measure_viking_levels as levels

#: Eight pixels on a real cap's span. The span is real because `cap_reference_grid` reads it and the
#: whole question is whether a moved span is noticed; the pixel count is small because nothing here
#: looks at a pixel value.
TINY_PX = 8

#: The REAL acquired store, bound at import while `paths.DATA` still points at this checkout — the
#: same reason `conftest.REAL_PUBLIC_ROOT` is bound the way it is. A guard that re-read the root per
#: call would follow this module's own redirect and go blind exactly when it is needed.
REAL_RAW_MARS = paths.DATA / "raw" / "mars"


def _raw_store() -> dict[Path, tuple[int, int]]:
    """Every acquired Mars file with its size and mtime. Absent tree reads as empty."""
    if not REAL_RAW_MARS.exists():
        return {}
    return {path: (path.stat().st_size, path.stat().st_mtime_ns)
            for path in REAL_RAW_MARS.rglob("*") if path.is_file()}


@pytest.fixture(autouse=True)
def the_acquired_store_is_never_written():
    """No test here may touch `data/raw/mars/`, and this exists because one did.

    REDIRECTING THE ROOT REACHES ONLY CALL-TIME READERS. `viking_luma.work_dir()` resolves
    `paths.DATA` per call and moved; `download_viking_mosaic.DATA_DIR` and `download_sim3292`'s twin
    are module-level constants bound at import, so a fixture that patched the root wrote its stand-in
    rasters straight over the real 797 MB mosaic and both SIM 3292 unit files. Every assertion in
    this module still passed — the fixture had isolated half its outputs and written the rest for
    real, which is a shape no test in here can see from the inside.

    So the guard is a snapshot rather than a list of paths anyone has to remember to extend: it
    catches the next escape too, including through a helper this module does not know about yet.
    """
    before = _raw_store()
    yield
    after = _raw_store()
    changed = sorted(path for path in after if before.get(path) != after[path])
    missing = sorted(path for path in before if path not in after)
    if not changed and not missing:
        return
    named = ", ".join(str(path.relative_to(REAL_RAW_MARS)) for path in changed + missing)
    pytest.fail(
        f"this test wrote into the ACQUIRED store, which is multi-gigabyte and re-fetched over the "
        f"network: {named}. Patch the acquirer's path FUNCTION — redirecting paths.DATA does not "
        f"reach a module-level DATA_DIR bound at import.")


def _grid(pole: str = "north", **overrides: Any) -> cap_render.CapGrid:
    """A cap grid small enough to write. `pole` is the real name because `ALPHA_LEVELS` keys on it."""
    base = cap_render.CapGrid(lat_0=90.0 if pole == "north" else -90.0,
                              edge_lat=cap_render.CAP_EDGE_LAT if pole == "north"
                              else -cap_render.CAP_EDGE_LAT,
                              px=TINY_PX, name=pole, az_sign=-1.0, body=bodies.MARS)
    return dataclasses.replace(base, **overrides) if overrides else base


#: `(width, height, (left, bottom, right, top))` — `freshness.grid_matches`' argument order, spelled
#: with a FIXED-LENGTH bounds tuple so the arity reaches `from_bounds` instead of being erased.
Reference = tuple[int, int, tuple[float, float, float, float]]


def _write_raster(path: Path, reference: Reference, crs: str) -> None:
    """A real raster on `reference`, so `grid_matches` reads dimensions and bounds off the file."""
    width, height, (left, bottom, right, top) = reference
    path.parent.mkdir(parents=True, exist_ok=True)
    profile: dict[str, Any] = dict(
        driver="GTiff", width=width, height=height, count=1, dtype="uint8", crs=crs,
        transform=from_bounds(left, bottom, right, top, width, height))
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(np.ones((height, width), dtype=np.uint8), 1)


def _cache(path: Path, grid: cap_render.CapGrid, *, stamped: bool = True) -> None:
    """Leave a cached artifact on `grid`'s disc, complete unless told otherwise."""
    _write_raster(path, cap_render.cap_reference_grid(grid), grid.aeqd)
    if stamped:
        freshness.mark_done(path)


def _age_past(source: Path, cached: Path) -> None:
    """Make `source` strictly newer than `cached`'s completion stamp.

    SET RATHER THAN RACED, and that is not tidiness. `is_stale` counts equal stamps as FRESH on
    purpose — a stage marks done after it writes, so only a strictly newer input means anything — and
    two writes inside one test land on a single filesystem timestamp often enough that racing the
    clock makes the test flaky instead of slow. Measured here: a marker and a `touch()` immediately
    after it reported the identical `st_mtime_ns`, so the assertion failed with nothing wrong.
    """
    stamped = freshness.done_marker(cached).stat().st_mtime_ns + 1_000_000_000
    os.utime(source, ns=(stamped, stamped))


class _Recorder:
    """Stands in for every builder in both scripts, and records what it was asked to make.

    IT WRITES A REAL RASTER because the caller reads its own output straight back — a recorder that
    only logged would turn a rebuild into a missing-file error, which is a different failure wearing
    the same red.
    """

    def __init__(self) -> None:
        self.built: list[str] = []

    def run(self, command: list[str]) -> None:
        """A `gdalwarp`/`gdal_translate` stand-in: the target is the last argument in both."""
        target = Path(command[-1])
        self.built.append(target.name)
        _write_raster(target, self._reference_from(command), "EPSG:4326")

    def burn(self, unit: str, target_srs: str, bounds, width: int, height: int,
             projected: Path, out: Path, creation_options=(), must_draw=None) -> Path:
        self.built.append(out.name)
        left, bottom, right, top = bounds
        _write_raster(out, (width, height, (left, bottom, right, top)), target_srs)
        return out

    @staticmethod
    def _reference_from(command: list[str]) -> Reference:
        """Read the grid the command asked for, so the recorder cannot hand back a shape nobody
        requested — the one way this fixture could hide the defect it exists to expose.

        A command carrying no window at all is a RELABEL (`gdal_translate -a_srs`), which by
        definition keeps its source's grid; copying it from the source is what makes the levels
        band's two-step chain end up on the shape the first step chose.
        """
        source_path = command[-2]
        window = next((flag for flag in ("-te", "-projwin") if flag in command), None)
        if window is None:
            with rasterio.open(source_path) as source:
                edges = source.bounds
                return source.width, source.height, (edges.left, edges.bottom,
                                                     edges.right, edges.top)

        index = command.index(window)
        values = [float(value) for value in command[index + 1:index + 5]]
        # gdal_translate takes ulx uly lrx lry; gdalwarp takes the plain bounding box.
        corners: tuple[float, float, float, float] = (
            (values[0], values[3], values[2], values[1]) if window == "-projwin"
            else (values[0], values[1], values[2], values[3]))
        span_x, span_y = corners[2] - corners[0], corners[3] - corners[1]

        if "-ts" in command:
            index = command.index("-ts")
            return int(command[index + 1]), int(command[index + 2]), corners
        if "-tr" in command:
            step = float(command[command.index("-tr") + 1])
            return round(span_x / step), round(span_y / step), corners
        # A window with neither a size nor a resolution keeps the SOURCE's pixel, which is what a
        # bare `gdal_translate -projwin` does — the band crop in the ice-white chain.
        with rasterio.open(source_path) as source:
            step_x, step_y = abs(source.transform.a), abs(source.transform.e)
        return round(span_x / step_x), round(span_y / step_y), corners


@pytest.fixture
def oracle(monkeypatch, tmp_path) -> _Recorder:
    """Both scripts with their data root redirected and every builder recorded.

    THE REDIRECT IS ASSERTED, NOT ASSUMED, by `test_the_redirect_actually_moves_the_scratch` below —
    a fixture that moved some of its outputs and left the rest pointed at the real store would write
    into `data/work/mars/` and still look green from in here.
    """
    monkeypatch.setattr(paths, "DATA", tmp_path)
    # EVERY ACQUIRED PATH IS PATCHED AT ITS FUNCTION, not left to the root above. Both acquirers hold
    # `DATA_DIR = paths.DATA / ...` at module scope, bound at import, so the redirect never reaches
    # them — and what they name is the real multi-gigabyte store.
    acquired = tmp_path / "raw" / "mars"
    monkeypatch.setattr(download_viking_mosaic, "mosaic_path",
                        lambda: acquired / download_viking_mosaic.MOSAIC_NAME)
    monkeypatch.setattr(download_sim3292, "unit_path",
                        lambda unit: acquired / "sim3292" / f"{unit.lower()}_sim3292.json")
    monkeypatch.setattr(viking_luma, "degrees_vrt", lambda source, out: source)

    recorder = _Recorder()
    for module in (ice_white, levels):
        monkeypatch.setattr(module, "run", recorder.run)
    monkeypatch.setattr(mars_ice, "burn_unit", recorder.burn)

    # The mosaic is a REAL raster: `viking_band` reads its width to size the band, so a bare touch
    # would fail for a reason that has nothing to do with freshness.
    _write_raster(download_viking_mosaic.mosaic_path(), (64, 32, (-180.0, -90.0, 180.0, 90.0)),
                  "EPSG:4326")
    for unit in ("lApc", "Apu"):
        unit_file = download_sim3292.unit_path(unit)
        unit_file.parent.mkdir(parents=True, exist_ok=True)
        unit_file.write_text("{}")
    _write_raster(viking_luma.luma_path(), (64, 32, (-180.0, -90.0, 180.0, 90.0)), "EPSG:4326")
    ice_white.out_dir().mkdir(parents=True, exist_ok=True)
    levels.out_dir().mkdir(parents=True, exist_ok=True)
    return recorder


#: Every cached cap artifact in both instruments, as `(name, target, drive)`. `drive` runs the real
#: script function; `target` is the file whose freshness that function gates on.
CAP_SITES: tuple[tuple[str, Callable[[cap_render.CapGrid], Path],
                       Callable[[cap_render.CapGrid], object]], ...] = (
    ("ice_white viking rgb",
     lambda grid: ice_white.out_dir() / f"viking_rgb_{grid.name}_cap.tif",
     lambda grid: ice_white.viking_rgb_on_cap(grid)),
    ("ice_white unit burn",
     lambda grid: ice_white.out_dir() / f"lapc_{grid.name}.tif",
     lambda grid: ice_white.shipped_alpha(
         grid, np.full((3, grid.px, grid.px), 200.0, dtype=np.float32))),
    ("levels viking on cap",
     lambda grid: levels.out_dir() / f"viking_{grid.name}_cap_pipeline.tif",
     lambda grid: levels.viking_on_cap(grid, from_pipeline=True)),
    ("levels unit burn",
     lambda grid: levels.out_dir() / f"lapc_{grid.name}.tif",
     lambda grid: levels.unit_masks(grid)),
)


@pytest.mark.parametrize("name,target,drive", CAP_SITES, ids=[site[0] for site in CAP_SITES])
class TestEveryCapCacheKnowsWhichDiscItIsOn:
    """The pair that has to hold at every site: a stale disc is rebuilt and a current one is not."""

    def test_an_artifact_from_another_disc_is_rebuilt(self, oracle, name, target, drive):
        """The defect itself. The cached file is complete, stamped, and on a disc this run is not
        measuring — every check except the grid one says it is fine."""
        grid = _grid()
        _cache(target(grid), _grid(px=TINY_PX * 2))
        drive(grid)
        assert target(grid).name in oracle.built, (
            f"{name} reused an artifact from a different disc")

    def test_an_artifact_on_this_disc_is_reused(self, oracle, name, target, drive):
        """The anti-vacuity control, and the reason the test above means anything: without it a site
        that rebuilt unconditionally would pass, and so would one whose cache had been deleted."""
        grid = _grid()
        _cache(target(grid), grid)
        drive(grid)
        assert target(grid).name not in oracle.built, (
            f"{name} rebuilt an artifact that was already on the right disc")

    def test_an_unstamped_artifact_is_rebuilt(self, oracle, name, target, drive):
        """A file on the right grid with no completion marker is a CRASHED build, not a cache. GDAL
        creates its target at the start of a run, so the half-written raster is full-sized and
        correctly shaped — which is exactly what `grid_matches` alone would wave through."""
        grid = _grid()
        _cache(target(grid), grid, stamped=False)
        drive(grid)
        assert target(grid).name in oracle.built, (
            f"{name} trusted an artifact that no build ever claimed to have finished")


class TestTheSourcesReachTheGate:
    """The other half of `warp_needs_rebuild`, which the grid cases cannot see: a source that moved
    under a correctly-shaped artifact. Passing no sources at all would leave every test above green.
    """

    def test_a_newer_unit_rebuilds_the_burn(self, oracle):
        grid = _grid()
        burnt = ice_white.out_dir() / f"lapc_{grid.name}.tif"
        _cache(burnt, grid)
        _age_past(download_sim3292.unit_path("lApc"), burnt)
        ice_white.shipped_alpha(grid, np.full((3, grid.px, grid.px), 200.0, dtype=np.float32))
        assert burnt.name in oracle.built, "a re-acquired unit did not reach the burn's gate"

    def test_a_newer_mosaic_rebuilds_the_rgb_warp(self, oracle):
        grid = _grid()
        warped = ice_white.out_dir() / f"viking_rgb_{grid.name}_cap.tif"
        _cache(warped, grid)
        _age_past(download_viking_mosaic.mosaic_path(), warped)
        ice_white.viking_rgb_on_cap(grid)
        assert warped.name in oracle.built, "a re-fetched mosaic did not reach the warp's gate"

    def test_a_source_that_did_not_move_leaves_the_cache_alone(self, oracle):
        """The control for both above. Without it they pass against a gate wired to no sources at
        all, since `is_stale` reports a missing marker as stale and would rebuild regardless."""
        grid = _grid()
        warped = ice_white.out_dir() / f"viking_rgb_{grid.name}_cap.tif"
        _cache(warped, grid)
        ice_white.viking_rgb_on_cap(grid)
        assert warped.name not in oracle.built


class TestTheBandIsGatedOnItsOwnGridAndNotTheCaps:
    """`viking_band` is the levels script's informational arm and the one artifact NOT on a cap disc
    — it is square degrees, sized by the mosaic's own sampling and by the measurement band. Its grid
    moves for different reasons, so it takes its own reference rather than a cap's."""

    def _band(self) -> Path:
        return levels.out_dir() / "viking_north_4326.tif"

    def _reference(self, band_degrees: float) -> Reference:
        with rasterio.open(download_viking_mosaic.mosaic_path()) as dataset:
            degrees_per_px = 360.0 / dataset.width
        return (round(360.0 / degrees_per_px), round(band_degrees / degrees_per_px),
                (-180.0, 90.0 - band_degrees, 180.0, 90.0))

    def test_a_band_at_the_current_span_is_reused(self, oracle):
        """The control, and it also pins that the script's own arithmetic is what this test mirrors:
        a reference computed any other way would fail here rather than in the case below."""
        band = self._band()
        _write_raster(band, self._reference(cap_render.CAP_MEASURE_BAND_DEGREES), "EPSG:4326")
        freshness.mark_done(band)
        levels.viking_band(northern=True)
        assert band.name not in oracle.built

    def test_a_band_cropped_to_a_different_span_is_rebuilt(self, oracle):
        """The row count is what carries this. `grid_matches` compares bounds at a tolerance chosen
        for metres, which is a whole degree here — but a band that re-spans moves its height by
        thousands of rows, so the shape trips even where the bounds would not."""
        band = self._band()
        _write_raster(band, self._reference(cap_render.CAP_MEASURE_BAND_DEGREES / 2), "EPSG:4326")
        freshness.mark_done(band)
        levels.viking_band(northern=True)
        assert band.name in oracle.built


class TestTheFixtureIsHonest:
    """Isolation is asserted here rather than assumed, because a fixture that moved SOME of its
    outputs and left the rest pointed at the real store passes every other test in this file."""

    def test_every_path_the_scripts_reach_is_inside_the_redirect(self, oracle, tmp_path):
        """The scratch dirs AND the acquired inputs, which is the distinction that was learned the
        expensive way: the scratch moved with `paths.DATA` and the acquired inputs did not."""
        reached = {
            "ice_white scratch": ice_white.out_dir(),
            "levels scratch": levels.out_dir(),
            "viking mosaic": download_viking_mosaic.mosaic_path(),
            "sim3292 lApc": download_sim3292.unit_path("lApc"),
            "viking luma": viking_luma.luma_path(),
        }
        for what, path in reached.items():
            assert tmp_path in path.parents, f"{what} escaped the redirect: {path}"

    def test_the_redirect_is_reaching_something_real(self, oracle, tmp_path):
        """The positive control. Every assertion above is satisfied by a path that simply does not
        exist, so at least one of them has to be a file this fixture actually wrote."""
        assert download_viking_mosaic.mosaic_path().exists()
        assert tmp_path in download_viking_mosaic.mosaic_path().parents


class TestTheAgreementProbeSamplesInsideTheDiscItReads:
    """`measure_cap_tile_agreement` is the after-a-cut check, and it spelled its own sample band.

    Its sampler refuses any latitude outside the cap disc, on purpose: the version that clamped to
    the texture's edge instead reported a 1.2 km disagreement that was its own doing. So a spelled
    band and a moved `CAP_EDGE_LAT` do not merely disagree, they take the whole instrument off the
    air, exiting 1 on the first sample, with nothing between the edge moving and the next person
    needing the check. `edge_lat` has moved twice now, which is the other half of this file's
    subject one level down.
    """

    def test_every_sample_lies_inside_the_disc_that_will_be_read(self, subtests):
        for pole in ("north", "south"):
            grid = _grid(pole)
            for latitude in agreement.sample_latitudes(grid):
                with subtests.test(pole=pole, latitude=latitude):
                    radius = (90.0 - abs(latitude)) / (90.0 - abs(grid.edge_lat))
                    assert radius <= 1.0, f"lat {latitude} outside a disc reaching {grid.edge_lat}"

    def test_the_band_moves_with_the_edge_rather_than_being_spelled(self, subtests):
        """THE NON-VACUITY CONTROL, and the assertion above needs it: a band hard-coded anywhere
        inside today's disc satisfies every `radius <= 1.0` there and is exactly the state this
        class exists to refuse. A derived band has to MOVE when the disc does."""
        near, far = _grid(edge_lat=84.0), _grid(edge_lat=70.0)
        inner, outer = agreement.sample_latitudes(near), agreement.sample_latitudes(far)
        with subtests.test("the bands differ"):
            assert inner != outer
        with subtests.test("each stays inside its own disc"):
            assert min(inner) >= 84.0
            assert min(outer) >= 70.0
        with subtests.test("the wider disc reaches further equatorward"):
            assert min(outer) < min(inner)

    def test_the_band_stops_where_the_TILES_stop(self):
        """The poleward end is the Mercator limit, not the pole: past it there is no tile to compare
        against, so a sample there would read the cap against nothing and call it agreement."""
        assert max(agreement.sample_latitudes(_grid())) < cap_render.feather_hi_deg()
