"""Every pure look transform sampled over a fixed domain, computed from the code and nothing else.

The recipe fingerprint beside this one records the constants a stage would write to disk. A curve is
not a constant: `seaice.ice_alpha` holds `ICE_LO`, `ICE_BAND` and `ICE_MAX_ALPHA`, and replacing its
smoothstep with `ice_max_alpha * fraction` moves every sea-ice pixel while all three stay where they
are. That change is invisible to the recipe fingerprint by construction, because a recipe is the
constants and never the arithmetic consuming them. This samples the arithmetic instead.

    uv run python -m scripts.curve_fingerprint            # print it
    uv run python -m scripts.curve_fingerprint --write    # regenerate the committed baseline

Run it as a module from the repo root: a script under `scripts/` that imports `pipeline` cannot be
run by path, since Python puts the script's own directory on `sys.path` rather than the root.

The domain is synthetic and fixed, so this needs no data store, no GPU and no Blender, and a moved
sample is a fact about the code alone. Where a transform reads a body's look, it takes Earth's,
because a second body would sample the same arithmetic through different constants and those the
recipe fingerprint already covers.

`SAMPLES` and `EXCLUDED` must between them name every public function in `pipeline/look/`, which is
what `test_curve_fingerprint` asserts against the source rather than against a count. A hand-kept
list is how a new transform becomes invisible, and a literal total is how the recipe fingerprint's
own coverage guard ended up unable to see a producer that had never been added.
"""

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pipeline.look import (
    cast_shadow,
    lake_depth,
    layer_producers,
    mars_ice,
    palette,
    seaice,
    sky_view,
    snow,
)

BASELINE = Path(__file__).resolve().parents[1] / "tests" / "curve_fingerprint.json"

#: The one spelling of how to regenerate, because the test's failure message ends with it.
REGENERATE = "uv run python -m scripts.curve_fingerprint --write"

#: Decimal places kept per sample. Nine sits three orders of magnitude above float noise and six
#: below the smallest curve change worth reporting, and `test_curve_fingerprint` pins both ends of
#: that margin so a tightening cannot quietly start flaking across platforms.
DIGITS = 9

#: The unit sweep every 0..1 transform is read on. Nine points, so both quarter points are sampled:
#: a smoothstep and a straight line agree exactly at the ends and the midpoint, so a coarser sweep
#: reports no change on the one substitution this file exists to catch.
UNIT = np.linspace(0.0, 1.0, 9)

#: A Mercator span and grid height standing in for a planet raster, and an elevation sweep spanning
#: both ramps. Arbitrary but fixed: what matters is that every run reads the same domain.
MERCATOR_TOP = 8_000_000.0
MERCATOR_BOTTOM = -8_000_000.0
GRID_ROWS = 9
ELEVATIONS = np.linspace(-8000.0, 6000.0, 9)
GROUND_M_PER_PX = (30.0, 150.0, 300.0, 600.0)

EARTH_LOOK = palette.look_for("earth")
WHITE_LAYERS = sorted(layer.name for layer in layer_producers.WHITE_UNION)


@dataclass(frozen=True)
class Sample:
    """One committed row, and the function whose arithmetic it reads.

    `covers` is a `module.function` name in `pipeline/look/`, so the registry guard can compare the
    two sides against the source. Several rows may cover one function where it takes a mode.
    """

    covers: str
    values: Callable[[], Any]


def _ramp(stops: list[tuple[float, tuple[float, float, float]]]) -> list[float]:
    return [channel for position in UNIT for channel in palette.ramp_color(float(position), stops)]


def _grid(row: np.ndarray) -> np.ndarray:
    """`row` repeated into a square, so a transform wanting two dimensions gets one built from the
    same sweep. Square rather than `GRID_ROWS` tall: a fixed height drifts away from the sweep's
    length and the mismatch surfaces as a broadcast error inside a producer, which reads as the
    transform being broken rather than the domain being wrong."""
    return np.tile(row, (row.size, 1))


def _relief(heights: np.ndarray) -> np.ndarray:
    return np.outer(np.arange(float(heights.size)), heights)


SAMPLES: dict[str, Sample] = {
    "cast_shadow.shadow_reach_px": Sample(
        "cast_shadow.shadow_reach_px",
        lambda: [cast_shadow.shadow_reach_px(8000.0, 15.0, metres, 12.0)
                 for metres in GROUND_M_PER_PX]),

    "lake_depth.lake_position:log1p": Sample(
        "lake_depth.lake_position", lambda: lake_depth.lake_position(UNIT * 1000.0, "log1p")),
    "lake_depth.lake_position:sqrt": Sample(
        "lake_depth.lake_position", lambda: lake_depth.lake_position(UNIT * 1000.0, "sqrt")),
    "lake_depth.lake_position:linear": Sample(
        "lake_depth.lake_position", lambda: lake_depth.lake_position(UNIT * 1000.0, "linear")),
    "lake_depth.lakes_only": Sample(
        "lake_depth.lakes_only",
        lambda: lake_depth.lakes_only(UNIT * 100.0, np.arange(UNIT.size) % 4)),
    "lake_depth.inland_water": Sample(
        "lake_depth.inland_water", lambda: lake_depth.inland_water(np.arange(UNIT.size) % 4)),

    "layer_producers.fold_white": Sample(
        "layer_producers.fold_white",
        lambda: layer_producers.fold_white(
            {name: _grid(UNIT).astype("float32") * weight
             for weight, name in enumerate(WHITE_LAYERS, start=1)},
            (UNIT.size, UNIT.size), exclusions={})[0]),

    "mars_ice.luma": Sample(
        "mars_ice.luma",
        lambda: mars_ice.luma(np.stack([UNIT * 255.0, UNIT * 128.0, UNIT * 64.0]))),
    "mars_ice.albedo_alpha": Sample(
        "mars_ice.albedo_alpha",
        lambda: mars_ice.albedo_alpha(UNIT * 255.0, (60.0, 200.0), -9999.0)),
    "mars_ice.graded_alpha": Sample(
        "mars_ice.graded_alpha",
        lambda: mars_ice.graded_alpha(_grid(UNIT * 255.0),
                                      np.ones(UNIT.size, dtype=bool), -9999.0)),
    "mars_ice.feather_alpha": Sample(
        "mars_ice.feather_alpha",
        lambda: mars_ice.feather_alpha(np.eye(16, dtype=bool), 200.0, 5.0)),
    "mars_ice.extent_for": Sample(
        "mars_ice.extent_for",
        lambda: mars_ice.extent_for({unit: np.eye(8, dtype=bool) for unit in mars_ice.NORTH_UNITS},
                                    True)),
    "mars_ice.unit_latitude_span": Sample(
        "mars_ice.unit_latitude_span",
        lambda: [degrees for unit in mars_ice.NORTH_UNITS
                 for degrees in (mars_ice.unit_latitude_span(unit, True) or (0.0, 0.0))]),
    "mars_ice.ice_bands": Sample(
        "mars_ice.ice_bands",
        lambda: [value for row0, row1, northern in
                 mars_ice.ice_bands((-20037508.34, -20037508.34, 20037508.34, 20037508.34), 512, 8)
                 for value in (row0, row1, float(northern))]),

    #: Mapped rather than passed the sweep: `smoothstep` is annotated for a scalar, and it is the
    #: ramp's easing rather than an array kernel, so the sample reads it the way its callers do.
    "palette.smoothstep": Sample(
        "palette.smoothstep", lambda: [palette.smoothstep(float(value)) for value in UNIT]),
    "palette.lin2srgb": Sample(
        "palette.lin2srgb", lambda: [palette.lin2srgb(float(value)) for value in UNIT]),
    "palette.srgb8_to_linear": Sample(
        "palette.srgb8_to_linear",
        lambda: [channel for level in (0, 64, 128, 192, 255)
                 for channel in palette.srgb8_to_linear((level, level // 2, 255 - level))]),
    "palette.ramp_color:land": Sample(
        "palette.ramp_color", lambda: _ramp(palette.LAND_STOPS)),
    "palette.ramp_color:sea": Sample(
        "palette.ramp_color", lambda: _ramp(palette.SEA_STOPS)),
    "palette.ramp_color:lake": Sample(
        "palette.ramp_color", lambda: _ramp(palette.LAKE_STOPS)),
    "palette.ramp_color:mars_land": Sample(
        "palette.ramp_color", lambda: _ramp(palette.MARS_LAND_STOPS)),
    "palette.lake_lut": Sample(
        "palette.lake_lut",
        lambda: [channel for colour in palette.lake_lut(16) for channel in colour]),
    "palette.relief_lut": Sample(
        "palette.relief_lut", lambda: palette.relief_lut("land", look=EARTH_LOOK, step=250.0)),
    "palette.lut_index": Sample(
        "palette.lut_index",
        lambda: palette.lut_index("land", ELEVATIONS, look=EARTH_LOOK, step=250.0)),
    "palette.lut_lookup": Sample(
        "palette.lut_lookup",
        lambda: palette.lut_lookup(palette.relief_lut("land", look=EARTH_LOOK, step=250.0),
                                   "land", ELEVATIONS, look=EARTH_LOOK, step=250.0)),
    "palette.color_relief_rows": Sample(
        "palette.color_relief_rows",
        lambda: [value for elevation, colour in
                 palette.color_relief_rows("land", look=EARTH_LOOK, step=500.0)
                 for value in (elevation, *colour)]),

    "seaice.unpack_seaice": Sample(
        "seaice.unpack_seaice", lambda: seaice.unpack_seaice((UNIT * 100.0).astype("float32"))),
    "seaice.ice_alpha": Sample("seaice.ice_alpha", lambda: seaice.ice_alpha(UNIT)),
    "seaice.gated_alpha": Sample(
        "seaice.gated_alpha",
        lambda: seaice.gated_alpha(UNIT, np.arange(UNIT.size) % 2 == 0)),

    "sky_view.occlusion_shape": Sample(
        "sky_view.occlusion_shape", lambda: sky_view.occlusion_shape(4096, 2048, 300.0)),
    "sky_view.normalised_occlusion": Sample(
        "sky_view.normalised_occlusion", lambda: sky_view.normalised_occlusion(_grid(UNIT), 300.0)),
    "sky_view.horizon_svf": Sample(
        "sky_view.horizon_svf", lambda: sky_view.horizon_svf(_relief(ELEVATIONS), 300.0)),

    "snow.unpack_persistence": Sample(
        "snow.unpack_persistence",
        lambda: snow.unpack_persistence((UNIT * 100.0).astype("float32"))),
    "snow.latitude_per_row": Sample(
        "snow.latitude_per_row",
        lambda: snow.latitude_per_row(MERCATOR_TOP, MERCATOR_BOTTOM, GRID_ROWS)),
    "snow.ramp_thresholds": Sample(
        "snow.ramp_thresholds", lambda: np.asarray(snow.ramp_thresholds(UNIT * 90.0)).ravel()),
    "snow.snow_alpha": Sample(
        "snow.snow_alpha",
        lambda: snow.snow_alpha(_grid(UNIT), MERCATOR_TOP, MERCATOR_BOTTOM)),
    "snow.source_cell_sigma_px": Sample(
        "snow.source_cell_sigma_px",
        lambda: [snow.source_cell_sigma_px(metres) for metres in GROUND_M_PER_PX]),
    "snow.soften_source_cells": Sample(
        "snow.soften_source_cells",
        lambda: snow.soften_source_cells(_grid(UNIT).astype("float32"), 300.0)),
    "snow.antarctic_snow_mask": Sample(
        "snow.antarctic_snow_mask",
        lambda: snow.antarctic_snow_mask(np.ones(UNIT.size, dtype=bool),
                                         np.linspace(-80.0, -50.0, UNIT.size))),
}

#: Public functions in `pipeline/look/` with no curve to sample, each with the reason it has none.
#: An I/O wrapper is excluded because its arithmetic lives in a function that is sampled, or in the
#: external tool it shells out to; a registry lookup because its answer is a constant the recipe
#: fingerprint already records.
EXCLUDED: dict[str, str] = {
    "lake_depth.warp_depth": "gdalwarp, no arithmetic of its own",
    "lake_depth.warp_depth_raster": "gdalwarp, no arithmetic of its own",

    "layer_producers.producer_for": "registry lookup",
    "layer_producers.producers_for": "registry lookup",
    "layer_producers.constants_for": "returns recorded constants, covered by the recipe fingerprint",
    "layer_producers.white_law": "registry lookup",
    "layer_producers.gather": "dispatches to producers over a window of real rasters",

    "mars_ice.burn_unit": "rasterises a gazetteer polygon through GDAL",
    "mars_ice.feather_alpha_bands": "the banded wrapper of `feather_alpha`, which is sampled",
    "mars_ice.build_alpha_raster": "writes a raster",

    "palette.look_for": "registry lookup",
    "palette.surface": "registry lookup",
    "palette.color_relief_text": "formats `color_relief_rows`, which is sampled",

    "perennial_ice.cap_ice": "registry lookup",

    "seaice.seaice_src": "path resolution",
    "seaice.ice_paint": "returns recorded constants, covered by the recipe fingerprint",
    "seaice.warp_seaice": "gdalwarp",
    "seaice.warp_seaice_raster": "gdalwarp",

    "sky_view.main": "command line entry point",

    "snow.persistence_nc": "path resolution",
    "snow.warp_persistence_raster": "gdalwarp",
    "snow.rasterize_glaciers_raster": "gdal_rasterize",
    "snow.rasterize_antarctic_rock": "gdal_rasterize",

    "viking_luma.work_dir": "path resolution",
    "viking_luma.luma_path": "path resolution",
    "viking_luma.recipe_path": "path resolution",
    "viking_luma.degrees_vrt": "builds a VRT",
    "viking_luma.build": "reads the mosaic",
    "viking_luma.build_recipe": "returns recorded constants, covered by the recipe fingerprint",
    "viking_luma.recorded_recipe": "reads the sidecar",
    "viking_luma.is_fresh": "compares the sidecar",
    "viking_luma.build_parser": "command line entry point",
    "viking_luma.main": "command line entry point",
}


def fingerprint() -> dict[str, list[float]]:
    """Every sample, rounded to `DIGITS` and keyed by row name, ordered for a readable diff."""
    rows: dict[str, list[float]] = {}
    for name, sample in SAMPLES.items():
        values = np.asarray(sample.values(), dtype=np.float64).ravel()
        rows[name] = [round(float(value), DIGITS) for value in values]
    return dict(sorted(rows.items()))


def serialise(rows: dict[str, list[float]]) -> str:
    """Stable bytes: sorted keys, one row per line, and a trailing newline."""
    body = ",\n".join(f'  {json.dumps(name)}: {json.dumps(values)}' for name, values in rows.items())
    return "{\n" + body + "\n}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true",
                        help=f"regenerate tests/{BASELINE.name} instead of printing")
    args = parser.parse_args(argv)
    text = serialise(fingerprint())
    if not args.write:
        print(text, end="")
        return 0
    unchanged = BASELINE.exists() and BASELINE.read_text(encoding="utf-8") == text
    BASELINE.write_text(text, encoding="utf-8")
    print(f"tests/{BASELINE.name}: "
          f"{'unchanged' if unchanged else 'rewritten, commit it with this change'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
